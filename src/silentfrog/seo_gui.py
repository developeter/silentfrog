from __future__ import annotations
from pathlib import Path
from typing import Any
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QUrl, Qt
from .seo_crawler import analyse, analyse_images
from PyQt5.QtGui import QColor, QBrush

import webbrowser
import sys
import asyncio
import threading
import logging
import json
import html as _html


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
            row = self._rows[index.row()]
            return row[index.column()] if index.column() < len(row) else ""
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
        order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Smart sort: understands bytes / KB / MB, plain numbers, or strings."""

        def _size_to_bytes(text: str) -> float | None:
            units = {"b": 1, "kb": 1_024, "mb": 1_048_576}
            parts = text.lower().split()
            if len(parts) != 2:
                return None
            try:
                num = float(parts[0])
            except ValueError:
                return None
            return num * units.get(parts[1], 1)

        def _key(row: list[str]):
            cell = row[column].strip()
            # Try human-friendly size first
            size_val = _size_to_bytes(cell)
            if size_val is not None:
                return size_val
            # Try plain numbers (“123” or “3.14”)
            if cell.replace(".", "", 1).isdigit():
                return float(cell)
            # Fallback: case-insensitive text
            return cell.lower()

        try:
            self.layoutAboutToBeChanged.emit()
            self._rows.sort(
                key=_key,
                reverse=(order == QtCore.Qt.SortOrder.DescendingOrder),
            )
        finally:
            self.layoutChanged.emit()


class MetaModel(_BaseModel):
    HEADERS = ["Name/Property", "Content", "Length"]
    # add colour coding for Title/Description length
    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = QtCore.Qt.DisplayRole,  # type: ignore[attr-defined]
    ):

        # 1️  Standard text display
        if role == QtCore.Qt.DisplayRole:                # type: ignore[attr-defined]
            return super().data(index, role)

        # 2️  Background colouring (only column “Length”)
        if role == Qt.BackgroundRole and index.column() == 2:
            GOOD = QBrush(QColor(0, 180, 0, 60))         # semi-transparent green
            BAD  = QBrush(QColor(200, 0, 0, 60))         # semi-transparent red

            key = self._rows[index.row()][0].lower()     # e.g. "description"
            try:
                n = int(self._rows[index.row()][2])
            except ValueError:
                return BAD

            # Description ideal 120-160 chars
            if key == "description":
                return GOOD if 120 <= n <= 160 else BAD

            # Robots meta: flag “noindex/nofollow”
            if key == "robots":
                bad = any(tok in self._rows[index.row()][1].lower()
                          for tok in ("noindex", "nofollow"))
                return BAD if bad else GOOD

        # Fallback → default behaviour
        return super().data(index, role)

class HeaderModel(_BaseModel):
    HEADERS = ["Tag", "Text"]

# -------------------------------------------------------------------
# Links tab model – colour “Status” column (index 3)
# -------------------------------------------------------------------
class LinksModel(GenericModel):
    """Highlights HTTP status: green 2xx | yellow 3xx | red 4xx/5xx."""

    def __init__(self, rows: list[list[str]]) -> None:
        headers = ["URL", "Anchor", "Follow ?", "Status"]
        super().__init__(headers, rows)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = QtCore.Qt.DisplayRole,          # type: ignore[attr-defined]
    ):
        # 1️⃣  Normal cell text
        if role == QtCore.Qt.DisplayRole:                # type: ignore[attr-defined]
            return super().data(index, role)

        # 2️⃣  Background colour for Status column
        if role == Qt.BackgroundRole and index.column() == 3:
            GREEN  = QBrush(QColor(  0, 180,   0, 60))   # semi-transparent
            YELLOW = QBrush(QColor(255, 200,   0, 60))
            RED    = QBrush(QColor(200,   0,   0, 60))

            try:
                code = int(self._rows[index.row()][3])
            except ValueError:
                return RED

            if 200 <= code < 300:
                return GREEN
            if 300 <= code < 400:
                return YELLOW
            return RED

        return super().data(index, role)

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

        # link cliccabili
        self.img_view.doubleClicked.connect(self._open_img_url)
        self.meta_view.doubleClicked.connect(self._open_meta_url)


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
        self.tabs.addTab(self.img_view, "Images")

        self.link_view = QtWidgets.QTableView()
        self.link_view.setModel(_BaseModel([]))
        self.link_view.setSortingEnabled(True)
        self.tabs.addTab(self.link_view, "Link")

        # ---------- Redirect tab ----------------------------------------- #
        self.redir_view = QtWidgets.QTableView()
        self.redir_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.redir_view, "Redirect")

        # ---------- Canonical tab ---------------------------------------- #
        self.canon_view = QtWidgets.QTableView()
        self.canon_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.canon_view, "Canonical")

        # ---------- Robots tab ------------------------------------------- #
        self.robots_view = QtWidgets.QTableView()
        self.robots_view.setModel(_BaseModel([]))   # empty model for now
        self.tabs.addTab(self.robots_view, "Robots")

        # ---------- Hreflang tab ----------------------------------------- #
        self.hlang_view = QtWidgets.QTableView()
        self.hlang_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.hlang_view, "Hreflang")

        # -----------Schema.org tab as a read-only QTextEdit --------------- #
        self.schema_view = QtWidgets.QTextEdit()
        self.schema_view.setReadOnly(True)
        self.tabs.addTab(self.schema_view, "Schema.org")

        self.key_view = QtWidgets.QTableView()
        self.key_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.key_view, "Keywords")

        # ---------- AI Crawl tab --------------------------------------- #
        self.ai_view = QtWidgets.QTableView()
        self.ai_view.setModel(_BaseModel([]))
        self.tabs.addTab(self.ai_view, "AI Crawl")
   
       # ─── SERP preview tab ────────────────────────────────────────────────────
        self.serp_view = QtWidgets.QTextBrowser()
        self.serp_view.setOpenExternalLinks(True)
        self.serp_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.serp_view.setMaximumHeight(220)
        self.serp_view.setStyleSheet("background:#fff; border:0;")

        self.serp_table = QtWidgets.QTableView()
        self.serp_table.setModel(_BaseModel([]))
        self.serp_table.setSortingEnabled(False)

        serp_tab = QtWidgets.QWidget()
        serp_lay = QtWidgets.QVBoxLayout(serp_tab)  # PyQt5 accepts only the parent
        serp_lay.setSpacing(0)                      # spacing = 0
        serp_lay.setContentsMargins(0, 0, 0, 0)     # left, top, right, bottom
        # ------------------------------------------------------------------------

        serp_lay.addWidget(self.serp_view)
        serp_lay.addWidget(self.serp_table)
        self.tabs.addTab(serp_tab, "SERP")

        # pulsanti extra --------------------------------------------------- #
        hbox = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Esporta Excel (TBD)")
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

    # -------------------- avvio analisi (thread worker) ------------------- #
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
        
        
        # ---------- Robots table ---------------------------------------- #
        robots_map: dict = data.get("robots", {})
        meta_str = data.get("meta_robots", "") or "—"

        rows: list[list[str]] = [["Meta / X-Robots-Tag", meta_str], ["", ""]]

        # Flatten every UA section:
        for ua, directives in robots_map.items():
            rows.append([f"User-Agent: {ua}", ""])          # header row
            for verb, path in directives:
                rows.append([verb, path])

        if not robots_map:
            rows.append(["robots.txt", "Not fetched or empty"])

        model = GenericModel(["Directive", "Value"], rows)
        _set(self.robots_view, model)
        self.robots_view.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )


        # ---------- Canonical table -------------------------------------- #
        canon = data.get("canonical", {})
        canon_rows = [
            ["Canonical URL", canon.get("target", "") or "—"],
            ["Self-referencing", "Yes" if canon.get("self") else "No"],
            ["Multiple canonicals", "Yes" if canon.get("multiple") else "No"],
            ["Canonical status", canon.get("status", "") or "—"],
        ]
        _set(self.canon_view, GenericModel(["Check", "Value"], canon_rows))


        # ---------- Redirect table -------------------------------------- #
        red = data.get("redirect", {})
        chain_txt = " ➜ ".join(red.get("chain", [])) if red.get("chain") else "—"
        red_rows = [
            ["Redirect chain", chain_txt],
            ["Hop count",      str(red.get("hops", ""))],
            ["Final status",   red.get("final_status", "")],
            ["Loop detected",  "Yes" if red.get("loop") else "No"],
        ]
        _set(self.redir_view, GenericModel(["Check", "Value"], red_rows))
        self.redir_view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

        # -------- Links tab ------------------------------------------
        link_rows = data.get("links", [])
        _set(self.link_view, LinksModel(link_rows))
        self.link_view.setAlternatingRowColors(False)   # keep colours crisp
        self.link_view.horizontalHeader().setSectionResizeMode(
             0, QtWidgets.QHeaderView.Stretch
         )

        # ---------- Hreflang table ------------------------------------- #
        h_rows = data.get("hreflang", [])
        h_headers = ["Lang", "Target URL", "Status", "Lang-OK?", "Return?"]
        _set(self.hlang_view, GenericModel(h_headers, h_rows))
        self.hlang_view.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )

        # ---------- AI Crawl table ------------------------------------- #
        ai_rows = data.get("ai_crawl", [])
        ai_headers = ["Agent", "Robots.txt OK", "Meta noai?", "Verdict"]
        _set(self.ai_view, GenericModel(ai_headers, ai_rows))
        self.ai_view.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        self.ai_view.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )

        # ---------- SERP Preview & Title Audit ------------------------- #
        serp = data.get("serp", {})
        audit = data.get("serp_audit", {})

        # Force-light preview; title and URL colours match real Google
        desc = serp.get("description", "")
        if len(desc) > 160:
            desc = desc[:157].rstrip() + "…"

        serp_html = f"""
        <div style='font-family:Roboto,Arial,sans-serif;font-size:14px;
                    line-height:1.3;background:#fff;color:#202124;padding:8px'>
           <table cellpadding='0' cellspacing='0' style='border:none;margin:0;padding:0'>
              <tr>
                <td rowspan='2' style='padding-right:6px;vertical-align:middle'>
                  {"<img src=\"" + serp["favicon"] + "\" width='30' height='30' alt='icon'/>"
                   if serp.get("favicon") else ""}
                </td>
                <td style='font-size:14px;color:#202124;font-weight:500;vertical-align:bottom'>
                  {serp["site_name"]}
                </td>
              </tr>
              <tr>
                <td style='font-size:12px;color:#4d5156;vertical-align:top'>
                  {serp["breadcrumb"]}
                </td>
              </tr>
            </table>
            <div>
                <a href='{serp["url"]}'
                style='font-size:18px;font-weight:400;color:#1a0dab;
                        text-decoration:none;display:inline-block;max-width:600px;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>
                    {serp["title"]}
                </a>
            </div>
            <div style='font-size:14px;color:#4d5156;margin-top:3px;max-width:600px'>
                {serp["description"]}
            </div>
        </div>
        """


        self.serp_view.setHtml(serp_html)

        audit_rows = [
            ["Length (chars)", audit.get("char_len", "")],
            ["Length (pixels)", audit.get("px_len", "")],
            ["> 60 chars", audit.get("too_long", "")],
            ["< 30 chars", audit.get("too_short", "")],
            ["> 561 px", audit.get("px_over", "")],
            ["< 200 px", audit.get("px_under", "")],
            ["Equals H1", audit.get("equals_h1", "")],
            ["Missing", audit.get("missing", "")],
        ]
        _set(self.serp_table, GenericModel(["Check", "Result"], audit_rows))
        self.serp_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )

        # ----- Schema.org tab: show data AND issues (like Google/Schema tester) -----
        schema_items = data.get("schema", [])
        if not schema_items:
            self.schema_view.setHtml(
                "<span style='color:red;font-weight:bold'>Schema.org not found</span>"
            )
        else:
            # theme-aware colours (QTextEdit uses Palette.Base for its background)
            bg = self.schema_view.palette().color(QtGui.QPalette.Base)
            is_dark = bg.value() < 128
            pre_bg     = "#111111" if is_dark else "#f7f7f7"
            pre_fg     = "#f0f0f0" if is_dark else "#202124"
            pre_border = "#444444" if is_dark else "#cccccc"
            # ensure the widget background follows the theme (HTML colors handle inner blocks)
            self.schema_view.setStyleSheet(
                "background:#1e1e1e; color:#f0f0f0;" if is_dark else "background:#ffffff; color:#202124;"
            )

            # split issues and data; count by source
            issues = []
            blocks = []
            counts = {"json-ld": 0, "microdata": 0, "rdfa": 0, "opengraph": 0, "json-ld-raw": 0}
            for row in schema_items:
                if isinstance(row, dict) and "_schema_issues" in row:
                    issues.extend(row["_schema_issues"] or [])
                    continue
                if isinstance(row, dict):
                    via = str(row.get("_extracted_via", ""))
                    counts[via] = counts.get(via, 0) + 1
                    try:
                        blocks.append(json.dumps(row, indent=2, ensure_ascii=False))
                    except Exception:
                        blocks.append(str(row))
                    continue
                if isinstance(row, list) and row:
                    raw_json = row[0]
                    try:
                        parsed = json.loads(raw_json)
                        blocks.append(json.dumps(parsed, indent=2, ensure_ascii=False))
                    except Exception:
                        counts["json-ld-raw"] = counts.get("json-ld-raw", 0) + 1
                        blocks.append(str(raw_json))
                    continue
                blocks.append(str(row))

            total = sum(v for v in counts.values())
            color = "#1a7f37" if total and not issues else ("#b26a00" if total else "#c62828")
            hdr = (
                f"<div style='font-weight:bold;color:{color}'>"
                f"Schema.org: {total} items &nbsp; "
                f"(JSON-LD {counts.get('json-ld',0)}, Microdata {counts.get('microdata',0)}, "
                f"RDFa {counts.get('rdfa',0)}, OpenGraph {counts.get('opengraph',0)}, "
                f"Raw {counts.get('json-ld-raw',0)})"                
                f"</div>"
            )
            err = ""
            if issues:
                items = "".join(f"<li>{_html.escape(x)}</li>" for x in sorted(set(issues)))
                err = f"<div style='color:#c62828;margin:6px 0'><b>Issues</b><ul>{items}</ul></div>"
            code = "".join(
                f"<pre style='background:{pre_bg};color:{pre_fg};border:1px solid {pre_border};"
                f"padding:6px;white-space:pre-wrap'>"
                f"{_html.escape(b)}"
                f"</pre>"
                for b in blocks
            )
            self.schema_view.setHtml(hdr + err + code)

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
            # combina alt/title con w/h/peso
            merged = [
                [u, alt, title, w, h, hr]
                for (u, alt, title, *_), (u2, w, h, hr) in zip(rows, out)
            ]
            self.dataReady.emit({"img_update": merged})
        except Exception as exc:                           # noqa: BLE001
            self.errorSig.emit(str(exc))

    # --- APRI URL ---------------------------------------------------- #
    def _open_img_url(self, index: QtCore.QModelIndex) -> None:
        url = index.sibling(index.row(), 0).data()  # colonna Src
        if url and isinstance(url, str):
            webbrowser.open(url)

    def _open_meta_url(self, index: QtCore.QModelIndex) -> None:
        name = index.sibling(index.row(), 0).data()
        if name in ("og:image", "og:image:url"):
            url = index.sibling(index.row(), 1).data()
            if url and isinstance(url, str):
                webbrowser.open(url)

    #Converte le righe (url, w, h, peso) nel formato a 6 colonne.
    def _update_images(self, rows: list[list[str]]) -> None:
        headers = ["Src", "Alt", "Title", "W", "H", "Peso"]
        model = GenericModel(headers, rows)
        self.img_view.setModel(model)
        model.layoutChanged.emit()
        self.img_view.resizeColumnsToContents()
        # --- keep URL column reasonable (max 280 px) ------------------
        self.img_view.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Interactive
        )
        self.img_view.setColumnWidth(0, 280)


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
