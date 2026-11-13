# 优化建议 backlog（不紧急，排期再做）

> 记录"值得做但现在不做"的优化想法；开新迭代时从这里挑。
> 状态：backlog = 未开始；doing = 进行中；done = 已完成。

| # | 建议 | 内容 | 状态 |
|:---|:---|:---|:---|
| 1 | README 视觉优化 | 流程图、演示 GIF、截图（photos）优化：让第一次访问的人快速看懂"这是什么、怎么跑、产出长什么样"，服务分发与求职展示。落地：GIF 改静态图（用户决策），10 张统一设计 PNG（中英各一套图），mermaid 架构图替换为设计图 | done |
| 2 | 快速开始拆双轨（修矛盾） | 前置要求表把 TAPD/Qoder/Node 标"必需"，与评测模块"零 key 无 TAPD 纯终端可跑"矛盾，会劝退只想试评测的访客。拆成第一轨"30 秒试评测（只要 Python）"+ 第二轨"TAPD 完整流程"。成本最低收益最大 | done |
| 3 | 自带用例一键接入 | 加 `--add 用例路径 --fixture 需求路径 --points ①②` 免手写 YAML；`--scan` 扫描目录写死（SCAN_ROOTS），加 `--scan-root` 让外部用例目录也能扫 | done |
| 4 | README 贴报告样例 | 放一段真实基线报告的脱敏截图/代码块，不跑代码也能看到产出（与第 1 条合并做） | done |
| 5 | skill 英文化（evaluator 先行） | 11 个 skill 全中文，英文用户 agent 匹配不上 frontmatter。先给唯一不依赖 TAPD 的 testcase-evaluator 出英文版，其余 description 加一句英文 | done |
| 6 | 跨 IDE 兼容落地 | README 称 Claude Code 可加载，但其找 `.claude/skills/`，仓库只有 `.qoder/skills/`。补软链指引（`ln -s ../.qoder/skills .claude/skills`）或小脚本 | done |
| 7 | GitHub 门面三件套 | 加 topics（llm-evaluation/test-case/agent-skills/qa）、打首个 release tag v0.1.0、仓库简介突出"LLM 测试用例评测"差异化标签。v0.1.0 已推送，topics/简介/Release 已由用户在网页完成 | done |
| 8 | 精准分发 | 中文发 TesterHome/掘金（测试工程师受众），英文发 dev.to；主题"我给 AI 写的用例找了个改作业的老师"，配第 1 条设计图 | backlog |
| 9 | 评测器自测 + requirements | evaluate.py 367 行仅负向对照一个自测，补 pytest（规则边界/YAML 解析/scan 逻辑）+ requirements.txt。面试故事："评测器也要被评测" | done |
| 10 | 回归对比命令 | README 称"两次 JSON 对比即回归报告"但需人肉 diff。加 `--diff 报告1.json 报告2.json` 输出逐用例逐规则变好/变坏 | done |
| 11 | 报告同日覆盖保护 | evaluate.py 按 `baseline-<日期>` 写报告，同日重跑直接覆盖：先带 key 跑出 Judge 基线、再零 key 重跑，Judge 基线会被规则版悄悄顶掉（git 里有存档可恢复，但本地是坑）。建议文件名加时分秒或覆盖前提示 | done |

> 已在路线图、不重复列：A/B prompt 回归演示（--diff 工具已就位，待做）；评测集扩充已完成（12 条，见下方落地记录）。
> 诚实提醒：第 7/8 条增加曝光，但星星增速取决于内容质量与运气，不编预期数字。

## 第 1 条落地记录（2026-11-12）

