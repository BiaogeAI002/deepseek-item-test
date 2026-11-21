"""item —— 零依赖的命令行待办清单（v0.1）。

分层：入口(main) -> 命令(cmd_*) -> 领域纯函数 -> 读写(load_data/save_data)。
数据文件为 UTF-8 JSON，写入走「临时文件 + os.replace」原子替换。
详见 docs/DESIGN.md。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

DATA_VERSION = 1
DEFAULT_FILENAME = ".item.json"
DUE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ID_RE = re.compile(r"[1-9]\d*")

USAGE = """用法:
  python item.py add <内容> [--due YYYY-MM-DD]
  python item.py list
  python item.py done <id>
  python item.py rm <id>
  python item.py --help
"""


class ItemError(Exception):
    """面向用户的错误；main() 统一转成 `错误: ...` 写 stderr。"""


class UsageError(ItemError):
    """参数用法错误；main() 额外打印用法。"""


# ---------------------------------------------------------------------------
# 数据路径
# ---------------------------------------------------------------------------


def resolve_data_path(environ=None, home=None) -> Path:
    """返回数据文件路径：ITEM_FILE 非空时优先，否则 ~/.item.json。"""
    env = os.environ if environ is None else environ
    raw = env.get("ITEM_FILE", "")
    if raw:
        return Path(raw).expanduser()
    base = Path(home) if home is not None else Path.home()
    return base / DEFAULT_FILENAME


# ---------------------------------------------------------------------------
# 领域纯函数（不碰文件、不碰 stdout）
# ---------------------------------------------------------------------------


def new_empty_data() -> dict:
    """空清单的初始数据。"""
    return {"version": DATA_VERSION, "next_id": 1, "items": []}


def _is_int(value) -> bool:
    """bool 是 int 的子类，这里必须排除。"""
    return isinstance(value, int) and not isinstance(value, bool)


def is_valid_due(value) -> bool:
    """是否为合法的 YYYY-MM-DD 真实日期。"""
    if not isinstance(value, str) or DUE_RE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def add_item(data: dict, text: str, due=None) -> int:
    """新增一条待办，返回新 id；失败抛 ItemError 且不改动 data。"""
    text = text.strip()
    if not text:
        raise ItemError("待办内容不能为空")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ItemError("待办内容包含无法编码的字符") from exc
    if due is not None and not is_valid_due(due):
        raise ItemError(f'非法日期 "{due}"（格式 YYYY-MM-DD）')

    item_id = data["next_id"]
    data["items"].append(
        {"id": item_id, "text": text, "done": False, "due": due}
    )
    data["next_id"] = item_id + 1
    return item_id


def format_list(data: dict) -> str:
    """list 命令的完整输出；空清单返回「暂无待办」。"""
    items = sorted(data["items"], key=lambda entry: entry["id"])
    if not items:
        return "暂无待办"
    lines = []
    for entry in items:
        mark = "x" if entry["done"] else " "
        line = f'{entry["id"]} [{mark}] {entry["text"]}'
        if entry["due"]:
            line += f' due:{entry["due"]}'
        lines.append(line)
    return "\n".join(lines)


def find_item(data: dict, item_id: int) -> dict:
    """按 id 找条目；不存在抛 ItemError。"""
    for entry in data["items"]:
        if entry["id"] == item_id:
            return entry
    raise ItemError(f"id 不存在: {item_id}")


def mark_done(data: dict, item_id: int) -> bool:
    """标记完成；返回是否真的发生改动（幂等：已完成返回 False）。"""
    entry = find_item(data, item_id)
    if entry["done"]:
        return False
    entry["done"] = True
    return True


def remove_item(data: dict, item_id: int) -> None:
    """删除条目；next_id 不回退，保证 id 不复用。"""
    entry = find_item(data, item_id)
    data["items"].remove(entry)


# ---------------------------------------------------------------------------
# 读取 / 校验 / 写入
# ---------------------------------------------------------------------------


def _corrupt(path: Path, reason: str) -> ItemError:
    return ItemError(f"数据文件损坏: {path}（{reason}）")


def load_data(path) -> dict:
    """读取并归一化数据文件；文件不存在按空清单处理。"""
    path = Path(path)
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        return new_empty_data()
    except OSError as exc:
        raise ItemError(
            f"无法读取数据文件: {path}（{exc.strerror or exc}）"
        ) from exc

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ItemError(
            f"数据文件无法读取: {path}（不是 UTF-8 文本）"
        ) from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _corrupt(path, f"不是合法 JSON: 第 {exc.lineno} 行") from exc

    return normalize_data(raw, path)


def normalize_data(raw, path) -> dict:
    """校验并归一化 JSON 结构；结构不符抛 ItemError。"""
    path = Path(path)

    if not isinstance(raw, dict):
        raise _corrupt(path, "顶层结构必须是 JSON 对象")

    version = raw.get("version", DATA_VERSION)
    if not _is_int(version) or version != DATA_VERSION:
        raise _corrupt(path, f"version 字段必须为 {DATA_VERSION}")

    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        raise _corrupt(path, "items 字段缺失或不是数组")

    items = []
    seen_ids = set()
    for index, entry in enumerate(items_raw):
        if not isinstance(entry, dict):
            raise _corrupt(path, f"items[{index}] 必须是 JSON 对象")

        item_id = entry.get("id")
        if not _is_int(item_id) or item_id < 1:
            raise _corrupt(path, f"items[{index}].id 必须是 >= 1 的整数")
        if item_id in seen_ids:
            raise _corrupt(path, f"items[{index}].id 重复: {item_id}")
        seen_ids.add(item_id)

        text_value = entry.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise _corrupt(path, f"items[{index}].text 必须是非空字符串")
        try:
            text_value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _corrupt(
                path, f"items[{index}].text 包含无法编码的字符（孤立代理项）"
            ) from exc

        done = entry.get("done", False)
        if not isinstance(done, bool):
            raise _corrupt(path, f"items[{index}].done 必须是布尔值")

        due = entry.get("due", None)
        if due is not None and not is_valid_due(due):
            raise _corrupt(path, f"items[{index}].due 必须是 YYYY-MM-DD 或 null")

        items.append({"id": item_id, "text": text_value, "done": done, "due": due})

    max_id = max((item["id"] for item in items), default=0)
    next_id = raw.get("next_id")
    if next_id is None:
        next_id = max_id + 1
    elif not _is_int(next_id) or next_id < 1:
        raise _corrupt(path, "next_id 必须是 >= 1 的整数")
    next_id = max(next_id, max_id + 1, 1)

    return {"version": DATA_VERSION, "next_id": next_id, "items": items}


def save_data(path, data) -> None:
    """原子写入：同目录临时文件 -> fsync -> os.replace；失败不动原文件。"""
    path = Path(path)
    parent = path.parent if str(path.parent) else Path(".")
    if not parent.is_dir():
        raise ItemError(f"无法写入数据文件: {path}（目录不存在）")

    fd = -1
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as exc:
        raise ItemError(
            f"无法写入数据文件: {path}（{exc.strerror or exc}）"
        ) from exc
    finally:
        if fd != -1:
            os.close(fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def parse_due(value: str) -> str:
    """校验 YYYY-MM-DD 日期字符串，返回原值；非法抛 ItemError。"""
    if DUE_RE.fullmatch(value) is None:
        raise ItemError(f'非法日期 "{value}"（格式 YYYY-MM-DD）')
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ItemError(f'非法日期 "{value}"（不是真实存在的日期）') from exc
    return value


def parse_id(value: str) -> int:
    """解析条目 id：必须是正整数字面量，否则抛 ItemError。"""
    if ID_RE.fullmatch(value) is None:
        raise ItemError(f'非法 id "{value}"')
    return int(value)


def parse_id_args(argv) -> int:
    """done / rm 的参数解析：恰好一个 id。"""
    args = list(argv)
    if not args:
        raise UsageError("缺少 id 参数")
    if len(args) > 1:
        raise UsageError("参数过多")
    return parse_id(args[0])


def parse_add_args(argv) -> tuple[str, str | None]:
    """解析 `add` 的参数（不含子命令本身）。"""
    args = list(argv)
    text = None
    due = None
    due_seen = False
    positional_only = False
    index = 0
    while index < len(args):
        arg = args[index]
        if not positional_only and arg == "--":
            positional_only = True
            index += 1
            continue
        if not positional_only and arg == "--due":
            if due_seen:
                raise UsageError("重复指定 --due")
            if index + 1 >= len(args):
                raise UsageError("--due 需要一个日期参数")
            due = parse_due(args[index + 1])
            due_seen = True
            index += 2
            continue
        if not positional_only and arg.startswith("-") and arg != "-":
            raise UsageError(f'未知参数 "{arg}"')
        if text is not None:
            raise UsageError("参数过多")
        text = arg
        index += 1

    if text is None:
        raise UsageError("缺少待办内容")
    return text, due


# ---------------------------------------------------------------------------
# 命令（解析 -> 读 -> 改 -> 写 -> 返回输出文本）
# ---------------------------------------------------------------------------


def cmd_add(argv) -> str:
    text, due = parse_add_args(argv)
    path = resolve_data_path()
    data = load_data(path)
    new_id = add_item(data, text, due)
    save_data(path, data)
    return str(new_id)


def cmd_list(argv) -> str:
    if argv:
        raise UsageError("参数过多")
    return format_list(load_data(resolve_data_path()))


def cmd_done(argv) -> str:
    item_id = parse_id_args(argv)
    path = resolve_data_path()
    data = load_data(path)
    if mark_done(data, item_id):
        save_data(path, data)
    return f"已完成: {item_id}"


def cmd_rm(argv) -> str:
    item_id = parse_id_args(argv)
    path = resolve_data_path()
    data = load_data(path)
    remove_item(data, item_id)
    save_data(path, data)
    return f"已删除: {item_id}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def run(argv) -> str:
    """执行一条命令，返回要写到 stdout 的文本；错误抛 ItemError。"""
    argv = list(argv)
    if not argv:
        raise UsageError("缺少命令")

    command, rest = argv[0], argv[1:]
    if command in ("-h", "--help"):
        return USAGE.rstrip("\n")
    if command == "add":
        return cmd_add(rest)
    if command == "list":
        return cmd_list(rest)
    if command == "done":
        return cmd_done(rest)
    if command == "rm":
        return cmd_rm(rest)
    raise UsageError(f'未知命令 "{command}"')


def _force_utf8_stdio() -> None:
    """把真实 stdout/stderr 固定为 UTF-8（设计 §7.4）。

    Windows 下 stdout 被管道/重定向时编码是 locale（gbk），输出 emoji 会抛
    UnicodeEncodeError，破坏「不向用户抛 traceback」。测试里的 StringIO
    没有 reconfigure，自动跳过。不加 errors="replace"：宁可暴露编码问题。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _discard_stdout() -> None:
    """输出流已断开时丢弃缓冲区，避免解释器退出阶段 flush 再报错。"""
    old = sys.stdout
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except OSError:
        return
    try:
        old.close()  # 冲刷旧缓冲，失败也一并吞掉
    except (OSError, ValueError):
        pass


def main(argv=None) -> int:
    """CLI 入口：所有异常在此转成 `错误: ...` 写 stderr，返回退出码。"""
    _force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        output = run(argv)
        if output:
            print(output)
            sys.stdout.flush()
    except UsageError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        print(USAGE, file=sys.stderr, end="")
        return 1
    except KeyboardInterrupt:
        print("错误: 已中断", file=sys.stderr)
        return 130
    except BrokenPipeError:
        _discard_stdout()
        print("错误: 输出已关闭", file=sys.stderr)
        return 1
    except UnicodeEncodeError:
        print("错误: 输出编码失败（内容包含无法编码的字符）", file=sys.stderr)
        return 1
    except ItemError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except OSError:
        # Windows 下写已关闭的管道是 OSError(22) 而不是 BrokenPipeError，
        # 输出阶段能到这儿的 OSError 只可能是输出流本身不可写。
        _discard_stdout()
        print("错误: 输出已关闭", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，不向用户抛 traceback
        print(f"错误: 内部错误: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
