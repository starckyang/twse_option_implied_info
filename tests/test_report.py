import json
import re
import subprocess

import numpy as np
import pandas as pd

from twvix.report import build_html, build_payload
from twvix.store import publish_pages
from test_store import repos, sh  # noqa: F401


def frames():
    s = pd.DataFrame([
        {"date": "2026-11-06", "vix": 46.4, "svix": 44.8, "vix_taifex_published": 46.52, "vix_diff": -0.1,
         "near_expiry": "2026-11-18", "next_expiry": "2026-12-16", "quality_flags": np.nan},
        {"date": "2026-11-09", "vix": 43.8, "svix": 41.7, "vix_taifex_published": np.nan, "vix_diff": np.nan,
         "near_expiry": "2026-11-18", "next_expiry": "2026-12-16", "quality_flags": "official_missing;x</script>"},
    ])
    c = pd.DataFrame([
        {"date": d, "horizon": h, "threshold": th, "gamma": g, "prob": 0.1 / (1 + g)}
        for d in s["date"] for h in ("30d", "near") for th in (0.9, 0.8) for g in (0, 1, 2, 4)
    ])
    return s, c, {"method_version": "1", "last_updated": "t", "params": {"risk_free_rate": 0.015}}


def test_payload_shape_and_nan_to_null():
    s, c, meta = frames()
    p = build_payload(s, c, meta)
    assert p["summary"][1]["vix_taifex_published"] is None and p["summary"][0]["quality_flags"] == ""
    assert set(p["crash"]["2026-11-09"]) == {"0.9", "0.8"} and set(p["crash"]["2026-11-09"]["0.9"]) == {"0", "1", "2", "4"}


def test_html_embeds_valid_json_and_cannot_break_script_tag():
    s, c, meta = frames()
    html = build_html(s, c, meta)
    m = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["summary"][1]["quality_flags"].endswith("</script>")
    assert "NaN" not in m.group(1) and "__PAYLOAD__" not in html
    assert "非投資建議" in html and "localStorage" not in html and "sessionStorage" not in html


def test_publish_pages_orphan_single_commit_force_and_skip_unchanged(repos):
    _, work = repos
    assert publish_pages(work, "<html>v1</html>") is True
    assert sorted(sh(work, "git", "ls-tree", "-r", "--name-only", "origin/gh-pages").split()) == [".nojekyll", "index.html"]
    assert publish_pages(work, "<html>v1</html>") is False  # 相同內容不推
    assert publish_pages(work, "<html>v2</html>") is True  # force push 取代，不留歷史
    assert sh(work, "git", "rev-list", "--count", "origin/gh-pages").strip() == "1"
    assert sh(work, "git", "show", "origin/gh-pages:index.html") == "<html>v2</html>"
    assert subprocess.run(["git", "merge-base", "origin/gh-pages", "origin/main"], cwd=work).returncode != 0
    assert sh(work, "git", "branch", "--list", "twvix-pages-tmp").strip() == ""
    assert sh(work, "git", "worktree", "list").strip().count("\n") == 0
