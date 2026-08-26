# 03 - MCP 工具调用规范（TAPD / dbx / weknora）

## 通用规则

- **调用任何 MCP 工具前**：先读取对应工具的 JSON Schema 文件（路径各机器不同，用 Glob 搜索 `**/mcps/{server}/tools/{tool}.json` 定位后 Read；常见位于 `{IDE缓存目录}/projects/{项目目录}/mcps/{server}/tools/{tool}.json`），否则 MCP 报 "no tools registered"
- **workspace_id 必传**：`get_workspace_info`、`get_stories_or_tasks` 等 TAPD 工具必须在 arguments 内部传 `workspace_id`（取 `config/project.config.json` 的 `tapd.workspace_id`），否则报 `Field required` 错误
- **dbx 只允许 SELECT**：禁止写操作

## TAPD（mcp-server-tapd）

| 场景 | 工具 | 要点 |
|:---|:---|:---|
| 查需求 | `get_stories_or_tasks` | 必须传 workspace_id；按 id 查单个需求 |
| 查父需求背景 | `get_stories_or_tasks` | 用父需求 id 查 description 获取业务背景 |
| 下载图片 | `get_image` | 返回 `download_url`，**有效期 300 秒**，需及时下载到 `workspace/personal/image-cache/{需求ID}/` |
| 查缺陷 | `get_bug` / `get_bug_count` | 周报场景：处理人字段为 `current_owner`，推荐用 `reporter` 统计 |
| 状态映射 | `get_workflows_status_map` | **必须指定 system 参数**；以接口实时返回为准，不硬编码状态码 |
| 查迭代 | `get_iterations` | 按迭代 ID 获取信息 |
| 写用例 | `create_tcases_batch` / `get_tcases` | 批量创建/查询用例 |
| 评论 | `create_comments` | 需先 get_comments 确认 |

### 坑点

- 周报/工时统计时间筛选：以 `created` 时间范围决策，不按 resolved 等状态时间
- 任务标题**复用需求原始标题**，不自行改写；查询优化优先用 owner 过滤
- `get_workflows_status_map` 不带 system 参数会报错

## TAPD 原生 API（比 MCP 更可靠）

适用场景：MCP 工具查询失败/过滤参数不生效时，或需要精确 owner 过滤时。

### 快速查询本人需求

1. 获取当前用户昵称：`GET https://api.tapd.cn/users/info` → `data.nick`
2. 用昵称作 `owner` 查询指定迭代需求：`GET https://api.tapd.cn/stories`
3. 关键参数：`workspace_id={workspace_id}`（取配置）、`iteration_id={迭代ID}`、`owner={用户昵称}`、
   `fields` 指定返回字段、`limit=200`
4. 优点：过滤参数正常生效、支持多值模糊匹配、一次请求完整结果（owner 过滤无需分页）

### 需求查询快速路径

- 按 id 查单个需求（含父需求）时，也可直接用 TAPD 原生 API 的 `/stories?id={id}` 获取 description 业务背景

## dbx（数据库）

| 项 | 值 |
|:---|:---|
| 连接名（connection_name） | 取配置 `database.connection_name` |
| 数据库（database） | 取配置 `database.database` |

> 未配置时调用 `dbx_list_connections` 列出可用连接后向用户确认；业务表速查见 `.qoder/team-memory/local/db-tables.md`（若存在）

### 坑点（重要）

- **BIGINT 精度丢失**：MySQL 大整数（如 tenant_id、id）在 JSON 传输会丢精度，查询时须 `CAST(id AS CHAR)` 等显式转字符串
- **动态选表**：优先用 `TABLE_NAME + TABLE_COMMENT` 双字段搜索（dbx_list_tables + dbx_describe_table），不要只看表名猜
- **Schema 前置加载**：调用 dbx 工具前需先加载 schema context（dbx_get_schema_context）

## weknora-knowledge（知识库）

| 场景 | 工具 | 要点 |
|:---|:---|:---|
| 查知识 | `find_knowledge` | 参数是 `keyword` 不是 `query`；无结果属正常，转 dbx/其他渠道 |
| 列知识库 | `list_knowledge_bases` | 可能返回空，优先用配置 `knowledge_bases` 中的 ID 直接查询 |
| 上传文档 | `upload_file` / `create_manual_knowledge` | 补充业务知识 |

### 坑点

- `find_knowledge` 传错参数名（query）会报 validation error

## 记忆（SearchMemory / UpdateMemory）

- 个人记忆存储在 AI 本地（用户维度），**团队协作不共享**
- 项目级知识应写入 `.qoder/team-memory/`（随 git 共享），个人记忆只放个人偏好
