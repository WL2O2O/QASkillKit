---
name: testcase-evaluator
description: >
  Test-case quality evaluation skill (alias /eval). Conversational entry to the evals/
  dual-channel evaluator: registered evals (8 rule assertions + LLM-as-Judge 4-dimension
  scoring), repo-wide structural scan (--scan), custom scan roots (--scan-root),
  one-command case registration (--add), regression comparison of two reports (--diff),
  on-the-fly generation with a key (--live), a one-command A/B prompt regression demo
  (evals/ab-demo.sh: production prompt vs a deliberately weakened variant, then --diff),
  an offline judge-reliability audit (--judge-agreement: contradiction rate
  between judge scores and the rule channel's deterministic findings, zero key),
  and a judge-stability measurement (--runs N: grade the same output N times,
  report pass@N, per-dimension spread and verdict flips; needs a key).
  Explains violations in plain language; badcase root causes and calibration records
  stay draft-only until a human confirms. Runs with zero keys, no TAPD needed.
  测试用例评测 Skill（简写 /eval）：登记评测、全仓结构扫描、--add 一键登记、--diff 回归对比、
  有 key 时现场生成再评、ab-demo.sh 一键 A/B prompt 回归（正式版 vs 故意弱化版）、--judge-agreement 裁判-规则一致率离线核对（零 key）、--runs N 裁判稳定性重复评（需 key）；
  违规解读成人话，badcase 根因与校准记录出草稿待人工确认。零 key 可跑、不依赖 TAPD。
  Use when the user says "评测/跑评测/给用例打分/eval", "evaluate/run evals/grade this
  case file", "对比两次报告/有没有退步/回归对比", "A/B 对比 prompt/prompt 回归演示", "裁判靠谱吗/裁判矛盾率/judge agreement", "裁判稳不稳/分数会不会抖/重复评/--runs",
  gives a case-file path for a quality check, or types /eval.
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
| A/B prompt regression, one command | `bash evals/ab-demo.sh` | needs a key; `--live` with the production prompt (A) vs the deliberately weakened `evals/prompts/variant-b-weakened.md` (B), then `--diff`; exit 1 = regressions found; resumable, `FORCE=1` re-runs both; artifacts in `evals/ab-demo/` |
| Audit judge reliability on archived reports | `python3 evals/evaluate.py --judge-agreement REPORT.json ...` | zero key, pure offline recompute; contradiction rate = judge scored above the cap the rule channel allows (`CONTRACT_CAPS`); judge-not-run cases count as uncheckable and never enter the denominator; exit always 0 (diagnostic, not a gate) |
| Measure judge stability | `python3 evals/evaluate.py --runs 3` | needs a key; grades the same output N times and reports pass@N, per-dimension min~max/spread, and verdict flips; spread ≥2 = unstable (±1 is known noise); diagnostic only — never affects the exit code; a failed round is counted, never back-filled |
| Your own prompt variant | `python3 evals/evaluate.py --live --sut-prompt VARIANT.md` | path may be absolute, cwd-relative, or relative to `evals/` |
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
  suggested root cause (prompt/model/tool/knowledge/evalset/evaluator);
- **Negative-control violations are evidence of successful detection, not failures** —
  never report them as problems;
- Judge ran → explain the four dimension scores and reasons, and remind that scores
  are reference-only until calibration is done.
- Judge ran → since v5 the prompt carries the evalset's ground-truth change-point
  list (`change_points` in cases.yaml) plus the rule channel's findings, and the judge
  is told not to re-derive or overrule them: if a reason still contradicts those findings
  or invents change points, draft a badcase (bc-0005 pattern) instead of trusting the score;
- `coverage` now rates scene sufficiency and granularity only — per-change-point coverage
  is decided by the rule channel, so never present a judge coverage score as coverage proof.
- Report the judge-rule contradiction rate whenever judge scores exist
  (embedded in the baseline report, or `--judge-agreement` on archived JSON): a high rate
  means the judge is overriding facts the rules already settled — which is exactly why the
  gate trusts the rule channel. It is NOT the judge-human agreement rate; that still needs
  sampled re-review recorded in `calibration.yaml`.
- Since v6 `hallucination` is bound to the `no_secrets` rule finding: if the rules list a
  fabricated credential/intranet address, the score must be ≤2 and the reason must admit that
  row. A judge that scores it high, or writes "nothing fabricated", is a bc-0007-pattern badcase.
- `--runs N` (stability) → report pass@N and the flip list, not just the means: a case whose
  verdict flips between rounds must never be presented as "judge says pass". Unstable dimensions
  (spread ≥2) go to human re-review; the rule channel is unaffected by design.
- Also watch the reverse direction (`strict_flags`, "reverse suspicion"): the judge scoring a
  dimension ≤2 with no matching rule evidence. Since v6 the known false positive is abstract
  placeholders — "account A" / "some user" / angle-bracket slots are NOT fabricated credentials.
  Never report a reverse suspicion as a defect without reading the fixture first.

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