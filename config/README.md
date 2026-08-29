# config — 项目私有配置中心

本目录是**全部项目/团队/环境私有信息的唯一存放处**。所有 skill、脚本、team-memory 均从这里读取私有配置，代码与文档中**禁止硬编码**任何 workspace_id、姓名、内网地址、数据库名、知识库 ID 等信息。

## 文件说明

| 文件 | git 状态 | 说明 |
|:---|:---|:---|
| `project.config.example.json` | ✅ 提交 | 配置模板（占位符 + 注释），新团队据此填写 |
| `project.config.json` | 🚫 忽略 | 真实配置，本地生效；由 `/setup` 向导生成或手工复制模板填写 |
| `README.md` | ✅ 提交 | 本说明文档 |

> 除本目录外，还有两处 gitignore 的本地私有文档目录：
> - `.qoder/skills/uitest/references/local/` — 各端测试环境信息与实战坑点（含内网地址）
> - `.qoder/team-memory/local/` — 项目私有的团队经验（如数据库常用表速查）

## 字段说明

### tapd

| 字段 | 说明 |
|:---|:---|
| `workspace_id` | TAPD 项目 ID。`/setup` 可通过 `get_user_participant_projects()` 自动获取；多项目时向导会让你选择 |

### team

| 字段 | 说明 | 使用方 |
|:---|:---|:---|
| `project_name` | 项目名称 | acceptance-report 报告表头 |
| `project_owner` | 项目负责人 | acceptance-report 报告表头 |
| `report_editor` | 报告修改者 | acceptance-report 报告表头 |
| `testers` | 测试工程师姓名列表 | analyze_bugs.py 统计修复人时剔除测试验证操作 |

### database

| 字段 | 说明 | 使用方 |
|:---|:---|:---|
| `connection_name` | dbx MCP 连接名 | mcpcase / uitest 等查询真实测试数据 |
| `database` | 业务数据库名 | 同上 |
| `test_tenant_id` | 测试租户 ID（可空） | 数据隔离确认 |
| `conventions` | 业务数据查询约定（逐条自然语言） | 生成 SQL / 统计口径时遵循 |
| `domain_keywords` | 英文表名关键词 → 中文业务含义映射 | 动态选表时辅助搜索 |

### knowledge_bases

weknora 知识库清单（`domain` 业务域 / `name` 名称 / `id` UUID）。skill 按需求所属业务域选取对应 `id` 直查。未配置知识库可留空数组，相关步骤自动跳过。

### color_legend

需求文档/原型图**颜色标注语义**（AI 识图与用例编写时按此解释颜色含义），**各团队可自定义**——不同团队需求文档的标注颜色规则可能不同，请人工按团队实际规范配置。

| 字段 | 说明 |
|:---|:---|
| `_comment` | 配置说明（可选） |
| `<颜色名>` | 键=颜色名（如 `red`），值=该颜色标注的业务含义（自然语言描述） |

默认图例（示例，未配置时的兜底语义）：

| 颜色 | 含义 |
|:---|:---|
| `black` | 原始需求逻辑（整图全黑=纯新增功能） |
| `red` | 本次需求迭代修改的逻辑 |
| `purple` | 需求开发中临时改动的逻辑 |
| `orange` | 尚未实现的逻辑或他人并行修改标注 |

> **使用说明**：
> - skill（ocr / mcpcase / case-review）识图时从 `config/project.config.json` 读取本配置解释颜色，**不依赖固定颜色规则**
> - 未配置时按默认图例处理（不中断流程），并提示用户运行 `/setup` 或手动补充配置
> - 各团队若颜色规范不同（如蓝色代替紫色、颜色含义不同），修改本配置即可，无需改动 skill

### product

| 字段 | 说明 | 使用方 |
|:---|:---|:---|
| `clients` | 产品各端名称列表 | 验收报告"各端稳定版本号"归类、需求标题前缀识别 |

### archive

各类产物的归档路径模板（相对项目根），`{迭代}`、`{需求ID}`、`{测试人员}` 为运行时占位符。一般无需修改，保持默认即可。

默认骨架（`/setup` 自动创建；产物整体入库，仅 `personal/drafts/` 草稿副本 gitignore）：

```
workspace/
├── personal/                    # 个人工作产物
│   ├── drafts/{迭代}/           # 草稿用例（双路径之一）
│   ├── image-cache/{需求ID}/    # 需求图片缓存（供 case-review 复用，提交前人工检查）
│   ├── weekly/                  # 周报
│   └── specs/                   # 需求规格说明
├── testcases/{迭代}/            # 正式归档用例（双路径之二）
├── bugs/{迭代}/{测试人员}/       # 缺陷
├── reports/                     # 测试报告
└── data/                        # 测试数据
```

> **路径自愈约定**：所有 skill 归档/定位时若目录不存在，**自动创建**（不因目录缺失中断流程），路径值一律以本配置为准。

## 读取约定（对 AI / 脚本）

1. **skill 执行第 0 步**统一读取本文件；文件不存在时提示用户运行 `/setup`，或走动态获取（如 workspace_id 通过 `get_user_participant_projects()` 获取）/向用户询问，**不得中断整个流程**
2. Python 脚本（如 `acceptance-report/scripts/*.py`）内置 `load_config()` 自动向上查找 `config/project.config.json`，CLI 参数显式传入时优先于配置
3. 凭证类信息（TAPD token、GLM API Key）**不放本配置**：TAPD token 从 MCP 配置 `~/.qoder/mcp.json` 读取，GLM Key 从用户环境变量 `GLM_API_KEY` 读取
