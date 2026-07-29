import os
import sys
from PySide6 import QtCore, QtWidgets
from gm_window import GMWindow
from tracker_overlay import overlay_runtime_log


def create_application(argv=None):
    """Create the process QApplication once, or reuse the existing instance."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        list(argv if argv is not None else sys.argv)
    )


def schedule_overlay_smoke_test(app, window):
    """Frozen/source lifecycle probe enabled only by an explicit environment flag."""
    def show_overlay():
        overlay_runtime_log("Overlay smoke test toggling on")
        window.btnOverlay.setChecked(True)
        QtCore.QTimer.singleShot(350, verify_overlay)

    def verify_overlay():
        overlay = window.overlay_win
        if overlay is None or not overlay.isVisible():
            overlay_runtime_log("Overlay smoke test failed to show overlay")
            app.exit(2)
            return
        overlay_runtime_log("Overlay smoke test verified visible overlay")
        window.btnOverlay.setChecked(False)
        QtCore.QTimer.singleShot(100, lambda: app.exit(0))

    QtCore.QTimer.singleShot(0, show_overlay)


def run(argv=None) -> int:
    app = create_application(argv)
    w = GMWindow()
    w.show()
    if os.environ.get("ENCOUNTEROS_OVERLAY_SMOKE_TEST") == "1":
        schedule_overlay_smoke_test(app, w)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
