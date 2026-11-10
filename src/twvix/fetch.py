"""下載與解析 TAIFEX TXO 每日行情。網路與格式細節都隔離在這個檔案。"""
from __future__ import annotations

import datetime as dt
import io
import re

import numpy as np
import pandas as pd

URL = "https://www.taifex.com.tw/cht/3/dlOptDataDown"
EXPECTED_HEADER = "交易日期,契約,到期月份(週別),履約價,買賣權"
MONTHLY_RE = re.compile(r"^\d{6}$")


class FetchError(RuntimeError):
    pass


def download_raw(start: dt.date, end: dt.date, timeout: float = 60) -> str:
    """下載 [start, end] 的 TXO 原始 CSV 文字（區間不可超過一個月）。"""
    import requests

    resp = requests.post(
        URL,
        data={
            "down_type": "1",
            "commodity_id": "TXO",
            "commodity_id2": "",
            "queryStartDate": start.strftime("%Y/%m/%d"),
            "queryEndDate": end.strftime("%Y/%m/%d"),
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    text = resp.content.decode("cp950", errors="replace")
    # 錯誤頁也是 HTTP 200，必須檢查表頭
    if not text.lstrip().startswith(EXPECTED_HEADER):
        raise FetchError(f"unexpected response (not a CSV): {text[:120]!r}")
    return text


def parse_csv(text: str) -> pd.DataFrame:
    """把原始 CSV 轉成乾淨的 long table。

    欄位：date, code, strike, cp('C'/'P'), bid, ask, settle, session, expiry(date)
    價格缺值（'-'）一律變成 NaN。
    """
    df = pd.read_csv(io.StringIO(text), index_col=False, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]
    for c in df.columns:
        df[c] = df[c].str.strip()

    def num(s: pd.Series) -> pd.Series:
        return pd.to_numeric(s.replace("-", np.nan), errors="coerce")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["交易日期"], format="%Y/%m/%d").dt.date,
            "code": df["到期月份(週別)"],
            "strike": pd.to_numeric(df["履約價"]),
            "cp": df["買賣權"].map({"買權": "C", "賣權": "P"}),
            "bid": num(df["最後最佳買價"]),
            "ask": num(df["最後最佳賣價"]),
            "settle": num(df["結算價"]),
            "session": df["交易時段"],
            "expiry": pd.to_datetime(df["契約到期日"], format="%Y%m%d").dt.date,
        }
    )
    return out


def monthly_regular(df: pd.DataFrame) -> pd.DataFrame:
    """只留月選、一般交易時段。"""
    m = df["code"].str.match(MONTHLY_RE) & (df["session"] == "一般")
    return df.loc[m].reset_index(drop=True)


def fetch_day(day: dt.date) -> pd.DataFrame:
    """下載單日並回傳月選一般時段。沒有一般時段資料（假日或尚未公布）時回傳空表。"""
    df = parse_csv(download_raw(day, day))
    return monthly_regular(df)
