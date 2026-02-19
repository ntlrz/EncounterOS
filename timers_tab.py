from __future__ import annotations
from PySide6 import QtWidgets, QtCore

class TimersTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QMainWindow):
        super().__init__(parent)
        self.parent = parent

        v = QtWidgets.QVBoxLayout(self)

        # Round timer
        gb = QtWidgets.QGroupBox("Round Timer")
        h = QtWidgets.QHBoxLayout(gb)
        self.lblRound = QtWidgets.QLabel("00:00")
        self.btnStart = QtWidgets.QPushButton("Start")
        self.btnStop  = QtWidgets.QPushButton("Stop")
        self.btnReset = QtWidgets.QPushButton("Reset")
        h.addWidget(self.lblRound); h.addStretch(1)
        h.addWidget(self.btnStart); h.addWidget(self.btnStop); h.addWidget(self.btnReset)
        v.addWidget(gb)

        self._sec = 0
        self._t = QtCore.QTimer(self)
        self._t.setInterval(1000)
        self._t.timeout.connect(self._tick)
        self.btnStart.clicked.connect(self._t.start)
        self.btnStop .clicked.connect(self._t.stop)
        self.btnReset.clicked.connect(self._reset)

        # Named timers table
        gb2 = QtWidgets.QGroupBox("Named Timers")
        v2 = QtWidgets.QVBoxLayout(gb2)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name","Mode","Time (mm:ss)","Start/Stop","Reset"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v2.addWidget(self.table)

        row_actions = QtWidgets.QHBoxLayout()
        self.btnAdd = QtWidgets.QPushButton("Add Timer")
        self.btnDel = QtWidgets.QPushButton("Delete Selected")
        row_actions.addWidget(self.btnAdd); row_actions.addWidget(self.btnDel); row_actions.addStretch(1)
        v2.addLayout(row_actions)
        v.addWidget(gb2)

        self._timers = []  # list of dicts: {sec:int, mode:'stopwatch'|'countdown', t:QTimer, widgets:...}

        self.btnAdd.clicked.connect(self._add_timer)
        self.btnDel.clicked.connect(self._delete_selected)

    # --- Round timer ---
    def _tick(self):
        self._sec += 1
        m, s = divmod(self._sec, 60)
        self.lblRound.setText(f"{m:02d}:{s:02d}")

    def _reset(self):
        self._sec = 0
        self.lblRound.setText("00:00")

    # --- Named timers ---
    def _add_timer(self):
        r = self.table.rowCount()
        self.table.insertRow(r)

        name = QtWidgets.QLineEdit("New Timer")
        mode = QtWidgets.QComboBox(); mode.addItems(["stopwatch","countdown"])
        time = QtWidgets.QTimeEdit(); time.setDisplayFormat("mm:ss"); time.setTime(QtCore.QTime(0,0))
        btnGo = QtWidgets.QPushButton("Start")
        btnRe = QtWidgets.QPushButton("Reset")

        self.table.setCellWidget(r,0,name)
        self.table.setCellWidget(r,1,mode)
        self.table.setCellWidget(r,2,time)
        self.table.setCellWidget(r,3,btnGo)
        self.table.setCellWidget(r,4,btnRe)

        # Model
        rec = {"sec":0, "mode":"stopwatch", "t":QtCore.QTimer(self)}
        rec["t"].setInterval(1000)
        def tick():
            if mode.currentText()=="stopwatch":
                rec["sec"] += 1
            else:
                rec["sec"] = max(0, rec["sec"] - 1)
            m, s = divmod(rec["sec"], 60)
            time.setTime(QtCore.QTime(0, m, s))
            if mode.currentText()=="countdown" and rec["sec"]==0:
                rec["t"].stop()
        rec["t"].timeout.connect(tick)

        def start_stop():
            if rec["t"].isActive():
                rec["t"].stop(); btnGo.setText("Start")
            else:
                # initialize from editor for countdown
                if mode.currentText()=="countdown":
                    mm = time.time().minute(); ss = time.time().second()
                    rec["sec"] = mm*60 + ss
                btnGo.setText("Stop"); rec["t"].start()
        btnGo.clicked.connect(start_stop)

        def reset():
            rec["t"].stop(); btnGo.setText("Start")
            rec["sec"] = 0
            time.setTime(QtCore.QTime(0,0))
        btnRe.clicked.connect(reset)

        def mode_changed(s):
            rec["mode"] = s
            reset()
        mode.currentTextChanged.connect(mode_changed)

        self._timers.append(rec)

    def _delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._timers):
                self._timers[r]["t"].stop()
                self._timers.pop(r)
            self.table.removeRow(r)