#!/usr/bin/env python3
"""
修正 Mermaid SVG 的对比度缺陷（mindmap 专用）
============================================
问题：Mermaid 默认 mindmap 调色板里，若干分区（section-root / section--1 /
section-2 …）的节点填充是浅色（lightness≈76%），但文字却被定义成白色
（`.section-2 text{fill:#ffffff}`），导致浅底白字、几乎看不见。

做法：向 SVG 注入一段高优先级的 <style>，把节点内文字统一强制为深色墨水色，
不改变任何节点填充与连线，因此不会破坏原有配色版式，只修可见性。

用法：
  python scripts/normalize_svg_contrast.py --dir output/images
  python scripts/normalize_svg_contrast.py --file output/images/01_mindmap.svg

幂等：已注入过则跳过；非 Mermaid SVG 自动忽略。
"""
import argparse
import sys
from pathlib import Path

MARKER = "svg-contrast-fix"
INK = "#1f2937"

OVERRIDE = (
    f"<style id=\"{MARKER}\">"
    "text, tspan, .nodeLabel, .nodeLabel p, .mindmap-node-label, "
    ".markdown-node-label, .markdown-node-label p, .markdown-node-label span "
    f"{{ fill: {INK} !important; color: {INK} !important; }}"
    "</style>"
)


def patch(svg_path: Path) -> bool:
    text = svg_path.read_text(encoding="utf-8")
    if "<svg" not in text:
        return False
    if MARKER in text:
        return False
    idx = text.rfind("</svg>")
    if idx == -1:
        return False
    svg_path.write_text(text[:idx] + OVERRIDE + text[idx:], encoding="utf-8")
    return True


def main():
    ap = argparse.ArgumentParser(description="修正 Mermaid SVG 文字对比度")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", help="SVG 所在目录")
    src.add_argument("--file", help="单个 SVG 文件")
    args = ap.parse_args()

    targets = [Path(args.file)] if args.file else sorted(Path(args.dir).glob("*.svg"))
    if not targets:
        print("[warn] 没有找到 SVG 文件")
        return

    fixed = 0
    for p in targets:
        if not p.exists():
            print(f"[skip] 文件不存在: {p}", file=sys.stderr)
            continue
        if patch(p):
            print(f"  [fix] {p.name}")
            fixed += 1
        else:
            print(f"  [skip] {p.name}")
    print(f"\n完成：{fixed} 个文件注入对比度修正")


if __name__ == "__main__":
    main()
