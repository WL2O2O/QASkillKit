#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QASkillKit 评测器（单文件 · 双通道 · 无 TAPD 公开入口）

通道 1 规则断言：格式/优先级/追溯/跳转引用/空预期/虚构凭证/变更点说明/变更点覆盖，零 key 可跑。
通道 2 LLM-as-Judge：coverage/relevance/consistency/hallucination 四维 1-5 分，
        检测到 API key 自动启用，否则明确跳过（不伪造分数）。

用法：
  python3 evals/evaluate.py                 # 离线评测内置脱敏产出（零 key 可跑）
  python3 evals/evaluate.py --live          # 先让 SUT prompt 现场生成用例再评测（需 key）
  python3 evals/evaluate.py --scan          # 全仓结构扫描：用例目录所有 MD 跑 6 项结构规则（零 key）
  python3 evals/evaluate.py --scan --scan-root DIR  # 扫自定义用例目录（可多次指定）
  python3 evals/evaluate.py --add 用例.md --fixture 需求.md --points ①②  # 一键登记自己的用例
  python3 evals/evaluate.py --diff 旧报告.json 新报告.json  # 回归对比：逐用例逐规则变好/变坏（零 key）
  python3 evals/evaluate.py --judge-agreement 报告.json [报告.json ...]  # 裁判-规则一致率核对（零 key，离线重算已存档报告）
  python3 evals/evaluate.py --runs 3       # 裁判稳定性：同一产出重复评 3 轮，看极差与结论翻转（需 key）
  python3 evals/evaluate.py --live --sut-prompt 变体.md    # A/B prompt 回归：换被测 prompt 现场生成（需 key）
  python3 evals/evaluate.py --out DIR       # 报告输出目录（默认 evals/reports）

报告命名：<前缀>-<日期>-<时分秒>.{md,json}，同日重跑互不覆盖（Judge 基线不会被零 key 重跑顶掉）。
--diff 退出码：0 = 无退步（可当回归门禁）；1 = 有退步。Judge 单维 ±1 视为运行间抖动不判退步
（见 calibration.yaml），降幅 ≥2 才判退步。
--judge-agreement 矛盾率：裁判给分高于「规则通道确定性结论所允许的上限」的比例（CONTRACT_CAPS）；
它只体检裁判有没有自相矛盾，不等于 judge-人工一致率（那需抽样复批）。裁判未跑的用例计入 uncheckable，不进分母。
--runs N 稳定性：同一产出重复评 N 轮，报告里给出 pass@N、各维度 min~max/极差、结论翻转；
极差 ≥2 记不稳定（±1 是已知运行间抖动）。它只诊断裁判、**不参与退出码**，门禁仍只认规则通道；
裁判没跑或成功轮次不足 2 时如实写「未测」，不拿缺数据冒充稳定。

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
import shutil
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

# Judge 维度定义：显式写明含义与方向（一律"分越高越好"）。
# 2026-11-12 首次真实运行校准产物：修复 hallucination 极性误解与"实际结果列为空"误判，
# 见 badcases.yaml bc-0001 / bc-0002。
# 2026-11-13 A/B prompt 演示发现裁判对格式/覆盖退化几乎无感（B 变体覆盖 0/5 仍给四维 5.0），
# coverage 改为"先逐变更点核对再打分 + 分数上限"、consistency 纳入输出契约，见 bc-0004。
# 2026-11-13 v4 实跑验证未达标（裁判把核对动作演出来但结论是编的、上限压不住，见 bc-0005）：
# 改为"机械事实不让裁判自己算"——变更点清单由评测集注入（不再让裁判自己拆），
# 规则通道已检出的违规作为既定事实注入（裁判不得否认），coverage 只评粒度/边界/异常充分性。
DIM_DEFS = {
    "coverage": (
        "覆盖充分性：本次需求的变更点清单已在下方【变更点清单】给出，"
        "\"每个变更点有没有对应用例\"由规则通道机械判定（结果见【规则通道已检出的确定性违规】），"
        "本维度**不重复判这件事、也不得自己另拆一份清单**。你只评用例的场景充分性与粒度："
        "边界值（阈值临界、上下限、空值/超长）、异常场景（失败、超时、并发、权限不足、数据不存在）、"
        "状态分支与数据组合是否写到，步骤与预期是否细到可照着执行。分数上限："
        "5=主要变更点都有主流程 + 边界 + 异常，粒度可直接执行；"
        "4=主流程齐、边界或异常有少量缺口；3=基本只有主流程，边界与异常缺失；"
        "2=多数变更点只有一条笼统用例，粒度不足以指导执行；1=用例过于笼统或与需求脱节。"
        "reason 必须写出你核对到的具体缺口（例如\"变更点②只写了成功路径，缺未开通租户的报错分支\"），"
        "禁止只写\"覆盖全面\"这类结论性套话。"
    ),
    "relevance": "相关性：每条用例是否直接对应需求中的功能点或规则。5=全部直接相关",
    "consistency": (
        "一致性：用例自身是否前后一致且可独立执行——术语与字段名前后统一、"
        "前置条件与操作步骤不矛盾、预期结果与操作步骤对得上、一条用例不依赖另一条才能读懂。"
        "**列结构、优先级取值、跳转引用这类可机械判定的输出契约由规则通道判**："
        "【规则通道已检出的确定性违规】里列出的事实不得否认、不得说\"符合要求\"，"
        "只要其中存在任一条契约违背（列数漂移、P3 或\"高/中/低\"、\"同上/见上文/参见\"、"
        "缺关联引用列），本维度不高于 3；没有契约违背时才按语义一致性给 4-5。"
    ),
    "hallucination": "无幻觉程度：是否虚构需求原文里不存在的事实。**先看【规则通道已检出的确定性违规】里有没有 no_secrets**：只要那里列出\"含虚构凭证/内网地址\"，本维度不得高于 2，且 reason 必须承认该行事实（写\"未虚构\"\"无幻觉\"即为不合格理由）。判定口径：需求原文没给出的账号、密码、token、内网 IP/域名、URL、库表名、具体人名/门店名，被写进前置条件、操作步骤或预期结果，就算虚构。例外只有一种——值本身带明显占位标记（尖括号占位符、\"示例\"、\"待补充\"、\"XXX\"、\"脱敏\"）；**写\"测试账号\"再跟一个具体账号名 + 明文密码不算标注，一律按虚构计**（\"使用测试账号 adminNNN、密码: 明文\"正是 AI 编造凭证的典型特征）。分数上限：5=完全没有需求外的事实；4=仅 1 处未标注的可疑数据且不影响执行；3=2 处以上可疑数据，或编造了需求里没有的功能/字段/规则；2=规则通道已检出 no_secrets，或出现明确的虚构凭证/内网地址；1=大面积虚构、用例无法照做。reason 必须落到具体行与具体值（哪一行、哪个值、需求原文里没有）。",
}


