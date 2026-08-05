#!/usr/bin/env python3
"""Run agent-device while keeping the local ADB server alive in this process."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 scripts/run_agent_device.py <agent-device 命令和参数>")
    adb = os.environ.get("ADB", "adb")
    if shutil.which(adb) is None:
        raise SystemExit("找不到 adb")
    if shutil.which("agent-device") is None:
        raise SystemExit("找不到 agent-device，请先安装官方 CLI")
    server = subprocess.Popen([adb, "nodaemon", "server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    try:
        result = subprocess.run(["agent-device", *sys.argv[1:]])
        return result.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
