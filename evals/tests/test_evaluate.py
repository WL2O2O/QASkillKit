#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测器自测（评测器也要被评测）

覆盖五块，全部零 key、离线、秒级：
1. 用例表解析（parse_case_tables）：表头识别 / 分隔行 / 空行终止 / 多表合并
2. 规则边界（rule_check）：8 条规则各自的触发与不触发边界（含正则边界：
   admin\\d{3,}、内网 IP 段 172.16-31、跳转引用四种写法）
3. 扫描逻辑（scan_repo）：无用例表的 MD 跳过 / 6 项结构规则过滤 / 不存在的根静默跳过
4. 评测集完整性：cases.yaml / badcases.yaml / calibration.yaml 结构与枚举值校验，
   引用文件存在性
5. 判别力与正样本保证：负向对照必须检出全部登记违规；正样本必须零违规
   （与运行时退出码语义一致，防止评测集或规则被改坏）
6. 报告命名（同日重跑不覆盖）与回归对比 --diff：退步/变好/抖动语义、
   Judge ±1 不判退步、扫描报告对比、类型不匹配拒绝、真实基线锚点

运行：python3 -m pytest evals/tests -q
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import evaluate  # noqa: E402

EVAL_DIR = evaluate.EVAL_DIR

HEADER = ("| 需求ID+需求名称 | 优先级 | 关联引用 | 用例类型 | 用例名称 "
          "| 前置条件 | 操作步骤 | 预期结果 | 实际结果 |")
SEP = "|:---|:---|:---|:---|:---|:---|:---|:---|:---|"


def make_table(*rows):
    return "\n".join([HEADER, SEP] + ["| " + " | ".join(r) + " |" for r in rows])


def clean_row(req="REQ-1", prio="P1", ref="变更点①", typ="功能", name="提交订单成功",
              pre="已登录商城", steps="选择商品，点击提交", exp="订单提交成功", actual=""):
    return [req, prio, ref, typ, name, pre, steps, exp, actual]


# ---------- 1. 用例表解析 ----------

class TestParseCaseTables:
    def test_basic_table(self):
        text = make_table(clean_row(), clean_row(prio="P2"))
        rows = evaluate.parse_case_tables(text)
        assert len(rows) == 2
        assert rows[0][1] == "P1" and rows[1][1] == "P2"
        assert all(len(r) == 9 for r in rows)  # 分隔行被跳过、单元格已 strip

    def test_header_must_contain_both_keywords(self):
        # 只有「优先级」没有「预期结果」的表不算用例表
        text = "| 名称 | 优先级 |\n|:---|:---|\n| a | P1 |"
        assert evaluate.parse_case_tables(text) == []

    def test_blank_line_terminates_table(self):
        text = make_table(clean_row()) + "\n\n| 孤儿 | 行 |"
        rows = evaluate.parse_case_tables(text)
        assert len(rows) == 1  # 空行后的 | 行不再收集

    def test_multiple_tables_merge_with_global_index(self):
        text = make_table(clean_row()) + "\n\n" + make_table(clean_row(prio="P0"))
        rows = evaluate.parse_case_tables(text)
        assert len(rows) == 2
        v, stats = evaluate.rule_check(text, [])
        assert stats["rows"] == 2


# ---------- 2. 规则边界 ----------