def parse_case_tables_with_headers(text):
    """解析所有用例表，返回 [(表头单元格, 该表数据行列表), ...]。

    表头识别条件与 parse_case_tables 一致：以 | 开头且同时含"优先级""预期结果"。
    保留表头是为了在表头非标准 9 列时，还能按列名兜底检查内容（见 rule_check）。
    """
    tables, header, rows = [], None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and "优先级" in s and "预期结果" in s:
            if header is not None:
                tables.append((header, rows))
            header = [c.strip() for c in s.strip("|").split("|")]
            rows = []
            continue
        if header is not None:
            if s.startswith("|"):
                cells = [c.strip() for c in s.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):
                    continue  # 分隔行
                rows.append(cells)
            elif s == "":
                tables.append((header, rows))
                header, rows = None, []
    if header is not None:
        tables.append((header, rows))
    return tables


def parse_case_tables(text):
    """解析所有用例表，返回行列表（每行=单元格列表）。"""
    return [r for _h, rows in parse_case_tables_with_headers(text) for r in rows]


def is_standard_header(header):
    """标准 9 列表头：位置固定，可直接按下标取值（第 1 列名称各团队略有差异，不做约束）。"""
    return (len(header) == 9 and header[1] == "优先级" and header[2] == "关联引用"
            and header[7] == "预期结果")


CHANGE_POINT_CHARS = "①②③④⑤⑥⑦⑧⑨⑩"


def rule_check(text, expected_points):
    """规则通道：返回 {rule: [violations]} 与统计信息。"""
    v = {r: [] for r in RULES}
    tables = parse_case_tables_with_headers(text)
    rows = [r for _h, rs in tables for r in rs]
    if not rows:
        v["format_columns"].append("未解析到任何用例表")
    covered = set()
    i = 0   # 行号跨表连续，与历史报告口径一致
    for header, trows in tables:
        if is_standard_header(header):
            for r in trows:
                i += 1
                if len(r) != 9:
                    v["format_columns"].append("行%d 列数%d≠9" % (i, len(r)))
                    continue
                _, prio, ref, _typ, _name, pre, steps, exp, _actual = r
                if prio not in ("P0", "P1", "P2"):
                    v["priority_valid"].append("行%d 优先级%r非法" % (i, prio))
                if not ref:
                    v["traceability"].append("行%d 关联引用为空" % i)
                covered.update(ch for ch in ref if ch in CHANGE_POINT_CHARS)
                if not exp:
                    v["expected_non_empty"].append("行%d 预期结果为空" % i)
                for field, label in ((pre, "前置条件"), (steps, "操作步骤"), (exp, "预期结果")):
                    if JUMP_RE.search(field):
                        v["no_jump_refs"].append("行%d %s含跳转引用" % (i, label))
                    if SECRET_RE.search(field):
                        v["no_secrets"].append("行%d %s含虚构凭证/内网地址" % (i, label))
            continue

        # 表头非标准（列数/列序变了）：按下标取值会错位，改成按列名兜底检查，
        # 否则"表格结构漂移"会把优先级非法、跳转引用、空预期结果等内容缺陷一起藏起来
        # （2026-11-13 A/B prompt 演示实测踩到，见 badcases.yaml bc-0003）。
        v["format_columns"].append("表头非标准 9 列：%s（共 %d 列，已按列名兜底检查内容）"
                                   % ("|".join(header), len(header)))
        idx = {name: n for n, name in enumerate(header)}
        if "关联引用" not in idx:
            v["traceability"].append("表头缺少关联引用列：用例无法追溯到变更点")

        def cell(r, name):
            n = idx.get(name)
            return r[n] if n is not None and n < len(r) else ""

        for r in trows:
            i += 1
            if len(r) != 9:
                v["format_columns"].append("行%d 列数%d≠9" % (i, len(r)))
            prio = cell(r, "优先级")
            if prio not in ("P0", "P1", "P2"):
                v["priority_valid"].append("行%d 优先级%r非法" % (i, prio))
            if "关联引用" in idx:
                ref = cell(r, "关联引用")
                if not ref:
                    v["traceability"].append("行%d 关联引用为空" % i)
                covered.update(ch for ch in ref if ch in CHANGE_POINT_CHARS)
            exp = cell(r, "预期结果")
            if not exp:
                v["expected_non_empty"].append("行%d 预期结果为空" % i)
            for name in ("前置条件", "操作步骤", "预期结果"):
                field = cell(r, name)
                if JUMP_RE.search(field):
                    v["no_jump_refs"].append("行%d %s含跳转引用" % (i, name))
                if SECRET_RE.search(field):
                    v["no_secrets"].append("行%d %s含虚构凭证/内网地址" % (i, name))

    if "变更点" not in text:
        v["change_section"].append("缺少变更点说明")
    for cp in expected_points:
        if cp not in covered:
            v["coverage"].append("变更点%s未被任何用例覆盖" % cp)
    return v, {"rows": len(rows), "covered": sorted(covered)}


# 全仓结构扫描：不需要需求原文/登记就能查的 6 项结构规则。
# 覆盖度与变更点说明依赖 fixture/expected_points，留给登记评测，不在扫描范围。
# 扫描根 = 项目约定的用例存放目录（--scan-root 可覆盖）；evals/fixtures 的负向对照故意写坏，不扫。
SCAN_ROOTS = ["workspace/testcases", "examples", "demo"]
SCAN_RULES = ["format_columns", "priority_valid", "traceability",
              "no_jump_refs", "expected_non_empty", "no_secrets"]


def scan_repo(roots=None):
    """扫描用例目录下所有含用例表的 MD，返回逐文件结构违规。"""
    results = []
    for root in (roots if roots is not None else SCAN_ROOTS):
        base = Path(root)
        if not base.is_absolute():
            base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not parse_case_tables(text):
                continue  # 不含用例表的 MD（说明文档等）跳过
            v, stats = rule_check(text, [])
            try:
                rel = str(path.relative_to(ROOT))
            except ValueError:
                rel = str(path)  # 仓库外的自定义扫描根：记绝对路径
            results.append({
                "path": rel,
                "rows": stats["rows"],
                "violations": {r: v[r] for r in SCAN_RULES if v[r]},
            })
    return results


def report_stem(prefix, now=None):
    """报告文件名主干：<前缀>-<日期>-<时分秒>。同日重跑互不覆盖（防 Judge 基线被零 key 重跑顶掉）。"""
    now = now or datetime.datetime.now()
    return "%s-%s-%s" % (prefix, now.strftime("%Y-%m-%d"), now.strftime("%H%M%S"))


# ---------- 回归对比（--diff） ----------

# Judge 单维 ±1 属运行间抖动（v2 复跑覆盖度 5→4 结论不变，见 calibration.yaml），
# 降幅超过 JUDGE_NOISE 才判退步；规则通道是确定性的，任何新增违规都算退步。
JUDGE_NOISE = 1


