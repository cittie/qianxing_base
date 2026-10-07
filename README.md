# Foundation — reusable base for building and shipping a level / small game

**English** ｜ [中文](README.zh-CN.md)

> 🤖 **AI assistants: read [`AGENTS.md`](AGENTS.md) first.** It carries the working conventions
> (language, layering, compliance posture, single-implementation rule) that this repository expects.

## What this is

A **reusable foundation** for the work that stays the same no matter which engine, platform or
topic a game uses:

| layer | contents |
| --- | --- |
| **generic design layer** (`design/`) | `balance-model.md` (the single source for numbers), `architecture.md` (platform-agnostic architecture), `map-template.md` (level design template) |
| **reusable tools** (`tools/`) | index a local docs mirror, check whether that mirror is behind its upstream, resolve a PAC file for git/curl, prove that a commit only touched comments |
| **working conventions** (`AGENTS.md`) | compliance posture, "measure, don't trust the doc", single-implementation, recording norms, AI boundaries |

A concrete game lives in **its own directory / repository** and calls these tools with **explicit
paths** (`--docs`, `--mirror`). Nothing game-specific, no third-party content, and no personal
information belongs here.

## Design layer rules

- Everything under `design/` must be **platform-agnostic**: no engine names, no platform APIs.
- Numbers and structure change here; platform implementation changes in the game repository.
  Never keep two copies of the same decision.
- `architecture.md` keeps the abstractions that survive a platform swap — for example a single
  command-stream interface so a single-player AI, a human player and a networked opponent share
  one architecture.

## Tools

| script | what it does | usage | exit code |
| --- | --- | --- | --- |
| `tools/build_docs_index.py` | builds node / heading / topic indexes over a local docs mirror | `--docs <mirror root>` | 0 |
| `tools/check_docs_update.py` | asks whether the mirror is behind its upstream repo | `--mirror <mirror root>`, `--record`, `--json` | 0 = current, 1 = update or no baseline, 2 = unreachable |
| `tools/pac_proxy.py` | decodes a PAC file (this machine serves it as decimal bytes) so git/curl can use it | `--git-config` | 0 |
| `tools/verify_comments_only.py` | proves a commit changed **only comments** (strips comments, compares byte-for-byte) | run inside the target repo | 1 = code changed too |

All of them are read-only apart from `--record`, which stores a baseline.

## Conventions worth knowing before you use this

- **Comments, docs and commit messages are written in Chinese** (the audience is the author and
  AI assistants); the two READMEs are the only bilingual artefact and must change together.
- **Single implementation**: once a capability lands in a real tool, the exploratory script is
  deleted. Two copies drift, and a forgotten copy is hard to notice.
- **Compliance first**: analysis of exported files is fine, but never ship a tool that writes back
  into game data, and never publish third-party content (official docs, official rules, other
  creators' assets) — keep those local and publish only conclusions you derived yourself.