class TestRuleCheck:
    def test_clean_sample_passes_all_rules(self):
        text = "## 变更点说明\n①提交入口\n" + make_table(clean_row())
        v, stats = evaluate.rule_check(text, ["①"])
        assert all(v[r] == [] for r in evaluate.RULES)
        assert stats["covered"] == ["①"]

    def test_no_table(self):
        v, _ = evaluate.rule_check("这是一段没有用例表的说明文字", ["①"])
        assert v["format_columns"] == ["未解析到任何用例表"]
        assert v["change_section"] and v["coverage"]

    def test_wrong_column_count_skips_other_checks(self):
        row8 = clean_row()[:8]
        v, _ = evaluate.rule_check(make_table(row8), [])
        assert v["format_columns"] == ["行1 列数8≠9"]
        # 列数不对的行直接跳过，不再报优先级/追溯等其他规则
        assert all(v[r] == [] for r in evaluate.RULES if r not in ("format_columns", "change_section"))

    @pytest.mark.parametrize("prio,ok", [
        ("P0", True), ("P1", True), ("P2", True),
        ("P3", False), ("p1", False), ("P10", False), ("高", False), ("", False),
    ])
    def test_priority_boundary(self, prio, ok):
        v, _ = evaluate.rule_check(make_table(clean_row(prio=prio)), [])
        assert (v["priority_valid"] == []) is ok

    def test_traceability_empty_ref(self):
        v, _ = evaluate.rule_check(make_table(clean_row(ref="")), [])
        assert v["traceability"] == ["行1 关联引用为空"]

    def test_expected_non_empty(self):
        v, _ = evaluate.rule_check(make_table(clean_row(exp="")), [])
        assert v["expected_non_empty"] == ["行1 预期结果为空"]

    def test_coverage_missing_point(self):
        text = make_table(clean_row(ref="变更点①②"))
        v, stats = evaluate.rule_check(text, ["①", "②", "③"])
        assert v["coverage"] == ["变更点③未被任何用例覆盖"]
        assert stats["covered"] == ["①", "②"]

    @pytest.mark.parametrize("field_text,fires", [
        ("见上", True), ("同上", True), ("参见附录A", True),
        ("见 第2节", True), ("见：需求原文", True),
        ("已登录商城后台", False), ("独立可读的完整步骤", False),
    ])
    def test_jump_ref_boundary(self, field_text, fires):
        v, _ = evaluate.rule_check(make_table(clean_row(steps=field_text)), [])
        assert bool(v["no_jump_refs"]) is fires

    @pytest.mark.parametrize("field_text,fires", [
        ("输入 密码: abc123", True), ("输入 密码：abc", True),
        ("使用 admin123 登录", True), ("使用 admin12 登录", False),   # \d{3,} 边界
        ("访问 http://10.0.0.1", True), ("访问 http://192.168.1.1", True),
        ("访问 http://172.16.0.1", True), ("访问 http://172.31.255.255", True),
        ("访问 http://172.15.0.1", False), ("访问 http://172.32.0.1", False),  # IP 段边界
        ("访问 https://10.0.0.1", False),  # 现状边界：规则只拦 http://，https 内网不在拦截范围
        ("访问 https://mall.example.com", False),
    ])
    def test_secret_boundary(self, field_text, fires):
        v, _ = evaluate.rule_check(make_table(clean_row(steps=field_text)), [])
        assert bool(v["no_secrets"]) is fires

    def test_secret_checked_in_all_three_fields(self):
        for kw in ("pre", "steps", "exp"):
            v, _ = evaluate.rule_check(make_table(clean_row(**{kw: "密码: x1"})), [])
            assert v["no_secrets"], "字段 %s 未被检查" % kw

    def test_change_section_required(self):
        # ref 用 REQ-1：全文不含「变更点」三字才触发（规则按关键词存在性检查）
        v, _ = evaluate.rule_check(make_table(clean_row(ref="REQ-1")), [])
        assert v["change_section"] == ["缺少变更点说明"]

    def test_row_index_is_global_across_tables(self):
        text = (make_table(clean_row(prio="P9")) + "\n\n"
                + make_table(clean_row(prio="P8")))
        v, _ = evaluate.rule_check(text, [])
        assert v["priority_valid"] == ["行1 优先级'P9'非法", "行2 优先级'P8'非法"]


# ---------- 3. 扫描逻辑 ----------

