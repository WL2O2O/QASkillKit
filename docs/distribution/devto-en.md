# I Built a Grading Teacher for AI-Written Test Cases

> Draft for dev.to. Verify the numbers against the latest reports in the repo before publishing.
> **Status: on hold — not published (decided 2026-11-18; revisit when needed).**

## The short version

Making an LLM write test cases is easy. **Proving it wrote them correctly** is the hard part.

I split the problem into two channels: deterministic **rule assertions** handle everything a machine can decide (table structure, priority values, traceability, cross-case references, empty expectations, fabricated secrets, change-point coverage), and an **LLM-as-Judge** only rates what machines cannot (scenario depth, relevance, semantic consistency, hallucination). The gate trusts the rule channel only; judge scores stay advisory.

It is open source: [QASkillKit](https://github.com/WL2O2O/QASkillKit). Clone it and you get a zero-key run in 30 seconds:

```bash
git clone https://github.com/WL2O2O/QASkillKit.git && cd QASkillKit
pip install pyyaml
python3 evals/evaluate.py
```

Twelve cases ship with the repo: three good ones pass, nine deliberately broken ones (eight of them break exactly one rule each — one "single-rule isolation shot" per assertion) are all caught.

This post is not about prompt engineering for test cases. It is about **grading the homework** — and the three traps I fell into along the way.

![Dual-channel evaluation flow: case + requirement go through the rule channel and an LLM judge; negative controls self-test discrimination; exit 0/1 gates the result](docs/assets/eval-gate-en.png)

## Trap 1: An LLM judge performs the ritual, then invents the conclusion

The obvious design is to hand the case and the requirement to a large model and ask for a score.

I did that first. Then an A/B experiment went wrong in an instructive way: I deliberately weakened the generation prompt (removing traceability, change-point and table-structure constraints). The output failed the rule channel on **change-point coverage 0/5, a missing change-point section, a 6-column table, and four "same as above" shortcuts** — and the judge gave it **5.0 on all four dimensions**.

Tightening the rubric made it worse in a subtler way. The judge started writing "change points 1–6 are all covered" — an audit-shaped sentence. But that output covered **zero** change points and had no change-point section at all. In the same run, a positive case that the rules confirmed as fully covered was docked to "only 3/5" — while its requirement had exactly three change points.

The lesson: **mechanically decidable checks cannot be delegated to a small judge model.** It learns the tone of auditing without doing the audit.

## Trap 2: Rules have blind spots too

So drop the judge and use rules only? Also no. Two real misses:

1. **Header drift hid row-level checks.** The old implementation saw a row with "column count ≠ 9", reported one format violation and `continue`d — skipping the other five row-level checks. The degraded output happened to be a 6-column table, so illegal priorities, "same as above" jumps and missing traceability all showed up as **100% compliant**.
2. **A new shape of cross-case reference.** "See above" and "same as above" are easy to catch; "run TC1's steps" — pushing a precondition onto another test case — was not. It is also sneakier, because it reads like normal prose.

Both fixes were small: fall back to **column-name checks** when headers are non-standard, and extend the reference regex to "run/refer to/reuse + case/TC + number" (the number is mandatory, so "run the export flow" is not flagged). But both taught the same lesson: **the evaluator needs to be evaluated too.** It now has 190 pytest assertions locking rule boundaries, with the real failure artifacts used as anchors.

## The design: two channels + negative controls

- **Rule channel (zero key)** — 8 deterministic assertions. CI and the pre-commit hook run only this: deterministic checks should not depend on a network or a model.
- **Judge channel (key required)** — four dimensions, 1–5, pass line at mean ≥ 4. It runs **after** the rule channel and only adds semantic judgment.
- **Negative controls** — nine deliberately broken samples, each violating at least one rule, proving the evaluator is not a rubber stamp. Discrimination is judged by "was it detected", never by the judge's score.
- **A three-step discipline** — every rubric change must bump the evalset version, re-run the zero-key baseline, and be re-verified with a real key. That way any "improvement" rules out "the standard was loosened".

To compare two runs after changing a prompt or model:

```bash
python3 evals/evaluate.py --diff old-report.json new-report.json
```

It lists per-case, per-rule regressions and improvements, and the exit code works as a regression gate. A ±1 judge move on a single dimension is run-to-run noise, not a regression — measured, not assumed.

## I also built a health check for the judge itself

If the judge cannot be trusted, quantify how untrustworthy it is. Three metrics, all recomputable offline with zero key:

1. **Contradiction rate** (`--judge-agreement`) — did the judge score above the cap the rule channel's findings allow? E.g. the rules catch a priority written as "P5", the cap says consistency ≤ 3, the judge gives 4: that is one contradiction. Over archived reports: 67% at the earliest baseline, 36–54% after the v4 tightening, 4–7% after v5 fed the judge the facts, and **0/14** at v7.
2. **Stability** (`--runs 3`) — grade the same output three times, report per-dimension spread and verdict flips. In one real run a negative control's hallucination score went 1→1→5 with `pass@3` of 1/3: **when the same output flips between pass and fail, one judge run cannot be trusted.**
3. **Reverse suspicion** — the judge scores a dimension down with no matching rule evidence. This is what caught a systematic "account A is a fabricated credential" misjudgment.

## The latest version (v8): partial success, honestly

This section exists because **the part I could not fix is more informative than the part I did.**

v8 attacked three known judge defects at once: abstract-reference misjudgment, invented coverage gaps, and treating a recorded product defect as the case's own format error. Besides rewording, it injects three **machine-verified facts** into the judge prompt (no column problems detected, a change-point→case-name mapping, the abstract references actually present in the output) — the v5 lesson again: if a machine can compute it, don't ask the judge to.

Three keyed repeated runs, each adding one layer:

| Variant | Reverse suspicions | Contradiction rate | Result |
|:---|:---|:---|:---|
| Wording only | 2 | 0/14 | fails |
| + machine facts | **0** | 1/14 | first two bars met, third still 0/3 |
| + phrase ban | **0** | **2/14** | cap adherence regressed |

The sharpest case: the judge wrote "the priority column contains the illegal value 'P5'" and then scored consistency 4 — the cap is ≤ 3. **It admitted the fact and ignored the cap.**

The conclusion: machine facts fix "cannot read the facts", but the longer the prompt, the more a small model loses track of meta-rules. **The wording lever is spent; the next version should truncate caps in code** (`score = min(score, cap)`) instead of adding more prose.

All three unfinished badcases were kept honest: bc-0009 was signed off and marked `fixed` only after its acceptance bars were met; bc-0010 and bc-0011 remain at `confirmed` because the fix has not landed — **half a cure is never quietly promoted to fixed.**

## Try it / steal it

```bash
# zero key: rule channel + repo-wide scan
python3 evals/evaluate.py
python3 evals/evaluate.py --scan

# evaluator self-tests (zero key, ~0.3s)
python3 -m pytest evals/tests -q

# with a key: judge + stability + agreement audit
export GLM_API_KEY=your_key
python3 evals/evaluate.py --runs 3
python3 evals/evaluate.py --judge-agreement evals/reports/xxx.json

# A/B prompt regression (production prompt vs deliberately weakened variant)
bash evals/ab-demo.sh
```

Register your own case in one command:

```bash
python3 evals/evaluate.py --add your-case.md --fixture requirement.md --points ①②③
```

The full methodology, calibration log and root-cause analyses of all 12 badcases live in [evals/README.md](https://github.com/WL2O2O/QASkillKit/blob/main/evals/README.md). Every number is tied to a real report under `evals/reports/`, so it can be recomputed rather than trusted.

If the idea of "first prove the evaluator is trustworthy, then use it to prove the cases are trustworthy" resonates, I would love to hear how your team validates AI output. The question I care about most: **would you put an LLM judge's score directly on your merge gate?**

---

**Cover / inline images**

1. Hero: `docs/assets/hero-en.png`
2. Flow diagram: `docs/assets/eval-gate-en.png`
3. Trap 1: `docs/assets/demo-judge-en.png`
4. Ending: `docs/assets/demo-zero-key.png`

**Publishing notes**

- Title: I Built a Grading Teacher for AI-Written Test Cases
- Tags: testing, ai, llm, python, opensource
- Repo: https://github.com/WL2O2O/QASkillKit
- If cross-posting, set the dev.to copy as canonical (or vice versa) to avoid duplicate-content dilution.
