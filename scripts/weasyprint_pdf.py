# -*- coding: utf-8 -*-
"""MD -> HTML -> weasyprint TTF 字体 PDF（独立版，无需 Chrome/Edge）。

与 scripts/gen_full_note.py 功能一致，但做成可单独调用的 CLI：
当本机没有 Chrome/Edge（md2pdf 默认渲染器）时，用它生成中文 PDF，
避免「豆腐块」乱码。必须用 TTF 版中文字体（OTF/CFF 版 fontconfig 加载失败）。

用法:
    python scripts/weasyprint_pdf.py <笔记MD> [输出PDF] [字体TTF路径]

示例:
    python scripts/weasyprint_pdf.py runs/BV1xx411c7mD_p1/output/xxx.md
    python scripts/weasyprint_pdf.py note.md out.pdf fonts/NotoSansSC-Variable.ttf
"""
import os
import sys
from pathlib import Path

# 复用 md2pdf.py 的渲染函数（与 gen_full_note.py 一致）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from md2pdf import md_to_html  # noqa: E402


def generate_pdf(md_path, out_pdf=None, font_path=None):
    md_path = os.path.abspath(md_path)
    out_dir = os.path.dirname(md_path)
    title = os.path.splitext(os.path.basename(md_path))[0]
    if out_pdf is None:
        out_pdf = os.path.join(out_dir, title + ".pdf")
    if font_path is None:
        font_path = os.path.join(BASE_DIR, "fonts", "NotoSansSC-Variable.ttf")

    # 1. MD -> HTML
    with open(md_path, encoding="utf-8") as fh:
        md_text = fh.read()
    html = md_to_html(md_text, Path(out_dir), title)
    html_path = os.path.join(out_dir, title + ".html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("HTML 已生成:", os.path.getsize(html_path) // 1024, "KB")

    # 2. 注入 @font-face + weasyprint 生成 PDF
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    font_name = os.path.splitext(os.path.basename(font_path))[0]
    font_face = f"""
@font-face {{
  font-family: "{font_name}";
  src: url("{os.path.basename(font_path)}");
}}
body {{ font-family: "{font_name}", sans-serif !important; }}
"""
    if "@font-face" not in html:
        html = html.replace("</head>", "<style>" + font_face + "</style></head>")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)

    font_config = FontConfiguration()
    HTML(string=html, base_url=out_dir).write_pdf(out_pdf, font_config=font_config)
    print("PDF 已生成:", os.path.getsize(out_pdf) // 1024, "KB")
    return out_pdf


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/weasyprint_pdf.py <笔记MD> [输出PDF] [字体TTF路径]")
        sys.exit(1)
    md = sys.argv[1]
    pdf = sys.argv[2] if len(sys.argv) > 2 else None
    font = sys.argv[3] if len(sys.argv) > 3 else None
    generate_pdf(md, pdf, font)
