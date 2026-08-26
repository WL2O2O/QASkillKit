<#
.SYNOPSIS
  使用 Windows.Media.Ocr 引擎逐像素提取图片中的全部文字（覆盖率通道）。
  输出格式与 ocr_extract.py --json-blocks 兼容，用于三轨协同交叉校验。

  内置后处理（默认全部开启，解决"排序乱、有错别字"两大痛点；可用开关关闭，兜底旧行为）：
  1. 自适应排序（-NoSort 关闭）：列检测 + 行分组 + 行内 x 排序，解决跨列/乱序
  2. 同行碎片合并（-NoMerge 关闭）：y 重叠 + x 紧邻的拆行块自动合并
  3. 错别字词典纠错（-NoFix 关闭）：内置历史高频错别字映射，替换痕迹记录到 fixes 字段
  4. 可疑行标记（-NoMark 关闭）：启发式标记疑似乱码行到 suspicious 字段，仅提示不改文

  几何信息探测：排序/合并依赖每行的 bbox 坐标。PowerShell 5.1 下 Windows.Media.Ocr 的
  BoundingRect 投影为 null（WinRT 结构体投影缺陷，历史版本 blocks.bbox 一直是无效的 0），
  此时自动探测并降级——跳过排序与合并，输出 geometry: "unavailable"，排序职责由 OpenOCR
  通道承担（其输出本就排序自然 + 带置信度）。若未来环境 bbox 可用，排序/合并自动生效
  （geometry: "ok"），无需改动调用方。

  兜底保障：后处理任一步异常时自动回退引擎原始输出，并输出 postprocess: "fallback"；
  全部后处理可用 -NoSort -NoMerge -NoFix -NoMark 完全关闭，恢复旧行为。

.PARAMETER ImagePath
  图片路径，支持中文路径。

.PARAMETER Json
  输出 JSON 格式（默认开启）。

.PARAMETER Output
  将结果保存到文件。

.PARAMETER NoSort
  跳过自适应排序，保持引擎原始输出顺序（兜底开关）。

.PARAMETER NoMerge
  跳过同行碎片合并（兜底开关）。

.PARAMETER NoFix
  跳过错别字词典纠错（兜底开关）。

.PARAMETER NoMark
  跳过可疑行标记（兜底开关）。

.EXAMPLE
  powershell windows-ocr.ps1 -ImagePath "需求图.png"
  powershell windows-ocr.ps1 -ImagePath "需求图.png" -Output result.json
  powershell windows-ocr.ps1 -ImagePath "需求图.png" -NoSort -NoMerge -NoFix -NoMark   # 完全旧行为
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath,
    [switch]$Json = $true,
    [string]$Output = "",
    [switch]$NoSort,
    [switch]$NoMerge,
    [switch]$NoFix,
    [switch]$NoMark
)

$ErrorActionPreference = "Stop"

# ==================== 后处理函数定义（必须在调用前） ====================

# 错别字词典（历史经验积累，可按需扩展；key 为引擎常见原始形态，含空格/斜杠变体）
# 维护规范（见 ocr/SKILL.md 词典维护规范）：新错别字按"字面映射固定"原则收录；
# 条目上限 50 条，超限时移除近期未命中且与当前业务无关的条目；改后必须转码 UTF-8 with BOM 并验证 fixes 命中
$script:typoDict = @{
    "缓荐"    = "缓存"
    "蓝呀"    = "蓝牙"
    "公 fi"   = "公斤"
    "公fi"    = "公斤"
    "默 / 认" = "默认"
    "默/ 认"  = "默认"
    "默/认"   = "默认"
    "胸物车"  = "购物车"
    "按im去重" = "按item去重"
}

# 中位行高
function Get-MedianHeight {
    param($Blocks)
    if ($Blocks.Count -eq 0) { return 20 }
    $heights = @($Blocks | ForEach-Object { ($_.bbox.y2 - $_.bbox.y1) } | Sort-Object)
    return $heights[[int][Math]::Floor($heights.Count / 2)]
}

