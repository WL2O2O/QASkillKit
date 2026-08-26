---
name: acceptance-report
description: >
  基于 MCP 工具链（mcp-server-tapd）的迭代验收报告生成 Skill，简写为 /ys。
  通过 TAPD 获取迭代信息、需求列表和缺陷列表，结合用户提供的迭代计划/发布计划，
  按验收报告模板（依据历史验收报告提炼）生成结构化验收报告。
  使用场景：需要生成迭代验收报告时，或用户提到 "验收报告"、"验收"、"生成验收"、
  "s{版本号}验收" 或直接提供迭代计划与发布计划时。
---

# 迭代验收报告生成 Skill

## 使用方式

调用格式：

> `/ys Sprint91`
> `/ys Sprint91，【sprint92迭代计划】模块A优化: 需求1、需求2、需求3 客户需求: 客户A、客户B 模块B优化：需求4、需求5 其他优化：UI交互优化、前端系统优化、后端系统优化 【sprint92发布计划】 开始：0806，提测：0815，uat发布：0824（验收到21点） 发布：A端：0825（周二），B端：0826（周三），C端：0827（周四）`

### 第 0 步：读取项目配置

执行前先读取 `config/project.config.json`（字段说明见 `config/README.md`），获取 `tapd.workspace_id`、`team.*`（项目名称/负责人/修改者/测试人员名单）、`product.clients`（各端名称）、`archive.report_dir`（报告输出目录）。配置文件不存在时提示用户运行 `/setup`，或通过 `get_user_participant_projects()` 动态获取 workspace_id / 向用户询问，不得中断流程。下文出现的 `{workspace_id}` 等占位符均指配置中的对应值。

执行本 Skill 时需确认以下信息（若用户未提供则主动询问；项目信息取自配置，无需询问）：
1. **迭代版本**：Sprint 编号（如 Sprint91），用于定位迭代与报告命名
2. **迭代计划**：本迭代主要方向（各业务模块优化、客户需求、其他优化等）
3. **发布计划**：开始日期、提测日期、UAT 发布日期（含截止时间）、各端正式发布日期（端名称参照配置 `product.clients`）
4. **固定项目信息（取自配置 `team.*`，直接使用无需询问）**：项目负责人=`team.project_owner`、项目名称=`team.project_name`、修改者=`team.report_editor`；版本说明从迭代计划提炼（无法提炼时留空由用户补充）
5. **协作文档链接（缺陷统计）**：用户未提供时在报告对应位置标注"待补充"，不主动询问

## 数据来源规范

### TAPD MCP 调用规则

#### 1. 获取迭代信息
- 调用 `get_iterations`：`workspace_id={workspace_id}, options={"name":"{迭代名}"}` 模糊匹配定位迭代
- 记录迭代 ID，用于需求/缺陷查询

#### 2. 获取需求列表
- 调用 `get_stories_or_tasks`：
  - `entity_type`: "stories"（⚠️ 必传，否则返回空）
  - `iteration_id`: 迭代ID
  - `fields`: 至少包含 `id,name,status,owner,modified,creator`
  - `limit`: 100，返回不足时按 `page` 翻页取完
- 需求链接：`https://www.tapd.cn/{workspace_id}/prong/stories/view/{id}`

#### 3. 获取缺陷列表
- ⚠️ **迭代范围**：一个版本通常包含 `Sprint{版本号}`（主迭代）与 `hotfix-s{版本号}`（平行 hotfix 迭代）两个迭代，缺陷统计必须用 `get_iterations` 拉全迭代列表确认后**合并两个迭代的缺陷**，只拉主迭代会漏掉 hotfix 缺陷（如 S90 = 0220 Sprint90 + 0228 hotfix-s90，共 101 条缺陷）
- 调用 `get_bug`（每个迭代分别拉取后合并去重）：
  - `iteration_id`: 迭代ID
  - `fields`: 至少包含 `id,title,status,reporter,current_owner,created,modified,severity,story_id,custom_field_one,custom_field_three,custom_field_five`（⚠️ custom_field_one=开发负责人、custom_field_three=缺陷类型、custom_field_five=缺陷产生原因，用于开发人员缺陷统计）
  - `limit`: 100，返回不足时按 `page` 翻页取完（⚠️ 默认 limit=10，不翻页会漏数据）
