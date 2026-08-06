#!/usr/bin/env python3
"""Check or prepare the local runtime for Codex-driven Android exploration."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SKILL = "callstackincubator/agent-device"
MIN_AGENT_DEVICE = (0, 14, 0)
DEFAULT_AGENT_DEVICE_VERSION = "0.20.5"
SNAPSHOT_HELPER_PACKAGE = "com.callstack.agentdevice.snapshothelper"
USER_NPM_PREFIX = Path.home() / ".codex" / "npm-global"
ANDROID_TOOLS_DIR = Path.home() / ".codex" / "android-platform-tools"
PLATFORM_TOOLS_BASE_URL = "https://dl.google.com/android/repository/platform-tools-latest-"


def run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
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
    """Find adb on PATH, in the user install, or in common SDK locations."""
    on_path = shutil.which("adb")
    if on_path:
        return on_path

    sdk_roots = [
        Path(value)
        for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT")
        if (value := os.environ.get(name))
    ]
    candidates = [
        ANDROID_TOOLS_DIR / "platform-tools" / "adb",
        Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
    ]
    candidates.extend(root / "platform-tools" / "adb" for root in sdk_roots)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_agent_device() -> str | None:
    """Find agent-device on PATH or in the user-local npm prefix."""
    on_path = shutil.which("agent-device")
    if on_path:
        return on_path

    candidates = [
        USER_NPM_PREFIX / "bin" / "agent-device",
        USER_NPM_PREFIX / "agent-device.cmd",
        Path.home() / "AppData" / "Roaming" / "npm" / "agent-device.cmd",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_dogfood_skill() -> Path | None:
    """Find the globally or project-installed official dogfood Skill."""
    candidates = [
        Path.home() / ".agents" / "skills" / "dogfood" / "SKILL.md",
        Path.cwd() / ".agents" / "skills" / "dogfood" / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
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
    unauthorized = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        if fields[1] == "device":
            devices.append(fields[0])
        elif fields[1] == "unauthorized":
            unauthorized.append(fields[0])
    if unauthorized:
        message = "device connected, USB debugging authorization required"
    else:
        message = "authorized device connected" if devices else "no authorized device"
    return {
        "name": "android-device",
        "ok": code == 0 and bool(devices),
        "devices": devices,
        "unauthorized": unauthorized,
        "message": message,
    }


def snapshot_helper_check() -> dict[str, object]:
    """Check the Android-side semantic snapshot helper, not just desktop tools."""
    adb = resolve_adb()
    if not adb:
        return {
            "name": "android-snapshot-helper",
            "ok": False,
            "package": SNAPSHOT_HELPER_PACKAGE,
            "message": "adb missing; install desktop tools first",
        }
    code, output = run([adb, "shell", "pm", "path", SNAPSHOT_HELPER_PACKAGE])
    installed = code == 0 and output.startswith("package:")
    return {
        "name": "android-snapshot-helper",
        "ok": installed,
        "package": SNAPSHOT_HELPER_PACKAGE,
        "message": "installed on Android device" if installed else "not installed on Android device",
    }


def checks() -> list[dict[str, object]]:
    adb = resolve_adb()
    agent_device = resolve_agent_device()
    results = [
        check_command("node", ["node", "--version"]),
        check_command("npm", ["npm", "--version"]),
        check_command("npx", ["npx", "--version"]),
        check_command("adb", [adb, "version"] if adb else ["adb", "version"]),
        check_command(
            "agent-device",
            [agent_device, "--version"] if agent_device else ["agent-device", "--version"],
        ),
        device_check(),
    ]
    agent = next(item for item in results if item["name"] == "agent-device")
    if agent["ok"]:
        parsed = version_tuple(str(agent["message"]))
        agent["supported"] = parsed is not None and parsed >= MIN_AGENT_DEVICE
        agent["ok"] = bool(agent["ok"] and agent["supported"])
        if not agent["supported"]:
            agent["message"] += f" (requires >= {'.'.join(map(str, MIN_AGENT_DEVICE))})"
    skill_path = resolve_dogfood_skill()
    results.append({
        "name": "official-dogfood-skill",
        "ok": skill_path is not None,
        "path": str(skill_path) if skill_path else str(Path.home() / ".agents" / "skills" / "dogfood" / "SKILL.md"),
        "message": "installed" if skill_path else "not installed",
    })
    results.append(snapshot_helper_check())
    return results


def platform_tools_url() -> str | None:
    suffixes = {
        "Darwin": "darwin.zip",
        "Linux": "linux.zip",
        "Windows": "windows.zip",
    }
    suffix = suffixes.get(platform.system())
    return f"{PLATFORM_TOOLS_BASE_URL}{suffix}" if suffix else None


def install_adb_direct() -> int:
    """Download Google's official Platform Tools into the user-local Codex directory."""
    url = platform_tools_url()
    if not url:
        print(f"当前系统（{platform.system() or 'unknown'}）没有可用的官方 Platform Tools 包。", file=sys.stderr)
        return 3

    curl = shutil.which("curl")
    if not curl:
        print("找不到 curl，无法下载 Google 官方 Platform Tools。", file=sys.stderr)
        return 3

    ANDROID_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-platform-tools-") as temp_dir:
        archive = Path(temp_dir) / "platform-tools.zip"
        print("从 Google 官方下载 Android Platform Tools…")
        code, output = run([curl, "-fL", "--retry", "2", "-o", str(archive), url])
        if output:
            print(output)
        if code:
            return code
        try:
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(ANDROID_TOOLS_DIR)
        except (OSError, zipfile.BadZipFile) as exc:
            print(f"Platform Tools 解压失败：{exc}", file=sys.stderr)
            return 4

    adb = resolve_adb()
    if not adb:
        print(f"下载完成，但未找到 adb。预期位置：{ANDROID_TOOLS_DIR / 'platform-tools'}", file=sys.stderr)
        return 4
    print(f"ADB 已安装到 {adb}")
    return 0


