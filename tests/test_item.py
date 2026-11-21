"""deepseek-item-test v0.1 单元测试（标准库 unittest）。

运行：
    python -m unittest -v
    python -m unittest tests.test_item.TestAdd -v
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import item

ROOT = Path(__file__).resolve().parents[1]


class ItemTestCase(unittest.TestCase):
    """每个用例独立临时目录，并把 ITEM_FILE 指向临时文件，绝不碰真实 ~/.item.json。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)
        self.path = self.tmp_dir / "data.json"
        patcher = patch.dict(os.environ, {"ITEM_FILE": str(self.path)})
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- 文件辅助 -----------------------------------------------------------
    def write_raw(self, content) -> None:
        """按原始字节写数据文件，用来构造损坏文件。"""
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.path.write_bytes(content)

    def file_bytes(self):
        """文件当前字节；不存在返回 None（用于断言「文件未变」）。"""
        return self.path.read_bytes() if self.path.exists() else None

    def read_json(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write_json(self, data: dict) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def tmp_files(self) -> list:
        return sorted(p.name for p in self.tmp_dir.iterdir())

    # -- CLI 辅助 -----------------------------------------------------------
    def run_cli(self, *args) -> tuple[int, str, str]:
        """进程内调用 main()，返回 (退出码, stdout, stderr)。"""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = item.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def assert_cli_error(self, args, message_part, usage=False):
        """断言一次失败调用：退 1、stdout 空、stderr 以「错误: 」开头。"""
        code, out, err = self.run_cli(*args)
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("错误: "), err)
        self.assertIn(message_part, err)
        if usage:
            self.assertIn("用法:", err)
        else:
            self.assertNotIn("用法:", err)
        return err


# ---------------------------------------------------------------------------
# T1 数据层
# ---------------------------------------------------------------------------


