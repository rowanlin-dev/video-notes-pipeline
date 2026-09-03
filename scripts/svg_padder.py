#!/usr/bin/env python3
"""
SVG viewBox 后处理：宽高比归一化
===================================
读取 SVG 文件的 viewBox，按宽高比阈值给视图加 padding，
使纵向图/横向图的宽高比落入合理范围，避免 Markdown/PDF 中极端变形。

用法：
  python scripts/svg_padder.py --dir runs/xxx/output/images [--target-min 0.65] [--target-max 2.0]
  python scripts/svg_padder.py --dir runs/xxx/output/images --dry-run  # 预览不改
"""
import re
import sys
import argparse
from pathlib import Path


def parse_viewbox(svg: str):
    m = re.search(r'viewBox="([^"]+)"', svg)
    if not m:
        return None
    parts = m.group(1).strip().split()
    if len(parts) != 4:
        return None
    return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])


def replace_viewbox(svg: str, x, y, w, h):
    old = f'viewBox="{x:.0f} {y:.0f} {w} {h}"'
    # 保留原始精度
    new_val = f"{x:.1f} {y:.1f} {w:.1f} {h:.1f}"
    new = f'viewBox="{new_val}"'
    return re.sub(r'viewBox="[^"]*"', new, svg)


def pad_svg(svg: str, target_min: float, target_max: float):
    vb = parse_viewbox(svg)
    if vb is None:
        return svg, None
    x, y, w, h = vb
    if w <= 0 or h <= 0:
        return svg, None

    ratio = w / h
    new_x, new_y, new_w, new_h = x, y, w, h

    if ratio < target_min:
        # 纵向图：加左右 padding
        target_w = h * target_min
        pad_x = (target_w - w) / 2
        new_x = x - pad_x
        new_w = target_w
        action = "pad-h"
        new_ratio = target_min
    elif ratio > target_max:
        # 横向图：加上下 padding
        target_h = w / target_max
        pad_y = (target_h - h) / 2
        new_y = y - pad_y
        new_h = target_h
        action = "pad-v"
        new_ratio = target_max
    else:
        return svg, None

    new_svg = replace_viewbox(svg, new_x, new_y, new_w, new_h)
    return new_svg, {
        "action": action,
        "old_ratio": round(ratio, 2),
        "new_ratio": round(new_ratio, 2),
        "old_vb": f"{x:.0f} {y:.0f} {w:.0f} {h:.0f}",
        "new_vb": f"{new_x:.1f} {new_y:.1f} {new_w:.1f} {new_h:.1f}",
    }


def main():
    ap = argparse.ArgumentParser(description="SVG viewBox 宽高比后处理")
    ap.add_argument("--dir", required=True, help="SVG 文件夹路径")
    ap.add_argument("--target-min", type=float, default=0.65, help="最小宽高比（纵向图，默认 0.65）")
    ap.add_argument("--target-max", type=float, default=2.0, help="最大宽高比（横向图，默认 2.0）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不修改文件")
    args = ap.parse_args()

    svg_dir = Path(args.dir)
    if not svg_dir.is_dir():
        print(f"[error] 目录不存在: {svg_dir}", file=sys.stderr)
        sys.exit(1)

    svg_files = sorted(svg_dir.glob("*.svg"))
    if not svg_files:
        print(f"[warn] 未找到 SVG 文件: {svg_dir}", file=sys.stderr)
        return

    modified = 0
    skipped = 0
    details = []

    for fp in svg_files:
        raw = fp.read_text(encoding="utf-8")
        new_svg, info = pad_svg(raw, args.target_min, args.target_max)
        if info is None:
            skipped += 1
            continue
        details.append((fp.name, info))
        if not args.dry_run:
            fp.write_text(new_svg, encoding="utf-8")
        modified += 1

    print(f"\n处理完成：{modified} 修改，{skipped} 跳过（{svg_dir}）")
    if args.dry_run:
        print("（dry-run 模式，未写入文件）")
    print()
    for name, info in details:
        print(f"  {name}")
        print(f"    {info['old_vb']}  ratio={info['old_ratio']}  →  {info['new_vb']}  ratio={info['new_ratio']}  ({info['action']})")

    if details:
        print()
        print("目标范围：", args.target_min, "~", args.target_max)


if __name__ == "__main__":
    main()