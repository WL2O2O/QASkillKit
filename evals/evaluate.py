#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QASkillKit 评测器（单文件 · 双通道 · 无 TAPD 公开入口）

通道 1 规则断言：格式/优先级/追溯/跳转引用/空预期/虚构凭证/变更点覆盖，零 key 可跑。
通道 2 LLM-as-Judge：coverage/relevance/consistency/hallucination 四维 1-5 分，
        检测到 API key 自动启用，否则明确跳过（不伪造分数）。

用法：
  python3 evals/evaluate.py                 # 离线评测内置脱敏产出（零 key 可跑）
  python3 evals/evaluate.py --live          # 先让 SUT prompt 现场生成用例再评测（需 key）
  python3 evals/evaluate.py --out DIR       # 报告输出目录（默认 evals/reports）

环境变量（key 只从环境读，不落盘）：
  EVAL_LLM_API_KEY / GLM_API_KEY / OPENAI_API_KEY   任一即可启用 Judge/live
  EVAL_LLM_BASE_URL   默认 https://open.bigmodel.cn/api/paas/v4（OpenAI 兼容）
  EVAL_LLM_MODEL      默认 glm-4-flash；--judge-model 可单独指定 Judge 模型

退出码：0 = 正样本全过且负向对照全部检出（CI 可直接用）；1 = 有失败。
依赖：pip install pyyaml
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent

RULES = ["format_columns", "priority_valid", "traceability", "no_jump_refs",
         "expected_non_empty", "no_secrets", "change_section", "coverage"]

JUMP_RE = re.compile(r"(见上|参见|同上|见\s|见：)")
SECRET_RE = re.compile(r"(密码[:：]\s*\S+|admin\d{3,}|http://(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.))")

# 失败规则 → 建议根因（人工确认后才算数，见 evals/README.md 根因 taxonomy）
SUGGESTED_ROOT_CAUSE = {
    "format_columns": "prompt", "priority_valid": "prompt", "traceability": "prompt",
    "no_jump_refs": "prompt", "expected_non_empty": "prompt", "change_section": "prompt",
    "coverage": "prompt", "no_secrets": "model",
}


def parse_case_tables(text):
    """解析所有用例表，返回行列表（每行=单元格列表）。"""
    rows, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and "优先级" in s and "预期结果" in s:
            current = []
            continue
        if current is not None:
            if s.startswith("|"):
                cells = [c.strip() for c in s.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):
                    continue  # 分隔行
                current.append(cells)
                rows.append(cells)
            elif s == "":
                current = None
    return rows


def rule_check(text, expected_points):
    """规则通道：返回 {rule: [violations]} 与统计信息。"""
    v = {r: [] for r in RULES}
    rows = parse_case_tables(text)
    if not rows:
        v["format_columns"].append("未解析到任何用例表")
    covered = set()
    for i, r in enumerate(rows, 1):
        if len(r) != 9:
            v["format_columns"].append("行%d 列数%d≠9" % (i, len(r)))
            continue
        _, prio, ref, _typ, _name, pre, steps, exp, _actual = r
        if prio not in ("P0", "P1", "P2"):
            v["priority_valid"].append("行%d 优先级%r非法" % (i, prio))
        if not ref:
            v["traceability"].append("行%d 关联引用为空" % i)
        covered.update(ch for ch in ref if ch in "①②③④⑤⑥⑦⑧⑨⑩")
        if not exp:
            v["expected_non_empty"].append("行%d 预期结果为空" % i)
        for field, label in ((pre, "前置条件"), (steps, "操作步骤"), (exp, "预期结果")):
            if JUMP_RE.search(field):
                v["no_jump_refs"].append("行%d %s含跳转引用" % (i, label))
            if SECRET_RE.search(field):
                v["no_secrets"].append("行%d %s含虚构凭证/内网地址" % (i, label))
    if "变更点" not in text:
        v["change_section"].append("缺少变更点说明")
    for cp in expected_points:
        if cp not in covered:
            v["coverage"].append("变更点%s未被任何用例覆盖" % cp)
    return v, {"rows": len(rows), "covered": sorted(covered)}


