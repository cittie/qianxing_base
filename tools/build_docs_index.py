#!/usr/bin/env python3
"""Build local markdown indexes over the official-docs mirror.

Why plain markdown instead of a database or a service: the whole corpus is ~2.2 MB /
~320 files, which `grep`/`read` handle in milliseconds and with zero moving parts. What the
agent actually lacked was not speed but *findability* -- knowing which file and section covers
a topic. These indexes fix that:

    headings.md  every ##/### heading in the corpus, with file and line
    nodes.md     node-level index (one row per node section in the node catalogs)
    topics.md    curated topic groups -> enclosing section + file:line

Every row also carries the source snapshot month (front-matter `crawledAt`), because a
document that looks authoritative may simply be old -- see the 2026-10-04 incident where a
2026-02 snapshot claimed slimes cannot patrol.

Usage:
    python tools/build_docs_index.py [--docs DIR] [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = WORKSPACE / "research" / "official-docs"
SCOPES = ("guide", "tutorial", "faq", "client")

FRESHNESS_WARNING = (
    "> ⚠️ **新鲜度判据 = 上游仓库的最后提交时间**（见 `refresh.ps1` 的输出 / `README.md` §2），"
    "**不是**下表里的 `crawledAt`：\n"
    "> 镜像出自第三方文档仓库 [Miliastra-knowledge](https://github.com/1475505/Miliastra-knowledge) "
    "（最近一次提交 **2026-09-25**）。`crawledAt` 只是该文件首次抓取时间，"
    "很多篇仍是 2026.1 且未随内容更新 —— **拿它当新旧判据会误判**。\n"
    "> 另：**「某能力到底有没有」一律以实测为准**（AGENTS.md §8；2026-10-04 曾被 2026-02 快照坑过一次）。\n"
)

# "## **1\. 设置自定义变量**" -> "设置自定义变量"
NODE_NAME_RE = re.compile(r"^\*{0,2}\s*(?:\d+(?:\.\d+)*)\s*[.\\、]?\s*(.*?)\s*\*{0,2}$")

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$")

# Curated themes: what we actually needed to look up while building the first level, plus the
# questions that are likely to come back. Keywords are matched literally (case-insensitive).
TOPICS: dict[str, list[str]] = {
    "造物推进 / 巡逻 / 寻路": ["未入战行为", "巡逻", "寻路", "路径管理", "关卡路径运动"],
    "造物与单位": ["造物", "单位标签", "基础战斗属性", "属性成长", "受击盒"],
    "战斗与数值": ["攻击力", "防御力", "基础生命值", "伤害系数", "伤害增量", "元素免疫"],
    "节点图挂载与生命周期": ["节点图配置", "实体节点图", "职业节点图", "关联节点图", "本地过滤器"],
    "自定义变量": ["自定义变量", "自定义变量快照", "自定义变量组件"],
    "数据结构（字典 / 结构体 / 列表）": ["字典", "结构体", "列表", "建立字典", "对列表设置值"],
    "事件": ["事件节点", "实体销毁时", "实体移除", "卡牌选择器完成时", "玩家传送完成时", "监听信号"],
    "阵营": ["阵营", "阵营属性", "设置实体阵营", "查询实体阵营", "敌对"],
    "定时器": ["定时器", "全局计时器", "定时器触发时"],
    "结算 / 排行榜": ["结算关卡", "结算状态", "排行榜", "段位", "计分板"],
    "UI / 界面": ["界面控件", "选项卡", "卡牌选择器", "铭牌", "文本气泡", "界面布局"],
    "客户端控件与 lua": ["客户端控件", "客户端脚本", "lua", "光标检测", "网格视窗", "模板引用"],
    "预设点与路径": ["预设点", "路径", "路点", "查询预设点"],
    "元件与创建": ["元件", "创建元件", "创建实体", "元件ID", "元件库"],
    "运动器": ["基础运动器", "投射运动器", "跟随运动器", "运动器"],
    "职业与镜头": ["职业", "职业技能", "镜头", "主镜头"],
    "背包 / 商店 / 道具 / 装备": ["背包", "商店", "道具", "装备"],
    "信号": ["发送信号", "信号管理器", "信号"],
    "限制与性能": ["编辑项范围限制", "上限", "性能", "同屏"],
    "地形与碰撞": ["地形", "碰撞", "可点击层级"],
    "复合节点与封装": ["复合节点", "调用"],
}


def parse_front_matter(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def snapshot_month(meta: dict[str, str]) -> str:
    raw = meta.get("crawledAt", "")
    m = re.match(r"(\d{4})-(\d{2})", raw)
    return f"{m.group(1)}-{m.group(2)}" if m else "?"


class Doc:
    __slots__ = ("path", "rel", "scope", "meta", "lines", "month", "title")

    def __init__(self, path: Path, docs_root: Path) -> None:
        self.path = path
        self.rel = path.relative_to(docs_root).as_posix()
        self.scope = self.rel.split("/", 1)[0]
        self.lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        self.meta = parse_front_matter("\n".join(self.lines[:40]))
        self.month = snapshot_month(self.meta)
        # Title comes from front matter; only fall back to the first H1 in the body. (Reading the
        # first H1 unconditionally is wrong here: for guide docs it is a *section* heading such
        # as "一、通用", which would hide every node catalog from the filter below.)
        self.title = self.meta.get("title", "").strip().strip("*")
        if not self.title or self.title == "undefined":
            for line in self.lines[:60]:
                m = HEADING_RE.match(line)
                if m and len(m.group(1)) == 1:
                    self.title = m.group(2).strip().strip("*")
                    break

    def headings(self) -> list[tuple[int, int, str]]:
        """(line_number, level, text) for every heading."""
        out = []
        for i, line in enumerate(self.lines, start=1):
            m = HEADING_RE.match(line)
            if m:
                out.append((i, len(m.group(1)), m.group(2).strip()))
        return out

    def enclosing_section(self, line_no: int) -> str:
        """The nearest heading at or above line_no, as 'H2 › H3'."""
        chain: list[tuple[int, str]] = []  # stack of (level, text)
        for i, level, text in self.headings():
            if i > line_no:
                break
            while chain and chain[-1][0] >= level:
                chain.pop()
            chain.append((level, text))
        return " › ".join(text for _level, text in chain[-2:])


def load_docs(docs_root: Path) -> list[Doc]:
    docs = []
    for scope in SCOPES:
        scope_dir = docs_root / scope
        if not scope_dir.is_dir():
            continue
        for path in sorted(scope_dir.glob("*.md")):
            docs.append(Doc(path, docs_root))
    return docs


def write_headings(docs: list[Doc], out: Path) -> int:
    rows = 0
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 全库标题索引\n\n")
        fh.write("> 自动生成（`tools/build_docs_index.py`），**请勿手工编辑**。\n")
        fh.write("> 用途：一次 grep 定位到「哪个文件、哪一节」讲这件事。\n")
        fh.write(FRESHNESS_WARNING)
        fh.write("\n")
        fh.write("| 层级 | 标题 | 文件 | 行 | crawledAt |\n| --- | --- | --- | --- | --- |\n")
        for doc in docs:
            for line_no, level, text in doc.headings():
                clean = text.replace("|", "\\|")
                fh.write(f"| H{level} | {clean} | {doc.rel} | {line_no} | {doc.month} |\n")
                rows += 1
    return rows


def write_nodes(docs: list[Doc], out: Path) -> int:
    """Node catalogs = docs with many numbered headings (执行节点 / 事件节点 / 查询节点 …)."""
    catalogs = []
    for doc in docs:
        heads = doc.headings()
        if "节点" not in doc.title or len(heads) < 10:
            continue
        catalogs.append((doc, heads))

    rows = 0
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 节点索引\n\n")
        fh.write("> 自动生成（`tools/build_docs_index.py`），**请勿手工编辑**。\n")
        fh.write("> 来源：官方节点目录类文档（执行节点 / 事件节点 / 查询节点 …）。\n")
        fh.write(FRESHNESS_WARNING)
        fh.write("\n")
        for doc, heads in catalogs:
            fh.write(f"## {doc.title}（{len(heads)} 节，{doc.rel}，crawledAt {doc.month}）\n\n")
            fh.write("| 节点 | 行 |\n| --- | --- |\n")
            for line_no, level, text in heads:
                # level 1 headings in these catalogs are *sections* ("一、通用"), not nodes
                if level < 2:
                    continue
                m = NODE_NAME_RE.match(text.replace("**", ""))
                name = (m.group(1) if m and m.group(1) else text).strip()
                name = name.lstrip(" .\\、*")  # "1\. 名称" leaves a stray ". " behind
                if not name:
                    continue
                fh.write(f"| {name.replace('|', chr(92) + '|')} | {line_no} |\n")
                rows += 1
            fh.write("\n")
    return rows


def write_topics(docs: list[Doc], out: Path, per_keyword: int = 6) -> int:
    rows = 0
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("# 主题索引（不知道该搜什么词时先看这里）\n\n")
        fh.write("> 自动生成（`tools/build_docs_index.py`），**请勿手工编辑**。\n")
        fh.write("> 命中行下面给出「所在章节」与「文件:行」，直接 `read` 那个文件的对应行即可。\n")
        fh.write(FRESHNESS_WARNING)
        fh.write("\n")
        for topic, keywords in TOPICS.items():
            fh.write(f"## {topic}\n\n")
            for kw in keywords:
                hits = []
                for doc in docs:
                    for i, line in enumerate(doc.lines, start=1):
                        if kw.lower() in line.lower():
                            hits.append((doc, i))
                            break  # one hit per document per keyword keeps the index readable
                if not hits:
                    continue
                fh.write(f"**{kw}**\n\n")
                for doc, line_no in hits[:per_keyword]:
                    section = doc.enclosing_section(line_no).replace("|", "\\|") or "（文首）"
                    fh.write(f"- {section} — `{doc.rel}:{line_no}`（crawledAt {doc.month}）\n")
                    rows += 1
                if len(hits) > per_keyword:
                    fh.write(f"- …另有 {len(hits) - per_keyword} 篇命中\n")
                fh.write("\n")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", default=str(DEFAULT_DOCS), help="mirror root (default research/official-docs)")
    ap.add_argument("--check", action="store_true", help="only report what would be written")
    args = ap.parse_args()

    docs_root = Path(args.docs)
    if not docs_root.is_dir():
        print(f"mirror not found: {docs_root}", file=sys.stderr)
        return 2

    docs = load_docs(docs_root)
    if not docs:
        print(f"no documents under {docs_root}", file=sys.stderr)
        return 2

    targets = {
        "headings.md": write_headings,
        "nodes.md": write_nodes,
        "topics.md": write_topics,
    }
    print(f"documents: {len(docs)} ({sum(len(d.lines) for d in docs)} lines)")
    for name, fn in targets.items():
        out = docs_root / name
        if args.check:
            print(f"would write {out}")
            continue
        rows = fn(docs, out)
        print(f"wrote {out}  ({rows} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
