"""独立黑盒验收脚本（不依赖 tests/ 内部实现，只通过子进程调 `python item.py`）。

运行：python verify/acceptance.py -v
约定：所有用例用临时目录 + ITEM_FILE，绝不读写真实 ~/.item.json；
      子进程不设置 PYTHONUTF8 / PYTHONIOENCODING，保留真实 gbk 管道路径。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEM = ROOT / "item.py"
PY = sys.executable


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "data.json"
        self.base_env = os.environ.copy()
        self.base_env.pop("PYTHONUTF8", None)
        self.base_env.pop("PYTHONIOENCODING", None)
        self.base_env["ITEM_FILE"] = str(self.path)

    # -- helpers ------------------------------------------------------------
    def run_cli(self, *args, env=None, cwd=None, timeout=60):
        result = subprocess.run(
            [PY, str(ITEM), *args],
            capture_output=True,
            cwd=str(cwd or ROOT),
            env=env or self.base_env,
            timeout=timeout,
        )
        # Windows 下 Python 文本流把 \n 转成 \r\n（标准行为，平台差异，非缺陷）；
        # 断言前归一化行尾，字节级 UTF-8 校验仍在（含下方 emoji 原始字节用例）。
        out = result.stdout.decode("utf-8").replace("\r\n", "\n")
        err = result.stderr.decode("utf-8").replace("\r\n", "\n")
        self.assertNotIn("\ufffd", out, f"stdout 含替换符: {out!r}")
        self.assertNotIn("\ufffd", err, f"stderr 含替换符: {err!r}")
        return result.returncode, out, err

    def write_raw(self, content):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.path.write_bytes(content)

    def write_json(self, data):
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def file_bytes(self):
        return self.path.read_bytes() if self.path.exists() else None

    def read_json(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def tmp_names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def assert_error(self, args, part, usage=None, env=None, cwd=None):
        before = self.file_bytes()
        code, out, err = self.run_cli(*args, env=env, cwd=cwd)
        self.assertEqual(code, 1, f"{args} 退出码: {code}, stderr={err}")
        self.assertEqual(out, "", f"{args} stdout 应为空")
        self.assertTrue(err.startswith("错误: "), f"{args} stderr 未以错误: 开头: {err!r}")
        self.assertIn(part, err)
        self.assertNotIn("Traceback", err)
        if usage is True:
            self.assertIn("用法:", err)
        elif usage is False:
            self.assertNotIn("用法:", err)
        self.assertEqual(self.file_bytes(), before, f"{args} 失败后文件字节变了")
        return err


# ---------------------------------------------------------------------------
# F1 add
# ---------------------------------------------------------------------------
class TestAdd(Base):
    def test_add_outputs_only_id_and_persists(self):
        code, out, err = self.run_cli("add", "买牛奶")
        self.assertEqual((code, out, err), (0, "1\n", ""))
        data = self.read_json()
        self.assertEqual(data["next_id"], 2)
        self.assertEqual(
            data["items"], [{"id": 1, "text": "买牛奶", "done": False, "due": None}]
        )

    def test_add_increments_and_never_reuses_deleted_id(self):
        self.assertEqual(self.run_cli("add", "A")[1], "1\n")
        self.assertEqual(self.run_cli("add", "B")[1], "2\n")
        self.assertEqual(self.run_cli("rm", "2")[0], 0)
        code, out, err = self.run_cli("add", "C")
        self.assertEqual((code, out, err), (0, "3\n", ""))
        self.assertEqual([i["id"] for i in self.read_json()["items"]], [1, 3])
        self.assertGreaterEqual(self.read_json()["next_id"], 4)

    def test_add_trims_outer_whitespace_only(self):
        self.run_cli("add", "  写 周报  ")
        self.assertEqual(self.read_json()["items"][0]["text"], "写 周报")

    def test_add_roundtrips_spaces_chinese_emoji(self):
        text = "买 牛奶 🥛 for 妈妈"
        self.assertEqual(self.run_cli("add", text)[0], 0)
        self.assertEqual(self.read_json()["items"][0]["text"], text)
        code, out, _ = self.run_cli("list")
        self.assertEqual((code, out), (0, f"1 [ ] {text}\n"))

    def test_add_due_persists_and_lists(self):
        self.assertEqual(self.run_cli("add", "开会", "--due", "2026-11-25")[0], 0)
        self.assertEqual(self.read_json()["items"][0]["due"], "2026-11-25")
        self.assertEqual(self.run_cli("list")[1], "1 [ ] 开会 due:2026-11-25\n")

    def test_add_rejects_empty_and_blank_text(self):
        for blank in ("", "   "):
            with self.subTest(blank=repr(blank)):
                self.assert_error(("add", blank), "待办内容不能为空", usage=False)
                self.assertFalse(self.path.exists())

    def test_add_missing_content_usage(self):
        self.assert_error(("add",), "缺少待办内容", usage=True)

    def test_add_too_many_positionals(self):
        self.assert_error(("add", "a", "b"), "参数过多", usage=True)

    def test_add_unknown_option(self):
        self.assert_error(("add", "x", "--foo"), '未知参数 "--foo"', usage=True)

    def test_add_due_missing_value(self):
        self.assert_error(("add", "x", "--due"), "--due 需要一个日期参数", usage=True)

    def test_add_due_repeated(self):
        self.assert_error(
            ("add", "x", "--due", "2026-01-01", "--due", "2026-01-02"),
            "重复指定 --due",
            usage=True,
        )

    def test_add_due_bad_format(self):
        self.assert_error(
            ("add", "x", "--due", "2026/11/25"),
            '非法日期 "2026/11/25"（格式 YYYY-MM-DD）',
            usage=False,
        )

    def test_add_due_impossible_date(self):
        self.assert_error(
            ("add", "x", "--due", "2026-02-30"),
            '非法日期 "2026-02-30"（不是真实存在的日期）',
            usage=False,
        )

    def test_add_due_equals_form_rejected(self):
        # DESIGN §6.2 只支持空格分隔；只要求报错+退 1+文件不变
        self.assert_error(("add", "x", "--due=2026-11-25"), "错误", usage=None)

    def test_add_double_dash_allows_leading_dash(self):
        code, out, err = self.run_cli("add", "--", "-开头的文本")
        self.assertEqual((code, out, err), (0, "1\n", ""))
        self.assertEqual(self.read_json()["items"][0]["text"], "-开头的文本")

    def test_add_double_dash_extra_positional(self):
        self.assert_error(("add", "--", "a", "b"), "参数过多", usage=True)

    def test_add_failure_keeps_existing_file(self):
        self.run_cli("add", "原有")
        self.assert_error(("add", "x", "--due", "2026-13-01"), "非法日期", usage=False)

    def test_add_on_corrupt_file_never_overwrites(self):
        self.write_raw("{ 坏掉的 json")
        self.assert_error(("add", "x"), "数据文件损坏", usage=False)

    def test_add_missing_parent_dir_fails_without_creating(self):
        target = self.dir / "nope" / "d.json"
        env = dict(self.base_env, ITEM_FILE=str(target))
        code, out, err = self.run_cli("add", "x", env=env)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("错误: "))
        self.assertIn("目录不存在", err)
        self.assertFalse(target.parent.exists())


# ---------------------------------------------------------------------------
# F2 list
# ---------------------------------------------------------------------------
class TestList(Base):
    def test_list_empty(self):
        code, out, err = self.run_cli("list")
        self.assertEqual((code, out, err), (0, "暂无待办\n", ""))
        self.assertFalse(self.path.exists())

    def test_list_exact_line_format_and_sorted(self):
        self.write_json(
            {
                "version": 1,
                "next_id": 4,
                "items": [
                    {"id": 3, "text": "已完成无日期", "done": True, "due": None},
                    {"id": 1, "text": "买牛奶", "done": False, "due": "2026-11-25"},
                    {"id": 2, "text": "写周报", "done": True, "due": None},
                ],
            }
        )
        code, out, err = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out,
            "1 [ ] 买牛奶 due:2026-11-25\n"
            "2 [x] 写周报\n"
            "3 [x] 已完成无日期\n",
        )

    def test_list_is_read_only(self):
        self.run_cli("add", "只读")
        before = self.file_bytes()
        self.run_cli("list")
        self.assertEqual(self.file_bytes(), before)

    def test_list_corrupt_file(self):
        self.write_raw('{"version": 1, "items": [{"id": 1}]}')
        self.assert_error(("list",), "数据文件损坏", usage=False)

    def test_list_extra_argument(self):
        self.assert_error(("list", "extra"), "参数过多", usage=True)

    def test_list_file_path_is_directory(self):
        env = dict(self.base_env, ITEM_FILE=str(self.dir))
        code, out, err = self.run_cli("list", env=env)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("无法读取数据文件", err)

    def test_list_non_utf8_file(self):
        self.write_raw(b"\xff\xfe\x00bad")
        self.assert_error(("list",), "不是 UTF-8 文本", usage=False)


# ---------------------------------------------------------------------------
# F3 done
# ---------------------------------------------------------------------------
class TestDone(Base):
    def test_done_marks_and_lists_x(self):
        self.run_cli("add", "买牛奶")
        code, out, err = self.run_cli("done", "1")
        self.assertEqual((code, out, err), (0, "已完成: 1\n", ""))
        self.assertTrue(self.read_json()["items"][0]["done"])
        self.assertEqual(self.run_cli("list")[1], "1 [x] 买牛奶\n")

    def test_done_is_idempotent_without_write(self):
        self.run_cli("add", "买牛奶")
        self.run_cli("done", "1")
        before = self.file_bytes()
        code, out, err = self.run_cli("done", "1")
        self.assertEqual((code, out, err), (0, "已完成: 1\n", ""))
        self.assertEqual(self.file_bytes(), before)

    def test_done_unknown_id(self):
        self.run_cli("add", "买牛奶")
        self.assert_error(("done", "9"), "id 不存在: 9", usage=False)

    def test_done_invalid_ids(self):
        for bad in ("abc", "0", "-1", "1.0", "01", " 1"):
            with self.subTest(bad=bad):
                self.assert_error(("done", bad), "非法 id", usage=False)

    def test_done_missing_arg(self):
        self.assert_error(("done",), "缺少 id 参数", usage=True)

    def test_done_too_many_args(self):
        self.run_cli("add", "x")
        self.assert_error(("done", "1", "2"), "参数过多", usage=True)

    def test_done_on_corrupt_file(self):
        self.write_raw("not json")
        self.assert_error(("done", "1"), "数据文件损坏", usage=False)

    def test_done_without_file_creates_nothing(self):
        self.assert_error(("done", "1"), "id 不存在: 1", usage=False)
        self.assertFalse(self.path.exists())


# ---------------------------------------------------------------------------
# F4 rm
# ---------------------------------------------------------------------------
class TestRm(Base):
    def test_rm_deletes_only_target(self):
        self.run_cli("add", "A")
        self.run_cli("add", "B")
        self.run_cli("add", "C")
        code, out, err = self.run_cli("rm", "2")
        self.assertEqual((code, out, err), (0, "已删除: 2\n", ""))
        self.assertEqual([i["id"] for i in self.read_json()["items"]], [1, 3])
        self.assertEqual(self.run_cli("list")[1], "1 [ ] A\n3 [ ] C\n")

    def test_rm_twice_reports_missing(self):
        self.run_cli("add", "A")
        self.run_cli("rm", "1")
        self.assert_error(("rm", "1"), "id 不存在: 1", usage=False)

    def test_rm_invalid_ids(self):
        for bad in ("abc", "0", "-1", "1.0", "01"):
            with self.subTest(bad=bad):
                self.assert_error(("rm", bad), "非法 id", usage=False)

    def test_rm_missing_arg(self):
        self.assert_error(("rm",), "缺少 id 参数", usage=True)

    def test_rm_too_many_args(self):
        self.run_cli("add", "x")
        self.assert_error(("rm", "1", "2"), "参数过多", usage=True)

    def test_rm_corrupt_file(self):
        self.write_raw("{")
        self.assert_error(("rm", "1"), "数据文件损坏", usage=False)


# ---------------------------------------------------------------------------
# F5 持久化
# ---------------------------------------------------------------------------
class TestPersistence(Base):
    def test_item_file_relative_path(self):
        sub = self.dir / "rel"
        sub.mkdir()
        env = dict(self.base_env, ITEM_FILE="rel/data.json")
        code, out, _ = self.run_cli("add", "相对", env=env, cwd=self.dir)
        self.assertEqual((code, out), (0, "1\n"))
        self.assertTrue((sub / "data.json").is_file())

    def test_item_file_with_spaces(self):
        target = self.dir / "有 空格 目录" / "数据 文件.json"
        target.parent.mkdir()
        env = dict(self.base_env, ITEM_FILE=str(target))
        code, out, _ = self.run_cli("add", "带空格路径", env=env)
        self.assertEqual((code, out), (0, "1\n"))
        self.assertEqual(
            json.loads(target.read_text(encoding="utf-8"))["items"][0]["text"],
            "带空格路径",
        )

    def test_default_path_uses_home_without_touching_real_home(self):
        home = self.dir / "fakehome"
        home.mkdir()
        env = dict(self.base_env)
        env.pop("ITEM_FILE", None)
        env["USERPROFILE"] = str(home)
        env["HOME"] = str(home)
        env.pop("HOMEDRIVE", None)
        env.pop("HOMEPATH", None)
        code, out, err = self.run_cli("add", "默认路径", env=env)
        self.assertEqual((code, out, err), (0, "1\n", ""))
        self.assertTrue((home / ".item.json").is_file())

    def test_first_add_creates_file_list_does_not(self):
        self.assertFalse(self.path.exists())
        self.run_cli("list")
        self.assertFalse(self.path.exists())
        self.run_cli("add", "x")
        self.assertTrue(self.path.is_file())

    def test_next_id_normalized_when_file_rolls_back(self):
        self.write_json(
            {"version": 1, "next_id": 1, "items": [{"id": 2, "text": "已有"}]}
        )
        code, out, _ = self.run_cli("add", "新")
        self.assertEqual((code, out), (0, "3\n"))
        self.assertEqual([i["id"] for i in self.read_json()["items"]], [2, 3])

    def test_missing_version_defaults_to_one(self):
        self.write_json({"items": [{"id": 1, "text": "旧文件"}]})
        code, out, _ = self.run_cli("list")
        self.assertEqual((code, out), (0, "1 [ ] 旧文件\n"))

    def test_unknown_fields_dropped_on_write(self):
        self.write_json(
            {
                "version": 1,
                "next_id": 2,
                "extra": "x",
                "items": [{"id": 1, "text": "a", "done": False, "due": None, "tag": "t"}],
            }
        )
        self.run_cli("add", "b")
        data = self.read_json()
        self.assertEqual(sorted(data), ["items", "next_id", "version"])
        self.assertEqual(sorted(data["items"][0]), ["done", "due", "id", "text"])

    def test_structured_corruption_cases(self):
        cases = {
            "非法 JSON": '{"version": 1, "items": [}',
            "0 字节": b"",
            "顶层数组": "[1, 2]",
            "items 缺失": '{"version": 1}',
            "items 非数组": '{"version": 1, "items": {}}',
            "缺 id": '{"version": 1, "items": [{"text": "x"}]}',
            "id 为 0": '{"version": 1, "items": [{"id": 0, "text": "x"}]}',
            "id 重复": '{"version": 1, "items": [{"id": 1, "text": "a"}, {"id": 1, "text": "b"}]}',
            "缺 text": '{"version": 1, "items": [{"id": 1}]}',
            "text 空白": '{"version": 1, "items": [{"id": 1, "text": "  "}]}',
            "done 非布尔": '{"version": 1, "items": [{"id": 1, "text": "x", "done": 1}]}',
            "due 非法": '{"version": 1, "items": [{"id": 1, "text": "x", "due": "2026-02-30"}]}',
            "version 2": '{"version": 2, "items": []}',
            "next_id 非整数": '{"version": 1, "next_id": "3", "items": []}',
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.write_raw(content)
                self.assert_error(("list",), "数据文件损坏", usage=False)
                self.assertIn(str(self.path), self.run_cli("list")[2])

    def test_atomic_write_failure_keeps_original_and_no_temp(self):
        original = {
            "version": 1,
            "next_id": 2,
            "items": [{"id": 1, "text": "原内容", "done": False, "due": None}],
        }
        self.write_json(original)
        before = self.file_bytes()
        code = (
            "import sys, item\n"
            "def boom(*a, **k):\n"
            "    raise OSError(13, 'Permission denied')\n"
            "item.os.replace = boom\n"
            "sys.exit(item.main(['add', '新内容']))\n"
        )
        result = subprocess.run(
            [PY, "-c", code],
            capture_output=True,
            cwd=str(ROOT),
            env=self.base_env,
            timeout=60,
        )
        self.assertEqual(result.returncode, 1)
        err = result.stderr.decode("utf-8")
        self.assertIn("无法写入数据文件", err)
        self.assertIn("Permission denied", err)
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(self.tmp_names(), ["data.json"])

    def test_100_items_performance(self):
        items = [
            {"id": i, "text": f"待办 {i}", "done": False, "due": None}
            for i in range(1, 101)
        ]
        self.write_json({"version": 1, "next_id": 101, "items": items})
        start = time.perf_counter()
        code, out, err = self.run_cli("list")
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(out.splitlines()), 100)
        self.assertLess(elapsed_ms, 300, f"list 100 条耗时 {elapsed_ms:.0f}ms")

    def test_file_is_readable_utf8_json(self):
        self.run_cli("add", "买牛奶 🥛")
        raw = self.path.read_bytes()
        text = raw.decode("utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertIn("买牛奶 🥛", text)
        self.assertNotIn("\\u", text)
        self.assertEqual(self.read_json()["items"][0]["text"], "买牛奶 🥛")


# ---------------------------------------------------------------------------
# F6 入口与退出码
# ---------------------------------------------------------------------------
class TestEntry(Base):
    def test_no_args(self):
        code, out, err = self.run_cli()
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("错误: 缺少命令"))
        self.assertIn("用法:", err)
        self.assertNotIn("Traceback", err)

    def test_help_exit_zero_stdout(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli(flag)
                self.assertEqual((code, err), (0, ""))
                self.assertIn("用法:", out)
                self.assertIn("python item.py add <内容>", out)

    def test_help_ignores_extra_args(self):
        code, out, _ = self.run_cli("--help", "nonsense")
        self.assertEqual(code, 0)
        self.assertIn("用法:", out)

    def test_unknown_command(self):
        code, out, err = self.run_cli("foo")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith('错误: 未知命令 "foo"'))
        self.assertIn("用法:", err)

    def test_all_errors_use_exit_one_and_stderr(self):
        cases = [
            ((), "缺少命令", True),
            (("add",), "缺少待办内容", True),
            (("add", "x", "--bad"), "未知参数", True),
            (("list", "x"), "参数过多", True),
            (("done",), "缺少 id 参数", True),
            (("rm", "abc"), "非法 id", False),
        ]
        for args, part, usage in cases:
            with self.subTest(args=args):
                self.assert_error(args, part, usage=usage)

    def test_pipe_emoji_without_utf8_env(self):
        self.assertEqual(self.run_cli("add", "牛奶 🥛")[0], 0)
        code, out, err = self.run_cli("list")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("牛奶 🥛", out)
        result = subprocess.run(
            [PY, str(ITEM), "list"],
            capture_output=True,
            cwd=str(ROOT),
            env=self.base_env,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("牛奶 🥛".encode("utf-8"), result.stdout)
        self.assertNotIn(b"Traceback", result.stderr)


# ---------------------------------------------------------------------------
# F7 README
# ---------------------------------------------------------------------------
class TestDocs(unittest.TestCase):
    def test_readme_covers_required_sections(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for part in (
            "Python 3.11",
            "零依赖",
            "item.py add",
            "item.py list",
            "item.py done",
            "item.py rm",
            "--help",
            "ITEM_FILE",
            "退出码",
            "python -m unittest",
        ):
            with self.subTest(part=part):
                self.assertIn(part, text)

    def test_readme_quickstart_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.pop("PYTHONUTF8", None)
            env.pop("PYTHONIOENCODING", None)
            env["ITEM_FILE"] = str(Path(tmp) / "data.json")
            commands = [
                (("add", "买牛奶", "--due", "2026-11-25"), "1\n"),
                (("add", "写周报"), "2\n"),
                (("done", "1"), "已完成: 1\n"),
                (("rm", "2"), "已删除: 2\n"),
            ]
            for args, expected in commands:
                with self.subTest(args=args):
                    result = subprocess.run(
                        [PY, str(ITEM), *args],
                        capture_output=True,
                        cwd=str(ROOT),
                        env=env,
                        timeout=60,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        result.stdout.decode("utf-8").replace("\r\n", "\n"), expected
                    )
            listed = subprocess.run(
                [PY, str(ITEM), "list"],
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                timeout=60,
            )
            self.assertEqual(
                listed.stdout.decode("utf-8").replace("\r\n", "\n"),
                "1 [x] 买牛奶 due:2026-11-25\n",
            )
            help_result = subprocess.run(
                [PY, str(ITEM), "--help"],
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                timeout=60,
            )
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("用法:", help_result.stdout.decode("utf-8"))


# ---------------------------------------------------------------------------
# 非功能：零依赖
# ---------------------------------------------------------------------------
class TestNonFunctional(unittest.TestCase):
    def test_zero_third_party_imports(self):
        import ast

        tree = ast.parse((ROOT / "item.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        allowed = {
            "__future__", "json", "os", "re", "sys", "tempfile", "datetime", "pathlib",
        }
        self.assertEqual(modules - allowed, set(), f"发现非标准库 import: {modules - allowed}")
        self.assertFalse((ROOT / "requirements.txt").exists())


# ---------------------------------------------------------------------------
# BUG-01 回归：输出阶段异常与孤立代理项
# ---------------------------------------------------------------------------
class TestOutputFailure(Base):
    def _run_closed_stdout(self, items):
        self.write_json({"version": 1, "next_id": len(items) + 1, "items": items})
        proc = subprocess.Popen(
            [PY, str(ITEM), "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
            env=self.base_env,
        )
        proc.stdout.close()  # 模拟 head/grep 提前关闭读端
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.stderr.close()
        rc = proc.wait(timeout=30)
        return rc, err

    def test_broken_pipe_large_output(self):
        items = [
            {"id": i, "text": "x" * 50, "done": False, "due": None}
            for i in range(1, 501)
        ]
        rc, err = self._run_closed_stdout(items)
        self.assertEqual(rc, 1)
        self.assertIn("错误: 输出已关闭", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Exception ignored", err)

    def test_broken_pipe_small_output(self):
        items = [{"id": 1, "text": "x", "done": False, "due": None}]
        rc, err = self._run_closed_stdout(items)
        self.assertEqual(rc, 1)
        self.assertIn("错误: 输出已关闭", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Exception ignored", err)

    def test_lone_surrogate_file_is_corrupt_and_untouched(self):
        self.write_raw('{"version": 1, "items": [{"id": 1, "text": "\\ud800"}]}')
        before = self.file_bytes()
        code, out, err = self.run_cli("list")
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("错误: 数据文件损坏: "))
        self.assertIn("孤立代理项", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.file_bytes(), before)

    def test_add_rejects_unencodable_text(self):
        code = "import sys, item\nsys.exit(item.main(['add', chr(0xD800)]))"
        result = subprocess.run(
            [PY, "-c", code],
            capture_output=True,
            cwd=str(ROOT),
            env=self.base_env,
            timeout=60,
        )
        self.assertEqual(result.returncode, 1)
        err = result.stderr.decode("utf-8")
        self.assertIn("待办内容包含无法编码的字符", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
