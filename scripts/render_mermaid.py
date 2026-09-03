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
import sys
import zlib
from pathlib import Path
from urllib.request import urlopen, Request


def render(mmd_path: Path, svg_path: Path) -> bool:
    text = mmd_path.read_text(encoding="utf-8").strip()
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
        sys.exit(1)


if __name__ == "__main__":
    main()