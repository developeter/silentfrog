import pathlib

import pandas as pd
import pytest
import requests_mock  # type: ignore[reportMissingImports]
from openpyxl import load_workbook

from silentfrog.redirect import check_redirects  # type: ignore[reportMissingImports]


def test_check_redirects(tmp_path: pathlib.Path):
    df = pd.DataFrame({0: ["https://old.example.com/page"], 1: ["https://new.example.com/page"]})
    in_xlsx = tmp_path / "input.xlsx"
    df.to_excel(in_xlsx, index=False, header=False)

    with requests_mock.Mocker() as m:
        m.get(
            "https://old.example.com/page",
            status_code=301,
            headers={"Location": "https://new.example.com/page"},
        )
        m.get("https://new.example.com/page", status_code=200)

        out = check_redirects(
            excel_path=in_xlsx,
            timeout=5,
            max_workers=2,
            respect_robots=False,
        )

    out_df = pd.read_excel(out)
    assert out_df.loc[0, "Redirect Correct"] == "Yes"
    assert out_df.loc[0, "Status Code"] == 200


def test_check_redirects_callback_and_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    df = pd.DataFrame(
        {
            "Old URL": ["https://old.example.com/a", "https://old.example.com/b"],
            "New URL": ["https://new.example.com/a", "https://new.example.com/b"],
        }
    )
    in_xlsx = tmp_path / "input.xlsx"
    df.to_excel(in_xlsx, index=False)

    calls = []

    def fake_single(sess, old_url, new_url, timeout, respect_robots):
        if old_url.endswith("/a"):
            return 301, new_url, True, 1, f"{old_url}->{new_url}"
        return 404, "", False, 0, ""

    monkeypatch.setattr("silentfrog.redirect._single", fake_single)
    monkeypatch.setattr("silentfrog.redirect._new_session", lambda verify_ssl: object())

    out = check_redirects(
        excel_path=in_xlsx,
        timeout=1,
        max_workers=2,
        respect_robots=False,
        progress_callback=lambda done, total, url, status: calls.append((done, total, url, status)),
    )

    out_df = pd.read_excel(out)
    assert list(out_df["Redirect Correct"]) == ["Yes", "No"]
    assert list(out_df["Status Code"]) == [301, 404]
    assert calls and calls[-1][0] == len(out_df)


def test_check_redirects_styles_404_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    df = pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://new.example.com/a"]})
    in_xlsx = tmp_path / "input.xlsx"
    df.to_excel(in_xlsx, index=False)

    monkeypatch.setattr("silentfrog.redirect._single", lambda *args, **kwargs: (404, "", False, 0, ""))
    monkeypatch.setattr("silentfrog.redirect._new_session", lambda verify_ssl: object())

    out = check_redirects(excel_path=in_xlsx, timeout=1, max_workers=1, respect_robots=False)

    workbook = load_workbook(out)
    try:
        sheet = workbook["Results"]
        assert sheet["E2"].value == "No"
        assert sheet["A2"].fill.start_color.rgb == "FFFFC7CE"
        assert sheet["B2"].fill.start_color.rgb == "FFFFC7CE"
    finally:
        workbook.close()
