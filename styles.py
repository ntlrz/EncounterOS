# Modern GM UI: rounded buttons, clear hover/press, consistent spacing.
# Use QPushButton[flat="false"] for normal buttons; primary actions can use .primary class.

DARK_QSS = """
QWidget { background-color: #1a1c20; color: #e8eaed; font-family: "Segoe UI", system-ui, sans-serif; }
QMainWindow::separator { width: 4px; background: #25272b; }
QSplitter::handle { background: #25272b; width: 4px; }

/* Inputs: rounded, subtle border */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {
  background-color: #25272b; color: #e8eaed; border: 1px solid #3c4043;
  border-radius: 8px; padding: 8px 10px; min-height: 20px;
  selection-background-color: #4a7bc2; selection-color: #fff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
  border-color: #5a9fd4;
}
QComboBox::drop-down { border: none; padding-right: 8px; }
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected { background-color: #3c4043; }
QListWidget::item:hover:!selected { background-color: #2d3034; }

/* Buttons: modern flat-with-hover, rounded */
QPushButton {
  background-color: #2d3034; color: #e8eaed; border: none;
  border-radius: 8px; padding: 8px 14px; min-height: 20px;
  font-weight: 500;
}
QPushButton:hover { background-color: #3c4043; }
QPushButton:pressed { background-color: #202124; }
QPushButton:disabled { background-color: #25272b; color: #5f6368; }
/* Primary action buttons (e.g. Next/Previous) */
QPushButton[class="primary"] {
  background-color: #4a7bc2; color: #fff;
}
QPushButton[class="primary"]:hover { background-color: #5a8ed4; }
QPushButton[class="primary"]:pressed { background-color: #3d6ab0; }

/* Toolbar buttons */
QToolButton {
  background-color: transparent; color: #e8eaed; border: none;
  border-radius: 8px; padding: 6px 10px; font-weight: 500;
}
QToolButton:hover { background-color: #2d3034; }
QToolButton:pressed, QToolButton:checked { background-color: #3c4043; }

/* Tabs */
QTabBar::tab {
  background: #25272b; color: #9aa0a6; padding: 10px 16px; margin-right: 2px;
  border-top-left-radius: 8px; border-top-right-radius: 8px;
}
QTabBar::tab:selected { background: #2d3034; color: #e8eaed; }
QTabBar::tab:hover:!selected { background: #2a2d31; }
QTabWidget::pane { border: 1px solid #3c4043; border-radius: 0 8px 8px 8px; top: -1px; }

QToolTip {
  background: #2d3034; color: #e8eaed; border: 1px solid #3c4043;
  border-radius: 6px; padding: 6px 8px;
}
QGroupBox {
  border: 1px solid #3c4043; border-radius: 8px; margin-top: 12px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9aa0a6; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #5f6368; background: #25272b; }
QCheckBox::indicator:checked { background: #4a7bc2; border-color: #4a7bc2; }
QDialog QPushButton { min-width: 80px; }
"""

LIGHT_QSS = """
QWidget { background-color: #f8f9fa; color: #202124; font-family: "Segoe UI", system-ui, sans-serif; }
QMainWindow::separator { width: 4px; background: #e8eaed; }
QSplitter::handle { background: #e8eaed; width: 4px; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {
  background-color: #fff; color: #202124; border: 1px solid #dadce0;
  border-radius: 8px; padding: 8px 10px; min-height: 20px;
  selection-background-color: #1a73e8; selection-color: #fff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
  border-color: #1a73e8;
}
QComboBox::drop-down { border: none; padding-right: 8px; }
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected { background-color: #e8eaed; color: #202124; }
QListWidget::item:hover:!selected { background-color: #f1f3f4; }

QPushButton {
  background-color: #fff; color: #202124; border: 1px solid #dadce0;
  border-radius: 8px; padding: 8px 14px; min-height: 20px;
  font-weight: 500;
}
QPushButton:hover { background-color: #f1f3f4; border-color: #dadce0; }
QPushButton:pressed { background-color: #e8eaed; }
QPushButton:disabled { background-color: #f1f3f4; color: #9aa0a6; }
QPushButton[class="primary"] {
  background-color: #1a73e8; color: #fff; border: none;
}
QPushButton[class="primary"]:hover { background-color: #1765cc; }
QPushButton[class="primary"]:pressed { background-color: #1557b0; }

QToolButton {
  background-color: transparent; color: #202124; border: none;
  border-radius: 8px; padding: 6px 10px; font-weight: 500;
}
QToolButton:hover { background-color: #e8eaed; }
QToolButton:pressed, QToolButton:checked { background-color: #dadce0; }

QTabBar::tab {
  background: #e8eaed; color: #5f6368; padding: 10px 16px; margin-right: 2px;
  border-top-left-radius: 8px; border-top-right-radius: 8px;
}
QTabBar::tab:selected { background: #fff; color: #202124; }
QTabBar::tab:hover:!selected { background: #f1f3f4; }
QTabWidget::pane { border: 1px solid #dadce0; border-radius: 0 8px 8px 8px; top: -1px; }

QToolTip {
  background: #fff; color: #202124; border: 1px solid #dadce0;
  border-radius: 6px; padding: 6px 8px;
}
QGroupBox {
  border: 1px solid #dadce0; border-radius: 8px; margin-top: 12px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #5f6368; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #5f6368; background: #fff; }
QCheckBox::indicator:checked { background: #1a73e8; border-color: #1a73e8; }
QDialog QPushButton { min-width: 80px; }
"""

MD_CSS = """
<style>
  body { font-family: system-ui, Segoe UI, Roboto, Arial, sans-serif; line-height: 1.25; }
  table { border-collapse: collapse; margin: 8px 0; width: 100%; }
  th, td { border: 1px solid rgba(136,136,136,0.25); padding: 6px 8px; text-align: left; vertical-align: top; }
  thead th { background: rgba(136,136,136,0.06); }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
</style>
"""