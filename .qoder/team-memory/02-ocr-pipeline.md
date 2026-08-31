# 02 - OCR 三轨协同（脚本 / 修复经验 / GLM 通道）

## 三轨协同架构

```
Windows OCR（覆盖率）+ OpenOCR（精读排序）+ VLM/Read（结构）
```

| 通道 | 工具 | 职责 | 特点 |
|:---|:---|:---|:---|
| Windows OCR | `.qoder/skills/ocr/scripts/windows-ocr.ps1` | 全量文本提取（覆盖率）+ 内置词典纠错 + 可疑行标记 | 逐像素不漏字，毫秒级离线；PS5.1 下 bbox 不可用，排序以 OpenOCR 为准 |
| OpenOCR | `.qoder/skills/ocr/scripts/ocr_extract.py --json-blocks` | 精读排序 + 置信度 | 输出 `score` 字段，`<0.7` 为低可信度，需原文校验 |
| VLM/Read | `Read` 工具（主）/ GLM（第二意见） | UI 结构理解 | 按钮/弹窗/表格/颜色标记；Read 细节保真更优 |

### 三轨交叉验证

- 同区域文本互相印证，错别字在对比中暴露（如 Windows OCR"默 / 认" vs OpenOCR"默认"）
- 结构验证：Read 描述的 UI 元素在 OCR 结果中应有对应文案
- 低置信度（score<0.7）处理优先级：Windows OCR 同区域 > TAPD 原文 > Spec > Read 复核

## Windows OCR 脚本（已修复，2026-08-06）

脚本：`.qoder/skills/ocr/scripts/windows-ocr.ps1`，输出与 `ocr_extract.py --json-blocks` 兼容。

### 内置后处理（2026-08-10 升级）

- **默认全部开启**：① 自适应排序（列检测+行分组+行内 x 排序，bbox 可用时生效）；② 同行碎片合并；③ 历史错别字词典纠错（`fixes` 字段记录替换痕迹，当前含：缓存/蓝牙/公斤/默认等高频错）；④ 可疑行标记（`suspicious` 字段仅提示不改文）
- **兜底开关**：`-NoSort -NoMerge -NoFix -NoMark` 可完全关闭恢复旧行为；后处理任一步异常自动回退引擎原始输出（`fallback: true`）
- **⚠️ PS5.1 下 BoundingRect 投影为 null**（WinRT 结构体投影缺陷，C# 反射同样拿不到）：blocks.bbox 恒为 0（**历史版本一直如此，属无效数据，不得依赖**）；脚本自动探测并输出 `geometry: "unavailable"` 跳过排序/合并，**排序职责由 OpenOCR 通道承担**（其输出本就排序自然+带 score）；若未来环境（如 pwsh CsWinRT）bbox 可用则自动生效，无需改调用方
- **扩展词典**：新增错别字直接在脚本内 `$script:typoDict` 映射补充（含空格/斜杠变体，如"默 / 认"）
- **词典维护规范（2026-08-10）**：使用中发现新错别字**必须**按 ocr/SKILL.md"词典维护规范"维护——① 收录原则：字面映射固定才入词典（"胸物车"→"购物车"、"按im去重"→"按item去重"为实测新增）；② 改后必须转码 UTF-8 with BOM 并重跑原图验证 `fixes` 命中；③ **条目上限 50 条**，超限时移除近期未命中且与当前业务无关的历史条目；④ 语义级替换（"规格"→"im"类）、价格符号类（¥→Y）不强行入词典，由 suspicious + 交叉验证兜底

### 历史失败根因与修复（重要）

**症状**：`TypeNotFound`（Language）、`MethodNotFound`（Create）、`System.__ComObject 无法调用 GetAwaiter`

**根因 1 - WinRT 异步调用**：PowerShell 5.1 中 `IAsyncOperation<T>` 投影为 `System.__ComObject`，
不能直接 `.GetAwaiter()`。**必须**通过反射调用 `[System.WindowsRuntimeSystemExtensions]` 的泛型
`AsTask<T>(IAsyncOperation<T>)` 转换为 .NET Task 再等待（脚本内 `Await-AsyncOp` 函数已封装）。

**根因 2 - 脚本编码**：含中文的 .ps1 必须是 **UTF-8 with BOM**，否则 PowerShell 5.1 按 ANSI(GBK)
解析中文导致 ParserError（如 `"`n"` 意外的标记）。

**根因 3 - 类型加载**：所有用到的命名空间必须显式加载 `ContentType = WindowsRuntime`（含
`Windows.Globalization`），`OcrEngine.Create()` 不可靠，用 `TryCreateFromLanguage("zh-CN")`。

