"""
OCR 图片纯文本提取脚本
基于 OpenOCR 引擎，支持中文路径、大图切块、按位置排序输出。
"""
import sys
import json
import os
import io
import shutil
import tempfile
import subprocess
import argparse
from pathlib import Path
from PIL import Image

# 强制 stdout/stderr 使用 UTF-8，避免 Windows GBK 编码乱码
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 第1步：检查/安装 openocr-python
# ============================================================
def ensure_openocr():
    """检查 openocr-python 是否安装，未安装则自动安装"""
    try:
        from openocr import OpenOCR
        return True
    except ImportError:
        print("[OCR] 正在安装 openocr-python...", file=sys.stderr)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "openocr-python", "-q"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[OCR] 安装失败: {result.stderr}", file=sys.stderr)
            return False
        print("[OCR] 安装完成", file=sys.stderr)
        return True


# ============================================================
# 第2步：处理中文路径问题
# ============================================================
def safe_image_path(image_path: str) -> str:
    """
    OpenCV 在 Windows 上无法读取含中文的文件路径。
    如果路径包含非ASCII字符，复制到临时目录返回新路径。
    """
    # 检查是否有中文字符
    if all(ord(c) < 128 for c in image_path):
        return image_path
    
    # 有非ASCII字符，复制到临时目录
    ext = Path(image_path).suffix or ".png"
    tmp_dir = Path(tempfile.gettempdir()) / "ocr_temp"
    tmp_dir.mkdir(exist_ok=True)
    
    dst = tmp_dir / f"ocr_img_{hash(image_path) & 0xFFFFFFFF}{ext}"
    shutil.copy2(image_path, str(dst))
    return str(dst)


