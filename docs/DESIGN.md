# deepseek-item-test v0.1 技术设计

> 状态：定稿 | 负责人：架构师 | 依据：`docs/PRD.md`（2026-11-21）
> 本文档只定技术方案；行为以 PRD 为准，PRD 未写死的输出文案由本文档定稿。

## 1. 结论（TL;DR）

- **单文件实现** `item.py`（约 300 行），零第三方依赖，只用 Python 3.11 标准库。
- **手写参数解析**，不用 `argparse`：argparse 的错误信息不带 `错误:` 前缀且默认退出码 2，与 PRD F6 冲突；命令面只有 4 条，手写更可控、更好测。
- **数据层与命令层分离**：`resolve_data_path / load_data / save_data` + 纯函数 `add_item / mark_done / remove_item / format_list`，命令函数只做解析与输出。
- **原子写入**：同目录 `tempfile.mkstemp` → `json.dump` → `flush+fsync` → `os.replace`；失败清理临时文件，原文件不动。
- **测试**：`unittest`，主用进程内调 `main()`（快、能断言"文件字节不变"），另设 3 个子进程冒烟用例验证真实入口与退出码。

## 2. 技术选型与约束

| 项 | 决定 | 理由 |
|---|---|---|
| 语言 | Python 3.11 | PRD 硬性要求 |
| 依赖 | 无 | 零依赖 |
| 运行方式 | `python item.py <cmd>`（仓库根目录） | 不打包、不安装 |
| 参数解析 | 手写 | 控制错误格式/退出码，见 §1 |
| 数据格式 | JSON（UTF-8，indent=2） | 人工可读、可 diff |
| 测试框架 | `unittest` | 标准库，`python -m unittest` 直接跑 |
| 目录 | 平铺：`item.py` + `tests/` | 单文件 PRD，避免过度设计 |

仅使用：`sys`、`os`、`json`、`re`、`tempfile`、`pathlib`、`datetime`；测试再加 `unittest`、`subprocess`、`contextlib`、`io`、`unittest.mock`。

## 3. 目录结构

```
deepseek-item-test/
├── item.py                 # 全部实现（入口 + 数据层 + 命令）
├── tests/
│   ├── __init__.py         # 空文件，保证 `python -m unittest` 能发现
│   └── test_item.py        # 全部测试
├── docs/
│   ├── PRD.md              # 产品经理产出
│   └── DESIGN.md           # 本文档
├── README.md               # 中文用法（开发任务 T4）
└── .gitignore              # __pycache__/、*.py[cod]、*.tmp
```

不建 `src/`、不建包：`item.py` 就是模块，`tests` 里 `import item` 即可（从仓库根跑测试时根目录在 `sys.path`）。

## 4. 模块划分（`item.py` 内部分区）

| 区块 | 内容 | 说明 |
|---|---|---|
| 常量 | `USAGE`、`DATA_VERSION = 1`、`DEFAULT_FILENAME = ".item.json"`、`DUE_RE` | 文案集中，测试可引用 |
| 异常 | `ItemError`、`UsageError(ItemError)` | `UsageError` 额外打印用法 |
| 数据路径 | `resolve_data_path(environ=None, home=None)` | 注入参数便于单测，不 mock 环境 |
| 读写 | `load_data(path)`、`save_data(path, data)`、`normalize_data(raw, path)` | 所有结构校验集中在此 |
| 领域纯函数 | `new_empty_data()`、`find_item(data, item_id)`、`add_item(data, text, due)`、`mark_done(data, item_id)`、`remove_item(data, item_id)`、`format_list(data)` | 不碰文件、不碰 stdout，方便单测 |
| 参数解析 | `parse_id(s)`、`parse_due(s)`、`parse_add_args(argv)`、`parse_id_args(argv)` | 只解析，不做 I/O |
| 命令 | `cmd_add / cmd_list / cmd_done / cmd_rm` | 解析 → 读 → 改 → 写 → 输出 |
| 入口 | `_force_utf8_stdio()`、`main(argv=None) -> int`、`run(argv)` | 先修正标准流编码，再顶层捕获异常、统一错误格式 |

依赖方向单向：`入口 → 命令 → 领域 → 读写`，反向禁止。

## 5. 数据模型与 JSON Schema 定稿

### 5.1 文件示例

```json
{
  "version": 1,
  "next_id": 3,
  "items": [
    {"id": 1, "text": "买牛奶", "done": false, "due": "2026-11-25"},
    {"id": 2, "text": "写周报", "done": true, "due": null}
  ]
}
```

字段顺序固定为 `version, next_id, items`；条目内为 `id, text, done, due`。文件末尾一个换行。`ensure_ascii=False`（中文可读），`indent=2`。

