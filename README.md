# QASkillKit — QA 全流程技能工具箱

<p align="center">
  🌐 <a href="README.md">中文</a> · <a href="README.en.md">English</a>
</p>

> **QA 全流程 AI 技能包：从原型图到可追溯测试用例**——多轨 OCR 识别需求图 → 自动生成用例（关联变更点）→ 用例与原型逐条一致性核查 → UI 自动化执行回填 → 规范化缺陷/验收报告。
>
> **真实数据驱动，杜绝 AI 幻觉** · **纯 Skill 驱动，零框架代码**——全部能力以 Markdown 技能文档（SKILL.md）+ 少量固化脚本沉淀，可读、可改、可进化。

---

## ✨ 它能做什么

| 环节 | Skill | 触发方式 | 说明 |
|:---|:---|:---|:---|
| 📝 测试用例设计 | `mcpcase` | 输入 TAPD 需求 ID，如 `1019311` | TAPD 拉需求 + 数据库查真实测试数据 + 知识库补业务上下文 + 原型图三轨 OCR 识图，生成结构化用例 |
| 🔍 用例核查 | `case-review` | `核查 1019311` | 用例与原型图逐条比对，有据直接修正，存疑输出待确认报告 |
| 🖥️ UI 自动化测试 | `uitest` | `测试 1019311` | browser-use 驱动浏览器实测网页端用例，智能分组合并执行，结果回填用例文件 |
| 🐞 缺陷报告 | `ai-testbug` | 描述缺陷现象 | 按团队缺陷模板生成规范缺陷文档（三级标题命名/复现步骤/预期实际） |
| 📊 迭代验收报告 | `acceptance-report`（/ys） | `生成 s92 验收报告` | 需求/缺陷统计、未按时提测清单、开发缺陷分布，固化脚本直连 TAPD OpenAPI |
| 📅 周报生成 | `weekly-report`（/zb） | `写周报` | 从 TAPD 拉取本周需求/缺陷动态，按指南生成结构化周报 |
| 🖼️ 三轨 OCR 识图 | `ocr` | 被其他 skill 自动调用 | Windows OCR（覆盖率）+ OpenOCR（精读）+ VLM（结构）三通道交叉验证 |
| ⚙️ 初始化向导 | `setup`（/setup） | 首次使用运行 | 自动探测 TAPD 项目/数据库连接/知识库，生成私有配置 |

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────┐
│                    AI Agent（IDE 内置）                │
│   AGENTS.md 自动加载 → 强制读取配置与团队记忆库           │
├──────────────┬──────────────────┬───────────────────┤
│ .qoder/skills │ .qoder/team-memory│  config/          │
│  技能包（10+）  │  团队记忆库（方法论） │  私有配置中心（唯一） │
│  SKILL.md     │  01~06 主题文档    │  workspace_id/成员 │
│  + 固化脚本    │  + local/（私有）   │  /数据库/知识库      │
├──────────────┴──────────────────┴───────────────────┤
│                    MCP 工具链                          │
│  mcp-server-tapd │ dbx（数据库只读） │ weknora │ browser-use │
└─────────────────────────────────────────────────────┘
```

三层沉淀，越用越聪明：

1. **Skill 层**：每个工作流一个 SKILL.md，步骤、坑点、口径全部显式化，AI 严格照此执行
2. **团队记忆层**（`team-memory/`）：跨 skill 共享的项目规范与踩坑经验，git 提交全团队共享；每次执行遇到新坑自动回灌沉淀
3. **配置层**（`config/`）：全部私有信息（TAPD 项目、团队成员、数据库、知识库）集中一处、gitignore 隔离，**仓库本身零敏感信息**

## 🚀 快速开始

### 前置要求

| 依赖 | 用途 | 必需性 |
|:---|:---|:---|
| [Qoder](https://qoder.com/)（或兼容 AGENTS.md 规范的 AI IDE） | 运行 Agent 与 Skill | ✅ 必需 |
| MCP: `mcp-server-tapd` | TAPD 需求/缺陷/迭代读写 | ✅ 必需 |
| MCP: `dbx` | 数据库只读查询（真实测试数据） | 推荐 |
| MCP: `browser-use` | UI 自动化测试 | uitest 需要 |
| MCP: `weknora-knowledge` | 业务知识库补充 | 可选 |
| Python 3 + Node.js ≥ 18 | 固化脚本/OCR/下载脚本 | ✅ 必需 |

### 三步跑起来

```bash
# 1. 克隆仓库
git clone https://github.com/{你的组织}/QASkillKit.git && cd QASkillKit

