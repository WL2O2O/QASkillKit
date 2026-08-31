# 项目级 Agent 指令（Qoder / Claude Code / 通用 AGENTS.md 规范）

> 本文件由 Qoder 在每次 Chat / Inline Chat 时**自动加载**（无需 `@` 引用）。
> 适用于所有 agent 对话、无论用户是否调用 skill。

## 强制必读：项目配置与团队记忆库

**每次开始处理任何任务前（包括但不限于编写用例、生成周报、评估工时、生成验收报告、OCR 识图、流程图转 Mermaid、用例核查、回答问题）**：

0. **先读取项目配置** `config/project.config.json`（私有信息：TAPD workspace_id/团队成员/数据库/知识库/归档路径；字段说明见 `config/README.md`）；配置不存在时提示用户运行 `/setup` 初始化，但不中断当前任务（可动态获取或询问用户）
1. **必须先读取** `.qoder/team-memory/README.md`（索引文件，含文件清单与适用 Skill）
2. **按任务相关主题**，再读取对应主题文件（如 01 项目基础/02 OCR 三轨/03 MCP 规范/04 用例标准/05 周报工时/06 验收报告）
3. **遵循团队沉淀的规范与坑点**，不得绕过
4. **如有更新或冲突**，以本目录最新内容为准（个人记忆仅存个人偏好，不得覆盖团队规范）

适用任务 → 必读主题文件映射：

| 任务 | 必读主题 |
|:---|:---|
| 编写 / 核查 / 评审测试用例 | 01、03、04 |
| OCR 识图 / 原型图分析 | 02、04 |
| 流程图转 Mermaid | 02 |
| 生成周报 / 测试工时评估 | 01、03、05 |
| 生成验收报告 | 01、03、06 |

## 关键行为约束

1. **禁止虚构数据**：所有测试数据必须通过 dbx MCP 真实查询或 TAPD 需求原文获取
2. **禁止跳转引用**：测试用例的前置条件/操作步骤/预期结果必须可独立阅读，不得写"见 xxx"
3. **禁止调用浏览器查看原型链接**：TAPD 中的原型链接以 `<img>` 贴图为准
4. **禁止硬编码路径**：路径以项目根为基准，使用相对路径或 Glob 定位
5. **临时文件归档**：所有 skill 产生的中间文件写到 `.gitignore` 忽略的目录（`_tmp/`、`workspace/personal/image-cache/` 等），不得污染正式归档目录
6. **私有信息不入库**：真实 workspace_id、姓名、内网地址、账号密码、库名、知识库 UUID 只写入 `config/project.config.json` 或各 `local/` 目录（均被 .gitignore 排除），禁止硬编码进 SKILL.md/脚本/team-memory 入库文件

## Skill 健壮性原则

- 任何 skill 都不应硬性依赖其他 skill（如 `/testcase-generator` 不应依赖 `/ocr`）；需图像能力时**直接调用** `.qoder/skills/ocr/scripts/` 下的脚本，不通过 skill 命令转发
- SKILL.md 可选择在执行步骤开头重复本规则（以防 agent 未加载 AGENTS.md），但不强制

## 项目根目录

- 工作区根目录：`./`（路径以本文件所在目录为基准）
- 项目配置中心：`config/`（`project.config.json` 真实配置不入库，`project.config.example.json` 模板入库）
- 团队记忆库：`.qoder/team-memory/`（其中 `local/` 子目录为团队私有，不入库）
- 本地 Skill：`.qoder/skills/`（其中 `ui-automation/references/local/` 为团队私有，不入库）
- 临时文件：`_tmp/`（项目根，已被 `.gitignore` 忽略）
- 个人工作产物：`workspace/personal/`（仅 `drafts/` 草稿副本被 `.gitignore` 排除，其余入库）
- 正式归档：`workspace/testcases/{迭代}/`（姓名子目录由用户自建）
- TAPD workspace_id：取 `config/project.config.json` 的 `tapd.workspace_id`

## 详细规范位置

具体规范按主题分散在以下文件，遇到对应任务请主动查阅：

- `.qoder/team-memory/01-project-basics.md` — 技术栈 / 目录 / 归档路径
- `.qoder/team-memory/02-ocr-pipeline.md` — OCR 三轨协同 / 脚本修复 / GLM
- `.qoder/team-memory/03-mcp-toolkit.md` — TAPD / dbx / weknora MCP 调用规范
- `.qoder/team-memory/04-testcase-standard.md` — 用例命名 / 头部结构 / 分类组织 / 归档
- `.qoder/team-memory/05-report-and-effort.md` — 周报统计 / 测试工时评估
- `.qoder/team-memory/06-acceptance-report.md` — 验收报告 / 提测 / 缺陷统计 / 固化脚本
