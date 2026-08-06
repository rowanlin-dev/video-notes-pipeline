# -*- coding: utf-8 -*-
"""MD -> HTML -> weasyprint TTF 字体 PDF（通用版）。

解决本机无 Chrome/Edge 时 md2pdf 的 PDF 中文豆腐块问题：
- 必须用 TTF 版中文字体（OTF/CFF 版 fontconfig 加载失败）
- weasyprint + FontConfiguration + @font-face 注入

用法:
    python gen_full_note.py <笔记MD> [标题] [字体TTF路径]

示例:
    python gen_full_note.py runs/BV1xx411c7mD_p1/output/xxx.md "标题" fonts/NotoSansSC-Variable.ttf
"""
import os, sys
from pathlib import Path

# 复用 md2pdf.py 的渲染函数
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from md2pdf import md_to_html

MD = sys.argv[1] if len(sys.argv) > 1 else ""
if not MD:
    print("用法: python gen_full_note.py <笔记MD> [标题] [字体TTF路径]")
    sys.exit(1)

OUT_DIR = os.path.dirname(os.path.abspath(MD))
TITLE = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(os.path.basename(MD))[0]
FONT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(BASE_DIR, "fonts", "NotoSansSC-Variable.ttf")

HTML_PATH = os.path.join(OUT_DIR, TITLE + ".html")
PDF = os.path.join(OUT_DIR, TITLE + ".pdf")

# 1. MD -> HTML
with open(MD, encoding="utf-8") as fh:
    md_text = fh.read()
html = md_to_html(md_text, Path(OUT_DIR), TITLE)
with open(HTML_PATH, "w", encoding="utf-8") as fh:
    fh.write(html)
print("HTML 已生成:", os.path.getsize(HTML_PATH) // 1024, "KB")

# 2. 注入 @font-face + weasyprint 生成 PDF
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

font_name = os.path.splitext(os.path.basename(FONT))[0]
font_face = f"""
@font-face {{
  font-family: "{font_name}";
  src: url("{os.path.basename(FONT)}");
}}
body {{ font-family: "{font_name}", sans-serif !important; }}
"""

if "@font-face" not in html:
    html = html.replace("</head>", "<style>" + font_face + "</style></head>")
    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(html)

font_config = FontConfiguration()
HTML(string=html, base_url=OUT_DIR).write_pdf(PDF, font_config=font_config)
print("PDF 已生成:", os.path.getsize(PDF) // 1024, "KB")