**经验：任何含中文的 .ps1 文件用 UTF-8 with BOM 保存**（Write 工具默认无 BOM，需转码）。

## OpenOCR

```powershell
cd .qoder/skills/ocr/scripts
python ocr_extract.py "图片.png" --json-blocks            # 完整块信息（transcription+score+bbox）
python ocr_extract.py "图片.png" --json-blocks --min-score 0.7   # 过滤低可信度
python ocr_extract.py "图片.png" --split --json-blocks    # 超大图切块
```

- 首次运行自动下载模型（~37MB）；Windows 下需先进入脚本所在目录执行
- 每张图约 8~10 秒；自动多列裁剪（左右列布局最佳）

### 调用坑点（重要）

- **必须 cd 到脚本所在目录再执行**：直接在项目根目录运行 `python ocr_extract.py` 会报 `No such file or directory`（Windows Python 路径解析特性）。统一调用形式：`cd .qoder\skills\ocr\scripts; python ocr_extract.py "<图片路径>" --json-blocks`
- **PowerShell 多命令用分号 `;` 分隔**，不能用 `&&`（那是 bash/sh 语法，PowerShell 5.1 会报错）
- **Node -e 内联脚本不能含中文/全角引号**：命令行内联传中文或全角字符（如“”）会被终端截断导致 `SyntaxError: Invalid or unexpected token`；必须写临时 .js 文件（Write 工具，UTF-8）再执行，用完即删
- **fc.exe 不支持中文路径**：cmd 的 `fc` 比较含中文文件名报“无效的参数”，改用临时 Node 脚本（readFileSync + crypto md5 哈希对比）验证文件一致性
- **Node 脚本硬编码文件名含中文全角引号（“”）报 ENOENT**：如“新增“核销记录”子菜单”，Write 写入时引号码位可能与磁盘实际不符；改用 `fs.readdirSync(dir).filter(f=>f.startsWith(前缀))` 动态匹配路径，避免硬编码引号
- **JS 源码字符串内嵌套 ASCII 单引号会截断字符串**：Write 工具写入的 .js 中 `'...更新为'退款成功'...'`（原文含 ASCII `'`）会在内层引号处截断报语法错误；文案引号一律改全角「」或中文弯引号规避；正则表达式则统一用 `new RegExp('...', 'm')` 字符串构造（正则字面量里 `\n` 会被 Write 转成真实换行报“未终止的正则表达式”）；文本行级增删改优先用 `split(eol)` + findIndex/splice + `join(eol)` 行数组方案，避免正则转义坑
- **Python 包装脚本内 print OCR 子进程 stdout 报 GBK 编码错误**：stdout 含 emoji（如 ✅）触发 `UnicodeEncodeError: 'gbk' codec can't encode`（Windows 控制台默认 GBK）；规避：不打印 stdout（OCR 结果已写入输出文件直接读文件）或先 `sys.stdout.reconfigure(encoding='utf-8')`
- 所有路径相对项目根，勿写死盘符（各成员 clone 位置不同）

## GLM 视觉通道（结构通道第二意见）

- **定位**：Read 为主，GLM 仅在 Read 输出不完整/结构存疑时作第二意见交叉验证，**不替代 Read**（GLM 有幻觉风险：漏商品行、单价混淆、小字丢失，不得单独作为用例依据）
- **调用**：`.qoder/skills/ocr/scripts/vlm-vision.ps1 -ImagePath <图> -Prompt <提示> -Channel glm -Json -NoCache`
- **Key 获取**：`GLM_API_KEY` 在**用户变量 User scope**（进程 `$env:` 读不到）：
  ```powershell
  $env:GLM_API_KEY = [Environment]::GetEnvironmentVariable("GLM_API_KEY", "User")
  ```
- **免费声明**（官方核实）：GLM-4V-Flash 是智谱首个完全免费的图像理解模型
  - 平台：https://bigmodel.cn/
  - API Key 创建：https://bigmodel.cn/apikey/platform
  - 官方免费文档：https://docs.bigmodel.cn/cn/guide/models/free/glm-4v-flash
- **未配置时自动降级**：跳过 GLM 仅用 Read，不阻塞流程；对话中输出配置引导模板

## 颜色标记识别规则（彩色标记+删除线识别）

