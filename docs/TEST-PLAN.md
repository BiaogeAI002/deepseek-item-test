# deepseek-item-test v0.1 测试计划与验收用例

> 负责人：测试工程师 | 依据：`docs/PRD.md`、`docs/DESIGN.md`（定稿 2026-11-21）
> 原则：独立验证。开发自测 + 测试独立黑盒用例 + 手工控制台验证 + 7d-code-reviewer 审查，四者都过才给「通过」。

## 1. 测试范围与结论门槛

| 范围 | 内容 |
|---|---|
| 必测（P0） | F1 add、F2 list、F3 done、F4 rm、F5 持久化、F6 错误处理、F7 README |
| 非功能 | 零依赖、退出码一致性、无 traceback、Windows 编码、100 条性能 |
| 审查 | 7d-code-reviewer 五步流程，无 🔴 严重问题 |
| 不测（v0.1 明确不做） | edit/clear/搜索/排序/并发/多用户/提醒 |

**验收通过条件（全部满足）**：本文档 P0 用例 100% 执行、无 🔴/🟠 遗留缺陷；`python -m unittest` 全绿；README 示例逐条实跑通过；审查报告无严重项。

## 2. 测试环境与准备

- 本机：Windows，Python 3.11.9，PowerShell；仓库 `C:\Users\admin\.dsh\bot\workspace\deepseek-item-test`
- 隔离：所有用例必须设置 `ITEM_FILE` 指向临时目录，**禁止触碰真实 `~/.item.json`**（执行前先确认该文件不存在或已备份，执行后核对未被修改）
- 编码（DESIGN §7.4 定稿）：程序入口 `_force_utf8_stdio()` 统一把 stdout/stderr 重配为 UTF-8；子进程用例**不设置** `PYTHONUTF8` / `PYTHONIOENCODING`，父进程按 UTF-8 解码，否则等于把坑盖住
- 独立用例不写进开发的 `tests/test_item.py`，避免与 T1–T4 冲突；黑盒一律 `subprocess` 调 `python item.py`，只断言契约（stdout/stderr/退出码/文件字节），不依赖内部函数名
- 计时：`Measure-Command { python item.py list }` → `TotalMilliseconds < 300`

## 3. 用例编号规则

`TC-<命令/领域>-<序号>`；严重程度：🔴 阻断（核心链路不可用/数据损坏）、🟠 严重（验收标准不满足）、🟡 轻微（文案/体验）。

## 4. 用例矩阵（P0）

### 4.1 F1 add

| 编号 | 场景 | 步骤 | 预期结果 |
|---|---|---|---|
| TC-ADD-01 | 成功新增 | `add "买牛奶"` | stdout 仅 `1\n`；退出 0；文件已生成且可被 `json.load`；条目 text=买牛奶、done=false、due=null |
| TC-ADD-02 | 连续新增 | add A、add B | stdout `1`、`2`；2 条按 id 升序 |
| TC-ADD-03 | 删除后 id 不复用 | add 1、add 2、rm 2、add C | 新 id=3；`next_id` ≥ 4；文件内无 id=2 |
| TC-ADD-04 | 内容去首尾空白 | `add "  写周报  "` | 文件中 text=`写周报`（无首尾空格） |
| TC-ADD-05 | 特殊字符 round-trip | `add "买 牛奶 🥛"` | 文件与 list 均完整保留空格、中文、emoji，无乱码/转义错误 |
| TC-ADD-06 | 合法 --due | `add "开会" --due 2026-11-25` | 文件 due=`2026-11-25`；list 行尾 ` due:2026-11-25` |
| TC-ADD-07 | 空内容 | `add ""` | stderr `错误: 待办内容不能为空`（DESIGN §6.4）；退出 1；stdout 空；文件不变 |
| TC-ADD-08 | 全空白内容 | `add "   "` | 同 ADD-07 |
| TC-ADD-09 | 缺内容 | `add` | stderr `错误: 缺少待办内容` + 用法；退出 1；文件不变 |
| TC-ADD-10 | 参数过多 | `add "a" "b"` | `错误: 参数过多` + 用法；退出 1；文件不变 |
| TC-ADD-11 | --due 缺值 | `add "a" --due` | `错误: --due 需要一个日期参数` + 用法；退出 1；文件不变 |
| TC-ADD-12 | --due 重复 | `add "a" --due 2026-11-25 --due 2026-11-26` | `错误: 重复指定 --due`；退出 1；文件不变 |
| TC-ADD-13 | 日期格式非法 | `add "a" --due 2026/11/25` | `错误: 非法日期 "2026/11/25"（格式 YYYY-MM-DD）`；退出 1；文件不变 |
| TC-ADD-14 | 日期不存在 | `add "a" --due 2026-02-30` | `错误: 非法日期 "2026-02-30"（不是真实存在的日期）`；退出 1；文件不变 |
| TC-ADD-15 | --due=值 形式 | `add "a" --due=2026-11-25` | 按设计不支持：`未知参数`；退出 1；文件不变（文案按 DESIGN §6.2 只校验报错+退出码亦可） |
| TC-ADD-16 | `--` 分隔 | `add -- "-开头的内容"` | 成功，id 输出，text=`-开头的内容` |
| TC-ADD-17 | 未知参数 | `add "a" --foo` | `错误: 未知参数 "--foo"` + 用法；退出 1；文件不变 |
| TC-ADD-18 | 已有文件损坏时 add | 预置非法 JSON 后 `add "a"` | 报损坏错误；**原文件字节不变**（不得覆盖） |
| TC-ADD-19 | 失败不写文件 | 上述任一失败用例 | 文件字节与执行前完全一致（首次 add 失败则文件不存在） |

