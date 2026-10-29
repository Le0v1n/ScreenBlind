"""English source strings and a Simplified Chinese catalog, bundled as Python data."""
from PyQt6.QtCore import QLocale, QTranslator, QLibraryInfo


def resolve_language(choice):
    if choice in ('en', 'zh_CN'):
        return choice
    return 'zh_CN' if QLocale.system().language() == QLocale.Language.Chinese else 'en'


_language = resolve_language('system')


def current_language():
    return _language


def configure_language(app, choice):
    global _language
    _language = resolve_language(choice)
    QLocale.setDefault(QLocale('zh_CN' if _language == 'zh_CN' else 'en_US'))
    previous = getattr(app, '_screenblind_translator', None)
    if previous is not None:
        app.removeTranslator(previous)
        previous.deleteLater()
    translator = QTranslator(app)
    if _language == 'zh_CN' and translator.load('qtbase_zh_CN', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    app._screenblind_translator = translator


def tr(source, **values):
    template = ZH_CN.get(source, source) if _language == 'zh_CN' else source
    return template.format(**values) if values else template


ZH_CN = {
    'The lock hotkey opens password recovery in remote mode. Lock and restore may share a hotkey; the tray Lock now action still locks all displays.': '锁定快捷键在远程模式下会唤出密码恢复框。锁定与恢复可设置为同一快捷键；托盘“立即锁定”仍会锁定全部屏幕。',
    'Block local mouse during remote mode (experimental)': '远程模式下屏蔽本地鼠标（实验性）',
    'Off by default. Blocks unmarked mouse movement, clicks and scrolling; allows injected input. Source flags were tested with this UU setup; filtering still needs a live test. Local keyboard recovery stays available; configure a recovery hotkey before testing. This is not a system security boundary.': '默认关闭。拦截未标记为注入的鼠标移动、点击和滚轮，保留注入输入。当前 UU 的来源标记已实测，屏蔽效果仍需复测。本地键盘可用于密码恢复，测试前请配置恢复快捷键。此功能不提供系统级安全隔离。',
    'Remote protection could not be enabled. All displays remain password-locked.': '远程保护无法启用，所有屏幕继续保持密码锁定。',
    'Mouse source diagnostic': '鼠标来源诊断',
    'Run two separate samples: local mouse only, then phone UU only. Each sample lasts 15 seconds. Move, click and scroll over this window. Input is never blocked. Only event counts and injection flags are kept in memory; no coordinates or key text are collected. Injection flags do not prove the source is UU.': '分两轮测试：先只用本地鼠标，再只用手机 UU。每轮 15 秒，请在本窗口上移动、点击和滚动。不会拦截操作；仅在内存统计事件数量与注入标记，不采集坐标或按键文本。注入标记不能证明输入来自 UU。',
    'Sample local mouse': '采样本地鼠标',
    'Sample phone UU': '采样手机 UU',
    'Stop sample': '停止采样',
    'Ready': '就绪',
    'Mouse diagnostic unavailable: {error}': '鼠标诊断不可用：{error}',
    'Sampling: {seconds}s remaining; {count} events': '采样中：剩余 {seconds} 秒，已收到 {count} 个事件',
    'Lock all displays, including newly connected displays': '锁定全部屏幕（包含新接入的屏幕）',
    '  Remote  ': '  远程模式  ',
    'Remote mode unavailable': '远程模式不可用',
    'Capture exclusion failed. All displays remain password-locked.': '无法排除遮挡层采集，已转为全部屏幕密码锁定。',
    'Remote input diagnostic': '远程输入诊断',
    'Exit remote mode (password required)': '退出远程模式（需验证密码）',
    'Enter remote mode': '进入远程模式',
    'Remote mode active · local screens covered': '远程模式运行中 · 本地屏幕已遮挡',
    'Select at least one connected display for remote use.': '请至少选择一个当前已连接的屏幕供远程使用。',
    'Restore local displays': '恢复本地显示',
    'Local displays are black. Only checked displays remain visible and usable to supported remote capture software.': '本地所有屏幕均遮黑；在支持的远程采集软件中，仅勾选屏幕可见并可操作。',
    'UU compatibility awaits a live test. Newly connected displays are denied by default. Exit remote mode with your password before changing this list.': 'UU 兼容性尚待联机验证。新接入屏幕默认不开放远程使用；修改列表前请验证密码退出远程模式。',
    'Enter your password to restore local displays': '请输入密码，验证通过后恢复本地显示',
    'Cancel': '取消',
    'Remote mode is off. It does not start automatically.': '远程模式未开启，不会随软件自动启动。',
    'Use test text only, such as aabb1122. Do not enter your password. Logs contain event metadata only and are not saved.': '仅输入 aabb1122 等测试字符，切勿输入真实密码。日志仅包含事件信息，不记录字符内容，也不会自动保存。',
    'Previous input path (comparison):': '旧版输入路径（对照）：',
    'Standard input path:': '标准输入路径：',
    'Rename selected display…': '重命名选中屏幕…',
    'Rename display': '重命名屏幕',
    'Display name (leave empty to reset):': '屏幕名称（留空恢复默认）：',
    '0 seconds starts the selected screensaver immediately after locking.': '设为 0 秒时，锁屏后立即启动所选屏保。',
    'Show the same image on all locked displays': '所有锁定屏幕同步显示同一张图片',
    'Enabled by default: images and transitions are synchronized. Turn off for independent slideshows.': '默认开启，图片和切换进度保持同步；关闭后各屏幕独立轮播。',
    'Add multiple folders one at a time. Images are combined into one playlist.': '可重复添加多个文件夹，图片将合并到同一播放列表。',
    'Add folder…': '添加文件夹…',
    'Remove selected folders': '移除所选文件夹',
    'Enhancements: {name}\nContact: {email}': '增强版贡献者：{name}\n联系邮箱：{email}',
    'Select displays to lock:': '选择需要锁定的显示器：',
    '↻  Refresh displays': '↻  刷新显示器',
    '🔢  Identify displays': '🔢  识别显示器',
    'Show a number on each connected display': '在每个已连接的显示器上显示编号',
    'Tip: unlocked displays remain visible; while locked, mouse and keyboard input is used only for unlocking.': '提示：未锁定的显示器继续显示内容；锁定期间鼠标和键盘仅用于解锁。',
    ' (Primary)': '（主显示器）',
    'Current password:': '当前密码：',
    'Enter current password': '输入当前密码',
    'New password:': '新密码：',
    'Enter new password': '输入新密码',
    'Confirm new password:': '确认新密码：',
    'Repeat new password': '再次输入新密码',
    'Show passwords': '显示密码',
    'Set password': '设置密码',
    'Password is set.': '已设置密码。',
    'No password set yet.': '尚未设置密码。',
    'Incorrect password': '密码错误',
    'The current password is incorrect.': '当前密码不正确。',
    'Empty password': '密码为空',
    'New password cannot be empty.': '新密码不能为空。',
    'Passwords do not match': '密码不一致',
    'The new passwords do not match.': '两次输入的新密码不一致。',
    'Done': '完成',
    'Password updated successfully.': '密码已更新。',
    'Start the screensaver when idle': '空闲后自动启动屏保',
    'Start screensaver after idle:': '空闲多久后启动屏保：',
    '  seconds': '  秒',
    'Animation style:': '屏保样式：',
    'Bubbles': '气泡',
    'Matrix': '数字雨',
    'Flurry': '流光',
    'Image slideshow': '图片幻灯片',
    'None': '无',
    'Slideshow options:': '幻灯片选项：',
    'No folder selected': '未选择文件夹',
    'Browse folder…': '选择文件夹…',
    'Seconds per image:': '每张图片的显示时长：',
    'Select image folder': '选择图片文件夹',
    "Lock what others shouldn't see. Unlock what matters.": '遮住私密内容，让需要展示的画面继续显示。',
    '  Visit website  ': '  访问原项目网站  ',
    '  ❤  Donate  ': '  ❤  支持原作者  ',
    'ScreenBlind selectively locks chosen displays while presentations, videos or dashboards remain visible on the others.\nMouse and keyboard input is captured until the correct password is entered.\n\nIncludes a system tray, global hotkeys, light/dark themes and English / Simplified Chinese.\nOriginal author: hemigapp · License: MIT': 'ScreenBlind 可选择性地锁定显示器，其他显示器继续显示演示、视频或看板。\n锁定期间鼠标和键盘由锁屏接管，输入正确密码后统一解锁。\n\n本分支增加中文界面、托盘驻留、全局快捷键与浅色 / 深色主题。\n原项目作者：hemigapp · 开源许可：MIT',
    'Usage and disclaimer\nScreenBlind is a privacy tool, not a replacement for the Windows lock screen. Win+L and Ctrl+Alt+Del are still handled by Windows. The software is provided as is, without warranty. Keep your password safe and have a recovery plan.': '使用说明与免责声明\n本软件是隐私遮挡工具，不能替代 Windows 系统锁屏。Win+L 和 Ctrl+Alt+Del 仍由系统处理。软件按现状提供，不作任何担保；请妥善保管密码，并保留恢复方式。',
    '  Displays  ': '  显示器  ',
    '  Security  ': '  安全  ',
    '  Screensaver  ': '  屏保  ',
    '  General  ': '  通用  ',
    '  About  ': '  关于  ',
    '  Lock now  ': '  立即锁定  ',
    'Open settings': '打开设置',
    'Lock now': '立即锁定',
    'Exit': '退出软件',
    'No password': '尚未设置密码',
    'Set a password in the Security tab before locking.': '请先在“安全”页面设置密码，再锁定显示器。',
    'No displays selected': '尚未选择显示器',
    'Select at least one display in the Displays tab.': '请先在“显示器”页面选择至少一个显示器。',
    'Locked': '已锁定',
    'Unlock the displays before exiting.': '请先输入密码解锁，再退出软件。',
    'ScreenBlind is still running': 'ScreenBlind 仍在运行',
    'Minimized to the tray. Double-click the icon to open settings, or right-click to exit.': '已收起到托盘。双击图标恢复设置，右键菜单可退出软件。',
    'ScreenBlind · Locked; enter your password to unlock': 'ScreenBlind · 已锁定，请输入密码解锁',
    'Start with Windows (run in the tray after sign-in)': '开机自启动（登录 Windows 后驻留托盘）',
    'Off by default. Keep the executable in its current location after enabling.': '默认关闭；开启后请保留当前程序的位置。',
    'Cannot read startup settings. Check registry access for the current user.': '无法读取开机自启动设置，请检查当前用户的注册表访问权限。',
    'Theme': '界面主题',
    'Dark': '深色',
    'Light': '浅色',
    'Global hotkeys · Active while in the tray': '全局快捷键 · 收起到托盘后仍然有效',
    ' shortcut': '快捷键',
    'Not set; press a key combination': '未设置，点击后按组合键',
    'Clear': '清除',
    'Click a field and press a combination: Ctrl / Alt + a letter, digit or F1–F11; Shift is optional.\nClear and save to disable an action. Hotkeys cannot unlock displays.': '点击输入框后按下组合键。支持 Ctrl / Alt + 字母、数字或 F1–F11，可加 Shift。\n清空后保存可禁用该操作；快捷键无法直接解锁。',
    'Save hotkeys': '保存快捷键',
    'Closing this window keeps ScreenBlind in the tray. Double-click the tray icon to open settings; right-click and choose Exit to quit.': '关闭窗口后继续驻留托盘。双击托盘图标打开设置，右键选择“退出软件”可完全退出。',
    'Settings update failed': '设置失败',
    'Cannot update startup settings. Check registry access for the current user.': '无法更新开机自启动设置，请检查当前用户的注册表访问权限。',
    'Enabled: ScreenBlind will run in the tray after your next Windows sign-in.': '已开启：下次登录 Windows 后将自动驻留托盘。',
    'Windows startup is disabled.': '已关闭开机自启动。',
    'Hotkeys are active.': '快捷键设置已生效。',
    'All hotkeys are disabled.': '已禁用全部快捷键。',
    ' Change the combination and save. The tray menu is still available.': ' 请修改后保存；托盘菜单仍可使用。',
    'Hotkeys are unavailable': '快捷键未启用',
    'Hotkeys were not saved': '快捷键未保存',
    '\nYour previous hotkeys remain active.': '\n原有快捷键保持不变。',
    'Hotkeys saved and applied.': '快捷键已保存并生效。',
    'Unable to start': '无法启动',
    'Error': '错误',
    'The system tray is unavailable. ScreenBlind cannot start.': '当前系统不支持托盘图标，无法启动。',
    'dddd, MMMM d': 'yyyy年M月d日 dddd',
    'Enter password': '输入密码',
    'Correct password unlocks    Esc  Cancel': '密码正确即解锁    Esc  取消',
    'Press any key or click to enter your password': '按任意键或点击以输入密码',
    'No eligible images found (minimum 1280 × 720)': '未找到符合条件的图片（最低 1280 × 720）',
    'Include subfolders': '包含子文件夹',
    'Lock-screen clock:': '锁屏时钟：',
    'Move the clock periodically': '定时移动时钟位置',
    'Off by default. When enabled, the clock moves every 30–120 seconds.': '默认关闭，时钟保持固定；开启后每 30–120 秒移动一次。',
    'Classic · time and seconds': '经典 · 时分与秒数',
    'Minimal · clean typography': '极简 · 轻盈留白',
    'Panel · soft indigo': '卡片 · 柔和靛蓝',
    'Off by default. Only images at least 1280 pixels wide and 720 pixels high are shown.': '默认关闭递归扫描。仅展示宽度至少 1280、高度至少 720 像素的图片。',
    'Use a single key combination.': '快捷键只能包含一组按键。',
    'Include Ctrl or Alt. The Windows key is not supported.': '请使用 Ctrl 或 Alt 作为组合键；不支持 Windows 键。',
    'Use a letter A–Z, digit 0–9 or F1–F11 as the main key.': '主键支持 A–Z、0–9 或 F1–F11。',
    'Two actions cannot use the same hotkey.': '两个操作不能使用相同的快捷键。',
    'Cannot create the ScreenBlind instance communication service.': '无法创建 ScreenBlind 实例通信服务。',
    'ScreenBlind is already running but could not be reached. Try again shortly.': 'ScreenBlind 已在运行，但暂时无法连接。请稍后重试。',
    'Display {number}': '显示器 {number}',
    '  at ({x}, {y})': '  位置（{x}, {y}）',
    'Forgot your password? Exit the app and delete this settings file to reset:\n{path}': '忘记密码？退出软件后，删除以下设置文件可重置：\n{path}',
    'Version {version}': '版本 {version}',
    'ScreenBlind v{version} · Running in the tray': 'ScreenBlind v{version} · 后台运行',
    'The shortcut {shortcut} is in use or could not be registered. Choose another combination.': '快捷键 {shortcut} 已被占用或无法注册，请换一组按键。',
    'Language': '界面语言',
    'System default': '跟随系统',
}
