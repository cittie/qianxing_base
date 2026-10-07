#!/usr/bin/env python3
"""检查官方《奇匠创作守则》是否被修订（与本地全文存档比对）。

为什么需要它：守则被官方定位为**最高优先级的补充协议**，且官方保留**随时修订权** ——
2026-01-14、2026-08-12 都改过。手动回官网翻一遍成本高，做成一条命令即可随时复核。

怎么拿到正文：官方页面 `user.mihoyo.com/sdk/ugc-agreement.html#/ugc_proto` 是 **Vue 纯前端壳**
（HTML 只有 ~750 字节，直接抓是空的），正文由页面 bundle 里的接口返回：

    GET https://sdk-static.mihoyo.com/hk4e_cn/combo/granter/api/getUgcProtocol
        ?language=zh-cn&channel_id=1&app_id=4

（`sdkCdn` 基址即 `sdk-static.mihoyo.com`；`biz` 段是 `hk4e_cn`。）

判定方式：把线上正文与本地存档**归一化后按句子/条目比对**（去掉 markdown 标记与空白），
两端都看 —— 线上有存档没有 = **漏了最新条款**；存档有线上没有 = **存档里有过期条款**。

退出码：0 = 与线上一致；1 = 发现更新；2 = 抓取/解析失败。
用法：
    python tools/check_rules_update.py              # 只看结论
    python tools/check_rules_update.py --verbose    # 附差异条目
    python tools/check_rules_update.py --save       # 顺带把线上正文存到 rules/.ugc-protocol-latest.txt
    python tools/check_rules_update.py --json       # 机器可读输出
"""

from __future__ import annotations

import argparse
import difflib
import glob
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 规则存档与状态文件都在**游戏侧工作区**的 rules/ 里 —— 本工具住基座，所以路径必须由参数给出
# （默认取当前目录下的 rules/，见 main() 的 --rules-dir）。
RULES_DIR = Path.cwd() / "rules"
API = ("https://sdk-static.mihoyo.com/hk4e_cn/combo/granter/api/getUgcProtocol"
       "?language=zh-cn&channel_id=1&app_id=4")
STATE = RULES_DIR / ".rules-check.json"
LATEST = RULES_DIR / ".ugc-protocol-latest.txt"
CST = timezone(timedelta(hours=8))


def archive_path() -> Path | None:
    """本地全文存档（文件名带版本日期，取字典序最大者即最新版本）。"""
    found = sorted(glob.glob(str(RULES_DIR / "奇匠创作守则-*.md")))
    return Path(found[-1]) if found else None


def fetch_live() -> tuple[str, dict]:
    """取回线上正文。返回 (正文字符串, 原始 data)。"""
    req = urllib.request.Request(API, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://user.mihoyo.com/sdk/ugc-agreement.html",
    })
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("retcode") != 0:
        raise RuntimeError(f"接口返回 retcode={payload.get('retcode')} message={payload.get('message')!r}")

    def longest_strings(node, out):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                longest_strings(v, out)
        elif isinstance(node, list):
            for v in node:
                longest_strings(v, out)
        return out

    parts = sorted(longest_strings(payload.get("data"), []), key=len, reverse=True)
    if not parts:
        raise RuntimeError("接口返回里没有可用的正文字段")
    return parts[0], payload


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{2,}", "\n", text)


def normalize(text: str) -> str:
    """去掉 markdown 标记、空白与常见标点，便于跨排版比对。"""
    return re.sub(r"[#*`>\s\u3000“”\"'（）()【】·]", "", text)