def _render_diff(title, header, reg, imp, notes):
    lines = [title, ""] + header + ["", "## 结论", "",
             "- ❌ 退步 %d 项 · ✅ 变好 %d 项 · ℹ️ 说明 %d 项" % (len(reg), len(imp), len(notes)),
             "- 退出码语义：退步 > 0 → 1（可当回归门禁）；否则 0"]
    for section, arr in (("## ❌ 退步（新报告更差）", reg),
                         ("## ✅ 变好（新报告更好）", imp),
                         ("## ℹ️ 说明（不判退步，人工留意）", notes)):
        if arr:
            lines += ["", section, ""] + ["- %s" % x for x in arr]
    return lines


def _diff_baseline(old, new):
    reg, imp, notes = [], [], []
    header = ["- 旧：%s（%s，评测集 v%s）" % (old.get("date"), old.get("mode"), old.get("evalset_version")),
              "- 新：%s（%s，评测集 v%s）" % (new.get("date"), new.get("mode"), new.get("evalset_version"))]
    if old.get("evalset_version") != new.get("evalset_version"):
        notes.append("评测集版本不同（v%s → v%s）：评分标准变过，对比仅供参考（升版本应重跑基线）"
                     % (old.get("evalset_version"), new.get("evalset_version")))
    oa, na = old.get("aggregates", {}), new.get("aggregates", {})
    if oa.get("exit_ok") != na.get("exit_ok"):
        (reg if not na.get("exit_ok") else imp).append(
            "总体结论 exit_ok：%s → %s" % (oa.get("exit_ok"), na.get("exit_ok")))
    if oa.get("discrimination_ok") != na.get("discrimination_ok"):
        (reg if not na.get("discrimination_ok") else imp).append(
            "判别力自测（负向对照）：%s → %s" % (oa.get("discrimination_ok"), na.get("discrimination_ok")))
    occ, ncc = oa.get("change_point_coverage"), na.get("change_point_coverage")
    if occ and ncc and list(occ) != list(ncc):
        (reg if ncc[0] < occ[0] else imp).append(
            "变更点覆盖：%d/%d → %d/%d" % (occ[0], occ[1], ncc[0], ncc[1]))

    ost, nst = old.get("judge_stability") or {}, new.get("judge_stability") or {}
    if ost.get("measured") and nst.get("measured") and ost.get("runs") == nst.get("runs"):
        if len(nst["unstable"]) != len(ost["unstable"]) or len(nst["flipped"]) != len(ost["flipped"]):
            notes.append("裁判稳定性（重复评 %d 轮）：不稳定 %d → %d 条、结论翻转 %d → %d 条"
                         "（只诊断裁判本身，不判退步）"
                         % (nst["runs"], len(ost["unstable"]), len(nst["unstable"]),
                            len(ost["flipped"]), len(nst["flipped"])))

    olds = {c["id"]: c for c in old.get("cases", [])}
    news = {c["id"]: c for c in new.get("cases", [])}
    for cid in list(olds) + [c for c in news if c not in olds]:
        if cid not in olds:
            notes.append("%s：新增用例（旧报告无此条，不参与对比）" % cid)
            continue
        if cid not in news:
            notes.append("%s：旧报告有、新报告没有（用例被移除或改名？人工确认是否故意）" % cid)
            continue
        o, n = olds[cid], news[cid]
        if o.get("verdict") != n.get("verdict"):
            good = n.get("verdict") in ("pass", "detected")
            (imp if good else reg).append(
                "%s 结论：%s → %s" % (cid, o.get("verdict"), n.get("verdict")))
        for rule in RULES:
            ov = set(o.get("violations", {}).get(rule, []))
            nv = set(n.get("violations", {}).get(rule, []))
            reg += ["%s / %s 新增违规：%s" % (cid, rule, m) for m in sorted(nv - ov)]
            imp += ["%s / %s 违规消除：%s" % (cid, rule, m) for m in sorted(ov - nv)]
        oj, nj = o.get("judge"), n.get("judge")
        if oj and nj:
            for d, cell in oj.items():
                if d not in nj:
                    continue
                delta = nj[d]["score"] - cell["score"]
                if delta == 0:
                    continue
                if delta <= -(JUDGE_NOISE + 1):
                    reg.append("%s / Judge %s：%s → %s（降幅超过 ±%d 抖动，判退步）"
                               % (cid, d, cell["score"], nj[d]["score"], JUDGE_NOISE))
                elif delta < 0:
                    notes.append("%s / Judge %s：%s → %s（±%d 运行间抖动，不判退步）"
                                 % (cid, d, cell["score"], nj[d]["score"], JUDGE_NOISE))
                else:
                    imp.append("%s / Judge %s：%s → %s" % (cid, d, cell["score"], nj[d]["score"]))
        elif oj and not nj:
            notes.append("%s：Judge 本次未跑（%s），只比规则通道" % (cid, n.get("judge_note", "无 key")))
        elif nj and not oj:
            notes.append("%s：Judge 本次新启用（%s），旧报告无分数可比" % (cid, n.get("judge_note", "")))
    lines = _render_diff("# 回归对比报告（登记评测）", header, reg, imp, notes)
    return lines, reg, imp


def _diff_scan(old, new):
    reg, imp, notes = [], [], []
    header = ["- 旧：%s（扫描根：%s）" % (old.get("date"), ", ".join(old.get("roots", []))),
              "- 新：%s（扫描根：%s）" % (new.get("date"), ", ".join(new.get("roots", [])))]
    of = {f["path"]: f for f in old.get("files", [])}
    nf = {f["path"]: f for f in new.get("files", [])}
    for path in list(of) + [p for p in nf if p not in of]:
        if path not in of:
            bad = nf[path].get("violations", {})
            if bad:
                reg += ["%s（新纳入扫描）/ %s：%s" % (path, r, "；".join(m))
                        for r, m in sorted(bad.items())]
            else:
                notes.append("%s：新纳入扫描，结构合规" % path)
            continue
        if path not in nf:
            notes.append("%s：不再被扫描（文件删除/移动/扫描根变化？人工确认）" % path)
            continue
        for rule in SCAN_RULES:
            ov = set(of[path].get("violations", {}).get(rule, []))
            nv = set(nf[path].get("violations", {}).get(rule, []))
            reg += ["%s / %s 新增违规：%s" % (path, rule, m) for m in sorted(nv - ov)]
            imp += ["%s / %s 违规消除：%s" % (path, rule, m) for m in sorted(ov - nv)]
    lines = _render_diff("# 回归对比报告（全仓扫描）", header, reg, imp, notes)
    return lines, reg, imp


def diff_reports(old, new):
    """对比两份 JSON 报告，返回 (markdown 行, 退步列表, 变好列表)。基线报告与扫描报告各自可比。"""
    old_scan, new_scan = old.get("mode") == "scan", new.get("mode") == "scan"
    if old_scan != new_scan:
        raise ValueError("两份报告类型不同（一份全仓扫描、一份登记评测），不能对比")
    return _diff_scan(old, new) if old_scan else _diff_baseline(old, new)


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