class TestScanRepo:
    def test_scan_filters_and_skips(self, tmp_path):
        # good.md：结构干净但没有「变更点」章节——change_section 属登记评测，扫描必须过滤掉
        (tmp_path / "good.md").write_text(
            make_table(clean_row(ref="REQ-1")), encoding="utf-8")
        # bad.md：三项结构违规
        (tmp_path / "bad.md").write_text(
            make_table(clean_row(prio="P5", pre="见上", exp="")), encoding="utf-8")
        # notes.md：无用例表的说明文档，应跳过
        (tmp_path / "notes.md").write_text("# 说明\n这里没有用例表。", encoding="utf-8")

        results = evaluate.scan_repo([str(tmp_path)])
        by_name = {Path(r["path"]).name: r for r in results}
        assert set(by_name) == {"good.md", "bad.md"}          # notes.md 被跳过
        assert by_name["good.md"]["violations"] == {}          # 6 项之外（change_section）不报
        assert set(by_name["bad.md"]["violations"]) == {
            "priority_valid", "no_jump_refs", "expected_non_empty"}
        assert by_name["bad.md"]["rows"] == 1

    def test_missing_root_skipped_silently(self):
        assert evaluate.scan_repo(["/nonexistent-scan-root-xyz"]) == []

    def test_scan_rules_exclude_fixture_dependent(self):
        # 覆盖度/变更点说明依赖需求原文，不在扫描范围
        assert "coverage" not in evaluate.SCAN_RULES
        assert "change_section" not in evaluate.SCAN_RULES
        assert set(evaluate.SCAN_RULES) <= set(evaluate.RULES)

    def test_default_roots_exclude_fixtures(self):
        # evals/fixtures 的负向对照是故意写坏的，默认扫描根不得包含
        assert not any(r.startswith("evals") for r in evaluate.SCAN_ROOTS)


# ---------- 4. 评测集完整性 ----------

class TestEvalsetIntegrity:
    @pytest.fixture(scope="class")
    def cfg(self):
        return yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))

    def test_meta_and_judge_config(self, cfg):
        meta = cfg["meta"]
        assert meta["judge"]["dimensions"] == [
            "coverage", "relevance", "consistency", "hallucination"]
        assert meta["judge"]["pass_threshold"] == 4
        assert (EVAL_DIR / meta["sut_prompt"]).is_file()

    def test_cases_wellformed_and_files_exist(self, cfg):
        for c in cfg["cases"]:
            assert c["kind"] in ("positive", "negative-control"), c["id"]
            assert (EVAL_DIR / c["fixture"]).is_file(), "%s fixture 缺失" % c["id"]
            assert (EVAL_DIR / c["output"]).is_file(), "%s output 缺失" % c["id"]
            for p in c["expected_change_points"]:
                assert p in evaluate.POINT_CHARS, "%s 变更点非法: %r" % (c["id"], p)
            if c["kind"] == "negative-control":
                unknown = set(c["expect_violations"]) - set(evaluate.RULES)
                assert not unknown, "%s 登记了不存在的规则: %s" % (c["id"], unknown)

    def test_has_discrimination_sample(self, cfg):
        kinds = [c["kind"] for c in cfg["cases"]]
        assert "negative-control" in kinds and "positive" in kinds

    def test_badcases_schema(self):
        bc = yaml.safe_load((EVAL_DIR / "badcases.yaml").read_text(encoding="utf-8"))
        fields = set(bc["schema"]["fields"])
        status_enum = set(bc["schema"]["status_enum"])
        root_causes = {"prompt", "model", "tool", "knowledge", "evalset"}
        for e in bc["entries"]:
            assert set(e.keys()) == fields, "bc 条目字段与 schema 不一致: %s" % e["id"]
            assert e["status"] in status_enum
            assert e["root_cause"] in root_causes
            # 人工确认制：confirmed_by 不得为空
            assert e["confirmed_by"], "%s 缺人工确认" % e["id"]

    def test_calibration_schema(self):
        cal = yaml.safe_load((EVAL_DIR / "calibration.yaml").read_text(encoding="utf-8"))
        fields = set(cal["schema"]["fields"])
        for e in cal["entries"]:
            assert set(e.keys()) == fields, "cal 条目字段与 schema 不一致: %s" % e["id"]
            assert e["agreed"] <= e["sample_size"]
            assert e["agreement"] == pytest.approx(e["agreed"] / e["sample_size"])


# ---------- 5. 判别力与正样本保证（与退出码语义一致） ----------