- 产物：`docs/assets/*.png` 10 张（2x 分辨率）——hero / architecture / eval-gate / demo-zero-key / demo-blocked / demo-judge，及 hero-en / architecture-en / eval-gate-en / demo-judge-en 四张英文版；
- 图源：`docs/assets/src/*.html`（手写 HTML/CSS，统一深色设计系统），改文案后 `bash docs/assets/src/render.sh [名字...]` 重渲染（Chrome headless）；
- 嵌入位置：中英 README 顶部 hero、架构节设计图（替换 mermaid）、轨道 A 零 key 终端图、评测节 eval-gate 与打分卡；evals/README 钩子节拦截图、校准节打分卡；
- 真实性红线：终端输出、拦截/修复故事（P10 → P0，提交 3f22726）、裁判四维分数全部取自真实运行捕获，不模拟不编造；英文版打分卡的裁判理由注明 translated；
- 验收口径：陌生人打开 README 30 秒内能明白是什么、怎么跑、产出长什么样。

## 第 9 条落地记录（2026-11-13）

- 产物：`evals/tests/test_evaluate.py` 58 条测试（六组：用例表解析 / 8 条规则边界含正则边界 / 扫描逻辑 / 评测集三个 YAML 完整性 / 判别力与正样本保证 / extract_json+resolve_key），零 key、1 秒内跑完；
- `requirements.txt`：pyyaml>=6.0（运行）+ pytest>=7.0（自测）；`.gitignore` 补 `.pytest_cache/`；
- CI（evals.yml）第一步加 `python3 -m pytest evals/tests -q`，依赖安装改用 requirements.txt；pre-commit 钩子保持两层不动（避免强制装 pytest，秒级优先）；
- 刻意边界：不测 Judge 网络调用与 --live（需 key，由人工校准实录兜底），单测只锁确定性逻辑；
- 文档同步：evals/README.md 新增「评测器自测」节并改 CI 描述为三层，中英 README 评测入口各加一句。

## 第 10+11 条落地记录（2026-11-13）

- `--diff 旧.json 新.json`：逐用例逐规则输出 ❌退步/✅变好/ℹ️说明 三类；规则通道新增违规即退步，Judge 单维 ±1 视为运行间抖动（calibration.yaml 已知），降幅 ≥2 才判退步；退出码 退步>0→1 可直接当 prompt 回归门禁（A/B 演示的工具已就位）；
- 扫描报告（scan-*.json）之间也可比；登记评测与扫描混比明确报错；评测集版本不同给"仅供参考"警告；新增/消失用例列入说明不判退步（防误伤，删用例须人工确认）；
- 报告文件名改为 `<前缀>-<日期>-<时分秒>`（baseline 与 scan 都改），同日重跑互不覆盖，JSON 增加 generated_at 字段；pre-commit 钩子不解析文件名，零影响；
- 新增 16 条 pytest（report_stem 命名 + diff 语义全套 + 真实基线锚点：11-11 vs 11-12 必须零退步），总数 74 条；
- 真实验证：校准前 v1 vs 修复后 v2 基线 diff 输出"变好 9 项"（fail→pass、hallucination 1→5），与校准实录完全吻合；负向对照 2→1 正确落入抖动说明；
- 文档同步：evals/README 新增「回归对比」节（含真实输出节选）+ 报告命名说明，中英 README 各加一句，testcase-evaluator SKILL.md 模式表加 --diff 行。

## 评测集扩充落地记录（2026-11-13，v2 → v3，12 条）