# 列边界检测：按 x1 排序后找大间隙（两侧块数均 >= 2 才算列边界）
function Get-ColumnBoundaries {
    param($Blocks, $MinGap)
    if ($Blocks.Count -lt 6) { return @() }
    $sorted = @($Blocks | Sort-Object { $_.bbox.x1 })
    $boundaries = @()
    for ($i = 1; $i -lt $sorted.Count; $i++) {
        $gap = $sorted[$i].bbox.x1 - $sorted[$i - 1].bbox.x2
        if ($gap -gt $MinGap -and $i -ge 2 -and ($sorted.Count - $i) -ge 2) {
            $boundaries += (($sorted[$i - 1].bbox.x2 + $sorted[$i].bbox.x1) / 2)
        }
    }
    return @($boundaries)
}

# 单列内排序：行分组（y 中心差 <= 阈值归组）→ 行内 x 排序 → 组间 y 排序
function Sort-OneColumn {
    param($Blocks, $MedianH)
    if ($Blocks.Count -le 1) { return @($Blocks) }
    $threshold = [Math]::Max($MedianH * 0.6, 5)
    $ordered = @($Blocks | Sort-Object { $_.bbox.y1 })
    $rows = New-Object System.Collections.ArrayList
    foreach ($b in $ordered) {
        $centerY = ($b.bbox.y1 + $b.bbox.y2) / 2
        $placed = $false
        for ($i = 0; $i -lt $rows.Count; $i++) {
            $ref = $rows[$i][0]
            $refCenter = ($ref.bbox.y1 + $ref.bbox.y2) / 2
            if ([Math]::Abs($centerY - $refCenter) -le $threshold) {
                $rows[$i] = @($rows[$i] + $b)
                $placed = $true
                break
            }
        }
        if (-not $placed) { [void]$rows.Add(@($b)) }
    }
    $result = New-Object System.Collections.ArrayList
    foreach ($row in $rows) {
        $rowSorted = @($row | Sort-Object { $_.bbox.x1 })
        foreach ($b in $rowSorted) { [void]$result.Add($b) }
    }
    return @($result)
}

# 自适应排序：列检测 → 分列 → 各列内排序 → 列间按 x 位置合并
function Sort-BlocksAdaptive {
    param($Blocks)
    $medianH = Get-MedianHeight -Blocks $Blocks
    $boundaries = @(Get-ColumnBoundaries -Blocks $Blocks -MinGap ([Math]::Max($medianH * 2, 60)))
    if ($boundaries.Count -ge 1 -and $boundaries.Count -le 2) {
        # 2~3 列：按块中心 x 分列
        $cols = @{}
        foreach ($b in $Blocks) {
            $cx = ($b.bbox.x1 + $b.bbox.x2) / 2
            $colIdx = 0
            for ($i = 0; $i -lt $boundaries.Count; $i++) {
                if ($cx -gt $boundaries[$i]) { $colIdx = $i + 1 }
            }
            if (-not $cols.ContainsKey($colIdx)) { $cols[$colIdx] = New-Object System.Collections.ArrayList }
            [void]$cols[$colIdx].Add($b)
        }
        $result = New-Object System.Collections.ArrayList
        foreach ($k in ($cols.Keys | Sort-Object)) {
            $colSorted = @(Sort-OneColumn -Blocks @($cols[$k]) -MedianH $medianH)
            foreach ($b in $colSorted) { [void]$result.Add($b) }
        }
        return @($result)
    }
    # 无明确列边界或列数 > 3：单列模式（兜底）
    return @(Sort-OneColumn -Blocks $Blocks -MedianH $medianH)
}

# 同行碎片合并：y 重叠 >= 行高 50% 且 x 间隙 <= 阈值时拼接文本，返回(结果, 合并数)
function Merge-CloseBlocks {
    param($Blocks, $MedianH)
    if ($Blocks.Count -le 1) { return @($Blocks), 0 }
    $maxGap = [Math]::Max($MedianH * 0.15, 6)
    $result = New-Object System.Collections.ArrayList
    $mergeCount = 0
    foreach ($b in $Blocks) {
        if ($result.Count -eq 0) { [void]$result.Add($b); continue }
        $last = $result[$result.Count - 1]
        $overlap = [Math]::Min($last.bbox.y2, $b.bbox.y2) - [Math]::Max($last.bbox.y1, $b.bbox.y1)
        $lastH = $last.bbox.y2 - $last.bbox.y1
        $bH = $b.bbox.y2 - $b.bbox.y1
        $minH = [Math]::Min($lastH, $bH)
        $gap = $b.bbox.x1 - $last.bbox.x2
        if ($minH -gt 0 -and $overlap -ge ($minH * 0.5) -and $gap -ge 0 -and $gap -le $maxGap) {
            $mergedObj = [PSCustomObject]@{
                transcription = ($last.transcription + $b.transcription)
                bbox = @{
                    x1 = $last.bbox.x1
                    y1 = [Math]::Min($last.bbox.y1, $b.bbox.y1)
                    x2 = $b.bbox.x2
                    y2 = [Math]::Max($last.bbox.y2, $b.bbox.y2)
                }
            }
            $result[$result.Count - 1] = $mergedObj
            $mergeCount++
        } else {
            [void]$result.Add($b)
        }
    }
    return @($result), $mergeCount
}

