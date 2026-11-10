import datetime as dt
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from twvix.store import CRASH_COLS, SUMMARY_COLS, upsert, write_data_branch
from helpers import synthetic_quotes

CFG = {
    "risk_free_rate": 0.015, "price_basis": "settle", "settle_min_valid": 1e-6, "min_strikes": 5,
    "holidays": set(), "crash_thresholds": [0.9, 0.8], "gammas": [0, 1, 2, 4],
    "vix_diff_warn": 0.6, "vix_diff_fail": 2.0,
}
D1, D2 = dt.date(2026, 11, 9), dt.date(2026, 11, 10)


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    sh(tmp_path, "git", "clone", str(remote), str(work))
    sh(work, "git", "config", "user.name", "t")
    sh(work, "git", "config", "user.email", "t@t")
    (work / "README.md").write_text("code\n")
    sh(work, "git", "add", ".")
    sh(work, "git", "commit", "-m", "init")
    sh(work, "git", "push", "origin", "HEAD:main")
    return remote, work


def day_df(day, sigma=0.2):
    rows = []
    for e, days in ((dt.date(2026, 11, 18), 9), (dt.date(2026, 12, 16), 37)):
        q = synthetic_quotes(F=100, T=days / 365, sigma=sigma, step=0.5)
        q["expiry"], q["settle"], q["date"], q["code"], q["session"] = e, q["bid"], day, "x", "一般"
        rows.append(q)
    return pd.concat(rows, ignore_index=True)


def fake_frames(date, vix=20.0):
    s = pd.DataFrame([{c: None for c in SUMMARY_COLS} | {"date": date, "vix": vix}])
    c = pd.DataFrame([{"date": date, "horizon": "30d", "threshold": 0.9, "gamma": 0, "prob": 0.1}])
    return s, c


def test_upsert_overwrites_same_date_only():
    a, _ = fake_frames("2026-11-09", 20.0)
    b, _ = fake_frames("2026-11-10", 21.0)
    both = upsert(a, b, SUMMARY_COLS)
    redo, _ = fake_frames("2026-11-09", 25.0)
    out = upsert(both, redo, SUMMARY_COLS)
    assert list(out["date"]) == ["2026-11-09", "2026-11-10"]
    assert out.loc[out.date == "2026-11-09", "vix"].iloc[0] == 25.0


def test_first_write_creates_orphan_branch_and_pushes(repos):
    remote, work = repos
    s, c = fake_frames("2026-11-09")
    assert write_data_branch(work, s, c, {"x": 1}) is True
    files = sh(work, "git", "ls-tree", "-r", "--name-only", "origin/data").split()
    assert sorted(files) == ["crash.csv", "meta.json", "summary.csv"]
    # orphan：與 main 無共同祖先
    assert subprocess.run(["git", "merge-base", "origin/data", "origin/main"], cwd=work).returncode != 0
    # main 沒被碰
    assert sh(work, "git", "ls-tree", "-r", "--name-only", "origin/main").split() == ["README.md"]
    # worktree 已清掉
    assert sh(work, "git", "worktree", "list").strip().count("\n") == 0


def test_rerun_same_day_no_duplicate_and_no_new_commit(repos):
    _, work = repos
    s, c = fake_frames("2026-11-09")
    write_data_branch(work, s, c, {"x": 1})
    assert write_data_branch(work, s, c, {"x": 2}) is False
    csv = sh(work, "git", "show", "origin/data:summary.csv")
    assert csv.count("2026-11-09") == 1
    assert sh(work, "git", "rev-list", "--count", "origin/data").strip() == "1"


def test_history_kept_and_changed_value_overwrites(repos):
    _, work = repos
    write_data_branch(work, *fake_frames("2026-11-09", 20.0), {"x": 1})
    write_data_branch(work, *fake_frames("2026-11-10", 21.0), {"x": 1})
    write_data_branch(work, *fake_frames("2026-11-09", 22.0), {"x": 1})  # 重算前一天
    df = pd.read_csv(pd.io.common.StringIO(sh(work, "git", "show", "origin/data:summary.csv")))
    assert list(df["date"]) == ["2026-11-09", "2026-11-10"]
    assert df.set_index("date").loc["2026-11-09", "vix"] == 22.0
    assert sh(work, "git", "rev-list", "--count", "origin/data").strip() == "3"  # 歷史保留，非 force


def test_fresh_clone_reads_remote_history(repos, tmp_path):
    remote, work = repos
    write_data_branch(work, *fake_frames("2026-11-09"), {"x": 1})
    other = tmp_path / "other"  # 模擬 Actions：只 clone 預設分支
    sh(tmp_path, "git", "clone", str(remote), str(other))
    write_data_branch(other, *fake_frames("2026-11-10"), {"x": 1})
    df = pd.read_csv(pd.io.common.StringIO(sh(other, "git", "show", "origin/data:summary.csv")))
    assert list(df["date"]) == ["2026-11-09", "2026-11-10"]
