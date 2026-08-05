---
name: app-experience-agent
description: Operate and evaluate an Android app from Codex through a local ADB-connected device. Use when the user wants Codex to inspect phone screenshots, choose safe taps/swipes/text input, record evidence, or generate an app-experience report without an external AI API.
---

# App Experience Agent

Use this skill when Codex is the AI operator and the Android phone is connected to the same computer over USB. Keep the control loop in the Codex task: capture a screenshot, inspect the current state, choose one bounded action, execute it with the bundled script, capture the result, and log evidence.

## Safety rules

- Do not perform payment, ordering, publishing, sending, deleting, subscribing, account changes, or other irreversible actions.
- Stop and ask the user before any action that could create an external side effect, even if the screen makes it look harmless.
- Use a test account and test data. Never intentionally capture passwords, OTPs, private messages, payment details, or personal data.
- Treat the phone as user-owned live state. Do not reset it, uninstall apps, clear app data, or change system settings unless explicitly requested.
- Execute one action at a time. After each action, inspect a fresh screenshot before continuing.
- Stop on ambiguity, repeated state, unexpected permission prompts, device disconnect, or a confidence below the level needed for a safe action.

## Workflow

### 0. Prefer the semantic control path when available

If the official `agent-device` CLI and its `dogfood` Skill are installed, use them for Android exploration before the basic ADB wrapper:

```sh
agent-device devices --platform android --json
agent-device open APP_OR_PACKAGE --platform android --serial SERIAL --session SESSION --json
agent-device snapshot -i --platform android --session SESSION --json
```

Prefer `agent-device find TEXT click` or a returned semantic ref over guessed coordinates. Re-snapshot after every UI mutation. Never use a coordinate merely because it worked on an earlier screenshot.

For scrolling, inspect the semantic snapshot first. If it shows an off-screen summary,
a scrollable container, or a target below the fold, use the official semantic scroll
command and then `snapshot`/`diff snapshot`:

```sh
agent-device scroll down --pixels 700 --duration-ms 300 --platform android --session SESSION --json
agent-device diff snapshot -i --platform android --session SESSION --json
```

The semantic path can identify supported scroll containers and may stop at an edge
without saving a duplicate screenshot. Do not treat `scrollable=true` alone as proof
that more content remains: it means the container supports scrolling, not that the
current position is above the bottom. If the semantic snapshot is sparse or the scroll
result cannot establish whether new content appeared, use the bounded visual fallback
in the long-page section below.

### Android compatibility preflight

Run the preflight before a long exploration:

1. Confirm `adb devices -l` shows the authorized device.
2. Confirm `agent-device open` succeeds.
3. Confirm `agent-device snapshot -i` succeeds on the current screen.
4. If snapshot fails, test a second screen or a simple system app before blaming the target app.

On OPPO/ColorOS, the Android snapshot helper may report automation-ownership release errors or lose its ADB forwarding port. Keep one `adb nodaemon server` alive across a sequence of `open`, `snapshot`, `find`, and `screenshot` commands. `AGENT_DEVICE_ANDROID_SNAPSHOT_HELPER_SESSION=0` can be tried as a recovery option, but it is not a guarantee.

Use this recovery order when the helper reports ownership, malformed-output, or ADB-timeout errors:

1. Close the named agent-device session.
2. Force-stop only `com.callstack.agentdevice.snapshothelper` if it is installed.
3. Reopen the target and retry one semantic snapshot with `AGENT_DEVICE_ANDROID_SNAPSHOT_HELPER_SESSION=0`.
4. If the same error remains across two different apps, stop retrying and ask the user to reboot the phone, unlock it, reconnect USB, and re-accept USB debugging if prompted. Do not uninstall user apps, clear app data, or reset the phone as a recovery step.

Treat a successful screenshot as evidence that the display transport works, not evidence that the semantic helper works.

### Keep one device session for the whole run

Start ADB/agent-device once and reuse the same process/session for preflight, opening,
snapshots, actions, and screenshots. Before starting another server, probe
`adb get-state`; if it succeeds, reuse the healthy server. Do not run `open --relaunch`
when the target app is already in the foreground. A failed `open` command is not proof
that the app did not launch—verify with one screenshot or foreground-package check.

Once per run is enough for the device check and helper preflight. If a WebView-heavy
screen produces only a root `WebView` node, stop retrying full semantic snapshots and
switch to the visual fallback. Record the semantic limitation in the report instead of
spending multiple round trips on the same failure.

### Do not wait indefinitely on a stalled state

The control loop must have a short recovery budget:

1. Wait at most 1–2 seconds for a normal page transition, then capture a fresh screenshot.
2. If the page is unchanged or the wrong top-level tab is visible, use the fresh screen
   to navigate to the intended tab or press `BACK` once when that is reversible.
3. If an ADB/agent-device command fails, retry the same command once after the existing
   server/session is healthy; do not repeat a whole exploration sequence blindly.
4. If the app still does not respond after one recovery action, capture the state and
   mark the step blocked. Continue with another app only if the device connection is
   healthy; otherwise stop and report the connection block.

