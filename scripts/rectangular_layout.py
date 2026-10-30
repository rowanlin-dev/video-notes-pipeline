#!/usr/bin/env python3
"""
矩形布局转换器
================
检测 .mmd 文件中横向线性排列的 flowchart LR（6 个及以上节点），
自动生成为矩形布局 SVG（上下少、左右多），替换 mermaid.ink 渲染的横向长图。

用法：
  python scripts/rectangular_layout.py --mermaid-dir runs/xxx/output/mermaid --images-dir runs/xxx/output/images
  python scripts/rectangular_layout.py --mermaid-dir runs/xxx/output/mermaid --images-dir runs/xxx/output/images --dry-run
"""
import re, math, sys
from pathlib import Path

FONT = "'Microsoft YaHei', 'PingFang SC', 'Noto Sans SC', sans-serif"
W, H = 140, 46  # 节点尺寸
VIEW_W, VIEW_H = 800, 600


def parse_mmd(path: Path):
    """解析 .mmd，提取节点标签列表。返回 (type, [label, ...]) 或 None。"""
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if not lines:
        return None

    first = lines[0].strip().lower()
    if not first.startswith("flowchart lr"):
        return None

    # 含 subgraph 的图不是线性链，矩形布局会把子图标题当成节点、连线也乱掉，直接跳过
    if any(l.strip().lower().startswith("subgraph") for l in lines[1:]):
        return None

    # 提取所有节点标签
    labels = []
    # 匹配 A[text] 或 A["text"] 或 A[text with spaces]
    label_pattern = re.compile(r'([A-Za-z]\w*)\s*\[([^\]]*)\]')
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith('%%'):
            continue
        for m in label_pattern.finditer(line):
            node_id = m.group(1)
            label = m.group(2).strip()
            if label:
                labels.append(label)

    if len(labels) < 6:
        return None

    # 去重保留顺序
    seen = []
    for l in labels:
        if l not in seen:
            seen.append(l)
    labels = seen

    if len(labels) < 6:
        return None

    return ("flowchart_lr", labels)


def generate_rectangular_svg(labels: list, svg_path: Path):
    """生成矩形布局 SVG。"""
    n = len(labels)
    # 分配各边节点数
    top_n = 2
    bottom_n = 2
    side_n = n - 4  # 左右总和
    right_n = math.ceil(side_n / 2)
    left_n = side_n - right_n

    # 矩形边界
    left_x, right_x = 150, 650
    top_y, bottom_y = 120, 480
    mid_y = (top_y + bottom_y) / 2
    mid_x = (left_x + right_x) / 2

    # 计算每个节点的中心坐标
    positions = {}

    # Top: left→right
    top_xs = [left_x + (right_x - left_x) * (i + 1) / (top_n + 1) for i in range(top_n)]
    for i in range(top_n):
        idx = i
        positions[idx] = (top_xs[i], top_y)

    # Right: top→bottom
    right_ys = [top_y + (bottom_y - top_y) * (i + 1) / (right_n + 1) for i in range(right_n)]
    for i in range(right_n):
        idx = top_n + i
        positions[idx] = (right_x, right_ys[i])

    # Bottom: right→left
    bottom_xs = [right_x - (right_x - left_x) * (i + 1) / (bottom_n + 1) for i in range(bottom_n)]
    for i in range(bottom_n):
        idx = top_n + right_n + i
        positions[idx] = (bottom_xs[i], bottom_y)

    # Left: bottom→top
    left_ys = [bottom_y - (bottom_y - top_y) * (i + 1) / (left_n + 1) for i in range(left_n)]
    for i in range(left_n):
        idx = top_n + right_n + bottom_n + i
        positions[idx] = (left_x, left_ys[i])

    # 序号标注偏移（向外）
    num_offset = {}
    for i in range(n):
        x, y = positions[i]
        if y <= top_y + 30:  # top
            num_offset[i] = (0, -38)
        elif y >= bottom_y - 30:  # bottom
            num_offset[i] = (0, 38)
        elif x >= right_x - 30:  # right
            num_offset[i] = (65, 0)
        else:  # left
            num_offset[i] = (-65, 0)

    # 生成 SVG
    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" width="100%" height="100%">')
    lines.append('<style>')
    lines.append(f'  .nr {{ fill: #ECECFF; stroke: #9370DB; stroke-width: 1.5; rx: 8; ry: 8; }}')
    lines.append(f'  .nt {{ font-family: {FONT}; font-size: 13px; fill: #333; text-anchor: middle; dominant-baseline: central; }}')
    lines.append(f'  .nn {{ font-family: {FONT}; font-size: 11px; fill: #666; text-anchor: middle; dominant-baseline: central; }}')
    lines.append(f'  .ap {{ fill: none; stroke: #555; stroke-width: 1.5; marker-end: url(#ah); }}')
    lines.append('</style>')
    lines.append('<defs>')
    lines.append('  <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">')
    lines.append('    <path d="M 0 0 L 10 5 L 0 10 z" fill="#555" />')
    lines.append('  </marker>')
    lines.append('</defs>')

    # 箭头
    for i in range(n):
        j = i + 1 if i + 1 < n else 0  # 闭环或线性
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        d = _arrow(x1, y1, x2, y2)
        if d:
            lines.append(f'  <path class="ap" d="{d}" />')

    # 节点
    for i, label in enumerate(labels):
        x, y = positions[i]
        lx, ly = x - W / 2, y - H / 2
        nx, ny = x + num_offset[i][0], y + num_offset[i][1]
        lines.append(f'  <rect class="nr" x="{lx:.1f}" y="{ly:.1f}" width="{W}" height="{H}" />')
        lines.append(f'  <text class="nt" x="{x:.1f}" y="{y:.1f}">{label}</text>')
        lines.append(f'  <text class="nn" x="{nx:.1f}" y="{ny:.1f}">{i + 1}</text>')

    lines.append('</svg>')
    svg_path.write_text('\n'.join(lines), encoding="utf-8")
    return True


