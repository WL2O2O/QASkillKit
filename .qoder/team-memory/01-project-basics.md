# 01 - 项目基础（技术栈 / 目录 / 归档）

## 项目定位

- 工作区：项目根目录（各成员 clone 位置不同，本文档所有路径均**相对项目根**，勿写死盘符）
- 用途：基于 TAPD 需求的 AI 测试用例设计与执行辅助（个人离线 + 团队协作）
- 当前迭代：hotfix-s91 / s91 / s90 等

## 技术栈

| 组件 | 说明 |
|:---|:---|
| PowerShell 5.1（Windows PowerShell，非 pwsh） | 脚本运行环境，注意 UTF-8 with BOM 编码要求 |
| Python 3 + Pillow + OpenOCR | `.qoder/skills/ocr/scripts/ocr_extract.py` 精读 OCR |
| Windows.Media.Ocr（WinRT） | `.qoder/skills/ocr/scripts/windows-ocr.ps1` 覆盖率 OCR |
| MCP 工具链 | TAPD（mcp-server-tapd）、dbx（数据库）、weknora-knowledge（知识库）、browser-use |
| Git | 项目版本管理，`.qoder/`、`config/`、`demo/`、`examples/`、`workspace/` 均入库；仅 `workspace/personal/drafts/`（个人草稿副本）与各 `local/`（私有）被 .gitignore 排除 |

## 目录结构

```
<项目根>/   # 各成员本地路径不同，下文均相对此目录
├── .qoder\skills\          # 本地 skill（git 追踪，团队共享）
│   ├── testcase-generator\  # 测试用例设计（主力）
│   ├── ocr\                # 三轨协同识图
│   │   └── scripts\         # OCR 脚本（windows-ocr.ps1 / vlm-vision.ps1 / ocr_extract.py，git 追踪团队共享）
│   ├── img-to-mermaid\     # 流程图转 mermaid（本地开发中，未随仓库发布）
│   ├── tseffort\           # 测试工时评估（本地开发中，未随仓库发布）
│   └── weekly-report\      # 周报生成
├── .qoder\team-memory\     # 团队记忆库（本目录）
├── workspace\
│   ├── personal\               # 个人工作产物（仅 drafts/ 草稿副本 gitignore）
│   │   ├── drafts\{迭代}\       # 草稿用例（hotfix 需求与迭代需求同目录，不单独建 hotfix 目录）
│   │   ├── image-cache\{需求ID}\  # TAPD 图片缓存
│   │   ├── weekly\              # 周报产物
│   │   └── specs\               # 需求规格说明
│   ├── testcases\{迭代}\        # 版本化用例归档（正式目录）
│   ├── bugs\{迭代}\{测试人员}\   # 缺陷
│   ├── reports\                  # 测试报告
│   └── data\                     # 测试数据
```

## 归档路径规则

- **测试用例**：`workspace/personal/drafts/{迭代名}/`（草稿）+ `workspace/testcases/{迭代名}/`（正式归档，**目录不存在时自动创建**）
- **hotfix 与迭代同目录**：hotfix 需求用例**不单独创建** hotfix 目录，与迭代需求放同一 `drafts/{迭代名}` / `testcases/{迭代名}` 目录（如 s92 与 s92hotfix 需求都放 s92 目录）
- **姓名子目录由用户自建**：正式目录下按个人姓名分目录（如 `testcases/{迭代名}/{姓名缩写}/`）由用户**自行创建与移动归档**，AI 生成/核查用例时直接归档到迭代目录平铺，不创建姓名目录
- **需求图片缓存**：`workspace/personal/image-cache/{需求ID}/`（随仓库入库，提交前人工检查是否含敏感截图）
- **路径自愈**：目录缺失时 AI 自动创建（mkdir -p），不因目录不存在中断流程；路径值统一取 `config/project.config.json` 的 `archive.*`
- **注意**：`workspace/` 产物整体入库（生成后人工检查再提交），仅 `personal/drafts/`（双路径归档的个人草稿副本）被 .gitignore 忽略；提交前请检查草稿以外的产物（图片缓存/周报/缺陷）是否含敏感内容

## 项目配置中心

- 私有信息（TAPD workspace_id、团队成员、数据库连接、知识库清单、归档路径等）统一存于 `config/project.config.json`（.gitignore 排除），模板见 `config/project.config.example.json`，字段说明见 `config/README.md`
- 各 Skill 执行前先读配置；配置不存在时提示运行 `/setup`，不中断流程
- 团队私有知识（如业务表速查）存于 `.qoder/team-memory/local/`（.gitignore 排除）；ui-automation 各端环境文档存于 `.qoder/skills/ui-automation/references/local/`（.gitignore 排除）

## 环境变量

| 变量 | 作用域 | 说明 |
|:---|:---|:---|
| `GLM_API_KEY` | **用户变量（User scope）** | 智谱 GLM API Key，进程 `$env:` 读不到，需 `[Environment]::GetEnvironmentVariable("GLM_API_KEY","User")` 显式读取注入 |

## PC后台测试账号（供应链示例项目）

> ⚠️ 完整账号清单（测试环境地址 / 账号 / 密码 / 适用场景）为私有信息，存于 `.qoder/team-memory/local/test-accounts.md`（.gitignore 排除，**不入库**）；本文档仅保留规则描述，不出现具体账号名与密码。

- **账号统一原则（2026-08-27 用户指令）**：用例尽量用 **1 个主账号**（**品牌方总账号**）登录（登录后新增员工账号/供应商账号等造数），门店/仓库数据用专用门店账号，大数据量/专用场景按需使用对应专用账号（清单见 local 私有文件）
- **品牌方账号 vs 员工账号**：品牌方总账号**不是员工账号，不能被绑定员工角色**；涉及角色/权限/登录拦截的用例，用主账号登录后在「员工管理」**新增员工账号**（绑定业务员/采购员/拣货员/分拣员/仓管员/门店管理员等角色类型），绑定所需角色后以员工账号为测试对象执行用例
- **账号仅作登录身份**：账号自带/绑定的数据（绑定客户数、经手单据数等）不是测试数据；用例所需数据以**新增为主**（详见 04 测试用例标准），存量数据使用须防变动失效

## 运行环境要求

- Node.js ≥ 18（e2e 测试/脚本运行），依赖安装：`npm install`

## 权威源定义

- **testcase-generator skill 唯一权威源**：`.qoder/skills/testcase-generator/SKILL.md`（用例生成逻辑与输出格式均以此为准，不依赖 `AI测试用例设计指南-MCP版.md`）
- **团队规范权威源**：本目录（`.qoder/team-memory/`），个人记忆仅存个人偏好

## 系统环境

- Windows 11 25H2（10.0.26200），用户 shell 为 Windows PowerShell 5.1
- 终端不支持 `&&` 分隔符，多条命令用 `;`
