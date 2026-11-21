# deepseek-item-test v0.1

零依赖的命令行待办清单。只要 Python 3.11，不需要 `pip install` 任何东西。

## 安装前提

- Python 3.11（仅用标准库）
- 无需安装：在仓库根目录直接用 `python item.py <命令>` 运行

## 快速开始

```powershell
python item.py add "买牛奶" --due 2026-11-25
python item.py add "写周报"
python item.py list
python item.py done 1
python item.py rm 2
python item.py --help
```

`list` 输出示例：

```
1 [x] 买牛奶 due:2026-11-25
2 [ ] 写周报
```

空清单输出 `暂无待办`。未完成显示 `[ ]`，已完成显示 `[x]`；有截止日期时行尾追加 ` due:YYYY-MM-DD`。

## 命令

| 命令 | 说明 |
|---|---|
| `add <内容> [--due YYYY-MM-DD]` | 添加待办，stdout 只输出新 id |
| `list` | 列出全部，按 id 升序 |
| `done <id>` | 标记完成；对已完成的 id 重复执行也算成功（幂等） |
| `rm <id>` | 删除；之后的 id 不会复用 |
| `-h` / `--help` | 打印用法，退出码 0 |

注意：

- 内容含空格/中文/emoji 时请加引号，内容按**单个参数**接收。
- 以 `-` 开头的内容用 `--` 分隔：`python item.py add -- "-开头的文本"`。
- `--due` 必须是真实存在的日期，`2026-02-30` 会被拒绝。

## 数据文件

- 默认路径：`~/.item.json`（Windows 上是 `%USERPROFILE%\.item.json`）。
- 设置环境变量 `ITEM_FILE` 可覆盖（支持相对路径、含空格路径）：

```powershell
$env:ITEM_FILE = "C:\temp\my-todos.json"
python item.py list
```

- 文件不存在时按空清单处理，首次 `add` 才创建（不会自动创建父目录）。
- 格式为 UTF-8 JSON，带缩进，可直接阅读/备份：

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

- 写入是原子的（临时文件 + 替换），不会留下半截文件。
- 文件损坏（非法 JSON、结构不符、非 UTF-8）时只报错退出，**不会覆盖或清空原文件**。

## 输出与退出码

- 正常结果写 stdout；所有错误写 stderr，并以 `错误: ` 开头。
- 成功退出码 `0`；业务/用法错误退出码 `1`；`Ctrl+C` 中断退出码 `130`。
- 任何情况下都不向用户抛 Python traceback。

## 编码说明

程序读写数据和输出均使用 UTF-8；在 Windows 上即使输出被重定向到文件或管道，emoji 也不会报错。

如果终端里中文显示为乱码，把代码页切到 UTF-8 即可：

```powershell
chcp 65001
```

或设置环境变量 `PYTHONUTF8=1`。输出文件本身始终是 UTF-8，用支持 UTF-8 的编辑器打开即可。

注意：PowerShell 5.1 的 `>` 会由 PowerShell 自己把输出**重新编码成 UTF-16LE**，那是 PowerShell 的行为，不是本程序的输出。要看程序输出的真实字节，用 `cmd /c` 重定向：

```powershell
cmd /c "python item.py list > todo.txt"
```

这样得到的 `todo.txt` 就是 UTF-8。

## 运行测试

```powershell
python -m unittest -v
```

测试全部通过 `ITEM_FILE` 指向临时目录，不会读写你真实的 `~/.item.json`。

## 目录结构

```
deepseek-item-test/
├── item.py            # 全部实现（入口 + 数据层 + 命令）
├── tests/
│   ├── __init__.py
│   └── test_item.py   # unittest 用例
├── docs/
│   ├── PRD.md
│   ├── DESIGN.md
│   └── TEST-PLAN.md
├── README.md
└── .gitignore
```

设计细节见 `docs/DESIGN.md`，需求见 `docs/PRD.md`。
