"""data 分支的讀寫：git show 讀歷史、git worktree 寫入、以日期為 key 做 upsert。

data 分支是 orphan branch，只放純文字結果；歷史保留，一般 push（不 force）。
"""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

METHOD_VERSION = "1"
SUMMARY_COLS = [
    "date", "vix", "svix", "vix_taifex_published", "vix_diff", "near_expiry", "next_expiry",
    "T_near", "T_next", "F_near", "F_next", "K0_near", "K0_next", "n_strikes_near", "n_strikes_next",
    "rate_used", "price_basis", "method_version", "quality_flags",
]
CRASH_COLS = ["date", "horizon", "threshold", "gamma", "prob"]


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def branch_exists(repo: Path, ref: str) -> bool:
    return git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def read_csv_at(repo: Path, ref: str, name: str, cols: list[str]) -> pd.DataFrame:
    """讀取某個 ref 上的 CSV；ref 或檔案不存在則回傳空表。"""
    r = git(repo, "show", f"{ref}:{name}", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return pd.DataFrame(columns=cols)
    return pd.read_csv(io.StringIO(r.stdout), dtype={"date": str})


def upsert(old: pd.DataFrame, new: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """以 date 為 key：新資料中出現的日期，整天覆蓋舊資料。"""
    keep = old[~old["date"].isin(set(new["date"]))] if len(old) else old
    out = pd.concat([keep, new], ignore_index=True) if len(keep) else new.copy()
    sort_cols = [c for c in ("date", "horizon", "threshold", "gamma") if c in out.columns]
    return out.sort_values(sort_cols, kind="stable").reset_index(drop=True)[cols]


def build_meta(cfg: dict, now_iso: str, last_date: str) -> dict:
    return {
        "method_version": METHOD_VERSION,
        "last_updated": now_iso,
        "last_trade_date": last_date,
        "params": {
            "risk_free_rate": cfg["risk_free_rate"],
            "price_basis": cfg.get("price_basis"),
            "settle_min_valid": cfg.get("settle_min_valid"),
            "min_strikes": cfg.get("min_strikes"),
            "crash_thresholds": cfg.get("crash_thresholds"),
            "gammas": cfg.get("gammas"),
            "vix_diff_warn": cfg.get("vix_diff_warn"),
            "vix_diff_fail": cfg.get("vix_diff_fail"),
        },
        "notes": [
            "SVIX 為遠期價正規化版本；與 Martin 以現貨正規化的版本在有股利時略有差異。",
            "崩盤門檻為相對遠期價的 moneyness（K/F）；真實機率版本取決於冪次效用假設，γ 為使用者參數。",
            "price_basis=settle 時使用 TAIFEX 每日結算價；利率為固定常數而非 TAIBOR。",
        ],
    }


def write_data_branch(
    repo: Path,
    summary: pd.DataFrame,
    crash: pd.DataFrame,
    meta: dict,
    *,
    branch: str = "data",
    remote: str = "origin",
    push: bool = True,
    message: str | None = None,
) -> bool:
    """把結果 upsert 到 data 分支並（可選）push。回傳是否有產生新 commit。"""
    repo = Path(repo)
    remote_ref = f"{remote}/{branch}"
    has_remote = git(repo, "remote", "get-url", remote, check=False).returncode == 0
    if has_remote:
        git(repo, "fetch", remote, branch, check=False)  # 遠端還沒有 data 分支時會失敗，忽略
    base = remote_ref if branch_exists(repo, remote_ref) else (branch if branch_exists(repo, branch) else None)

    old_s = read_csv_at(repo, base, "summary.csv", SUMMARY_COLS) if base else pd.DataFrame(columns=SUMMARY_COLS)
    old_c = read_csv_at(repo, base, "crash.csv", CRASH_COLS) if base else pd.DataFrame(columns=CRASH_COLS)
    out_s = upsert(old_s, summary[SUMMARY_COLS], SUMMARY_COLS)
    out_c = upsert(old_c, crash[CRASH_COLS], CRASH_COLS)

    tmp = Path(tempfile.mkdtemp(prefix="twvix_data_"))
    wt = tmp / "wt"
    try:
        if base:
            git(repo, "worktree", "add", "-B", branch, str(wt), base)
        else:
            git(repo, "worktree", "add", "--detach", str(wt))
            git(wt, "checkout", "--orphan", branch)
            git(wt, "rm", "-rf", "--quiet", ".", check=False)
        out_s.to_csv(wt / "summary.csv", index=False)
        out_c.to_csv(wt / "crash.csv", index=False)
        # last_updated 每次都變；只有資料真的有差異才 commit，避免同一天重跑產生空洞 commit
        (wt / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        git(wt, "add", "-A")
        changed_data = git(wt, "diff", "--cached", "--quiet", "--", "summary.csv", "crash.csv", check=False).returncode != 0
        has_head = git(wt, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
        if has_head and not changed_data:
            return False  # 資料沒變，不 commit（meta 的 last_updated 不單獨造成 commit）
        dates = ",".join(sorted(set(summary["date"])))
        git(wt, "-c", "user.name=twvix-bot", "-c", "user.email=twvix-bot@users.noreply.github.com",
            "commit", "-q", "-m", message or f"data: {dates}")
        if push and has_remote:
            git(wt, "push", remote, f"HEAD:refs/heads/{branch}")
        return True
    finally:
        git(repo, "worktree", "remove", "--force", str(wt), check=False)
        git(repo, "worktree", "prune", check=False)