def units(text: str) -> list[str]:
    """按句子 / 条目切分并归一化（忽略过短片段）。"""
    seen, out = set(), []
    for part in re.split(r"[\n；。]", text):
        n = normalize(part)
        if len(n) >= 10 and not n.isdigit() and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def version_date(text: str) -> str:
    """正文里最靠前的“20XX年X月X日”—— 通常就是本次更新概要的版本日期。"""
    hits = re.findall(r"20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text)
    return re.sub(r"\s+", "", hits[0]) if hits else "未知"


def archive_body(path: Path) -> str:
    """只取存档里的**官方正文**部分 —— 跳过文件开头我们自己加的来源说明块。

    不剥掉它的话，比对会把那些说明算成"存档比线上多出的条款"，淹没真正的差异信号。
    """
    text = path.read_text(encoding="utf-8")
    marker = "## 《奇匠创作守则》"
    return text.split(marker, 1)[-1] if marker in text else text


def changed_spans(archive_text: str, live_text: str, limit: int = 12) -> tuple[list[str], int]:
    """归一化后逐字符比对，返回 (差异片段描述, 差异字符总数)。

    按"行 / 句"比对会有大量假阳性 —— 同一句话在两边的**断行位置不同**就会被算成两条差异。
    归一化把空白全部去掉，再用 difflib 找真实差异片段，判据才稳。
    """
    a, b = normalize(archive_text), normalize(live_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    spans, total = [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        total += max(i2 - i1, j2 - j1)
        if len(spans) < limit:
            old = a[i1:i2][:70] or "（无）"
            new = b[j1:j2][:70] or "（无）"
            kind = {"replace": "改写", "delete": "官方已删", "insert": "官方新增"}[tag]
            spans.append(f"[{kind}] 存档：{old}  →  线上：{new}")
    return spans, total


def archive_version(path: Path) -> str:
    """从存档文件名里取版本（如 奇匠创作守则-2026.8.12.md → 2026年8月12日）。"""
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", path.name)
    return f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日" if m else "未知"


def main() -> int:
    global RULES_DIR, STATE, LATEST
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true", help="打印差异条目")
    ap.add_argument("--save", action="store_true", help="把线上正文存到 <rules-dir>/.ugc-protocol-latest.txt")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供脚本/定时任务读取）")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结论")
    ap.add_argument("--rules-dir", default=str(RULES_DIR),
                    help="游戏侧工作区的 rules/ 目录（放守则存档与检查状态）；默认取当前目录下的 rules/")
    args = ap.parse_args()

    RULES_DIR = Path(args.rules_dir).expanduser().resolve()
    STATE = RULES_DIR / ".rules-check.json"
    LATEST = RULES_DIR / ".ugc-protocol-latest.txt"

    archive = archive_path()
    result: dict = {"api": API, "checked_at": datetime.now(CST).isoformat(timespec="seconds")}

    try:
        live_raw, _payload = fetch_live()
    except Exception as exc:                                   # 网络 / 接口问题
        result.update(verdict="fetch-failed", error=str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=1) if args.json
              else f"❌ 抓取失败：{exc}")
        return 2

    live = strip_html(live_raw)
    result["live_version"] = version_date(live)
    result["live_chars"] = len(live)
    result["live_sha256"] = hashlib.sha256(normalize(live).encode("utf-8")).hexdigest()[:16]

    if archive is None:
        result.update(verdict="no-archive")
        print(json.dumps(result, ensure_ascii=False, indent=1) if args.json
              else "⚠️ 找不到本地存档 rules/奇匠创作守则-*.md")
        return 1
    result["archive"] = archive.name
    result["archive_version"] = archive_version(archive)

    # 判据：版本日期变了 → 一定更新；否则看归一化后的真实差异字符数（阈值挡住排版噪声）
    spans, delta = changed_spans(archive_body(archive), live)
    version_changed = result["live_version"] != result["archive_version"]
    changed = version_changed or delta > 200

    result.update(live_units=len(units(live)), archive_units=len(units(archive_body(archive))),
                  diff_chars=delta, diff_spans=len(spans), version_changed=version_changed)
    result["verdict"] = "update-available" if changed else "up-to-date"
    if args.verbose or changed:
        result["diff_samples"] = spans

    if args.save:
        LATEST.write_text(live, encoding="utf-8", newline="\n")
        result["saved"] = str(LATEST)

    STATE.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    elif args.quiet:
        print(f"{result['verdict']}  (线上 {result['live_version']} / 存档 {result['archive_version']}, 差异 {delta} 字符)")
    else:
        print(f"{'✅ 与线上一致' if not changed else '⚠️ 发现更新'}"
              f"（线上版本 {result['live_version']} ｜ 存档 {result['archive_version']}）")
        print(f"   归一化后差异 {delta} 字符（{len(spans)} 处）｜ 存档：{archive.name}")
        if changed:
            for s in spans[:10]:
                print("      · " + s)
            print("   → 复核后请更新 rules/奇匠创作守则-<新版本日期>.md，并同步 rules/compliance.md 的摘录")
            print("   → 线上正文可用 --save 落到 rules/.ugc-protocol-latest.txt 便于逐条对照")
        print(f"   上次检查已记录到 {STATE}")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