- 缺陷链接：`https://www.tapd.cn/tapd_fe/{workspace_id}/bug/detail/{id}`
- 开发人员中文名映射：TAPD 账号名可能为拼音/英文，调用 `get_workspace_users` 获取昵称后再填入报告
- ⚠️ **开发人员缺陷统计数据来源**：`fetch_lists.py --type bugs` 已默认拉取 `custom_field_one,custom_field_three,custom_field_five`；`analyze_bugs.py` 读取这些自定义字段，优先以 `custom_field_one`（开发负责人）为开发人员归属，为空时回退到状态变更修复人

#### 4. 自定义字段
- 涉及 UAT/线上来源、提测时间等统计时，先调用 `get_entity_custom_fields(workspace_id={workspace_id}, options={"entity_type":"bugs"或"stories"})` 获取字段配置，再使用 `custom_field_*` 查询
- ⚠️ **缺陷自定义字段映射**（用于开发人员缺陷统计，`fetch_lists.py` 已默认拉取）：

| TAPD 字段键 | 字段名 | 类型 | 验收报告用途 |
| :--- | :--- | :--- | :--- |
| `custom_field_one` | 开发负责人 | user_chooser | 开发人员列（优先取值，为空回退到状态变更修复人） |
| `custom_field_three` | 缺陷 类型 | multi_select | 主要问题类型列（选项：常规缺陷/UI错误/修改引入缺陷/低级缺陷/用例未执行/需求优化/历史遗留缺陷/环境问题/重复修改缺陷） |
| `custom_field_five` | 缺陷产生原因 | textarea | 缺陷产生原因列（开发填写的根因分析） |

- ⚠️ `custom_field_three`（缺陷类型）的枚举值固定为：`常规缺陷|用例未执行|低级缺陷|重复修改缺陷|需求优化|UI错误|历史遗留缺陷|修改引入缺陷|环境问题`

#### 5. 需求状态变更历史（提测时间判定首选）
- 提测时间 = 需求状态流转历史中首次进入"测试中"（status_2）的时间；TAPD 评论非必填，无法覆盖全部流转，必须用状态变更历史接口
- 调用 TAPD OpenAPI（非 MCP 工具）：`GET https://api.tapd.cn/story_changes`
  - 参数：`workspace_id={workspace_id}`、`story_id={需求ID}`（支持逗号分隔多 ID 批量，建议每批 10 个）、`change_field=status`（只返回状态变更）、`limit=100` + `page` 翻页
  - 鉴权：Header `Authorization: Bearer {TAPD_ACCESS_TOKEN}`（⚠️ access_token 传 URL 参数会返回 422；token 从 MCP 配置 mcp.json 的 mcp-server-tapd.env 读取，勿硬编码/写入文档）
  - 返回：`data[].WorkitemChange`，取 `field_changes[]` 中 `field=status` 的记录：`created`=流转时间、`value_before_parsed/value_after_parsed`=流转前后状态、`creator`=操作人；每条需求完整时间线按 created 排序

#### 6. 缺陷状态变更历史（开发人员缺陷统计修复人判定）
- 统计口径：缺陷修复人 = 状态流转中进入"已解决"（resolved）的变更人，需拉取缺陷状态变更历史判定（`current_owner` 是最后处理人，可能被测试验证操作污染，不用于统计）
- 调用 TAPD OpenAPI（非 MCP 工具）：`GET https://api.tapd.cn/bug_changes`
  - 参数：`workspace_id={workspace_id}`、`bug_id={缺陷ID}`（⚠️ 逐条单查，批量逗号分隔会覆盖不全）、`limit=100` + `page` 翻页
  - ⚠️ `change_field=status` 参数无效（返回全部字段变更），需本地过滤 `field_changes[].field == "status"`
  - 鉴权：同第 5 节 `Authorization: Bearer`
  - 返回：`data[].WorkitemChange`，`field_changes[]` 中 `field=status` 的记录：`created`=流转时间、`value_before_parsed/value_after_parsed`=流转前后状态（英文枚举：new/in_progress/resolved/verified/rejected/closed/reopened）、`author`=操作人（中文名）
  - 状态流转链为 `new → in_progress → resolved → verified`，不存在直接的 new→resolved；修复人 = 每条缺陷最后一次 `in_progress→resolved` 或 `reopened→resolved` 的 `author`，若为测试人员则回溯更早的非测试修复人
  - ⚠️ Windows 控制台输出中文乱码是 GBK 显示问题，数据本身正常：写 UTF-8 文件后用文件读取验证（用 Python urllib 请求，避免 PowerShell Invoke-RestMethod 编码问题）