# 2. 在 IDE 中配置好 MCP 服务（tapd 必需，其余按需）

# 3. 在 AI 对话框运行初始化向导
/setup
```

`/setup` 会自动探测 TAPD 项目、数据库连接、知识库清单，生成 `config/project.config.json`（gitignore，不会提交）。之后直接开始使用：

```
/mcpcase 1019311        ← 为 TAPD 需求 1019311 生成测试用例
测试 1019311             ← UI 自动化执行该需求的用例
/ys 生成 s92 验收报告     ← 生成迭代验收报告
/zb                     ← 生成本周周报
```

## 🔒 隐私与脱敏设计

本仓库可直接公开，所有私有信息通过三个 gitignore 隔离区管理：

| 位置 | 存放内容 | git 状态 |
|:---|:---|:---|
| `config/project.config.json` | TAPD workspace_id、团队成员、数据库连接、知识库 UUID、归档路径 | 🚫 忽略（模板 `project.config.example.json` 入库） |
| `.qoder/team-memory/local/` | 团队私有知识（如业务表速查） | 🚫 忽略 |
| `.qoder/skills/uitest/references/local/` | 各端测试环境地址/账号规则/端特有坑点 | 🚫 忽略（模板 `env-template.md` 入库） |

凭证类（TAPD token、API Key）不进任何配置文件：token 从 MCP 配置读取，Key 从环境变量读取。密码类一律"每次询问，不记录"。

## 📁 目录结构

```
├── AGENTS.md                    # Agent 全局指令（自动加载，强制读配置+记忆库）
├── config/                      # 私有配置中心（模板入库，真实配置 gitignore）
├── .qoder/
│   ├── skills/                  # 技能包（setup/mcpcase/uitest/acceptance-report/...）
│   │   └── {skill}/SKILL.md     #   每个技能的完整执行规程 + scripts/ 固化脚本
│   └── team-memory/             # 团队记忆库（01~06 主题方法论 + local/ 私有）
├── examples/                    # 脱敏示例（虚构用例格式样例）
├── demo/                        # 真实用例脱敏示例（演示产出质量）
├── workspace/                   # 业务工作区（仅 personal/drafts/ 草稿副本 gitignore，其余入库）
└── _tmp/                        # 临时文件（gitignore）
```

## 🧬 设计理念

- **纯 Skill，零框架**：没有一行需要维护的框架代码，全部能力用自然语言规程 + 少量单文件脚本表达，任何人可读懂、可定制
- **真实数据，禁止虚构**：测试数据必须来自数据库真实查询或需求原文，从源头杜绝 AI 幻觉用例
- **人机协作边界清晰**：AI 禁止写库、禁止执行推送/支付等高危操作，SQL 只输出给人执行
- **经验复利**：每次执行的坑点按端/按主题回灌到 team-memory 与 references，团队越用越强
- **跨 IDE 兼容**：基于通用 AGENTS.md 规范，Qoder / Claude Code 等均可加载

## 🤝 贡献与二次开发

- 新增技能：参照 `.qoder/skills/` 任一 SKILL.md 的结构（使用方式 → 执行流程总览 → 分步规程 → 坑点 → 输出规范）
- 修改规范：直接编辑 `team-memory/` 主题文档，git 提交即团队生效
- 硬性红线：私有信息只进 `config/` 与 `local/`，禁止硬编码进任何入库文件（详见 `AGENTS.md`）

## 📄 License

[MIT](LICENSE)
