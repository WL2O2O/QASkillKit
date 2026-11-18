#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测器自测（评测器也要被评测）

覆盖九块，全部零 key、离线、秒级：
1. 用例表解析（parse_case_tables）：表头识别 / 分隔行 / 空行终止 / 多表合并
2. 规则边界（rule_check）：8 条规则各自的触发与不触发边界（含正则边界：
   admin\\d{3,}、内网 IP 段 172.16-31、跳转引用含"执行TC1操作"这类跨用例引用）
3. 扫描逻辑（scan_repo）：无用例表的 MD 跳过 / 6 项结构规则过滤 / 不存在的根静默跳过
4. 评测集完整性：cases.yaml / badcases.yaml / calibration.yaml 结构与枚举值校验，
   引用文件存在性
5. 判别力与正样本保证：负向对照必须检出全部登记违规；正样本必须零违规
   （与运行时退出码语义一致，防止评测集或规则被改坏）
6. 报告命名（同日重跑不覆盖）与回归对比 --diff：退步/变好/抖动语义、
   Judge ±1 不判退步、扫描报告对比、类型不匹配拒绝、真实基线锚点
7. 表头漂移兜底与 A/B 演示产物锚点：非标准表头按列名继续查内容（bc-0003 回归），
   evals/ab-demo/ 里 A 变体必须零违规、B 变体必须被检出
8. 裁判-规则一致率（judge_agreement）：契约上限映射 / 矛盾与反向可疑判定 /
   裁判未跑不进分母 / 报告小节渲染 / 真实存档报告锚点
9. 裁判稳定性（--runs N）：极差 ≥2 记不稳定（±1 是已知抖动）/ pass@N 与结论翻转 /
   单轮失败不补分、轮次不足如实写"无法测" / 渲染小节 / 不参与退出码 / --diff 只作说明