“卡住”通常来自三类状态之一：app 仍在加载、动作落到了其他标签页，或
different tab, or the ADB client/server failed. A new screenshot distinguishes these
cases faster than repeated taps. A navigation tap is safe to redirect after confirming
the visible target; an action-oriented or account-changing control is not.

### Fast fallback: local OCR when the app exposes no useful inner UI tree

Some apps expose only a `WebView` or a custom-rendered surface. In that case, use the
fresh screenshot as the visual source and run the bundled macOS Vision OCR helper:

```sh
python3 scripts/ocr.py RUN_DIR/evidence/evidence-XXX.png --query "会员中心"
```

The helper runs locally with Apple Vision; it does not call an AI API or send the
screenshot to a service. It returns recognized text, confidence, and pixel bounds.
Use a returned text box only when all of these are true:

1. The screenshot is fresh and the target text is visibly confirmed.
2. The text match is exact or unambiguous, and the tap is inside that text box or its
   clearly associated navigation label.
3. The destination is read-only/navigation. OCR is not permission to tap a purchase,
   activation, order, submit, delete, or account-changing control.

After an OCR-guided tap, capture one fresh screenshot and verify the destination. If
Apple Vision OCR is unavailable, use the screenshot manually or stop and ask the user
to take over; do not silently use stale or guessed coordinates.

For speed, keep the loop bounded: one semantic snapshot attempt, otherwise one fresh
screenshot plus OCR, one action, then one verification screenshot. Avoid repeatedly
requesting full UI snapshots from a WebView-heavy screen.

### Cover long pages with bounded scrolling

If the requested module continues below the fold, do not stop after the first screen.
Use the current screenshot to identify a neutral content area, then perform one
moderate vertical swipe with the change check. The command compares the central
content area with the previous evidence image and discards the new image when the
page did not materially move:

```sh
python3 scripts/device.py swipe-check --run RUN_DIR 540 1900 540 700 --duration-ms 450 --wait-seconds 0.8 --title "会员中心下一屏" --reason "查看会员中心下一段内容"
```

If the command returns `changed: false`, treat the page as unchanged or already at the
bottom: do not save or label another screenshot. If it returns `changed: true`, keep the
returned evidence image and continue only if it reveals a new relevant module. If it
returns `changed: null`, compare the fresh screenshot manually and keep it only when
there is genuinely new content. Two screens are enough when the second screen reaches
the bottom; never force a third screen. Stop after two materially unchanged attempts or
before an action-oriented control if the next gesture could trigger it. Use at most 4–6
screens for a normal module review. Swiping is navigation, not permission to tap cards,
claim benefits, buy, or activate anything.

For a long page, label evidence as “首屏 / 中段 / 底部” and analyze modules across
all captured screens. A report that claims to cover a page must say which sections were
actually seen and which remain unverified.

### Abstract dynamic and personal data in the product report

Do not put account-dependent values in the default report. Generalize counts, balances,
progress, dates, prices, coupon amounts, badges, usernames, and status values:

- `27/35 项权益` → “显示当前可享权益数量”
- `11602/30000` → “显示当前成长进度”
- `2026.09.30` → “显示会员有效期”
- `13 元` → “展示优惠金额”

Keep exact values only when the user explicitly asks for a snapshot, data comparison,
or correctness check. Screenshots may remain as evidence, but the written product
summary should use categories rather than volatile values.

If `agent-device screenshot` fails through `adb exec-out` while the device is still connected, use a same-server fallback: `adb shell screencap -p /sdcard/<name>.png` followed by `adb pull`. Treat this as a screenshot transport fallback only; it does not replace semantic verification.

### Bootstrap for a new user

Use the bundled bootstrap script before attempting device control:

```sh
python3 scripts/bootstrap.py --json
```

The check is read-only. If Node.js/npm/npx are present but the tools are missing, explain the changes and ask the user for permission before running:

```sh
python3 scripts/bootstrap.py --install
```

With the user's approval, `--install` installs the validated `agent-device@0.20.5`,
the official `callstackincubator/agent-device` `dogfood` Skill, and Android Platform
Tools/ADB. On macOS it uses Homebrew; on Debian/Ubuntu it uses `apt-get`; on Windows
it uses WinGet when available. If no supported package manager is available, show the
official download page and stop rather than claiming ADB is ready. Use `--install-adb`
when only ADB is missing. A different explicitly approved agent-device version can be
selected with `--agent-device-version VERSION`; the read-only check still requires
`agent-device >= 0.14.0`.

The installer never runs silently: invoke it only after the user approves the
installation step. It cannot accept the phone's USB debugging prompt; the user must tap
“允许 USB 调试”. After installation, rerun the read-only check and require an authorized
device before exploration.

When sharing this Skill, share the whole `app-experience-agent` folder. The recipient can
run the bootstrap command to install the CLI and dogfood Skill locally; the CLI itself is
not vendored inside the Skill because it depends on the recipient's Node/npm, ADB, OS
architecture, and device-side helper.

### 1. Prepare a run

From this skill directory, use:

```sh
python3 scripts/device.py status
python3 scripts/device.py start-run --title "短任务名称" --task "任务描述"
```