#### 7. 状态变更历史脚本（推荐，替代临时手写脚本）
- ⚠️ MCP (mcp-server-tapd) 未封装 `story_changes`/`bug_changes` 接口，必须直连 TAPD OpenAPI；历史每次临时写 Python 脚本，现已固化到 `scripts/` 目录，直接调用即可，无需再手写
- 脚本清单（位于 `scripts/` 下，PowerShell 调用 `python scripts/{脚本名}.py ...`，输出写 UTF-8 文件后用文件读取验证，不要依赖控制台中文）
  - `fetch_lists.py`：拉取需求/缺陷列表（analyze 脚本的输入）。`--type stories|bugs`（必选）、`--iterations "迭代ID1,迭代ID2"`（主迭代+hotfix 迭代逗号分隔合并去重，必选）、`--out 输出.json`（必选，格式 `{"data":[...]}`）、可选 `--workspace`（默认读取 `config/project.config.json` 的 `tapd.workspace_id`）、`--fields` 覆盖默认字段（默认已含分析所需字段）；⚠️ TAPD 返回元素为 `{"Story":{...}}`/`{"Bug":{...}}` 嵌套结构，脚本自动解嵌套取 id 去重，输出保留原始嵌套结构（analyze 脚本兼容）
  - `fetch_changes.py`：拉取状态变更历史。`--type stories|bugs`（必选）、`--ids "id1,id2"` 或 `--ids-file 文件`（二选一）、`--out 输出.json`（必选）、可选 `--workspace`（默认读取配置）；token 自动从 `~/.qoder/mcp.json` 的 mcp-server-tapd.env 读取（勿硬编码）；story 模式默认按 `change_field=status` 过滤，`--all-fields` 可拉全部字段；bug 逐条查询
  - `analyze_testing.py`：未按时提测统计（单清单口径）。`--changes story_changes.json --stories 需求列表.json --tt-date YYYY-MM-DD [--out 结果.txt]`；自动识别父需求（parent_id 反查）排除、"测试中→验收中→已实现"正常前进不算误提测、超期提测/当天未到测试中/从未提测三类判定；输出未按时清单（含首次测试中时间、操作人）
  - `analyze_bugs.py`：缺陷修复人统计 + 版本遗留候选。`--bugs 缺陷列表.json --changes bug_changes.json [--exclude 测试人员名单，默认读取配置 `team.testers`] [--out 结果.txt]`；修复人 = 最后一次 in_progress/reopened→resolved 的 author（测试人员自动回溯），自动剔除【优化】类与 new/reopened/in_progress 遗留
  - `fetch_relations.py`：缺陷→需求关联关系查询（Relations API）。`--bug-ids "id1,id2"` 或 `--bug-ids-file 文件`（必选其一）、`--out 输出.json`（必选）、可选 `--workspace`（默认读取配置）；每个 bug 调用一次 `/relations?source_type=bug&source_id={bid}`，返回 `{bug_id: story_id | null}` 映射；token 自动读取 mcp.json（勿硬编码）；适用于 `story_id` 字段为空时补全 bug→story 关联
- 输入数据来源：需求/缺陷列表用 `fetch_lists.py` 直连 OpenAPI 拉取保存为 JSON（勿再用 MCP 返回数据手工转录，易丢字段），提取 ID 传给 `fetch_changes.py`；需求列表 JSON 需含 `id/name/owner/status/parent_id` 字段（parent_id 用于父需求识别）
- 数据流：`fetch_lists.py` 拉列表（--iterations 传主迭代+hotfix 迭代）→ 提取 ID → `fetch_changes.py` 拉变更历史 / `fetch_relations.py` 拉 bug→story 关联 → `analyze_testing.py` / `analyze_bugs.py` 统计 → 结果填入报告
- ⚠️ **中间数据目录规范**：所有拉取/分析产生的中间文件（`*_stories.json`/`*_bugs.json`/`*_ids.txt`/`*_changes.json`/`*_result.txt`/`*_bug_story_map.json`）统一输出到 skill 目录下的 `.qoder\skills\acceptance-report\_tmp\` 子目录（如 `.qoder\skills\acceptance-report\_tmp\s91_stories.json`），**禁止写入 scripts/ 目录或其他非 _tmp 目录**（.gitignore 已忽略 `_tmp/`，skill 目录保持只含脚本与文档）；⚠️ 中间文件仅为脚本流水线传递数据的临时产物，**报告生成完毕后立即清理当前版本全部中间文件（`s{版本号}_*`），_tmp 目录保持为空、不残留任何文件**；生成新报告前也先清理当前版本旧中间文件，避免旧数据干扰新统计（清理时机详见执行流程第三步、第五步）
- ⚠️ **脚本运行方式**：执行 scripts 下的脚本一律用 `python -B scripts/xxx.py ...`（`-B` 禁止生成 `__pycache__`，⚠️ 脚本内 `sys.dont_write_bytecode` 对直接运行的模块本身无效，只有 `-B`/环境变量 `PYTHONDONTWRITEBYTECODE=1` 能彻底阻止）

#### 8. 缺陷-需求关联关系查询（Relations API）
- ⚠️ **背景**：TAPD Bug 的 `story_id` 字段仅在通过需求关联创建缺陷时自动填充，直接在 Bug 模块创建的缺陷此字段常为空（如 Sprint88 的 110 条缺陷中仅 5 条有值）。缺陷与需求的真实关联存储在 TAPD 的 `/relations` 表中（`source_type=bug, target_type=story`），需要通过 Relations API 逐条查询。
- 调用 TAPD OpenAPI：`GET https://api.tapd.cn/relations?workspace_id={workspace_id}&source_type=bug&source_id={bug_id}&limit=10`
  - 参数：`workspace_id`、`source_type=bug`、`source_id={缺陷完整ID}`（⚠️ 19 位完整 ID，非后 7 位）、`limit=10`
  - 鉴权：Header `Authorization: Bearer {TAPD_ACCESS_TOKEN}`（同 story_changes/bug_changes）
  - 返回：`data[].Relation`，包含 `source_type`（固定 bug）、`source_id`、`target_type`（story 或 bug）、`target_id`；筛选 `target_type=story` 的记录即关联需求