运行：python3 -m pytest evals/tests -q
"""
import inspect
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
        # 跨用例引用（bc-0006）：把前置条件/步骤寄托在另一条用例上
        ("执行TC1操作", True), ("执行 TC3 操作", True), ("参考用例2", True),
        ("参照用例3", True), ("复用用例 12 的前置条件", True), ("沿用TC-7", True),
        ("见用例2", True), ("同TC3 的前置条件", True), ("参见TC2", True),
        # 边界：编号标识后面必须跟编号；"执行 XX 操作"本身是正常动作
        ("已登录商城后台", False), ("独立可读的完整步骤", False),
        ("执行导出操作", False), ("执行登录", False), ("执行提交流程", False),
        ("执行用例设计", False), ("不同用例的公共前置", False),
    ])
    def test_jump_ref_boundary(self, field_text, fires):
        v, _ = evaluate.rule_check(make_table(clean_row(steps=field_text)), [])
        assert bool(v["no_jump_refs"]) is fires

    def test_cross_case_jump_ref_checked_in_both_table_paths(self):
        # bc-0006：标准 9 列表与表头漂移兜底路径都要能检出，且报对字段名
        v, _ = evaluate.rule_check(make_table(clean_row(pre="执行TC1操作")), [])
        assert v["no_jump_refs"] == ["行1 前置条件含跳转引用"]
        v, _ = evaluate.rule_check(make_drift_table(drift_row(pre="执行TC1操作")), [])
        assert v["no_jump_refs"] == ["行1 前置条件含跳转引用"]
        for kw in ("pre", "steps", "exp"):
            v, _ = evaluate.rule_check(make_table(clean_row(**{kw: "参考用例2"})), [])
            assert v["no_jump_refs"], "字段 %s 未被检查" % kw

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


# ---------- 2b. 表头漂移兜底（A/B prompt 演示发现的盲区，bc-0003） ----------
#
# 历史实现：列数≠9 的行报完 format_columns 就 continue，后面 5 项行级检查全跳过。
# 后果：被测 prompt 一改成"表头列数按需精简"，输出漂成 6 列，P3 优先级、
# 前置条件里的"同上"、缺失的关联引用列全部漏检——表格结构漂移把内容缺陷藏起来了。
# 现在：表头非标准 9 列时，按列名定位兜底检查，能查多少查多少。

DRIFT_HEADER = "| 序号 | 测试项 | 优先级 | 前置条件 | 操作步骤 | 预期结果 |"
DRIFT_SEP = "| ---- | ---- | ---- | ---- | ---- | ---- |"


def make_drift_table(*rows, header=DRIFT_HEADER):
    return "\n".join([header, DRIFT_SEP] + ["| " + " | ".join(r) + " |" for r in rows])


def drift_row(no="1", item="提交订单", prio="P1", pre="已登录商城",
              steps="点击提交", exp="订单提交成功"):
    return [no, item, prio, pre, steps, exp]


class TestHeaderDriftFallback:
    def test_standard_header_detection(self):
        std = [c.strip() for c in HEADER.strip("|").split("|")]
        assert evaluate.is_standard_header(std)
        # 第 1 列名称各团队有差异，不影响判定
        assert evaluate.is_standard_header(["需求ID+名称"] + std[1:])
        assert not evaluate.is_standard_header(std[:6])              # 列数不够
        assert not evaluate.is_standard_header(std[:1] + std[2:])    # 优先级不在第 2 列

    def test_headers_and_rows_returned_per_table(self):
        text = make_table(clean_row()) + "\n\n" + make_drift_table(drift_row())
        tables = evaluate.parse_case_tables_with_headers(text)
        assert len(tables) == 2
        assert evaluate.is_standard_header(tables[0][0])
        assert len(tables[0][1]) == 1 and len(tables[1][1]) == 1
        # parse_case_tables 行为不变：仍然是扁平的行列表
        assert len(evaluate.parse_case_tables(text)) == 2

    def test_illegal_priority_caught_in_drifted_table(self):
        v, _ = evaluate.rule_check(make_drift_table(drift_row(prio="P3")), [])
        assert v["priority_valid"] == ["行1 优先级'P3'非法"]

    @pytest.mark.parametrize("prio", ["高", "中", "低", ""])
    def test_non_p_level_priority_caught(self, prio):
        v, _ = evaluate.rule_check(make_drift_table(drift_row(prio=prio)), [])
        assert v["priority_valid"], "优先级 %r 应被判非法" % prio

    def test_jump_ref_caught_in_drifted_table(self):
        v, _ = evaluate.rule_check(make_drift_table(drift_row(pre="同上")), [])
        assert v["no_jump_refs"] == ["行1 前置条件含跳转引用"]

    def test_secret_caught_in_drifted_table(self):
        v, _ = evaluate.rule_check(make_drift_table(drift_row(steps="用 admin123 登录")), [])
        assert v["no_secrets"] and "操作步骤" in v["no_secrets"][0]

    def test_empty_expected_caught_in_drifted_table(self):
        v, _ = evaluate.rule_check(make_drift_table(drift_row(exp="")), [])
        assert v["expected_non_empty"] == ["行1 预期结果为空"]

    def test_missing_ref_column_reported_once_per_table(self):
        text = make_drift_table(drift_row(), drift_row(no="2"))
        v, _ = evaluate.rule_check(text, [])
        assert v["traceability"] == ["表头缺少关联引用列：用例无法追溯到变更点"]

    def test_ref_column_honored_when_present(self):
        header = "| 序号 | 优先级 | 关联引用 | 前置条件 | 操作步骤 | 预期结果 |"
        text = "## 变更点说明\n①入口\n" + make_drift_table(
            ["1", "P1", "①", "已登录", "点击提交", "成功"], header=header)
        v, stats = evaluate.rule_check(text, ["①"])
        assert v["coverage"] == [] and stats["covered"] == ["①"]
        assert v["change_section"] == []

    def test_row_numbering_stays_global_across_mixed_tables(self):
        text = make_table(clean_row(prio="P9")) + "\n\n" + make_drift_table(drift_row(prio="P7"))
        v, stats = evaluate.rule_check(text, [])
        assert v["priority_valid"] == ["行1 优先级'P9'非法", "行2 优先级'P7'非法"]
        assert stats["rows"] == 2

    def test_standard_table_with_short_row_keeps_old_behavior(self):
        # 标准表头 + 某行少一列：下标会错位，只报列数，不做兜底（避免误报）
        short = clean_row()[:8]
        v, _ = evaluate.rule_check(make_table(short), [])
        assert v["format_columns"] == ["行1 列数8≠9"]
        assert v["priority_valid"] == [] and v["no_jump_refs"] == []


class TestAbDemoArtifacts:
    """A/B prompt 演示的真实产物做锚点：B 变体必须被检出，A 变体必须干净。

    每次 --live 跑完，快照目录按运行时间戳落盘（cases-HHMMSS），所以一个变体
    下可能有多次运行的产物；这里遍历所有快照，任何一次 B 的退化产出都必须被抓。
    """

    AB = EVAL_DIR / "ab-demo"
    # 首轮 A/B 演示（v3 裁判）的运行时间戳，用于钉住具体锚点
    V3_A, V3_B = "cases-092720", "cases-093523"
    V4_B = "cases-170848"

    @staticmethod
    def snapshots(variant):
        return sorted(p for p in (TestAbDemoArtifacts.AB / variant).glob("cases-*") if p.is_dir())

    def test_variant_b_outputs_are_flagged(self):
        snaps = self.snapshots("b")
        assert snaps, "缺 A/B 演示产物：先跑 bash evals/ab-demo.sh"
        for snap in snaps:
            for path in sorted(snap.glob("*.md")):
                v, _ = evaluate.rule_check(path.read_text(encoding="utf-8"), ["①", "②", "③"])
                assert v["format_columns"], "%s/%s 应检出表头/列数问题" % (snap.name, path.name)
                assert v["change_section"], "%s/%s 应检出缺少变更点说明" % (snap.name, path.name)

    def test_variant_b_blind_spot_regression(self):
        # bc-0003 锚点：这三处曾被"列数≠9 就 continue"漏掉（v3 那轮的 B 产出）
        b = self.AB / "b" / self.V3_B
        v, _ = evaluate.rule_check((b / "tc-1000001-good.md").read_text(encoding="utf-8"), [])
        assert any("P3" in m for m in v["priority_valid"])
        v, _ = evaluate.rule_check((b / "tc-1000002-good.md").read_text(encoding="utf-8"), [])
        assert any("'高'" in m for m in v["priority_valid"])
        v, _ = evaluate.rule_check((b / "tc-1020256-executed.md").read_text(encoding="utf-8"), [])
        assert v["no_jump_refs"], "前置条件里的「同上」应被检出"

    def test_variant_b_v4_run_still_flagged(self):
        # v4 那轮的 B 产出：缺关联引用列 + 中文优先级也必须被抓（不能只靠 v3 快照）
        b = self.AB / "b" / self.V4_B
        assert b.is_dir(), "缺 v4 轮的 B 快照：%s" % b.name
        for path in sorted(b.glob("*.md")):
            v, _ = evaluate.rule_check(path.read_text(encoding="utf-8"), [])
            assert v["traceability"], "%s 应检出缺少关联引用列" % path.name
            assert v["format_columns"], "%s 应检出表头非标准 9 列" % path.name
        # 这轮 tc-1000001-good 用的是合法 P0/P1，另两份写成了「高/中」
        v, _ = evaluate.rule_check((b / "tc-1000002-good.md").read_text(encoding="utf-8"), [])
        assert any("'高'" in m for m in v["priority_valid"])
        v, _ = evaluate.rule_check((b / "tc-1020256-executed.md").read_text(encoding="utf-8"), [])
        assert any("'中'" in m for m in v["priority_valid"])

    def test_variant_b_cross_case_jump_refs_now_flagged(self):
        # bc-0006 锚点：v4 轮 B 产出的这份有 4 行前置条件写「执行TC1操作」，
        # 旧 JUMP_RE 只认"见/同上/参见"，整份 no_jump_refs 仍显示合规。
        # 现在必须逐行检出，且行号与表内序号对得上（行2~行5）。
        b = self.AB / "b" / self.V4_B
        text = (b / "tc-1020256-executed.md").read_text(encoding="utf-8")
        assert text.count("执行TC1操作") == 4
        v, _ = evaluate.rule_check(text, [])
        hits = sorted(m for m in v["no_jump_refs"] if "前置条件" in m)
        assert hits == ["行%d 前置条件含跳转引用" % i for i in (2, 3, 4, 5)]

    def test_variant_a_outputs_are_clean(self):
        snaps = self.snapshots("a")
        assert snaps, "缺 A/B 演示产物：先跑 bash evals/ab-demo.sh"
        for snap in snaps:
            for path in sorted(snap.glob("*.md")):
                v, _ = evaluate.rule_check(path.read_text(encoding="utf-8"), [])
                assert all(v[r] == [] for r in evaluate.RULES), "%s/%s 不该有违规：%s" % (
                    snap.name, path.name, {k: x for k, x in v.items() if x})

    def test_diff_report_records_regressions(self):
        # 首轮（v3）对比：A 干净 → B 退化，exit_ok 由 True 翻 False
        first = self.AB / "diff-baseline-2026-11-13-092720-vs-baseline-2026-11-13-093523.md"
        text = first.read_text(encoding="utf-8")
        assert "❌ 退步" in text and "exit_ok：True → False" in text

    def test_every_diff_report_has_regressions(self):
        diffs = sorted(self.AB.glob("diff-*.md"))
        assert diffs, "缺 A/B 对比报告：先跑 bash evals/ab-demo.sh"
        for path in diffs:
            assert "❌ 退步" in path.read_text(encoding="utf-8"), "%s 应记录退步项" % path.name


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
        root_causes = {"prompt", "model", "tool", "knowledge", "evalset", "evaluator"}
        for e in bc["entries"]:
            assert set(e.keys()) == fields, "bc 条目字段与 schema 不一致: %s" % e["id"]
            assert e["status"] in status_enum
            assert e["root_cause"] in root_causes
            # 人工确认制：只有 open（AI 草稿）允许 confirmed_by 为空；
            # 一旦进入 confirmed/fixed/wontfix，必须有人名——AI 不能自己宣布修好了
            if e["status"] == "open":
                assert e["fix_ref"] is None or "待确认" in str(e["fix_ref"]), (
                    "%s 是 open 草稿，fix_ref 不得声称已修复" % e["id"])
            else:
                assert e["confirmed_by"], "%s 缺人工确认" % e["id"]

    def test_calibration_schema(self):
        cal = yaml.safe_load((EVAL_DIR / "calibration.yaml").read_text(encoding="utf-8"))
        fields = set(cal["schema"]["fields"])
        for e in cal["entries"]:
            assert set(e.keys()) == fields, "cal 条目字段与 schema 不一致: %s" % e["id"]
            assert e["agreed"] <= e["sample_size"]
            assert e["agreement"] == pytest.approx(e["agreed"] / e["sample_size"])

    def test_cal_0003_records_human_item_by_item_review(self):
        # v8 的 161427 由本人在对话中逐项复批（不是 AI 复核、也不是抽检背书）：
        # 分数级 12/14，严格级 8/14——两级必须同时落盘，防止有人只引用 85.7%
        cal = yaml.safe_load((EVAL_DIR / "calibration.yaml").read_text(encoding="utf-8"))
        e = next(x for x in cal["entries"] if x["id"] == "cal-0003")
        assert (e["sample_size"], e["agreed"]) == (14, 12)
        assert "161427" in e["scope"]
        assert "逐项" in e["reviewer"] and "WL2O2O" in e["reviewer"]
        assert "严格级" in e["note"] and "8/14" in e["note"]
        assert "定向抽样" in e["note"]

    def test_cal_0004_is_labeled_authorized_batch_not_human_review(self):
        # 十三份的"授权口径代批"：数字必须落盘，但 reviewer/note 必须写明 AI 代判、本人未逐项阅读——
        # 防止日后被引用成"人工逐项复批"（这 212 项是授权 + 口径，不是人读的）
        cal = yaml.safe_load((EVAL_DIR / "calibration.yaml").read_text(encoding="utf-8"))
        e = next(x for x in cal["entries"] if x["id"] == "cal-0004")
        assert (e["sample_size"], e["agreed"]) == (212, 171)
        assert "代批" in e["reviewer"] and "未逐项阅读" in e["reviewer"]
        assert "WL2O2O" in e["reviewer"]
        assert "不是人工逐项复批" in e["note"] and "372" in e["note"]
        assert "严格级" in e["note"] and "146/212" in e["note"]
        assert "不可混算" in e["note"]
        # 明细必须和汇总对得上：审计文件里的合计行写死 212/41/17/8，改数字就得同时改两处
        audit = (EVAL_DIR / "reviews/corpus-audit-2026-11-18.md").read_text(encoding="utf-8")
        assert "可核对 212，不认可 41，反向可疑 17，编造举证 8" in audit
        assert "不是人工逐项阅读" in audit and "372" in audit


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

    def test_every_rule_has_isolated_negative(self, cfg):
        # v3 设计：8 条规则每条都有一发"单规则隔离弹"（expect_violations 只登记一条）
        isolated = {c["expect_violations"][0] for c in cfg["cases"]
                    if c["kind"] == "negative-control" and len(c["expect_violations"]) == 1}
        assert isolated == set(evaluate.RULES), "缺隔离负向对照的规则: %s" % (
            set(evaluate.RULES) - isolated)

    def test_isolated_negatives_violate_only_target_rule(self, cfg):
        # 隔离纯度：单规则负向对照必须"只坏一处"，多触发任何规则都算设计被破坏
        for c in cfg["cases"]:
            if c["kind"] != "negative-control" or len(c["expect_violations"]) != 1:
                continue
            output = (EVAL_DIR / c["output"]).read_text(encoding="utf-8")
            v, _ = evaluate.rule_check(output, c["expected_change_points"])
            detected = {r for r in evaluate.RULES if v[r]}
            assert detected == set(c["expect_violations"]), "%s 隔离不纯: 实际触发 %s" % (
                c["id"], detected)


# ---------- 6. 工具函数 ----------

class TestJudgeRubric:
    """锁住裁判的评分标准文本（v4 收紧 bc-0004 → v5 分工重划 bc-0005）：零 key、不联网，只查 prompt 拼装。"""

    @pytest.fixture(scope="class")
    def jcfg(self):
        cfg = yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))
        return cfg["meta"]["judge"]

    def test_evalset_version_bumped_for_rubric_change(self, jcfg):
        # 评分标准变了就得升版本（三件套：升版本 + 重跑基线 + 重新校准）
        assert jcfg is not None
        meta = yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))["meta"]
        assert meta["version"] >= 8

    def test_coverage_defers_mechanical_check_to_rules(self):
        # v5：coverage 不再让裁判自己拆清单/数覆盖，只评场景充分性与粒度（bc-0005 治疗）
        d = evaluate.DIM_DEFS["coverage"]
        assert "变更点清单" in d and "不重复判" in d
        assert "边界值" in d and "异常场景" in d
        for score in ("5=", "4=", "3=", "2=", "1="):
            assert score in d, "coverage 缺 %s 档定义" % score
        assert "禁止只写" in d   # reason 必须给具体缺口，不许套话

    def test_consistency_covers_output_contract(self):
        d = evaluate.DIM_DEFS["consistency"]
        # 契约项交给规则通道判，但裁判不得推翻其结论，且有明确降分上限
        assert "P3" in d and "同上" in d and "关联引用" in d
        assert "不得否认" in d and "不得高于 3" in d
        # v7（bc-0008 治疗）：堵住"承认事实但重新定义口径"的逃逸路径
        assert "内容契约的一部分" in d
        assert "这是格式问题" in d and "免于降分" in d
        assert "重新定义口径" in d

    def test_change_points_ground_truth_matches_expected(self):
        # 喂给裁判的清单必须与规则通道用的 expected_change_points 同编号，否则两通道各说各话
        cfg = yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))
        cp = cfg["change_points"]
        for c in cfg["cases"]:
            assert c["fixture"] in cp, "%s 的 fixture 缺 change_points 清单" % c["id"]
            symbols = [x[0] for x in cp[c["fixture"]]]
            assert symbols == c["expected_change_points"], (
                "%s 清单编号 %s 与 expected_change_points %s 不一致"
                % (c["id"], symbols, c["expected_change_points"]))
            assert all(len(x) > 6 for x in cp[c["fixture"]]), "清单条目应含描述，不能只有编号"

    def test_judge_prompt_injects_checklist_and_rule_findings(self, jcfg):
        p = evaluate.build_judge_prompt(
            "需求原文X", "用例产出Y", jcfg,
            points=["① 变更点一", "② 变更点二"],
            rule_findings=["tc-x / coverage：变更点②未被任何用例覆盖"])
        assert "【变更点清单" in p and "① 变更点一" in p and "② 变更点二" in p
        assert "不要自己另拆" in p
        assert "【规则通道已检出的确定性违规" in p
        assert "变更点②未被任何用例覆盖" in p and "不得推翻" in p

    def test_judge_prompt_without_findings_says_clean(self, jcfg):
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg, points=["① a"])
        assert "无（8 条规则全部通过）" in p

    def test_judge_prompt_without_checklist_falls_back(self, jcfg):
        # --add 登记的用例可能还没写 change_points：必须显式告诉裁判"未登记"，不能留空让它瞎猜
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg)
        assert "未登记" in p and "自行从需求原文拆出清单" in p

    def test_judge_prompt_injects_machine_facts(self, jcfg):
        # v8：规则通道"确认没问题"也要当事实注入，否则裁判照样编列数错误/编缺口
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg, points=["① a"],
                                        facts=["列结构：未检出任何列数/表头问题（用例表为标准 9 列）"])
        assert "【规则通道确认无问题的机械事实" in p
        assert "未检出任何列数/表头问题" in p and "不可推翻" in p

    def test_machine_facts_declare_clean_format_mapping_and_abstract_refs(self):
        text = make_table(clean_row(ref="①②", pre="使用账号 A 登录"), clean_row(ref="②"))
        v, _ = evaluate.rule_check(text, ["①", "②"])
        facts = " ".join(evaluate.machine_facts(text, v, ["① 入口", "② 打码"]))
        assert "未检出任何列数/表头问题" in facts
        assert "变更点① 已被这些用例引用" in facts and "《提交订单成功》" in facts
        assert "账号 A" in facts and "不是虚构凭证" in facts

    def test_machine_facts_silent_about_format_when_rules_report_it(self):
        v = {r: [] for r in evaluate.RULES}
        v["format_columns"] = ["行1 列数8≠9"]
        facts = " ".join(evaluate.machine_facts(make_table(clean_row()), v, []))
        assert "未检出任何列数" not in facts

    def test_judge_forwards_checklist_and_findings(self, jcfg, monkeypatch):
        # 真联网跑不了，但 prompt 拼装必须带上清单与规则结论：截住 llm_chat 看它收到什么
        seen = {}

        def fake_llm_chat(messages, model, base, key):
            seen["prompt"] = messages[0]["content"]
            return json.dumps({d: {"score": 5, "reason": "r"} for d in jcfg["dimensions"]})

        monkeypatch.setattr(evaluate, "llm_chat", fake_llm_chat)
        evaluate.judge("需求X", "产出Y", jcfg, "m", "http://b", "k",
                       points=["① 清单条目"], rule_findings=["tc / coverage：变更点①未被任何用例覆盖"])
        assert "① 清单条目" in seen["prompt"]
        assert "变更点①未被任何用例覆盖" in seen["prompt"]

    def test_main_wires_change_points_from_evalset(self):
        # 防回归：主流程必须从 cases.yaml 的 change_points 取清单、并把违规明细与机械事实传给裁判
        src = inspect.getsource(evaluate.main)
        assert 'cfg.get("change_points")' in src
        assert "points, findings" in src
        assert "machine_facts(" in src and "args.runs, facts" in src

    def test_judge_prompt_carries_dims_and_conventions(self, jcfg):
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg)
        for dim in jcfg["dimensions"]:
            assert "- %s：" % dim in p, "prompt 缺维度 %s" % dim
        for rule in ("格式退化不等于内容合格", "分工", "只输出 JSON",
                     "实际结果」列在执行阶段才填写", "禁止编造清单里没有的变更点"):
            assert rule in p, "prompt 缺评审约定：%s" % rule
        assert "需求原文X" in p and "用例产出Y" in p

    def test_rubric_change_is_documented(self):
        bc = yaml.safe_load((EVAL_DIR / "badcases.yaml").read_text(encoding="utf-8"))
        e4 = next(x for x in bc["entries"] if x["id"] == "bc-0004")
        assert e4["status"] == "fixed" and e4["confirmed_by"]
        assert "v3 → v4" in e4["fix_ref"]
        # v4 首轮未达标、v5 同一验收达标，两段证据都必须落盘（不许只写"已修复"）
        assert "221550" in e4["fix_ref"] and "1/2/2" in e4["fix_ref"]
        # v5 治疗（bc-0005）同样标 fixed，且如实写明首轮残留的 1 项矛盾（不许写成全部归零）
        e5 = next(x for x in bc["entries"] if x["id"] == "bc-0005")
        assert e5["confirmed_by"] and e5["status"] == "fixed"
        assert "v4 → v5" in e5["fix_ref"] and "2.75" in e5["fix_ref"]
        assert "1/28" in e5["fix_ref"] and "bc-0007" in e5["fix_ref"]

    def test_v6_verification_and_human_confirmation_are_recorded(self):
        # bc-0007 的 v6 实测数字必须落盘；2026-11-18 根因与「已修复」判定由 WL2O2O 签字 → fixed，
        # 但"人工抽样复批未做"这句必须留在条内（fixed 说的是口径修好，不是裁判被验证可信）；
        # bc-0008/bc-0009 的根因已由 WL2O2O 确认：前者四条验收全达标标 fixed，
        # 后者只达标一半，只能标 confirmed（不许把"半治好"写成 fixed）
        bc = yaml.safe_load((EVAL_DIR / "badcases.yaml").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in bc["entries"]}
        e7 = by_id["bc-0007"]
        assert "233955" in e7["fix_ref"] and "5 → 2" in e7["fix_ref"]   # 实测证据落盘
        assert e7["status"] == "fixed" and "WL2O2O" in e7["confirmed_by"]
        assert "标 fixed" in e7["fix_ref"] and "人工抽样复批仍未做" in e7["fix_ref"]
        assert e7["root_cause"] == "evalset" and e7["dimension"].startswith("hallucination")
        assert "v5 → v6" in e7["fix_ref"]

        e8 = by_id["bc-0008"]
        assert e8["status"] == "fixed" and "WL2O2O" in e8["confirmed_by"]
        assert e8["root_cause"] == "evalset" and "tc-neg-format" in e8["case_id"]
        assert "consistency" in e8["dimension"]
        assert "075449" in e8["fix_ref"] and "0%" in e8["fix_ref"]       # v7 达标证据落盘
        assert "验收标准" in e8["fix_ref"]

        e9 = by_id["bc-0009"]
        # 2026-11-18 v8 复核后由 WL2O2O 签字标 fixed：三条验收在注入机械事实后达成（160734/161427）
        assert e9["status"] == "fixed" and "WL2O2O" in e9["confirmed_by"]
        assert e9["root_cause"] == "evalset" and "tc-neg-priority" in e9["case_id"]
        assert "hallucination" in e9["dimension"]
        assert "只达标一半" in e9["fix_ref"] and "075449" in e9["fix_ref"]
        assert "161427" in e9["fix_ref"] and "标 fixed" in e9["fix_ref"]
        # bc-0009 是 v6 收紧后的过度纠正：修法不得把 bc-0007 治好的又放回去
        assert "仍 ≤2" in e9["fix_ref"]

    def test_2026_11_18_confirmations_are_recorded(self):
        # 人工确认制的现场记录：bc-0006（evaluator 漏检成立）与 bc-0012（v8 上限退化）同一天签字
        bc = yaml.safe_load((EVAL_DIR / "badcases.yaml").read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in bc["entries"]}
        e6 = by_id["bc-0006"]
        assert e6["status"] == "fixed" and "WL2O2O" in e6["confirmed_by"]
        assert e6["root_cause"] == "evaluator"
        assert "CROSS_CASE_RE" in e6["fix_ref"] and "标 fixed" in e6["fix_ref"]
        e12 = by_id["bc-0012"]
        # 根因认 model，但修法未落地 → 只能 confirmed，不许写 fixed
        assert e12["status"] == "confirmed" and "WL2O2O" in e12["confirmed_by"]
        assert e12["root_cause"] == "model"
        assert "score = min(score, cap)" in e12["fix_ref"]
        assert "不得改 fixed" in e12["fix_ref"]
        # bc-0010 / bc-0011 本轮维持 confirmed（用户 2026-11-18 决定保持）
        for cid in ("bc-0010", "bc-0011"):
            assert by_id[cid]["status"] == "confirmed", cid
        # bc-0007 是最后一条 open 的：签字后 badcases 里不再有 open 项
        assert [x["id"] for x in bc["entries"] if x["status"] == "open"] == []
        e7 = by_id["bc-0007"]
        assert e7["status"] == "fixed" and "WL2O2O" in e7["confirmed_by"]

    def test_fixed_entries_always_carry_human_confirmation(self):
        # 人工确认制的硬约束：任何 confirmed/fixed 条目都必须有 confirmed_by，
        # 且 AI 起草的 open 条目不许偷偷带上确认人（防止"AI 自己给自己盖章"）
        bc = yaml.safe_load((EVAL_DIR / "badcases.yaml").read_text(encoding="utf-8"))
        for e in bc["entries"]:
            if e["status"] in ("confirmed", "fixed", "wontfix"):
                assert e["confirmed_by"], "%s 标了 %s 却没有人工确认" % (e["id"], e["status"])
            else:
                assert e["status"] == "open" and e["confirmed_by"] is None, e["id"]


    def test_hallucination_binds_to_rule_channel(self):
        # v6：hallucination 必须以规则通道的 no_secrets 结论为准（bc-0007 治疗）
        d = evaluate.DIM_DEFS["hallucination"]
        assert "no_secrets" in d and "不得高于 2" in d
        assert "未虚构" in d and "不合格理由" in d   # 明文禁止 v5 那种"未虚构"却给 5 分的理由
        for score in ("5=", "4=", "3=", "2=", "1="):
            assert score in d, "hallucination 缺 %s 档定义" % score
        assert "reason 必须落到具体行" in d

    def test_hallucination_placeholder_exception_is_narrow(self):
        # v5 的宽例外（"标注为示例/占位的测试账号不算虚构"）正是裁判放过虚构凭证的口子
        d = evaluate.DIM_DEFS["hallucination"]
        assert "占位标记" in d
        assert "不算标注" in d and "仍按虚构计" in d
        assert "测试账号" in d   # 必须点名这种写法
        # v8（bc-0009 复发）：例外改成判定动作，词表只当举例——不背词表也不放过具体值
        assert "做两个动作" in d and "能不能被核验" in d
        assert "哪怕前面写着" in d

    def test_v8_coverage_gap_claims_need_evidence(self):
        # bc-0010：裁判把产出里已经写了的"库存批次未开通"分支说成缺失（model 稳定误读）。
        # 修法不是在词表里加一句，而是强制举证顺序：先点名已有的用例/场景，再说缺什么
        d = evaluate.DIM_DEFS["coverage"]
        assert "声称缺口之前必须先举证" in d
        assert "点名用例编号或名称" in d
        assert "不得声称缺口" in d
        assert "不得把一条已经写在产出里的场景说成" in d

    def test_v8_consistency_distinguishes_product_defects(self):
        # bc-0011：裁判把「实际结果」列记录的产品缺陷（导出表头文案错）当成用例的列数错误
        d = evaluate.DIM_DEFS["consistency"]
        assert "实际结果」列" in d and "不构成用例自身的格式错误" in d
        assert "format_columns" in d and "不得凭空认定" in d
        # 不能把 bc-0008 治好的契约上限放回去
        assert "不得高于 3" in d

    def test_v8_conventions_state_new_rules(self, jcfg):
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg, points=["① a"])
        assert "能不能被核验" in p                      # 约定 5
        assert "点名编号或名称" in p                     # 约定 6
        assert "format_columns" in p and "不是用例自身的格式错误" in p   # 约定 7

    def test_hallucination_exempts_abstract_references(self):
        # v7（bc-0009 治疗）：抽象指代不算虚构凭证——否则四条负向对照被稳定误判成 1 分
        d = evaluate.DIM_DEFS["hallucination"]
        assert "抽象指代" in d and "不算虚构" in d
        for token in ("账号 A", "某用户", "用户甲", "XX 门店"):
            assert token in d, "hallucination 例外没点名 %s" % token
        assert "不得据此把本维度压到 3 分以下" in d
        # 但 v6 治好的不能放回去：具体值跟在后面仍按虚构计
        assert "一旦跟了具体账号名/明文密码/IP/域名" in d
        assert "不得高于 2" in d

    def test_convention_5_states_both_v7_calibrations(self, jcfg):
        # 评审约定 5 是裁判最先读到的硬规矩，两条 v7 口径都得在里面露面
        p = evaluate.build_judge_prompt("需求原文X", "用例产出Y", jcfg, points=["① a"])
        assert "重新定义口径" in p and "不免除上限" in p
        assert "抽象指代" in p and "不得据此把 hallucination 压到 3 分以下" in p

    def test_convention_caps_hallucination_when_secrets_found(self, jcfg):
        p = evaluate.build_judge_prompt(
            "需求原文X", "用例产出Y", jcfg, points=["① a"],
            rule_findings=["tc-neg-secrets / no_secrets：行1 前置条件含虚构凭证/内网地址"])
        assert "hallucination 不得给 3 分以上" in p
        assert "coverage 与 consistency 均不得给 4 分以上" in p

    def test_every_contract_cap_is_stated_in_the_prompt(self, jcfg):
        # 一致率指标拿上限卡裁判，前提是这个上限在 prompt 里明文说过——否则是拿没说过的规矩扣分
        p = evaluate.build_judge_prompt(
            "需求原文X", "用例产出Y", jcfg, points=["① a"],
            rule_findings=["tc / no_secrets：行1 前置条件含虚构凭证/内网地址",
                           "tc / coverage：变更点②未被任何用例覆盖"])
        stated = {
            ("coverage", 3): ["coverage 与 consistency 均不得给 4 分以上", "不高于 3"],
            ("consistency", 3): ["不高于 3", "coverage 与 consistency 均不得给 4 分以上"],
            ("hallucination", 2): ["hallucination 不得给 3 分以上", "不得高于 2"],
        }
        for (dim, cap), phrases in stated.items():
            assert any(x in p for x in phrases), "prompt 没写明 %s ≤%d 的上限" % (dim, cap)
        for rule, caps in evaluate.CONTRACT_CAPS.items():
            for dim, cap in caps:
                assert (dim, cap) in stated, "CONTRACT_CAPS 里 %s→%s≤%d 没有对应的 prompt 明文" % (
                    rule, dim, cap)

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
              judge_note="", rule_pass=None):
    c = {"id": cid, "kind": kind, "verdict": verdict,
         "violations": violations or {}, "judge": judge, "judge_note": judge_note}
    if rule_pass is not None:
        c["rule_pass"] = rule_pass
    return c


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

    def test_negative_control_judge_drop_is_note_not_regression(self):
        # backlog #14：负向对照故意写坏，裁判给它降分不是被测产出退步。
        # 真实案例：同一评测集 v6 相隔 40 分钟两跑，tc-neg-jump-refs 的 hallucination 5 → 1
        # 被旧逻辑判退步，把正样本的真退步淹掉了。
        old = base_report([base_case(cid="tc-neg", kind="negative-control",
                                     verdict="detected", judge=judge_scores())],
                          mode="offline+judge")
        new = base_report([base_case(cid="tc-neg", kind="negative-control",
                                     verdict="detected", judge=judge_scores(hallucination=1))],
                          mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and imp == []
        assert any("tc-neg / Judge hallucination：5 → 1" in x and "负向对照" in x for x in lines)

    def test_negative_control_judge_rise_is_not_improvement(self):
        # 反向同理：裁判对负向样本"看走眼"给高分，也不该记成变好（判别力由规则通道负责）
        old = base_report([base_case(cid="tc-neg", kind="negative-control",
                                     verdict="detected", judge=judge_scores(hallucination=1))],
                          mode="offline+judge")
        new = base_report([base_case(cid="tc-neg", kind="negative-control",
                                     verdict="detected", judge=judge_scores())],
                          mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and imp == []
        assert any("负向对照" in x and "1 → 5" in x for x in lines)

    def test_negative_control_rule_channel_still_counts(self):
        # 只豁免 Judge 分数；负向对照的规则结论/漏检判定必须照常记账
        old = base_report([base_case(cid="tc-neg", kind="negative-control", verdict="detected",
                                     violations={"no_jump_refs": ["行1 前置条件含跳转引用"]},
                                     judge=judge_scores(hallucination=1))],
                          mode="offline+judge")
        new = base_report([base_case(cid="tc-neg", kind="negative-control", verdict="detected",
                                     violations={}, judge=judge_scores())],
                          mode="offline+judge")
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert any("违规消除" in x for x in imp), "规则通道的违规消除仍应记变好"
        assert not any("Judge" in x for x in imp), "Judge 分数变化不许混进变好"

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


# ---------- 9. 裁判-规则一致率（judge_agreement / --judge-agreement） ----------

# 真实锚点：已存档的不可变产物。v4 B 变体（170848）矛盾率必须一直是 15/28；
# v5 B 臂（221550）喂了清单+规则结论后掉到 1/28；v6（233955）治好了 bc-0007 但换了个维度冒头。
V4_B_REPORT = "ab-demo/b/baseline-2026-11-13-170848.json"
V5_B_REPORT = "ab-demo/b/baseline-2026-11-13-221550.json"
V6_REPORT = "reports/baseline-2026-11-13-233955.json"
V6_RUNS3_REPORT = "reports/baseline-2026-11-14-001756.json"   # v6 + --runs 3 真实稳定性产物
V7_RUNS3_REPORT = "reports/baseline-2026-11-14-075449.json"   # v7 + --runs 3：矛盾率首次归零
V8_RUNS3_REPORTS = (                                           # v8 三次逐次加料（措辞 → 事实 → 禁用词）
    "reports/baseline-2026-11-18-155846.json",
    "reports/baseline-2026-11-18-160734.json",
    "reports/baseline-2026-11-18-161427.json",
)


class TestJudgeAgreement:
    def test_contract_caps_map_every_rule_to_a_dimension(self):
        # 每条规则都得有契约上限映射；漏一条 = 裁判可以在那个维度上"看不见"规则抓到的问题
        for rule in evaluate.RULES:
            assert rule in evaluate.CONTRACT_CAPS, "规则 %s 没有契约上限映射" % rule
        for rule, caps in evaluate.CONTRACT_CAPS.items():
            assert rule in evaluate.RULES, "映射里有未登记的规则 %s" % rule
            for dim, cap in caps:
                assert dim in DIMS and 1 <= cap <= 5

    def test_contract_caps_follow_v5_rubric(self):
        # v5 约定的三条硬上限：契约类违规压 consistency、覆盖类压 coverage、虚构凭证压 hallucination
        caps = evaluate.CONTRACT_CAPS
        for rule in ("format_columns", "priority_valid", "traceability",
                     "no_jump_refs", "expected_non_empty"):
            assert caps[rule] == [("consistency", 3)]
        for rule in ("change_section", "coverage"):
            assert caps[rule] == [("coverage", 3)]
        assert caps["no_secrets"] == [("hallucination", 2)]

    def test_judge_above_cap_is_contradiction(self):
        c = base_case(cid="tc-neg-priority", verdict="fail",
                      violations={"priority_valid": ["行2 优先级'P5'非法"]},
                      judge=judge_scores(consistency=5), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert (agg["checkable"], agg["contradictions"]) == (1, 1)
        assert agg["contradiction_rate"] == 1.0
        it = agg["items"][0]
        assert it["case"] == "tc-neg-priority" and it["dimension"] == "consistency"
        assert it["score"] == 5 and it["cap"] == 3
        assert "P5" in it["evidence"] and it["reason"]

    def test_judge_at_cap_is_not_contradiction(self):
        # 上限是"不得高于 3"，给 3 分本身不算矛盾（否则指标会把合规裁判也判成矛盾）
        c = base_case(verdict="fail", violations={"priority_valid": ["行2 优先级'P5'非法"]},
                      judge=judge_scores(consistency=3), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["checkable"] == 1 and agg["contradictions"] == 0
        assert agg["contradiction_rate"] == 0.0 and agg["items"] == []

    def test_unmapped_dimensions_are_not_counted(self):
        # 规则只压它映射的维度：coverage 违规时 relevance 给满分不算矛盾、也不进分母
        c = base_case(verdict="fail", violations={"coverage": ["变更点②未被任何用例覆盖"]},
                      judge=judge_scores(coverage=3, relevance=5), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["checkable"] == 1          # 只数 coverage 这一个映射维度
        assert agg["contradictions"] == 0 and agg["contradiction_rate"] == 0.0
        assert agg["items"] == []

    def test_clean_case_has_nothing_to_check(self):
        agg = evaluate.judge_agreement([base_case(judge=judge_scores(), rule_pass=True)])
        assert agg["checkable"] == 0 and agg["contradictions"] == 0
        assert agg["contradiction_rate"] is None and agg["strict_flags"] == []

    def test_judge_not_run_goes_to_uncheckable_not_denominator(self):
        # 无 key 时不能拿缺数据凑指标：违规用例计入 uncheckable，分母保持 0
        c = base_case(verdict="fail", violations={"traceability": ["表头缺少关联引用列"]},
                      judge=None, judge_note="skipped（无 API key，仅规则通道）", rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["checkable"] == 0 and agg["contradiction_rate"] is None
        assert len(agg["uncheckable"]) == 1
        assert "traceability" in agg["uncheckable"][0] and "无法核对" in agg["uncheckable"][0]

    def test_clean_case_without_judge_is_not_uncheckable(self):
        agg = evaluate.judge_agreement([base_case(judge=None, rule_pass=True)])
        assert agg["uncheckable"] == []  # 没违规就没东西要核对，不该刷"无法核对"

    def test_strict_flag_when_rules_clean_but_judge_scores_low(self):
        # 反向可疑：规则 8 项全过、裁判却给 ≤2 分 → 可能误判，要人工复批
        c = base_case(judge=judge_scores(coverage=2), rule_pass=True)
        agg = evaluate.judge_agreement([c])
        assert agg["contradictions"] == 0 and len(agg["strict_flags"]) == 1
        assert "coverage=2" in agg["strict_flags"][0] and "人工复批" not in agg["strict_flags"][0]

    def test_no_strict_flag_when_rules_already_failed(self):
        c = base_case(verdict="fail", violations={"coverage": ["变更点①未被任何用例覆盖"]},
                      judge=judge_scores(coverage=2), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["strict_flags"] == []      # 规则和裁判同向，不是可疑
        assert agg["contradictions"] == 0     # 2 分低于上限，也不是矛盾

    def test_strict_flag_when_low_score_has_no_matching_rule_evidence(self):
        # 反向可疑的第二种情形（v6 实测补的盲区）：规则通道确实有违规，但违规的是别的维度，
        # 裁判却在"没有证据"的维度上压分 —— 老实现只看 rule_pass，这种就漏了
        c = base_case(cid="tc-neg-priority", verdict="fail",
                      violations={"priority_valid": ["行2 优先级'P5'非法"]},
                      judge=judge_scores(hallucination=1, consistency=3), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["contradictions"] == 0
        assert len(agg["strict_flags"]) == 1
        assert "hallucination=1" in agg["strict_flags"][0]
        assert "没检出 no_secrets 类违规" in agg["strict_flags"][0]

    def test_low_score_backed_by_a_fired_rule_is_not_suspicious(self):
        # 同样有别的维度违规，但压低分的维度本身有规则证据（no_secrets 命中）→ 不算可疑
        c = base_case(verdict="fail",
                      violations={"priority_valid": ["行2 优先级'P5'非法"],
                                  "no_secrets": ["行1 前置条件含虚构凭证/内网地址"]},
                      judge=judge_scores(hallucination=2, consistency=3), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        assert agg["strict_flags"] == []

    def test_dim_rules_is_the_inverse_index_of_contract_caps(self):
        for rule, caps in evaluate.CONTRACT_CAPS.items():
            for dim, _cap in caps:
                assert rule in evaluate.DIM_RULES[dim], "%s 没进 %s 的反查表" % (rule, dim)
        assert set(evaluate.DIM_RULES) <= set(DIMS)

    def test_render_agreement_full_section(self):
        c = base_case(cid="tc-neg-secrets", verdict="fail",
                      violations={"no_secrets": ["行1 前置条件含虚构凭证/内网地址"]},
                      judge=judge_scores(hallucination=5), rule_pass=False)
        agg = evaluate.judge_agreement([c])
        text = "\n".join(evaluate.render_agreement(agg))
        assert "## 裁判-规则一致性" in text
        assert "可核对 1 项" in text and "矛盾 1 项" in text and "矛盾率 100%" in text
        assert "| case | 维度 | 裁判分 | 上限 |" in text
        assert "hallucination" in text and "≤2" in text
        assert "门禁只认规则通道" in text

    def test_render_agreement_zero_denominator_is_honest(self):
        agg = evaluate.judge_agreement([base_case(
            verdict="fail", violations={"coverage": ["变更点③未被任何用例覆盖"]},
            judge=None, judge_note="error: 502", rule_pass=False)])
        text = "\n".join(evaluate.render_agreement(agg))
        assert "矛盾率 —" in text and "无法核对 1 项" in text
        assert "100%" not in text and "0%" not in text  # 不许把缺数据画成 0 矛盾

    def test_render_agreement_without_anything_checkable(self):
        text = "\n".join(evaluate.render_agreement(
            evaluate.judge_agreement([base_case(judge=judge_scores(), rule_pass=True)])))
        assert "本次无可核对项" in text

    def test_agreement_report_offline_recompute(self, tmp_path):
        rep = base_report([base_case(cid="tc-neg-priority", verdict="fail",
                                     violations={"priority_valid": ["行2 优先级'P5'非法"]},
                                     judge=judge_scores(consistency=5), rule_pass=False)],
                          version=4, mode="offline+judge")
        f = tmp_path / "baseline-x.json"
        f.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
        text = "\n".join(evaluate.agreement_report([f]))
        assert "# 裁判-规则一致性核对" in text and "baseline-x.json" in text
        assert "| v4 | offline+judge | 1 | 1 | 100% |" in text
        assert "不等于 judge-人工一致率" in text

    def test_agreement_report_rejects_scan_report(self, tmp_path):
        f = tmp_path / "scan-x.json"
        f.write_text(json.dumps(scan_report(), ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError) as e:
            evaluate.agreement_report([f])
        assert "扫描报告" in str(e.value)

    def test_real_v4_b_report_is_measured_contradictory(self):
        # 真实锚点：v4 那次 B 变体复跑（裁判声称"列结构完整统一、优先级使用 P0/P1/P2"）
        # 必须被本指标判为矛盾，否则说明指标松了、抓不到 bc-0005 那类放过
        rep = json.loads((EVAL_DIR / V4_B_REPORT).read_text(encoding="utf-8"))
        agg = evaluate.judge_agreement(rep["cases"])
        assert agg["checkable"] == 28 and agg["contradictions"] == 15
        assert abs(agg["contradiction_rate"] - 15 / 28) < 1e-9
        pairs = {(i["case"], i["dimension"]) for i in agg["items"]}
        assert ("tc-neg-secrets", "hallucination") in pairs   # "无虚构" vs 规则检出虚构凭证
        assert ("tc-1000001-good", "consistency") in pairs     # "列结构完整" vs 表头漂移

    def test_real_v5_and_v6_reports_show_the_fix_landed(self):
        # 真实锚点：v5 把清单+规则结论喂给裁判后矛盾从 15/28 → 1/28（B 臂），
        # v6 收紧 hallucination 定义后 bc-0007 那条（tc-neg-secrets）消失，
        # 换成了 tc-neg-format 用"这是格式问题不是内容不一致"绕过上限（→ bc-0008 候选）
        v5 = evaluate.judge_agreement(json.loads(
            (EVAL_DIR / V5_B_REPORT).read_text(encoding="utf-8"))["cases"])
        assert (v5["checkable"], v5["contradictions"]) == (28, 1)
        assert {i["case"] for i in v5["items"]} == {"tc-neg-secrets"}

        v6 = evaluate.judge_agreement(json.loads(
            (EVAL_DIR / V6_REPORT).read_text(encoding="utf-8"))["cases"])
        assert (v6["checkable"], v6["contradictions"]) == (14, 1)
        assert {i["case"] for i in v6["items"]} == {"tc-neg-format"}
        assert "tc-neg-secrets" not in {i["case"] for i in v6["items"]}   # bc-0007 已治好

    def test_real_v6_report_flags_the_placeholder_false_positives(self):
        # v6 的过度纠正：fixture 里只有"账号 A"这类抽象占位，裁判却判"虚构了账号 A 和密码"给 1/2 分。
        # 这两条必须被反向可疑抓到，否则说明指标盲区没补上（补之前 strict_flags 是 0）
        agg = evaluate.judge_agreement(json.loads(
            (EVAL_DIR / V6_REPORT).read_text(encoding="utf-8"))["cases"])
        assert len(agg["strict_flags"]) == 2
        assert any("tc-neg-priority" in s and "hallucination=1" in s for s in agg["strict_flags"])
        assert any("tc-neg-traceability" in s and "hallucination=2" in s for s in agg["strict_flags"])
        assert all("账号 A" in s or "虚构" in s for s in agg["strict_flags"])  # 理由必须带上原文证据

    def test_real_archived_reports_are_all_recomputable(self):
        # 十一份带裁判的存档报告（v2/v3/v4/v5/v6）都要能离线重算，且矛盾都 > 0
        paths = [EVAL_DIR / "reports" / "baseline-2026-11-12.json",
                 EVAL_DIR / "reports" / "baseline-2026-11-13-165241.json",
                 EVAL_DIR / "ab-demo" / "a" / "baseline-2026-11-13-092720.json",
                 EVAL_DIR / "ab-demo" / "b" / "baseline-2026-11-13-093523.json",
                 EVAL_DIR / "ab-demo" / "a" / "baseline-2026-11-13-170553.json",
                 EVAL_DIR / V4_B_REPORT,
                 EVAL_DIR / "reports" / "baseline-2026-11-13-220749.json",
                 EVAL_DIR / "ab-demo" / "a" / "baseline-2026-11-13-221318.json",
                 EVAL_DIR / V5_B_REPORT,
                 EVAL_DIR / V6_REPORT,
                 EVAL_DIR / V6_RUNS3_REPORT]
        text = "\n".join(evaluate.agreement_report(paths))
        for p in paths:
            assert p.name in text
        for rep_path in paths:
            agg = evaluate.judge_agreement(
                json.loads(rep_path.read_text(encoding="utf-8"))["cases"])
            assert agg["contradictions"] > 0, "%s 竟然零矛盾，指标可能失效" % rep_path.name
        assert "矛盾率 —" not in text  # 十一份都跑了裁判，不该出现"无法核对"占位

    def test_main_embeds_agreement_in_report(self):
        # 防回归：主流程必须算一致性、写进 JSON、并在裁判跑过时渲染小节
        src = inspect.getsource(evaluate.main)
        assert "judge_agreement(results)" in src
        assert '"judge_agreement": agreement' in src
        assert "render_agreement(agreement)" in src
        assert 'if any(r["judge"] for r in results):' in src  # 裁判没跑就不硬塞这一节

    def test_cli_exposes_judge_agreement_flag(self):
        src = inspect.getsource(evaluate.main)
        assert '"--judge-agreement"' in src and "agreement_report(paths)" in src


# ---------- 10. 裁判稳定性（--runs N / judge_stability） ----------

class TestJudgeStability:
    """锁住重复评的口径：只诊断裁判、极差 ≥2 才算不稳定、缺轮次不编数字、不影响退出码。"""

    def test_spread_alert_is_two_because_one_is_known_noise(self):
        # ±1 是 calibration.yaml 里记过的运行间抖动，若阈值定 1 会把正常抖动全报成不稳定
        assert evaluate.JUDGE_SPREAD_ALERT == 2
        assert evaluate.JUDGE_NOISE == 1

    def test_stable_runs_are_not_flagged(self):
        runs = [judge_scores(coverage=5), judge_scores(coverage=4), judge_scores(coverage=5)]
        st = evaluate.case_stability(runs, list(DIMS), 4)
        assert (st["runs_requested"], st["runs_scored"], st["runs_failed"]) == (3, 3, 0)
        assert st["unstable"] == [] and st["flipped"] is False
        cov = st["dimensions"]["coverage"]
        assert (cov["min"], cov["max"], cov["spread"]) == (4, 5, 1)
        assert cov["values"] == [5, 4, 5] and cov["mean"] == 4.67
        assert st["pass_at_n"] == "3/3" and st["spread_max"] == 1

    def test_spread_of_two_is_unstable_and_lists_the_values(self):
        runs = [judge_scores(coverage=5), judge_scores(coverage=3)]
        st = evaluate.case_stability(runs, list(DIMS), 4)
        assert st["spread_max"] == 2 and len(st["unstable"]) == 1
        assert "coverage 极差 2" in st["unstable"][0] and "5→3" in st["unstable"][0]

    def test_unstable_dimension_that_stays_above_threshold_is_not_a_flip(self):
        # 极差大但每轮都过线：算不稳定，不算结论翻转（两件事分开报，别混成一个数）
        runs = [judge_scores(coverage=5), judge_scores(coverage=3), judge_scores(coverage=4)]
        st = evaluate.case_stability(runs, list(DIMS), 3)
        assert len(st["unstable"]) == 1 and st["flipped"] is False
        assert st["pass_at_n"] == "3/3"

    def test_verdict_flip_is_detected(self):
        # 同一份产出重复评忽过忽不过：这是"单跑不可采信"的直接证据
        runs = [judge_scores(coverage=5, relevance=5, consistency=5, hallucination=5),
                judge_scores(coverage=2, relevance=3, consistency=3, hallucination=3)]
        st = evaluate.case_stability(runs, list(DIMS), 4)
        assert st["flipped"] is True and st["pass_at_n"] == "1/2"
        assert st["means"] == [5.0, 2.75]

    def test_failed_run_is_counted_but_never_scored(self):
        # 单轮调用失败：记失败轮次、不进任何统计，也绝不补一个分数进去
        runs = [judge_scores(), None, judge_scores(coverage=4)]
        st = evaluate.case_stability(runs, list(DIMS), 4)
        assert (st["runs_scored"], st["runs_failed"]) == (2, 1)
        assert st["dimensions"]["coverage"]["values"] == [5, 4]
        assert st["pass_at_n"] == "2/2"

    def test_all_runs_failed_leaves_nothing_to_measure(self):
        st = evaluate.case_stability([None, None], list(DIMS), 4)
        assert st["runs_scored"] == 0 and st["dimensions"] == {}
        assert st["means"] == [] and st["pass_at_n"] is None and st["flipped"] is None

    def test_incomplete_dimension_run_is_skipped_not_averaged(self):
        # 某轮缺维度：不进均分（不猜缺的那维），但该轮的其它维度值仍参与极差
        partial = {"coverage": {"score": 1, "reason": "r"}}
        st = evaluate.case_stability([judge_scores(coverage=5), partial], list(DIMS), 4)
        assert st["dimensions"]["coverage"]["values"] == [5, 1]
        assert st["means"] == [5.0] and st["pass_at_n"] == "1/1"

    def test_single_run_cannot_measure_stability(self):
        c = dict(base_case(judge=judge_scores()), judge_runs=[judge_scores()])
        agg = evaluate.judge_stability([c], list(DIMS), 4)
        assert agg["measured"] == [] and len(agg["insufficient"]) == 1
        assert "不足 2 轮" in agg["insufficient"][0] and agg["reason"]

    def test_no_judge_runs_says_not_run_instead_of_stable(self):
        agg = evaluate.judge_stability([base_case(judge=None)], list(DIMS), 4)
        assert agg["runs"] == 0 and agg["measured"] == []
        assert "裁判未跑" in agg["reason"] and "稳定" not in agg["reason"]

    def test_aggregate_collects_unstable_flipped_and_insufficient(self):
        cases = [
            dict(base_case(cid="tc-a", judge=judge_scores()),
                 judge_runs=[judge_scores(coverage=5), judge_scores(coverage=3)]),
            dict(base_case(cid="tc-b", judge=judge_scores()),
                 judge_runs=[judge_scores(),
                             judge_scores(coverage=2, relevance=3, consistency=3, hallucination=3)]),
            dict(base_case(cid="tc-c", judge=judge_scores()), judge_runs=[judge_scores()]),
            base_case(cid="tc-d", judge=None),          # 裁判没跑：不进任何一栏
        ]
        agg = evaluate.judge_stability(cases, list(DIMS), 4)
        assert agg["runs"] == 2 and agg["measured"] == ["tc-a", "tc-b"]
        assert any(x.startswith("tc-a") for x in agg["unstable"])
        assert any(x.startswith("tc-b") and "不可采信" in x for x in agg["flipped"])
        assert any(x.startswith("tc-c") for x in agg["insufficient"])
        assert all("tc-d" not in x for x in agg["unstable"] + agg["flipped"] + agg["insufficient"])
        assert [row["id"] for row in agg["table"]] == ["tc-a", "tc-b"]   # JSON 可序列化（非元组）

    def test_render_stability_section(self):
        cases = [dict(base_case(cid="tc-a", judge=judge_scores()),
                      judge_runs=[judge_scores(coverage=5), judge_scores(coverage=3)])]
        text = "\n".join(evaluate.render_stability(
            evaluate.judge_stability(cases, list(DIMS), 4)))
        assert "## 裁判稳定性（同一产出重复评 2 轮）" in text
        assert "| case | 通过轮次 | 各轮均分 | 最大极差 |" in text
        assert "coverage 3~5" in text and "2/2" in text
        assert "不稳定明细" in text and "coverage 极差 2" in text
        assert "不参与退出码" in text

    def test_render_stability_without_data_is_honest(self):
        text = "\n".join(evaluate.render_stability(
            evaluate.judge_stability([base_case(judge=None)], list(DIMS), 4)))
        assert "未测：裁判未跑" in text
        assert "0 条" not in text and "很稳定" not in text   # 不许把缺数据画成稳定

    def test_judge_repeated_calls_n_times_and_keeps_order(self, monkeypatch):
        calls = []

        def fake_llm_chat(messages, model, base, key):
            calls.append(len(calls) + 1)
            return json.dumps({d: {"score": 5, "reason": "r%d" % len(calls)} for d in DIMS})

        monkeypatch.setattr(evaluate, "llm_chat", fake_llm_chat)
        cfg = {"dimensions": list(DIMS)}
        runs, notes = evaluate.judge_repeated("需求X", "产出Y", cfg, "m", "http://b", "k", runs=3)
        assert len(runs) == 3 and calls == [1, 2, 3]
        assert notes == ["run1 ok", "run2 ok", "run3 ok"]
        assert runs[0]["coverage"]["reason"] == "r1" and runs[2]["coverage"]["reason"] == "r3"

    def test_judge_repeated_survives_a_mid_run_failure(self, monkeypatch):
        # 第 2 轮炸了：不中断、不补分，第 1/3 轮照常返回，失败原因如实记下
        n = {"i": 0}

        def flaky(messages, model, base, key):
            n["i"] += 1
            if n["i"] == 2:
                raise ValueError("502 bad gateway")
            return json.dumps({d: {"score": 5, "reason": "r"} for d in DIMS})

        monkeypatch.setattr(evaluate, "llm_chat", flaky)
        runs, notes = evaluate.judge_repeated("需求X", "产出Y", {"dimensions": list(DIMS)},
                                              "m", "http://b", "k", runs=3)
        assert [r is None for r in runs] == [False, True, False]
        assert "run2 error" in notes[1] and "502" in notes[1]

    def test_runs_below_one_is_rejected_by_cli(self):
        src = inspect.getsource(evaluate.main)
        assert '"--runs"' in src and "args.runs < 1" in src

    def test_main_wires_stability_without_touching_exit_code(self):
        # 稳定性必须进报告，但绝不能参与门禁判定（exit_ok 只由 verdict 与判别力决定）
        src = inspect.getsource(evaluate.main)
        assert "judge_repeated(" in src and "case_stability(judge_runs" in src
        assert "judge_stability(results" in src and '"judge_stability": stability' in src
        assert "render_stability(stability)" in src
        assert 'if args.runs > 1:' in src                 # 默认 1 轮时不塞这一节
        exit_line = [ln for ln in src.splitlines() if "exit_ok = all(" in ln][0]
        assert "stability" not in exit_line

    def test_first_successful_run_is_the_reported_judge_score(self):
        # 历史报告可比性：Judge 列必须是第 1 轮成功的分数，不是均值（均值另在稳定性小节）
        src = inspect.getsource(evaluate.main)
        assert "next((r for r in judge_runs if isinstance(r, dict)), None)" in src
        assert "取第 %d/%d 轮" in src

    def test_diff_reports_stability_change_as_note_only(self):
        old = base_report([base_case(judge=judge_scores())])
        new = base_report([base_case(judge=judge_scores())])
        old["judge_stability"] = {"runs": 3, "measured": ["tc-1"], "unstable": [], "flipped": []}
        new["judge_stability"] = {"runs": 3, "measured": ["tc-1"],
                                  "unstable": ["tc-1：coverage 极差 2"], "flipped": []}
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and imp == []                     # 稳定性变化不判退步
        assert any("裁判稳定性" in ln and "不稳定 0 → 1 条" in ln for ln in lines)

    def test_diff_ignores_stability_when_runs_differ(self):
        old = base_report([base_case(judge=judge_scores())])
        new = base_report([base_case(judge=judge_scores())])
        old["judge_stability"] = {"runs": 2, "measured": ["tc-1"], "unstable": [], "flipped": []}
        new["judge_stability"] = {"runs": 3, "measured": ["tc-1"],
                                  "unstable": ["x"], "flipped": ["y"]}
        lines, reg, imp = evaluate.diff_reports(old, new)
        assert reg == [] and not any("裁判稳定性" in ln for ln in lines)  # 轮次不同不可比

    def test_archived_reports_without_stability_still_recompute(self):
        # 老报告没有 judge_stability 字段：一致率离线重算与 --diff 都不能因此崩
        rep = json.loads((EVAL_DIR / V6_REPORT).read_text(encoding="utf-8"))
        assert "judge_stability" not in rep
        agg = evaluate.judge_agreement(rep["cases"])
        assert agg["checkable"] == 14
        lines, reg, imp = evaluate.diff_reports(rep, rep)
        assert reg == [] and imp == []

    def test_real_runs3_report_is_recomputable_offline(self):
        # 真实锚点：v6 那轮 --runs 3（12 条 × 3 轮）的存档产物，稳定性小结必须能离线重算出同样的结论
        rep = json.loads((EVAL_DIR / V6_RUNS3_REPORT).read_text(encoding="utf-8"))
        assert rep.get("judge_stability", {}).get("runs") == 3
        st = evaluate.judge_stability(rep["cases"], list(DIMS),
                                      rep["judge_stability"]["threshold"])
        assert len(st["measured"]) == 12 and st["insufficient"] == []
        assert st["unstable"] == ["tc-neg-expected-empty：hallucination 极差 4（1→1→5）"]
        assert len(st["flipped"]) == 1 and "1/3" in st["flipped"][0]
        by_id = {row["id"]: row["stability"] for row in st["table"]}
        # 正样本稳：三条都 3/3 过线，极差 ≤1
        for cid in ("tc-1000001-good", "tc-1000002-good", "tc-1020256-executed"):
            assert by_id[cid]["pass_at_n"] == "3/3" and by_id[cid]["spread_max"] <= 1
        # bc-0009 是"稳定地错"：三条负向对照的 hallucination 三轮全 1 分（极差 0）
        for cid in ("tc-neg-priority", "tc-neg-traceability", "tc-neg-jump-refs"):
            assert by_id[cid]["dimensions"]["hallucination"]["values"] == [1, 1, 1]
        # bc-0008 的逃逸不稳定：consistency 有时 3（守上限）有时 4（绕过）
        assert by_id["tc-neg-format"]["dimensions"]["consistency"]["spread"] == 1
        assert 4 in by_id["tc-neg-format"]["dimensions"]["consistency"]["values"]
        # 一致率用的是第 1 轮分数，与同轮稳定性可比
        agg = evaluate.judge_agreement(rep["cases"])
        assert (agg["checkable"], agg["contradictions"]) == (14, 1)
        assert len(agg["strict_flags"]) == 4 and all("账号 A" in x for x in agg["strict_flags"])

    def test_real_v7_runs3_report_meets_bc0008_bar(self):
        # v7 真实锚点：bc-0008 的验收口径全部达标——tc-neg-format 的 consistency 三轮恒 3（不再出现 4），
        # 总矛盾率首次归零（14 可核对 / 0 矛盾），正样本 consistency 未被虚降
        rep = json.loads((EVAL_DIR / V7_RUNS3_REPORT).read_text(encoding="utf-8"))
        assert rep["evalset_version"] == 7 and rep["judge_stability"]["runs"] == 3
        agg = evaluate.judge_agreement(rep["cases"])
        assert (agg["checkable"], agg["contradictions"]) == (14, 0)
        assert agg["contradiction_rate"] == 0.0 and agg["items"] == []
        st = evaluate.judge_stability(rep["cases"], list(DIMS),
                                      rep["judge_stability"]["threshold"])
        by_id = {row["id"]: row["stability"] for row in st["table"]}
        assert by_id["tc-neg-format"]["dimensions"]["consistency"]["values"] == [3, 3, 3]
        for cid in ("tc-1000001-good", "tc-1000002-good", "tc-1020256-executed"):
            assert by_id[cid]["pass_at_n"] == "3/3" and by_id[cid]["spread_max"] <= 1
            assert by_id[cid]["dimensions"]["consistency"]["min"] >= 4   # 正样本没被新口径压低

    def test_real_v7_runs3_report_only_partially_meets_bc0009_bar(self):
        # v7 真实锚点（如实记不达标的一半）：bc-0009 要求"反向可疑归零"，实测 4 → 1，
        # 抽象占位误判从"稳定地错"变成"间歇性地错"——所以 badcase 仍 open，不得写成已修复
        rep = json.loads((EVAL_DIR / V7_RUNS3_REPORT).read_text(encoding="utf-8"))
        agg = evaluate.judge_agreement(rep["cases"])
        assert len(agg["strict_flags"]) == 1 and "账号 A" in agg["strict_flags"][0]
        assert "tc-neg-coverage" in agg["strict_flags"][0]
        st = evaluate.judge_stability(rep["cases"], list(DIMS),
                                      rep["judge_stability"]["threshold"])
        by_id = {row["id"]: row["stability"] for row in st["table"]}
        # v6 那轮三条负向对照 hallucination 三轮全 1（稳定地错）；v7 后不再是 1
        for cid in ("tc-neg-priority", "tc-neg-traceability", "tc-neg-jump-refs"):
            assert by_id[cid]["dimensions"]["hallucination"]["values"] == [5, 5, 5]
        # 但误判没根除：两条负向对照的 hallucination 极差 4、结论翻转（稳定性小节抓到的就是这个）
        assert sorted(st["unstable"]) == sorted([
            "tc-neg-expected-empty：hallucination 极差 4（5→2→1）",
            "tc-neg-coverage：hallucination 极差 4（1→5→5）"])
        assert len(st["flipped"]) == 2
        # bc-0007 不能被 v7 放回去：tc-neg-secrets 的 hallucination 三轮都 ≤2
        assert by_id["tc-neg-secrets"]["dimensions"]["hallucination"]["max"] <= 2

    def test_v7_report_is_the_first_zero_contradiction_run(self):
        # 十一份历史带裁判报告矛盾都 > 0（见上一条测试），v7 是第一份 0 矛盾的：
        # 这条断言把"指标不是被调松的"钉住——上限映射与判定逻辑一个字没改，只是裁判开始守规矩
        for old in (V4_B_REPORT, V5_B_REPORT, V6_REPORT, V6_RUNS3_REPORT):
            rep = json.loads((EVAL_DIR / old).read_text(encoding="utf-8"))
            assert evaluate.judge_agreement(rep["cases"])["contradictions"] > 0, old
        v7 = json.loads((EVAL_DIR / V7_RUNS3_REPORT).read_text(encoding="utf-8"))
        assert evaluate.judge_agreement(v7["cases"])["contradictions"] == 0
        assert evaluate.CONTRACT_CAPS["format_columns"] == [("consistency", 3)]  # 口径未动

    def test_real_v8_runs3_reports_record_the_tradeoff(self):
        # v8 三次带 key 实测（逐次加料）：只改措辞 → 加机械事实 → 再加禁用词。
        # 这条把"部分达标 + 新代价"钉在测试里，防止文档把 v8 写成全面治好：
        #   ① 事实注入确实治好了 bc-0009 依赖的反向可疑（2 → 0），也帮 bc-0010 一次拿回 coverage 5；
        #   ② 但上限遵守反而退化（矛盾 0 → 1 → 2），bc-0011 三次都 4 分，bc-0010 在第三版复发。
        reps = [json.loads((EVAL_DIR / p).read_text(encoding="utf-8"))
                for p in (V8_RUNS3_REPORTS)]
        for rep in reps:
            assert rep["evalset_version"] == 8 and rep["judge_stability"]["runs"] == 3
        aggs = [evaluate.judge_agreement(r["cases"]) for r in reps]
        assert [a["checkable"] for a in aggs] == [14, 14, 14]
        assert [a["contradictions"] for a in aggs] == [0, 1, 2]        # 上限被稀释
        assert [len(a["strict_flags"]) for a in aggs] == [2, 0, 0]     # 反向可疑被治好
        by = [{c["id"]: c for c in r["cases"]} for r in reps]
        # bc-0011：产品缺陷被当格式错误，三次都是 4 分（0/3 达标）
        assert all(b["tc-1020256-executed"]["judge"]["consistency"]["score"] == 4 for b in by)
        # bc-0010：加事实那版 coverage 5，再加禁用词后又掉到 4
        assert [b["tc-1000002-good"]["judge"]["coverage"]["score"] for b in by] == [4, 5, 4]
        # bc-0009：事实注入后 hallucination 三轮回 5，且 bc-0007 没被放回去
        for b in by[1:]:
            assert b["tc-neg-priority"]["stability"]["dimensions"]["hallucination"]["values"] == [5, 5, 5]
            assert b["tc-neg-secrets"]["stability"]["dimensions"]["hallucination"]["max"] <= 2
        # 最关键的一条：第三版既达到了"反向可疑 0"，又退化了"上限遵守"——
        # 以后若有人只引用 0 这个数字，这条断言会提醒他同份报告还有 2 项矛盾
        assert len(aggs[2]["strict_flags"]) == 0 and aggs[2]["contradictions"] == 2
        assert any(i["case"] == "tc-neg-priority" and i["dimension"] == "consistency"
                   and i["score"] == 4 and i["cap"] == 3 for i in aggs[2]["items"])
        assert any("'P5'" in i["reason"] for i in aggs[2]["items"])