def build_judge_prompt(fixture, output, cfg, points=None, rule_findings=None):
    """拼裁判 prompt（独立成函数，便于零 key 自测锁住评分标准文本，见 tests）。

    points：评测集给定的变更点清单（ground truth），注入后裁判只核对这份清单、不自己拆；
    rule_findings：规则通道已检出的违规明细，作为确定性事实注入，裁判不得否认
    （v4 实测：小模型会自己编核对结论、还会断言"优先级使用 P0/P1/P2"而产物写的是"高/中"，见 bc-0005）。
    """
    dims = cfg["dimensions"]
    dim_lines = "\n".join("- %s：%s" % (d, DIM_DEFS.get(d, "按维度名含义评审")) for d in dims)
    blocks = []
    if points:
        blocks.append("【变更点清单（评测集给定的 ground truth，不要自己另拆一份）】\n"
                      + "\n".join("- %s" % p for p in points))
    else:
        blocks.append("【变更点清单（评测集给定的 ground truth，不要自己另拆一份）】\n"
                      "- 未登记：本条用例的评测集条目没写 change_points，请自行从需求原文拆出清单，"
                      "并在 coverage 的 reason 里先列出你拆到的清单再评场景充分性")
    if rule_findings:
        blocks.append("【规则通道已检出的确定性违规（机器判定，事实不可推翻；没有列出即为未发现）】\n"
                      + "\n".join("- %s" % f for f in rule_findings))
    else:
        blocks.append("【规则通道已检出的确定性违规】\n- 无（8 条规则全部通过）")
    return (
        "你是严格的测试用例质量评审员。对照需求原文评审用例产出，按 1-5 分打分"
        "（5=完全满足，4=少量可接受瑕疵，3=明显问题，2=严重问题，1=完全不符）。\n"
        "所有维度都是分数越高越好。维度定义：\n%s\n"
        "评审约定：\n"
        "1. 「实际结果」列在执行阶段才填写，设计阶段为空属正常，不算缺陷、不算幻觉。\n"
        "2. reason 必须与 score 方向一致：理由说没有问题就必须给高分。\n"
        "3. 用例文件头部的元信息（脱敏声明、样本类型标注等）不属于用例内容，不参与打分。\n"
        "4. 分工：能机器判定的事（变更点是否逐条被覆盖、列结构、优先级取值、跳转引用、"
        "敏感信息）由规则通道判，其结论已在下方给出，你不得推翻、不得重算、不得视而不见；"
        "你只评机器判不了的事（场景充分性与粒度、相关性、前后一致、有无虚构）。\n"
        "5. 格式退化不等于内容合格：只要【规则通道已检出的确定性违规】非空，"
        "coverage 与 consistency 均不得给 4 分以上；其中若列出 no_secrets（虚构凭证/内网地址），"
        "hallucination 不得给 3 分以上。\n"
        "6. reason 必须落到具体证据（哪条用例、哪个变更点、缺什么场景），"
        "禁止写\"覆盖全面\"\"符合要求\"这类没有证据的结论；也禁止编造清单里没有的变更点。\n"
        "只输出 JSON，格式 {\"维度名\": {\"score\": 数字, \"reason\": \"一句话理由\"}}。\n\n"
        "%s\n\n【需求原文】\n%s\n\n【用例产出】\n%s"
        % (dim_lines, "\n\n".join(blocks), fixture, output))


def judge(fixture, output, cfg, model, base, key, points=None, rule_findings=None):
    dims = cfg["dimensions"]
    prompt = build_judge_prompt(fixture, output, cfg, points, rule_findings)
    raw = llm_chat([{"role": "user", "content": prompt}], model, base, key)
    scores = extract_json(raw)
    for d in dims:
        if d not in scores or not isinstance(scores[d].get("score"), (int, float)):
            raise ValueError("judge 输出缺维度 %s" % d)
    return scores


# 同一份产出重复评：任一维度极差 ≥2 记「不稳定」；±1 是已知抖动（见 calibration.yaml），不算问题
JUDGE_SPREAD_ALERT = 2


def judge_repeated(fixture, output, cfg, model, base, key,
                   points=None, rule_findings=None, runs=1):
    """对同一份产出连续调 runs 次裁判，返回 (每轮分数列表, 每轮说明列表)。

    单轮失败不中断也不补分：那一轮记 None + 失败原因，稳定性只按成功的轮次算，
    成功轮次不足 2 就如实写"无法测稳定性"（不拿 1 轮冒充稳定）。
    """
    scores, notes = [], []
    for i in range(max(1, int(runs))):
        try:
            scores.append(judge(fixture, output, cfg, model, base, key, points, rule_findings))
            notes.append("run%d ok" % (i + 1))
        except Exception as e:
            scores.append(None)
            notes.append("run%d error: %s" % (i + 1, e))
    return scores, notes


def _dim_values(run, dims):
    return [run[d]["score"] for d in dims
            if isinstance(run.get(d), dict) and isinstance(run[d].get("score"), (int, float))]


def case_stability(runs, dims, threshold):
    """把一条用例的 N 轮裁判分数压成稳定性小结（runs 里允许有 None = 该轮调用失败）。

    看三件事：① 每个维度的极差（≥JUDGE_SPREAD_ALERT 记不稳定）；② 各轮四维均分；
    ③ 结论翻转——同一份产出有时过线有时不过线，说明这条的 Judge 结论单跑不可采信。
    """
    ok = [r for r in runs if isinstance(r, dict)]
    st = {"runs_requested": len(runs), "runs_scored": len(ok),
          "runs_failed": len(runs) - len(ok), "dimensions": {}, "means": [],
          "pass_runs": 0, "spread_max": 0, "unstable": [], "flipped": None,
          "pass_at_n": None}
    if not ok:
        return st
    for d in dims:
        vals = [r[d]["score"] for r in ok if isinstance(r.get(d), dict)
                and isinstance(r[d].get("score"), (int, float))]
        if not vals:
            continue
        spread = max(vals) - min(vals)
        st["dimensions"][d] = {"values": vals, "mean": round(sum(vals) / float(len(vals)), 2),
                               "min": min(vals), "max": max(vals), "spread": spread}
        st["spread_max"] = max(st["spread_max"], spread)
        if spread >= JUDGE_SPREAD_ALERT:
            st["unstable"].append("%s 极差 %d（%s）"
                                  % (d, spread, "→".join(str(v) for v in vals)))
    for r in ok:
        vals = _dim_values(r, dims)
        if len(vals) != len(dims):
            continue                      # 该轮维度不全，不进均分统计（不猜缺的那维）
        mean = sum(vals) / float(len(vals))
        st["means"].append(round(mean, 2))
        if mean >= threshold:
            st["pass_runs"] += 1
    if st["means"]:
        st["pass_at_n"] = "%d/%d" % (st["pass_runs"], len(st["means"]))
        st["flipped"] = 0 < st["pass_runs"] < len(st["means"])
    return st