- ⚠️ **使用方式**：直接用 `scripts/fetch_relations.py`（已封装上述逻辑），无需手动查接口
- **注意事项**：
  - 需求数量统计时要注意：一个缺陷可能关联到历史迭代的需求（如 Sprint88 的缺陷关联到 Sprint87 的需求），这类跨迭代缺陷仍应计入当前迭代的缺陷统计，并在备注中标注"含历史迭代关联缺陷"
  - 无关联的缺陷（relations 查询返回 null）通常是手动创建且未手动关联需求的 bug，单独统计数量在报告中备注即可
  - `fetch_relations.py` 默认限制每个 bug 查询 10 条 relations 记录（limit=10），一般足够（单个 bug 很少关联超过 10 条），如需调整可修改脚本中的 limit 参数

## 验收报告模板

完整模板见 [template.md](template.md)，依据团队历史验收报告提炼，生成时严格按模板结构填充。

## 各章节填写规则

### 表头项目信息

| 字段 | 来源 |
| :--- | :--- |
| 版本编号 | `Sprint{版本号}-hotfix{版本号}` |
| 版本日期 | 开始日期 - 实际发布日期 |
| 版本说明 | 迭代计划概述（如"此版本主要以迭代优化和客户需求"） |
| 其他日期 | 用户提供的发布计划 |

### 问题比较多的需求

- ⚠️ **数据来源**：缺陷与需求的关联优先从 **Relations API** 获取（参见数据来源规范第 8 节），而非直接依赖 `bug.story_id` 字段（该字段在直接在 Bug 模块创建的缺陷中常为空，如 Sprint88 中 105/110 条为空）
- **获取方式**：调用 `scripts/fetch_relations.py --bug-ids-file .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_ids.txt --out .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_story_map.json` 生成 bug→story 映射；再用该映射按 story_id 分组统计缺陷数量，缺陷数量 ≥ 5 的需求列入（阈值可让用户调整）
- **回退策略**：Relations API 查询结果中仍无关联的缺陷（通常是手动创建但未关联需求的缺陷），按 `bug.story_id` 字段补充统计；仍然无关联的缺陷不计入"问题比较多的需求"章节（可在项目测试总结中备注未关联需求数）
- 需求标题、处理人（`@需求owner` 格式）从 TAPD 需求表反查
- 备注：可写缺陷数量或留空；跨迭代关联缺陷备注"含历史迭代关联缺陷"

### 未按时提测需求（合计：N 条）

