#!/usr/bin/env python3
"""
Mermaid .mmd → SVG 通用渲染器（mermaid.ink API）
================================================
自动扫描 mermaid 目录下的所有 .mmd 文件，通过 mermaid.ink 免费 API 渲染为 SVG，
支持 base64 和 zlib 两种编码策略，写入 images 目录。

用法：
  python scripts/render_mermaid.py --mermaid-dir runs/xxx/output/mermaid
  python scripts/render_mermaid.py --mermaid-dir runs/xxx/output/mermaid --images-dir runs/xxx/output/images
  python scripts/render_mermaid.py --mermaid-dir runs/xxx/output/mermaid --dry-run
"""
import base64
import argparse
import re
import sys
import zlib
from pathlib import Path
from urllib.request import urlopen, Request


def _quote_url_nodes(text: str) -> str:
    """mermaid.ink 对节点文本中的 URL（含 :// 未加引号）返回 400，自动补引号兜底。"""
    return re.sub(r"\[([^\[\]\"']*://[^\[\]]*)\]", r'["\1"]', text)


def _is_light_color(color: str) -> bool:
    """判断 mermaid 的填充色是否为浅色（hsl 亮度 > 60% 或十六进制相对亮度 > 0.6）。"""
    color = color.strip()
    m = re.match(r"hsl\(\s*[^,]+,\s*[^%]+%,\s*([\d.]+)%\s*\)", color)
    if m:
        return float(m.group(1)) > 60
    if color.startswith("#") and len(color) in (4, 7):
        h = color[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6
    return False


def _fix_light_text(svg: str) -> str:
    """浅色节点上的白色文字 → 深灰，修复对比度。

    mermaid 默认主题会按 section 给节点配色，部分 section（mindmap 分支、timeline 分段）
    的底色是浅色（hsl 亮度 70%+），文字却仍是白色，白字压浅底几乎无法阅读。
    这里按每个 section 的实际填充色判断亮度，只改浅色 section 的文字/图标颜色，
    深色 section（如 timeline 根节点）保持白字。

    mindmap 例外：mermaid.ink 渲染出的 mindmap 节点（含根节点）实际都是浅色底，
    因此对 mindmap 直接把所有白色文字统一改成深灰。
    """
    if "mindmapDiagram" in svg:
        svg = svg.replace("fill:#ffffff", "fill:#1f2937")
        svg = svg.replace("color:#ffffff", "color:#1f2937")
        return svg

    fills = re.findall(
        r"#mermaid-svg \.section-([A-Za-z0-9_-]+) (?:rect|path|circle|polygon)"
        r"[^{]*\{fill:(#[0-9a-fA-F]{3,6}|hsl\([^)]*\))", svg)
    for key, color in fills:
        if not _is_light_color(color):
            continue
        k = re.escape(key)
        svg = re.sub(rf"(section-{k} text{{fill:)#ffffff", r"\1#1f2937", svg)
        svg = re.sub(rf"(section-{k} span{{color:)#ffffff", r"\1#1f2937", svg)
        svg = re.sub(rf"(node-icon-{k}{{font-size:40px;color:)#ffffff", r"\1#1f2937", svg)
    return svg


def render(mmd_path: Path, svg_path: Path) -> bool:
    text = mmd_path.read_text(encoding="utf-8").strip()

    variants = [text]
    fixed = _quote_url_nodes(text)
    if fixed != text:
        variants.append(fixed)

    for text in variants:
        raw = text.encode("utf-8")

        strategies = [
            ("b64+urlencode", lambda: base64.urlsafe_b64encode(raw).decode("ascii")),
        ]
        if len(raw) > 50:
            strategies.append((
                "zlib+b64",
                lambda: base64.urlsafe_b64encode(zlib.compress(raw)[2:-4]).decode("ascii"),
            ))

        for name, encoder in strategies:
            try:
                encoded = encoder()
                url = f"https://mermaid.ink/svg/{encoded}"
                req = Request(url, headers={"User-Agent": "video-notes-pipeline/1.0"})
                with urlopen(req, timeout=30) as resp:
                    svg = resp.read().decode("utf-8")
                    svg = _fix_light_text(svg)
                    svg_path.write_text(svg, encoding="utf-8")
                    print(f"  [ok] {mmd_path.name} ({name})")
                    return True
            except Exception:
                continue

    print(f"  [error] {mmd_path.name} -> 所有策略均失败", file=sys.stderr)
    return False


def main():
    ap = argparse.ArgumentParser(description="Mermaid .mmd → SVG 渲染器")
    ap.add_argument("--mermaid-dir", required=True, help="存放 .mmd 文件的目录")
    ap.add_argument("--images-dir", default=None, help="输出 SVG 的目录（默认 mermaid-dir 的父级/images）")
    ap.add_argument("--dry-run", action="store_true", help="仅列出要渲染的文件，不执行")
    args = ap.parse_args()

    mermaid_dir = Path(args.mermaid_dir)
    if not mermaid_dir.is_dir():
        print(f"[error] mermaid 目录不存在: {mermaid_dir}", file=sys.stderr)
        sys.exit(1)

    images_dir = Path(args.images_dir) if args.images_dir else mermaid_dir.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    mmd_files = sorted(mermaid_dir.glob("*.mmd"))
    if not mmd_files:
        print(f"[warn] {mermaid_dir} 下没有 .mmd 文件")
        return

    if args.dry_run:
        print(f"发现 {len(mmd_files)} 个 .mmd 文件，将渲染到 {images_dir}：")
        for f in mmd_files:
            svg_name = f.stem + ".svg"
            print(f"  {f.name} -> {svg_name}")
        return

    ok = 0
    for mmd in mmd_files:
        svg = images_dir / (mmd.stem + ".svg")
        if render(mmd, svg):
            ok += 1

    print(f"\n完成: {ok}/{len(mmd_files)}")
    if ok < len(mmd_files):
        print(f"  [warn] {len(mmd_files) - ok} 个文件渲染失败，继续后续处理")


if __name__ == "__main__":
    main()