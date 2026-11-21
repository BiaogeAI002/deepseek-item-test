# v0.2 待办（BACKLOG）

> 来源：验收审查（测试工程师）+ 合并前评审（架构师），均使用 7d-code-reviewer。
> 2026-11-21 用户拍板：5 个轻微项全部记入 v0.2，不阻塞 v0.1 交付。

结论：v0.1 无严重/中等问题（0 🔴 / 0 🟠），两份报告均在 `docs/review/`。

## 待办清单

| # | 级别 | 位置 | 问题 | 建议方案 |
|---|---|---|---|---|
| 1 | 轻微 | `item.py:457-462` | `except OSError` 覆盖整个 try；未来命令层未包装的 OSError 会被误报为「输出已关闭」，掩盖真实 I/O 错误 | print/flush 单独包一个 try，命令层 OSError 走独立分支（当前不可达） |
| 2 | 轻微 | `item.py:237` | `path.parent if str(path.parent) else Path(".")` 判空分支恒真 | 删死分支，直接取 `path.parent` |
| 3 | 轻微 | `item.py:160-170` | 带 UTF-8 BOM 的手改文件报「不是合法 JSON」，提示不直观 | 读取用 `utf-8-sig`，写入仍 UTF-8 无 BOM |
| 4 | 轻微 | `item.py:83-89` | 内容含 `\n`/`\r` 时 `list` 输出多行，破坏「每行一条」契约；数据本身未坏 | `add` 拒绝或替换换行字符，并补用例 |
| 5 | 轻微 | `tests/test_item.py:706-716` | `proc.stderr` 未关闭，实测 2 条 ResourceWarning | 用 `with` 管理子进程管道或用后显式 close |

## 建议处理顺序

4 → 3 → 1 → 2 → 5（4、3 有可观察影响，1、2、5 为防御性/洁净度）。
改完需重跑 `python -m unittest`（76 条）与 `python verify/acceptance.py`（64 条），并补对应回归用例。
