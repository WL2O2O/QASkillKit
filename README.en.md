<p align="center">
  <img src="docs/assets/hero-en.png" alt="QASkillKit — the QA workflow AI skill toolkit" width="100%">
</p>

# QASkillKit — QA All-in-One Agent Skill Kit

<p align="center">
  🌐 <a href="README.md">中文</a> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="https://github.com/WL2O2O/QASkillKit/actions/workflows/evals.yml"><img src="https://github.com/WL2O2O/QASkillKit/actions/workflows/evals.yml/badge.svg" alt="evals CI"></a>
</p>

> **QA All-in-One AI Skill Kit: from prototype images to traceable test cases** — multi-channel OCR reads requirement diagrams → auto-generates cases (linked to change points) → case-vs-prototype consistency review → UI automation with results logged back → standardized defect & acceptance reports.
>
> **Real-data driven, zero AI hallucination** · **Pure Skill-driven, zero framework code** — all capabilities are Markdown skill docs (SKILL.md) with minimal utility scripts. Readable, editable, improvable.

---

## ✨ What It Does

| Area | Skill | Alias / Shortcut | How to Invoke | Description |
|:---|:---|:---|:---|:---|
| 📝 Test Case Design | `testcase-generator` | — | Input a TAPD requirement ID (e.g. `1019311`) | Fetches requirements from TAPD, queries real test data from DB, supplements business context from knowledge base, and OCRs prototype images to generate structured test cases. |
| 🔍 Case Review | `testcase-reviewer` | — | `review 1019311` | Compares test cases against prototype images line by line; directly fixes confirmed mismatches, outputs a pending-confirmation report for ambiguous items. |
| 🖥️ UI Automation | `ui-automation` | — | `test 1019311` | Drives browser via browser-use MCP to execute Web-based test cases; groups and merges related cases, logs results back into case files. |
| 🐞 Defect Reports | `defect-logger` | — | Describe the bug | Writes standardized defect documents following the team's defect template (title, preconditions, steps, actual/expected results). |
| 📊 Acceptance Reports | `acceptance-report` | `/ys` | `generate s92 acceptance report` | Requirement/defect statistics, delayed-delivery lists, developer defect distribution; scripts connect directly to TAPD OpenAPI. |
| 📅 Weekly Reports | `weekly-report` | `/zb` | `write weekly report` | Pulls requirement/defect updates from TAPD for the current week, generates a structured weekly report. |
| 🖼️ OCR | `ocr` | — | Called by other skills automatically | Three-channel cross-validated OCR: Windows OCR (coverage) + OpenOCR (precision) + VLM (structure). |
| ⚙️ Setup Wizard | `setup` | `/setup` | `/setup` on first use | Auto-detects TAPD project, DB connections, knowledge bases; generates private config. |
| 🧪 Agent Evaluation | `evals/` module | — | `python3 evals/evaluate.py` | YAML eval set + rule assertions / LLM-as-Judge dual channel; runs with zero keys, no TAPD needed, negative-control self-test; the evaluator itself is covered by pytest self-tests. |
| 🧪 Case Evaluation | `testcase-evaluator` | `/eval` | `evaluate this case file` / `run evals` | Conversational entry to the evals module: picks registered eval / repo-wide scan / --live, explains violations in plain language; badcase root causes and calibration stay human-confirmed. |

## 🚀 Quick Start

Pick a track: **just trying it out → Track A** (30 seconds, Python only); **your team uses TAPD and wants the full workflow → Track B**.

### Track A: Evaluate test cases in 30 seconds (no TAPD, no key, no IDE)

```bash
git clone https://github.com/WL2O2O/QASkillKit.git && cd QASkillKit
pip install pyyaml
python3 evals/evaluate.py
```

You'll see: of the 12 bundled case files, the 3 good ones pass and all 9 intentionally broken ones get flagged — 8 of them break exactly one rule each (one dedicated detection sample per rule), so the evaluator is no rubber stamp. Reports land in `evals/reports/`.

