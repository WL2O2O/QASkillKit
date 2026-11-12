# 评测基线报告 2026-11-12（offline+judge）

- 评测集版本：1；Judge：启用（glm-4-flash，key 来源 EVAL_LLM_API_KEY）
- 判别力自测（负向对照）：✅ 全部检出
- 变更点覆盖：8/8

## 用例级结果

| case | 类型 | 规则通道 | Judge | 结论 |
|:---|:---|:---|:---|:---|
| tc-1000001-good | positive | ✅ | 3.5 | fail |
| tc-1000002-good | positive | ✅ | 3.5 | fail |
| tc-1000001-negative | negative-control | ❌ | 3.0 | detected |

## 规则合规率（正样本）

| 规则 | 合规率 |
|:---|:---|
| format_columns | 100% |
| priority_valid | 100% |
| traceability | 100% |
| no_jump_refs | 100% |
| expected_non_empty | 100% |
| no_secrets | 100% |
| change_section | 100% |
| coverage | 100% |

## 违规明细与建议根因（根因须人工确认，见 badcases.yaml）

- **tc-1000001-negative / format_columns**（建议根因：prompt）：行4 列数8≠9
- **tc-1000001-negative / priority_valid**（建议根因：prompt）：行1 优先级'P5'非法
- **tc-1000001-negative / no_jump_refs**（建议根因：prompt）：行2 前置条件含跳转引用
- **tc-1000001-negative / expected_non_empty**（建议根因：prompt）：行3 预期结果为空
- **tc-1000001-negative / no_secrets**（建议根因：model）：行5 前置条件含虚构凭证/内网地址
- **tc-1000001-negative / coverage**（建议根因：prompt）：变更点③未被任何用例覆盖

> Judge 校准提醒：LLM-as-Judge 自身需人工抽样校准（judge-人工一致率），
> 本报告 judge 分数仅作基线参考，方法论见 evals/README.md。
