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
| 9 | 评测器自测 + requirements | evaluate.py 367 行仅负向对照一个自测，补 pytest（规则边界/YAML 解析/scan 逻辑）+ requirements.txt。面试故事："评测器也要被评测" | backlog |
| 10 | 回归对比命令 | README 称"两次 JSON 对比即回归报告"但需人肉 diff。加 `--diff 报告1.json 报告2.json` 输出逐用例逐规则变好/变坏 | backlog |
| 11 | 报告同日覆盖保护 | evaluate.py 按 `baseline-<日期>` 写报告，同日重跑直接覆盖：先带 key 跑出 Judge 基线、再零 key 重跑，Judge 基线会被规则版悄悄顶掉（git 里有存档可恢复，但本地是坑）。建议文件名加时分秒或覆盖前提示 | backlog |

> 已在路线图、不重复列：A/B prompt 回归演示、评测集扩到 8-10 条。
> 诚实提醒：第 7/8 条增加曝光，但星星增速取决于内容质量与运气，不编预期数字。

## 第 1 条落地记录（2026-11-12）

- 产物：`docs/assets/*.png` 10 张（2x 分辨率）——hero / architecture / eval-gate / demo-zero-key / demo-blocked / demo-judge，及 hero-en / architecture-en / eval-gate-en / demo-judge-en 四张英文版；
- 图源：`docs/assets/src/*.html`（手写 HTML/CSS，统一深色设计系统），改文案后 `bash docs/assets/src/render.sh [名字...]` 重渲染（Chrome headless）；
- 嵌入位置：中英 README 顶部 hero、架构节设计图（替换 mermaid）、轨道 A 零 key 终端图、评测节 eval-gate 与打分卡；evals/README 钩子节拦截图、校准节打分卡；
- 真实性红线：终端输出、拦截/修复故事（P10 → P0，提交 3f22726）、裁判四维分数全部取自真实运行捕获，不模拟不编造；英文版打分卡的裁判理由注明 translated；
- 验收口径：陌生人打开 README 30 秒内能明白是什么、怎么跑、产出长什么样。