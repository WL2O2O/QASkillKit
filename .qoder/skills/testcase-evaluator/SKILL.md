---
name: testcase-evaluator
description: >
  Test-case quality evaluation skill (alias /eval). Conversational entry to the evals/
  dual-channel evaluator: registered evals (8 rule assertions + LLM-as-Judge 4-dimension
  scoring), repo-wide structural scan (--scan), custom scan roots (--scan-root),
  one-command case registration (--add), regression comparison of two reports (--diff),
  and on-the-fly generation with a key (--live).
  Explains violations in plain language; badcase root causes and calibration records
  stay draft-only until a human confirms. Runs with zero keys, no TAPD needed.
  测试用例评测 Skill（简写 /eval）：登记评测、全仓结构扫描、--add 一键登记、--diff 回归对比、
  有 key 时现场生成再评；
  违规解读成人话，badcase 根因与校准记录出草稿待人工确认。零 key 可跑、不依赖 TAPD。
  Use when the user says "评测/跑评测/给用例打分/eval", "evaluate/run evals/grade this
  case file", "对比两次报告/有没有退步/回归对比", gives a case-file path for a quality
  check, or types /eval.
---

# Test-Case Evaluation (testcase-evaluator)

> Division of labor: the capability itself is `evals/evaluate.py` (dual-channel evaluator).
> This skill only does **orchestration and interpretation** — it never reimplements
> evaluation logic. Tutorials and field details live in
> [evals/README.md](../../../evals/README.md) (Chinese; English overview in README.en.md).
> Upstream/downstream: testcase-generator writes cases, testcase-reviewer checks
> prototype consistency, this skill grades case quality.

## Usage

Triggered by `/eval`, or phrases like "run evals", "evaluate this case file",
"grade xxx.md", "评测一下这份用例", "跑评测". If the target is ambiguous, ask first
(registered set / specific file / whole repo / live generation / two-report diff) — do not guess.
Always respond in the user's language.

## Execution Flow Overview

| Step | Action | Required | Conditional |
| :--- | :--- | :---: | :--- |
| 0 | Per AGENTS.md, read project config + team-memory README index and relevant topics (01/03/04) | ✅ | |
| 1 | Clarify the evaluation target, pick a mode (see mode table) | ✅ | |
| 2 | Detect API keys in the environment; decide whether the judge channel runs | ✅ | |
| 3 | Run the evaluator; collect exit code and reports | ✅ | |
| 4 | Interpret results in plain language and report | ✅ | |
| 5 | Closed loop: badcase draft / calibration reminder / version-bump reminder | | on fail, after judge runs, or when the rubric changes |
| 6 | Intermediate artifacts go to `_tmp/`, never pollute official directories | ✅ | |

## Mode Quick Reference

| User intent | Command | Notes |
| :--- | :--- | :--- |
| Run evals / registered set | `python3 evals/evaluate.py` | 8 rules on registered cases + negative-control self-test; judge auto-enabled with a key |
| Scan all case files | `python3 evals/evaluate.py --scan` | 6 structural rules; covers unregistered files too |
| Scan a directory outside the repo | `python3 evals/evaluate.py --scan --scan-root DIR` | repeatable; defaults to the project's case directories |
| Grade a specific unregistered file | `--scan` (or `--scan-root`) first for structure | content grading (coverage/judge) needs registration: `--add CASE.md --fixture REQ.md --points ①②`, see evals/README scenario 2 |
| Register my own case | `python3 evals/evaluate.py --add CASE.md --fixture REQ.md --points ①②` | copies the fixture, appends to cases.yaml preserving comments; remind the user to desensitize (public repo) |
| AI writes cases, then grades | `python3 evals/evaluate.py --live` | needs a key; simplified (text only, no prototypes/DB) |
| Compare two runs (prompt/model regression) | `python3 evals/evaluate.py --diff OLD.json NEW.json` | per-case per-rule better/worse; judge ±1 single-dim change = noise, drop ≥2 = regression; exit 1 on regressions; scan reports comparable too, but never baseline-vs-scan |
| Different model/vendor | env `EVAL_LLM_BASE_URL`/`EVAL_LLM_MODEL` or `--judge-model` | any OpenAI-compatible endpoint |

## Execution Notes

**Step 2, key detection**: any of `EVAL_LLM_API_KEY` / `GLM_API_KEY` / `OPENAI_API_KEY`
present → judge auto-enabled; none → rules only, and tell the user explicitly
"judge skipped, no scores fabricated". Keys are read from the environment only:
never written to any file, never echoed in full in chat.

**Step 3, running**: exit code 0 = all pass, 1 = failures; reports default to
`evals/reports/` (override with `--out`); filenames carry date + time, so same-day
re-runs never overwrite earlier baselines. Add `--brief` for hook/CI-style concise
output (blocking items only).

**Step 4, interpretation**:
- Translate violations into plain language: which file, which row, which rule,
  suggested root cause (prompt/model/tool/knowledge/evalset);
- **Negative-control violations are evidence of successful detection, not failures** —
  never report them as problems;
- Judge ran → explain the four dimension scores and reasons, and remind that scores
  are reference-only until calibration is done.

**Step 5, closed loop (always human-confirmed; AI drafts alone don't count)**:
- fail → draft an `evals/badcases.yaml` entry (status open, confirmed_by null);
  only mark fixed after the user confirms;
- judge ran → remind about sampled human re-review; append agreement rates to
  `evals/calibration.yaml`;
- user wants to tighten/loosen the rubric → remind the three-piece set:
  bump version + re-run baseline + re-calibrate.

## Red Lines

- Never fabricate scores: no key → skip; judge failure → record the error honestly.
- Keys never touch disk; private info never enters the repo (project-level red lines in AGENTS.md).
- Root-cause confirmation and calibration re-review must be human; this skill only drafts and reminds.
- No dependency on other skills: run evals/ scripts directly (project skill-robustness principle).