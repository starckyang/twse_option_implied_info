import json
import subprocess

import numpy as np
import pandas as pd

from twvix.report import build_payload, build_site
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


def test_site_files_links_and_embedded_data():
    s, c, meta = frames()
    files = build_site(s, c, meta)
    pages = ["index", "vix", "svix", "bound", "crash", "methodology"]
    assert set(files) == {f"{p}.html" for p in pages} | {"assets/data.js", "assets/style.css", "assets/common.js"}
    for p in pages:
        h = files[f"{p}.html"]
        assert all(x not in h for x in ("__NAV__", "__FOOTER__", "__GAMMA__", "__BOUND__"))
        assert 'aria-current="page"' in h and "非投資建議" in h
        for q in pages:
            assert f'href="{q}.html"' in h  # 每頁都有完整導覽
    assert "γ 是什麼" in files["index.html"] and "γ 是什麼" in files["crash.html"]
    assert "bound.html" in files["index.html"] and "NCC" in files["bound.html"] and "NCC" in files["methodology.html"]
    assert "crash.html?th=0.8" in files["index.html"] and "svix.html#spread" in files["index.html"]
    js = files["assets/data.js"]
    assert js.startswith("window.TW = ") and "NaN" not in js
    data = json.loads(js[len("window.TW = "):].rstrip().rstrip(";").replace("<\\/", "</"))
    assert data["summary"][1]["quality_flags"].endswith("</script>")  # 資料中的 </script> 已跳脫，不會截斷頁面
    assert "</script>" not in js
    blob = "".join(files.values())
    assert "localStorage" not in blob and "sessionStorage" not in blob


def test_publish_pages_orphan_single_commit_force_and_skip_unchanged(repos):
    _, work = repos
    v1 = {"index.html": "<html>v1</html>", "assets/a.js": "1"}
    assert publish_pages(work, v1) is True
    assert sorted(sh(work, "git", "ls-tree", "-r", "--name-only", "origin/gh-pages").split()) == [".nojekyll", "assets/a.js", "index.html"]
    assert publish_pages(work, v1) is False  # 相同內容不推
    assert publish_pages(work, {**v1, "index.html": "<html>v2</html>"}) is True  # force push 取代，不留歷史
    assert sh(work, "git", "rev-list", "--count", "origin/gh-pages").strip() == "1"
    assert sh(work, "git", "show", "origin/gh-pages:index.html") == "<html>v2</html>"
    assert subprocess.run(["git", "merge-base", "origin/gh-pages", "origin/main"], cwd=work).returncode != 0
    assert sh(work, "git", "branch", "--list", "twvix-pages-tmp").strip() == ""
    assert sh(work, "git", "worktree", "list").strip().count("\n") == 0


def test_premium_bound_formula():
    from twvix.report import premium_bound

    ann, d30 = premium_bound(41.68, 0.015)
    assert ann == np.float64(0.4168**2)
    assert abs(d30 - np.exp(0.015 * 30 / 365) * 0.4168**2 * 30 / 365) < 1e-15
    assert 0.0142 < d30 < 0.0144  # 約 1.43%
    assert premium_bound(None, 0.015) == (None, None) and premium_bound(float("nan"), 0.015) == (None, None)
    # SVIX 越高，下界越高；rate=0 時不含折現項
    assert premium_bound(20, 0.0)[1] == (0.2**2) * 30 / 365


def test_payload_has_bound_fields():
    s, c, meta = frames()
    p = build_payload(s, c, meta)
    assert abs(p["summary"][0]["lb_ann"] - 0.448**2) < 1e-12 and 0 < p["summary"][0]["lb_30d"] < p["summary"][0]["lb_ann"]