class TestDataLayer(ItemTestCase):
    def test_new_empty_data(self):
        self.assertEqual(
            item.new_empty_data(), {"version": 1, "next_id": 1, "items": []}
        )

    def test_resolve_data_path_default(self):
        self.assertEqual(
            item.resolve_data_path(environ={}, home="/home/u"),
            Path("/home/u") / ".item.json",
        )

    def test_resolve_data_path_item_file_overrides(self):
        self.assertEqual(
            item.resolve_data_path(environ={"ITEM_FILE": "/data/x.json"}),
            Path("/data/x.json"),
        )

    def test_resolve_data_path_empty_item_file_falls_back(self):
        self.assertEqual(
            item.resolve_data_path(environ={"ITEM_FILE": ""}, home="/home/u"),
            Path("/home/u") / ".item.json",
        )

    def test_resolve_data_path_keeps_relative_path(self):
        self.assertEqual(
            item.resolve_data_path(environ={"ITEM_FILE": "sub/x.json"}),
            Path("sub/x.json"),
        )

    def test_resolve_data_path_expands_tilde(self):
        resolved = item.resolve_data_path(environ={"ITEM_FILE": "~/x.json"})
        self.assertNotIn("~", str(resolved))

    def test_load_missing_file_returns_empty_without_creating(self):
        self.assertEqual(item.load_data(self.path), item.new_empty_data())
        self.assertFalse(self.path.exists())

    def test_load_valid_file(self):
        self.write_json(
            {
                "version": 1,
                "next_id": 3,
                "items": [
                    {"id": 1, "text": "买牛奶", "done": False, "due": "2026-11-25"},
                    {"id": 2, "text": "写周报", "done": True, "due": None},
                ],
            }
        )
        data = item.load_data(self.path)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["next_id"], 3)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["text"], "买牛奶")
        self.assertTrue(data["items"][1]["done"])

    def test_load_applies_defaults_for_missing_done_and_due(self):
        self.write_json(
            {
                "version": 1,
                "items": [
                    {"id": 1, "text": "只有必填字段"},
                ],
            }
        )
        data = item.load_data(self.path)
        self.assertEqual(data["items"][0]["done"], False)
        self.assertIsNone(data["items"][0]["due"])
        self.assertEqual(data["next_id"], 2)

    def test_load_drops_unknown_fields(self):
        self.write_json(
            {
                "version": 1,
                "next_id": 2,
                "extra": "ignored",
                "items": [{"id": 1, "text": "x", "done": False, "due": None, "tag": "t"}],
            }
        )
        data = item.load_data(self.path)
        self.assertEqual(list(data), ["version", "next_id", "items"])
        self.assertEqual(list(data["items"][0]), ["id", "text", "done", "due"])

    def test_load_normalizes_next_id_from_max_item(self):
        # next_id 缺失 -> max(id)+1
        self.write_json({"version": 1, "items": [{"id": 7, "text": "x"}]})
        self.assertEqual(item.load_data(self.path)["next_id"], 8)

        # next_id 回退（手改文件）-> 纠正到 max(id)+1
        self.write_json(
            {"version": 1, "next_id": 1, "items": [{"id": 5, "text": "x"}]}
        )
        self.assertEqual(item.load_data(self.path)["next_id"], 6)

        # next_id 合法且更大 -> 保留（删除后不复用）
        self.write_json(
            {"version": 1, "next_id": 9, "items": [{"id": 3, "text": "x"}]}
        )
        self.assertEqual(item.load_data(self.path)["next_id"], 9)

    def test_load_rejects_corrupt_files_without_touching_them(self):
        cases = {
            "不是合法 JSON": '{"version": 1, "items": [}',
            "0 字节文件": b"",
            "顶层不是对象": "[1, 2, 3]",
            "items 缺失": '{"version": 1}',
            "items 不是数组": '{"version": 1, "items": {}}',
            "单条不是对象": '{"version": 1, "items": ["x"]}',
            "缺 id": '{"version": 1, "items": [{"text": "x"}]}',
            "id 为 0": '{"version": 1, "items": [{"id": 0, "text": "x"}]}',
            "id 为布尔": '{"version": 1, "items": [{"id": true, "text": "x"}]}',
            "id 重复": '{"version": 1, "items": [{"id": 1, "text": "a"}, {"id": 1, "text": "b"}]}',
            "缺 text": '{"version": 1, "items": [{"id": 1}]}',
            "text 全空白": '{"version": 1, "items": [{"id": 1, "text": "   "}]}',
            "text 非字符串": '{"version": 1, "items": [{"id": 1, "text": 5}]}',
            "text 孤立代理项": '{"version": 1, "items": [{"id": 1, "text": "\\ud800"}]}',
            "done 非布尔": '{"version": 1, "items": [{"id": 1, "text": "x", "done": 1}]}',
            "due 格式错": '{"version": 1, "items": [{"id": 1, "text": "x", "due": "11/25"}]}',
            "due 非真实日期": '{"version": 1, "items": [{"id": 1, "text": "x", "due": "2026-02-30"}]}',
            "version 不支持": '{"version": 2, "items": []}',
            "next_id 非整数": '{"version": 1, "next_id": "3", "items": []}',
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.write_raw(content)
                before = self.file_bytes()
                with self.assertRaises(item.ItemError) as ctx:
                    item.load_data(self.path)
                message = str(ctx.exception)
                self.assertTrue(message.startswith("数据文件损坏: "), message)
                self.assertIn(str(self.path), message)
                self.assertEqual(self.file_bytes(), before)

    def test_load_non_utf8_file(self):
        self.write_raw(b"\xff\xfe\x00bad")
        with self.assertRaises(item.ItemError) as ctx:
            item.load_data(self.path)
        self.assertIn("不是 UTF-8 文本", str(ctx.exception))

    def test_load_dir_path_reports_read_error(self):
        with self.assertRaises(item.ItemError) as ctx:
            item.load_data(self.tmp_dir)
        self.assertIn("无法读取数据文件", str(ctx.exception))


# ---------------------------------------------------------------------------
# T1 持久化
# ---------------------------------------------------------------------------


class TestPersistence(ItemTestCase):
    def test_save_then_load_roundtrip(self):
        data = {
            "version": 1,
            "next_id": 3,
            "items": [
                {"id": 1, "text": "买牛奶 🥛", "done": False, "due": "2026-11-25"},
                {"id": 2, "text": "写周报", "done": True, "due": None},
            ],
        }
        item.save_data(self.path, data)
        self.assertEqual(item.load_data(self.path), data)

    def test_save_writes_readable_utf8_json_with_trailing_newline(self):
        data = {
            "version": 1,
            "next_id": 2,
            "items": [{"id": 1, "text": "买牛奶", "done": False, "due": None}],
        }
        item.save_data(self.path, data)
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertIn("买牛奶", text)  # ensure_ascii=False
        self.assertNotIn("\\u", text)
        self.assertIn('\n  "version": 1', text)  # indent=2
        self.assertEqual(self.read_json(), data)

    def test_save_overwrites_previous_content(self):
        item.save_data(self.path, item.new_empty_data())
        item.save_data(
            self.path,
            {
                "version": 1,
                "next_id": 2,
                "items": [{"id": 1, "text": "新内容", "done": False, "due": None}],
            },
        )
        self.assertEqual(self.read_json()["items"][0]["text"], "新内容")

    def test_save_leaves_no_temp_file(self):
        item.save_data(self.path, item.new_empty_data())
        self.assertEqual(self.tmp_files(), ["data.json"])

    def test_save_into_directory_with_spaces_and_unicode(self):
        target = self.tmp_dir / "有 空格 的目录" / "数据 文件.json"
        target.parent.mkdir()
        item.save_data(target, item.new_empty_data())
        self.assertEqual(item.load_data(target), item.new_empty_data())

    def test_save_missing_parent_dir_fails(self):
        target = self.tmp_dir / "nope" / "data.json"
        with self.assertRaises(item.ItemError) as ctx:
            item.save_data(target, item.new_empty_data())
        self.assertIn("目录不存在", str(ctx.exception))
        self.assertFalse(target.parent.exists())

    def test_save_replace_failure_keeps_original_and_cleans_temp(self):
        original = {
            "version": 1,
            "next_id": 2,
            "items": [{"id": 1, "text": "原内容", "done": False, "due": None}],
        }
        item.save_data(self.path, original)
        before = self.file_bytes()

        changed = {
            "version": 1,
            "next_id": 2,
            "items": [{"id": 1, "text": "改坏了", "done": False, "due": None}],
        }
        with patch.object(item.os, "replace", side_effect=OSError(13, "Permission denied")):
            with self.assertRaises(item.ItemError) as ctx:
                item.save_data(self.path, changed)

        self.assertIn("无法写入数据文件", str(ctx.exception))
        self.assertIn("Permission denied", str(ctx.exception))
        self.assertEqual(self.file_bytes(), before)
        self.assertEqual(self.tmp_files(), ["data.json"])


# ---------------------------------------------------------------------------
# T2 add / list
# ---------------------------------------------------------------------------


class TestAdd(ItemTestCase):
    def test_add_prints_only_new_id(self):
        code, out, err = self.run_cli("add", "买牛奶")
        self.assertEqual((code, out, err), (0, "1\n", ""))
        self.assertEqual(self.read_json()["items"][0]["text"], "买牛奶")

    def test_add_uses_incrementing_ids(self):
        self.run_cli("add", "第一条")
        code, out, _ = self.run_cli("add", "第二条")
        self.assertEqual(out, "2\n")
        self.assertEqual([i["id"] for i in self.read_json()["items"]], [1, 2])
        self.assertEqual(self.read_json()["next_id"], 3)

    def test_add_with_due_persists_date(self):
        code, out, err = self.run_cli("add", "买牛奶", "--due", "2026-11-25")
        self.assertEqual((code, out, err), (0, "1\n", ""))
        self.assertEqual(self.read_json()["items"][0]["due"], "2026-11-25")

    def test_add_trims_surrounding_whitespace(self):
        code, _, _ = self.run_cli("add", "  写周报  ")
        self.assertEqual(code, 0)
        self.assertEqual(self.read_json()["items"][0]["text"], "写周报")

    def test_add_keeps_inner_spaces_chinese_and_emoji(self):
        text = "买 牛奶 🥛 for 妈妈"
        code, _, _ = self.run_cli("add", text)
        self.assertEqual(code, 0)
        self.assertEqual(self.read_json()["items"][0]["text"], text)

    def test_add_double_dash_allows_dash_text(self):
        code, out, err = self.run_cli("add", "--", "-开头的文本")
        self.assertEqual((code, out, err), (0, "1\n", ""))
        self.assertEqual(self.read_json()["items"][0]["text"], "-开头的文本")

    def test_add_double_dash_two_contents_is_too_many(self):
        self.assert_cli_error(("add", "--", "a", "b"), "参数过多", usage=True)

    def test_add_rejects_blank_text_and_creates_no_file(self):
        for blank in ("", "   "):
            with self.subTest(content=blank):
                self.assert_cli_error(("add", blank), "待办内容不能为空")
                self.assertIsNone(self.file_bytes())

    def test_add_without_content_shows_usage(self):
        self.assert_cli_error(("add",), "缺少待办内容", usage=True)

    def test_add_too_many_positionals_shows_usage(self):
        self.assert_cli_error(("add", "a", "b"), "参数过多", usage=True)

    def test_add_unknown_option_shows_usage(self):
        self.assert_cli_error(("add", "x", "--foo"), '未知参数 "--foo"', usage=True)

    def test_add_due_without_value_shows_usage(self):
        self.assert_cli_error(("add", "x", "--due"), "--due 需要一个日期参数", usage=True)

    def test_add_duplicate_due_shows_usage(self):
        self.assert_cli_error(
            ("add", "x", "--due", "2026-01-01", "--due", "2026-01-02"),
            "重复指定 --due",
            usage=True,
        )

    def test_add_bad_due_format(self):
        self.assert_cli_error(
            ("add", "x", "--due", "2026/01/01"), "非法日期 \"2026/01/01\"（格式 YYYY-MM-DD）"
        )

    def test_add_impossible_due_date(self):
        self.assert_cli_error(
            ("add", "x", "--due", "2026-02-30"),
            "非法日期 \"2026-02-30\"（不是真实存在的日期）",
        )

    def test_add_failure_keeps_existing_file_unchanged(self):
        self.run_cli("add", "原有条目")
        before = self.file_bytes()
        self.assert_cli_error(("add", "x", "--due", "2026-13-01"), "非法日期")
        self.assertEqual(self.file_bytes(), before)

    def test_add_rejects_unencodable_text(self):
        self.assert_cli_error(("add", "\ud800"), "待办内容包含无法编码的字符")
        self.assertIsNone(self.file_bytes())

    def test_add_on_corrupt_file_fails_without_overwriting(self):
        self.write_raw("{ 坏掉的 json")
        before = self.file_bytes()
        self.assert_cli_error(("add", "x"), "数据文件损坏")
        self.assertEqual(self.file_bytes(), before)


class TestList(ItemTestCase):
    def test_list_empty_says_no_todo_and_creates_no_file(self):
        code, out, err = self.run_cli("list")
        self.assertEqual((code, out, err), (0, "暂无待办\n", ""))
        self.assertFalse(self.path.exists())

    def test_list_formats_all_items_sorted_by_id(self):
        self.write_json(
            {
                "version": 1,
                "next_id": 4,
                "items": [
                    {"id": 3, "text": "做完的", "done": True, "due": None},
                    {"id": 1, "text": "买牛奶", "done": False, "due": "2026-11-25"},
                    {"id": 2, "text": "写周报", "done": False, "due": None},
                ],
            }
        )
        code, out, err = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out,
            "1 [ ] 买牛奶 due:2026-11-25\n"
            "2 [ ] 写周报\n"
            "3 [x] 做完的\n",
        )

    def test_list_does_not_modify_file(self):
        self.run_cli("add", "只读测试")
        before = self.file_bytes()
        self.run_cli("list")
        self.assertEqual(self.file_bytes(), before)

    def test_list_extra_argument_shows_usage(self):
        self.assert_cli_error(("list", "extra"), "参数过多", usage=True)

    def test_list_corrupt_file_reports_error(self):
        self.write_raw('{"version": 1, "items": [{"id": 1}]}')
        self.assert_cli_error(("list",), "数据文件损坏")


