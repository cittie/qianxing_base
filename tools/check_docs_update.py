#!/usr/bin/env python3
"""Check whether a local documentation mirror is behind its upstream git repository.

A "mirror" here is just a directory of markdown files crawled from some upstream repo. This tool
asks GitHub for that repo's HEAD and compares it with what the mirror recorded last time, so you
can tell whether refreshing is worth the download.

The upstream repository is **not hardcoded**: give it with `--repo owner/name`, or leave it out
and the tool reads the `repo` field of `<mirror>/upstream-state.json` (which `--record` writes).

Exit codes: 0 = mirror is current, 1 = update available (or no baseline recorded), 2 = unreachable.

两个问题很容易被混为一谈：

    「我的镜像落后于上游了吗？」      ← 本脚本回答这个
    「游戏里的数据是最新的吗？」      ← 单靠文档谁都回答不了；上游只知道它上次爬取时
                                      网站写了什么，而网站本身可能就滞后于实现。
                                      能力类问题必须去真实环境里实测。

它把上游 HEAD 提交与本地登记的提交做比较，告诉你值不值得刷新。
本机直连 api.github.com 可用；万一不通，会解析 PAC（经由 tools/pac_proxy.py）并用 curl 重试。

用法：
    python tools/check_docs_update.py --mirror <镜像根>              # 报告状态
    python tools/check_docs_update.py --mirror <镜像根> --record     # 把当前上游登记为"我们已有的"
    python tools/check_docs_update.py --mirror <镜像根> --json

退出码：0 = 一致，1 = 有更新，2 = 连不上。
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
# 默认按"本脚本所在的基座"推断；从基座运行时请用 --mirror 显式指向游戏侧的镜像目录。
MIRROR = WORKSPACE / "research" / "official-docs"
STATE_FILE = MIRROR / "upstream-state.json"

REPO = ""      # 由 --repo 或镜像的 upstream-state.json 提供，见 main()
API = ""
GIT_URL = ""

# 统计文件数时只看这些子目录（镜像可能按别的方式组织；不存在的会被跳过）
SCOPES = ("guide", "tutorial", "faq", "client")


def load_repo_from_state(mirror: Path) -> str:
    """从镜像的 upstream-state.json 里读上游仓库（`owner/name`）。"""
    try:
        data = json.loads((mirror / "upstream-state.json").read_text(encoding="utf-8"))
    except Exception:      # noqa: BLE001
        return ""
    return str(data.get("repo", ""))


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
    global MIRROR, STATE_FILE, REPO, API, GIT_URL
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", action="store_true", help="把当前上游登记为我们的基线")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供脚本/定时任务读取）")
    ap.add_argument("--mirror", default=str(MIRROR),
                    help="文档镜像根目录（默认按脚本位置推断；从基座调用时应显式指向游戏侧的镜像路径）")
    ap.add_argument("--repo", default="",
                    help="上游仓库 owner/name（缺省时读镜像的 upstream-state.json）")
    args = ap.parse_args()

    MIRROR = Path(args.mirror).expanduser().resolve()
    STATE_FILE = MIRROR / "upstream-state.json"

    REPO = args.repo or load_repo_from_state(MIRROR)
    if not REPO:
        print("缺少上游仓库：请用 --repo owner/name 指定，"
              "或让镜像里存在带 repo 字段的 upstream-state.json", file=sys.stderr)
        return 2
    API = f"https://api.github.com/repos/{REPO}/commits?per_page=1"
    GIT_URL = f"https://github.com/{REPO}.git"

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
    print(f"   python tools/check_docs_update.py --mirror {MIRROR} --record")
    print("   （若该镜像另有索引生成脚本，也一并重跑 —— 索引生成器通常属于平台专属，不在基座里）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