- **颜色图例语义**：从 `config/project.config.json` 的 `color_legend` 读取（各团队可自定义，未配置时按默认图例兜底并提示 `/setup`）；默认：⬛ 黑色=原始需求逻辑（整图全黑时为纯新增功能）；🔴 红色=本次需求迭代修改的逻辑（核心变更点）；🟣 紫色=需求开发中临时改动的逻辑（正相关，与 TAPD 描述冲突时以 TAPD 描述为准）；🟠 橙色=尚未实现的逻辑或他人并行修改标注（须以 TAPD 描述/开发评论交叉验证是否属于本次需求范围）
- 需求图片（尤其是注释面板）中，**有颜色标记的文字（红/紫/橙及蓝/绿等其他与背景可区分的彩色）是需求正相关内容**（用例核心依据，不限于红色；橙色先验证范围）；**黑色/灰色背景文字多为上下文参考**（用于理解语境，一般不为其编写用例；但含明确业务规则——字段约束/枚举选项/数值限制——时须按兜底判断流程确认后编写）
- **全黑图片兜底**：整张图无彩色标记时推断为新功能，基于全部注释文本编写用例
- **删除线文字**：表示功能已移除，不得编写用例
- 注释面板特殊处理：彩色标注（字段约束/状态流转/操作结果）→ 必须写用例；黑色说明（操作流程/示例数据/通用说明/面板标题）→ 不独立编写；删除线 → 排除
- Read 识别颜色标记区域（输出需标注区域颜色属性，含删除线区域），OCR 提取对应精确文案，交叉验证
- 无法区分颜色时按「5 步兜底判断流程」（TAPD 原文 → Spec 文档 → 知识库查询 → dbx 表结构 → 待确认）处理，以 TAPD 描述为准
- 详细规则见 `.qoder/skills/ocr/SKILL.md`「颜色标记识别规则（彩色标记+删除线识别）」，testcase-generator / testcase-reviewer 调用 OCR 结果时必读并按彩色标记分层处理

## 兜底策略

- 所有通道识别均明显不足（文本块远少于肉眼可见量）时：**停止自动化尝试**，提示用户人工切图（裁剪文字区域为独立小图或拼接长图）

## 临时文件清理规范

- **需求图片缓存**：testcase-generator 生成用例后**默认保留** `workspace/personal/image-cache/{需求ID}/` 下的图片（与 testcase-reviewer 缓存策略一致，生成→核查复用同一批图，避免重复下载；缓存截图随仓库入库，**提交前请人工检查是否含敏感内容**）；确需释放空间时手动删除该目录或要求 AI 清理
- **缓存一致性校验（防同名覆盖盲区）**：TAPD 同名图片内容被更新时（URL/文件名不变），按 basename 复用会静默用旧图。对策：下载统一走 `testcase-reviewer/scripts/download_images.js`（自动写 `.manifest.json` 记录 md5/size/cached_at）；testcase-reviewer 复用前调 `get_image` 拿实时链接后执行 `--verify` 模式（Range 请求头比对 Content-Length），OK 复用 / CHANGED、UNKNOWN 重下；缓存超 7 天或用户指定 `--refresh` 时强制重下
- **OCR 临时切片**：`ocr_extract.py` 使用 `tempfile.gettempdir()` 系统临时目录，由系统自动回收，不占用项目空间
- **通用原则**：所有 skill 产生的临时文件优先写入已被 .gitignore 排除的目录（如 `_tmp/`、`workspace/personal/drafts/`），流程末尾按需清理（需求图片缓存默认保留，见上）；测试用例、周报等交付物写入 `workspace/` 对应归档目录保留
- **DeleteFile 删除后验证**：DeleteFile 返回成功后 Glob 仍可能显示文件存在（索引缓存滞后，实际已删）；以 PowerShell `Get-ChildItem -Filter` 或 `Test-Path` 实测为准，勿据此重复删除或误判清理失败

## 原型图注释滞后于 TAPD 描述（核查经验）

- 现象：原型图注释可能与 TAPD 描述冲突，且多为**需求变更前的旧注释**（已三次出现：1019782 图7"支持点击切换规格"为模板残留，用户确认本期不做；1019783 图3 仍写"展示'全部商品'"，而 TAPD 描述为"删除全部商品选项"，用户已确认删除，图3 为旧注释；1019739 标注 6 在 WIN 页面标注"调用 /versionConfig/uploadAPK"（应为 uploadWinSoftware）、标注 1 写"json、zip 上传至服务器 CDN 目录"（与本期前端直传 OSS 矛盾），均为旧说明残留）
- 处理：结论不唯一时按 testcase-reviewer 规范列为**待确认项**（用例暂按 TAPD 描述编写），不直接改；用户确认后再双路径同步修正
- 判定提示：图1（需求来源表）通常含蓝框/红框标注的需求原始诉求，是判断新旧注释的最可靠锚点；TAPD 描述中的"业务流程（新）/影响范围"章节是判定新旧交互的权威锚点
