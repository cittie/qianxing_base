# Foundation — reusable base for building and shipping a level / small game

**English** ｜ [中文](README.zh-CN.md)

> 🤖 **AI assistants: read [`AGENTS.md`](AGENTS.md) first.** It carries the working conventions
> (language, layering, compliance posture, single-implementation rule) that this repository expects.

## What this is

A **foundation** for the parts of "build a level / small game and ship it" that are worth keeping:

| layer | contents | on a platform swap |
| --- | --- | --- |
| **abstraction** (`design/`) | `balance-model.md` (the single source for numbers), `architecture.md` (layered architecture), `map-template.md` | **unchanged** |
| **platform adapters** (`platforms/<name>/`) | one folder per target platform: capabilities, **hard limits**, event model, compliance constraints, and that platform's own tools | **this is what changes** |
| **shared tools** (`tools/`) | is a docs mirror behind upstream, resolve a PAC file for git/curl, prove a commit only touched comments | unchanged |
| **conventions** (`AGENTS.md`) | compliance posture, measure-don't-trust-the-doc, single implementation, recording norms, AI boundaries | unchanged |

**Platform-specific tools belong here** — each one lives under its own platform folder, so they
cannot contaminate each other, while the **data and conclusions stay in the game workspace**
(paths are passed in). Adapted so far: **Miliastra Wonderland**; Steam / iOS / Android each have a
checklist waiting to be filled.

A concrete game lives in **its own directory / repository** and calls these tools with **explicit
paths** (`--docs`, `--mirror`, `--rules-dir`). No game content, no third-party content, and no personal
information belongs here.

## Design layer rules

- Everything under `design/` must be **platform-agnostic**: no engine names, no platform APIs.
  Keep the *abstractions* free of platform assumptions; one concrete platform may appear as a
  **worked example**, clearly marked as such — remove that example and the document must still
  stand on its own.
- Numbers and structure change here; platform implementation changes in the game repository.
  Never keep two copies of the same decision.
- `architecture.md` keeps the abstractions that survive a platform swap — for example a single
  command-stream interface so a single-player AI, a human player and a networked opponent share
  one architecture.

**Paths this repo does not contain.** The design documents cite files such as `rules/compliance.md`,
`design/<a specific level>.md` or `research/<platform>.md`. Those live in the **paired game
workspace**, which is not published here — treat them as context for *why* an abstraction looks the
way it does, not as links you should be able to open.

## Tools

| script | what it does | usage | exit code |
| --- | --- | --- | --- |
| `tools/check_docs_update.py` | asks whether a local docs mirror is behind its upstream repository (the upstream is given by flag or read from the mirror's own state file) | `--mirror <mirror root>`, `--repo owner/name`, `--record`, `--json` | 0 = current, 1 = update or no baseline, 2 = unreachable |
| `tools/pac_proxy.py` | decodes a PAC file (this machine serves it as decimal bytes) so git/curl can use it | `--git-config` | 0 |
| `tools/verify_comments_only.py` | proves a commit changed **only comments** (strips comments, compares byte-for-byte) | `--repo <target repo>` (default: cwd) | 1 = code changed too |

All of them are read-only apart from `--record`, which stores a baseline.

### Platform tools (`platforms/<name>/tools/`)

| script | what it does | usage |
| --- | --- | --- |
| `platforms/miliastra/tools/check_rules_update.py` | compares that platform's **live rule text** against the local archive, so you notice when it is amended | `--rules-dir <game workspace>/rules`; `--verbose` / `--save` / `--json` / `--quiet` |
| `platforms/miliastra/tools/build_docs_index.py` | builds node / heading / topic indexes over that platform's offline docs mirror | `--docs <game workspace>/research/official-docs`; `--check` |

Platform tools ship **no data**: paths are arguments and state is written on the game side.

## Conventions worth knowing before you use this

- **Comments, docs and commit messages are written in Chinese** (the audience is the author and
  AI assistants); the two READMEs are the only bilingual artefact and must change together.
- **Single implementation**: once a capability lands in a real tool, the exploratory script is
  deleted. Two copies drift, and a forgotten copy is hard to notice.
- **Compliance first**: analysis of exported files is fine, but never ship a tool that writes back
  into game data, and never publish third-party content (official docs, official rules, other
  creators' assets) — keep those local and publish only conclusions you derived yourself.
