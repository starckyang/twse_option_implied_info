import datetime as dt
from pathlib import Path

from twvix.fetch import monthly_regular, parse_csv

SAMPLE = Path(__file__).parent.parent / "samples" / "txo_20261109_head.csv"


def test_parse_sample():
    df = parse_csv(SAMPLE.read_text(encoding="utf-8"))
    assert len(df) == 12
    assert set(df["cp"]) <= {"C", "P"}
    assert df["code"].iloc[0] == "202611"  # 已 strip
    assert df["expiry"].iloc[0] == dt.date(2026, 11, 18)
    assert df["bid"].isna().iloc[0]  # '-' -> NaN
    p = df[(df["cp"] == "P") & (df["strike"] == 33700)].iloc[0]
    assert (p["bid"], p["ask"]) == (50, 56)


def test_monthly_regular_filters():
    df = parse_csv(SAMPLE.read_text(encoding="utf-8"))
    assert len(monthly_regular(df)) == len(df)