# ============================================================
# 第3步：大图切块（仅图片一边 > 2000px 时）
# ============================================================
def _compute_grid(width: int, height: int, max_tile: int):
    """按目标块尺寸自动计算网格行列数。"""
    cols = max(1, -(-width // max_tile))
    rows = max(1, -(-height // max_tile))
    return rows, cols


def _split_image_into_tiles(image_path: str, out_dir: str,
                            rows=None, cols=None, overlap=120, max_tile=1500) -> list[str]:
    """将大图按网格切块，返回切块路径列表（行优先排序）。"""
    img = Image.open(image_path)
    width, height = img.size

    if rows is None and cols is None:
        rows, cols = _compute_grid(width, height, max_tile)
    else:
        rows = rows or 1
        cols = cols or 1

    tile_w = -(-width // cols)
    tile_h = -(-height // rows)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    tiles = []
    for r in range(rows):
        for c in range(cols):
            left = max(0, c * tile_w - (overlap if c > 0 else 0))
            upper = max(0, r * tile_h - (overlap if r > 0 else 0))
            right = min(width, (c + 1) * tile_w + (overlap if c < cols - 1 else 0))
            lower = min(height, (r + 1) * tile_h + (overlap if r < rows - 1 else 0))

            tile = img.crop((left, upper, right, lower))
            tile_path = out_path / f"tile_r{r + 1}_c{c + 1}.png"
            tile.save(tile_path)
            tiles.append(str(tile_path))

    return tiles


def split_large_image(image_path: str, output_dir: str) -> list[str]:
    """切分大图（图片一边 > 2000px 时用），返回切块路径列表"""
    img = Image.open(image_path)
    w, h = img.size
    if w <= 2000 and h <= 2000:
        return [image_path]

    print(f"[OCR] 原图 {w}x{h} 超过 2000px，切块处理...", file=sys.stderr)
    tiles = _split_image_into_tiles(image_path, output_dir)
    print(f"[OCR] 切分为 {len(tiles)} 块", file=sys.stderr)
    return tiles if tiles else [image_path]


# ============================================================
# 第4步：多区域检测与自动裁剪
# ============================================================
def detect_column_regions(blocks: list[dict], img_width: int, img_height: int,
                         padding: int = 15, split_count: int = 1) -> list[tuple]:
    """
    从文本块位置检测多列区域，返回 [(x1,y1,x2,y2), ...]
    
    参数：
        split_count: 最多切出几列（默认1表示只切一次，得到2列）
    
    步骤：
    1. 按 x_mid 排序文本块
    2. 发现 x 坐标 gap（阈值取 min(图片宽8%, 中位文本高*3)）的位置作为列分隔线
    3. 取 top-N 个最大 gap 做列分割
    4. 对每列计算实际文本 y 范围（min_y ~ max_y），加 padding 后返回
    """
    if not blocks:
        return [(0, 0, img_width, img_height)]
    
    # 计算每个块的范围
    for b in blocks:
        xs = [p[0] for p in b['points']]
        ys = [p[1] for p in b['points']]
        b['_x_min'] = min(xs)
        b['_x_max'] = max(xs)
        b['_x_mid'] = (b['_x_min'] + b['_x_max']) / 2
        b['_y_min'] = min(ys)
        b['_y_max'] = max(ys)
    
    # 按 x_mid 排序，发现 gap
    sorted_blocks = sorted(blocks, key=lambda b: b['_x_mid'])
    x_mids = [b['_x_mid'] for b in sorted_blocks]
    
    # 估算 gap 阈值（取图片宽8% 与 中位文本高*3 中较大值）
    heights = sorted([b['_y_max'] - b['_y_min'] for b in blocks])
    median_h = heights[len(heights) // 2] if heights else 15
    # 自动裁剪用较大阈值，避免切得太碎
    gap_threshold = max(median_h * 3, img_width * 0.08, 60)
    
    gaps = []
    for i in range(len(x_mids) - 1):
        gap = x_mids[i + 1] - x_mids[i]
        if gap > gap_threshold:
            gaps.append((gap, i, x_mids[i], x_mids[i + 1]))
    
    if not gaps or len(blocks) < 5:
        return [(0, 0, img_width, img_height)]  # 单列
    
    # ---- 兜底：检测结果不合理时回退到单列模式 ----
    # 取 top-N 个最大 gap 做列分割
    gaps.sort(key=lambda g: g[0], reverse=True)
    top_gaps = gaps[:split_count]
    
    # 计算列分界线
    split_xs = []
    for _, i, _, _ in top_gaps:
        sx = (sorted_blocks[i]['_x_max'] + sorted_blocks[i + 1]['_x_min']) / 2
        split_xs.append(sx)
    split_xs = sorted(set(split_xs))
    
    # 如果列数 > 3，可能是噪声导致的误判，回退到单列
    if len(split_xs) + 1 > 3:
        return [(0, 0, img_width, img_height)]
    
    # 构建列区间：[(x_start, x_end)]
    col_ranges = []
    prev = 0
    for sx in split_xs:
        col_ranges.append((prev, sx))
        prev = sx
    col_ranges.append((prev, img_width))
    
    # 对每列，计算实际文本的 y 范围
    regions = []
    for col_idx, (x1, x2) in enumerate(col_ranges):
        # 该列涉及的文本块
        col_blocks = [b for b in blocks if x1 <= b['_x_mid'] <= x2]
        if not col_blocks:
            continue
        # 如果列宽 < 30px，很可能是单个字符误判，回退到单列
        if x2 - x1 < 30:
            return [(0, 0, img_width, img_height)]
        y_min = min(b['_y_min'] for b in col_blocks)
        y_max = max(b['_y_max'] for b in col_blocks)
        regions.append((
            max(0, x1 - padding),
            max(0, y_min - padding),
            min(img_width, x2 + padding),
            min(img_height, y_max + padding)
        ))
    
    return regions if len(regions) > 1 else [(0, 0, img_width, img_height)]


def ocr_multi_region(image_path: str) -> list[dict]:
    """
    多区域 OCR：先快速检测文本位置确定列区域，
    裁剪后每区独立重新识别，结果按列排序拼接。
    """
    from openocr import OpenOCR

    _, ext = os.path.splitext(image_path)

    # 第一遍：检测文本位置
    ocr = OpenOCR(task='ocr', mode='mobile', backend='onnx')
    result = ocr(image_path=image_path)
    
    detections = []
    if result and isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, list):
                for line in item:
                    if isinstance(line, str) and '\t' in line:
                        raw_data = line.split('\t', 1)[1]
                        data = json.loads(raw_data)
                        detections.extend(data)
    
    # 打开原图
    img = Image.open(image_path)
    w, h = img.size
    
    # 检测列区域
    regions = detect_column_regions(detections, w, h)
    
    if len(regions) <= 1:
        return detections  # 单列，直接返回
    
    # 裁剪并重新识别
    region_results = []
    for i, (x1, y1, x2, y2) in enumerate(regions):
        crop = img.crop((x1, y1, x2, y2))
        crop_path = os.path.join(
            tempfile.gettempdir(), "ocr_temp", f"region_{i}{ext or '.png'}"
        )
        os.makedirs(os.path.dirname(crop_path), exist_ok=True)
        crop.save(crop_path)
        
        # 单独识别（单列排序更准）
        region_blocks = ocr_image(crop_path)
        region_results.append(region_blocks)
    
    # 按列排序：左 → 右
    # 每列内的 blocks 已经各自排序过
    all_blocks = []
    for col_idx, rb in enumerate(region_results):
        # 为每列添加列标记用于后续拼接
        rb_sorted = sort_blocks_adaptive(rb)
        if rb_sorted:
            all_blocks.append((col_idx, rb_sorted))
    
    # 扁平化所有block，按列拼接
    all_blocks.sort(key=lambda x: x[0])
    return [b for _, blist in all_blocks for b in blist]


# ============================================================
# 第4.5步：智能排序算法
# ============================================================
def sort_blocks_adaptive(blocks: list[dict]) -> list[dict]:
    if not blocks:
        return blocks
    
    # 为每个块计算元数据
    for b in blocks:
        ys = [p[1] for p in b['points']]
        xs = [p[0] for p in b['points']]
        b['_y_top'] = min(ys)
        b['_y_bot'] = max(ys)
        b['_y_mid'] = (b['_y_top'] + b['_y_bot']) / 2
        b['_x_mid'] = (min(xs) + max(xs)) / 2
        b['_height'] = b['_y_bot'] - b['_y_top']
    
    # 估算行高：取中位文本高度的 1.5 倍（含行间距）
    heights = sorted([b['_height'] for b in blocks])
    median_h = heights[len(heights) // 2] if heights else 15
    line_h = max(median_h * 1.2, 10)
    
    # ---- 多列检测 ----
    # 通过 x 坐标 gap 找出列边界
    x_mids = sorted([b['_x_mid'] for b in blocks])
    gaps = []
    for i in range(len(x_mids) - 1):
        gap = x_mids[i + 1] - x_mids[i]
        if gap > max(median_h * 1.5, 40):
            gaps.append((gap, x_mids[i], x_mids[i + 1]))
    
    if gaps:
        # 取最大 gap 作为列分隔线
        _, left_end, right_start = max(gaps, key=lambda g: g[0])
        col_split = (left_end + right_start) / 2
        for b in blocks:
            b['_col'] = 0 if b['_x_mid'] < col_split else 1
    else:
        for b in blocks:
            b['_col'] = 0
    
    # ---- 排序：所属列 → 所在行（y分组）→ 同行内x顺序 ----
    # 行分组精度 = line_h * 0.6，保证相邻行一定分开
    row_unit = max(line_h * 0.6, 8)
    blocks.sort(key=lambda b: (
        b.get('_col', 0),
        round(b['_y_mid'] / row_unit),
        b['_x_mid']
    ))
    return blocks


# ============================================================
# 第5步：OCR 识别单张图片
# ============================================================
def ocr_image(image_path: str) -> list[dict]:
    """对单张图片执行 OCR，返回文本块列表（OpenOCR 原始顺序）"""
    from openocr import OpenOCR
    
    ocr = OpenOCR(task='ocr', mode='mobile', backend='onnx')
    result = ocr(image_path=image_path)
    
    blocks = []
    if result and isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, list):
                for line in item:
                    if isinstance(line, str) and '\t' in line:
                        raw_data = line.split('\t', 1)[1]
                        data = json.loads(raw_data)
                        blocks.extend(data)
    return blocks


# ============================================================
# 第5步：主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="OCR 图片纯文本提取")
    parser.add_argument("image_path", help="图片路径（支持中文路径）")
    parser.add_argument("--split", action="store_true", help="对超大图片执行切块")
    parser.add_argument("--no-crop", action="store_true",
                        help="禁用自动列区域检测裁剪，使用全局识别+排序")
    parser.add_argument("--output", "-o", help="输出到文件（默认输出到stdout）")
    parser.add_argument("--json-blocks", action="store_true",
                        help="输出每个文本块的完整信息（含 score 和 bbox），而非仅拼接文本")
    parser.add_argument("--min-score", type=float, default=0.0,
                        help="仅输出置信度 >= 此值的文本块（默认 0.0 即全部输出）")
    args = parser.parse_args()
    
    # 确保安装
    if not ensure_openocr():
        sys.exit(1)
    
    # 处理中文路径
    safe_path = safe_image_path(args.image_path)
    print(f"[OCR] 处理: {os.path.basename(args.image_path)}", file=sys.stderr)
    
    # ---- 自动模式（默认）：先检测列区域，智能决策是否裁剪 ----
    if args.no_crop:
        # 用户显式要求禁用自动裁剪
        # 判断是否需要切块
        images_to_process = [safe_path]
        if args.split:
            tmp_split_dir = tempfile.mkdtemp()
            images_to_process = split_large_image(safe_path, tmp_split_dir)
        
        all_blocks = []
        for img_path in images_to_process:
            blocks = ocr_image(img_path)
            all_blocks.extend(blocks)
    else:
        # 智能模式：自动检测是否需要裁剪
        # 单列图 → 1次OCR直接出结果（无额外开销）
        # 多列图 → 裁剪后每列独立重新识别
        all_blocks = ocr_multi_region(safe_path)
        
    # 智能排序（自适应行高 + 多列检测）
    all_blocks = sort_blocks_adaptive(all_blocks)
    
    # 按 min-score 过滤
    if args.min_score > 0.0:
        all_blocks = [b for b in all_blocks if b.get('score', 0.0) >= args.min_score]
    
    # 输出
    if args.json_blocks:
        # 输出每个文本块的完整信息
        blocks_output = []
        for b in all_blocks:
            xs = [p[0] for p in b['points']]
            ys = [p[1] for p in b['points']]
            blocks_output.append({
                "transcription": b['transcription'],
                "score": b.get('score', 0.0),
                "bbox": {
                    "x1": min(xs),
                    "y1": min(ys),
                    "x2": max(xs),
                    "y2": max(ys)
                }
            })
        output = json.dumps({
            "blocks_count": len(all_blocks),
            "blocks": blocks_output
        }, ensure_ascii=False)
    else:
        # 原有行为：仅拼接文本
        full_text = ''.join(b['transcription'] for b in all_blocks)
        output = json.dumps({"text": full_text, "blocks_count": len(all_blocks)}, ensure_ascii=False)
    
    if args.output:
        content = full_text if not args.json_blocks else json.dumps(blocks_output, ensure_ascii=False, indent=2)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"[OCR] 结果已保存到: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