### 4.2 F2 list

| 编号 | 场景 | 步骤 | 预期结果 |
|---|---|---|---|
| TC-LIST-01 | 空清单 | 无文件 / 空 items | stdout 仅 `暂无待办\n`；退出 0 |
| TC-LIST-02 | 行格式 | 预置 1 未完成、2 已完成带 due、3 已完成无 due | 逐行精确：`1 [ ] 买牛奶`、`2 [x] 写周报 due:2026-11-25`、`3 [x] 归档` |
| TC-LIST-03 | 按 id 升序 | 文件中 items 乱序（3,1,2） | 输出仍按 1,2,3 |
| TC-LIST-04 | 只读 | 记录文件字节 → list → 再比 | 字节完全一致 |
| TC-LIST-05 | 中文/emoji 显示 | 含 `买 牛奶 🥛` | 行内完整显示 |
| TC-LIST-06 | 文件损坏 | 非法 JSON | `错误: 数据文件损坏: <path>…`；退出 1；不覆盖 |

### 4.3 F3 done

| 编号 | 场景 | 步骤 | 预期结果 |
|---|---|---|---|
| TC-DONE-01 | 成功完成 | add → `done 1` | stdout `已完成: 1\n`；退出 0；文件 done=true；list 显示 `[x]` |
| TC-DONE-02 | 幂等 | 对已完成 id 再 `done 1` | 退出 0；stdout `已完成: 1`；**文件字节不变**（不重复写） |
| TC-DONE-03 | id 不存在 | `done 9` | `错误: id 不存在: 9`；退出 1；文件不变 |
| TC-DONE-04 | id 非整数 | `done abc` | `错误: 非法 id "abc"`；退出 1；文件不变 |
| TC-DONE-05 | id 为 0 / 负数 / 小数 / 前导零 | `done 0`、`done -1`、`done 1.5`、`done 01` | 均 `非法 id`；退出 1；文件不变（`01` 按 DESIGN `[1-9]\d*` 判非法，若实现接受需提出） |
| TC-DONE-06 | 缺参 | `done` | `错误: 缺少 id 参数` + 用法；退出 1 |
| TC-DONE-07 | 多参 | `done 1 2` | `错误: 参数过多` + 用法；退出 1；文件不变 |

### 4.4 F4 rm

| 编号 | 场景 | 步骤 | 预期结果 |
|---|---|---|---|
| TC-RM-01 | 成功删除 | add 1、2 → `rm 1` | stdout `已删除: 1\n`；退出 0；list 无 1；id 2 仍在 |
| TC-RM-02 | 其他 id 不变 | 同 RM-01 后核对文件 | 剩余条目 id 仍为 2，不重排 |
| TC-RM-03 | 重复删除 | `rm 1` 两次 | 第二次 `错误: id 不存在: 1`；退出 1；文件不变 |
| TC-RM-04 | 非法 id / 缺参 / 多参 | `rm abc`、`rm`、`rm 1 2` | 分别 `非法 id`、`缺少 id 参数`+用法、`参数过多`+用法；退出 1；文件不变 |

### 4.5 F5 持久化

| 编号 | 场景 | 步骤 | 预期结果 |
|---|---|---|---|
| TC-PERS-01 | 默认路径 | 单测级：`resolve_data_path(environ={}, home=临时目录)` | 返回 `<home>/.item.json`（不读写真实 home） |
| TC-PERS-02 | ITEM_FILE 覆盖 | 设绝对临时路径后 add | 数据写该路径，默认 `~/.item.json` 未被创建/修改 |
| TC-PERS-03 | 相对路径 | cwd=临时目录，`ITEM_FILE=data.json` | 写入 `<cwd>/data.json` |
| TC-PERS-04 | 含空格路径 | `ITEM_FILE=<tmp>/my data.json` | 正常读写 |
| TC-PERS-05 | 文件不存在 | 无文件时 `list` | `暂无待办`，退出 0；**不创建文件** |
| TC-PERS-06 | 首次 add 创建 | 无文件时 add | 文件被创建，内容合法 JSON |
| TC-PERS-07 | 父目录不存在 | `ITEM_FILE=<不存在目录>/d.json` 后 add | `错误: 无法写入数据文件: <path>（目录不存在）`；退出 1；目录未被创建 |
| TC-PERS-08 | JSON 可读 | add 中文后查看文件 | UTF-8、缩进、中文可读（或 `\u` 转义但 round-trip 无损）；末尾换行 |
| TC-PERS-09 | 原子性 | patch `os.replace` 抛 OSError（开发测试）+ 复核代码 | 报 `无法写入数据文件`；原文件不变；目录无 `*.tmp` 残留 |
| TC-PERS-10 | next_id 回退纠正 | 手改文件 next_id=1 且有 id 2 → add | 新 id=3，不覆盖已有 id |

