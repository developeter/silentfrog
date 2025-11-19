import pathlib
import pandas as pd
import requests_mock

from silentfrog.redirect import check_redirects


def test_check_redirects(tmp_path: pathlib.Path):
    df = pd.DataFrame(
        {0: ["https://old.example.com/page"], 1: ["https://new.example.com/page"]}
    )
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
