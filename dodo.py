"""doit 任務定義。`uv run doit list` 看全部；`uv run doit` 跑預設流程；只重跑變動的步驟。

流程：
  fetch_raw:<YYYYMM>      下載該月 TXO 原始檔            → _data/raw/
  fetch_official:<YYYYMM> 下載官方 VIX                    → _data/official/
  compute:<YYYYMM>        逐日計算 + 比對官方 + 自檢     → _output/months/
  combine                 合併各月、算差異統計            → _output/
  test                    pytest
  check_complete          預設流程最後一步：data 分支是否涵蓋所有交易日
  update_latest           第二條線：補上 data 分支漏的日子（含今天），一次 push
  publish_data            （不在預設流程）把本機 _output 整批 upsert 到 data 分支並 push

區間用環境變數覆寫：TWVIX_START、TWVIX_END（預設 config.yaml 的 backfill_start 到台北時間今天）。
例：TWVIX_START=2026-10-01 uv run doit combine
"""
import datetime as dt
import os
from pathlib import Path

import yaml
from doit.tools import config_changed

from twvix.runner import today_taipei
from twvix.steps import months

DOIT_CONFIG = {"default_tasks": ["test", "combine", "check_complete"], "verbosity": 2}

CONFIG = "config.yaml"
_cfg = yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8"))
START = os.environ.get("TWVIX_START") or str(_cfg.get("backfill_start", "2026-08-03"))
END = os.environ.get("TWVIX_END") or today_taipei().isoformat()
MONTHS = months(dt.date.fromisoformat(START), dt.date.fromisoformat(END))

# 計算邏輯的原始碼；任何一個變動，所有月份的 compute 都會重跑（fetch 不會）
CALC_SRC = [f"src/twvix/{n}.py" for n in
            ("calendar", "chain", "vix", "svix", "smile", "crash", "pipeline", "runner", "official", "fetch", "steps", "store")]


def task_test():
    """pytest（程式、測試或設定有變動才重跑）"""
    return {
        # pytest 通過才寫標記檔；失敗則下次會再跑
        "actions": ["uv run pytest -q", "touch .doit_test_ok"],
        "file_dep": CALC_SRC + [str(p) for p in sorted(Path("tests").glob("*.py"))] + [CONFIG],
        "targets": [".doit_test_ok"],
        "clean": True,
    }


def task_fetch_raw():
    """下載每月 TXO 原始檔。最後一個月（可能還在更新）每天重抓一次。"""
    for i, ym in enumerate(MONTHS):
        t = f"_data/raw/txo_{ym}.csv"
        d = {
            "name": ym,
            "actions": [f"uv run python -c \"from twvix.steps import fetch_raw; fetch_raw('{ym}','{START}','{END}','{t}')\""],
            "targets": [t],
            "uptodate": [config_changed(f"{START}|{END}")],  # 區間或結束日改變就重抓
        }
        yield d


def task_fetch_official():
    """下載每月官方 VIX（官方檔每天更新，所以每天重抓一次）。"""
    for ym in MONTHS:
        t = f"_data/official/vix_{ym}.csv"
        yield {
            "name": ym,
            "actions": [f"uv run python -c \"from twvix.steps import fetch_official; fetch_official('{ym}','{t}')\""],
            "targets": [t],
            "uptodate": [config_changed(END)],
        }


def task_compute():
    """每月：逐日計算 VIX/SVIX/崩盤機率，與官方比對並自檢。"""
    for ym in MONTHS:
        raw, off = f"_data/raw/txo_{ym}.csv", f"_data/official/vix_{ym}.csv"
        outs = [f"_output/months/{n}_{ym}.csv" for n in ("summary", "crash", "errors")]
        yield {
            "name": ym,
            "actions": [
                "uv run python -c \"from twvix.steps import compute_month; "
                f"compute_month('{raw}','{off}','{CONFIG}','{outs[0]}','{outs[1]}','{outs[2]}')\""
            ],
            "file_dep": [raw, off, CONFIG] + CALC_SRC,
            "targets": outs,
        }


def task_combine():
    """合併各月結果，輸出 _output/summary.csv、crash.csv、errors.csv、diff_stats.json。"""
    deps = [f"_output/months/{n}_{ym}.csv" for ym in MONTHS for n in ("summary", "crash", "errors")]
    return {
        "actions": ["uv run python -c \"from twvix.steps import combine; combine('_output/months','_output')\""],
        "file_dep": deps,
        "targets": ["_output/summary.csv", "_output/crash.csv", "_output/errors.csv", "_output/diff_stats.json"],
    }


def task_check_complete():
    """第一條線的最後一步：原始資料有的交易日，data 分支是否都有。缺了就失敗並提示跑 update_latest。"""
    return {
        "actions": ["uv run python -c \"from twvix.steps import check_complete; check_complete('_data/raw', '.')\""],
        "file_dep": [f"_data/raw/txo_{ym}.csv" for ym in MONTHS],
        "task_dep": ["combine"],
        "uptodate": [False],  # 看的是遠端 data 分支，每次都要重查
    }


def task_update_latest():
    """第二條線：檢查 data 分支有沒有漏（含今天），有就補上並 push。獨立於上面的流程，不需要先 fetch/compute。
    TWVIX_NO_PUSH=1 只寫本機；TWVIX_FULL=1 從 backfill_start 全部掃描。"""
    flags = (" --no-push" if os.environ.get("TWVIX_NO_PUSH") else "") + (" --full" if os.environ.get("TWVIX_FULL") else "")
    return {"actions": [f"uv run twvix update-latest --config {CONFIG}{flags}"], "uptodate": [False], "verbosity": 2}


def task_publish_data():
    """upsert 到 data 分支。不在預設流程；需要時 `uv run doit publish_data`（加 TWVIX_NO_PUSH=1 則只寫本機）。"""
    push = "False" if os.environ.get("TWVIX_NO_PUSH") else "True"
    return {
        "actions": [
            "uv run python -c \"from twvix.steps import publish; "
            f"publish('_output/summary.csv','_output/crash.csv','{CONFIG}','.',{push})\""
        ],
        "file_dep": ["_output/summary.csv", "_output/crash.csv"],
        "uptodate": [False],  # 永遠視為過期，明確呼叫就執行；內容沒變時 store 不會 commit
    }
