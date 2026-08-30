import logging

from PySide6.QtWidgets import QMessageBox


logger = logging.getLogger("ferreteria_gui")


def show_error(parent, title, exc):
    logger.exception("%s: %s", title, exc)
    QMessageBox.critical(parent, title, str(exc) or "Ocurrió un error inesperado")


STYLE = """
QMainWindow, QWidget { background: #f4f6f8; color: #17202a; font-size: 11pt; }
QPushButton { background: #e7ebef; border: 1px solid #9daab6; border-radius: 6px; padding: 10px 16px; font-size: 11pt; }
QPushButton:hover { background: #dce3e9; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 3px solid #f39c12; background: #fff8e8; color: #17202a; }
QPushButton[class="action"] { background: #dce8f2; border-color: #7e9db7; min-height: 24px; padding: 8px 10px; font-size: 10pt; }
QPushButton#primary { background: #1877c9; color: white; font-weight: bold; font-size: 18px; padding: 14px 24px; }
QPushButton#primary:focus { border: 4px solid #f5b041; background: #125d9d; color: white; }
QPushButton#danger { background: #b23b3b; color: white; }
QPushButton#danger:focus { border: 4px solid #f5b041; background: #8e2d2d; color: white; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #aeb8c2; border-radius: 5px; padding: 8px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background: #e5e9ed; color: #4b5563; border: 1px solid #8d99a5; }
QCheckBox:disabled { color: #4b5563; }
QCheckBox::indicator:disabled { border: 1px solid #7b8794; background: #d7dde3; }
QTableWidget { background: white; gridline-color: #dde2e7; alternate-background-color: #f7f9fa; }
QTableWidget::item:selected { background: #1769aa; color: #ffffff; }
QTableWidget::item:selected:!active { background: #245f8f; color: #ffffff; }
QHeaderView::section { background: #263746; color: white; padding: 8px; border: none; }
QListWidget { background: #263746; color: white; border: none; font-size: 15px; }
QListWidget::item { padding: 15px; }
QListWidget::item:selected { background: #1877c9; }
QLabel#pageTitle { font-size: 18pt; font-weight: bold; }
QLabel#businessName { font-size: 17pt; font-weight: bold; color: #263746; }
"""