def judge_stability(results, dims, threshold):
    """汇总所有用例的重复评结果。裁判没跑 / 只跑一轮 / 轮次不足都如实说明，不编稳定性数字。"""
    runs_req = max([len(c.get("judge_runs") or []) for c in results] or [0])
    measured, unstable, flipped, insufficient, table = [], [], [], [], []
    for c in results:
        runs = c.get("judge_runs") or []
        if not runs:
            continue
        st = c.get("stability") or case_stability(runs, dims, threshold)
        if st["runs_scored"] < 2:
            insufficient.append("%s：成功 %d 轮%s，不足 2 轮无法测稳定性"
                                % (c["id"], st["runs_scored"],
                                   "（失败 %d 轮）" % st["runs_failed"] if st["runs_failed"] else ""))
            continue
        measured.append(c["id"])
        table.append({"id": c["id"], "stability": st})
        if st["unstable"]:
            unstable.append("%s：%s" % (c["id"], "；".join(st["unstable"])))
        if st["flipped"]:
            flipped.append("%s：%s 轮过线（各轮均分 %s），单跑结论不可采信"
                           % (c["id"], st["pass_at_n"],
                              "/".join("%.2f" % m for m in st["means"])))
    reason = None
    if not measured:
        reason = ("裁判未跑：无 key 或未启用 Judge" if runs_req == 0
                  else "成功轮次不足 2：--runs 需 ≥2 且每轮裁判都要调用成功")
    return {"runs": runs_req, "spread_alert": JUDGE_SPREAD_ALERT, "threshold": threshold,
            "measured": measured, "table": table, "unstable": unstable,
            "flipped": flipped, "insufficient": insufficient, "reason": reason}


def render_stability(stab):
    """稳定性小节（Markdown）。裁判没跑就只写"未测"，绝不把缺数据画成"很稳定"。"""
    lines = ["## 裁判稳定性（同一产出重复评 %d 轮）" % max(stab["runs"], 1), ""]
    if not stab["measured"]:
        lines += ["- 未测：%s" % (stab["reason"] or "无可测数据"),
                  "- 稳定性不参与退出码：门禁只认规则通道，Judge 分数一律当参考。", ""]
        return lines
    lines.append("- 测了 %d 条用例 · 不稳定 %d 条 · 结论翻转 %d 条 · 轮次不足 %d 条"
                 % (len(stab["measured"]), len(stab["unstable"]),
                    len(stab["flipped"]), len(stab["insufficient"])))
    lines.append("- 判定口径：任一维度极差 ≥%d 记不稳定（±1 是已知运行间抖动）；"
                 "各轮四维均分有过有不过记「结论翻转」" % stab["spread_alert"])
    lines.append("")
    lines.append("| case | 通过轮次 | 各轮均分 | 最大极差 | 维度分数（min~max） |")
    lines.append("|:---|:---|:---|:---|:---|")
    for row in stab["table"]:
        cid, st = row["id"], row["stability"]
        dims_txt = "；".join("%s %s~%s" % (d, v["min"], v["max"])
                             for d, v in sorted(st["dimensions"].items()))
        lines.append("| %s | %s | %s | %d | %s |"
                     % (cid, st["pass_at_n"],
                        "/".join("%.2f" % m for m in st["means"]),
                        st["spread_max"], dims_txt))
    if stab["unstable"]:
        lines += ["", "**不稳定明细**（需人工复批，别拿单轮分数下结论）：", ""]
        lines += ["- %s" % u for u in stab["unstable"]]
    if stab["flipped"]:
        lines += ["", "**结论翻转明细**（同一份产出重复评忽过忽不过）：", ""]
        lines += ["- %s" % f for f in stab["flipped"]]
    if stab["insufficient"]:
        lines += ["", "**轮次不足**：", ""]
        lines += ["- %s" % i for i in stab["insufficient"]]
    lines += ["", "> 稳定性只诊断裁判本身，**不参与退出码**；门禁仍只认规则通道。", ""]
    return lines


CONTRACT_CAPS = {
    "format_columns":     [("consistency", 3)],
    "priority_valid":     [("consistency", 3)],
    "traceability":       [("consistency", 3)],
    "no_jump_refs":       [("consistency", 3)],
    "expected_non_empty": [("consistency", 3)],
    "change_section":     [("coverage", 3)],
    "coverage":           [("coverage", 3)],
    "no_secrets":         [("hallucination", 2)],
}


DIM_RULES = {}
for _rule, _caps in CONTRACT_CAPS.items():
    for _dim, _cap in _caps:
        DIM_RULES.setdefault(_dim, []).append(_rule)


def judge_agreement(cases):
    """裁判分数 × 规则通道结论交叉核对，返回矛盾率与明细（纯函数，零 key 可测/可回溯旧报告）。

    两个方向都查：
      宽松矛盾 = 规则检出违规、裁判却给了高于上限的分（放过退步，bc-0004/bc-0005 那类）；
      反向可疑 = 规则通道全干净、裁判却给某维度 ≤2 分（可能误判，需人工复批）。
    裁判没跑（无 key）或调用失败的用例计入 uncheckable，不进分母——不拿缺数据凑指标。

    计数单位是「规则违规 × 它映射的裁判维度」：一条用例同时违反 4 条契约类规则就贡献 4 个
    可核对项（每个都要求 consistency 不高于 3）。所以分母随违规数增长，读数字时要知道这点。
    """
    items, uncheckable, strict = [], [], []
    checkable = 0
    for c in cases:
        j = c.get("judge")
        violated = [r for r in CONTRACT_CAPS if (c.get("violations") or {}).get(r)]
        if not j:
            if violated:
                uncheckable.append("%s：裁判未跑或调用失败（%s），%s 无法核对"
                                   % (c["id"], c.get("judge_note", ""), "/".join(violated)))
            continue
        for rule in violated:
            msgs = c["violations"][rule]
            for dim, cap in CONTRACT_CAPS[rule]:
                cell = j.get(dim)
                if not isinstance(cell, dict) or "score" not in cell:
                    continue
                checkable += 1
                if cell["score"] > cap:
                    items.append({
                        "case": c["id"], "dimension": dim, "score": cell["score"],
                        "cap": cap, "rule": rule, "evidence": msgs[0],
                        "reason": (cell.get("reason") or "")[:70],
                    })
        if c.get("rule_pass"):
            for dim, cell in j.items():
                if isinstance(cell, dict) and cell.get("score", 5) <= 2:
                    strict.append("%s / %s=%s：规则通道 8 项全过，裁判却给低分（理由：%s）"
                                  % (c["id"], dim, cell["score"], (cell.get("reason") or "")[:60]))
        else:
            # 规则通道有违规时，只查"没被任何规则点到的维度"：裁判在那里给 ≤2 分就是无证据压分
            # （v6 实测：收紧 hallucination 定义后，裁判把"账号 A"这类抽象占位当成虚构凭证打了 1 分）
            fired = set(violated)
            for dim, rules in DIM_RULES.items():
                cell = j.get(dim)
                if not isinstance(cell, dict) or not isinstance(cell.get("score"), (int, float)):
                    continue
                if cell["score"] <= 2 and not (fired & set(rules)):
                    strict.append("%s / %s=%s：规则通道没检出 %s 类违规，裁判却判低分（理由：%s）"
                                  % (c["id"], dim, cell["score"], "/".join(rules),
                                     (cell.get("reason") or "")[:60]))
    return {
        "checkable": checkable,
        "contradictions": len(items),
        "contradiction_rate": (len(items) / checkable) if checkable else None,
        "items": items,
        "strict_flags": strict,
        "uncheckable": uncheckable,
    }