- 判定模型（用户确认，单清单口径：原"提测日截止后提测需求"模块已删除，内容合并入本清单）：
  - ⚠️ **先排除父需求**：父需求（存在其他需求 parent_id 指向它）无提测要求，不计入提测统计；识别方式：拉迭代需求后按 parent_id 反查，被引用的需求即父需求
  - 提测时间 = 需求状态流转历史中首次进入"测试中"状态的时间（⚠️ story_changes 的 `value_after_parsed` 返回中文状态名如"测试中"/"验收中"/"未开始"，非枚举码）
  - 未按时提测需求 = 满足以下任一：
    1. 首次进入"测试中"时间 > 提测日（超过提测日才提测，即原"提测日截止后提测"，合并入本清单）
    2. 提测日当天有状态流转但最晚一条未到"测试中"（仍在实现中/未开始/规划中等；含误提测后转回实现中/其他状态且当天未再转回测试中的场景）
    3. 整个迭代从未进入"测试中"（遗留未完成），备注"从未提测"
  - 按时提测判据：提测日当天最晚流转已到"测试中"（含其后的验收中/已实现等）→ 按时（⚠️ "测试中→验收中"属正常前进，不算误提测）；提测日当天无流转且首次进入"测试中" < 提测日 → 按时（提前提测）
- 提测时间获取（按优先级）：
  1. 需求状态变更历史（首选，完整覆盖所有流转、含未填评论的流转）：调用 TAPD OpenAPI `story_changes`（见数据来源规范第 5 节），取每条需求首次 `value_after_parsed="测试中"` 的 `created` 即提测时间；同时提取提测日当天的全部流转，取最晚一条判断当天是否已转测试中
  2. 状态流转评论（仅补充证据，评论非必填）：`get_comments(entry_type="stories", entry_id={需求ID}, limit=500)`，筛选 title 含"测试中"的评论——"流转状态从 [X] 到 [测试中] 添加"（自动流转记录）或"在状态 [测试中] 添加"（开发提测说明），评论 created 时间即提测时间；无评论不代表未提测
  3. 客观判据：需求 `created`（创建时间）> 提测日 → 必然未按时提测，用状态变更历史确认首次测试中时间后列入
- 误提测场景：状态流转历史出现"测试中 → 实现中/其他状态"（含再回到"测试中"的返工），说明曾误提测/返工；判定以提测日当天最晚状态流转为准（当天最晚已回到测试中→按时），备注中说明转回情况
- 表结构：|序号|需求|提测时间|处理人|备注|，备注列写"操作人：{提测变更人}"；合计条数 = 列表实际条数，**单独成行置于表格前**（格式：**合计：{N}**，如 **合计：13**）；无法取全时标注"其余待人工核对"；标题中不含"待确认"字样，避免阅读疑惑
- 无满足项时保留空行

### 版本遗留问题

- 数据来源：该迭代缺陷中状态未关闭（非 resolved/verified/closed）且确认遗留到下版本的缺陷
- **判定口径（用户确认）**：状态没有变更（从未进入 resolved）的缺陷即算遗留——包括状态仍为 new（新/未处理）、reopened（重新打开）、in_progress（进行中）的缺陷；此类缺陷不参与"共处理缺陷"统计（去掉已关闭/已拒绝/未处理状态时一并排除），但需在版本遗留问题中列出
- 格式：缺陷标题 + 换行 TAPD 链接 + 处理人（`@修复人`）+ 备注（遗留原因，如"91修复上线"）
- 无法自动判定遗留时，列出候选缺陷请用户确认后填入

### UAT发现的问题 / 线上发现的问题

- 数据来源：缺陷来源/环境自定义字段（需先 `get_entity_custom_fields` 确认字段是否存在）；无法获取时默认留空由用户补充
- 格式：序号、发现问题、处理人、原因、如何解决/措施、备注

### 开发人员缺陷统计

- ⚠️ **数据来源（用户确认）**：数据直接取自 TAPD 缺陷的自定义字段，而非 AI 推断或企微文档：

| 报告列 | TAPD 数据来源 | 说明 |
| :--- | :--- | :--- |
| 开发人员 | `custom_field_one`（开发负责人） | 优先取自定义字段值；为空时回退到状态变更修复人（状态流转中进入"已解决"的变更人） |
| 缺陷数量 | 按开发人员分组统计 | `analyze_bugs.py` 自动统计 |
| 缺陷产生原因 | `custom_field_five`（缺陷产生原因） | 开发填写的根因分析原文，逐条列出按频次排序（如"抖音核销遗留bug（1次）、UI错误/细节（5次）"） |
| 主要问题类型 | `custom_field_three`（缺陷 类型） | multi_select 枚举值，去重后汇总关键词（如"精度计算、UI对齐、组件复用"） |
| 建议改进方向 | AI 基于缺陷产生原因+类型自动生成 | 从具体原因关键词匹配精准建议，编号列出（如"1. 金额计算涉及精度必须使用 decimal 类型"） |

