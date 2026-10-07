#!/usr/bin/env python3
"""Check whether the official-docs mirror is behind its upstream repository.

The mirror is a snapshot of the third-party repo `1475505/Miliastra-knowledge`, which crawls
the official site. Two different questions get confused easily:

    "is my mirror behind upstream?"      <- this script answers this
    "is the data current in the game?"   <- nobody can answer this from documents alone;
                                            upstream only knows what the site said the last
                                            time it crawled, and the site itself can lag the
                                            implementation. Ability questions need in-editor tests.

It compares the upstream HEAD commit against a locally recorded one and tells you whether to
refresh. Direct HTTPS to api.github.com works on this machine; if it ever does not, the PAC is
evaluated (via tools/pac_proxy.py) and the request is retried through that proxy with curl.

Usage:
    python tools/check_docs_update.py            # report status
    python tools/check_docs_update.py --record   # record current upstream as "what we have"
    python tools/check_docs_update.py --json

Exit codes: 0 up to date, 1 update available, 2 could not check.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
WORKSPACE = TOOLS.parent
MIRROR = WORKSPACE / "research" / "official-docs"
STATE_FILE = MIRROR / "upstream-state.json"

REPO = "1475505/Miliastra-knowledge"
API = f"https://api.github.com/repos/{REPO}/commits?per_page=1"
GIT_URL = f"https://github.com/{REPO}.git"

SCOPES = ("guide", "tutorial", "faq", "client")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_file_count() -> int:
    total = 0
    for scope in SCOPES:
        d = MIRROR / scope
        if d.is_dir():
            total += len(list(d.glob("*.md")))
    return total


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_proxy(host: str) -> str | None:
    """Ask the PAC what to use for this host; returns e.g. 'socks5h://127.0.0.1:10808'."""
    try:
        sys.path.insert(0, str(TOOLS))
        import pac_proxy  # noqa: PLC0415 - optional, only needed when direct access fails

        url = pac_proxy.pac_url_from_registry()
        if not url:
            return None
        resolved = pac_proxy.Pac(pac_proxy.fetch(url)).resolve(host)
    except Exception:  # noqa: BLE001 - proxy resolution is best effort
        return None
    if not resolved or resolved.upper().startswith("DIRECT"):
        return None
    scheme, _, addr = resolved.partition(" ")
    addr = addr.strip()
    if scheme.upper().startswith("SOCKS5"):
        return f"socks5h://{addr}"
    if scheme.upper() == "PROXY":
        return f"http://{addr}"
    return None


def fetch_api_direct() -> list | None:
    req = urllib.request.Request(API, headers={"User-Agent": "gil-inspect-docs-check"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def fetch_api_via_curl(proxy: str) -> list | None:
    """curl is present on Windows 10+ and speaks both http and socks proxies."""
    flag = "--socks5-hostname" if proxy.startswith("socks5h://") else "--proxy"
    target = proxy.split("://", 1)[1]
    cmd = ["curl", "-s", "--max-time", "20", flag, target, API]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return None


def fetch_sha_via_git() -> str | None:
    """Last-resort fallback: git already knows how to reach github (SSH rewrite / proxy)."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", GIT_URL, "HEAD"],
            capture_output=True, text=True, timeout=45, check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        return out.stdout.split()[0]
    except Exception:  # noqa: BLE001
        return None


def upstream_state() -> tuple[dict | None, str]:
    """Returns (state, how) where how describes which transport worked."""
    data = fetch_api_direct()
    if data:
        return _from_api(data), "direct https"
    proxy = resolve_proxy("api.github.com")
    if proxy:
        data = fetch_api_via_curl(proxy)
        if data:
            return _from_api(data), f"via PAC proxy {proxy}"
    sha = fetch_sha_via_git()
    if sha:
        return {"sha": sha, "date": "", "message": ""}, "git ls-remote (sha only)"
    return None, "unreachable"


def _from_api(data: list) -> dict:
    top = data[0]
    commit = top.get("commit", {})
    return {
        "sha": top.get("sha", ""),
        "date": commit.get("author", {}).get("date", ""),
        "message": (commit.get("message", "") or "").splitlines()[0],
    }


def main() -> int:
    global MIRROR, STATE_FILE
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="store the current upstream as our baseline")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--mirror", default=str(MIRROR),
                    help="文档镜像根目录（默认按脚本位置推断；从基座运行时应显式指定游戏侧的镜像路径）")
    args = ap.parse_args()

    MIRROR = Path(args.mirror).expanduser().resolve()
    STATE_FILE = MIRROR / "upstream-state.json"

    upstream, how = upstream_state()
    if upstream is None:
        print("could not reach the upstream repository (direct, PAC proxy and git all failed)", file=sys.stderr)
        return 2

    state = load_state()
    local = local_file_count()
    verdict = "unknown"

    if args.record:
        state = {
            "repo": REPO,
            "sha": upstream["sha"],
            "date": upstream["date"],
            "message": upstream["message"],
            "recordedAt": utc_now(),
            "localFiles": local,
        }
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"recorded upstream {upstream['sha'][:7]} ({upstream['date']}) against {local} local files")
        print(f"state file: {STATE_FILE}")
        return 0

    if not state.get("sha"):
        verdict = "no-baseline"
    elif state["sha"] == upstream["sha"]:
        verdict = "up-to-date"
    else:
        verdict = "update-available"

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "transport": how,
            "upstream": upstream,
            "recorded": state,
            "localFiles": local,
        }, ensure_ascii=False, indent=2))
        return {"up-to-date": 0, "update-available": 1, "no-baseline": 1}[verdict]

    print(f"mirror      : {MIRROR}  ({local} markdown files)")
    print(f"upstream    : {upstream['sha'][:7]}  {upstream['date']}")
    if upstream["message"]:
        print(f"              {upstream['message']}")
    print(f"transport   : {how}")
    if state.get("sha"):
        print(f"recorded    : {state['sha'][:7]}  {state.get('date','')}  (checked in {state.get('recordedAt','?')})")
    else:
        print("recorded    : <no baseline yet>")

    if verdict == "up-to-date":
        print("\n=> up to date. Nothing to refresh.")
        print("   (remember: upstream itself only knows what the site said at its last crawl,")
        print("    and the site can lag the implementation -- ability questions need in-editor tests)")
        return 0
    if verdict == "no-baseline":
        print("\n=> no local baseline recorded. If your mirror matches the upstream above, run:")
        print(f"   python tools/check_docs_update.py --mirror {MIRROR} --record")
        return 1

    print("\n=> an update is available. Refresh with:")
    print(f"   powershell -NoProfile -ExecutionPolicy Bypass -File {MIRROR}\\refresh.ps1")
    print(f"   python tools/build_docs_index.py --docs {MIRROR}")
    print(f"   python tools/check_docs_update.py --mirror {MIRROR} --record")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
