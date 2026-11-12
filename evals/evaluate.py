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
  python3 evals/evaluate.py --out DIR       # 报告输出目录（默认 evals/reports）

报告命名：<前缀>-<日期>-<时分秒>.{md,json}，同日重跑互不覆盖（Judge 基线不会被零 key 重跑顶掉）。
--diff 退出码：0 = 无退步（可当回归门禁）；1 = 有退步。Judge 单维 ±1 视为运行间抖动不判退步
（见 calibration.yaml），降幅 ≥2 才判退步。

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
DIM_DEFS = {
    "coverage": "覆盖度：用例是否覆盖需求的全部变更点与主要场景。5=变更点全覆盖且粒度合理；仅缺个别极端边界不低于4",
    "relevance": "相关性：每条用例是否直接对应需求中的功能点或规则。5=全部直接相关",
    "consistency": "一致性：用例间格式、术语、逻辑是否一致，预期结果是否具体可验证。5=完全一致",
    "hallucination": "无幻觉程度：是否虚构需求中不存在的事实（功能、业务数据、凭证、内网地址）。5=完全无虚构，1=大量虚构；明确标注为示例/占位的测试账号不算虚构",
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


def judge(fixture, output, cfg, model, base, key):
    dims = cfg["dimensions"]
    dim_lines = "\n".join("- %s：%s" % (d, DIM_DEFS.get(d, "按维度名含义评审")) for d in dims)
    prompt = (
        "你是严格的测试用例质量评审员。对照需求原文评审用例产出，按 1-5 分打分"
        "（5=完全满足，4=少量可接受瑕疵，3=明显问题，2=严重问题，1=完全不符）。\n"
        "所有维度都是分数越高越好。维度定义：\n%s\n"
        "评审约定：\n"
        "1. 「实际结果」列在执行阶段才填写，设计阶段为空属正常，不算缺陷、不算幻觉。\n"
        "2. reason 必须与 score 方向一致：理由说没有问题就必须给高分。\n"
        "3. 用例文件头部的元信息（脱敏声明、样本类型标注等）不属于用例内容，不参与打分。\n"
        "只输出 JSON，格式 {\"维度名\": {\"score\": 数字, \"reason\": \"一句话理由\"}}。\n\n"
        "【需求原文】\n%s\n\n【用例产出】\n%s" % (dim_lines, fixture, output))
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
    ap.add_argument("--diff", nargs=2, metavar=("OLD_JSON", "NEW_JSON"),
                    help="回归对比两份 JSON 报告：逐用例逐规则变好/变坏（零 key；退步>0 退出码 1）")
    args = ap.parse_args()

    if args.add:
        add_case(args)

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
        print("\n".join(md[:12]))
        print("报告已写入：%s/%s.{md,json}" % (out_dir, stem))
        print("exit_ok=%s" % exit_ok)
    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()