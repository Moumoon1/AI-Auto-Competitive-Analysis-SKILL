#!/usr/bin/env python3
"""Run local macOS Vision OCR and optionally find an exact text target."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def run_vision(image: Path) -> list[dict]:
    source = Path(__file__).with_name("vision_ocr.swift")
    swift = shutil.which("swift")
    if not swift:
        raise RuntimeError("swift is not installed; local Vision OCR is unavailable")
    cache_root = Path("/private/tmp/app-experience-agent-swift-cache")
    (cache_root / "clang").mkdir(parents=True, exist_ok=True)
    (cache_root / "swift").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("CLANG_MODULE_CACHE_PATH", str(cache_root / "clang"))
    env.setdefault("SWIFT_MODULECACHE_PATH", str(cache_root / "swift"))
    proc = subprocess.run(
        [swift, str(source), str(image)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(detail or f"Vision OCR exited with {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vision OCR returned invalid JSON: {exc}") from exc
    return data if isinstance(data, list) else []


def compact(text: str) -> str:
    return "".join(text.split()).casefold()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--query", help="exact or contained text to locate")
    parser.add_argument("--min-confidence", type=float, default=0.35)
    args = parser.parse_args()

    if not args.image.is_file():
        print(json.dumps({"error": f"image not found: {args.image}"}, ensure_ascii=False))
        return 2

    try:
        items = [
            item
            for item in run_vision(args.image)
            if float(item.get("confidence", 0)) >= args.min_confidence
        ]
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    if args.query:
        wanted = compact(args.query)
        matches = []
        for item in items:
            text = compact(str(item.get("text", "")))
            if text == wanted or wanted in text:
                item = dict(item)
                item["centerX"] = round(float(item["x"]) + float(item["width"]) / 2, 1)
                item["centerY"] = round(float(item["y"]) + float(item["height"]) / 2, 1)
                matches.append(item)
        matches.sort(key=lambda item: (-float(item.get("confidence", 0)), item["centerY"]))
        output = {"query": args.query, "matches": matches, "count": len(matches)}
    else:
        output = {"items": items, "count": len(items)}

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
