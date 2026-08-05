#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
垃圾帧自进化黑名单
==================
发现某帧是求点赞/片头/广告等垃圾帧后，运行本脚本把它“记住”，
下次 auto_select 会自动剔除相似帧。

用法：
  python learn_trash.py runs/BV1AaN162EsX_p1 --frame frame_0002.jpg
  python learn_trash.py runs/BV1AaN162EsX_p1 --frame frame_0002.jpg --delete

--delete 会同时从 final/ 和 selected/ 删除该帧文件（默认只学习不删）。
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime


LEARNED_FILE = "trash_learned.json"


def load_learned(root: Path) -> dict:
    p = root / LEARNED_FILE
    if not p.exists():
        return {"version": 1, "updated_at": "", "patterns": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated_at": "", "patterns": []}


def save_learned(root: Path, data: dict):
    p = root / LEARNED_FILE
    data["updated_at"] = datetime.now().isoformat()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_patterns(scores: dict, extracts: dict, frame_name: str, bvid: str):
    """从 vision_scores.json / vision_extract.json 提取可学习的黑名单特征。"""
    info = scores.get(frame_name, {})
    ext = extracts.get(frame_name, {})
    if isinstance(ext, dict) and "results" in ext:
        ext = ext["results"]

    patterns = []

    # 1. theme
    theme = str(info.get("theme", "")).strip()
    if theme and len(theme) >= 2:
        patterns.append({"type": "theme", "value": theme, "source": frame_name, "bvid": bvid})

    # 2. keywords
    for kw in info.get("keywords", []):
        kw = str(kw).strip()
        if kw and len(kw) >= 2:
            patterns.append({"type": "keyword", "value": kw, "source": frame_name, "bvid": bvid})

    # 3. 图中文字 / content / text
    texts = []
    if isinstance(ext, dict):
        texts.append(str(ext.get("text", "")))
        texts.append(str(ext.get("content", "")))
    if isinstance(ext, str):
        texts.append(ext)
    for t in texts:
        t = t.strip()
        if not t:
            continue
        # 只取前 40 字作为特征，避免图中文字过长导致正则问题
        snippet = t[:40].strip()
        if len(snippet) >= 4:
            patterns.append({"type": "text", "value": snippet, "source": frame_name, "bvid": bvid})

    return patterns


def dedupe(existing: list, new: list) -> list:
    """去重：相同 value 保留已有的（保留最早学习时间）。"""
    seen = {p["value"] for p in existing}
    out = list(existing)
    for p in new:
        if p["value"] not in seen:
            out.append(p)
            seen.add(p["value"])
    return out


def main():
    ap = argparse.ArgumentParser(description="把某个垃圾帧的特征写进自进化黑名单")
    ap.add_argument("run_dir", help="本次运行的 workspace 目录，例如 runs/BV1AaN162EsX_p1")
    ap.add_argument("--frame", required=True, help="要学习的帧文件名，例如 frame_0002.jpg")
    ap.add_argument("--delete", action="store_true",
                    help="同时从 final/ 和 selected/ 删除该帧文件")
    ap.add_argument("--root", default=None,
                    help="项目根目录（trash_learned.json 存放位置），默认取 run_dir 的父目录")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"[error] 运行目录不存在：{run_dir}", file=sys.stderr)
        sys.exit(1)

    root = Path(args.root) if args.root else run_dir.parent.parent
    scores_path = run_dir / "vision_scores.json"
    extract_path = run_dir / "vision_extract.json"

    if not scores_path.exists():
        print(f"[error] 找不到打分文件：{scores_path}", file=sys.stderr)
        sys.exit(1)

    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    extracts = json.loads(extract_path.read_text(encoding="utf-8")) if extract_path.exists() else {}

    if args.frame not in scores:
        print(f"[error] 找不到帧 {args.frame}，可选：{list(scores.keys())[:20]}", file=sys.stderr)
        sys.exit(1)

    bvid = run_dir.name.split("_")[0] if "_" in run_dir.name else run_dir.name
    new_patterns = extract_patterns(scores, extracts, args.frame, bvid)
    if not new_patterns:
        print("[warn] 没能从该帧提取到可学习特征")
        sys.exit(0)

    learned = load_learned(root)
    before = len(learned["patterns"])
    learned["patterns"] = dedupe(learned["patterns"], new_patterns)
    added = len(learned["patterns"]) - before
    save_learned(root, learned)

    print(f"[ok] 已从 {args.frame} 学习 {added} 条新黑名单特征（累计 {len(learned['patterns'])} 条）")
    for p in new_patterns[:5]:
        print(f"  + [{p['type']}] {p['value'][:40]}")

    if args.delete:
        deleted = 0
        for sub in ["final", "selected"]:
            p = run_dir / sub / args.frame
            try:
                if p.exists():
                    p.unlink()
                    deleted += 1
                    print(f"[delete] {p}")
            except Exception as e:
                print(f"[warn] 删除失败 {p}: {e}")
        print(f"[ok] 已删除 {deleted} 个副本")


if __name__ == "__main__":
    main()
