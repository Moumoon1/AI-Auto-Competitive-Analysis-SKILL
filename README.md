# App Experience Agent

一个在 Codex 中运行的 Android App 体验走查工具：Codex 负责看截图、理解任务和决定下一步；本地 ADB 脚本负责截图、点击、滑动、输入、记录证据和生成报告。

## 当前边界

- 不需要 AI API。
- 不提供独立 Web 页面。
- 需要电脑安装 `adb`，手机开启 USB 调试并授权。
- 默认只执行可逆、低风险操作。
- 不输入密码、验证码、支付信息，也不执行支付、发布、发送、删除或下单。

## 第一次运行

```sh
# 在项目根目录执行
python3 .codex/skills/app-experience-agent/scripts/bootstrap.py --json
```

如果缺少 Node.js、agent-device 或 ADB，先向用户说明并在获得同意后运行：

```sh
python3 .codex/skills/app-experience-agent/scripts/bootstrap.py --install
```

首次使用还需要在安卓手机上安装 Agent Device Snapshot Helper（不是只在电脑上安装工具），并在系统提示时点击“安装”。连接并授权手机后，再运行：

```sh
python3 .codex/skills/app-experience-agent/scripts/device.py status
python3 .codex/skills/app-experience-agent/scripts/smoke_test.py
```

连接并授权手机后，启动一次走查：

```sh
python3 .codex/skills/app-experience-agent/scripts/device.py start-run \
  --title "设置页面走查" \
  --task "打开目标 App，进入设置页面，观察入口是否容易找到" \
  --package com.example.app
```

命令会输出 `RUN_DIR`。之后每次截图或动作都带上这个目录：

```sh
python3 .codex/skills/app-experience-agent/scripts/device.py launch --run RUN_DIR --package com.example.app --reason "启动目标 App"
python3 .codex/skills/app-experience-agent/scripts/device.py screenshot --run RUN_DIR --title "初始页面" --reason "记录任务起点" --with-ui
python3 .codex/skills/app-experience-agent/scripts/device.py tap --run RUN_DIR 540 1200 --reason "点击当前截图中的设置入口"
python3 .codex/skills/app-experience-agent/scripts/device.py screenshot --run RUN_DIR --title "设置页面" --reason "验证点击结果" --with-ui
python3 .codex/skills/app-experience-agent/scripts/report.py --run RUN_DIR

# 生成可交付的 HTML/Markdown 报告，截图会以内嵌缩略图显示，点击可查看大图
python3 .codex/skills/app-experience-agent/scripts/finalize_report.py \\
  --run RUN_DIR --output-dir outputs --name app-experience-report
```

浏览长页面时，优先使用 `swipe-check`。它会在滑动后比较前后截图；如果页面
没有实际变化，就丢弃重复截图并提示停止，不会强行生成“底部”证据。

在 Codex 中使用本项目时，触发 `app-experience-agent` Skill，并要求它每次动作后重新读取截图。不要把示例坐标直接套用到别的设备或页面。
