---
name: testcase-evaluator
description: >
  测试用例评测 Skill（简写 /eval）。evals/ 双通道评测器的对话入口：登记评测（8 项规则断言 +
  LLM-as-Judge 四维打分）、全仓结构扫描（--scan）、有 key 时可现场生成再评（--live）；
  违规解读成人话，badcase 根因与校准记录出草稿待人工确认。零 key 可跑、不依赖 TAPD。
  使用场景：用户提到"评测/跑评测/给用例打分/eval"，或给出用例文件路径要求质量检查，
  或输入 /eval 时。
---

# 测试用例评测（testcase-evaluator）

> 分工：能力本体是 `evals/evaluate.py`（双通道评测器），本 Skill 只做**编排与解读**，
> 不重新实现评测逻辑；教程与字段细节一律见 [evals/README.md](../../../evals/README.md)，本文不重复。
> 上下游：testcase-generator 生成用例、testcase-reviewer 核查原型一致性、本 Skill 给用例质量打分。

## 使用方式

用户输入 `/eval`，或说"跑评测""评测一下这份用例""给 xxx.md 打分"时触发本 Skill。
目标不明确时先问清（评登记集 / 指定文件 / 全仓 / 现场生成），不要猜。

## 完整执行流程总览

| 顺序 | 执行动作 | 必须 | 条件触发 |
| :--- | :--- | :---: | :--- |
| 0 | 按 AGENTS.md 读项目配置 + 团队记忆库 README 索引及相关主题（01/03/04） | ✅ | |
| 1 | 明确评测目标，选模式（见模式速查） | ✅ | |
| 2 | 探测环境 API key，决定裁判通道是否启用 | ✅ | |
| 3 | 跑评测器，拿退出码与报告 | ✅ | |
| 4 | 人话解读结果并汇报 | ✅ | |
| 5 | 闭环引导：badcase 草稿 / 校准提醒 / 升版本提醒 | | fail 或 judge 跑过或改评分标准时 |
| 6 | 中间产物归 `_tmp/`，不污染正式目录 | ✅ | |

## 模式速查

| 用户意图 | 命令 | 说明 |
| :--- | :--- | :--- |
| 跑评测 / 评登记集 | `python3 evals/evaluate.py` | 在册用例 8 项规则 + 负向对照自测；有 key 加裁判 |
| 全仓扫 / 检查所有用例文件 | `python3 evals/evaluate.py --scan` | 6 项结构规则，未登记文件也守 |
| 评指定的未登记文件 | 先 `--scan` 看结构层（仓库外目录用 `--scan-root`） | 内容评（覆盖度/裁判）需登记：`--add 用例 --fixture 需求 --points ①②` 一条命令，见 evals/README 情况 2 |
| 让 AI 现场写再评 | `python3 evals/evaluate.py --live` | 需 key；简化版（只看文字，无原型图/数据库） |
| 换模型/换厂商 | 环境 `EVAL_LLM_BASE_URL`/`EVAL_LLM_MODEL` 或 `--judge-model` | 任何 OpenAI 兼容接口 |

## 执行要点

**第 2 步 key 探测**：`EVAL_LLM_API_KEY` / `GLM_API_KEY` / `OPENAI_API_KEY` 任一存在 → 裁判自动启用；
都没有 → 只跑规则，并明确告知用户"裁判跳过、不编分数"。key 只从环境读：不写进任何文件、不在对话里回显完整 key。

**第 3 步运行**：退出码 0 = 全过，1 = 有失败；报告默认 `evals/reports/`（`--out` 可改）。
钩子/CI 式简洁输出加 `--brief`（只列挡路条目）。

**第 4 步解读**：
- 违规翻译成人话：哪份文件、哪一行、犯哪条规则、建议根因（prompt/model/tool/knowledge/evalset）；
- **负向对照的违规是"成功检出"的证据，不是失败**，不得误报成问题；
- judge 跑过 → 解释四维分数与理由，并提醒校准完成前分数只作参考。

**第 5 步闭环（一律人工确认，AI 草稿单独不算数）**：
- fail → 出 `evals/badcases.yaml` 条目草稿（status open、confirmed_by null），用户确认后才改 fixed；
- judge 跑过 → 提醒抽样人工复批，一致率追加进 `evals/calibration.yaml`；
- 用户要收/放评分标准 → 提醒三件套：升 version + 重跑基线 + 重新校准。

## 红线

- 不伪造分数：无 key 就跳过，judge 失败如实记 error。
- key 不落盘、私有信息不入库（项目级红线见 AGENTS.md）。
- 根因确认、校准复批必须人工；本 Skill 只出草稿与提醒。
- 不依赖其他 skill：直接跑 evals/ 脚本（项目 Skill 健壮性原则）。