# 错别字词典纠错，返回(处理后的块数组, 修正统计数组)
function Fix-Typos {
    param($Blocks)
    if ($Blocks.Count -eq 0) { return @($Blocks), @() }
    $fixStats = @{}
    $out = New-Object System.Collections.ArrayList
    foreach ($b in $Blocks) {
        $t = $b.transcription
        foreach ($k in $script:typoDict.Keys) {
            if ($t.Contains($k)) {
                $t = $t.Replace($k, $script:typoDict[$k])
                if ($fixStats.ContainsKey($k)) { $fixStats[$k]++ } else { $fixStats[$k] = 1 }
            }
        }
        [void]$out.Add([PSCustomObject]@{
            transcription = $t
            bbox = $b.bbox
        })
    }
    $fixArr = @()
    foreach ($k in $fixStats.Keys) {
        $fixArr += [PSCustomObject]@{ from = $k; to = $script:typoDict[$k]; count = $fixStats[$k] }
    }
    return @($out), @($fixArr)
}

# 可疑行启发式标记（仅提示，不改文本），返回原因字符串（空串 = 不标记）
function Test-Suspicious {
    param($Text)
    if ($Text.Length -lt 2) { return "" }
    # 规则1：中文与孤立单字母混排（如 "公fi"）
    if ($Text -match "[\u4e00-\u9fa5][a-zA-Z][\u4e00-\u9fa5]" -or
        $Text -match "^[a-zA-Z][\u4e00-\u9fa5]" -or
        $Text -match "[\u4e00-\u9fa5][a-zA-Z]$") { return "中英混排疑似乱码" }
    # 规则2：连续 2+ 空格
    if ($Text -match "\s{2,}") { return "连续空格" }
    # 规则3：中文与 / 混合（疑似拆行残留）
    if ($Text -match "[\u4e00-\u9fa5]\s*/\s*[\u4e00-\u9fa5]") { return "斜杠拆分残留" }
    return ""
}

# ==================== WinRT 加载与图片识别（保持不变） ====================

# 解析完整路径
$resolvedPath = Resolve-Path $ImagePath -ErrorAction Stop
$fullPath = $resolvedPath.Path

# ---- 加载 WinRT 类型（必须显式加载全部用到的命名空间）----
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.FileRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

# ---- WinRT 异步等待封装 ----
# PowerShell 5.1 中 IAsyncOperation<T> 投影为 System.__ComObject，不能直接 .GetAwaiter()，
# 必须通过 WindowsRuntimeSystemExtensions.AsTask<T> 静态泛型方法转换后再等待。
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-AsyncOp {
    param($AsyncOp, $ResultType)
    $task = $asTaskGeneric.MakeGenericMethod($ResultType).Invoke($null, @($AsyncOp))
    return $task.GetAwaiter().GetResult()
}

# ---- 读取图片字节并构建内存流（避免中文路径下 FileRandomAccessStream 投影异常）----
$bytes = [System.IO.File]::ReadAllBytes($fullPath)
$memStream = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]::new()
$writer = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType = WindowsRuntime]::new($memStream)
$writer.WriteBytes($bytes)
$null = Await-AsyncOp $writer.StoreAsync() ([System.UInt32])
$memStream.Seek(0)