def render_agreement(agg):
    """把一致性核对结果渲染成报告小节（独立成函数，零 key 可测）。"""
    lines = ["## 裁判-规则一致性（自动核对，不等于人工校准）", ""]
    if not agg["checkable"] and not agg["uncheckable"]:
        lines.append("（本次无可核对项：规则通道没检出契约类违规，或裁判未跑）")
        return lines
    if agg["contradiction_rate"] is None:
        lines.append("- 可核对 0 项 · 矛盾 0 项 · 矛盾率 —（分母为 0，不算指标）")
    else:
        lines.append("- 可核对 %d 项 · 矛盾 %d 项 · **矛盾率 %.0f%%**"
                     "（裁判给分高于规则结论允许的上限）"
                     % (agg["checkable"], agg["contradictions"],
                        agg["contradiction_rate"] * 100))
    if agg["uncheckable"]:
        lines.append("- 无法核对 %d 项（裁判未跑/调用失败，不进分母）" % len(agg["uncheckable"]))
    if agg["strict_flags"]:
        lines.append("- 反向可疑 %d 项（裁判给 ≤2 分但规则通道没有对应证据，需人工复批）"
                     % len(agg["strict_flags"]))
    if agg["items"]:
        lines += ["", "| case | 维度 | 裁判分 | 上限 | 规则通道的确定性证据 | 裁判理由 |",
                  "|:---|:---|:---|:---|:---|:---|"]
        for it in agg["items"]:
            lines.append("| %s | %s | %s | ≤%d | %s：%s | %s |" % (
                it["case"], it["dimension"], it["score"], it["cap"],
                it["rule"], it["evidence"][:38], it["reason"][:38]))
    if agg["strict_flags"]:
        lines.append("")
    for s in agg["strict_flags"]:
        lines.append("- %s" % s)
    lines += ["", "> 这是「裁判有没有自相矛盾」的自动体检：矛盾率高 = 裁判在放过规则抓到的问题，",
              "> 所以门禁只认规则通道、Judge 分数仅作参考；judge-人工一致率另见 calibration.yaml。"]
    return lines


def agreement_report(paths):
    """对已存档的 JSON 报告离线重算一致性（可跨评测集版本对比裁判可靠性）。"""
    rows, details = [], []
    for p in paths:
        rep = json.loads(Path(p).read_text(encoding="utf-8"))
        if "cases" not in rep:
            raise ValueError("%s 不是登记评测报告（缺 cases），扫描报告没有裁判分数" % p)
        agg = judge_agreement(rep["cases"])
        rate = "—" if agg["contradiction_rate"] is None else "%.0f%%" % (
            agg["contradiction_rate"] * 100)
        rows.append((Path(p).name, rep.get("evalset_version", "?"), rep.get("mode", "?"),
                     agg["checkable"], agg["contradictions"], rate,
                     len(agg["strict_flags"]), len(agg["uncheckable"])))
        if agg["items"] or agg["strict_flags"]:
            details.append("### %s" % Path(p).name)
            details += ["- 矛盾：%s / %s=%s（上限 ≤%d）｜规则证据：%s｜裁判理由：%s"
                        % (it["case"], it["dimension"], it["score"], it["cap"],
                           it["evidence"][:50], it["reason"][:50]) for it in agg["items"]]
            details += ["- 反向可疑：%s" % s for s in agg["strict_flags"]]
            details.append("")
    lines = ["# 裁判-规则一致性核对（离线重算已存档报告）", "",
             "| 报告 | 评测集 | 模式 | 可核对 | 矛盾 | 矛盾率 | 反向可疑 | 无法核对 |",
             "|:---|:---|:---|:---|:---|:---|:---|:---|"]
    lines += ["| %s | v%s | %s | %d | %d | %s | %d | %d |" % r for r in rows]
    if details:
        lines += ["", "## 明细", ""] + details
    lines += ["", "> 矛盾率 = 裁判给分高于「规则通道结论所允许的上限」的比例，纯自动、不需人工；",
              "> 它只说明裁判是否自相矛盾，不等于 judge-人工一致率（那需要抽样复批，见 calibration.yaml）。"]
    return lines