- 构成：3 正样本（新增 tc-1020256-executed：真实执行版，实际结果列已回填 PASS/FAIL/未执行，验证评测器不惩罚执行期内容）+ 1 混合负向对照（原 tc-1000001-negative）+ 8 单规则隔离负向对照（每份只坏一处，8 条规则各一发）；
- 隔离设计要点：隔离弹里"被坏行"覆盖的变更点由其他行兜住，避免误触发 coverage；neg-change-section 全文（含注释）刻意避开"变更点"触发词——change_section 规则按关键词存在性检查，这是写第 9 条测试时发现的真实语义；
- 隔离纯度由 pytest 锁定：test_isolated_negatives_violate_only_target_rule 断言 detected == expect（恰好一条，不多不少）；test_every_rule_has_isolated_negative 断言 8 条规则全覆盖；
- 新 fixture：fixtures/1020256-requirement.md（需求文字提炼自 demo1.md 头部概述，不含执行期内网标识）+ fixtures/neg-*.md 8 份（均基于虚构需求 1000001）；demo1.md 本体只读引用，未改动；
- 基线：reports/baseline-2026-11-13-063552.*（v3 零 key，13/13 覆盖、9/9 检出、exit 0）；--diff v2→v3 零退步（覆盖 8/8→13/13 判变好，新用例进说明桶）；
- 待办：新样本 Judge 基线待 export key 重跑 + 抽样校准（evals/README 已注明）；
- 文档同步：中英 README 轨道 A 文案与 demo-zero-key 配图按 v3 真实输出重渲染，evals/README 情况 1/校准节/基线诚实声明更新。
## A/B prompt 回归演示落地记录（2026-11-13，真实 live+judge 运行）

- 工具：evaluate.py 新增 `--sut-prompt`（替换 --live 的被测 prompt；路径支持绝对/相对当前目录/相对 evals/ 三种写法，找不到给人话报错），A/B 跑法从此是一等公民；
- 脚本：`evals/ab-demo.sh` 一键跑完 A（正式版 prompt）→ B（`evals/prompts/variant-b-weakened.md`，故意弱化：允许"同上"、放开 P3 与"高/中/低"、不要变更点表与覆盖矩阵、列数按需精简、只写 5 条主流程）→ `--diff`；key 只从环境读，脚本不写盘不打印；产物落 `evals/ab-demo/{a,b}/`（报告 + 现场生成用例快照）与 `evals/ab-demo/diff-*.md`；
- 断点续跑：单变体约 2-5 分钟（3 次生成 + 12 次 Judge），首跑在 A 结束后中断过一次（B 目录空、`_tmp/eval-live` 里 A 的产物还在），因此脚本改为"已有报告 json 的变体自动跳过"，`FORCE=1` 强制重跑，并在开跑前打印耗时提示避免误判卡死；A 的快照已抢救到 `ab-demo/a/cases/`；
- 真实结果（glm-4-flash，报告 092720 vs 093523）：A 干净——3 条正样本 Judge 四维全 5.0、变更点覆盖 13/13、exit_ok=True；B 退步——覆盖 0/13、exit_ok=False、`--diff` 判 ❌退步 37 项 / ✅变好 4 项 / ℹ️说明 5 项，对比退出码 1（可直接当 prompt 回归门禁）；
- 意外收获 1（bc-0003，评测器盲区，已修）：规则通道遇到"列数≠9"的行只报 format_columns 就 continue，B 的 6 列表格里的 P3、"高/中"、前置条件"同上"、缺失关联引用列**当时全部漏检**（B 报告这三项合规率还显示 100%）。修法：`parse_case_tables_with_headers()` 保留表头 + `is_standard_header()` 判定列序，非标准表头改为按列名兜底检查；标准表头但某行少列仍只报列数（下标会错位，宁可不猜）。验证：登记评测集与全仓扫描结果零变化（--diff 旧新基线 退步 0/变好 0），新增 18 条 pytest（合成漂移表 + 拿这次 B 的真实产物当锚点），总数 94 条；
- 意外收获 2（bc-0004，裁判宽松，待人工确认）：B 那份 `tc-1020256-executed` 规则通道查出覆盖 0/5、缺变更点说明、4 处"同上"，Judge 却给四维全 5.0（另两条也只 5.0→4.8/4.5，仍在及格线内）。说明**只靠 LLM 裁判当门禁会放过这种退步**，规则通道不是可选项；coverage 维度定义要不要收紧属评分标准变更，需人工确认 + 升评测集版本 + 重跑基线 + 重新校准，本次未动；
- 待办：A/B 两份 live+judge 报告可当 v3 的 Judge 参考样本，但尚未人工抽样复批，一致率待补记 calibration.yaml；bc-0003/bc-0004 的 confirmed_by 仍为 null（open 草稿，pytest 已放宽为"只有 open 允许无人工确认"）；
- 文档同步：evals/README 新增「A/B prompt 回归演示」节（含真实 diff 节选与两条发现）、pytest 条数与基线诚实声明更新，中英 README 各加一段，testcase-evaluator SKILL.md 模式表加 ab-demo.sh 与 --sut-prompt 两行。

