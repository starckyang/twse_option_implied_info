import datetime as dt

import pandas as pd
import pytest

from twvix.runner import update_latest
from twvix.store import read_data_branch
from test_store import CFG, day_df, repos, sh  # noqa: F401

CFG2 = {**CFG, "backfill_start": "2026-11-02"}
D = lambda d: dt.date(2026, 11, d)


def make(days, official=None, bad=()):
    """回傳 (fetch, official) 注入函式。days: 有一般時段資料的交易日；official: {date: vix}；bad: 資料有問題的日子。"""
    frames = {d: day_df(d, sigma=0.2 + 0.01 * (d.day % 5)) for d in days}
    for d in bad:
        frames[d] = frames[d].assign(settle=float("nan"), bid=float("nan"), ask=float("nan"))  # 全無報價 → ValueError

    def fetch(a, b):
        fr = [f for d, f in frames.items() if a <= d <= b]
        return pd.concat(fr, ignore_index=True) if fr else day_df(D(1)).iloc[0:0]

    def off(a, b):
        return {d: v for d, v in (official or {}).items() if a <= d <= b}

    return fetch, off


def dates(work):
    s, _ = read_data_branch(work)
    return list(s["date"])


def test_empty_branch_fills_from_backfill_start(repos):
    _, work = repos
    f, o = make([D(2), D(3), D(4)])
    r = update_latest(CFG2, work, today=D(4), fetch=f, official=o)
    assert r["status"] == "written" and dates(work) == ["2026-11-02", "2026-11-03", "2026-11-04"]


def test_adds_only_today_when_rest_present(repos):
    _, work = repos
    f, o = make([D(2), D(3)])
    update_latest(CFG2, work, today=D(3), fetch=f, official=o)
    f, o = make([D(2), D(3), D(4)])
    r = update_latest(CFG2, work, today=D(4), fetch=f, official=o)
    assert r["written"] == ["2026-11-04"]
    assert sh(work, "git", "rev-list", "--count", "origin/data").strip() == "2"


def test_fills_gap_in_middle_and_today(repos):
    _, work = repos
    f, o = make([D(2), D(4)])  # 11/3 當時漏掉
    update_latest(CFG2, work, today=D(4), fetch=f, official=o)
    assert dates(work) == ["2026-11-02", "2026-11-04"]
    f, o = make([D(2), D(3), D(4), D(5)])
    r = update_latest(CFG2, work, today=D(5), fetch=f, official=o)
    assert sorted(r["written"]) == ["2026-11-03", "2026-11-05"]
    assert dates(work) == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]


def test_weekend_and_holiday_are_not_gaps(repos):
    _, work = repos
    f, o = make([D(2), D(3), D(5), D(6)])  # 11/4 休市、11/7-8 週末：資料裡本來就沒有
    update_latest(CFG2, work, today=D(9), fetch=f, official=o)
    assert update_latest(CFG2, work, today=D(9), fetch=f, official=o)["status"] == "nothing_to_do"
    assert dates(work) == ["2026-11-02", "2026-11-03", "2026-11-05", "2026-11-06"]


def test_fills_official_vix_when_published_later(repos):
    _, work = repos
    f, _ = make([D(2), D(3)])
    update_latest(CFG2, work, today=D(3), fetch=f, official=lambda a, b: {})
    s, _ = read_data_branch(work)
    assert s["quality_flags"].str.contains("official_missing").all()
    # 官方值還沒公布 → 沒東西可補
    assert update_latest(CFG2, work, today=D(3), fetch=f, official=lambda a, b: {})["status"] == "nothing_to_do"
    # 公布了
    f, o = make([D(2), D(3)], official={D(2): 20.0, D(3): 20.1})
    r = update_latest(CFG2, work, today=D(3), fetch=f, official=o)
    assert sorted(r["written"]) == ["2026-11-02", "2026-11-03"]
    s, _ = read_data_branch(work)
    assert not s["quality_flags"].fillna("").str.contains("official_missing").any()
    assert s["vix_taifex_published"].tolist() == [20.0, 20.1]


def test_failed_day_not_written_others_are(repos):
    _, work = repos
    f, o = make([D(2), D(3), D(4)], bad=[D(3)])
    r = update_latest(CFG2, work, today=D(4), fetch=f, official=o)
    assert list(r["failed"]) == ["2026-11-03"]
    assert dates(work) == ["2026-11-02", "2026-11-04"]


def test_tolerance_failure_reported(repos):
    _, work = repos
    f, o = make([D(2)], official={D(2): 35.0})
    r = update_latest(CFG2, work, today=D(2), fetch=f, official=o)
    assert "ToleranceError" in r["failed"]["2026-11-02"] and dates(work) == []


def test_today_not_published_is_not_a_failure(repos):
    _, work = repos
    f, o = make([D(2), D(3)])
    update_latest(CFG2, work, today=D(3), fetch=f, official=o)
    r = update_latest(CFG2, work, today=D(4), fetch=f, official=o)  # 11/4 還沒有一般時段資料
    assert r == {"written": [], "failed": {}, "status": "nothing_to_do"}


def test_rerun_is_unchanged(repos):
    _, work = repos
    f, o = make([D(2), D(3)])
    update_latest(CFG2, work, today=D(3), fetch=f, official=o)
    r = update_latest(CFG2, work, today=D(3), fetch=f, official=o, full=True)  # 全掃描也不會重複寫
    assert r["status"] == "nothing_to_do"
    assert sh(work, "git", "rev-list", "--count", "origin/data").strip() == "1"


def test_self_check_failure_reported_and_not_written(repos):
    _, work = repos
    f, o = make([D(2)])
    r = update_latest({**CFG2, "min_strikes": 10_000}, work, today=D(2), fetch=f, official=o)
    assert "SelfCheckError" in r["failed"]["2026-11-02"] and dates(work) == []
