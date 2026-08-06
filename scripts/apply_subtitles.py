# -*- coding: utf-8 -*-
"""把修正后的字幕写回 pipeline 所需的 JSON + TXT（通用版）。

用法:
    python apply_subtitles.py <字幕JSON> [输出TXT]

字幕 JSON 期望格式: {"body": [{"from": 秒, "to": 秒, "content": "..."}]}
TXT 每行: [秒.秒-秒.秒] 文本
"""
import json, os, sys

SUBS_JSON = sys.argv[1] if len(sys.argv) > 1 else ""
if not SUBS_JSON:
    print("用法: python apply_subtitles.py <字幕JSON> [输出TXT]")
    sys.exit(1)
OUT_TXT = sys.argv[2] if len(sys.argv) > 2 else SUBS_JSON.rsplit(".json", 1)[0] + ".txt"

with open(SUBS_JSON, encoding="utf-8") as fh:
    data = json.load(fh)
body = data["body"]

os.makedirs(os.path.dirname(os.path.abspath(OUT_TXT)), exist_ok=True)
with open(OUT_TXT, "w", encoding="utf-8") as fh:
    for s in body:
        fh.write(f"[{s['from']:.1f}-{s['to']:.1f}] {s['content']}\n")
print(f"已写出 {len(body)} 条 → {OUT_TXT}")
