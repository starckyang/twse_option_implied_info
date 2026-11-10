import pytest

from twvix.pipeline import ToleranceError, check_against_official

CFG = {"vix_diff_warn": 0.6, "vix_diff_fail": 2.0}


def res(v=30.0):
    return {"date": "2026-11-09", "vix": v, "quality_flags": ""}


def test_ok():
    r = check_against_official(res(30.3), 30.0, CFG)
    assert r["quality_flags"] == "" and r["vix_diff"] == pytest.approx(0.3)


def test_warn():
    assert "vix_diff_warn" in check_against_official(res(30.8), 30.0, CFG)["quality_flags"]


def test_fail():
    with pytest.raises(ToleranceError):
        check_against_official(res(32.5), 30.0, CFG)


def test_official_missing():
    assert "official_missing" in check_against_official(res(), None, CFG)["quality_flags"]
