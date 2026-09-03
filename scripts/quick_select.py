#!/usr/bin/env python3
"""快速精选：从 vision_scores.json 选分数最高的不重复主题帧"""
import json, shutil, sys
from pathlib import Path

scores_path = Path(sys.argv[1])
selected_dir = Path(sys.argv[2])
final_dir = Path(sys.argv[3])
min_frames = int(sys.argv[4]) if len(sys.argv) > 4 else 5
max_frames = int(sys.argv[5]) if len(sys.argv) > 5 else 12
hard_max = int(sys.argv[6]) if len(sys.argv) > 6 else 30

scores = json.loads(scores_path.read_text(encoding="utf-8"))
valid = {k: v for k, v in scores.items() if not v.get("error")}
print(f"有效帧: {len(valid)}/{len(scores)}")

# 剔除低分和黑屏类
ok = {}
for k, v in valid.items():
    s = int(v.get("score", 0))
    t = str(v.get("type", "")).lower().strip()
    if s < 3 or t in ("blackscreen", "meme", "ad", "face"):
        print(f"  剔除: {k} score={s} type={t}")
        continue
    ok[k] = v

ranked = sorted(ok.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)
eff_max = min(hard_max, max(max_frames, int(len(ok) * 0.6)))
print(f"候选 {len(ok)} 帧，effective_max={eff_max}")

final_dir.mkdir(parents=True, exist_ok=True)
for old in final_dir.glob("*.jpg"):
    old.unlink(missing_ok=True)

chosen, chosen_kw = [], []
for name, info in ranked:
    if len(chosen) >= eff_max:
        break
    kw = set(info.get("keywords", []))
    # 简单 Jaccard 去重
    too_sim = False
    for ck in chosen_kw:
        if not kw and not ck:
            inter = 0
        else:
            inter = len(kw & ck) / len(kw | ck) if kw | ck else 0
        if inter >= 0.5:
            too_sim = True
            break
    if too_sim:
        continue
    src = selected_dir / name
    if not src.exists():
        print(f"  [warn] 源文件不存在: {name}")
        continue
    shutil.copy(src, final_dir / name)
    chosen.append(name)
    chosen_kw.append(kw)
    print(f"  [select] {name} score={info.get('score')} {info.get('theme', '')[:40]}")

# 补足到 min_frames
if len(chosen) < min_frames:
    for name, info in ranked:
        if name in chosen:
            continue
        if len(chosen) >= min_frames:
            break
        src = selected_dir / name
        if src.exists():
            shutil.copy(src, final_dir / name)
            chosen.append(name)
            print(f"  [补选] {name} score={info.get('score')}")

print(f"\n最终精选: {len(chosen)} 帧 → {final_dir}")