# ---- 解码图片为 SoftwareBitmap ----
$decoder = Await-AsyncOp ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]::CreateAsync($memStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$softwareBitmap = Await-AsyncOp $decoder.GetSoftwareBitmapAsync() ([Windows.Graphics.Imaging.SoftwareBitmap])

# ---- 创建 OCR 引擎（中文优先）----
$lang = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]::new("zh-CN")
$ocrEngine = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]::TryCreateFromLanguage($lang)
if ($null -eq $ocrEngine) {
    $ocrEngine = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]::TryCreateFromLanguage([Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]::new("en-US"))
}
if ($null -eq $ocrEngine) {
    throw "Windows OCR 引擎创建失败：请检查系统是否安装 OCR 语言包（设置-时间和语言-语言-可选功能-OCR）"
}

# ---- 执行识别 ----
$result = Await-AsyncOp $ocrEngine.RecognizeAsync($softwareBitmap) ([Windows.Media.Ocr.OcrResult])

# 清理
$memStream.Dispose()

# ---- 原始行提取（引擎顺序，含 bbox）----
$rawLines = @()
$rawText = ""
foreach ($line in $result.Lines) {
    $lineWords = @()
    foreach ($word in $line.Words) {
        $lineWords += $word.Text
    }
    $lineStr = ($lineWords -join "").Trim()
    $rawLines += [PSCustomObject]@{
        transcription = $lineStr
        bbox = @{
            x1 = [int]$line.BoundingRect.X
            y1 = [int]$line.BoundingRect.Y
            x2 = [int]($line.BoundingRect.X + $line.BoundingRect.Width)
            y2 = [int]($line.BoundingRect.Y + $line.BoundingRect.Height)
        }
    }
    $rawText += $lineStr + "`n"
}

# ---- 几何信息探测（PS5.1 下 BoundingRect 投影为 null，bbox 全为 0 时排序/合并自动降级）----
$hasGeometry = $true
foreach ($b in $rawLines) {
    if ($b.bbox.x1 -eq 0 -and $b.bbox.y1 -eq 0 -and $b.bbox.x2 -eq 0 -and $b.bbox.y2 -eq 0) {
        $hasGeometry = $false
        break
    }
}
$geometryStatus = "ok"
if (-not $hasGeometry) { $geometryStatus = "unavailable" }

# ==================== 后处理（默认开启，异常自动回退原始输出） ====================

$postText = $rawText
$procBlocks = @($rawLines)
$sortedFlag = $false
$fixesArr = @()
$mergeCount = 0
$susArr = @()
$fallbackFlag = $false

try {
    if (-not $NoSort -and $hasGeometry) {
        $procBlocks = @(Sort-BlocksAdaptive -Blocks $procBlocks)
        $sortedFlag = $true
    }
    if (-not $NoMerge -and $hasGeometry) {
        $mergedResult, $mergeCount = Merge-CloseBlocks -Blocks $procBlocks -MedianH (Get-MedianHeight -Blocks $procBlocks)
        $procBlocks = @($mergedResult)
    }
    if (-not $NoFix) {
        $fixedResult, $fixesArr = Fix-Typos -Blocks $procBlocks
        $procBlocks = @($fixedResult)
    }
    if (-not $NoMark) {
        foreach ($b in $procBlocks) {
            $reason = Test-Suspicious -Text $b.transcription
            if ($reason) {
                $susArr += [PSCustomObject]@{ text = $b.transcription; reason = $reason }
            }
        }
    }
    $postText = (@($procBlocks | ForEach-Object { $_.transcription }) -join "`n")
} catch {
    # 兜底：后处理异常时回退引擎原始输出，保证识别结果不丢失
    $postText = $rawText
    $procBlocks = @($rawLines)
    $fallbackFlag = $true
}

# ---- 格式化输出 ----
if ($Json) {
    $outputObj = [PSCustomObject]@{
        text = $postText.Trim()
        blocks_count = $procBlocks.Count
        blocks = @($procBlocks)
        sorted = $sortedFlag
        fixes = @($fixesArr)
        merged = $mergeCount
        suspicious = @($susArr)
        fallback = $fallbackFlag
        geometry = $geometryStatus
    }
    $jsonStr = $outputObj | ConvertTo-Json -Depth 5 -Compress

    if ($Output) {
        $jsonStr | Out-File -FilePath $Output -Encoding utf8
        Write-Host "[OCR] 结果已保存到: $Output"
    } else {
        Write-Host $jsonStr
    }
} else {
    if ($Output) {
        $postText.Trim() | Out-File -FilePath $Output -Encoding utf8
        Write-Host "[OCR] 结果已保存到: $Output"
    } else {
        Write-Host $postText.Trim()
    }
}
