# 06 - 迭代验收报告生成规范（acceptance-report）

适用 Skill：`acceptance-report`（/ys）

## 固定项目信息（从配置读取，无需询问）

| 项 | 值 |
|:---|:---|
| 项目负责人 | 取配置 `team.project_owner` |
| 项目名称 | 取配置 `team.project_name` |
| 修改者 | 取配置 `team.report_editor` |
| 协作文档链接（缺陷统计） | 用户未提供时标注"待补充"，不主动询问 |

## 迭代结构

- 一个版本 = 主迭代 `Sprint{版本号}` + 平行迭代 `hotfix-s{版本号}`，缺陷统计必须合并两个迭代，只拉主迭代会漏缺陷
- 迭代 ID 用 `get_iterations` 定位（workspace_id 取配置 `tapd.workspace_id`）

## 未按时提测需求（单清单口径，用户确认）

- 先排除父需求（被其他需求 parent_id 引用的需求无提测要求）
- 提测时间 = 需求状态流转历史（story_changes）中**首次进入"测试中"**的时间
- 未按时 = 满足任一：
  1. 首次进入"测试中" > 提测日
  2. 提测日当天有流转但最晚一条未到"测试中"（含误提测转回）
  3. 整个迭代从未进入"测试中"（备注"从未提测"）
- 按时 = 提测日当天最晚流转已到"测试中"（含其后的验收中/已实现等正常前进，不算误提测）
- 表结构：|序号|需求|提测时间|处理人|备注|；合计条数单独成行置于表格前（`**合计：{N}**`），标题行不含合计

## 开发人员缺陷统计口径

- 修复人 = 缺陷状态流转中最后一次 `in_progress/reopened → resolved` 的变更人（非 current_owner）
- 测试人员（取配置 `team.testers` 名单）只做验证不算修复，命中时回溯更早的非测试修复人
- 剔除【优化】前缀缺陷、被拒绝/转需求/设计如此缺陷
- 统计表头标注口径说明

## 固化脚本（scripts/ 目录，禁止再临时手写）

MCP 未封装列表/变更历史接口，需直连 TAPD OpenAPI。四个脚本均在
`.qoder/skills/acceptance-report/scripts/`，token 自动从
`C:\Users\{USER}\.qoder\mcp.json`（mcpServers.mcp-server-tapd.env.TAPD_ACCESS_TOKEN）读取，**禁止硬编码**。

| 脚本 | 作用 | 关键参数 |
|:---|:---|:---|
| `fetch_lists.py` | 拉需求/缺陷列表（analyze 输入） | `--type stories|bugs --iterations "主迭代ID,hotfix迭代ID" --out 文件.json` |
| `fetch_changes.py` | 拉状态变更历史 | `--type stories|bugs --ids/--ids-file --out` |
| `analyze_testing.py` | 未按时提测统计 | `--changes --stories --tt-date YYYY-MM-DD` |
| `analyze_bugs.py` | 修复人统计+遗留候选 | `--bugs --changes [--exclude 测试人员]` |

数据流：`fetch_lists.py` 拉列表 → 提取 ID → `fetch_changes.py` 拉变更历史 →
`analyze_*.py` 统计 → 结果填入报告。

## 中间数据目录规范（2026-08-10 新增，2026-08-11 修正为 skill 级目录）

- 所有拉取/分析产生的中间文件（`*_stories.json`/`*_bugs.json`/`*_ids.txt`/`*_changes.json`/`*_result.txt`）
  统一输出到 **skill 目录下的 `.qoder\skills\acceptance-report\_tmp\` 子目录**（如 `.qoder\skills\acceptance-report\_tmp\s91_stories.json`），
  **禁止写入 scripts/ 目录或项目根目录 `_tmp\`**：放 skill 子目录可保证各 skill 中间文件隔离、避免互相干扰，
  同时便于按 skill 粒度清理和 .gitignore 配置
- `.gitignore` 已忽略 `_tmp/`（含 skill 子目录下）、`__pycache__/`、`*.pyc`，skill 目录保持只含脚本与文档
- 报告生成完毕后中间文件可保留在 `.qoder\skills\acceptance-report\_tmp\` 备查，或删除该目录下 `s{版本号}_*` 彻底清理
- 坑点：**执行 scripts 脚本一律用 `python -B`**（脚本内 `sys.dont_write_bytecode` 对直接运行的主模块无效，只有 `-B`/`PYTHONDONTWRITEBYTECODE=1` 才彻底阻止生成 `__pycache__`）；Windows 下 DeleteFile 对 pyc 可能假成功，需用 Python `shutil.rmtree` 删

## 关键坑点

- **列表接口返回嵌套结构**：TAPD `/stories`、`/bugs` 返回元素为 `{"Story":{...}}`/`{"Bug":{...}}` 包装，直接 `item.get("id")` 取不到 id 会输出空列表，须先解嵌套（fetch_lists.py 已内置）
- **鉴权**：用 Header `Authorization: Bearer {token}`，access_token 传 URL 参数返回 422
- **变更历史接口包装名不同**：story_changes 的 data 元素用 `WorkitemChange` 包装，bug_changes 用 `BugChange` 包装。`fetch_changes.py` 的 `extract_item` 需同时检查两种（已内置），勿只写一种
- **story_changes 操作人字段为 `creator`**（非 `author`），`analyze_testing.py` 取操作人时需 `change.get("creator")`；bug_changes 操作人字段为 `author`（`analyze_bugs.py` 已正确使用）
- **story_changes 支持批量**（story_id 逗号分隔每批 ≤10，`change_field=status` 过滤）；**bug_changes 必须逐条查**，且 `change_field` 参数无效需本地过滤
- **输出验证**：脚本输出写 UTF-8 文件后读文件验证，勿依赖 GBK 控制台中文
- **story_changes 状态名为中文**（测试中/验收中/已实现），bug_changes 为英文枚举（new/in_progress/resolved...）
- **提测时间不用 modified**（最后操作时间非提测时间），以状态流转历史为准；评论非必填仅作补充证据
