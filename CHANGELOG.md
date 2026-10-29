# 更新日志 / Changelog

## v1.7.0 — Unreleased / 待 UU 联机验收

- 新增默认关闭的全部屏幕锁定策略；按稳定标识保存选择，自动检测新增、移除和几何变化。
- 标准密码输入控件接管字符提交和输入法替换，多屏共享密码状态；保留首次唤醒与完整密码立即解锁。
- 新增仅记录测试事件元数据的远程输入诊断窗口。
- 新增独立远程模式，允许列表以外默认遮挡；本地全黑，允许屏幕的遮挡使用 Windows 排除采集接口。
- 退出、扩大远程权限或恢复本地显示需验证密码；恢复快捷键默认留空。
- 排除采集失败、允许屏幕全部断开时，转为普通全部屏幕密码锁定。
- 修复 UU 手机豆包输入法提交英文时，带 Ctrl 状态的 Unicode 文本被误作快捷键的问题；用户已确认输入与现有远程模式逻辑正常。GBoard 按用户要求暂缓验收。
- 新增鼠标来源诊断与默认关闭的“远程模式下屏蔽本地鼠标（实验性）”；根据当前 UU 实测标记区分非注入与注入鼠标事件，保留本地键盘密码恢复。实际屏蔽效果仍待联机验收，不提供系统级输入隔离。
- 锁定快捷键在远程模式自动唤出密码恢复框；锁定与恢复允许共用一个组合，普通锁屏仍需密码解锁。
- 新增默认关闭的本地键盘屏蔽：远程模式仅保留已配置的锁定/恢复组合，本地修饰键不穿透影响远程输入；密码框位于前台时允许普通本地输入，取消后继续屏蔽。UU 注入键盘保持放行，仍待手机复测；系统 Ctrl+Alt+Delete 不在普通应用可拦截范围。
- 修复修饰键按下与抬起经过不同输入路径时，Alt/Ctrl 抬起被吞掉而残留按下状态的问题；修饰键抬起统一转发并清理内部状态。

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