- **统计口径（用户确认）**：
  - **不统计已关闭（closed）的缺陷**：缺陷状态为 `closed` / `已关闭` 的不参与统计
  - **不统计缺陷类型为"历史遗留缺陷"的缺陷**：`custom_field_three` 含"历史遗留缺陷"的不参与统计
  - 取缺陷状态流转中进入"已解决"（resolved）状态的变更人（修复人）归属，而非 `current_owner`（最后处理人）
  - **剔除测试工程师**：若最后一次修复人是测试人员（配置 `team.testers` 名单），回溯更早的非测试修复人
  - **剔除优化类缺陷（用户口径）**：title 以 `【优化】` 开头的缺陷为优化类，不计入缺陷统计
  - 被拒绝（rejected）/转需求/设计如此/无流转的缺陷无修复人，不计入开发人员统计
- **analyze_bugs.py 输出结构**（详见脚本注释）：
  - 一、开发人员缺陷统计汇总表（直接用于报告填充）
  - 二、缺陷明细列表（按开发人员分组：缺陷类型、缺陷产生原因、关联需求、标题）
  - 三、缺陷分析总结（类型分布、原因归类、全局改进建议、Top 开发人员）
  - 四、已关闭缺陷清单
  - 五、历史遗留缺陷类型清单（不进统计）
  - 六~八、版本遗留/优化/无修复人清单
- 报告表头建议标注统计口径，如：`（统计口径：Sprint{版本号} + hotfix-s{版本号} 两个迭代；开发人员取自 TAPD 自定义字段"开发负责人"，为空回退到状态变更修复人；已剔除测试工程师验证操作记录、已关闭缺陷、缺陷类型为"历史遗留缺陷"的缺陷；标题以【优化】开头的优化类缺陷不计入；被拒绝/转需求/设计如此类缺陷未计入，合计 N 条）`
- ⚠️ 生成报告时：从 `analyze_bugs.py` 输出的一、三部分提取数据填入报告主表 + 项目测试总结；二部分（缺陷明细）作为附录供参考，不强制写入报告正文（可让用户确认是否需要）

### 项目测试总结及建议

- 基于数据生成初稿：
  - 本迭代共处理缺陷 N 条（⚠️ 口径：合并主迭代+hotfix 平行迭代的总缺陷，去掉已关闭（closed）/已拒绝（rejected）/新（new）/重新打开（reopened）状态缺陷，再去掉标题以【优化】开头的优化类缺陷以及缺陷类型为"历史遗留缺陷"的缺陷，与开发人员缺陷统计表合计一致），其中需求缺陷 N 条（对比上迭代需求缺陷 N 条，计算上涨/下降百分比）
  - 完成测试的需求、优化条数
  - ⚠️ **缺陷分析总结**：从 `analyze_bugs.py` 输出第三部分提取——缺陷类型分布、缺陷产生原因归类、全局改进建议、Top 开发人员，直接纳入项目测试总结
  - ⚠️ 性能测试结果不默认生成，仅当本次迭代有性能专项测试时由人工补充
  - ⚠️ 各端稳定版本号：端名称根据本期需求标题前缀识别（对照配置 `product.clients` 列表，逐行列出），版本号留占位符由人工填写；标题中不含"待确认"字样，避免阅读疑惑
- ⚠️ 需求缺陷数由 Relations API 获取 bug→story 映射后自动统计，不再依赖 bug.story_id 字段；对于 Relations 仍无关联的缺陷，单独备注"未关联需求缺陷 N 条"

### 提测日截止后提测需求

- ⚠️ **该模块已按用户要求删除**：不再单独成章，内容（首次进入"测试中"时间 > 提测日的需求）合并进"未按时提测需求"章节统一统计

## 文件规范

- 文件名：`s{版本号}验收.md`（如 s91验收.md）
- 文件输出路径：配置 `archive.report_dir` 目录（默认 `workspace/reports/`），目录不存在时自动创建

## 执行流程

### 第一步：确认输入信息
- 确认：迭代版本、迭代计划、发布计划、项目信息、企微文档链接
- 若用户已全部提供，跳过确认

### 第二步：获取迭代信息
- `get_iterations` 匹配目标迭代，记录迭代 ID

