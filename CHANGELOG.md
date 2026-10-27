# 更新日志 / Changelog

## v1.6.4 — 2026-10-27

本次发布包含 v1.5 之后的全部改进 / Includes all enhancements since v1.5.

- 锁屏后等待屏保支持 0 秒，立即开始轮播；仍可关闭自动屏保。
- 支持多个图片文件夹；递归扫描子文件夹开关默认关闭。
- 自动跳过宽度不足 1280 或高度不足 720 像素的图片，以及无法读取的图片。
- 多屏默认同步显示同一图片和切换进度，可切换为独立轮播。
- 支持为显示器设置名称，在设置、识别卡和锁屏中显示。
- 时钟默认固定，可开启定时移动；支持经典、极简、靛蓝卡片三种样式和实时预览。
- 任意首次按键仅用于唤出密码框，不计入密码；完整密码匹配后立即解锁并返回托盘。
- 输入密码时幻灯片继续轮播，背景模糊，时钟和输入框保持清晰；Esc 取消后恢复清晰背景。
- 下拉框收起时和秒数输入框忽略滚轮改值，减少滚动设置页时的误操作。

### Download

- [Windows x64 executable and SHA-256 checksum](https://github.com/Le0v1n/ScreenBlind/releases/tag/v1.6.4).
- Portable single-file build, no Python installation required. Tested on Windows 11 x64.
- Exit the previous tray instance before launching the new executable; saved settings are retained.

### Validation

- 67 automated tests passed, including password behavior, background blur, wheel controls, saved options, recursive scanning, image resolution boundaries, and simulated multi-display slideshow behavior.
- PyInstaller packaging and executable startup with isolated APPDATA passed.
- Password-background blur and clock previews visually checked on Windows.
- Physical mixed-DPI/hotplug and a full sign-out/reboot startup cycle were not exercised.