# ---------------------------------------------------------------------------
# T3 done / rm
# ---------------------------------------------------------------------------


class TestDone(ItemTestCase):
    def test_done_marks_item_complete(self):
        self.run_cli("add", "买牛奶")
        code, out, err = self.run_cli("done", "1")
        self.assertEqual((code, out, err), (0, "已完成: 1\n", ""))
        self.assertTrue(self.read_json()["items"][0]["done"])
        self.assertIn("1 [x] 买牛奶", self.run_cli("list")[1])

    def test_done_is_idempotent_and_does_not_write_file(self):
        self.run_cli("add", "买牛奶")
        self.run_cli("done", "1")
        before = self.file_bytes()
        code, out, err = self.run_cli("done", "1")
        self.assertEqual((code, out, err), (0, "已完成: 1\n", ""))
        self.assertEqual(self.file_bytes(), before)

    def test_done_missing_id_shows_usage(self):
        self.assert_cli_error(("done",), "缺少 id 参数", usage=True)

    def test_done_too_many_args_shows_usage(self):
        self.assert_cli_error(("done", "1", "2"), "参数过多", usage=True)

    def test_done_rejects_non_integer_id(self):
        for bad in ("abc", "0", "-1", "1.0", " 1"):
            with self.subTest(value=bad):
                self.assert_cli_error(("done", bad), f'非法 id "{bad}"')

    def test_done_unknown_id_keeps_file_unchanged(self):
        self.run_cli("add", "买牛奶")
        before = self.file_bytes()
        self.assert_cli_error(("done", "9"), "id 不存在: 9")
        self.assertEqual(self.file_bytes(), before)

    def test_done_unknown_id_without_file_creates_no_file(self):
        self.assert_cli_error(("done", "1"), "id 不存在: 1")
        self.assertFalse(self.path.exists())

    def test_done_on_corrupt_file_fails_without_overwriting(self):
        self.write_raw("not json")
        before = self.file_bytes()
        self.assert_cli_error(("done", "1"), "数据文件损坏")
        self.assertEqual(self.file_bytes(), before)


