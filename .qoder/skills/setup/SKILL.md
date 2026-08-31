---
name: setup
description: >
  项目初始化配置向导 Skill，简写为 /setup。首次使用本仓库或配置缺失时运行，
  引导用户生成 config/project.config.json（TAPD workspace_id、团队成员、数据库连接、
  知识库清单、产品端列表等私有配置），并可选初始化 workspace/ 骨架、team-memory/local/ 与
  ui-automation/references/local/ 私有文档。能自动探测的信息（TAPD 项目、dbx 连接、知识库）
  优先自动探测，探测不到才询问用户。
  使用场景：用户运行 /setup、提到 "初始化"、"配置向导"、"首次使用"，
  或其他 skill 发现 config/project.config.json 不存在时引导至此。
---

# 项目初始化配置向导（/setup）

## 目标

一次向导完成三件事：

1. 生成 `config/project.config.json`（全部 skill 的私有配置来源，gitignore 不入库）
2. 创建 `workspace/` 业务工作区骨架（归档路径目录；产物整体入库，仅 `personal/drafts/` 草稿副本 gitignore）
3. （可选）初始化 `.qoder/team-memory/local/`（团队私有知识，如业务表速查）与 `.qoder/skills/ui-automation/references/local/`（各端测试环境文档）

> **原则**：能自动探测的绝不让用户手填；用户可跳过任何字段（留空/占位符），后续 skill 运行时会按需询问补齐。

## 执行流程

### 第一步：检查现状

1. 读取 `config/project.config.json`：
   - **不存在** → 全新初始化，以 `config/project.config.example.json` 为骨架
   - **已存在** → 增量模式：读出现有值，仅补齐缺失/占位符（`<` 开头视为未填写）字段，已填字段展示确认、不覆盖
2. 读取 `config/README.md` 了解字段含义（向导话术以此为准）

### 第二步：自动探测（依次执行，失败不阻塞）

| 探测项 | 方式 | 结果处理 |
| :--- | :--- | :--- |
| TAPD workspace_id | 调用 mcp-server-tapd `get_user_participant_projects()` | 单项目直接采用；多项目列出让用户选择；失败则询问用户 |
| TAPD 项目名称 | 同上返回的项目名 | 作为 `team.project_name` 默认值供用户确认 |
| dbx 连接 | 调用 `dbx_list_connections`（先读工具 Schema，Glob `**/mcps/dbx/tools/dbx_list_connections.json`） | 单连接直接采用为 `database.connection_name`；多连接让用户选择；无 dbx 则留空 |
| 数据库名 | 选定连接后 `dbx_list_tables` 或连接元信息确认默认库 | 采用为 `database.database` |
| weknora 知识库 | 调用 `list_knowledge_bases`（可能返回空，属正常） | 有结果列出让用户勾选并标注业务域；无结果则留空数组并说明"可后续手工补" |

> 每项探测前先按 MCP 使用规范读取对应工具的 JSON Schema；某个 MCP 服务未安装/不可用时明确告知用户该项跳过，不报错中断。

### 第三步：询问用户（仅问探测不到的）

用一轮集中提问（AskUserQuestion 或对话），逐项给默认值：

| 字段 | 问法要点 | 默认值 |
| :--- | :--- | :--- |
| `team.project_owner` | 项目负责人姓名（验收报告表头用） | 留空待补 |
| `team.report_editor` | 验收报告修改者姓名 | 留空待补 |
| `team.testers` | 测试工程师姓名列表（缺陷统计剔除测试验证操作用） | 空数组 |
| `database.test_tenant_id` | 测试租户 ID（无租户体系可留空） | 空 |
| `database.conventions` | 业务查询约定（如"统计会员须排除临时会员"），可后续积累 | 空数组 |
| `database.domain_keywords` | 英文表名关键词→中文业务含义映射，可后续积累 | 空对象 |
| `product.clients` | 产品各端名称（如 PC后台、H5商城、App） | 空数组 |
| `color_legend` | 需求文档/原型图颜色标注语义（各团队可自定义，AI 识图/写用例时按此解释颜色） | example 中的默认图例（黑=原始逻辑/红=本次修改/紫=临时改动/橙=未实现或他人修改），保持默认即可，后续可人工按团队规范修改 |
| `archive.*` | 归档路径模板，一般保持默认 | example 中的默认值 |

### 第四步：写入配置

1. 按 example 的结构与字段顺序生成 `config/project.config.json`（UTF-8，无 BOM，2 空格缩进）
2. 未填写字段保留 example 的占位符原文（以 `<` 开头），便于后续识别"未配置"
3. 写入后 Read 回读验证 JSON 可解析
4. 快速自检：若存在 `.qoder/skills/acceptance-report/scripts/config_util.py`，运行
   `python -c "import sys; sys.path.insert(0,'.qoder/skills/acceptance-report/scripts'); import config_util; print(config_util.load_project_config().get('tapd'))"`
   验证读取链路

### 第五步：创建 workspace 骨架 + 可选初始化私有文档

**workspace 骨架（自动创建，目录已存在则跳过）**：按 `config/project.config.json` 的 `archive.*` 路径模板建目录（默认）：

```
workspace/personal/{drafts,image-cache,weekly,specs}
workspace/testcases
workspace/bugs
workspace/reports
workspace/data
```

> 各 skill 归档时若目录缺失也会自动创建（路径自愈），骨架仅为首次体验完整。

随后询问用户是否需要初始化私有文档：

| 项 | 动作 |
| :--- | :--- |
| 业务表速查 | 创建 `.qoder/team-memory/local/db-tables.md`（表头骨架：业务领域 \| 核心表），内容由团队后续积累；若用户提供了 dbx 连接，可现场用 `information_schema.TABLES` 拉取表清单按注释初步归类 |
| ui-automation 端文档 | 按 `.qoder/skills/ui-automation/references/env-template.md` 为用户报出的每个网页端在 `references/local/` 创建一份端文档，环境地址/账号由用户提供（敏感账号标注"每次询问，不记录"） |

### 第六步：完成汇总

输出汇总给用户：

1. 已写入的配置项清单（敏感值打码展示，如 workspace_id 只显示前 2 后 2 位）
2. 留空待补的字段及影响（哪个 skill 什么场景会再询问）
3. 提醒三件事：
   - `config/project.config.json`、`*/local/` 均已被 `.gitignore` 排除，**不会提交**
   - 凭证类不在本配置：TAPD token 在 `~/.qoder/mcp.json`（MCP 配置），GLM Key 在环境变量 `GLM_API_KEY`
   - 随时可重跑 `/setup` 增量补齐

## 硬性约束

- **禁止**将任何真实配置值写入 `config/project.config.example.json`、SKILL.md、team-memory 入库文件等会提交的文件
- **禁止**记录用户的账号密码到任何文件（含 local/），密码类一律"每次询问，不记录"
- 增量模式下**不得覆盖**用户已填写的真实值，除非用户明确要求修改
- 全程不中断：任何 MCP 探测失败都降级为询问用户或留空待补
