from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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
_RESULT_COLUMNS = (
    "Status Code",
    "Final URL",
    "Redirect Correct",
    "Redirect Chain Length",
    "Redirect Chain URLs",
)


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


@dataclass(frozen=True, slots=True)
class _RedirectRowResult:
    index: int
    old_url: str
    status: str | int
    final_url: str
    is_correct: bool
    chain_length: int
    chain_urls: str


def _load_redirect_frame(excel_path: Path) -> pd.DataFrame:
    first_df = pd.read_excel(excel_path, nrows=1)
    has_headers = {"Old URL", "New URL"}.issubset(first_df.columns)
    if has_headers:
        return pd.read_excel(excel_path)
    return pd.read_excel(excel_path, header=None, names=["Old URL", "New URL"])


def _ensure_result_columns(df: pd.DataFrame) -> None:
    for column in _RESULT_COLUMNS:
        if column not in df.columns:
            df[column] = ""


def _redirect_jobs(df: pd.DataFrame) -> list[tuple[int, str, str]]:
    jobs: list[tuple[int, str, str]] = []
    for index, row in df.iterrows():
        jobs.append((index, str(row["Old URL"]), str(row["New URL"])))
    return jobs


def _run_redirect_job(
    job: tuple[int, str, str],
    *,
    timeout: int,
    respect_robots: bool,
    verify_ssl: bool,
) -> _RedirectRowResult:
    index, old_url, new_url = job
    session = _new_session(verify_ssl)
    status, final_url, is_correct, chain_length, chain_urls = _single(
        session,
        old_url,
        new_url,
        timeout,
        respect_robots,
    )
    return _RedirectRowResult(index, old_url, status, final_url, is_correct, chain_length, chain_urls)


def _apply_redirect_result(df: pd.DataFrame, result: _RedirectRowResult) -> None:
    df.loc[result.index, "Status Code"] = result.status
    df.loc[result.index, "Final URL"] = result.final_url
    df.loc[result.index, "Redirect Correct"] = "Yes" if result.is_correct else "No"
    df.loc[result.index, "Redirect Chain Length"] = result.chain_length
    df.loc[result.index, "Redirect Chain URLs"] = result.chain_urls


def _pause_if_requested(pause_flag: threading.Event | None) -> None:
    if pause_flag is None:
        return
    while pause_flag.is_set():
        time.sleep(0.2)


def _status_column_index(worksheet) -> int | None:
    for index, cell in enumerate(worksheet[1], start=1):
        if cell.value == "Status Code":
            return index
    return None


def _style_redirect_sheet(worksheet) -> None:
    from openpyxl.styles import Font, PatternFill

    default_font = Font(name="Arial", size=10)
    red_fill = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")
    status_idx = _status_column_index(worksheet)

    for row in worksheet.iter_rows():
        for cell in row:
            cell.font = default_font
        if status_idx and row[status_idx - 1].value == 404:
            for cell in row:
                cell.fill = red_fill


def _write_redirect_results(df: pd.DataFrame, output_path: Path) -> Path:
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
        worksheet = writer.sheets["Results"]
        _style_redirect_sheet(worksheet)
    return output_path


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
    df = _load_redirect_frame(excel_path)
    _ensure_result_columns(df)
    total = len(df)
    done = 0
    jobs = _redirect_jobs(df)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(
            lambda job: _run_redirect_job(
                job,
                timeout=timeout,
                respect_robots=respect_robots,
                verify_ssl=verify_ssl,
            ),
            jobs,
        )
        for result in results:
            _apply_redirect_result(df, result)
            done += 1
            if progress_callback:
                progress_callback(done, total, result.old_url, result.status)
            _pause_if_requested(pause_flag)

    output_path = excel_path.with_stem(excel_path.stem + "_results")
    return _write_redirect_results(df, output_path)
