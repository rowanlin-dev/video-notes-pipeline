#!/usr/bin/env python3
"""
动态甘特图生成器 — 根据标签文本长度自动计算布局
=============================================
用法：
  python generate_gantt.py --config gantt_config.json --output images/gantt.svg

Config JSON 格式：
{
  "title": "标题",
  "rows": [
    {"label": "标签文本", "start": 0, "end": 10, "class": "req"},
    ...
  ],
  "legend": [
    {"label": "图例项", "class": "req"},
    ...
  ]
}

核心逻辑：
  1. 遍历所有 label，用 fontmetrics 估算最大文本宽度
  2. 标签区宽度 = 最大文本宽度 + 10px 右内边距
  3. viewBox = 标签区宽度 + 网格区宽度 + 右内边距
  4. 所有元素坐标按标签区宽度动态平移
"""

import json, math, argparse
from pathlib import Path

# 字体度量（Microsoft YaHei 12px 近似值）
CJK_W = 12    # 中文字符宽度
ASCII_W = 7   # ASCII 字符宽度
DIGIT_W = 7   # 数字宽度
PUNCT_W = 6   # 标点宽度
FONT_SIZE = 12
LABEL_PAD = 10   # 标签右边界到网格左边界的间距
RIGHT_PAD = 20    # 网格右边界到 viewBox 右边距

# 格坐标映射（11px/分钟，从 0 开始）
def grid_x(minute):
    return minute * 11

# 估算文本宽度
def text_width(text):
    w = 0
    for ch in text:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:  # CJK
            w += CJK_W
        elif 0x30 <= cp <= 0x39:  # 数字
            w += DIGIT_W
        elif ch in '()（）[]【】{}《》<>/\\+=-':
            w += PUNCT_W
        else:
            w += ASCII_W
    return w

# 颜色映射
COLOR_CLASSES = {
    "req":    {"fill": "#c7d2fe", "stroke": "#6366f1", "label": "需求分析"},
    "infra":  {"fill": "#a7f3d0", "stroke": "#059669", "label": "基础设施"},
    "core":   {"fill": "#fde68a", "stroke": "#d97706", "label": "核心开发"},
    "finish": {"fill": "#fecaca", "stroke": "#dc2626", "label": "收尾交付"},
}

def generate(config_path, output_path):
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    rows = cfg["rows"]
    title = cfg.get("title", "甘特图")
    legend = cfg.get("legend", [])

    # 1) 计算最大标签宽度
    max_label_w = max(text_width(r["label"]) for r in rows) if rows else 0

    # 2) 标签区宽度 = 最大文本宽度 + 内边距
    label_area = max_label_w + LABEL_PAD

    # 3) 网格区宽度 = 最大分钟 × 11px
    max_min = max(r["end"] for r in rows) if rows else 60
    grid_w = grid_x(max_min)

    # 4) viewBox
    vb_w = label_area + grid_w + RIGHT_PAD
    vb_h = 340

    # 5) 网格起点
    g0 = label_area  # grid x=0 的位置

    # 6) 行高布局
    row_h = 28
    row_gap = 10
    row_y = lambda i: 35 + i * (row_h + row_gap)  # 矩形 y
    row_text_y = lambda i: row_y(i) + row_h - 6    # 文本 y（垂直居中偏下）

    # 构建 SVG
    svg = []

    def a(tag, attrs, content=None):
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        if content is None:
            svg.append(f"  <{tag} {attr_str}/>")
        else:
            svg.append(f"  <{tag} {attr_str}>{content}</{tag}>")

    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w} {vb_h}" width="100%" height="auto">')
    svg.append('  <defs>')
    svg.append('    <style>')
    svg.append('      .g-title { fill: #1e1b4b; font-size: 15px; font-weight: 600; font-family: "Microsoft YaHei", sans-serif; }')
    svg.append('      .g-label { fill: #1e1b4b; font-size: 12px; text-anchor: end; font-family: "Microsoft YaHei", sans-serif; }')
    svg.append('      .g-time-label { fill: #fff; font-size: 9px; font-weight: 600; text-anchor: middle; font-family: "Microsoft YaHei", sans-serif; }')
    svg.append('      .g-legend-text { fill: #6b7280; font-size: 10px; font-family: "Microsoft YaHei", sans-serif; }')
    svg.append('      .g-grid-line { stroke: #e5e7eb; stroke-width: 1; }')
    svg.append('      .g-grid-label { fill: #9ca3af; font-size: 10px; text-anchor: middle; font-family: "Microsoft YaHei", sans-serif; }')
    for cls, c in COLOR_CLASSES.items():
        svg.append(f'      .g-bar-{cls} {{ fill: {c["fill"]}; stroke: {c["stroke"]}; stroke-width: 1; rx: 3; ry: 3; }}')
    svg.append('    </style>')
    svg.append('  </defs>')

    # Title
    title_x = vb_w // 2
    svg.append(f'  <text x="{title_x}" y="25" text-anchor="middle" class="g-title">{title}</text>')

    svg.append(f'  <g transform="translate(0, 40)">')

    # 网格线 + 时间刻度（5分钟间隔）
    for m in range(0, max_min + 1, 5):
        x = g0 + grid_x(m)
        a("line", {"x1": x, "y1": 0, "x2": x, "y2": row_y(len(rows)) + 10, "class": "g-grid-line", "stroke-dasharray": "3,3"})
        a("text", {"x": x, "y": 15, "class": "g-grid-label"}, str(m))

    # 行
    for i, r in enumerate(rows):
        cls = r.get("class", "core")
        label_x = g0 - LABEL_PAD  # 右对齐，网格左侧
        a("text", {"x": label_x, "y": row_text_y(i), "class": "g-label"}, r["label"])
        bar_x = g0 + grid_x(r["start"])
        bar_w = grid_x(r["end"]) - grid_x(r["start"])
        a("rect", {"x": bar_x, "y": row_y(i), "width": bar_w, "height": row_h, "class": f"g-bar-{cls}"})
        # 时间标签居中在色条上
        time_cx = bar_x + bar_w // 2
        time_cy = row_y(i) + row_h // 2 + 3
        a("text", {"x": time_cx, "y": time_cy, "class": "g-time-label"}, f"{r['start']}-{r['end']}min")

    svg.append(f'  </g>')

    # 图例
    if legend:
        svg.append(f'  <g transform="translate({g0}, 290)">')
        a("text", {"x": 0, "y": 12, "class": "g-legend-text"}, "图例:")
        x = 50
        for item in legend:
            cls = item.get("class", "req")
            c = COLOR_CLASSES.get(cls, COLOR_CLASSES["req"])
            a("rect", {"x": x, "y": 0, "width": 16, "height": 16, "class": f"g-bar-{cls}"})
            x += 22
            a("text", {"x": x, "y": 13, "class": "g-legend-text"}, item.get("label", c["label"]))
            x += text_width(item.get("label", c["label"])) + 20
        svg.append(f'  </g>')

    svg.append('</svg>')

    Path(output_path).write_text("\n".join(svg), encoding="utf-8")
    max_label = max(rows, key=lambda r: text_width(r["label"]))["label"]
    print(f"[ok] 甘特图已生成: {output_path}")
    print(f"     viewBox: 0 0 {vb_w} {vb_h}")
    print(f"     标签区宽度: {label_area}px (最大标签 '{max_label}' = {max_label_w}px)")
    print(f"     网格起点: x={g0}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="动态甘特图生成器")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--output", required=True, help="输出 SVG 路径")
    args = parser.parse_args()
    generate(args.config, args.output)