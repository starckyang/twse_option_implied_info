"""交易日與近月／次月選擇。

換月規則（TAIFEX 官方）：近月到期前剩 2 個交易日（含到期日）起，改用次月與次次月。
回補歷史時，交易日可由資料本身判定；未來日期靠設定檔的休市日清單。
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable

ROLL_TRADING_DAYS = 2


def is_trading_day(d: dt.date, holidays: set[dt.date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def trading_days_after(d: dt.date, end: dt.date, holidays: set[dt.date]) -> int:
    """(d, end] 內的交易日數。"""
    n, cur = 0, d
    while cur < end:
        cur += dt.timedelta(days=1)
        if is_trading_day(cur, holidays):
            n += 1
    return n


def select_expiries(
    trade_date: dt.date, expiries: Iterable[dt.date], holidays: set[dt.date] | None = None
) -> tuple[dt.date, dt.date]:
    """回傳 (近月到期日, 次月到期日)。expiries 為當日可用的月選到期日。"""
    holidays = holidays or set()
    alive = sorted(e for e in set(expiries) if e >= trade_date)
    if len(alive) < 2:
        raise ValueError("need at least 2 live monthly expiries")
    if trading_days_after(trade_date, alive[0], holidays) <= ROLL_TRADING_DAYS:
        if len(alive) < 3:
            raise ValueError("need 3 live monthly expiries around roll")
        return alive[1], alive[2]
    return alive[0], alive[1]
