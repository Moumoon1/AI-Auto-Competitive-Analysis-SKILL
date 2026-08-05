#!/usr/bin/env python3
"""Check or prepare the local runtime for Codex-driven Android exploration."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SKILL = "callstackincubator/agent-device"
MIN_AGENT_DEVICE = (0, 14, 0)
DEFAULT_AGENT_DEVICE_VERSION = "0.20.5"


def run(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        return 127, str(exc)
    output = (result.stdout or result.stderr).strip()
    return result.returncode, output


def version_tuple(value: str) -> tuple[int, ...] | None:
    parts = value.strip().lstrip("v").split(".")
    numbers: list[int] = []
    for part in parts:
        digits = "".join(char for char in part if char.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers) if len(numbers) >= 2 else None


def resolve_adb() -> str | None:
    """Find adb on PATH or in common Android SDK locations."""
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
    return None


def check_command(name: str, command: list[str]) -> dict[str, object]:
    path = shutil.which(command[0])
    if not path:
        return {"name": name, "ok": False, "message": f"missing: {command[0]}"}
    code, output = run(command)
    return {
        "name": name,
        "ok": code == 0,
        "path": path,
        "message": output.splitlines()[0] if output else f"exit {code}",
    }


def device_check() -> dict[str, object]:
    adb = resolve_adb()
    if not adb:
        return {"name": "android-device", "ok": False, "message": "adb missing"}
    code, output = run([adb, "devices", "-l"])
    devices = []
    for line in output.splitlines():
        if "\tdevice" in line:
            devices.append(line.split()[0])
    return {
        "name": "android-device",
        "ok": code == 0 and bool(devices),
        "devices": devices,
        "message": "authorized device connected" if devices else "no authorized device",
    }


def checks() -> list[dict[str, object]]:
    adb = resolve_adb()
    results = [
        check_command("node", ["node", "--version"]),
        check_command("npm", ["npm", "--version"]),
        check_command("npx", ["npx", "--version"]),
        check_command("adb", [adb, "version"] if adb else ["adb", "version"]),
        check_command("agent-device", ["agent-device", "--version"]),
        device_check(),
    ]
    agent = next(item for item in results if item["name"] == "agent-device")
    if agent["ok"]:
        parsed = version_tuple(str(agent["message"]))
        agent["supported"] = parsed is not None and parsed >= MIN_AGENT_DEVICE
        agent["ok"] = bool(agent["ok"] and agent["supported"])
        if not agent["supported"]:
            agent["message"] += f" (requires >= {'.'.join(map(str, MIN_AGENT_DEVICE))})"
    skill_path = ROOT.parents[3] / ".agents" / "skills" / "dogfood" / "SKILL.md"
    results.append({
        "name": "official-dogfood-skill",
        "ok": skill_path.exists(),
        "path": str(skill_path),
        "message": "installed" if skill_path.exists() else "not installed",
    })
    return results


def install_adb() -> int:
    """Install Android Platform Tools through an available package manager."""
    if resolve_adb():
        print("ADB 已安装，跳过。")
        return 0

    system = platform.system()
    if system == "Darwin":
        brew = shutil.which("brew")
        if brew:
            print("安装 Android Platform Tools（Homebrew）…")
            code, output = run([brew, "install", "android-platform-tools"])
            if output:
                print(output)
            return code
    elif system == "Linux":
        apt = shutil.which("apt-get")
        if apt:
            print("安装 Android Platform Tools（apt）…")
            code, output = run(["sudo", apt, "update"])
            if output:
                print(output)
            if code:
                return code
            code, output = run(["sudo", apt, "install", "-y", "adb"])
            if output:
                print(output)
            return code
    elif system == "Windows":
        winget = shutil.which("winget")
        if winget:
            print("安装 Android Platform Tools（WinGet）…")
            code, output = run([
                winget,
                "install",
                "--id",
                "Google.PlatformTools",
                "--exact",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ])
            if output:
                print(output)
            return code

    print(
        f"当前系统（{system or 'unknown'}）没有可用的自动安装方式。请安装 Android Platform Tools 后重新运行检查："
        " https://developer.android.com/tools/releases/platform-tools",
        file=sys.stderr,
    )
    return 3


def install(version: str, include_adb: bool) -> int:
    required = ["npm", "npx"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        print(f"缺少安装工具：{', '.join(missing)}。请先安装 Node.js。", file=sys.stderr)
        return 2

    print(f"安装官方 agent-device CLI {version}…")
    code, output = run(["npm", "install", "--global", f"agent-device@{version}"])
    if output:
        print(output)
    if code:
        return code

    if include_adb:
        code = install_adb()
        if code:
            return code

    print("安装官方 dogfood Skill…")
    code, output = run(["npx", "--yes", "skills", "add", OFFICIAL_SKILL, "--skill", "dogfood"])
    if output:
        print(output)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="检查或准备 app-experience-agent 运行环境")
    parser.add_argument("--install", action="store_true", help="安装 agent-device、dogfood Skill 和 Android Platform Tools")
    parser.add_argument("--install-adb", action="store_true", help="只安装 Android Platform Tools")
    parser.add_argument("--agent-device-version", default=DEFAULT_AGENT_DEVICE_VERSION, help=f"要安装的 agent-device 版本，默认 {DEFAULT_AGENT_DEVICE_VERSION}")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    args = parser.parse_args()

    if args.install:
        status = install(args.agent_device_version, include_adb=True)
        if status:
            return status
    elif args.install_adb:
        status = install_adb()
        if status:
            return status

    result = checks()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result:
            marker = "OK" if item["ok"] else "!!"
            print(f"[{marker}] {item['name']}: {item.get('message', '')}")
        print("提示：首次 snapshot 可能需要安装 Android snapshot helper；OPPO/ColorOS 设备可能需要额外兼容处理。")
    return 0 if all(bool(item["ok"]) for item in result if item["name"] != "android-device") else 1


if __name__ == "__main__":
    raise SystemExit(main())