## bc-0004 治疗记录（2026-11-13，评测集 v3 → v4：收紧裁判标准）

- 触发：A/B 演示量出裁判宽松——B 变体产出规则通道查出覆盖 0/5、缺变更点说明、4 处"同上"，Judge 仍给四维全 5.0；用户判定"发现即治疗"，同意升级维度定义；
- 改标准（evaluate.py）：`DIM_DEFS["coverage"]` 从一句笼统描述改成可执行流程——先拆变更点清单 → 逐点核对有无对应用例 → 按分数上限表打分（全覆盖含边界=5、全覆盖边界少=4、漏 1 点或全无边界=3、漏 2 点以上=2、只写主流程=1），且 reason 必须写出核对结论；`DIM_DEFS["consistency"]` 纳入输出契约（列结构完整、优先级只用 P0/P1/P2、禁止"同上/见上文"，违背任一项不高于 3）；judge prompt 新增评审约定 4「格式退化不等于内容合格」与 5「先做变更点核对再评其余维度」；
- 可测性重构：judge prompt 拼装抽成 `build_judge_prompt()`，零 key 就能自测评分标准文本（TestJudgeRubric 5 条：版本 ≥4、coverage 上限表齐 5 档、consistency 含契约关键词、prompt 携带全部维度与约定、bc-0004 已确认且记录 v3→v4），pytest 总数 94 → 99；
- 升版本 + 重跑基线：cases.yaml `meta.version` 3 → 4；`reports/baseline-2026-11-13-145132.*` 为 v4 零 key 基线，与 v3 基线 `--diff` = 退步 0 / 变好 0 / 说明 1「评测集版本不同」，证明只动了裁判标准、没扰动规则通道；
- 重新校准（待 key，未做不得声称已生效）：需 export key 后 ① `python3 evals/evaluate.py`（v4 登记评测 Judge 基线，12 次调用）② `FORCE=1 bash evals/ab-demo.sh`（A/B 各重跑，约 60 次调用），验收标准「B 变体 coverage < 4、A 变体仍高分」；跑完抽样人工复批并追加 calibration.yaml 记录；
- 文档同步：evals/README「裁判校准实录」新增第二次校准小节（v3→v4 全过程 + 待验证声明）、A/B 节发现 2 改为"已确认并治疗"、基线诚实声明区分 v3/v4 与 ab-demo 报告的裁判标准版本，中英 README 各补一句"裁判短板已量化并收紧标准，门禁以规则通道为准"；badcases.yaml bc-0003 置 fixed、bc-0004 置 confirmed（confirmed_by WL2O2O）。

## v4 裁判标准首轮验证记录（2026-11-13，export key 实跑：**未达验收标准**）

