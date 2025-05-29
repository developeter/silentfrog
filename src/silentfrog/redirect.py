from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests
import urllib.robotparser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__all__ = ["check_redirects"]

USER_AGENT = "SilentFrog/1.0 (+https://example.com)"
_logger = logging.getLogger(__name__)


def _robots_allowed(url: str) -> bool:
    parsed = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True


def _new_session(verify_ssl: bool) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    s.verify = verify_ssl
    retry = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=20)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _single(
    sess: requests.Session,
    old_url: str,
    new_url: str,
    timeout: int,
    respect_robots: bool,
) -> Tuple[str | int, str, bool, int, str]:
    if respect_robots and not _robots_allowed(old_url):
        return "Robots-block", "", False, 0, ""

    try:
        r = sess.get(old_url, allow_redirects=True, timeout=timeout)
        final = r.url
        ok = final.rstrip("/") == new_url.rstrip("/")
        chain = " -> ".join([h.url for h in r.history] + [final])
        return r.status_code, final, ok, len(r.history), chain
    except requests.exceptions.SSLError as exc:
        return "SSL error", "", False, 0, str(exc)
    except requests.RequestException as exc:
        return "Error", "", False, 0, str(exc)


def check_redirects(
    excel_path: str | Path,
    *,
    timeout: int = 10,
    max_workers: int = 5,
    respect_robots: bool = True,
    verify_ssl: bool = True,
    progress_callback: Callable[[int, int, str, str | int], None] | None = None,
    pause_flag: threading.Event | None = None,
) -> Path:
    """
    Legge un XLSX con colonne Old URL / New URL,
    crea <nome>_results.xlsx con font Arial 10 pt e righe 404 rosso chiaro.
    """
    excel_path = Path(excel_path)

    first_df = pd.read_excel(excel_path, nrows=1)
    if {"Old URL", "New URL"}.issubset(first_df.columns):
        df = pd.read_excel(excel_path)
    else:
        df = pd.read_excel(excel_path, header=None, names=["Old URL", "New URL"])

    total = len(df)
    for col in (
        "Status Code",
        "Final URL",
        "Redirect Correct",
        "Redirect Chain Length",
        "Redirect Chain URLs",
    ):
        if col not in df.columns:
            df[col] = ""

    done = 0
    lock = threading.Lock()

    def _task(idx_row: Tuple[int, pd.Series]) -> None:
        nonlocal done
        idx, row = idx_row
        sess = _new_session(verify_ssl)
        status, final, ok, length, chain = _single(
            sess,
            str(row["Old URL"]),
            str(row["New URL"]),
            timeout,
            respect_robots,
        )

        df.loc[idx, "Status Code"] = status
        df.loc[idx, "Final URL"] = final
        df.loc[idx, "Redirect Correct"] = "Sì" if ok else "No"
        df.loc[idx, "Redirect Chain Length"] = length
        df.loc[idx, "Redirect Chain URLs"] = chain

        with lock:
            done += 1
            if progress_callback:
                progress_callback(done, total, row["Old URL"], status)

        if pause_flag is not None:
            while pause_flag.is_set():
                time.sleep(0.2)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_task, df.iterrows()))

    out = excel_path.with_stem(excel_path.stem + "_results")
    # ---------- scrittura + styling ----------------------------------- #
    from openpyxl.styles import Font, PatternFill

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")

        wb = writer.book
        ws = writer.sheets["Results"]

        default_font = Font(name="Arial", size=10)
        red_fill = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")

        # trova indice colonna Status Code
        status_idx = None
        for i, c in enumerate(ws[1], 1):
            if c.value == "Status Code":
                status_idx = i
                break

        for row in ws.iter_rows():
            for cell in row:
                cell.font = default_font
            if status_idx and row[status_idx - 1].value == 404:
                for cell in row:
                    cell.fill = red_fill

    return out
