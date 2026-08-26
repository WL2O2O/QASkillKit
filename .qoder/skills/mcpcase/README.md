# `/mcpcase` — AI 测试用例设计（MCP 版）

> 本 README 介绍 `/mcpcase` 与相关 skill 的关系与协作方式。
> 详细执行流程见 [SKILL.md](SKILL.md)。

## 三个 Skill 的关系总览

| Skill | 定位 | 与其他 Skill 的关系 |
|:---|:---|:---|
| **`/mcpcase`** | 生成测试用例 | 调用 `/ocr` skill 识图 → 生成用例 → 缓存图片（供 case-review 复用） |
| **`/ocr`** | 三轨协同识图 | Windows OCR + OpenOCR + Read 三通道交叉验证、置信度追踪、兜底处理，供 mcpcase/case-review 统一调用 |
| **`/case-review`** | 核查已有用例 | 复用 mcpcase 的图片缓存，调用 `/ocr` skill 做原型一致性比对 |

> **关键设计**：mcpcase 与 case-review 都**通过 `/ocr` skill 统一调用识图能力**，由 /ocr 内部完成三轨协同、置信度追踪与兜底逻辑；不直接在各自 skill 中调脚本，避免 /ocr 能力打折扣。

## 典型使用场景

### 场景 1：为一个新需求生成测试用例

```bash
/mcpcase 1019033
/mcpcase 1019033 @workspace/personal/specs/限量销售-Spec.md   # 带 Spec 文档
```

**自动完成**：
1. TAPD 拉需求 + 内嵌原型图
2. 调用 `/ocr` skill 三轨协同识图（无需手动 `/ocr`）
3. dbx 拉真实测试数据
4. 按变更点 / Spec 验收标准生成用例
5. **缓存图片**到 `workspace/personal/image-cache/{需求ID}/`（供 case-review 复用）
6. 双路径归档到 `workspace/personal/drafts/{迭代}/` + `workspace/testcases/{迭代}/`（目录不存在时自动创建）

### 场景 2：核查已生成的用例与原型图是否一致

```bash
/case-review 1019033
```

**自动完成**：
1. **优先复用** mcpcase 留下的图片缓存（按 TAPD `<img>` basename 匹配）
2. 缺失图片才下载，避免重复 `get_image` 浪费配额
3. 调用 `/ocr` skill 三轨协同识图（Windows OCR + OpenOCR + Read）
4. 逐条比对用例 ↔ 原型，输出有据修正项 / 待确认项
5. 双路径同步修正（正式路径 + 个人副本），md5 校验一致

### 场景 3：单独识图（不涉及用例）

```bash
/ocr <图片路径>           # 通用识图，输出三通道交叉验证结果
```

适用：识别规范说明图、提取流程图、解析设计稿等非用例场景。

## 三 Skill 协作流程图

```
┌─────────────────────────────────────────────────────────────┐
│  成员只需要与 mcpcase/case-review 对话                    │
└─────────────────────────────────────────────────────────────┘
                  ↓                       ↓
            ┌──────────┐            ┌──────────────┐
            │ /mcpcase │            │ /case-review │
            │  生成用例 │            │   核查用例    │
            └────┬─────┘            └──────┬───────┘
                 │                         │
                 │  (1) 图片缓存            │  (1) 优先复用缓存
                 │      ↓                   │      ↓
                 │  ┌────────────────────┐  │
                 │  │ image-cache/      │  │
                 │  │  {需求ID}/         │  │
                 │  └────────────────────┘  │
                 │                         │
                 └────────┬────────────────┘
                          ↓
              ┌────────────────────────┐
              │  /ocr skill（统一入口）│
              │  三轨协同识图           │
              │  - Windows OCR         │
              │  - OpenOCR             │
              │  - Read / GLM          │
              └────────────────────────┘
```

## 我应该用哪个 Skill？

| 你想做的事 | 用哪个 |
|:---|:---|
| 新需求要写测试用例 | `/mcpcase <需求ID>` |
| 已有用例，要核对与原型/需求是否一致 | `/case-review <需求ID>` |
| 只想要 OCR 文字提取（不写用例） | `/ocr <图片路径>` |
| 把流程图转成 Mermaid 代码 | （本地开发中，未随仓库发布） |

## 协作要点

1. **图片缓存共享**：mcpcase 生成的图片默认保留在 `workspace/personal/image-cache/{需求ID}/`；case-review 会**按 TAPD 原始文件名**自动匹配复用，避免重复下载
2. **双路径同步**：mcpcase 生成的用例归档到两份（个人副本 + 正式目录），case-review 修改时也同步两份并以 md5 校验
3. **团队记忆库强制读取**：本 skill 在执行前会先读 `.qoder/team-memory/04-testcase-standard.md` 等规范文件，遵循团队沉淀的标准
4. **统一通过 `/ocr` skill 识图**：mcpcase/case-review 都自动调用 `/ocr`，成员不需要会主动调用 `/ocr`，识图细节（三轨协同、置信度、兜底）由 /ocr 统一负责

## 详细文档

- [SKILL.md](SKILL.md) — 完整执行流程与规范
- [.qoder/team-memory/02-ocr-pipeline.md](../../../team-memory/02-ocr-pipeline.md) — OCR 三轨协同原理
- [.qoder/team-memory/04-testcase-standard.md](../../../team-memory/04-testcase-standard.md) — 用例命名/头部/归档规范