def _arrow(x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return ""
    off = 28
    sx = x1 + dx / dist * off
    sy = y1 + dy / dist * off
    ex = x2 - dx / dist * off
    ey = y2 - dy / dist * off
    is_corner = abs(dx) > 10 and abs(dy) > 10
    if is_corner:
        mx = (sx + ex) / 2
        my = (sy + ey) / 2
        outward = 20
        ndx = -dy / dist
        ndy = dx / dist
        cpx = mx + ndx * outward
        cpy = my + ndy * outward
        return f'M {sx:.1f} {sy:.1f} Q {cpx:.1f} {cpy:.1f} {ex:.1f} {ey:.1f}'
    else:
        return f'M {sx:.1f} {sy:.1f} L {ex:.1f} {ey:.1f}'


def main():
    import argparse
    ap = argparse.ArgumentParser(description="矩形布局转换器：检测横向链式图 → 矩形 SVG")
    ap.add_argument("--mermaid-dir", required=True, help="存放 .mmd 文件的目录")
    ap.add_argument("--images-dir", default=None, help="输出 SVG 的目录")
    ap.add_argument("--dry-run", action="store_true", help="仅列出要转换的文件，不执行")
    args = ap.parse_args()

    mermaid_dir = Path(args.mermaid_dir)
    if not mermaid_dir.is_dir():
        print(f"[error] mermaid 目录不存在: {mermaid_dir}", file=sys.stderr)
        sys.exit(1)

    images_dir = Path(args.images_dir) if args.images_dir else mermaid_dir.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    mmd_files = sorted(mermaid_dir.glob("*.mmd"))
    converted = 0
    for mmd in mmd_files:
        result = parse_mmd(mmd)
        if result is None:
            continue
        typ, labels = result
        n = len(labels)
        svg = images_dir / (mmd.stem + ".svg")
        if args.dry_run:
            print(f"  [detect] {mmd.name} ({n} 个节点) -> 矩形布局")
            continue
        generate_rectangular_svg(labels, svg)
        print(f"  [rect] {mmd.name} ({n} 个节点) -> {svg.name}")
        converted += 1

    if args.dry_run:
        if converted == 0:
            print("未检测到需要转换的横向链式图")
        return

    print(f"\n完成: {converted} 个文件转换为矩形布局")
    if converted == 0:
        print("未检测到需要转换的横向链式图（6 个及以上节点的 flowchart LR）")


if __name__ == "__main__":
    main()