### 5.2 字段规则

| 字段 | 类型 | 规则 |
|---|---|---|
| `version` | int | 存在时必须为 `1`，其他值 → 数据损坏；缺失按 1 容错 |
| `next_id` | int | ≥1；**分配 id 的唯一来源**，只增不减。缺失时按 `max(现有 id)+1` 补；非 int → 损坏 |
| `items` | list | 必须存在且为数组，否则损坏 |
| `items[].id` | int | `1 ≤ id`，布尔值不算 int；重复 id → 损坏 |
| `items[].text` | str | 非空（`strip()` 后），否则损坏 |
| `items[].done` | bool | 缺失按 `false`；非 bool → 损坏 |
| `items[].due` | str \| null | 缺失按 `null`；存在时必须是合法 `YYYY-MM-DD`，否则损坏 |

未知字段忽略（向前兼容），但写回时不保留。

### 5.3 关键语义

- **id 删除后不复用**：`add` 取 `next_id`，写入后 `next_id += 1`；删除条目不回退 `next_id`。加载时归一化 `next_id = max(文件 next_id, max(items.id)+1, 1)`，手改文件导致回退也能纠正。
- **损坏判定与容错**：`items` 缺失、单条缺 `id`/`text`、类型错误 → 报错；`done`/`due` 缺失 → 容错补默认值（PRD §6）。
- **空文件（0 字节）**：不是合法 JSON → 按损坏报错，不当空清单。
- **文件不存在**：返回空数据 `{version:1, next_id:1, items:[]}`，不创建文件（首次 `add` 才落盘）。
- **只读命令**（`list`）绝不写文件。

## 6. CLI 契约

### 6.1 用法

```
用法:
  python item.py add <内容> [--due YYYY-MM-DD]
  python item.py list
  python item.py done <id>
  python item.py rm <id>
  python item.py --help
```

`-h` / `--help` 仅作为**第一个**参数识别：用法写 stdout，退出码 0（忽略其后的多余参数）。不带参数 → 用法写 stderr，退出码 1。

### 6.2 参数解析规则

**add**
- 内容为**单个参数**，含空格/中文/emoji 时用户自行加引号；两个位置参数 → `参数过多`。
- `--due DATE` 只支持空格分隔形式；重复出现 → `重复指定 --due`。
- 支持 `--` 结束选项：`python item.py add -- "-开头的文本"`，`--` 后必须恰好一个内容参数。
- 未知 `-` 开头参数 → `未知参数 "--foo"`。
- 缺内容 → `缺少待办内容`（用法错误，打用法）。

**done / rm**
- 恰好一个 id 参数；缺 → `缺少 id 参数`（打用法）；多 → `参数过多`（打用法）。
- id 必须匹配 `[1-9]\d*`，否则 `非法 id "abc"`（不打用法）。

**日期**
- 必须匹配 `\d{4}-\d{2}-\d{2}` 且 `date.fromisoformat` 能解析（拒绝 `2026-02-30`）；错误信息 `非法日期 "..."（格式 YYYY-MM-DD）` / `（不是真实存在的日期）`，不打用法。

### 6.3 输出与退出码

| 命令 | 成功 stdout | 退出码 | 失败 |
|---|---|---|---|
| `add` | 仅新 id，如 `3` | 0 | stderr，1，文件不变 |
| `list` | 每行 `<id> [ ] <内容>` 或 `<id> [x] <内容>`，有 due 追加 ` due:YYYY-MM-DD`，按 id 升序；空清单输出 `暂无待办` | 0 | stderr，1 |
| `done` | `已完成: <id>`（已完成的 id 也输出这句，且不写文件） | 0 | stderr，1，文件不变 |
| `rm` | `已删除: <id>` | 0 | stderr，1，文件不变 |
| `-h/--help` | 用法 | 0 | — |
| 未知子命令 | — | — | `错误: 未知命令 "xxx"` + 用法，stderr，1 |

所有错误统一 `错误: ` 前缀，退出码 1（PRD §7 已定）。`KeyboardInterrupt` → `错误: 已中断`，退出码 130。其余未捕获异常由顶层兜底为 `错误: 内部错误: ...`，退出码 1（不向用户抛 traceback）。

### 6.4 错误文案（测试按此断言）

