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
import zlib
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # Pillow is optional; the bundled PNG fallback remains available.
    Image = None  # type: ignore[assignment]


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = SKILL_DIR / "runs"
_SERVER_PROCESS: subprocess.Popen[bytes] | None = None
ADB_COMMAND_TIMEOUT = 8.0
ADB_INPUT_TIMEOUT = 5.0
ADB_BEST_EFFORT_TIMEOUT = 8.0


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def adb_path() -> str:
    configured = os.environ.get("ADB")
    if configured:
        if shutil.which(configured) or Path(configured).exists():
            return configured
        raise SystemExit(f"ADB 环境变量指向的路径不可用：{configured}")

    on_path = shutil.which("adb")
    if on_path:
        return on_path

    candidates = [
        Path.home() / ".codex" / "android-platform-tools" / "platform-tools" / "adb",
        Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise SystemExit("找不到 adb。请运行 bootstrap.py --install，或设置 ADB 环境变量。")


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
    timeout = ADB_COMMAND_TIMEOUT
    if len(args) >= 2 and args[0] == "shell" and args[1] in {"input", "uiautomator"}:
        timeout = ADB_INPUT_TIMEOUT
    try:
        result = subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            f"ADB 命令超时（{timeout:g} 秒），已终止本次操作: {' '.join(command)}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"ADB 命令失败: {' '.join(command)}\n{stderr}") from exc
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def adb_best_effort(*args: str) -> None:
    """Run a command whose client may be reaped after the device completes it."""
    try:
        subprocess.run([adb_path(), *args], capture_output=True, timeout=ADB_BEST_EFFORT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return


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


def png_sample(path: Path, columns: int = 48, rows_count: int = 64) -> list[tuple[int, int, int]]:
    """Decode a small RGB sample from an 8-bit, non-interlaced PNG."""
    if Image is not None:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            top = int(rgb.height * 0.08)
            bottom = int(rgb.height * 0.92)
            resampling = getattr(Image, "Resampling", Image).BILINEAR
            reduced = rgb.crop((0, top, rgb.width, bottom)).resize((columns, rows_count), resampling)
            return list(reduced.getdata())

    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 文件")
    cursor = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while cursor + 8 <= len(data):
        length = struct.unpack(">I", data[cursor:cursor + 4])[0]
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:cursor + 8 + length]
        cursor += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or interlace != 0:
        raise ValueError("只支持 8-bit 非交错 PNG")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError(f"不支持的 PNG 色彩类型: {color_type}")
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    decoded: list[bytearray] = []
    offset = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        current = bytearray(raw[offset:offset + stride])
        offset += stride
        for index in range(stride):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 255
            elif filter_type == 2:
                current[index] = (current[index] + up) & 255
            elif filter_type == 3:
                current[index] = (current[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
                current[index] = (current[index] + predictor) & 255
            elif filter_type != 0:
                raise ValueError(f"不支持的 PNG filter: {filter_type}")
        decoded.append(current)
        previous = current

    top = max(0, int(height * 0.08))
    bottom = min(height, int(height * 0.92))
    sample: list[tuple[int, int, int]] = []
    for row_index in range(rows_count):
        y = min(bottom - 1, top + ((row_index * 2 + 1) * (bottom - top) // (rows_count * 2)))
        scanline = decoded[y]
        for column_index in range(columns):
            x = min(width - 1, (column_index * 2 + 1) * width // (columns * 2))
            offset = x * channels
            if color_type == 0:
                rgb = (scanline[offset],) * 3
            elif color_type == 2:
                rgb = tuple(scanline[offset:offset + 3])
            elif color_type == 4:
                rgb = (scanline[offset],) * 3
            else:
                rgb = tuple(scanline[offset:offset + 3])
            sample.append(rgb)  # type: ignore[arg-type]
    return sample


def image_difference(first: Path, second: Path) -> float:
    """Return normalized central-screen pixel difference in the range 0..1."""
    first_sample = png_sample(first)
    second_sample = png_sample(second)
    if len(first_sample) != len(second_sample):
        return 1.0
    if not first_sample:
        return 0.0
    total = sum(
        abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])
        for left, right in zip(first_sample, second_sample)
    )
    return total / (len(first_sample) * 3 * 255)


def latest_evidence_image(run: Path) -> Path | None:
    for metadata_path in reversed(sorted((run / "evidence").glob("*.json"))):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        image = run / "evidence" / str(metadata.get("image", ""))
        if image.is_file():
            return image
    return None


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


def cmd_swipe_check(args: argparse.Namespace) -> None:
    """Swipe once and retain a screenshot only when the central content changes."""
    run = require_run(args.run)
    previous = latest_evidence_image(run)
    if previous is None:
        raise SystemExit("swipe-check 需要先有一张当前页面截图")
    adb("shell", "input", "swipe", str(args.x1), str(args.y1), str(args.x2), str(args.y2), str(args.duration_ms))
    append_event(run, {"kind": "action", "type": "swipe", "from": [args.x1, args.y1], "to": [args.x2, args.y2], "duration_ms": args.duration_ms, "reason": args.reason})
    time.sleep(args.wait_seconds)
    candidate = capture(run, args.title, args.reason, args.with_ui)
    try:
        difference = image_difference(previous, candidate)
    except (OSError, ValueError, struct.error, zlib.error) as exc:
        append_event(run, {"kind": "scroll_check", "changed": None, "comparison_error": str(exc), "image": candidate.name})
        print(json.dumps({"changed": None, "image": str(candidate), "message": "无法自动比较，请人工确认截图"}, ensure_ascii=False))
        return
    changed = difference > args.threshold
    if not changed:
        candidate_json = candidate.with_suffix(".json")
        candidate_xml = candidate.with_suffix(".xml")
        candidate.unlink(missing_ok=True)
        candidate_json.unlink(missing_ok=True)
        candidate_xml.unlink(missing_ok=True)
    append_event(run, {"kind": "scroll_check", "changed": changed, "difference": round(difference, 6), "threshold": args.threshold, "discarded_image": None if changed else candidate.name})
    print(json.dumps({"changed": changed, "difference": round(difference, 6), "threshold": args.threshold, "image": str(candidate) if changed else None}, ensure_ascii=False))


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
    swipe_check = sub.add_parser("swipe-check")
    swipe_check.add_argument("--run", required=True)
    swipe_check.add_argument("x1", type=int)
    swipe_check.add_argument("y1", type=int)
    swipe_check.add_argument("x2", type=int)
    swipe_check.add_argument("y2", type=int)
    swipe_check.add_argument("--duration-ms", type=int, default=450)
    swipe_check.add_argument("--wait-seconds", type=float, default=0.8)
    swipe_check.add_argument("--threshold", type=float, default=0.02)
    swipe_check.add_argument("--title", required=True)
    swipe_check.add_argument("--reason", required=True)
    swipe_check.add_argument("--with-ui", action="store_true")
    swipe_check.set_defaults(func=cmd_swipe_check)
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
