#!/usr/bin/env python3
"""Copy a completed app-experience report to a user-visible output directory."""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import shutil
from pathlib import Path


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return value.strip("-._") or "app-experience-report"


def inline_markup(value: str, run_dir: Path) -> str:
    """Render the small Markdown subset used by the generated report."""
    escaped = html.escape(value)

    def image(match: re.Match[str]) -> str:
        alt = html.escape(match.group(1))
        relative = match.group(2)
        image_path = (run_dir / relative).resolve()
        if not image_path.is_file():
            return f'<span class="missing-image">[图片缺失：{alt}]</span>'
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f'<img class="report-image" src="data:{mime};base64,{data}" alt="{alt}">'

    escaped = re.sub(r"!\[([^]]*)\]\(([^)]+)\)", image, escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(markdown: str, run_dir: Path, title: str) -> str:
    lines = markdown.splitlines()
    body: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    table_rows: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            body.append(f"<p>{inline_markup(' '.join(paragraph), run_dir)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            body.append(f"</{list_tag}>")
            list_tag = None

    def flush_table() -> None:
        nonlocal table_rows
        if table_rows:
            body.append("<table>" + "".join(table_rows) + "</table>")
            table_rows = []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_paragraph()
            close_list()
            flush_table()
            continue
        image_line = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
        if image_line:
            flush_paragraph()
            close_list()
            flush_table()
            alt = html.escape(image_line.group(1))
            image_html = inline_markup(line, run_dir)
            body.append(f'<figure class="evidence-card">{image_html}<figcaption>{alt}</figcaption></figure>')
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            close_list()
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            tag = "th" if not table_rows else "td"
            table_rows.append("<tr>" + "".join(f"<{tag}>{inline_markup(cell, run_dir)}</{tag}>" for cell in cells) + "</tr>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            close_list()
            flush_table()
            level = len(heading.group(1))
            body.append(f"<h{level}>{inline_markup(heading.group(2), run_dir)}</h{level}>")
            continue
        ordered = re.match(r"^\d+\.\s+(.*)$", line)
        unordered = re.match(r"^[-*]\s+(.*)$", line)
        if ordered or unordered:
            flush_paragraph()
            flush_table()
            target = "ol" if ordered else "ul"
            if list_tag != target:
                close_list()
                body.append(f"<{target}>")
                list_tag = target
            body.append(f"<li>{inline_markup((ordered or unordered).group(1), run_dir)}</li>")
            continue
        close_list()
        flush_table()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    flush_table()
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{safe_title}</title>
<style>
body{{font:16px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;max-width:980px;margin:40px auto;padding:0 20px;color:#1f2937}}
article{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:16px 0}}
img{{max-width:100%;height:auto;border:1px solid #d1d5db;border-radius:8px;margin:12px 0}}
code{{background:#f3f4f6;padding:2px 5px;border-radius:4px}}
table{{border-collapse:collapse;width:100%;margin:16px 0}}th,td{{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top}}th{{background:#f3f4f6}}
.missing-image{{color:#b91c1c;background:#fef2f2;padding:4px 8px;border-radius:4px}}
.evidence-card{{display:inline-block;width:176px;vertical-align:top;margin:6px;padding:8px;border:1px solid #e5e7eb;border-radius:10px;background:#fff;cursor:zoom-in}}
.evidence-card .report-image{{display:block;width:160px;height:104px;object-fit:cover;margin:0}}
.evidence-card figcaption{{font-size:12px;line-height:1.35;margin-top:6px;color:#4b5563;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.lightbox{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);align-items:center;justify-content:center;z-index:10}}
.lightbox.open{{display:flex}}
.lightbox img{{max-width:94vw;max-height:90vh;object-fit:contain;border:0;margin:0}}
.lightbox button{{position:fixed;top:18px;right:24px;border:0;border-radius:50%;width:40px;height:40px;font-size:28px;line-height:1;background:#fff;color:#111;cursor:pointer}}
</style></head><body>{''.join(body)}
<div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="查看大图"><button id="lightbox-close" type="button" aria-label="关闭">×</button><img id="lightbox-image" alt=""></div>
<script>
const lightbox=document.getElementById('lightbox');
const lightboxImage=document.getElementById('lightbox-image');
function closeLightbox(){{lightbox.classList.remove('open');lightboxImage.src='';}}
document.querySelectorAll('.evidence-card .report-image').forEach((image)=>image.addEventListener('click',()=>{{lightboxImage.src=image.src;lightboxImage.alt=image.alt;lightbox.classList.add('open');}}));
document.getElementById('lightbox-close').addEventListener('click',closeLightbox);
lightbox.addEventListener('click',(event)=>{{if(event.target===lightbox)closeLightbox();}});
document.addEventListener('keydown',(event)=>{{if(event.key==='Escape')closeLightbox();}});
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="completed run directory")
    parser.add_argument("--output-dir", required=True, type=Path, help="user-visible output directory")
    parser.add_argument("--name", default="app-experience-report", help="output filename stem")
    args = parser.parse_args()

    run_dir = args.run.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not run_dir.is_dir():
        parser.error(f"run directory does not exist: {run_dir}")

    source_md = run_dir / "report.md"
    source_html = run_dir / "report.html"
    missing = [str(path) for path in (source_md, source_html) if not path.is_file()]
    if missing:
        parser.error("report files are missing; run scripts/report.py first: " + ", ".join(missing))

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_name(args.name)
    destinations = {
        "markdown": output_dir / f"{stem}.md",
        "html": output_dir / f"{stem}.html",
    }
    shutil.copy2(source_md, destinations["markdown"])
    manifest_path = run_dir / "manifest.json"
    title = "App Experience Run"
    if manifest_path.is_file():
        title = json.loads(manifest_path.read_text(encoding="utf-8")).get("title", title)
    destinations["html"].write_text(
        markdown_to_html(source_md.read_text(encoding="utf-8"), run_dir, str(title)),
        encoding="utf-8",
    )

    print(json.dumps({key: str(path) for key, path in destinations.items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
