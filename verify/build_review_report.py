"""生成 7d-code-reviewer 标准 HTML 审查报告（模板填充，内容 HTML 转义）。"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(
    r"C:\Users\admin\.dsh\profiles\desktop\node_modules"
    r"\@7dgroup\dsh-skill-7d-code-reviewer\assets\7d-code-reviewer"
    r"\templates\report-template.html"
)

ISSUES = [
    {
        "class": "minor",
        "label": "轻微",
        "location": "item.py:457-462",
        "title": "main() 的 OSError 兜底可能误标「输出已关闭」",
        "description": (
            "输出已移入 try 内执行，但 except OSError 覆盖整个 try：若命令层未来出现"
            "未包装的 OSError，会被误报为「输出已关闭」，掩盖真实 I/O 错误。"
            "当前 load_data/save_data 均已包装 OSError，实际不可达。"
        ),
        "suggestion": "把输出写入抽成 _emit(output) 并只在该函数内捕获 BrokenPipeError/OSError；命令层异常仍按层级包装。",
        "code": "def _emit(output: str) -> None:\n    print(output)\n    sys.stdout.flush()",
    },
    {
        "class": "minor",
        "label": "轻微",
        "location": "item.py:237",
        "title": "save_data 父目录判断含死分支",
        "description": "Path(\"data.json\").parent 为 Path(\".\")，str() 恒为非空，else Path(\".\") 不可达，属冗余代码。",
        "suggestion": "简化为 parent = path.parent。",
        "code": "parent = path.parent\nif not parent.is_dir():\n    raise ItemError(...)",
    },
    {
        "class": "minor",
        "label": "轻微",
        "location": "item.py:83-89 / 101-113",
        "title": "内容含换行会破坏 list 单行契约",
        "description": (
            "add $'a\\nb' 会把换行原样写入；list 输出变成两行，第二行没有 id，"
            "脚本按行解析时可能误判条目数。PRD 未要求支持控制字符，属边界改进。"
        ),
        "suggestion": "在 add_item / normalize_data 拒绝 \\r、\\n（或转义展示），并补一条用例。",
        "code": "if any(ch in text for ch in (\"\\r\", \"\\n\")):\n    raise ItemError(\"待办内容不能包含换行\")",
    },
    {
        "class": "minor",
        "label": "轻微",
        "location": "item.py:160-170",
        "title": "UTF-8 BOM 文件被当作损坏",
        "description": (
            "Windows 记事本手改保存可能带 BOM；decode(\"utf-8\") 后 json.loads 报"
            "「不是合法 JSON」。数据不会被覆盖，但提示不够直观。"
        ),
        "suggestion": "读取时改用 utf-8-sig，或在错误文案中提示「文件带 BOM」。",
        "code": "text = raw_bytes.decode(\"utf-8-sig\")",
    },
]

GOOD_POINTS = [
    "分层清晰：入口 → 命令 → 领域纯函数 → 读写，数据层不碰 stdout，职责单一。",
    "原子写入完整：同目录 mkstemp → json.dump → flush → fsync → os.replace，失败清理临时文件且原文件不变。",
    "损坏数据保护扎实：严格 UTF-8、结构校验、重复 id 检测，绝不覆盖原文件。",
    "参数解析手写，错误文案与退出码统一为「错误: 」+ 1，符合 PRD F6。",
    "编码修复到位：入口 reconfigure UTF-8，子进程用真实 gbk 管道验证 emoji，不依赖 PYTHONUTF8。",
    "BUG-01 修复完整：输出阶段纳入 try，断管道/孤立代理项均退 1、无 traceback、无 120。",
    "测试充分：76 条 unittest + 64 条独立黑盒，覆盖幂等、id 不复用、原子性、损坏文件。",
    "零第三方依赖，单文件 471 行，注释与文档齐全，便于维护。",
]

IMPROVEMENTS = [
    {
        "title": "统一输出出口，明确异常归属",
        "description": "把 print/flush 封装为 _emit(output)，只在该函数内处理断管/编码异常；main 的 OSError 分支随之收敛，避免把数据层 OSError 误判为输出问题。",
        "code": "if output:\n    _emit(output)",
    },
    {
        "title": "补充控制字符与 BOM 的数据文件约定",
        "description": "在 README「数据文件」一节说明换行/回车会被拒绝（或转义）、BOM 不受支持；减少用户手改 JSON 时的困惑。",
        "code": "## 数据文件\n- 内容不得包含换行/回车；文件不要保存为带 BOM 的 UTF-8。",
    },
]


def issue_html(item: dict) -> str:
    e = html.escape
    code = f"<pre><code>{e(item['code'])}</code></pre>" if item.get("code") else ""
    return (
        f'<div class="issue {item["class"]}">'
        '<div class="issue-header">'
        f'<span class="severity-badge {item["class"]}">{item["label"]}</span>'
        f'<span class="issue-location">{e(item["location"])}</span>'
        "</div>"
        f"<h4>{e(item['title'])}</h4>"
        f'<div class="issue-description">{e(item["description"])}</div>'
        '<div class="issue-suggestion">'
        f"<strong>修复建议：</strong>{e(item['suggestion'])}"
        f"{code}"
        "</div></div>"
    )


def good_html(text: str) -> str:
    return f'<div class="good-point">{html.escape(text)}</div>'


def improvement_html(item: dict) -> str:
    return (
        '<div class="issue-suggestion">'
        f"<h4>{html.escape(item['title'])}</h4>"
        f"<p>{html.escape(item['description'])}</p>"
        f"<pre><code>{html.escape(item['code'])}</code></pre>"
        "</div>"
    )


def main() -> int:
    now = datetime.now()
    timestamp = now.isoformat(timespec="seconds")
    filename = f"code-review-report-{now.strftime('%Y%m%d%H%M%S')}.html"
    output = ROOT / "docs" / "review" / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    critical = sum(1 for i in ISSUES if i["class"] == "critical")
    medium = sum(1 for i in ISSUES if i["class"] == "medium")
    minor = sum(1 for i in ISSUES if i["class"] == "minor")

    summary = (
        "总体评分 9/10：分层清晰、原子写入与损坏数据保护扎实；76 条 unittest + "
        "64 条独立黑盒全绿，审查无严重/中等问题，发现 4 处轻微改进。审查前已修复"
        "并回归 BUG-01（输出阶段异常导致 traceback / 退出码 120）。"
    )

    replacements = {
        "{{report_title}}": html.escape("代码审查报告 - item.py（deepseek-item-test v0.1）"),
        "{{review_timestamp}}": html.escape(timestamp),
        "{{total_score}}": "9",
        "{{total_score_percent}}": "90%",
        "{{summary_description}}": html.escape(summary),
        "{{critical_count}}": str(critical),
        "{{medium_count}}": str(medium),
        "{{minor_count}}": str(minor),
        "{{good_points_count}}": str(len(GOOD_POINTS)),
        "{{code_quality_score}}": "9",
        "{{security_score}}": "10",
        "{{performance_score}}": "9",
        "{{maintainability_score}}": "9",
        "{{critical_issues}}": '<p style="color: #27ae60;">🎉 未发现严重问题！</p>',
        "{{medium_issues}}": '<p style="color: #27ae60;">🎉 未发现中等问题！</p>',
        "{{minor_issues}}": "".join(issue_html(i) for i in ISSUES)
        if ISSUES
        else '<p style="color: #27ae60;">🎉 未发现轻微问题！</p>',
        "{{good_points}}": "".join(good_html(g) for g in GOOD_POINTS)
        if GOOD_POINTS
        else '<p style="color: #666;">暂无特别突出的优点。</p>',
        "{{improvement_suggestions}}": "".join(improvement_html(i) for i in IMPROVEMENTS),
    }

    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)

    if "{{" in text:
        print("未填充的占位符: " + ", ".join(sorted(set(t for t in text.split("{{")[1:]))))
        return 1

    output.write_text(text, encoding="utf-8")
    print(f"report={output}")
    print(f"critical={critical} medium={medium} minor={minor} good={len(GOOD_POINTS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
