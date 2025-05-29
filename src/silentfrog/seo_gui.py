from __future__ import annotations

import sys
import asyncio
import threading
import logging
from pathlib import Path
from typing import Any

from PyQt5 import QtCore, QtGui, QtWidgets

from .seo_crawler import analyse

from functools import partial
from .seo_crawler import analyse, analyse_images

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#                               MODELLI TABELLA                               #
# --------------------------------------------------------------------------- #
class _BaseModel(QtCore.QAbstractTableModel):
    HEADERS: list[str] = []

    def __init__(self, rows: list[list[str]]) -> None:
        super().__init__()
        self._rows = rows

    # dimensioni ----------------------------------------------------------- #
    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(self.HEADERS)

    # dati ----------------------------------------------------------------- #
    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = QtCore.Qt.DisplayRole,  # type: ignore[attr-defined]
    ):
        if role == QtCore.Qt.DisplayRole:  # type: ignore[attr-defined]
            return self._rows[index.row()][index.column()]
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,  # type: ignore[attr-defined]
    ):
        if (
            role == QtCore.Qt.DisplayRole  # type: ignore[attr-defined]
            and orientation == QtCore.Qt.Horizontal  # type: ignore[attr-defined]
        ):
            return self.HEADERS[section]
        return None

class GenericModel(_BaseModel):
    """Modello tabellare con header dinamico."""

    def __init__(self, headers: list[str], rows: list[list[str]]) -> None:
        self.HEADERS = headers            # type: ignore[assignment]
        super().__init__(rows)

    def sort(
        self,
        column: int,
        order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,  # noqa: N802
    ):

        try:
            self.layoutAboutToBeChanged.emit()
            self._rows.sort(
                key=lambda r: float(r[column].replace(',', '').replace('KB','').replace('MB','').replace('GB',''))
                if r[column].replace('.','',1).isdigit() else r[column].lower(),
                reverse=(order == QtCore.Qt.SortOrder.DescendingOrder), 
            )
        finally:
            self.layoutChanged.emit()


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]


class HeaderModel(_BaseModel):
    HEADERS = ["Tag", "Text"]


