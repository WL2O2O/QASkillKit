# 团队记忆库（Team Memory）

> 本目录是**项目级共享记忆**，随 git 提交、团队成员可共同维护。
> 与个人记忆（存储在 AI 助手本地）互补：**个人记忆 = 个人偏好**，**本目录 = 团队资产与项目规范**。

## ⚠️ 对 Agent 的强制要求（2026-08-11 新增）

本目录在 Qoder 中由项目根 `AGENTS.md` **自动加载**。任何 agent（无论是否调用 skill）开始处理本项目任务前，**必须**：

1. **先读本 README**（索引文件，定位本目录结构与文件清单）
2. **按当前任务相关主题**读取对应主题文件（文件索引表见下节）
3. **遵循团队沉淀的规范与坑点**，不得绕过或自行用其他流程替代
4. **优先以本目录为准**——个人记忆仅存个人偏好，不得覆盖团队规范；如有冲突以本目录最新内容为准

即使在没有 `AGENTS.md` 的环境（如成员未拉取最新代码）下，agent 主动打开本 README 时也应遵守上述要求。

## 使用规则

- **AI 调用 Skill 时**：先通读 `README.md`（索引），再按需读取对应主题文件
- **团队成员**：直接编辑/补充本目录文件，git 提交后全团队可见
- **写入要求**：每条经验需包含「场景 → 方法 → 坑点」，避免只有结论没有上下文

## 文件索引

| 文件 | 主题 | 适用 Skill |
|:---|:---|:---|
| [01-project-basics.md](01-project-basics.md) | 项目技术栈、目录结构、归档路径 | 全部 |
| [02-ocr-pipeline.md](02-ocr-pipeline.md) | OCR 三轨协同、脚本修复经验、GLM 通道 | ocr / mcpcase |
| [03-mcp-toolkit.md](03-mcp-toolkit.md) | TAPD / dbx / weknora MCP 调用规范与坑点、TAPD 原生 API | mcpcase / weekly-report / tseffort |
| [04-testcase-standard.md](04-testcase-standard.md) | 测试用例命名、头部结构、分类组织、双端复用、归档规范 | mcpcase / ai-testcase-design |
| [05-report-and-effort.md](05-report-and-effort.md) | 周报统计规则、测试工时评估规范（上限 2.5h） | weekly-report / tseffort |
| [06-acceptance-report.md](06-acceptance-report.md) | 验收报告固定项目信息、提测/缺陷统计口径、固化脚本清单与坑点 | acceptance-report |
| [07-tapd-attachment-upload.md](07-tapd-attachment-upload.md) | TAPD 需求附件上传 7 步工作流（browser-use，3 层隐藏控件处理） | mcpcase / ai-testcase-design / uitest |
| [08-ai-evolution.md](08-ai-evolution.md) | AI 能力进化与经验沉淀机制：主动发现问题→评估→确认后升级；坑点须固化到 Skill 强制规则 | 全部 |

## 维护日志

| 日期 | 内容 |
|:---|:---|
| 2026-08-06 | 初始化团队记忆库，从个人记忆沉淀项目级资产 |
| 2026-08-06 | 补充：周报统计与工时评估规范（05）、TAPD 原生 API 查询（03）、用例分类/双端复用/表述规范（04） |
| 2026-08-06 | OCR 脚本统一迁移至 `.qoder/skills/ocr/scripts/`（三轨全覆盖，git 追踪团队共享）；02 新增调用坑点（cd 目录 + 分号分隔 + 相对路径），同步个人记忆 |
| 2026-08-06 | 新增临时文件清理规范：mcpcase 流程末尾自动删除图片缓存，02 新增专项章节 + .gitignore 补充 `_tmp/` 模式 |
| 2026-08-07 | 归档规则更新：hotfix 需求不再单独建 `hotfix-{迭代}testcase` 目录，与迭代需求同目录存放；正式目录姓名子目录（姓名/姓名缩写）由用户自行创建，AI 归档不建姓名目录 |
| 2026-08-10 | windows-ocr.ps1 升级：内置词典纠错+可疑行标记+几何排序（`-NoSort/-NoMerge/-NoFix/-NoMark` 兜底，PS5.1 bbox 不可用自动降级）；mcpcase 8.3 回灌 case-review 识图强化点（浅灰小字/双色标注/大图 bbox），图片缓存改为生成后默认保留 |
| 2026-08-10 | case-review 增加"优先复用图片缓存"：按 TAPD `<img>` basename 匹配 `需求图片缓存/{需求ID}/` 同名文件，全部命中跳过下载；下载统一原始文件名（禁止自定义重命名）；ocr 新增"词典维护规范"：持续更新 + 50 条上限 + BOM 转码 + fixes 验证 + 字面映射收录原则（实测新增"胸物车/按im去重"），02 同步记录 |
| 2026-08-10 | 新增 06-acceptance-report.md：验收报告固定项目信息、未按时提测单清单口径、缺陷修复人统计口径、4 个固化脚本（fetch_lists/fetch_changes/analyze_testing/analyze_bugs）与坑点；删除 .workbuddy 临时目录 |
| 2026-08-10 | 修复 fetch_changes.py extract_item 未处理 BugChange 包装名 + analyze_testing.py 操作人字段 author→creator；06/SKILL.md 坑点同步补充 |
| 2026-08-11 | 创建项目根 `AGENTS.md`：强制 agent 每次对话前通读 team-memory，跨 IDE 兼容（Qoder/Claude Code/通用 AGENTS.md 规范）；README 顶部新增"对 Agent 的强制要求"段作为双轨保障；team-memory/06 中间数据目录从"项目根 _tmp"修正为"skill 级目录 _tmp"与 acceptance-report SKILL.md 对齐 |
| 2026-08-27 | 新增 07-tapd-attachment-upload.md：TAPD 需求附件上传 7 步标准工作流（S93 九需求 9/9 验证），沉淀 3 层隐藏控件（+ 按钮 visibility / panel 屏幕外定位 / upload-input display:none）处理方法与 `sort:不允许为空` 坑点解法 |
| 2026-08-29 | 新增 08-ai-evolution.md：AI 主动发现问题→评估升级价值→需要升级时先向用户确认；坑点记忆约束力不足，必须固化到 Skill 强制规则（案例：mcpcase 文件名安全化 + review 有据直接修正模式） |
