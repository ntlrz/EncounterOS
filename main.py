import sys
from PySide6 import QtWidgets
from gm_window import GMWindow

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = GMWindow()
    w.show()
    sys.exit(app.exec())