| 场景 | 文案（不含 `错误: ` 前缀） | 打用法 |
|---|---|---|
| 缺子命令 / 未知子命令 | `缺少命令` / `未知命令 "x"` | 是 |
| 缺内容 / 内容全空白 | `缺少待办内容`（用法错误） / `待办内容不能为空`（值错误） | 前是后否 |
| 参数过多 | `参数过多` | 是 |
| 未知参数 | `未知参数 "--x"` | 是 |
| `--due` 缺值 / 重复 | `--due 需要一个日期参数` / `重复指定 --due` | 是 |
| 非法日期 | `非法日期 "2026-02-30"（不是真实存在的日期）` | 否 |
| 缺 id / 非法 id | `缺少 id 参数` / `非法 id "abc"` | 前是后否 |
| id 不存在 | `id 不存在: 9` | 否 |
| JSON 损坏 | `数据文件损坏: <path>（不是合法 JSON: 第 N 行）` | 否 |
| 结构不符 | `数据文件损坏: <path>（<具体原因>）` | 否 |
| 非 UTF-8 | `数据文件无法读取: <path>（不是 UTF-8 文本）` | 否 |
| 读/写失败 | `无法读取数据文件: <path>（<系统错误>）` / `无法写入数据文件: <path>（<系统错误>）` | 否 |

## 7. 关键流程

### 7.1 add

```
main → _force_utf8_stdio() → parse_add_args → load_data(path) → add_item(data, text, due)
     → save_data(path, data) → print(new_id)
```
所有校验（内容、日期）在 `save_data` 之前完成，保证失败时文件不变。

### 7.2 done（幂等）

```
load → find_item → 若 done 已为 True：直接 print 确认，return 0（不写文件）
                 → 否则置 True → save → print
```

### 7.3 原子写入

1. `parent.is_dir()` 为假 → `无法写入数据文件: <path>（目录不存在）`（PRD：不自动建父目录）。
2. `tempfile.mkstemp(prefix=".item.json.", suffix=".tmp", dir=parent)`，与目标同目录，保证 `os.replace` 同卷。
3. 写入 → `flush` → `os.fsync` → 关闭。
4. `os.replace(tmp, path)` 原子替换。
5. 任一步 `OSError` → 删除临时文件（best-effort）→ `ItemError`；原文件保持原样。
6. 不 fsync 目录（Windows 不支持，收益低）。

### 7.4 标准流编码（实测确认的坑）

Windows 下 stdout 被管道/重定向时编码是 `gbk`（本机实测 `sys.stdout.encoding == "gbk"`），`print("🥛")` 直接抛 `UnicodeEncodeError`，会破坏「不向用户抛 traceback」。`python item.py list > todo.txt` 和 CI 捕获都属于这条真实路径。

方案：`main()` 第一步调用 `_force_utf8_stdio()`：

```python
def _force_utf8_stdio() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:      # 测试里的 StringIO 没有 reconfigure
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
```

- 本机已实测：管道下 reconfigure 后 `中文 🥛` 正常输出，退出码 0。
- 不加 `errors="replace"`：会静默丢字符，宁可让编码问题在测试中暴露。
- 控制台 tty 走 PEP 528 本来就是 UTF-8，reconfigure 无副作用。
- 副作用：重定向到文件时字节为 UTF-8（README 写明）。

### 7.5 错误处理链

命令/数据层只 `raise ItemError`（或 `UsageError`），`main` 统一转成 `错误: ...` 写 stderr 并返回 1；数据层不 `print`、不 `sys.exit`。

## 8. 测试组织

### 8.1 结构

```python
class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data.json"
        self.env = patch.dict(os.environ, {"ITEM_FILE": str(self.path)})

    def run_cli(self, *args) -> tuple[int, str, str]:   # 进程内，重定向 stdout/stderr
    def file_bytes(self) -> bytes | None:                # 断言"文件不变"
    def read_json(self) -> dict:
```

测试类：`TestDataLayer`、`TestAdd`、`TestList`、`TestDone`、`TestRm`、`TestPersistence`、`TestMain`、`TestCliSmoke`（子进程）。

### 8.2 用例矩阵（P0 全覆盖）

| 区域 | 必测 |
|---|---|
| add | 成功→只输出 id / 落盘可 re-load；空串、全空白；`--due` 合法/缺值/重复/非法格式/`2026-02-30`；内容含空格中文 emoji；`--` 分隔；未知参数；参数过多；删除后 id 不复用（add 1,2 → rm 2 → add 得 3） |
| list | 空清单 `暂无待办`；混合完成状态与 due 的行格式；按 id 升序（文件乱序也升序）；只读不改文件字节 |
| done | 成功置 `[x]`；重复执行幂等且文件字节不变；id 不存在/非整数/0/缺参/多参 |
| rm | 成功删除且其他 id 不变；重复删除报错；非法 id/缺参/多参 |
| 持久化 | 默认路径（注入 home 单测 `resolve_data_path`）；`ITEM_FILE` 覆盖（相对路径、含空格路径）；文件不存在按空处理；首次 add 创建文件；父目录不存在报错 |
| 损坏 | 非法 JSON、`items` 非数组、缺 `id`/`text`、`done` 非 bool、`due` 非法、重复 id、0 字节：均报错且**文件字节不变** |
| 原子性 | patch `item.os.replace` 抛 `OSError`：报错、原文件不变、目录无 `.tmp` 残留 |
| 入口 | 无参数→用法 stderr 退 1；`--help`→用法 stdout 退 0；未知命令→退 1 且带用法 |
| 编码 | 子进程**不设** `PYTHONUTF8/PYTHONIOENCODING`，`add` 含 emoji 后 `list`，管道捕获字节按 UTF-8 解码含 emoji、退 0；进程内 `redirect_stdout(StringIO)` 下 `_force_utf8_stdio()` 不报错 |
| 冒烟（子进程） | `--help`；add→list→done→rm 全链路；损坏文件报错退出 1；env 只加 `ITEM_FILE`（**不设** `PYTHONUTF8`，保留真实 gbk 管道路径），父进程 `encoding="utf-8"` 捕获 |