### 4.6 F6 错误处理

| 编号 | 场景 | 预期结果 |
|---|---|---|
| TC-ERR-01 | 无子命令 | stderr 用法、退出 1、stdout 空 |
| TC-ERR-02 | `-h` / `--help` | stdout 用法、退出 0 |
| TC-ERR-03 | 未知命令 `foo` | `错误: 未知命令 "foo"` + 用法到 stderr；退出 1 |
| TC-ERR-04 | 错误格式统一 | 所有失败用例：stderr 以 `错误: ` 开头；stdout 为空；退出码 1 |
| TC-ERR-05 | 非法 JSON | `数据文件损坏: <path>（不是合法 JSON: 第 N 行）`；退出 1；**原文件字节不变** |
| TC-ERR-06 | 结构不符 | items 非数组 / 缺 id / 缺 text / done 非 bool / due 非法 / 重复 id / version=2 / 0 字节：均报损坏，文件不变 |
| TC-ERR-07 | 非 UTF-8 | 写入 GBK 字节 → `数据文件无法读取: <path>（不是 UTF-8 文本）`；退出 1；文件不变 |
| TC-ERR-08 | 无 traceback | 上述所有错误输出不含 `Traceback (most recent call last)` |

### 4.7 F7 文档

| 编号 | 场景 | 预期结果 |
|---|---|---|
| TC-DOC-01 | README 内容 | 覆盖 Python 3.11/零依赖、5 条命令示例、`ITEM_FILE`、退出码约定、跑测试方法 |
| TC-DOC-02 | 示例可执行 | 按 README 示例逐条复制执行，输出与文档一致 |

### 4.8 非功能

| 编号 | 场景 | 预期结果 |
|---|---|---|
| TC-NF-01 | 零依赖 | `item.py` 仅 import 标准库；无 requirements/第三方包；`python -c "import item"` 无缺包 |
| TC-NF-02 | 100 条性能 | list 100 条 `TotalMilliseconds < 300` |
| TC-NF-03 | 管道/重定向编码 | 默认环境（不设 `PYTHONUTF8`/`PYTHONIOENCODING`）下 `python item.py list` 重定向到文件/管道：退出 0、无 traceback、输出按 UTF-8 解码后中文+emoji 完整（无替换符 U+FFFD） |
| TC-NF-03b | 控制台编码 | 交互式控制台 `list` 中文+emoji 完整显示，无 UnicodeEncodeError |
| TC-NF-04 | 跨平台路径 | 代码审查：路径用 `pathlib`/`os.path`，无硬编码 `\\`；`ITEM_FILE` 展开 `~` |
| TC-NF-05 | 审查 | 7d-code-reviewer 五步流程，严重/中等/轻微分级 + 四维评分，无 🔴 |

## 5. 缺陷记录模板

```
[ID] BUG-<序号> | 严重程度：🔴/🟠/🟡 | 状态：OPEN/FIXED/VERIFIED
标题：<一句话>
环境：Windows / Python 3.11.9 / ITEM_FILE=<路径>
复现步骤：
  1. ...
  2. ...
预期结果：
实际结果：
证据：<stdout/stderr/退出码/文件字节>
影响：<违反 PRD/DESIGN 哪条>
```

修复后必须回归：原用例 + 相邻命令全链路 + `python -m unittest` 全量。

## 6. 执行记录（测试阶段填写）

| 日期 | 范围 | 结果 | 备注 |
|---|---|---|---|
| 2026-11-21 | F1–F7 + 非功能全量 | 通过 | 单测 76 条 OK；独立黑盒 64 条 OK；BUG-01 修复后回归通过；7d 审查 9/10 无严重/中等。详见 `docs/ACCEPTANCE-REPORT.md` |

## 7. 交付物

- 本测试计划与用例（本文件）
- 独立黑盒验收脚本：`verify/acceptance.py`（P0 全绿后编写并执行，不并入开发 `tests/`）
- 缺陷清单（如有）
- 验收报告：通过项 / 遗留问题 / 风险与建议 + 明确「通过/不通过」
- 7d-code-reviewer 审查报告：`docs/review/code-review-report-<timestamp>.html`