class TestDiscrimination:
    @pytest.fixture(scope="class")
    def cfg(self):
        return yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))

    def test_negative_control_fully_detected(self, cfg):
        for c in cfg["cases"]:
            if c["kind"] != "negative-control":
                continue
            output = (EVAL_DIR / c["output"]).read_text(encoding="utf-8")
            v, _ = evaluate.rule_check(output, c["expected_change_points"])
            detected = {r for r in evaluate.RULES if v[r]}
            missing = set(c["expect_violations"]) - detected
            assert not missing, "%s 漏检规则: %s（评测器判别力坏了）" % (c["id"], missing)

    def test_positives_zero_violation(self, cfg):
        for c in cfg["cases"]:
            if c["kind"] != "positive":
                continue
            output = (EVAL_DIR / c["output"]).read_text(encoding="utf-8")
            v, _ = evaluate.rule_check(output, c["expected_change_points"])
            bad = {r: msgs for r, msgs in v.items() if msgs}
            assert not bad, "%s 出现违规（正样本保证被破坏）: %s" % (c["id"], bad)


# ---------- 6. 工具函数 ----------

class TestExtractJson:
    def test_plain(self):
        assert evaluate.extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert evaluate.extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_embedded_in_prose(self):
        assert evaluate.extract_json('评分如下：{"a": 1} 完毕') == {"a": 1}

    def test_invalid_raises(self):
        with pytest.raises(json.JSONDecodeError):
            evaluate.extract_json("这不是 JSON")


class TestResolveKey:
    VARS = ("EVAL_LLM_API_KEY", "GLM_API_KEY", "OPENAI_API_KEY")

    def test_no_key(self, monkeypatch):
        for v in self.VARS:
            monkeypatch.delenv(v, raising=False)
        assert evaluate.resolve_key() == (None, None)

    def test_single_key(self, monkeypatch):
        for v in self.VARS:
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("GLM_API_KEY", "k-test")
        assert evaluate.resolve_key() == ("k-test", "GLM_API_KEY")

    def test_priority_order(self, monkeypatch):
        monkeypatch.setenv("EVAL_LLM_API_KEY", "k-first")
        monkeypatch.setenv("GLM_API_KEY", "k-second")
        monkeypatch.setenv("OPENAI_API_KEY", "k-third")
        assert evaluate.resolve_key() == ("k-first", "EVAL_LLM_API_KEY")


# ---------- 7. 报告命名（同日重跑不覆盖） ----------

class TestReportStem:
    def test_format(self):
        import datetime as dt
        stem = evaluate.report_stem("baseline", dt.datetime(2026, 11, 13, 9, 5, 3))
        assert stem == "baseline-2026-11-13-090503"

    def test_same_day_different_seconds_no_collision(self):
        import datetime as dt
        a = evaluate.report_stem("baseline", dt.datetime(2026, 11, 13, 9, 0, 0))
        b = evaluate.report_stem("baseline", dt.datetime(2026, 11, 13, 21, 30, 1))
        assert a != b  # Judge 基线不会被同日零 key 重跑顶掉


# ---------- 8. 回归对比（--diff） ----------

DIMS = ("coverage", "relevance", "consistency", "hallucination")


def judge_scores(**over):
    s = {d: {"score": 5, "reason": "ok"} for d in DIMS}
    for d, v in over.items():
        s[d]["score"] = v
    return s


def base_case(cid="tc-1", kind="positive", verdict="pass", violations=None, judge=None,
              judge_note=""):
    return {"id": cid, "kind": kind, "verdict": verdict,
            "violations": violations or {}, "judge": judge, "judge_note": judge_note}


def base_report(cases=None, version=2, mode="offline+rules-only", date="2026-11-12", **agg):
    a = {"rule_compliance": {}, "change_point_coverage": [8, 8],
         "discrimination_ok": True, "exit_ok": True}
    a.update(agg)
    return {"date": date, "mode": mode, "evalset_version": version,
            "cases": cases if cases is not None else [], "aggregates": a}


def scan_report(files=None, date="2026-11-12"):
    return {"date": date, "mode": "scan", "roots": ["examples"],
            "files": files or [], "aggregates": {}}