Want the AI to write cases on the fly and grade them? `export GLM_API_KEY=your_key`, then run `python3 evals/evaluate.py --live`. To feed in your own requirements or case files, follow the step-by-step guide in [evals/README.md](evals/README.md).

### Track B: Full QA workflow (TAPD teams)

Prerequisites:

| Dependency | Purpose | Required |
|:---|:---|:---:|
| [Qoder](https://qoder.com/) (or any IDE supporting AGENTS.md) | Runs agents & skills | ✅ Required |
| MCP: `mcp-server-tapd` | TAPD read/write | ✅ Required |
| MCP: `dbx` | DB read-only queries for real test data | Recommended |
| MCP: `browser-use` | UI automation | Required for ui-automation |
| MCP: `weknora-knowledge` | Business knowledge base | Optional |
| Python 3 + Node.js ≥ 18 | Utility scripts / OCR | ✅ Required |

Get started in 3 steps:

```bash
# 1. Clone
git clone https://github.com/WL2O2O/QASkillKit.git && cd QASkillKit

# 2. Configure MCP services (tapd required, others optional)

# 3. Run the setup wizard
/setup
```

After `/setup` generates `config/project.config.json` (gitignored), you're ready:

```
/testcase-generator 1019311   ← Generate test cases for TAPD requirement 1019311
test 1019311             ← Run UI automation for that requirement
/ys generate s92 report ← Generate acceptance report
/zb                     ← Generate this week's report
/eval                   ← Evaluate case quality (no TAPD, zero keys needed)
```

## 🧪 Agent Evaluation (public entry, no TAPD needed)

Clone and run without any TAPD project — experience the core methodology: **QA for AI itself**.

<!-- Source: docs/assets/src/eval-gate-en.html; re-render with bash docs/assets/src/render.sh eval-gate-en -->
<p align="center">
  <img src="docs/assets/eval-gate-en.png" alt="Dual-channel evaluation flow: cases plus requirement fixture enter the rule channel and LLM-as-Judge; negative controls prove discrimination; exit 0/1 passes or blocks; reports and bad cases feed back" width="100%">
</p>

```bash
pip install pyyaml
python3 evals/evaluate.py        # zero keys: rule channel + bundled desensitized outputs, baseline report
```

Provide any OpenAI-compatible key (e.g. `GLM_API_KEY`) to enable the LLM-as-Judge channel; `--live` makes the SUT prompt generate cases on the fly before evaluation. The eval set includes a **negative control** (intentionally bad output) that the evaluator must fully detect; the exit code is CI-ready for prompt regression. See [evals/README.md](evals/README.md).

**The evaluator is evaluated too** — pytest self-tests lock rule boundaries, table parsing, scan logic and the discrimination guarantee (`pip install -r requirements.txt && python3 -m pytest evals/tests -q`, zero keys, under a second); CI runs them on every push/PR.

**Prompt/model regression** — `python3 evals/evaluate.py --diff old.json new.json` compares two reports per case and per rule, listing regressions vs improvements (a ±1 single-dimension judge change counts as run-to-run noise, not regression); the exit code works as a regression gate. Report filenames carry date + time, so same-day re-runs never overwrite earlier baselines.

**See it in action** — `bash evals/ab-demo.sh` (needs a key) runs `--live` twice on the same evalset and model: once with the production prompt, once with a deliberately weakened variant, then diffs them. The real 2026-11-13 run flagged 37 regressions (change-point coverage 13/13 → 0/13, `exit_ok` True → False) and also exposed a blind spot in the evaluator itself (row-level checks were skipped whenever a table's column count drifted) — now fixed, with that run's real artifacts used as test anchors. Outputs and the diff report live in `evals/ab-demo/`. The same run also measured the judge channel's weakness: on a degraded output the rules found change-point coverage 0/5 while the LLM judge still awarded 5.0 on all four dimensions — so the coverage/consistency rubric was tightened (evalset bumped to v4) and re-verified with a real key: variant B's coverage scores did drop from 5/5/5 to 3/3/4, yet the four-dimension means (4.50/4.50/4.75) **still cleared the pass line**, and the judge merely performed the audit ritual while inventing its conclusions (an output covering zero change points was reported as "points 1-6 all covered", while a fully covered positive was docked to "only 3/5"). The verdict is written into `evals/README.md` and bc-0005: **mechanically decidable checks cannot be delegated to a small judge model — the gate trusts the deterministic rule channel only, and judge scores stay advisory.** That verdict drove evalset v5: the ground-truth change-point checklist and the rule channel's findings are now injected into the judge prompt (it may no longer derive its own checklist or overrule the rules), and `coverage` only rates what machines cannot decide — boundary values, exception paths, and step granularity. **v5 has since been re-run with a real key and met its acceptance criteria**: the weakened variant B's four-dimension means fell from 4.50/4.50/4.75 under v4 (all passing) to 2.75/3.25/2.25 (all failing for the first time), its contradiction rate dropped 54% → 4%, and the production variant A still scored 4.75/4.75/4.25. Evalset v6 then fixed one more recurring lie — the rules flagging a fabricated credential while the judge scored hallucination 5 and wrote "nothing fabricated" — by binding that dimension's definition to the rule channel's finding. Judge self-contradiction is now an automatic metric as well: `python3 evals/evaluate.py --judge-agreement report.json` cross-checks the judge's four dimension scores against the rule channel's deterministic findings and reports a contradiction rate (e.g. the rules catch a priority written as "High" while the judge scores consistency 5 and claims "priorities use P0/P1/P2"). Re-computed offline over the eleven archived judge-bearing reports: 67% for the earliest v2 baseline, 74% for the v3 weakened variant, 36%-54% after the v4 rubric tightening, 4%-7% after v5 fed the checklist and rule findings in, and 7% for v6 — quantified backing for "the gate trusts the rule channel only". The reverse-suspicion column (judge scoring a dimension down without matching rule evidence) was recomputed under a widened check after v6: the old implementation only inspected cases where all 8 rules passed and therefore missed "rules did fail, but not the rules backing this dimension", so the earlier claim of "zero in all six" is obsolete — the eleven reports now show 0-4 such items (four in the v6 repeated-grading run, all the same placeholder misjudgment), each routed to human re-review. One step further, judge stability is measurable too: `python3 evals/evaluate.py --runs 3` grades the same output three times and reports pass@3, per-dimension spread, and a verdict-flip list. The real 2026-11-14 run (12 cases × 3 rounds = 36 judge calls) showed all three positives passing 3/3 with a maximum spread of ≤1 — their scores reproduce — while the only unstable case was the negative control tc-neg-expected-empty, whose hallucination score went 1→1→5 (spread 4) and passed in just 1 of 3 rounds: **when the same output flips between pass and fail, a single judge run cannot be trusted.** More useful still, it separated two known problems by nature: three negative controls scored hallucination 1 in all three rounds (spread 0, each claiming the fixture's "account A" was a fabricated credential although those fixtures contain none) — **an error that reproduces is not noise, it is a rubric-wording defect** (bc-0009); whereas the consistency escape "this is a formatting issue, not an inconsistency" appeared in only one of three rounds (bc-0008), invisible to a single run. Stability diagnoses the judge only and never affects the exit code.

**Bring your own cases** — register with one command, no hand-written YAML:

```bash
python3 evals/evaluate.py --add path/to/cases.md --fixture path/to/requirement.md --points ①②
```

**What the report looks like** (excerpt from a real baseline; reports are currently in Chinese; full versions in `evals/reports/`):

```markdown
# 评测基线报告 2026-11-12（offline+judge）
- 判别力自测（负向对照）：✅ 全部检出
- 变更点覆盖：8/8

| case | 类型 | 规则通道 | Judge | 结论 |
|:---|:---|:---|:---|:---|
| tc-1000001-good | positive | ✅ | 4.8 | pass |
| tc-1000002-good | positive | ✅ | 5.0 | pass |
| tc-1000001-negative | negative-control | ❌ | 3.0 | detected |

- **tc-1000001-negative / priority_valid**：行1 优先级'P5'非法
- **tc-1000001-negative / coverage**：变更点③未被任何用例覆盖
```

The judge's per-dimension scorecard (real baseline; the deliberately broken negative control gets caught):

<p align="center">
  <img src="docs/assets/demo-judge-en.png" alt="LLM-as-Judge scorecard: two good cases pass at 4.8/5.0; the negative control scores 1 on hallucination and is detected" width="100%">
</p>

## 🏗️ Architecture

<!-- Source: docs/assets/src/architecture-en.html; re-render with bash docs/assets/src/render.sh architecture-en -->
<p align="center">
  <img src="docs/assets/architecture-en.png" alt="Architecture: the agent reads three compounding layers (skills, team memory, private config) and calls the MCP toolchain; one evaluator guards three quality gates" width="100%">
</p>

Three layers that compound in value:

1. **Skill layer** — each workflow is a SKILL.md with documented steps, pitfalls, and business rules
2. **Team memory layer** (`team-memory/`) — cross-skill knowledge and experience; git-tracked for the whole team
3. **Config layer** (`config/`) — all private info centralized in one place, gitignored, **the repo itself has zero sensitive data**

## 🧬 Design Principles

- **Pure Skill, zero framework** — no framework code to maintain; everything is natural-language MWP + simple scripts
- **Real data only** — test data must come from real DB queries or requirement originals; no AI-hallucinated cases
- **Human-AI boundary** — AI must not write to DB, execute payments, or other destructive operations; SQL is output-only for human execution
- **Compounding experience** — pitfalls from each run are fed back into team-memory and references
- **Cross-IDE compatible** — based on the standard AGENTS.md convention; works with Qoder, Claude Code, and more. A committed `.claude/skills → .qoder/skills` symlink makes Claude Code work out of the box (Windows: if the symlink doesn't resolve, run `mklink /D .claude\skills ..\.qoder\skills` in an admin terminal)

## 🔒 Privacy & Confidentiality

All private info is managed through three gitignore zones:

| Location | Contents | Git Status |
|:---|:---|:---|
| `config/project.config.json` | TAPD workspace_id, team members, DB connections, knowledge UUIDs | 🚫 Ignored (template `project.config.example.json` checked in) |
| `.qoder/team-memory/local/` | Team-private knowledge (e.g. table lookups) | 🚫 Ignored |
| `.qoder/skills/ui-automation/references/local/` | Environment addresses, account rules, pitfalls | 🚫 Ignored (template `env-template.md` checked in) |

Credentials (TAPD token, API keys) never enter config files — tokens from MCP config, keys from environment variables. Passwords are "ask each time, never record."

## 📁 Directory Structure

```
├── AGENTS.md                    # Global agent instructions (auto-loaded)
├── config/                      # Private config center (template committed, real config gitignored)
├── evals/                       # Agent evaluation module (public entry: YAML eval set + dual-channel evaluator + baseline reports)
├── .qoder/
│   ├── skills/                  # Skills (setup/testcase-generator/ui-automation/acceptance-report/...)
│   │   └── {skill}/SKILL.md     #   Each skill has a complete procedure + scripts/
│   └── team-memory/             # Team memory (01~06 topic docs + local/ private)
├── examples/                    # Desensitized examples (fictional case format samples)
├── demo/                        # Real-case desensitized samples (showing output quality)
├── workspace/                   # Working area (only personal/drafts/ gitignored)
└── _tmp/                        # Temporary files (gitignored)
```

## 🤝 Contributing

- **New skill**: Follow the SKILL.md structure in `.qoder/skills/` (how to use → workflow overview → step-by-step → pitfalls → output spec)
- **Update specs**: Edit `team-memory/` topic docs directly; git commit makes it team-wide
- **Hard rule**: Private info only in `config/` and `local/`; never hardcode into any committed file

## 📄 License

[MIT](LICENSE)