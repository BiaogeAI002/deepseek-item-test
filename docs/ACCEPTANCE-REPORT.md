# deepseek-item-test v0.1 验收报告

> 测试工程师 | 2026-11-21 | 依据：`docs/PRD.md`、`docs/DESIGN.md`、`docs/TEST-PLAN.md`

## 1. 结论

**通过。** P0 功能与验收标准全部满足；BUG-01 已修复并回归通过；7d-code-reviewer 审查 9/10、无严重/中等问题。建议进入合并前评审与提交阶段。

## 2. 验收环境与方法

- Windows，Python 3.11.9，PowerShell 5.1；仓库 `C:\Users\admin\.dsh\bot\workspace\deepseek-item-test`
- 独立黑盒：`verify/acceptance.py`，只通过子进程调 `python item.py`，断言 stdout/stderr/退出码/文件字节；不依赖开发测试内部实现
- 子进程一律设置 `ITEM_FILE` 指向临时目录，**未读写真实 `~/.item.json`**；默认路径用例通过注入 `USERPROFILE` 验证
- 子进程**不设置** `PYTHONUTF8` / `PYTHONIOENCODING`，保留真实 gbk 管道路径
- 手工/文档：README「快速开始」6 条命令逐条实跑；100 条 list 计时 5 次

## 3. 执行结果

| 项目 | 命令 | 结果 |
|---|---|---|
| 开发单测 | `python -m unittest -q` | **76 条 OK**，退出 0 |
| 独立黑盒 | `python verify/acceptance.py -q` | **64 条 OK**，退出 0 |
| 5 条命令 + README 示例 | 按 README 顺序实跑 | 输出与文档一致，退出码 0 |
| 100 条性能 | 5 次计时（含进程启动） | 中位数 **62.4ms**（要求 <300ms） |
| 零依赖 | AST 扫描 import + 文件检查 | 仅标准库，无 requirements |
| 管道 emoji | 默认环境、管道捕获 | UTF-8 字节完整，rc=0，无 traceback |
| `--help` / 未知命令 / 无参数 | 子进程 | 0 / 1 / 1，错误均以 `错误: ` 开头 |

**用例数核实（Chief 要求）**：以本次独立运行为准——单测 **76 条**、黑盒 **64 条**。此前出现的 71/72/73 是开发迭代过程中的中间数量，不作为验收依据。

## 4. 缺陷清单

| ID | 严重程度 | 标题 | 状态 |
|---|---|---|---|
| BUG-01 | 🟠 严重 | `main()` 输出阶段在 try 外，断管道/孤立代理项会 traceback 或退出码 120 | **VERIFIED** |

**复现（修复前）**

1. 管道提前关闭（等价 `item.py list | head`）：500 条数据 → `Traceback ... OSError: [Errno 22]`；1 条数据 → 退出码 120 + `Exception ignored ... OSError`。
2. 数据文件含孤立代理项 `{"id":1,"text":"\ud800"}` → `list` 在 `print` 处 `UnicodeEncodeError` traceback。

**修复与回归（修复后）**

- 大/小输出断管道：均 **rc=1**，stderr `错误: 输出已关闭`，无 traceback、无 `Exception ignored`、无 120。
- 孤立代理项文件：**rc=1**，`错误: 数据文件损坏: <path>（items[0].text 包含无法编码的字符（孤立代理项））`，**原文件字节不变**。
- `add` 传入不可编码内容：rc=1，`错误: 待办内容包含无法编码的字符`，不创建文件。
- 回归已固化在 `verify/acceptance.py::TestOutputFailure`（4 条）并全绿。

## 5. 遗留问题（轻微，不阻塞交付）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `item.py:457-462` | `except OSError` 覆盖整个 try，未来命令层未包装的 OSError 可能被误报为「输出已关闭」 | 当前不可达，语义隐患 |
| 2 | `item.py:237` | `parent = path.parent if str(path.parent) else Path(".")` 分支恒真 | 死代码，无功能影响 |
| 3 | `item.py:83-89` | 内容含 `\n`/`\r` 会原样保存，`list` 变成多行，破坏「每行一条」契约 | 边界输入，PRD 未要求 |
| 4 | `item.py:160-170` | 带 UTF-8 BOM 的手改文件被报「不是合法 JSON」 | 提示不够直观，数据不丢 |

## 6. 风险与建议

1. **交互式控制台编码**：本会话无可交互 tty，未人工目视控制台；已用管道 UTF-8 字节 + `reconfigure` 实现验证，风险低，建议用户首次使用时按 README `chcp 65001` 目视确认一次。
2. **PowerShell 5.1 重定向**：`>` 会把输出转成 UTF-16LE，这是 PowerShell 行为；README 已注明用 `cmd /c` 看真实 UTF-8 字节，验收不据此判缺陷。
3. **并发写**：v0.1 明确不做；多进程同时写存在丢失更新风险，PRD 非目标。
4. 建议后续版本处理第 5 节 4 个轻微项，尤其换行与 BOM，减少手改数据文件的困惑。

## 7. 审查结果（7d-code-reviewer）

- 五步流程、严重/中等/轻微三级分级、四维评分
- 总体 **9/10**：代码质量 9、安全性 10、性能 9、可维护性 9
- **0 严重、0 中等、4 轻微**，无 🔴，满足 PRD 成功判定第 3 条
- HTML 报告：`docs/review/code-review-report-20261121182133.html`

## 8. 附件

- 独立黑盒用例：`verify/acceptance.py`（64 条）
- 测试计划与用例：`docs/TEST-PLAN.md`
- 审查报告：`docs/review/code-review-report-20261121182133.html`
- 合并前评审报告（架构师）：`docs/review/code-review-report-20261121182550.html`
- 审查报告生成脚本：`verify/build_review_report.py`、`verify/build_architect_review.py`
- v0.2 待办：`docs/BACKLOG.md`