def resolve_key():
    for var in ("EVAL_LLM_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(var):
            return os.environ[var], var
    return None, None


POINT_CHARS = "①②③④⑤⑥⑦⑧⑨⑩"


def add_case(args):
    """一键登记：校验用例 → 需求拷入 fixtures/ → 追加 cases.yaml（文本追加以保留注释）。"""
    case_path = Path(args.add).resolve()
    if not case_path.is_file():
        sys.exit("--add: 用例文件不存在：%s" % case_path)
    if not args.fixture:
        sys.exit("--add 还需要 --fixture 指定需求文字文件（裁判要对照需求打分）")
    fixture_path = Path(args.fixture).resolve()
    if not fixture_path.is_file():
        sys.exit("--fixture: 需求文件不存在：%s" % fixture_path)
    text = case_path.read_text(encoding="utf-8")
    if not parse_case_tables(text):
        sys.exit("--add: 用例文件里没找到用例表（表头含「优先级」「预期结果」的表格）")

    # 变更点：显式 --points 优先；否则从「变更点说明」表首列自动提取
    points = [ch for ch in args.points if ch in POINT_CHARS]
    if not points:
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("|"):
                first = s.strip("|").split("|")[0].strip()
                if len(first) == 1 and first in POINT_CHARS and first not in points:
                    points.append(first)

    eval_set = Path(args.eval_set)
    cfg = yaml.safe_load(eval_set.read_text(encoding="utf-8"))
    existing = {c["id"] for c in cfg["cases"]}
    cid = args.id or ("tc-" + case_path.stem)
    cid = re.sub(r"[^\w-]+", "-", cid).strip("-") or "tc-added"
    base_id, n = cid, 2
    while cid in existing:
        cid = "%s-%d" % (base_id, n)
        n += 1

    # 需求文件：不在 evals/fixtures/ 下就拷一份进去（评测集自包含）；同名同内容复用
    fixtures_dir = EVAL_DIR / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)
    if fixture_path.parent == fixtures_dir:
        dest = fixture_path
    else:
        dest = fixtures_dir / fixture_path.name
        n = 2
        while dest.exists() and dest.read_bytes() != fixture_path.read_bytes():
            dest = fixtures_dir / ("%s-%d%s" % (fixture_path.stem, n, fixture_path.suffix))
            n += 1
        if not dest.exists():
            shutil.copyfile(fixture_path, dest)
    fixture_rel = dest.relative_to(EVAL_DIR).as_posix()
    output_rel = Path(os.path.relpath(case_path, EVAL_DIR)).as_posix()

    # 文本追加（yaml.dump 会丢掉已有注释）；追加后整体校验，失败则不写
    original = eval_set.read_text(encoding="utf-8")
    if not original.endswith("\n"):
        original += "\n"
    block = ("\n  - id: %s\n    kind: positive\n    fixture: %s\n    output: %s\n"
             "    expected_change_points: [%s]\n" % (
                 cid, fixture_rel, output_rel, ", ".join('"%s"' % p for p in points)))
    updated = original + block
    try:
        check = yaml.safe_load(updated)
        if not any(c["id"] == cid for c in check["cases"]):
            raise ValueError("新条目没落进 cases 列表（评测集的 cases: 须是最后一个顶层键）")
    except Exception as e:
        sys.exit("--add: 追加后 YAML 校验失败，文件未改动：%s" % e)
    eval_set.write_text(updated, encoding="utf-8")

    print("✅ 已登记 %s" % cid)
    print("   需求：%s" % fixture_rel)
    print("   用例：%s" % output_rel)
    print("   变更点：%s" % (" ".join(points) if points
                          else "无（覆盖度检查暂跳过，可稍后在 cases.yaml 补 expected_change_points）"))
    print("   现在跑：python3 evals/evaluate.py")
    print("⚠️ 本仓库公开：请确认需求与用例已脱敏（无实名/内网地址/账号密码）")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description="QASkillKit 双通道评测器")
    ap.add_argument("--eval-set", default=str(EVAL_DIR / "cases.yaml"))
    ap.add_argument("--out", default=str(EVAL_DIR / "reports"))
    ap.add_argument("--live", action="store_true", help="SUT 现场生成用例再评测（需 key）")
    ap.add_argument("--scan", action="store_true",
                    help="全仓结构扫描：用例目录所有 MD 跑 6 项结构规则（无需登记、无需 key）")
    ap.add_argument("--brief", action="store_true",
                    help="失败时只打印挡路条目（钩子/CI 简洁输出），不打印完整报告")
    ap.add_argument("--sut-model", default=os.environ.get("EVAL_LLM_MODEL", "glm-4-flash"))
    ap.add_argument("--judge-model", default=os.environ.get("EVAL_JUDGE_MODEL", ""))
    ap.add_argument("--add", metavar="CASE_MD",
                    help="一键登记自己的用例（配合 --fixture/--points，免手写 YAML）")
    ap.add_argument("--fixture", metavar="REQ_MD",
                    help="需求文字文件（--add 用，自动拷入 evals/fixtures/）")
    ap.add_argument("--points", default="",
                    help="变更点编号如 ①②③（--add 用；省略时从用例的变更点说明表自动提取）")
    ap.add_argument("--id", default="", help="登记 id（--add 可选，默认取用例文件名）")
    ap.add_argument("--scan-root", action="append", metavar="DIR",
                    help="自定义扫描根（--scan 用，可多次；默认项目约定目录）")
    ap.add_argument("--sut-prompt", metavar="PROMPT_MD",
                    help="A/B 回归用：替换 --live 的被测 SUT prompt（默认取评测集 meta.sut_prompt）")
    ap.add_argument("--diff", nargs=2, metavar=("OLD_JSON", "NEW_JSON"),
                    help="回归对比两份 JSON 报告：逐用例逐规则变好/变坏（零 key；退步>0 退出码 1）")
    ap.add_argument("--runs", type=int, default=1, metavar="N",
                    help="裁判稳定性：同一产出重复评 N 轮（需 key，默认 1 不测）；"
                         "输出 pass@N、各维度极差、结论翻转，不参与退出码")
    ap.add_argument("--judge-agreement", nargs="+", metavar="REPORT_JSON",
                    help="裁判-规则一致率核对：拿裁判四维分数与规则通道确定性结论交叉比对，"
                         "输出矛盾率（纯离线重算已存档报告，零 key）")
    args = ap.parse_args()

    if args.runs < 1:
        sys.exit("--runs 必须 ≥1（1 = 只评一次、不测稳定性）")

    if args.add:
        add_case(args)

    if args.judge_agreement:
        paths = [Path(p) for p in args.judge_agreement]
        for p in paths:
            if not p.is_file():
                sys.exit("--judge-agreement: 报告不存在：%s" % p)
        try:
            print("\n".join(agreement_report(paths)))
        except ValueError as e:
            sys.exit("--judge-agreement: %s" % e)
        sys.exit(0)

    if args.diff:
        paths = [Path(p) for p in args.diff]
        for p in paths:
            if not p.is_file():
                sys.exit("--diff: 报告不存在：%s" % p)
        old = json.loads(paths[0].read_text(encoding="utf-8"))
        new = json.loads(paths[1].read_text(encoding="utf-8"))
        try:
            lines, reg, _ = diff_reports(old, new)
        except ValueError as e:
            sys.exit("--diff: %s" % e)
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / ("diff-%s-vs-%s.md" % (paths[0].stem, paths[1].stem))
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print("")
        print("报告已写入：%s" % dest)
        sys.exit(1 if reg else 0)

    if args.scan:
        roots = args.scan_root or SCAN_ROOTS
        for r in (args.scan_root or []):
            base = Path(r) if Path(r).is_absolute() else ROOT / r
            if not base.is_dir():
                sys.exit("扫描根不存在：%s" % r)
        files = scan_repo(roots)
        bad = [f for f in files if f["violations"]]
        now = datetime.datetime.now()
        stem = report_stem("scan", now)
        today = now.date().isoformat()
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        scan = {"date": today, "generated_at": now.isoformat(timespec="seconds"),
                "mode": "scan", "roots": roots, "files": files,
                "aggregates": {"files_scanned": len(files),
                               "files_violating": len(bad), "exit_ok": not bad}}
        (out_dir / (stem + ".json")).write_text(
            json.dumps(scan, ensure_ascii=False, indent=2), encoding="utf-8")
        md = ["# 全仓结构扫描报告 %s" % now.strftime("%Y-%m-%d %H:%M:%S"), "",
              "- 扫描根：%s" % ", ".join(roots),
              "- 用例文件 %d 份，违规 %d 份" % (len(files), len(bad)), ""]
        if bad:
            md.append("## 违规明细")
            md.append("")
            for f in bad:
                for rule, msgs in f["violations"].items():
                    md.append("- **%s / %s**：%s" % (f["path"], rule, "；".join(msgs)))
        else:
            md.append("（全部用例文件结构合规）")
        (out_dir / (stem + ".md")).write_text("\n".join(md) + "\n", encoding="utf-8")
        if args.brief:
            for f in bad:
                for rule, msgs in f["violations"].items():
                    print("- 全仓扫描 %s / %s：%s" % (f["path"], rule, "；".join(msgs)))
        else:
            print("\n".join(md))
            print("报告已写入：%s/%s.{md,json}" % (out_dir, stem))
        sys.exit(0 if not bad else 1)

    cfg = yaml.safe_load(Path(args.eval_set).read_text(encoding="utf-8"))
    jcfg = cfg["meta"]["judge"]
    key, key_src = resolve_key()
    base = os.environ.get("EVAL_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    judge_model = args.judge_model or args.sut_model
    if args.live and not key:
        sys.exit("--live 需要 API key（EVAL_LLM_API_KEY/GLM_API_KEY/OPENAI_API_KEY 任一）")

    # --live 的被测 prompt（SUT）：A/B 回归时用 --sut-prompt 换掉默认那份
    sut_prompt = None
    if args.live:
        sut_rel = args.sut_prompt or cfg["meta"]["sut_prompt"]
        sut_path = Path(sut_rel)
        if not sut_path.is_file():
            sut_path = EVAL_DIR / sut_rel   # 也支持相对 evals/ 目录的写法（评测集里就是这么写的）
        if not sut_path.is_file():
            sys.exit("--sut-prompt 找不到文件：%s（可写绝对路径、相对当前目录、或相对 evals/ 的路径）" % sut_rel)
        sut_prompt = sut_path.read_text(encoding="utf-8")
        print("ℹ️ 被测 SUT prompt：%s" % sut_path)

    results = []
    for case in cfg["cases"]:
        fixture = (EVAL_DIR / case["fixture"]).read_text(encoding="utf-8")
        if args.live and case["kind"] == "positive":
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
        # v5：把评测集给定的变更点清单与规则通道的确定性结论一起喂给裁判（bc-0005 治疗）
        points = (cfg.get("change_points") or {}).get(case["fixture"])
        findings = ["%s / %s：%s" % (case["id"], rule, msg)
                    for rule in RULES for msg in violations[rule]]

        judge_scores, judge_note = None, "skipped（无 API key，仅规则通道）"
        judge_runs, stability = [], None
        if key:
            # --runs N：同一产出重复评 N 轮，第 1 轮成功的分数即上表 Judge 列（保持与历史报告可比）
            judge_runs, run_notes = judge_repeated(fixture, output, jcfg, judge_model, base, key,
                                                   points, findings, args.runs)
            judge_scores = next((r for r in judge_runs if isinstance(r, dict)), None)
            failed = [n for n in run_notes if "error" in n]
            if judge_scores is None:
                judge_note = "error: %s" % (failed[0] if failed else "所有轮次均无有效分数")
            else:
                used = judge_runs.index(judge_scores) + 1
                judge_note = "model=%s" % judge_model + (
                    "" if args.runs == 1 else
                    "（取第 %d/%d 轮%s）" % (used, args.runs,
                                            "，失败 %d 轮" % len(failed) if failed else ""))
            if args.runs > 1:
                stability = case_stability(judge_runs, jcfg["dimensions"], jcfg["pass_threshold"])

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
            "judge_runs": judge_runs, "stability": stability,
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
    agreement = judge_agreement(results)   # 裁判 × 规则交叉核对（裁判没跑就是 0 可核对）
    stability = judge_stability(results, jcfg["dimensions"], jcfg["pass_threshold"])

    now = datetime.datetime.now()
    stem = report_stem("baseline", now)
    today = now.date().isoformat()
    mode = ("live" if args.live else "offline") + ("+judge" if key else "+rules-only")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "date": today, "generated_at": now.isoformat(timespec="seconds"),
        "mode": mode, "evalset_version": cfg["meta"]["version"],
        "key_source": key_src, "judge_model": judge_model if key else None,
        "cases": results,
        "judge_agreement": agreement,
        "judge_stability": stability,
        "aggregates": {
            "rule_compliance": compliance,
            "change_point_coverage": [covered_cp, total_cp],
            "discrimination_ok": discrimination,
            "exit_ok": exit_ok,
        },
    }
    (out_dir / (stem + ".json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 评测基线报告 %s（%s）" % (now.strftime("%Y-%m-%d %H:%M:%S"), mode), ""]
    md.append("- 评测集版本：%s；Judge：%s" % (cfg["meta"]["version"],
              ("启用（%s，key 来源 %s）" % (judge_model, key_src)) if key else "跳过（无 key，不伪造分数）"))
    md.append("- 判别力自测（负向对照）：%s" % ("✅ 全部检出" if discrimination else "❌ 有漏检"))
    md.append("- 变更点覆盖：%d/%d" % (covered_cp, total_cp))
    if any(r["judge"] for r in results):
        rate = agreement["contradiction_rate"]
        md.append("- 裁判-规则一致性：可核对 %d 项 · 矛盾 %d 项 · 矛盾率 %s（明细见下方小节）"
                  % (agreement["checkable"], agreement["contradictions"],
                     "—" if rate is None else "%.0f%%" % (rate * 100)))
    elif agreement["uncheckable"]:
        md.append("- 裁判-规则一致性：裁判未跑，%d 项无法核对（不拿缺数据凑指标）"
                  % len(agreement["uncheckable"]))
    if args.runs > 1:
        if stability["measured"]:
            md.append("- 裁判稳定性：重复评 %d 轮 · 测了 %d 条 · 不稳定 %d 条 · 结论翻转 %d 条"
                      "（明细见下方小节；不参与退出码）"
                      % (stability["runs"], len(stability["measured"]),
                         len(stability["unstable"]), len(stability["flipped"])))
        else:
            md.append("- 裁判稳定性：未测（%s）" % stability["reason"])
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
    if any(r["judge"] for r in results):
        md.extend(render_agreement(agreement))
        md.append("")
    if args.runs > 1:
        md.extend(render_stability(stability))
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
    (out_dir / (stem + ".md")).write_text("\n".join(md) + "\n", encoding="utf-8")

    if args.brief:
        for r in results:
            if r["kind"] == "positive" and r["verdict"] != "pass":
                if r["violations"]:
                    for rule, msgs in r["violations"].items():
                        print("- 登记评测 %s / %s：%s" % (r["id"], rule, "；".join(msgs)))
                else:
                    print("- 登记评测 %s：judge 均分低于及格线" % r["id"])
            if r["kind"] == "negative-control" and r["verdict"] != "detected":
                print("- 登记评测 %s：负向对照未全部检出，评测器自身可能坏了" % r["id"])
    else:
        print("\n".join(md[:md.index("## 规则合规率（正样本）")]))
        print("报告已写入：%s/%s.{md,json}" % (out_dir, stem))
        print("exit_ok=%s" % exit_ok)
    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()