### 第三步：获取需求数据
- ⚠️ **清理旧中间文件**：生成新报告前，先删除 `.qoder\skills\acceptance-report\_tmp\` 下当前版本号的旧中间文件（`.qoder\skills\acceptance-report\_tmp\s{版本号}_*`），避免上次运行的残留干扰本次统计（如旧 relations 映射导致分组错误）；仅清理当前版本号匹配的文件，不删其他版本的中间数据
- `get_iterations` 已定位的迭代 ID，调用 `scripts/fetch_lists.py --type stories --iterations "{主迭代ID},{hotfix迭代ID}" --out .qoder\skills\acceptance-report\_tmp\s{版本号}_stories.json` 拉取需求列表（多迭代自动合并去重，详见数据来源规范第 7 节；⚠️ 中间文件统一输出到 `.qoder\skills\acceptance-report\_tmp\`，勿写入 skill 目录）
- 提取需求 ID 列表（写入 `.qoder\skills\acceptance-report\_tmp\s{版本号}_story_ids.txt`），调用 `scripts/fetch_changes.py --type stories --ids-file .qoder\skills\acceptance-report\_tmp\s{版本号}_story_ids.txt --out .qoder\skills\acceptance-report\_tmp\s{版本号}_story_changes.json` 拉取状态变更历史，再调用 `scripts/analyze_testing.py --stories .qoder\skills\acceptance-report\_tmp\s{版本号}_stories.json --changes .qoder\skills\acceptance-report\_tmp\s{版本号}_story_changes.json --tt-date {提测日} --out .qoder\skills\acceptance-report\_tmp\s{版本号}_testing_result.txt` 统计"未按时提测需求"（详见数据来源规范第 7 节）

### 第四步：获取缺陷数据
- 调用 `scripts/fetch_lists.py --type bugs --iterations "{主迭代ID},{hotfix迭代ID}" --out .qoder\skills\acceptance-report\_tmp\s{版本号}_bugs.json` 拉取缺陷列表（⚠️ 必须含主迭代+hotfix 平行迭代，否则漏缺陷；默认已拉取 custom_field_one（开发负责人）、custom_field_three（缺陷类型）、custom_field_five（缺陷产生原因））
- 提取缺陷 ID 列表（写入 `.qoder\skills\acceptance-report\_tmp\s{版本号}_bug_ids.txt`），调用 `scripts/fetch_relations.py --bug-ids-file .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_ids.txt --out .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_story_map.json` 查询缺陷→需求关联（后续"问题比较多的需求"按此映射分组统计，而非直接依赖 bug.story_id 字段）
- 继续用缺陷 ID 列表调用 `scripts/fetch_changes.py --type bugs --ids-file .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_ids.txt --out .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_changes.json` 拉取变更历史
- 调用 `scripts/analyze_bugs.py --bugs .qoder\skills\acceptance-report\_tmp\s{版本号}_bugs.json --changes .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_changes.json --bug-story-map .qoder\skills\acceptance-report\_tmp\s{版本号}_bug_story_map.json --out .qoder\skills\acceptance-report\_tmp\s{版本号}_bugs_result.txt` 统计：① 开发人员缺陷汇总表（含缺陷产生原因/主要问题类型/建议改进方向）② 缺陷明细 ③ 缺陷分析总结 ④ 版本遗留候选（详见数据来源规范第 7 节）
- 按状态筛选"版本遗留问题"（不确定时列候选请用户确认）

### 第五步：生成验收报告
- 按 template.md 模板填充各章节，无法自动生成/需人工确认的内容明确标注（"待人工复核"）
- 保存到 `{archive.report_dir}\s{版本号}验收.md`
- 生成后向用户汇报：数据来源与统计口径、待人工补充项清单
- ⚠️ **报告生成完毕后清理中间文件**：删除 `.qoder\skills\acceptance-report\_tmp\` 下当前版本全部中间文件（`s{版本号}_*`），_tmp 目录保持为空、不残留文件（中间文件仅为脚本流水线的临时数据，统计结果已全部写入报告，无需保留）

## 关键坑点

| 坑点 | 影响 | 规避 |
| :--- | :--- | :--- |
| `get_stories_or_tasks` 不传 entity_type | 返回空 | options 必传 `entity_type: "stories"` |
| `get_stories_or_tasks` 用数字 iteration_id 过滤 | 只返回父需求（漏子需求，77条只剩40条） | 用 `iteration_name: "%Sprint90%"` 模糊匹配取全 |
| `get_bug` 的 iteration_id 传数字 | 只返回部分旧缺陷（88条只剩20条） | iteration_id 必须传字符串形式（19 位长 ID 字符串） |
| `get_bug` 传 iteration_name | 参数被忽略，返回全 workspace 缺陷 | 只用字符串 iteration_id 过滤 |
| `get_bug` 默认 limit=10 | 缺陷数据不全 | 显式传 `limit: 100` 并翻页取完 |
| stories `custom_field_three`（提测日期）常为空 | 未按时提测需求无法自动判定 | 优先用需求状态变更历史 `story_changes`（首次进入"测试中"的 created 即提测时间；提测日当天取最晚一条流转判断是否已转测试中），评论/创建时间仅作补充；无需依赖提测日期字段 |
| `get_comments` 的 created 过滤参数无效 | 按时间范围筛选评论失效（返回全量或最新） | 不传 created，用 `limit: 500` + `page` 翻页全量拉取后本地筛选 |
| `get_comments` 的 order 参数无效 | 排序不生效 | 依赖默认倒序（created desc），不要传 order |
| `get_comments` 的 title 精确匹配 | 按关键词筛评论返回空 | title 不用做筛选条件，全量拉取后本地按 title 过滤 |
| 状态流转时评论非必填 | 评论无法覆盖全部状态流转，基于评论判定提测时间会漏判/误判（如 07-07 深夜提测无评论，或 07-10 补充说明被误当提测） | 提测时间一律以 `story_changes` 状态变更历史为准；评论仅作补充证据，不得据此断言未按时 |
| `story_changes` 用 access_token URL 参数 | 返回 422 | 用 Header `Authorization: Bearer {TAPD_ACCESS_TOKEN}` |
| `story_changes` 未过滤 change_field | 返回全部字段变更，数据量大 | 传 `change_field=status` 只取状态流转 |
| MCP 未封装 story_changes/bug_changes | 每次临时手写 Python 脚本，逻辑重复且易错 | 直接用 `scripts/` 目录固化脚本：`fetch_lists.py` 拉列表 + `fetch_changes.py` 拉数据（token 自动读取 mcp.json）+ `analyze_testing.py`/`analyze_bugs.py` 统计，勿再手写 |
| TAPD 列表接口返回嵌套结构（`{"Story":{...}}`/`{"Bug":{...}}`） | 直接 `item.get("id")` 取不到 id，脚本输出空列表 | `fetch_lists.py` 已内置解嵌套取 id 去重；手写脚本时注意解嵌套或复用 `extract_item` |
| bug_changes 包装名为 `BugChange` 而非 `WorkitemChange` | `extract_item` 只检查 WorkitemChange 导致 bug_changes 解包失败，analyze_bugs 拿到 {"BugChange":{...}} 整体，`field` 取不到 → 误判 0 修复人 | `fetch_changes.py` 的 extract_item 同时检查 `WorkitemChange` 和 `BugChange`（已修复） |
| story_changes 操作人字段为 `creator` 而非 `author` | `analyze_testing.py` 取操作人恒为空 | analyze_testing 用 `change.get("creator")`（已修复）；bug_changes 的字段为 `author`（analyze_bugs 已正确） |
| TAPD 账号为拼音/英文 | 统计表人名对不上 | 用 `get_workspace_users` 映射中文昵称 |
| 遗留缺陷自动判定不可靠 | 遗漏/误列 | 列候选缺陷请用户确认 |
| 缺陷原因/建议类字段 | AI 无法精确归纳 | 优先取 TAPD 自定义字段 `custom_field_five`（缺陷产生原因）和 `custom_field_three`（缺陷类型）；`analyze_bugs.py` 已内置关键词归类与建议生成逻辑 |
| 缺陷自定义字段未拉取 | 开发人员/缺陷类型/缺陷产生原因列均为空 | `fetch_lists.py --type bugs` 默认字段已包含 `custom_field_one,custom_field_three,custom_field_five`；如 TAPD 未配置这些字段需人工补充 |
| 提测时间无直接字段 | 筛选口径不准 | 用需求状态变更历史首次进入"测试中"的 created；不用 modified 近似（modified 是最后操作时间，非提测时间） |
| `bug.story_id` 字段在 Bug 模块直接创建的缺陷中常为空 | "问题比较多的需求"按 story_id 分组统计漏掉大量缺陷（Sprint88 中 105/110 条为空） | 调用 `fetch_relations.py` 通过 Relations API 补全 bug→story 映射，不要依赖 story_id 字段 |
| `/relations` 接口默认只返回最新 N 条记录（如 91 条） | 全量拉取 `/relations?limit=100` 只拿到最新记录，较旧的 bug→story 关系查不到 | 必须按 `source_type=bug&source_id={bid}` 逐条查询每个 bug 的 relations，不能用全量拉取 |
| `/relations` 接口需要 19 位完整 bug ID | 7 位短 ID 查不到关系 | 必须使用 TAPD 完整 19 位 ID，非后 7 位 |