class TestRm(ItemTestCase):
    def test_rm_deletes_item_and_keeps_other_ids(self):
        self.run_cli("add", "第一条")
        self.run_cli("add", "第二条")
        self.run_cli("add", "第三条")
        code, out, err = self.run_cli("rm", "2")
        self.assertEqual((code, out, err), (0, "已删除: 2\n", ""))
        ids = [entry["id"] for entry in self.read_json()["items"]]
        self.assertEqual(ids, [1, 3])
        self.assertNotIn("2 [", self.run_cli("list")[1])

    def test_rm_does_not_reuse_deleted_id(self):
        self.run_cli("add", "第一条")
        self.run_cli("add", "第二条")
        self.run_cli("rm", "2")
        code, out, _ = self.run_cli("add", "第三条")
        self.assertEqual(out, "3\n")
        self.assertEqual(self.read_json()["next_id"], 4)

    def test_rm_twice_reports_unknown_id(self):
        self.run_cli("add", "第一条")
        self.run_cli("rm", "1")
        before = self.file_bytes()
        self.assert_cli_error(("rm", "1"), "id 不存在: 1")
        self.assertEqual(self.file_bytes(), before)

    def test_rm_missing_id_shows_usage(self):
        self.assert_cli_error(("rm",), "缺少 id 参数", usage=True)

    def test_rm_too_many_args_shows_usage(self):
        self.assert_cli_error(("rm", "1", "2"), "参数过多", usage=True)

    def test_rm_rejects_non_integer_id(self):
        for bad in ("abc", "0", "-1"):
            with self.subTest(value=bad):
                self.assert_cli_error(("rm", bad), f'非法 id "{bad}"')

    def test_rm_unknown_id_keeps_file_unchanged(self):
        self.run_cli("add", "买牛奶")
        before = self.file_bytes()
        self.assert_cli_error(("rm", "2"), "id 不存在: 2")
        self.assertEqual(self.file_bytes(), before)

    def test_rm_on_corrupt_file_fails_without_overwriting(self):
        self.write_raw("{")
        before = self.file_bytes()
        self.assert_cli_error(("rm", "1"), "数据文件损坏")
        self.assertEqual(self.file_bytes(), before)


