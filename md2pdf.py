#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown -> PDF（保留内嵌图片，供 ima 知识库入库）
=================================================
先把 Markdown 渲染成带样式的 HTML，再调用系统 Edge/Chrome 无头模式打印为 PDF。
选这条路的原因：中文字体、图片、超链接都能原样保留，且 Windows 必带 Edge，无需额外依赖。

用法：
  python md2pdf.py --input ./output/note.md --output ./output/note.pdf
"""
import os
import re
import sys
import shutil
import argparse
import subprocess
import tempfile
from pathlib import Path

try:
    import markdown as md_lib
except ImportError:
    md_lib = None


BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", "Source Han Sans SC", sans-serif;
  font-size: 11.5pt; line-height: 1.85; color: #1a1a1a; margin: 0;
}
h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 8px; margin: 0 0 18px; }
h2 { font-size: 15pt; margin: 24px 0 10px; padding-left: 9px; border-left: 4px solid #4a6fa5; }
h3 { font-size: 13pt; margin: 18px 0 8px; color: #2c4a70; }
p  { margin: 8px 0; text-align: justify; }
blockquote {
  margin: 10px 0; padding: 8px 14px; background: #f5f7fa;
  border-left: 3px solid #b8c4d4; color: #555; font-size: 10.5pt;
}
img { max-width: 100%; display: inline-block; border: 1px solid #ddd; border-radius: 3px; }
.img-wrap { text-align: center; margin: 12px auto 4px; }
.img-portrait img { max-width: 55%; }
.img-square img { max-width: 75%; }
.img-landscape img { max-width: 100%; }
div[align="center"] { text-align: center; font-size: 9.5pt; color: #666; margin-bottom: 16px; }
a { color: #4a6fa5; text-decoration: none; }
code { background: #f2f2f2; padding: 1px 5px; border-radius: 3px; font-size: 10pt; }
pre { background: #f7f7f7; padding: 10px 12px; border-radius: 4px; overflow-x: auto; }
pre code { background: none; }
ul, ol { padding-left: 24px; }
li { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 10.5pt; }
th, td { border: 1px solid #ccc; padding: 6px 10px; }
th { background: #eef2f7; }
hr { border: none; border-top: 1px solid #ddd; margin: 18px 0; }
"""


def find_browser():
    for p in BROWSER_CANDIDATES:
        if Path(p).exists():
            return p
    for name in ("msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _parse_viewbox(svg_text: str):
    m = re.search(r'viewBox="([^"]+)"', svg_text)
    if not m:
        return None
    parts = m.group(1).strip().split()
    if len(parts) != 4:
        return None
    return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])


def _classify_svg_images(html: str, base_dir: Path) -> str:
    """对 SVG 图片按宽高比分类，加外层 div 和 CSS 类"""
    def _wrap(m):
        src = m.group(1)
        img_tag = m.group(0)
        svg_path = base_dir / src
        if not svg_path.exists():
            return img_tag
        svg_text = svg_path.read_text(encoding="utf-8")
        vb = _parse_viewbox(svg_text)
        if vb is None:
            return img_tag
        _, _, w, h = vb
        if w <= 0 or h <= 0:
            return img_tag
        ratio = w / h
        if ratio < 0.8:
            cls = "img-portrait"
        elif ratio > 1.5:
            cls = "img-landscape"
        else:
            cls = "img-square"
        return f'<div class="img-wrap {cls}">{img_tag}</div>'
    return re.sub(r'<img[^>]+src="([^"]+\.svg)"[^>]*>', _wrap, html, flags=re.IGNORECASE)


def _preprocess_markdown_images(md_text: str) -> str:
    """将<div align="center">内的 ![alt](path) 转换为 <img alt="alt" src="path">。
    markdown 库在 HTML 块标签内不解析 Markdown 图片，需要预处理。
    """
    def _replace_img(match):
        alt = match.group(1)
        src = match.group(2)
        return f'<img src="{src}" alt="{alt}">'
    # 匹配 ![...](...)，处理换行和空格
    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _replace_img, md_text)


def md_to_html(md_text: str, base_dir: Path, title: str) -> str:
    if md_lib is None:
        raise RuntimeError("缺少依赖：pip install markdown")
    # 预处理：将 ![alt](src) 转换为 <img>，解决 HTML 块内不解析问题
    md_text = _preprocess_markdown_images(md_text)
    body = md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "md_in_html"],
    )
    body = _classify_svg_images(body, base_dir)
    base_uri = base_dir.resolve().as_uri() + "/"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<base href="{base_uri}">
<title>{title}</title><style>{CSS}</style></head>
<body>{body}</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Markdown 转 PDF（内嵌图片）")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--keep-html", action="store_true", help="保留中间 HTML 便于排查")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"[error] 找不到输入文件: {src}", file=sys.stderr)
        sys.exit(1)

    out_pdf = Path(args.output) if args.output else src.with_suffix(".pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    md_text = src.read_text(encoding="utf-8")
    title = src.stem
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    if m:
        title = m.group(1).strip()

    html_path = src.with_suffix(".html")
    html_path.write_text(md_to_html(md_text, src.parent, title), encoding="utf-8")

    browser = find_browser()
    if not browser:
        print("[error] 未找到 Edge/Chrome，无法生成 PDF。HTML 已保留：" + str(html_path),
              file=sys.stderr)
        sys.exit(2)

    # 每次用独立的临时 user-data-dir，避免 Windows 下 msedge 与系统默认配置锁
    # 冲突导致 --headless 打印卡死（180s 超时退出）。用完即清。
    user_data_dir = tempfile.mkdtemp(prefix="md2pdf_edge_")
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=10000",
        f"--user-data-dir={user_data_dir}",
        f"--print-to-pdf={out_pdf.resolve()}",
        html_path.resolve().as_uri(),
    ]
    print(f"[pdf] 使用 {Path(browser).name} 打印 ...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)

    if not out_pdf.exists():
        print("[error] PDF 生成失败", file=sys.stderr)
        print(r.stderr[-1500:], file=sys.stderr)
        sys.exit(3)

    if not args.keep_html:
        try:
            html_path.unlink()
        except OSError:
            pass

    size_kb = out_pdf.stat().st_size / 1024
    print(f"[done] PDF: {out_pdf}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
