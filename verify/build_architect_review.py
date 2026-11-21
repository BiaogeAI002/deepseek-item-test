"""生成架构师合并前评审的 HTML 报告（7d-code-reviewer 模板驱动）。

一次性脚本：读取技能模板 -> 填充占位符 -> 输出 code-review-report-{timestamp}.html。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(
    r"C:\Users\admin\.dsh\profiles\desktop\node_modules\@7dgroup"
    r"\dsh-skill-7d-code-reviewer\assets\7d-code-reviewer\templates\report-template.html"
)


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def issue(severity: str, loc: str, title: str, desc: str, suggestion: str, code: str = "") -> str:
    label = {"critical": "严重", "medium": "中等", "minor": "轻微"}[severity]
    code_block = f"<pre><code>{esc(code)}</code></pre>" if code else ""
    return f"""<div class="issue {severity}">
    <div class="issue-header">
        <span class="severity-badge {severity}">{label}</span>
        <span class="issue-location">{esc(loc)}</span>
    </div>
    <h4>{esc(title)}</h4>
    <div class="issue-description">{esc(desc)}</div>
    <div class="issue-suggestion">
        <strong>修复建议：</strong>{esc(suggestion)}
        {code_block}
    </div>
</div>"""


def good_point(text: str) -> str:
    return f'<div class="good-point">{esc(text)}</div>'


def suggestion(title: str, desc: str, code: str = "") -> str:
    code_block = f"<pre><code>{esc(code)}</code></pre>" if code else ""
    return f"""<div class="issue-suggestion">
    <h4>{esc(title)}</h4>
    <p>{esc(desc)}</p>
    {code_block}
</div>"""


minor_issues = "\n".join(
    [
        issue(
            "minor",
            "item.py:457-462",
            "`except OSError` 覆盖整个 try，语义过宽",
            "兜底 OSError 位于 try 之外层，但 except 分支覆盖了 run() 的全部执行期。当前 run() 的文件 I/O 都已包装成 ItemError，实际不可达；将来若有命令层未包装的 OSError，会被误报为「输出已关闭」。",
            "把输出动作单独放进一个 try，业务异常与输出异常分开收口，或增加 writing_output 标志判断。",
            "if output:\n    try:\n        print(output)\n        sys.stdout.flush()\n    except (BrokenPipeError, OSError):\n        _discard_stdout()\n        print(\"错误: 输出已关闭\", file=sys.stderr)\n        return 1",
        ),
        issue(
            "minor",
            "item.py:237",
            "`path.parent` 判空分支恒真",
            "`Path.parent` 永远不是空字符串（相对路径为 `.`），`str(path.parent) if ... else Path(\".\")` 的 else 分支是死代码。",
            "直接使用 `parent = path.parent`，行为不变，可读性更好。",
        ),
        issue(
            "minor",
            "item.py:83-89 / 101-113",
            "内容含换行会破坏 list「每行一条」契约",
            "`add \"a\\nb\"` 会原样保存，`list` 输出变成两行，违反 PRD F2 的行格式；数据不丢，但下游按行解析会错位。",
            "v0.2 起在 add_item 中拒绝 `\\r`/`\\n`，或统一转义为 `\\n` 字面量；v0.1 可记入待办。",
            "if \"\\n\" in text or \"\\r\" in text:\n    raise ItemError(\"待办内容不能包含换行\")",
        ),
        issue(
            "minor",
            "item.py:160-170",
            "带 UTF-8 BOM 的手改文件提示不直观",
            "`raw_text.decode(\"utf-8\")` 保留 BOM\\ufeff，json.loads 报「不是合法 JSON: 第 1 行」，用户难以定位是 BOM。",
            "读取时用 `encoding=\"utf-8-sig\"`（或先 strip BOM），并对 BOM 场景补一条测试。",
        ),
        issue(
            "minor",
            "tests/test_item.py:706-716",
            "TestOutputFailure 泄漏 proc.stderr 句柄",
            "`run_with_closed_pipe()` 关闭了 stdout 读端，但 `proc.stderr` 从未 close，76 条运行时出现 2 条 ResourceWarning（本次实测）。不影响断言，但会污染测试输出。",
            "用 `with proc:` 包裹，或在 `wait()` 后 `proc.stderr.close()`。",
            "with proc:\n    proc.stdout.close()\n    stderr_text = proc.stderr.read().decode(\"utf-8\", \"replace\")\n    rc = proc.wait()",
        ),
    ]
)

good_points = "\n".join(
    [
        good_point("分层干净：main → cmd_* → 领域纯函数 → load/save，命令层不直接 open/json.load，边界清晰。"),
        good_point("原子写入实现正确：同目录 mkstemp + fsync + os.replace，异常路径清理临时文件、原文件字节不变，测试有 patch os.replace 的实证。"),
        good_point("损坏数据保护到位：结构校验集中在 normalize_data，坏文件、非 UTF-8、孤立代理项都只报错不覆盖，且带文件路径。"),
        good_point("编码边界处理扎实：stdout/stderr 固定 UTF-8，断管道大/小输出均 rc=1 且无 traceback，未用 errors=\"replace\" 掩盖问题。"),
        good_point("测试覆盖高：76 条单测覆盖全部命令与错误分支，另有真实子进程管道用例；PRD 验收标准可逐条对应。"),
        good_point("零第三方依赖，100 条 list 实测 62ms，远低于 300ms 要求。"),
    ]
)

improvements = "\n".join(
    [
        suggestion(
            "收窄输出阶段异常范围（建议 v0.2 首项）",
            "把 print/flush 单独 try，OSError 只归因于输出流；业务层 OSError 交给内部错误兜底，避免未来误报。",
            "if output:\n    try:\n        print(output)\n        sys.stdout.flush()\n    except BrokenPipeError:\n        _discard_stdout()\n        print(\"错误: 输出已关闭\", file=sys.stderr)\n        return 1",
        ),
        suggestion(
            "换行与 BOM 一起处理",
            "两者都来自手改/边界输入，v0.2 一并收口：add 拒绝换行，读取兼容 utf-8-sig，各补 1 条测试。",
        ),
        suggestion(
            "测试资源清理",
            "关闭子进程 stderr 句柄，保持 `python -m unittest` 输出干净（当前 2 条 ResourceWarning）。",
        ),
    ]
)

values = {
    "report_title": "代码审查报告 - item.py（合并前评审）",
    "review_timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    "total_score": "9",
    "total_score_percent": "90%",
    "summary_description": (
        "优秀，代码质量高，符合最佳实践。本次为合并前门禁评审，"
        "0 严重、0 中等、5 轻微；所有轻微项均不阻塞 v0.1 合并，建议记入 v0.2。"
    ),
    "critical_count": "0",
    "medium_count": "0",
    "minor_count": "5",
    "good_points_count": "6",
    "code_quality_score": "9",
    "security_score": "10",
    "performance_score": "9",
    "maintainability_score": "9",
    "critical_issues": '<p style="color: #27ae60;">🎉 未发现严重问题！</p>',
    "medium_issues": '<p style="color: #27ae60;">🎉 未发现中等问题！</p>',
    "minor_issues": minor_issues,
    "good_points": good_points,
    "improvement_suggestions": improvements,
}

template = TEMPLATE.read_text(encoding="utf-8")
for key, value in values.items():
    template = template.replace("{{" + key + "}}", str(value))

if "{{" in template:
    raise SystemExit(f"模板仍有未填充占位符: {template[template.index('{{'):][:80]}")

timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
out_dir = ROOT / "docs" / "review"
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / f"code-review-report-{timestamp}.html"
out.write_text(template, encoding="utf-8")
print(out)