# --------------------------------------------------------------------------- #
#                              FINESTRA PRINCIPALE                            #
# --------------------------------------------------------------------------- #
class WebpageSeoWindow(QtWidgets.QWidget):
    """Analisi SEO di una singola pagina – crawler asincrono."""
    
    # --- SEGNALI thread-safe ------------------------------------------
    dataReady = QtCore.pyqtSignal(dict)     # payload dei dati
    errorSig  = QtCore.pyqtSignal(str)      # messaggio d’errore

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Analisi webpage SEO – Silentfrog")
        self.resize(950, 620)

        # icona (fallback se non trova tema)
        icon_path = Path(__file__).with_name("assets").joinpath("icon.png")
        self.setWindowIcon(QtGui.QIcon(str(icon_path)))
       
        # mantiene vivi i modelli delle tabelle
        self._models: list[QtCore.QAbstractTableModel] = []

        self._build_ui()
        
        # connessioni segnali → slot GUI
        self.dataReady.connect(self._populate_tables)
        self.errorSig.connect(self._show_error)

    # --------------------------- costruzione UI --------------------------- #
    def _build_ui(self) -> None:
        vbox = QtWidgets.QVBoxLayout(self)

        # barra URL -------------------------------------------------------- #
        urlbar = QtWidgets.QHBoxLayout()
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        urlbar.addWidget(self.url_edit, 1)

        self.btn_go = QtWidgets.QPushButton("Analizza")
        self.btn_go.clicked.connect(self._start_analysis)
        urlbar.addWidget(self.btn_go)
        vbox.addLayout(urlbar)

        # Tab -------------------------------------------------------------- #
        self.tabs = QtWidgets.QTabWidget()
        vbox.addWidget(self.tabs, 1)

        self.meta_view = QtWidgets.QTableView()
        self.meta_view.setModel(MetaModel([]))
        self.meta_view.setSortingEnabled(True)
        self.tabs.addTab(self.meta_view, "Meta tag")

        self.h_view = QtWidgets.QTableView()
        self.h_view.setModel(HeaderModel([]))
        self.h_view.setSortingEnabled(True)
        self.tabs.addTab(self.h_view, "Header H1-H6")

        self.img_view = QtWidgets.QTableView()
        self.img_view.setModel(_BaseModel([]))
        self.img_view.setSortingEnabled(True)
        self.tabs.addTab(self.img_view, "Immagini")

        self.link_view = QtWidgets.QTableView()
        self.link_view.setModel(_BaseModel([]))
        self.link_view.setSortingEnabled(True)
        self.tabs.addTab(self.link_view, "Link")

        self.schema_view = QtWidgets.QTableView()
        self.schema_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.schema_view, "Schema.org")

        self.key_view = QtWidgets.QTableView()
        self.key_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.key_view, "Keywords")

        # pulsanti extra --------------------------------------------------- #
        hbox = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Esporta Excel")
        self.btn_export.setEnabled(False)
        hbox.addWidget(self.btn_export)

        self.btn_img_dl = QtWidgets.QPushButton("Analizza immagini")
        self.btn_img_dl.clicked.connect(self._start_img_analysis)
        self.btn_img_dl.setEnabled(False)
        hbox.addWidget(self.btn_img_dl)

        hbox.addStretch()
        vbox.addLayout(hbox)

        # progress --------------------------------------------------------- #
        self.bar = QtWidgets.QProgressBar()
        self.bar.setVisible(False)
        vbox.addWidget(self.bar)

    # -------------------- avvio analisi (thread worker) ------------------ #
    def _start_analysis(self) -> None:
        self._models.clear()           # libera modelli precedenti
        log.info("Pulizia modelli, ora: %d", len(self._models))
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "URL mancante", "Inserisci un URL.")
            return

        self.btn_go.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)

        threading.Thread(target=self._run_worker, args=(url,), daemon=True).start()

    # --------------------------- worker thread --------------------------- #
    def _run_worker(self, url: str) -> None:
        try:
            data = asyncio.run(analyse(url, timeout=15))
            log.info(
                "Crawler OK – meta=%d headers=%d images=%d links=%d schema=%d kw=%d",
                len(data["meta"]),
                len(data["headers"]),
                len(data["images"]),
                len(data["links"]),
                len(data["schema"]),
                len(data["keywords"]),
            )
            self.dataReady.emit(data)          # <-- passa i dati al main-thread
        except Exception as exc:  # noqa: BLE001
            self.errorSig.emit(str(exc))       # <-- mostra errore in GUI
        finally:
            QtCore.QTimer.singleShot(0, self._reset_ui)

    # ---------------------------- slot GUI ------------------------------ #
    def _populate_tables(self, data: dict[str, Any]) -> None:
        
        # se arriva solo l'update immagini
        if "img_update" in data:
            self._update_images(data["img_update"])
            return

        log.info("Popolo le tabelle nella GUI – righe meta=%d", len(data["meta"]))

        def _set(view: QtWidgets.QTableView, model: QtCore.QAbstractTableModel):
            self._models.append(model)            # <-- salva il riferimento
            was_sorted = view.isSortingEnabled()
            view.setSortingEnabled(False)
            view.setModel(model)
            model.layoutChanged.emit()
            view.resizeColumnsToContents()
            view.setSortingEnabled(was_sorted)

        _set(self.meta_view,   MetaModel(data["meta"]))
        _set(self.h_view,      HeaderModel(data["headers"]))

        _set(self.img_view,    GenericModel(
            ["Src", "Alt", "Title", "Peso", "W", "H"], data["images"])
        )
        _set(self.link_view,   GenericModel(
            ["Href", "Tipo", "Follow", "Status"], data["links"])
        )
        _set(self.schema_view, GenericModel(["JSON-LD"], data["schema"]))
        _set(self.key_view,    GenericModel(["Termine", "Freq"], data["keywords"]))
        self._update_images(data["images"])


        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.btn_export.setEnabled(True)
        self.btn_img_dl.setEnabled(True)
        log.info("Modelli vivi dopo populate: %d", len(self._models))

    def _start_img_analysis(self) -> None:
        # modello corrente → righe immagine
        model: GenericModel = self.img_view.model()  # type: ignore[assignment]
        if model is None or model.rowCount() == 0:
            QtWidgets.QMessageBox.information(self, "Niente da fare", "Tabella immagini vuota.")
            return

        rows = [model._rows[i] for i in range(model.rowCount())]
        threading.Thread(
            target=self._run_img_worker,
            args=(rows,),
            daemon=True,
        ).start()


    def _run_img_worker(self, rows: list[list[str]]) -> None:
        try:
            out = asyncio.run(analyse_images(self.url_edit.text(), rows, timeout=15))
            self.dataReady.emit({"img_update": out})  # piggy-back sul segnale esistente
        except Exception as exc:  # noqa: BLE001
            self.errorSig.emit(str(exc))


    def _update_images(self, rows: list[list[str]]) -> None:
        
        img_headers = ["Src", "Alt", "Title", "W", "H", "Peso"]
        # append w/h/peso alle vecchie colonne o rimpiazza?
        self.img_view.setModel(GenericModel(img_headers, rows))
        model = self.img_view.model()
        if isinstance(model, QtCore.QAbstractTableModel):  # evita “None” per Pylance
            model.layoutChanged.emit()
        self.img_view.resizeColumnsToContents()
        log.info("Aggiornate immagini: %d righe", len(rows))


    def _reset_ui(self) -> None:
        self.bar.setVisible(False)
        self.btn_go.setEnabled(True)

    # mostra un messaggio di errore (deve restituire None)
    def _show_error(self, msg: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Errore", msg)

# --------------------------- avvio stand-alone --------------------------- #
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = WebpageSeoWindow()
    win.show()
    sys.exit(app.exec())