class TestDiffReports:
    def test_identical_reports_no_change(self):
        r = base_report([base_case()])
        lines, reg, imp = evaluate.diff_reports(r, json.loads(json.dumps(r)))
        assert reg == [] and imp == []
        assert "退步 0 项" in "\n".join(lines)

    def test_new_violation_is_regression(self):
        old = base_report([base_case()])
        new = base_report([base_case(verdict="fail",
                                     violations={"priority_valid": ["行1 优先级'P5'非法"]})])
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert any("priority_valid 新增违规" in x for x in reg)
        assert any("结论：pass → fail" in x for x in reg)
        assert imp == []

    def test_fixed_violation_is_improvement(self):
        old = base_report([base_case(verdict="fail",
                                     violations={"priority_valid": ["行1 优先级'P5'非法"]})],
                          exit_ok=False)
        new = base_report([base_case()])
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == []
        assert any("违规消除" in x for x in imp)
        assert any("fail → pass" in x for x in imp)
        assert any("exit_ok" in x for x in imp)

    def test_judge_minus_one_is_noise_not_regression(self):
        old = base_report([base_case(judge=judge_scores())], mode="offline+judge")
        new = base_report([base_case(judge=judge_scores(coverage=4))], mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == []
        assert any("抖动" in x for x in lines)

    def test_judge_drop_beyond_noise_is_regression(self):
        old = base_report([base_case(judge=judge_scores())], mode="offline+judge")
        new = base_report([base_case(judge=judge_scores(hallucination=3))], mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert any("hallucination" in x and "判退步" in x for x in reg)

    def test_judge_score_up_is_improvement(self):
        old = base_report([base_case(judge=judge_scores(coverage=4))], mode="offline+judge")
        new = base_report([base_case(judge=judge_scores())], mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and any("coverage" in x for x in imp)

    def test_judge_only_in_old_becomes_note(self):
        old = base_report([base_case(judge=judge_scores())], mode="offline+judge")
        new = base_report([base_case(judge_note="skipped（无 API key，仅规则通道）")])
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and imp == []
        assert any("只比规则通道" in x for x in lines)

    def test_evalset_version_mismatch_warns(self):
        lines, reg, imp = evaluate.diff_reports(
            base_report(version=1), base_report(version=2))
        assert reg == []
        assert any("评测集版本不同" in x for x in lines)

    def test_added_and_removed_cases_are_notes(self):
        old = base_report([base_case(cid="tc-old")])
        new = base_report([base_case(cid="tc-new")])
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and imp == []
        text = "\n".join(lines)
        assert "tc-new：新增用例" in text and "tc-old：旧报告有、新报告没有" in text

    def test_negative_control_missed_is_regression(self):
        old = base_report([base_case(cid="tc-neg", kind="negative-control", verdict="detected")])
        new = base_report([base_case(cid="tc-neg", kind="negative-control", verdict="MISSED")],
                          discrimination_ok=False, exit_ok=False)
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert any("detected → MISSED" in x for x in reg)
        assert any("判别力" in x for x in reg)

    def test_coverage_drop_is_regression(self):
        lines, reg, imp = evaluate.diff_reports(
            base_report(), base_report(change_point_coverage=[7, 8]))
        assert any("变更点覆盖" in x for x in reg)

    def test_scan_new_violation_and_fix(self):
        old = scan_report([{"path": "examples/a.md", "rows": 2,
                            "violations": {"priority_valid": ["行1 优先级'P5'非法"]}}])
        new = scan_report([{"path": "examples/a.md", "rows": 2, "violations": {}},
                           {"path": "examples/b.md", "rows": 1,
                            "violations": {"no_jump_refs": ["行1 操作步骤含跳转引用"]}}])
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert any("b.md（新纳入扫描）/ no_jump_refs" in x for x in reg)
        assert any("a.md / priority_valid 违规消除" in x for x in imp)

    def test_mixed_report_types_rejected(self):
        with pytest.raises(ValueError):
            evaluate.diff_reports(base_report(), scan_report())

    def test_diff_against_real_committed_baselines(self):
        # 真实防回归锚点：11-11（v1 零 key）与 11-12（v2 offline+judge）对比不得判出退步
        rd = EVAL_DIR / "reports"
        old = json.loads((rd / "baseline-2026-11-11.json").read_text(encoding="utf-8"))
        new = json.loads((rd / "baseline-2026-11-12.json").read_text(encoding="utf-8"))
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [], "真实基线对比出现退步: %s" % reg
        assert any("评测集版本不同" in x for x in lines)  # v1 → v2 必须给出警告
