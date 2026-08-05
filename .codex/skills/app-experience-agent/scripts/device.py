#!/usr/bin/env python3
"""Small, explicit ADB wrapper for Codex-led Android app experience runs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = SKILL_DIR / "runs"
_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def adb_path() -> str:
    value = os.environ.get("ADB", "adb")
    if shutil.which(value) is None and not Path(value).exists():
        raise SystemExit("找不到 adb。请安装 Android Platform Tools，或设置 ADB 环境变量。")
    return value


def start_local_adb_server() -> None:
    """Keep the ADB server in this process so the desktop sandbox does not reap it."""
    global _SERVER_PROCESS
    # Reuse a healthy server, including one started by agent-device. Starting
    # a second nodaemon server on tcp:5037 can race the existing daemon and
    # make a subsequent get-state look like a disconnected device.
    try:
        probe = subprocess.run(
            [adb_path(), "get-state"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if probe.returncode == 0:
            return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process = subprocess.Popen([adb_path(), "nodaemon", "server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return
    time.sleep(0.35)
    if process.poll() is None:
        _SERVER_PROCESS = process


def stop_local_adb_server() -> None:
    if _SERVER_PROCESS is None:
        return
    _SERVER_PROCESS.terminate()
    try:
        _SERVER_PROCESS.wait(timeout=2)
    except subprocess.TimeoutExpired:
        _SERVER_PROCESS.kill()


def adb(*args: str, binary: bool = False) -> bytes | str:
    command = [adb_path(), *args]
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"ADB 命令失败: {' '.join(command)}\n{stderr}") from exc
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def adb_best_effort(*args: str) -> None:
    """Run a command whose client may be reaped after the device completes it."""
    subprocess.run([adb_path(), *args], capture_output=True, timeout=12)


def require_run(path: str) -> Path:
    run = Path(path).expanduser().resolve()
    if not (run / "manifest.json").exists():
        raise SystemExit(f"不是有效的 run 目录: {run}")
    (run / "evidence").mkdir(exist_ok=True)
    return run


def append_event(run: Path, event: dict[str, Any]) -> None:
    event = {"timestamp": now(), **event}
    with (run / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def next_step(run: Path) -> int:
    events = run / "events.jsonl"
    if not events.exists():
        return 1
    return sum(1 for line in events.read_text(encoding="utf-8").splitlines() if line.strip()) + 1


def png_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        return None, None
    return struct.unpack(">II", data[16:24])


def device_screen_size() -> tuple[int, int]:
    raw = str(adb("shell", "wm", "size"))
    matches = re.findall(r"(\d+)x(\d+)", raw)
    if not matches:
        raise SystemExit(f"无法读取设备屏幕尺寸: {raw.strip()}")
    width, height = matches[-1]
    return int(width), int(height)


def dump_ui() -> str:
    remote = "/sdcard/codex-window.xml"
    adb("shell", "uiautomator", "dump", remote)
    return str(adb("exec-out", "cat", remote))


def capture(run: Path, title: str, reason: str, save_ui: bool = False) -> Path:
    step = next_step(run)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"evidence-{step:03d}-{stamp}"
    image_path = run / "evidence" / f"{stem}.png"
    remote_image = f"/sdcard/codex-{stem}.png"
    # On some ColorOS builds the screencap client exits with SIGTERM after the
    # remote file has already been written. Pulling the file is the real check.
    adb_best_effort("shell", "screencap", "-p", remote_image)
    adb("pull", remote_image, str(image_path))
    adb_best_effort("shell", "rm", "-f", remote_image)
    image = image_path.read_bytes()
    image_width, image_height = png_dimensions(image)
    ui_path = None
    if save_ui:
        ui_path = run / "evidence" / f"{stem}.xml"
        ui_path.write_text(dump_ui(), encoding="utf-8")
    metadata = {
        "step": step,
        "title": title,
        "reason": reason,
        "image": image_path.name,
        "ui_dump": ui_path.name if ui_path else None,
        "sha256_16": hashlib.sha256(image).hexdigest()[:16],
        "image_width": image_width,
        "image_height": image_height,
        "timestamp": now(),
    }
    (run / "evidence" / f"{stem}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(run, {"kind": "evidence", **metadata})
    print(image_path)
    return image_path


def encode_input(text: str) -> str:
    return text.replace("%", "%25").replace(" ", "%s")


def cmd_status(_: argparse.Namespace) -> None:
    print(adb("devices", "-l"), end="")


def cmd_screen_size(_: argparse.Namespace) -> None:
    width, height = device_screen_size()
    print(json.dumps({"width": width, "height": height}, ensure_ascii=False))


def cmd_start_run(args: argparse.Namespace) -> None:
    DEFAULT_RUNS.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", args.title).strip("-").lower() or "app-experience"
    run = DEFAULT_RUNS / f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"
    (run / "evidence").mkdir(parents=True)
    manifest = {"title": args.title, "task": args.task, "package": args.package, "started_at": now(), "status": "running", "device": str(adb("get-state")).strip()}
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(run, {"kind": "run_started", "title": args.title, "task": args.task})
    print(run)


def cmd_screenshot(args: argparse.Namespace) -> None:
    capture(require_run(args.run), args.title, args.reason, args.with_ui)


def cmd_dump_ui(args: argparse.Namespace) -> None:
    run = require_run(args.run)
    path = run / "ui-latest.xml"
    path.write_text(dump_ui(), encoding="utf-8")
    append_event(run, {"kind": "ui_dump", "path": path.name})
    print(path)


def log_action(args: argparse.Namespace, action: dict[str, Any]) -> None:
    run = require_run(args.run)
    append_event(run, {"kind": "action", **action})
    print(json.dumps(action, ensure_ascii=False))


def cmd_tap(args: argparse.Namespace) -> None:
    adb("shell", "input", "tap", str(args.x), str(args.y))
    log_action(args, {"type": "tap", "x": args.x, "y": args.y, "reason": args.reason})


def cmd_tap_ratio(args: argparse.Namespace) -> None:
    if not 0 <= args.x_ratio <= 1 or not 0 <= args.y_ratio <= 1:
        raise SystemExit("x-ratio 和 y-ratio 必须在 0 到 1 之间")
    width, height = device_screen_size()
    x = round(args.x_ratio * (width - 1))
    y = round(args.y_ratio * (height - 1))
    adb("shell", "input", "tap", str(x), str(y))
    log_action(args, {
        "type": "tap",
        "x": x,
        "y": y,
        "coordinate_mode": "screen_ratio",
        "x_ratio": args.x_ratio,
        "y_ratio": args.y_ratio,
        "screen_size": [width, height],
        "reason": args.reason,
    })


def cmd_swipe(args: argparse.Namespace) -> None:
    adb("shell", "input", "swipe", str(args.x1), str(args.y1), str(args.x2), str(args.y2), str(args.duration_ms))
    log_action(args, {"type": "swipe", "from": [args.x1, args.y1], "to": [args.x2, args.y2], "duration_ms": args.duration_ms, "reason": args.reason})


def cmd_input(args: argparse.Namespace) -> None:
    if any(token in args.text.lower() for token in ("password", "otp", "验证码", "密码")):
        raise SystemExit("拒绝输入疑似敏感文本。请使用普通非敏感测试文本。")
    adb("shell", "input", "text", encode_input(args.text))
    log_action(args, {"type": "input_text", "text_length": len(args.text), "reason": args.reason})


def cmd_key(args: argparse.Namespace) -> None:
    allowed = {"BACK": "4", "HOME": "3", "ENTER": "66"}
    key = args.key.upper()
    if key not in allowed:
        raise SystemExit("key 只支持 BACK、HOME、ENTER")
    adb("shell", "input", "keyevent", allowed[key])
    log_action(args, {"type": "key", "key": key, "reason": args.reason})


def cmd_wait(args: argparse.Namespace) -> None:
    if not 0 <= args.seconds <= 10:
        raise SystemExit("等待时间必须在 0 到 10 秒之间")
    time.sleep(args.seconds)
    log_action(args, {"type": "wait", "seconds": args.seconds, "reason": args.reason})


def cmd_launch(args: argparse.Namespace) -> None:
    adb("shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1")
    log_action(args, {"type": "launch", "package": args.package, "reason": args.reason})


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Codex-led Android experience ADB tools")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("screen-size").set_defaults(func=cmd_screen_size)
    start = sub.add_parser("start-run")
    start.add_argument("--title", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--package")
    start.set_defaults(func=cmd_start_run)
    shot = sub.add_parser("screenshot")
    shot.add_argument("--run", required=True)
    shot.add_argument("--title", required=True)
    shot.add_argument("--reason", required=True)
    shot.add_argument("--with-ui", action="store_true")
    shot.set_defaults(func=cmd_screenshot)
    ui = sub.add_parser("dump-ui")
    ui.add_argument("--run", required=True)
    ui.set_defaults(func=cmd_dump_ui)
    tap = sub.add_parser("tap")
    tap.add_argument("--run", required=True)
    tap.add_argument("x", type=int)
    tap.add_argument("y", type=int)
    tap.add_argument("--reason", required=True)
    tap.set_defaults(func=cmd_tap)
    tap_ratio = sub.add_parser("tap-ratio")
    tap_ratio.add_argument("--run", required=True)
    tap_ratio.add_argument("x_ratio", type=float)
    tap_ratio.add_argument("y_ratio", type=float)
    tap_ratio.add_argument("--reason", required=True)
    tap_ratio.set_defaults(func=cmd_tap_ratio)
    swipe = sub.add_parser("swipe")
    swipe.add_argument("--run", required=True)
    swipe.add_argument("x1", type=int)
    swipe.add_argument("y1", type=int)
    swipe.add_argument("x2", type=int)
    swipe.add_argument("y2", type=int)
    swipe.add_argument("--duration-ms", type=int, default=450)
    swipe.add_argument("--reason", required=True)
    swipe.set_defaults(func=cmd_swipe)
    inp = sub.add_parser("input")
    inp.add_argument("--run", required=True)
    inp.add_argument("--text", required=True)
    inp.add_argument("--reason", required=True)
    inp.set_defaults(func=cmd_input)
    key = sub.add_parser("key")
    key.add_argument("--run", required=True)
    key.add_argument("key")
    key.add_argument("--reason", required=True)
    key.set_defaults(func=cmd_key)
    wait = sub.add_parser("wait")
    wait.add_argument("--run", required=True)
    wait.add_argument("--seconds", type=float, default=1)
    wait.add_argument("--reason", required=True)
    wait.set_defaults(func=cmd_wait)
    launch = sub.add_parser("launch")
    launch.add_argument("--run", required=True)
    launch.add_argument("--package", required=True)
    launch.add_argument("--reason", required=True)
    launch.set_defaults(func=cmd_launch)
    return p


if __name__ == "__main__":
    args = parser().parse_args()
    start_local_adb_server()
    try:
        args.func(args)
    finally:
        stop_local_adb_server()