断言约定：错误用例同时断言 `退出码 == 1`、`stderr 以 "错误: " 开头`、`stdout == ""`、数据文件字节未变。

### 8.3 运行

```powershell
python -m unittest -v          # 全量
python -m unittest tests.test_item.TestAdd -v
```

测试禁用真实 `~/.item.json`：`setUp` 必须设置 `ITEM_FILE`。

## 9. 任务卡

依赖：T1 完成后再做 T2/T3；T2、T3 都改 `item.py` 和 `tests/test_item.py`，**串行执行**避免冲突；T4 最后。

| 卡 | 范围 | DoD | 验证 |
|---|---|---|---|
| **T1** 骨架 + 数据层 | `item.py`：常量、USAGE、`ItemError/UsageError`、`resolve_data_path`、`load_data`、`normalize_data`、`save_data`、`new_empty_data`；`tests/__init__.py`、`.gitignore` | 无 CLI 业务命令也能跑测试；结构校验按 §5.2；损坏文件不覆盖；写失败无残留、原文件不变 | `python -m unittest tests.test_item.TestDataLayer tests.test_item.TestPersistence -v` |
| **T2** add + list | `parse_due`、`parse_add_args`、`add_item`、`format_list`、`cmd_add`、`cmd_list`；对应测试 | PRD F1/F2 全部验收标准；add 失败文件不变；日期校验；空清单文案 | `python -m unittest tests.test_item.TestAdd tests.test_item.TestList -v` + 手工 5 条命令 |
| **T3** done + rm | `parse_id`、`find_item`、`mark_done`、`remove_item`、`cmd_done`、`cmd_rm`；对应测试 | PRD F3/F4；done 幂等不写文件；删除后 id 不复用 | `python -m unittest tests.test_item.TestDone tests.test_item.TestRm -v` |
| **T4** 入口 + 文档 | `_force_utf8_stdio`、`run`、`main`、未知命令/用法、`__main__`；`tests/test_item.py` 的 `TestMain/TestCliSmoke`；`README.md`（中文） | 无参/未知命令/`--help` 行为；emoji 管道用例；子进程冒烟 3 条；README 覆盖 PRD F7 并写明输出为 UTF-8 | `python -m unittest -v` 全绿 + `python item.py --help` |

完成定义（每卡通用）：命令能跑、测试全绿、无第三方 import、无 traceback 泄漏、错误文案与 §6.4 一致。

## 10. 约定、风险与明确不做

**约定**
- 输出文案（`已完成: <id>`、`已删除: <id>`、`暂无待办`）由本文档定稿，测试按此断言。
- `ITEM_FILE` 非空即生效；`~` 会展开；相对路径相对当前工作目录。
- 所有文件读写显式 `encoding="utf-8"`；JSON 写入带 `newline="\n"`。
- 标准输出统一 UTF-8（含管道/重定向），由 `_force_utf8_stdio()` 保证；README 写明。

**风险**
- git 身份：开发已设置 `user.name/user.email`，提交前用 `git config user.name` 复核。
- 控制台编码：已由 §7.4 解决；若个别终端显示乱码，用 `chcp 65001` 查看，不影响文件内容与退出码。
- 数据层与命令层同文件，评审时重点看边界是否越层（命令层不得直接 `open`/`json.load`）。

**明确不做（防过度设计）**
- 不用 `argparse`、不用 dataclass、不拆模块、不打包 exe、不加锁文件/并发控制、不做 `--json` 等 P1（P1 仅在 P0 全绿后可选）。
- 不引入任何第三方测试库。

**评审门禁**：开发与测试完成后，我按 7d-code-reviewer 技能做合并前评审（五步流程、三级分级、四维评分、文本摘要 + HTML 报告），有 🔴 不合并。