The `start-run` command prints the run directory. Keep that path for every following command.

### 2. Inspect before acting

```sh
python3 scripts/device.py screenshot --run RUN_DIR --title "初始页面" --reason "任务开始"
python3 scripts/device.py dump-ui --run RUN_DIR
```

Inspect the returned screenshot in the Codex conversation. Use the UI dump when it contains useful text or bounds, but do not assume every app exposes a complete accessibility tree. Prefer a visible, reversible action. Use coordinates from the current screenshot only as an explicitly verified fallback; never reuse coordinates after a layout change, and never click when the current screen cannot be confirmed.

### Coordinate safety: use original image pixels or screen ratios

Screenshots shown in the conversation may be visually downscaled. Never copy a coordinate
from the rendered chat image directly into `device.py tap`. The screenshot metadata records
the original `image_width` and `image_height`; use those pixels, or use the ratio-based
command when the target is best described by position:

```sh
python3 scripts/device.py screen-size
python3 scripts/device.py tap-ratio --run RUN_DIR 0.93 0.95 --reason "点击当前截图确认的个人中心入口"
```

The ratio is relative to the full physical screen, from 0 to 1. Re-read the current
screenshot after every layout change. Choose the center of the whole visible tab hit
area, not the apparent center in a resized preview. If the target is text inside a card,
use the original screenshot dimensions and the text/card bounds from that same screenshot.

### 3. Execute one action

Use one of these commands and include a short reason:

```sh
python3 scripts/device.py tap --run RUN_DIR X Y --reason "点击搜索入口"
python3 scripts/device.py swipe --run RUN_DIR X1 Y1 X2 Y2 --duration-ms 450 --reason "向下浏览列表"
python3 scripts/device.py input --run RUN_DIR --text "示例文本" --reason "填写搜索词"
python3 scripts/device.py key --run RUN_DIR BACK --reason "返回上一页"
python3 scripts/device.py wait --run RUN_DIR --seconds 1.2 --reason "等待页面稳定"
```

Then capture a fresh screenshot:

```sh
python3 scripts/device.py screenshot --run RUN_DIR --title "动作后页面" --reason "验证点击结果"
```

### 4. Finish and report

When the task is complete, failed, blocked, or stopped by the user:

```sh
python3 scripts/report.py --run RUN_DIR
```

Read the generated Markdown report, verify the evidence sequence, and summarize what actually happened. Do not infer a successful task merely because an action command returned exit code 0; verify the resulting screen.

The generated report is only a scaffold. Before handing it off, complete the analysis
using [references/report-schema.md](references/report-schema.md). At minimum, cover:

- the exact journey and whether the goal was completed;
- the product's functional modules and what each module is for;
- the strongest and weakest UI/UX aspects, tied to a screenshot and a concrete recommendation;
- whether each item is confirmed, observed, or unverified;
- the important unvisited modules or risky controls that were intentionally not tested.

Keep ADB/helper failures, retries, elapsed time, and coordinate details in the internal
run log unless they directly cause a user-visible product problem. They are not part of
the default product report.

Do not call an agent coordinate error an app UX defect unless the same behavior is
reproduced with a confirmed target and a fresh screenshot. Do not leave the generated
“请补充结论” placeholder in the final report.

## Action guidance

- Use `launch --package PACKAGE` only when the user has named the target package.
- Use semantic `agent-device scroll` for an exposed scroll container; use `swipe-check` as the visual fallback. Use `tap` for a visible target, `input` for non-sensitive test text, and `key BACK` for reversible navigation.
- For long pages, scroll through neutral content areas and capture each newly revealed module; never reuse a swipe endpoint after the layout changes.
- If semantic snapshot/find fails, do not silently downgrade to coordinate guessing. Retry once after the helper has exited, close and reopen the session, or ask the user to take over. A screenshot-derived coordinate is acceptable only when the exact current screen and target are unambiguous and the action is low-risk.
- Use `ask_user` conceptually by stopping the workflow and asking in chat; do not invent an automatic confirmation for risky actions.
- Keep a small step budget, normally 12 actions for an exploratory run unless the user asks for more.
- If two consecutive screenshots are materially unchanged after an action, do not repeat the same action blindly. Try one recovery action or stop and report the block.

Every report must distinguish these three states:

- **Confirmed:** directly visible or verified by a fresh semantic/screenshot state.
- **Observed:** a visible property of the current screen, not of an unvisited downstream page.
- **Blocked/unverified:** an intended action or page that was never successfully reached.

Do not describe an unvisited page's UX, features, or defects as findings.

## Bundled scripts

- `scripts/device.py`: safe ADB wrapper, screenshots, UI dumps, run metadata, and action logging.
- `scripts/report.py`: render a run's JSONL events and evidence into Markdown and standalone HTML.
- `scripts/smoke_test.py`: offline verification that creates a fixture run and checks report generation without touching a phone.
- `scripts/ocr.py` and `scripts/vision_ocr.swift`: local Apple Vision OCR fallback for text and pixel bounds when semantic UI inspection is incomplete.
- `references/report-schema.md`: required structure for a complete, evidence-based report.
