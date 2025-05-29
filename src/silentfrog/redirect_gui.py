from __future__ import annotations
from PyQt5 import QtCore, QtGui, QtWidgets

import threading
import time
import sys
from PyQt5 import QtGui


from pathlib import Path
from PyQt5 import QtCore, QtWidgets
from .redirect import check_redirects


class RedirectWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(str)

    def __init__(
        self,
        excel_path: str,
        timeout: int,
        workers: int,
        robots: bool,
        verify_ssl: bool,
    ):
        super().__init__()
        icon_path = Path(__file__).with_name("assets").joinpath("icon.png")
        self.excel_path = excel_path
        self.timeout = timeout
        self.workers = workers
        self.robots = robots
        self.verify_ssl = verify_ssl

        self._pause = threading.Event()

    # ---------- API per la GUI ------------------------------------------ #
    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()

    # ---------- codice in background ------------------------------------ #
    def run(self) -> None:
        def cb(done: int, total: int, url: str, status: str | int) -> None:
            # progress-bar
            self.progress.emit(int(done / total * 100))
            # log live
            self.log.emit(f"[{done}/{total}] {url} → {status}")
            # pausa gestita qui (thread worker)
            while self._pause.is_set():
                time.sleep(0.2)

        try:
            out = check_redirects(
                self.excel_path,
                timeout=self.timeout,
                max_workers=self.workers,
                respect_robots=self.robots,
                verify_ssl=self.verify_ssl,
                progress_callback=cb,
                pause_flag=self._pause,
            )
            self.finished.emit(str(out))
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"Errore: {exc}")
            self.finished.emit("")


# ----------------------- finestra GUI ----------------------------------- #
class RedirectWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        icon_dir = Path(__file__).with_name("assets")
        ext      = ".ico" if sys.platform.startswith("win") else ".png"
        self.setWindowIcon(QtGui.QIcon(str(icon_dir / f"icon{ext}")))
        self.setWindowTitle("Check Redirect – Silentfrog")
        self.setMinimumSize(650, 450)
        self._build_ui()

    # ----- costruzione interfaccia -------------------------------------- #
    def _build_ui(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)

        # file
        top = QtWidgets.QHBoxLayout()
        self.btn_file = QtWidgets.QPushButton("Carica xlsx")
        self.btn_file.clicked.connect(self._select_file)
        top.addWidget(self.btn_file)

        self.lbl_file = QtWidgets.QLabel("Nessun file selezionato")
        self.lbl_file.setStyleSheet("color: grey")
        top.addWidget(self.lbl_file, stretch=1)
        lay.addLayout(top)

        # opzioni
        form = QtWidgets.QFormLayout()

        self.spin_timeout = QtWidgets.QSpinBox()
        self.spin_timeout.setRange(1, 60)
        self.spin_timeout.setValue(10)
        form.addRow("Timeout (s):", self.spin_timeout)

        self.spin_threads = QtWidgets.QSpinBox()
        self.spin_threads.setRange(1, 20)
        self.spin_threads.setValue(5)
        form.addRow("Thread:", self.spin_threads)

        self.chk_robots = QtWidgets.QCheckBox("Rispetta robots.txt")
        self.chk_robots.setChecked(True)
        form.addRow(self.chk_robots)

        self.chk_ssl = QtWidgets.QCheckBox("Ignora errori SSL (meno sicuro)")
        form.addRow(self.chk_ssl)

        lay.addLayout(form)

        # progress & log
        self.bar = QtWidgets.QProgressBar()
        lay.addWidget(self.bar)

        self.txt_log = QtWidgets.QTextEdit()
        self.txt_log.setReadOnly(True)
        lay.addWidget(self.txt_log, stretch=1)

        # pulsanti
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Avvia")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._launch)
        btn_row.addWidget(self.btn_start)

        self.btn_pause = QtWidgets.QPushButton("Pausa")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)
        btn_row.addWidget(self.btn_pause)

        btn_row.addStretch()
        lay.addLayout(btn_row)

    # ----- slot GUI ------------------------------------------------------ #
    def _select_file(self) -> None:
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Seleziona file", "", "Excel (*.xlsx *.xls)"
        )
        if fname:
            self.excel_path = fname
            self.lbl_file.setText(Path(fname).name)
            self.lbl_file.setStyleSheet("")  # reset colore
            self.btn_start.setEnabled(True)

    def _launch(self) -> None:
        # blocca alcuni widget
        self.btn_start.setEnabled(False)
        self.btn_file.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.spin_timeout.setEnabled(False)
        self.spin_threads.setEnabled(False)
        self.chk_robots.setEnabled(False)
        self.chk_ssl.setEnabled(False)
        self.bar.setValue(0)
        self.txt_log.clear()

        self.worker = RedirectWorker(
            self.excel_path,
            timeout=self.spin_timeout.value(),
            workers=self.spin_threads.value(),
            robots=self.chk_robots.isChecked(),
            verify_ssl=not self.chk_ssl.isChecked(),
        )
        self.worker.progress.connect(self.bar.setValue)
        self.worker.log.connect(self.txt_log.append)
        self.worker.finished.connect(self._on_finish)
        self.worker.start()

    def _toggle_pause(self) -> None:
        self.worker.toggle_pause()
        if self.worker._pause.is_set():
            self.btn_pause.setText("Riprendi")
            # riabilita le opzioni
            self.spin_timeout.setEnabled(True)
            self.spin_threads.setEnabled(True)
            self.chk_robots.setEnabled(True)
            self.chk_ssl.setEnabled(True)
        else:
            self.btn_pause.setText("Pausa")
            self.spin_timeout.setEnabled(False)
            self.spin_threads.setEnabled(False)
            self.chk_robots.setEnabled(False)
            self.chk_ssl.setEnabled(False)

    def _on_finish(self, out_path: str) -> None:
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("Pausa")
        self.btn_file.setEnabled(True)

        if out_path:
            QtWidgets.QMessageBox.information(
                self, "Finito", f"Risultati salvati in:\n{out_path}"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Errore", "Elaborazione interrotta o fallita."
            )
