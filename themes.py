"""Shared light/dark palette for windows, dialogs and tray menus."""
from PyQt6.QtGui import QColor, QPalette
from pathlib import Path
import sys

PALETTES = {
    'dark': dict(bg='#10121b', panel='#191c2a', input='#131622', text='#edf0fa',
                 muted='#a3adc6', border='#343b53', hover='#292f47', accent='#a5b4fc',
                 warning='#30281a', warning_text='#f2dba2'),
    'light': dict(bg='#f5f7fc', panel='#ffffff', input='#ffffff', text='#1d2740',
                  muted='#54627b', border='#ccd3e3', hover='#e9edfa', accent='#4338ca',
                  warning='#fff6df', warning_text='#735018'),
}


def apply_theme(app, theme: str):
    c = dict(PALETTES.get(theme, PALETTES['dark']))
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    c['checkmark'] = (base / 'media_assets' / 'checkmark.svg').as_posix()
    palette = QPalette()
    for role, value in {
        QPalette.ColorRole.Window: c['bg'], QPalette.ColorRole.WindowText: c['text'],
        QPalette.ColorRole.Base: c['input'], QPalette.ColorRole.AlternateBase: c['panel'],
        QPalette.ColorRole.Text: c['text'], QPalette.ColorRole.Button: c['panel'],
        QPalette.ColorRole.ButtonText: c['text'], QPalette.ColorRole.Highlight: '#6366f1',
        QPalette.ColorRole.HighlightedText: '#ffffff',
        QPalette.ColorRole.ToolTipBase: c['panel'], QPalette.ColorRole.ToolTipText: c['text'],
        QPalette.ColorRole.PlaceholderText: c['muted'],
    }.items():
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget {{ background: {bg}; color: {text}; font-family: 'Microsoft YaHei UI'; font-size: 10pt; }}
        QWidget#header, QWidget#footer {{ background: {panel}; border: 1px solid {border}; }}
        QLabel {{ background: transparent; }}
        QLabel[secondary="true"] {{ color: {muted}; font-size: 9pt; }}
        QLabel#brand {{ color: {accent}; font-size: 18pt; font-weight: 600; }}
        QLabel#aboutDisclaimer {{ background: {warning}; color: {warning_text}; border: 1px solid {border}; border-radius: 8px; padding: 12px; }}
        QTabWidget::pane {{ border: none; border-top: 1px solid {border}; }}
        QTabBar::tab {{ padding: 12px 18px; color: {muted}; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: {accent}; border-bottom: 2px solid #6366f1; }}
        QTabBar::tab:hover {{ background: {hover}; }}
        QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; padding: 8px 16px; }}
        QPushButton:hover {{ background: {hover}; border-color: #6366f1; }}
        QPushButton:pressed {{ background: {border}; }}
        QPushButton#lockBtn {{ background: #be123c; color: white; border: none; font-weight: 600; font-size: 12pt; }}
        QPushButton#lockBtn:hover {{ background: #e11d48; }}
        QPushButton:disabled {{ color: {muted}; background: {border}; }}
        QLineEdit, QSpinBox, QComboBox, QKeySequenceEdit, QListWidget {{ background: {input}; border: 1px solid {border}; border-radius: 6px; padding: 8px; selection-background-color: #6366f1; selection-color: white; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{ border-color: #6366f1; }}
        QComboBox QAbstractItemView {{ background: {panel}; color: {text}; selection-background-color: #6366f1; selection-color: white; }}
        QListWidget::item {{ padding: 10px; border-radius: 4px; }}
        QListWidget::item:selected {{ background: {hover}; color: {text}; }}
        QCheckBox {{ spacing: 9px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid {muted}; background: {input}; }}
        QCheckBox::indicator:checked {{ background: #6366f1; border: 1px solid #6366f1; image: url("{checkmark}"); }}
        QFrame[role="separator"] {{ background: {border}; max-height: 1px; margin: 5px 0; }}
        QMenu {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 5px; }}
        QMenu::item {{ padding: 8px 18px; }}
        QMenu::item:selected {{ background: {hover}; }}
        QMenu::item:disabled {{ color: {muted}; }}
        QMenu::separator {{ height: 1px; background: {border}; margin: 4px; }}
        QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; }}
    """.format(**c))
