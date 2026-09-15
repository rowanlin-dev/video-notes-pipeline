#!/usr/bin/env python3
"""
从 Markdown 笔记中提取 Mermaid 代码块 → 保存为 .mmd 文件 → 替换为 <img> 标签
========================================================================
用法：
  python scripts/extract_mermaid.py --note output/note.md --mermaid-dir output/mermaid --img-prefix images

效果：
  - 把 note.md 中的 ```mermaid ... ``` 代码块提取为 .mmd 文件
  - 在原位置替换为 <img src="images/xxx.svg"> 标签
  - 更新后的 note.md 可直接用于 PDF 生成
"""
import re
import sys
import argparse
from pathlib import Path


def extract_mermaid_blocks(md_text: str):
    """提取所有 Mermaid 代码块，返回 [(序号, mermaid_code, 完整匹配), ...]"""
    pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)
    blocks = []
    for i, m in enumerate(pattern.finditer(md_text), 1):
        code = m.group(1).strip()
        if code:
            blocks.append((i, code, m))
    return blocks


def _safe_name(code: str, idx: int) -> str:
    """从代码第一行提取简短文件名。"""
    first = code.strip().split("\n")[0].strip()
    # 取前 5 个中文字符或 10 个英文字符
    name = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", first)[:12]
    if not name:
        name = f"diagram_{idx:02d}"
    return name


def main():
    ap = argparse.ArgumentParser(description="从 Markdown 提取 Mermaid 代码块")
    ap.add_argument("--note", required=True, help="输入 Markdown 文件路径")
    ap.add_argument("--mermaid-dir", required=True, help="输出 .mmd 文件目录")
    ap.add_argument("--img-prefix", default="images", help="图片相对路径前缀")
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不修改文件")
    args = ap.parse_args()

    note_path = Path(args.note)
    if not note_path.exists():
        print(f"[error] 文件不存在: {note_path}", file=sys.stderr)
        sys.exit(1)

    mermaid_dir = Path(args.mermaid_dir)
    mermaid_dir.mkdir(parents=True, exist_ok=True)

    md_text = note_path.read_text(encoding="utf-8")
    blocks = extract_mermaid_blocks(md_text)

    if not blocks:
        print(f"[warn] {note_path} 中没有 Mermaid 代码块")
        return

    print(f"发现 {len(blocks)} 个 Mermaid 代码块")

    # 保存 .mmd 文件并构建替换字典
    replacements = []
    for idx, code, match in blocks:
        name = _safe_name(code, idx)
        mmd_name = f"{idx:02d}_{name}.mmd"
        svg_name = f"{idx:02d}_{name}.svg"
        mmd_path = mermaid_dir / mmd_name

        if not args.dry_run:
            mmd_path.write_text(code, encoding="utf-8")
        print(f"  [{idx:02d}] {mmd_name}  ({len(code)} 字符)")

        # 替换：代码块 → <img> 标签（居中）
        img_tag = (
            f'<div align="center">\n'
            f'  <img src="{args.img_prefix}/{svg_name}" alt="图{idx} {name}" style="max-width: 90%;">\n'
            f'</div>'
        )
        replacements.append((match.start(), match.end(), img_tag))

    if args.dry_run:
        print(f"\n(dry-run 模式，未修改文件)")
        return

    # 从后往前替换，保持索引正确
    for start, end, tag in sorted(replacements, key=lambda x: x[0], reverse=True):
        md_text = md_text[:start] + "\n" + tag + "\n" + md_text[end:]

    # 清除 LLM 生成的虚假图片占位符（![图 N xxx](images/图_N_xxx.svg)）
    # 这些占位符引用的文件名与实际 SVG 不匹配，实际 SVG 已由上方 <img> 标签引用
    orphan_pattern = re.compile(r'!\[图\s+\d+\s+[^\]]*\]\(images/图_\d+_[^)]+\.svg\)')
    orphan_count = len(orphan_pattern.findall(md_text))
    if orphan_count:
        md_text = orphan_pattern.sub("", md_text)
        md_text = re.sub(r'\n{3,}', '\n\n', md_text)
        print(f"\n清除 {orphan_count} 个虚假图片占位符（LLM 生成的文件名不匹配）")

    note_path.write_text(md_text, encoding="utf-8")
    print(f"\n已更新: {note_path}")
    print(f"  Mermaid 文件: {mermaid_dir}/")
    print(f"  请运行 render_mermaid.py 将 .mmd 渲染为 SVG")


if __name__ == "__main__":
    main()