def llm_chat(messages, model, base, key):
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]


def extract_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


def judge(fixture, output, cfg, model, base, key):
    dims = cfg["dimensions"]
    prompt = (
        "你是严格的测试用例质量评审员。对照需求原文评审用例产出，按 1-5 分打分"
        "（5=完全满足，4=少量可接受瑕疵，3=明显问题，2=严重问题，1=完全不符）。\n"
        "维度：%s。\n只输出 JSON，格式 {\"维度名\": {\"score\": 数字, \"reason\": \"一句话理由\"}}。\n\n"
        "【需求原文】\n%s\n\n【用例产出】\n%s" % (", ".join(dims), fixture, output))
    raw = llm_chat([{"role": "user", "content": prompt}], model, base, key)
    scores = extract_json(raw)
    for d in dims:
        if d not in scores or not isinstance(scores[d].get("score"), (int, float)):
            raise ValueError("judge 输出缺维度 %s" % d)
    return scores


def resolve_key():
    for var in ("EVAL_LLM_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var], var
    return None, None


def main():
    ap = argparse.ArgumentParser(description="QASkillKit 双通道评测器")
    ap.add_argument("--eval-set", default=str(EVAL_DIR / "cases.yaml"))
    ap.add_argument("--out", default=str(EVAL_DIR / "reports"))
    ap.add_argument("--live", action="store_true", help="SUT 现场生成用例再评测（需 key）")
    ap.add_argument("--sut-model", default=os.environ.get("EVAL_LLM_MODEL", "glm-4-flash"))
    ap.add_argument("--judge-model", default=os.environ.get("EVAL_JUDGE_MODEL", ""))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.eval_set).read_text(encoding="utf-8"))
    jcfg = cfg["meta"]["judge"]
    key, key_src = resolve_key()
    base = os.environ.get("EVAL_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    judge_model = args.judge_model or args.sut_model
    if args.live and not key:
        sys.exit("--live 需要 API key（EVAL_LLM_API_KEY/GLM_API_KEY/OPENAI_API_KEY 任一）")

    results = []
    for case in cfg["cases"]:
        fixture = (EVAL_DIR / case["fixture"]).read_text(encoding="utf-8")
        if args.live and case["kind"] == "positive":
            sut_prompt = (EVAL_DIR / cfg["meta"]["sut_prompt"]).read_text(encoding="utf-8")
            output = llm_chat([{"role": "system", "content": sut_prompt},
                               {"role": "user", "content": "需求原文：\n" + fixture}],
                              args.sut_model, base, key)
            live_dir = ROOT / "_tmp" / "eval-live"
            live_dir.mkdir(parents=True, exist_ok=True)
            (live_dir / (case["id"] + ".md")).write_text(output, encoding="utf-8")
            output_src = "_tmp/eval-live/%s.md" % case["id"]
        else:
            if "output" not in case:
                sys.exit("case %s 缺少 output：离线模式评的是现成用例文件；"
                         "想让 AI 现场写请加 --live（详见 evals/README.md）" % case["id"])
            output = (EVAL_DIR / case["output"]).read_text(encoding="utf-8")
            output_src = case["output"]

        violations, stats = rule_check(output, case["expected_change_points"])
        rule_pass = all(not violations[r] for r in RULES)

        judge_scores, judge_note = None, "skipped（无 API key，仅规则通道）"
        if key:
            try:
                judge_scores = judge(fixture, output, jcfg, judge_model, base, key)
                judge_note = "model=%s" % judge_model
            except Exception as e:  # judge 失败不伪造分数，明确记录
                judge_note = "error: %s" % e

        if case["kind"] == "negative-control":
            detected = {r for r in RULES if violations[r]}
            ok = set(case.get("expect_violations", [])) <= detected
            verdict = "detected" if ok else "MISSED"
        else:
            judge_ok = judge_scores is None or (
                sum(judge_scores[d]["score"] for d in jcfg["dimensions"]) / len(jcfg["dimensions"])
                >= jcfg["pass_threshold"])
            verdict = "pass" if (rule_pass and judge_ok) else "fail"

        results.append({
            "id": case["id"], "kind": case["kind"], "output_src": output_src,
            "violations": {r: violations[r] for r in RULES if violations[r]},
            "stats": stats, "rule_pass": rule_pass,
            "judge": judge_scores, "judge_note": judge_note, "verdict": verdict,
        })

    positives = [r for r in results if r["kind"] == "positive"]
    negatives = [r for r in results if r["kind"] == "negative-control"]
    compliance = {r: (sum(1 for p in positives if not p["violations"].get(r)) / len(positives))
                  for r in RULES} if positives else {}
    total_cp = sum(len(c["expected_change_points"]) for c in cfg["cases"] if c["kind"] == "positive")
    covered_cp = sum(len(set(p["stats"]["covered"]) & set(
        next(c for c in cfg["cases"] if c["id"] == p["id"])["expected_change_points"]))
        for p in positives)
    discrimination = all(n["verdict"] == "detected" for n in negatives)
    exit_ok = all(p["verdict"] == "pass" for p in positives) and discrimination

    today = datetime.date.today().isoformat()
    mode = ("live" if args.live else "offline") + ("+judge" if key else "+rules-only")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "date": today, "mode": mode, "evalset_version": cfg["meta"]["version"],
        "key_source": key_src, "judge_model": judge_model if key else None,
        "cases": results,
        "aggregates": {
            "rule_compliance": compliance,
            "change_point_coverage": [covered_cp, total_cp],
            "discrimination_ok": discrimination,
            "exit_ok": exit_ok,
        },
    }
    (out_dir / ("baseline-%s.json" % today)).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 评测基线报告 %s（%s）" % (today, mode), ""]
    md.append("- 评测集版本：%s；Judge：%s" % (cfg["meta"]["version"],
              ("启用（%s，key 来源 %s）" % (judge_model, key_src)) if key else "跳过（无 key，不伪造分数）"))
    md.append("- 判别力自测（负向对照）：%s" % ("✅ 全部检出" if discrimination else "❌ 有漏检"))
    md.append("- 变更点覆盖：%d/%d" % (covered_cp, total_cp))
    md.append("")
    md.append("## 用例级结果")
    md.append("")
    md.append("| case | 类型 | 规则通道 | Judge | 结论 |")
    md.append("|:---|:---|:---|:---|:---|")
    for r in results:
        j = "—" if r["judge"] is None else "%.1f" % (
            sum(r["judge"][d]["score"] for d in jcfg["dimensions"]) / len(jcfg["dimensions"]))
        md.append("| %s | %s | %s | %s | %s |" % (
            r["id"], r["kind"], "✅" if r["rule_pass"] else "❌", j, r["verdict"]))
    md.append("")
    md.append("## 规则合规率（正样本）")
    md.append("")
    md.append("| 规则 | 合规率 |")
    md.append("|:---|:---|")
    for r in RULES:
        md.append("| %s | %.0f%% |" % (r, compliance.get(r, 0) * 100))
    md.append("")
    md.append("## 违规明细与建议根因（根因须人工确认，见 badcases.yaml）")
    md.append("")
    any_v = False
    for r in results:
        for rule, msgs in r["violations"].items():
            any_v = True
            md.append("- **%s / %s**（建议根因：%s）：%s" % (
                r["id"], rule, SUGGESTED_ROOT_CAUSE.get(rule, "待定"), "；".join(msgs)))
    if not any_v:
        md.append("（正样本无违规；负向对照违规见 JSON 报告）")
    md.append("")
    md.append("> Judge 校准提醒：LLM-as-Judge 自身需人工抽样校准（judge-人工一致率），")
    md.append("> 本报告 judge 分数仅作基线参考，方法论见 evals/README.md。")
    (out_dir / ("baseline-%s.md" % today)).write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n".join(md[:12]))
    print("报告已写入：%s/baseline-%s.{md,json}" % (out_dir, today))
    print("exit_ok=%s" % exit_ok)
    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()