- 实跑三份带 Judge 的报告：① `reports/baseline-2026-11-13-165241.*`（v4 登记评测，offline+judge，12 条全有分数，正样本均分 4.75/4.75/4.25，exit_ok=True，覆盖 13/13）② `ab-demo/a/baseline-2026-11-13-170553.*`（v4 A 臂 live+judge）③ `ab-demo/b/baseline-2026-11-13-170848.*`（v4 B 臂 live+judge）；A/B 对比 `diff-…170553-vs-…170848.md` = ❌退步 50 项 / ✅变好 2 项 / ℹ️说明 6 项（比 v3 那轮的 37 项多，因为表头漂移兜底现在把 6 列表格的每一行都记账），退出码 1；
- 对照验收标准「B 变体 coverage < 4、A 变体仍高分」：**方向对了但没达标**——B 的 coverage 从 v3 那轮 5/5/5 掉到 **3/3/4**、理由里出现"覆盖 x/y"核对句式，可四维均分 4.50/4.50/4.75 **仍全部 ≥4**，这轮判 fail 完全靠规则通道；
- 关键发现（bc-0005，open）：裁判把核对动作演出来了但**结论是编的**——B 的 tc-1000001-good 实际覆盖 0 点、无变更点说明，理由写"变更点1、2、3、4、5、6均覆盖"；反过来 165241 的正样本 tc-1000001-good 规则通道确认 ①②③ 全覆盖（fixture 只有 3 点），裁判扣到 4 分说"②③无用例对应，仅覆盖 3/5"；consistency 明写"违背契约任一项不高于 3"，B 三份都是 6 列表格 + "高/中"优先级 + "执行TC1操作"引用，裁判仍全给 5 分并断言"优先级使用 P0/P1/P2"；
- 其他如实记录：v4 A 臂 exit_ok=False（`--live` 生成波动，tc-1020256-executed 漏变更点⑤，覆盖 12/13）→ 说明 live A/B 单次结果要连着看，生成波动本身就该暴露；1 条负向对照 Judge 调用被远端断连（tc-neg-expected-empty，报告显示"—"，不补分）；v3 那轮 A/B 报告仍未经人工抽样复批，一致率待补 calibration.yaml；
- 脚本 bug 与修复：`run_variant` 原来用"目录空才拷快照"的判断，导致 `FORCE=1` 重跑时快照不刷新——v3 的产物一直躺在 `a/cases`、`b/cases` 里配着 v4 的报告。改为**按运行时间戳落盘** `cases-HHMMSS/`（`git mv` 旧目录为 `a/cases-092720`、`b/cases-093523`，v4 B 产物抢救进 `b/cases-170848/`）；**v4 A 臂的现场生成产物已被 `_tmp/eval-live` 覆盖丢失**，只剩报告 json/md（诚实声明已写进 evals/README）；
- 新登记 bc-0006（open）：`JUMP_RE` 漏掉"执行TC1操作"式跨用例引用（b/cases-170848/tc-1020256-executed.md 前置条件列 4 处），该轮 no_jump_refs 合规率仍显示 100%；
- 测试：TestAbDemoArtifacts 改为遍历所有 `cases-*` 快照（任何一轮 B 的退化产出都必须被抓）、bc-0003 锚点钉在 v3 那轮的 `cases-093523`、新增 v4 B 快照锚点（缺关联引用列 + "高/中"优先级）、diff 断言钉住首轮文件名并另加"每份 diff 都必须含 ❌退步"通用断言；pytest 99 → **101 条全绿**；
- 结论与待决：机械可判的事（覆盖几点/列数/优先级合法性）不能指望小模型裁判，门禁只认规则通道。下一步三选一待用户定：(a) 把 cases.yaml 的变更点清单注入 judge prompt（核对给定清单而非自己拆）(b) coverage 归规则通道、裁判只评粒度/边界/异常并放宽上限 (c) 换更强裁判模型或多数投票再测；
- 文档同步：evals/README「裁判校准实录」把"待 key 验证"改成实跑结论（含四条证据）、A/B 节加第二轮 50 项退步与产物布局说明、pytest 条数 94→101、基线诚实声明列出三份带 Judge 报告及其裁判标准版本并声明 A 臂 v4 快照丢失；中英 README 各把"待复跑验证"改成实测结论；badcases.yaml bc-0004 fix_ref 记"未达验收标准、不标 fixed"，新增 bc-0005/bc-0006 两条 open 草稿（confirmed_by null，等人工确认）。

