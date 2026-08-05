#!/usr/bin/env python3
"""Render an App Experience Agent run as Markdown and standalone HTML."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path


def read_events(run: Path) -> list[dict]:
    path = run / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evidence(run: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run / "evidence").glob("*.json"))]


def render(run: Path) -> tuple[str, str]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    events = read_events(run)
    shots = evidence(run)
    title = manifest.get("title", "App Experience Run")
    task = manifest.get("task", "")
    actions = [e for e in events if e.get("kind") == "action"]
    md = [f"# App 体验走查报告：{title}", "", "## 任务", "", task or "（未填写）", "", "## 执行概览", "", f"- 证据截图：{len(shots)}", "", "## 操作时间线", ""]
    if not actions:
        md.append("暂无操作记录。")
    else:
        for index, event in enumerate(actions, 1):
            action = event.get("type", "unknown")
            reason = event.get("reason", "")
            detail = ""
            if action == "tap":
                detail = f" ({event.get('x')}, {event.get('y')})"
            elif action == "swipe":
                detail = f" {event.get('from')} → {event.get('to')}"
            elif action == "input_text":
                detail = f"（输入 {event.get('text_length', 0)} 个字符，内容未记录）"
            md.append(f"{index}. `{action}`{detail} — {reason}")
    md.extend(["", "## 关键页面证据", ""])
    if not shots:
        md.append("暂无截图证据。")
    else:
        for shot in shots:
            image = f"evidence/{shot['image']}"
            md.extend([f"### {shot.get('title', '未命名页面')}", "", shot.get("reason", ""), "", f"![{shot.get('title', 'evidence')}]({image})", ""])
    md.extend([
        "## 功能模块与体验分析（必须补全）",
        "",
        "| 功能模块 | 作用 | 已确认内容 | UI/UX 印象 |",
        "|---|---|---|---|",
        "| | | | 清晰 / 一般 / 突出问题 |",
        "",
        "### UI/UX 优点",
        "",
        "- 补充 2–5 个最突出的优点，并引用对应截图。",
        "",
        "### UI/UX 问题与改进建议",
        "",
        "- `[High/Medium/Low] 问题 — 证据 — 影响 — 具体建议`",
        "",
        "### 未验证范围",
        "",
        "- 列出未访问的模块，以及未点击的领取、购买、激活或账户操作。",
        "",
        f"生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
    ])
    markdown = "\n".join(md) + "\n"

    rows = [f"<li><code>{html.escape(str(event.get('type', 'unknown')))}</code> — {html.escape(str(event.get('reason', '')))}</li>" for event in actions]
    cards = [f"<article><h3>{html.escape(str(shot.get('title', '未命名页面')))}</h3><p>{html.escape(str(shot.get('reason', '')))}</p><img src=\"evidence/{html.escape(shot['image'])}\" alt=\"evidence\"></article>" for shot in shots]
    timeline = "".join(rows) or "<li>暂无操作记录</li>"
    evidence_cards = "".join(cards) or "<p>暂无截图证据。</p>"
    document = f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>{html.escape(title)}</title>
<style>body{{font:16px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;max-width:980px;margin:40px auto;padding:0 20px;color:#1f2937}}article{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:16px 0}}img{{max-width:100%;border:1px solid #d1d5db;border-radius:8px}}code{{background:#f3f4f6;padding:2px 5px;border-radius:4px}}</style>
<body><h1>App 体验走查报告：{html.escape(title)}</h1><h2>任务</h2><p>{html.escape(task)}</p><h2>执行概览</h2><ul><li>证据截图：{len(shots)}</li></ul><h2>操作时间线</h2><ol>{timeline}</ol><h2>关键页面证据</h2>{evidence_cards}<h2>功能模块与体验分析（必须补全）</h2><table><tr><th>功能模块</th><th>作用</th><th>已确认内容</th><th>UI/UX 印象</th></tr><tr><td></td><td></td><td></td><td>清晰 / 一般 / 突出问题</td></tr></table><h3>UI/UX 优点</h3><p>补充 2–5 个最突出的优点，并引用截图。</p><h3>UI/UX 问题与改进建议</h3><p>[High/Medium/Low] 问题 — 证据 — 影响 — 具体建议</p><h3>未验证范围</h3><p>列出未访问模块和未点击的高风险操作。</p></body></html>"""
    return markdown, document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run).expanduser().resolve()
    if not (run / "manifest.json").exists():
        raise SystemExit(f"不是有效的 run 目录: {run}")
    markdown, document = render(run)
    (run / "report.md").write_text(markdown, encoding="utf-8")
    (run / "report.html").write_text(document, encoding="utf-8")
    print(run / "report.md")
    print(run / "report.html")


if __name__ == "__main__":
    main()