# ---------------------------------------------------------------------------
# T4 入口与子进程冒烟
# ---------------------------------------------------------------------------


class TestMain(ItemTestCase):
    def test_no_args_prints_usage_to_stderr(self):
        self.assert_cli_error((), "缺少命令", usage=True)

    def test_help_goes_to_stdout(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli(flag)
                self.assertEqual(code, 0)
                self.assertEqual(err, "")
                self.assertIn("用法:", out)
                self.assertIn("python item.py add <内容>", out)

    def test_help_ignores_extra_args(self):
        code, out, err = self.run_cli("--help", "whatever")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("用法:", out)

    def test_unknown_command_prints_usage(self):
        self.assert_cli_error(("foo",), '未知命令 "foo"', usage=True)

    def test_keyboard_interrupt_exits_130(self):
        with patch.object(item, "run", side_effect=KeyboardInterrupt):
            code, out, err = self.run_cli("list")
        self.assertEqual((code, out), (130, ""))
        self.assertIn("错误: 已中断", err)

    def test_unexpected_exception_is_wrapped_without_traceback(self):
        with patch.object(item, "run", side_effect=RuntimeError("boom")):
            code, out, err = self.run_cli("list")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("错误: 内部错误: boom", err)
        self.assertNotIn("Traceback", err)

    def test_force_utf8_stdio_skips_streams_without_reconfigure(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            item._force_utf8_stdio()  # StringIO 无 reconfigure，不应抛异常
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_relative_item_file_path(self):
        (self.tmp_dir / "rel").mkdir()
        old_cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        self.addCleanup(os.chdir, old_cwd)
        with patch.dict(os.environ, {"ITEM_FILE": "rel/data.json"}):
            code, out, _ = self.run_cli("add", "相对路径")
        self.assertEqual((code, out), (0, "1\n"))
        self.assertTrue((self.tmp_dir / "rel" / "data.json").is_file())


class CliSmokeBase(unittest.TestCase):
    """子进程测试公共基类：临时 ITEM_FILE、utf-8 捕获。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_dir = Path(self.tmp.name)
        self.path = self.tmp_dir / "data.json"
        self.env = os.environ.copy()
        self.env["ITEM_FILE"] = str(self.path)
        # 设计 §8.2：子进程不设 PYTHONUTF8/PYTHONIOENCODING，保留真实 gbk 管道路径
        self.env.pop("PYTHONUTF8", None)
        self.env.pop("PYTHONIOENCODING", None)

    def run_script(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "item.py"), *args],
            capture_output=True,
            encoding="utf-8",
            cwd=str(ROOT),
            env=self.env if env is None else env,
            timeout=30,
        )


class TestCliSmoke(CliSmokeBase):
    """真实子进程：验证入口、退出码和管道编码。"""

    def test_help_exit_zero(self):
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("用法:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_full_chain(self):
        added = self.run_script("add", "买牛奶", "--due", "2026-11-25")
        self.assertEqual((added.returncode, added.stdout), (0, "1\n"))

        self.run_script("add", "写周报")
        listed = self.run_script("list")
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(
            listed.stdout, "1 [ ] 买牛奶 due:2026-11-25\n2 [ ] 写周报\n"
        )

        done = self.run_script("done", "1")
        self.assertEqual((done.returncode, done.stdout), (0, "已完成: 1\n"))

        removed = self.run_script("rm", "2")
        self.assertEqual((removed.returncode, removed.stdout), (0, "已删除: 2\n"))

        final = self.run_script("list")
        self.assertEqual(final.stdout, "1 [x] 买牛奶 due:2026-11-25\n")

    def test_corrupt_file_exits_one(self):
        self.path.write_text("{ 坏", encoding="utf-8")
        result = self.run_script("list")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("错误: "))
        self.assertNotIn("Traceback", result.stderr)

    def test_emoji_through_pipe_without_utf8_env(self):
        # 复现「管道 stdout=gbk」场景：子进程不设任何 UTF-8 相关环境变量。
        added = self.run_script("add", "牛奶 🥛")
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertNotIn("UnicodeEncodeError", added.stderr)

        listed = self.run_script("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("牛奶 🥛", listed.stdout)

    def test_item_file_with_spaces(self):
        target = self.tmp_dir / "有 空格" / "数据.json"
        target.parent.mkdir()
        env = dict(self.env, ITEM_FILE=str(target))
        result = self.run_script("add", "带空格路径", env=env)
        self.assertEqual((result.returncode, result.stdout), (0, "1\n"))
        self.assertTrue(target.is_file())


class TestOutputFailure(CliSmokeBase):
    """BUG-01 回归：输出阶段异常不得漏出 traceback。"""

    def write_items(self, count: int) -> None:
        data = {
            "version": 1,
            "next_id": count + 1,
            "items": [
                {"id": i, "text": f"任务{i}", "done": False, "due": None}
                for i in range(1, count + 1)
            ],
        }
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def run_with_closed_pipe(self) -> tuple[int, str]:
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "item.py"), "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
            env=self.env,
        )
        proc.stdout.close()  # 关闭读端，模拟 `item list | head` 后管道断开
        stderr_text = proc.stderr.read().decode("utf-8", "replace")
        return proc.wait(), stderr_text

    def assert_clean_output_failure(self, rc: int, stderr_text: str) -> None:
        self.assertEqual(rc, 1, stderr_text)
        self.assertIn("错误: 输出已关闭", stderr_text)
        self.assertNotIn("Traceback", stderr_text)
        self.assertNotIn("Exception ignored", stderr_text)

    def test_broken_pipe_large_output(self):
        self.write_items(500)
        self.assert_clean_output_failure(*self.run_with_closed_pipe())

    def test_broken_pipe_small_output(self):
        # 小输出会留在缓冲区，必须在 main 里 flush，否则解释器退出时退 120。
        self.write_items(1)
        self.assert_clean_output_failure(*self.run_with_closed_pipe())

    def test_isolated_surrogate_file_is_corrupt_not_traceback(self):
        self.path.write_bytes(
            b'{"version": 1, "items": [{"id": 1, "text": "\\ud800"}]}'
        )
        before = self.path.read_bytes()
        result = self.run_script("list")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("错误: 数据文件损坏", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