## 评测集 v5 治疗记录（2026-11-13，bc-0005 的 (a)+(b) 组合：机械事实不再让裁判自己算）

- 触发：v4 首轮实跑未达验收标准（B 的 coverage 3/3/4、四维均分 4.50/4.50/4.75 仍全部过线；裁判把"逐点核对"演出来但结论是编的；consistency 的降分上限被无视）。用户选定 (a)+(b) 组合方向，bc-0005 由 open 转 confirmed（confirmed_by WL2O2O；root_cause 仍记 model——小模型指令遵循不足，治疗动作落在评测集侧）；
- (a) 喂事实：cases.yaml 新增顶层 `change_points` 段，按 fixture 给 ground-truth 变更点清单（1000001 三点、1000002 五点、1020256 五点，内容取自登记正样本的「变更点说明」表，即评测集认定的参考答案口径）；`build_judge_prompt(fixture, output, cfg, points, rule_findings)` 注入两块事实——【变更点清单（评测集给定的 ground truth，不要自己另拆一份）】与【规则通道已检出的确定性违规（不得推翻、不得重算、不得视而不见）】；规则通道干净时显式写"无（8 条规则全部通过）"，用例没登记清单时显式写"未登记"并要求裁判自拆后在 reason 里先列清单，不留空给它瞎猜；
- (b) 改 coverage：`DIM_DEFS["coverage"]` 从"自己拆清单+逐点核对+上限表"改为"覆盖充分性"——机械覆盖度归规则通道，裁判只评边界值/异常场景/状态分支/数据组合/粒度，5 档上限按此重写，reason 必须落到具体缺口、禁止"覆盖充分"这类套话；`consistency` 改为语义一致性（术语统一、前置与步骤不矛盾、预期与步骤对得上、不依赖另一条用例）+ 规则通道列出契约违背时不高于 3；评审约定重排为 4「分工：能机器判的归规则通道」/ 5「规则通道有违规则 coverage、consistency 不得高于 3」/ 6「禁止编造清单里没有的变更点」；
- 接线：main() 从 `cfg["change_points"][case["fixture"]]` 取清单，把 violations 展平成 "case / rule：明细" 一并传给 judge()；
- 升版本 + 重跑基线：meta.version 4 → 5；`reports/baseline-2026-11-13-205017.*` 为 v5 零 key 基线，与 v4 零 key 基线（145132）`--diff` = **退步 0 / 变好 0 / 说明 1「版本不同」**，确认只动裁判侧；另用假 key + 不可达端点探测新 prompt 拼装不崩（Judge 调用失败如实记 "—"，不补分）；
- 测试：pytest 101 → **107 条全绿**（清单编号必须与 expected_change_points 一致、prompt 注入清单与规则结论、无 findings 时写"无（8 条规则全部通过）"、无清单时的"未登记"兜底、monkeypatch llm_chat 验 judge() 转发、inspect.getsource 锁主流程接线防回归）；
- 待验证（需 key，未跑不得声称已生效）：`python3 evals/evaluate.py` + `FORCE=1 bash evals/ab-demo.sh`，验收标准「B 变体 Judge 均分 < 4 且理由不与规则通道结论矛盾、A 变体仍高分」；跑完按校准实录方法抽样人工复批、追加 calibration.yaml；
- 代价与立场：喂事实等于放弃裁判在机械项上的独立性，用独立性换可靠性；门禁仍只认规则通道。bc-0006（`JUMP_RE` 漏"执行TC1操作"式引用）本轮未治疗，保持 open；
- 文档同步：evals/README 新增「第三次校准：v4 → v5」小节、`--add` 节补 change_points 用法、pytest 条数、A/B 节补一句 v5、诚实声明列出 v5 零 key 基线并声明"带 Judge 分数的三份都是 v4 标准下跑的"；中英 README 各补一句 v5 与其未验证状态；testcase-evaluator SKILL.md 补 v5 分工说明与 root_cause 枚举 evaluator。
