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