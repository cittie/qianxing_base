#!/usr/bin/env python3
"""证明一次改动**只动了注释**：把 HEAD 版本与工作区版本各自去掉注释后逐字节比较。

比对方式：
  * `.go` / `.txt` 等：去掉行内 `//`（或 `#`）之后的部分，以及整行注释；
  * 若"去注释后"两份内容完全一致 → 该文件只有注释被改动 ✅

用法：
    python tools/verify_comments_only.py            # 检查所有已改动文件
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 目标仓库由 --repo 指定（默认当前目录）—— 不要把本机路径写死在这里
REPO = Path.cwd()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout


def strip_comments(text: str, marker: str) -> str:
    """按行剥掉注释；保留代码部分（含行尾注释之前的代码）。"""
    kept = []
    for line in text.splitlines():
        idx = line.find(marker)
        if idx >= 0:
            line = line[:idx]
        if line.strip() == "":
            continue
        kept.append(line.rstrip())
    return "\n".join(kept)


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="目标仓库路径（默认当前目录）")
    args = ap.parse_args()

    REPO = Path(args.repo).expanduser().resolve()
    if not (REPO / ".git").exists():
        print(f"{REPO} 不是一个 git 仓库", file=sys.stderr)
        return 2

    changed = [l for l in git("diff", "--name-only").splitlines() if l.strip()]
    if not changed:
        print("没有已改动的文件")
        return 0

    ok, bad = [], []
    for name in changed:
        path = REPO / name
        if not path.is_file():
            continue                      # 被删除的文件不在此列
        marker = "#" if path.suffix in {".txt", ".gitignore"} or name == ".gitignore" else "//"
        old = git("show", f"HEAD:{name}")
        new = path.read_text(encoding="utf-8")
        if strip_comments(old, marker) == strip_comments(new, marker):
            ok.append(name)
        else:
            bad.append(name)

    print(f"改动文件 {len(changed)} 个：")
    for name in ok:
        print(f"  ✅ {name}（去掉注释后与 HEAD 完全一致）")
    for name in bad:
        print(f"  ❌ {name}（**代码本身**也变了，需要人工确认）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
