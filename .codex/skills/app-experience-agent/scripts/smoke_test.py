#!/usr/bin/env python3
"""Offline smoke test for run metadata and report rendering."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    report = root / "scripts" / "report.py"
    with tempfile.TemporaryDirectory(prefix="app-experience-smoke-") as temp:
        run = Path(temp) / "run"
        evidence = run / "evidence"
        evidence.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({"title": "离线测试", "task": "验证报告生成", "device": "offline", "started_at": "test"}, ensure_ascii=False), encoding="utf-8")
        (run / "events.jsonl").write_text(json.dumps({"kind": "action", "type": "tap", "x": 10, "y": 20, "reason": "测试点击"}, ensure_ascii=False) + "\n", encoding="utf-8")
        (evidence / "evidence-001.json").write_text(json.dumps({"title": "测试页面", "reason": "测试证据", "image": "evidence-001.png"}, ensure_ascii=False), encoding="utf-8")
        (evidence / "evidence-001.png").write_bytes(PNG_1X1)
        subprocess.run([sys.executable, str(report), "--run", str(run)], check=True, capture_output=True, text=True)
        assert (run / "report.md").exists()
        assert (run / "report.html").exists()
        assert "测试页面" in (run / "report.md").read_text(encoding="utf-8")
    print("smoke test passed")


if __name__ == "__main__":
    main()