def install_adb() -> int:
    """Install Android Platform Tools without requiring Homebrew."""
    if resolve_adb():
        print("ADB 已安装，跳过。")
        return 0
    return install_adb_direct()


def install_agent_device(version: str) -> int:
    """Install agent-device into a user-local npm prefix to avoid system permissions."""
    npm = shutil.which("npm")
    if not npm:
        print("缺少安装工具：npm。请先安装 Node.js。", file=sys.stderr)
        return 2
    USER_NPM_PREFIX.mkdir(parents=True, exist_ok=True)
    print(f"安装官方 agent-device CLI {version} 到用户目录…")
    code, output = run([
        npm,
        "install",
        "--global",
        "--prefix",
        str(USER_NPM_PREFIX),
        f"agent-device@{version}",
    ])
    if output:
        print(output)
    return code


def install(version: str, include_adb: bool) -> int:
    status = install_agent_device(version)
    if status:
        return status

    if include_adb:
        status = install_adb()
        if status:
            return status

    npx = shutil.which("npx")
    if not npx:
        print("缺少安装工具：npx。请先安装 Node.js。", file=sys.stderr)
        return 2
    print("安装官方 dogfood Skill 到用户目录…")
    code, output = run([
        npx,
        "--yes",
        "skills",
        "add",
        OFFICIAL_SKILL,
        "--skill",
        "dogfood",
        "--global",
        "--agent",
        "codex",
        "--copy",
        "--yes",
    ])
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
        helper = next(item for item in result if item["name"] == "android-snapshot-helper")
        if not helper["ok"]:
            print("下一步：请在安卓手机上安装 Agent Device Snapshot Helper（不是只在电脑上安装工具）。")
            print(f"安卓端包名：{SNAPSHOT_HELPER_PACKAGE}。手机弹出安装界面时请点击“安装”，完成后重新运行本检查。")
        else:
            print("安卓端 Agent Device Snapshot Helper 已安装。")
        print("提示：OPPO/ColorOS 设备可能需要保持解锁，并重新确认 USB 调试授权。")
    return 0 if all(bool(item["ok"]) for item in result if item["name"] != "android-device") else 1


if __name__ == "__main__":
    raise SystemExit(main())
