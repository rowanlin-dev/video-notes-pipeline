#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动精选帧：读取 vision_scores_*.json，按分数降序、要求 complete=True，
并用关键词 Jaccard 相似度去重以保证多样性，精选 7-12 帧复制到 final/ 目录。

用法：
  python auto_select.py \
    --scores ./workspace/vision_scores_pXX.json \
    --selected-dir ./frames/pXX/selected \
    --final-dir ./frames/pXX/final
"""
import os
import re
import sys
import json
import argparse
import shutil
from pathlib import Path


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_env(root: Path = None):
    """读取项目根目录 .env，不覆盖已有环境变量。"""
    if root is None:
        root = Path(__file__).resolve().parent
    f = root / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def parse_keywords(raw: str) -> list:
    """把逗号分隔的关键词字符串拆成列表；空字符串返回空列表。"""
    return [k.strip() for k in raw.split(",") if k.strip()] if raw else []


def load_learned_trash(path: Path) -> list:
    """
    读取自进化黑名单 trash_learned.json，返回可用于正则匹配的 pattern 列表。
    对非正则条目做 re.escape，避免图中文字里的特殊字符干扰匹配。
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for p in data.get("patterns", []):
        value = str(p.get("value", "")).strip()
        if not value or len(value) < 2:
            continue
        # 简单规则：若 value 里包含正则元字符，且用户显式写了 .* 等，则原样使用；
        # 否则转义成字面量，避免普通文本里的 ()[] 触发正则错误。
        if re.search(r"[.*+?^${}()|[\]\\]", value) and any(c in value for c in [".*", "+", "?"]):
            out.append(value)
        else:
            out.append(re.escape(value))
    return out


DEFAULT_TYPE_TRASH = {"meme", "blackscreen", "ad", "face"}


def is_trash(info: dict, patterns: list, min_score: int,
             type_trash: set = None, ocr_text: str = "") -> tuple:
    """
    判断一帧是否应被剔除。
    返回 (是否剔除, 原因)。
    检查范围：type 字段、has_educational_visual、score、theme/keywords/text/content/reasoning、ocr_text。
    """
    score = int(info.get("score", 0) or 0)
    if score < min_score:
        return True, f"score={score} < min_score={min_score}"

    frame_type = str(info.get("type", "")).lower().strip()
    type_trash = type_trash or DEFAULT_TYPE_TRASH
    if frame_type in type_trash:
        return True, f"type={frame_type} 在垃圾类型黑名单中"

    # 没有教育视觉元素且分数不高的帧，通常是黑屏字幕或低价值画面
    has_visual = info.get("has_educational_visual")
    if has_visual is False and score < 5:
        return True, "has_educational_visual=false 且 score<5（纯字幕黑屏/低价值画面）"

    if not patterns:
        return False, ""

    haystacks = [
        str(info.get("theme", "")),
        " ".join(str(k) for k in info.get("keywords", [])),
        str(info.get("text", "")),
        str(info.get("content", "")),
        str(info.get("reasoning", "")),
        str(ocr_text),
    ]
    text = "\n".join(haystacks)
    for p in patterns:
        try:
            if re.search(p, text, re.IGNORECASE):
                return True, f"命中黑名单正则: {p}"
        except re.error:
            # 非法正则退化为字面量匹配
            if p in text:
                return True, f"命中黑名单关键词: {p}"
    return False, ""


def main():
    # 先加载 .env，再解析参数，否则 default 里读不到 FRAME_* 配置
    load_env()

    ap = argparse.ArgumentParser(description="自动精选 7-12 帧到 final/")
    ap.add_argument("--scores", required=True, help="vision_scores_*.json 路径")
    ap.add_argument("--selected-dir", required=True, help="去重后的 selected/ 帧目录")
    ap.add_argument("--final-dir", required=True, help="输出 final/ 帧目录")
    ap.add_argument("--min", type=int, default=7, help="最少帧数")
    ap.add_argument("--max", type=int, default=12,
                    help="基础上限：候选帧少时取此值；候选帧多（操作步骤多）时按候选数×0.6 自动放宽")
    ap.add_argument("--hard-max", type=int,
                    default=int(os.getenv("FRAME_HARD_MAX", "40")),
                    help="绝对上限（默认 40），防止候选极多时失控（每帧需 2 次视觉模型调用）")
    ap.add_argument("--similarity-threshold", type=float, default=0.5,
                    help="关键词相似度阈值，超过则视为重复主题跳过")
    ap.add_argument("--trash-keywords", default=os.getenv("FRAME_TRASH_KEYWORDS", ""),
                    help="逗号分隔的垃圾帧黑名单（支持正则），例：白嫖,一键三连,求赞")
    ap.add_argument("--min-score", type=int, default=int(os.getenv("FRAME_MIN_SCORE", "3")),
                    help="入选帧最低 AI 分数")
    ap.add_argument("--learned-trash", default=os.getenv("LEARNED_TRASH_FILE", ""),
                    help="自进化黑名单文件路径，默认项目根目录 trash_learned.json")
    ap.add_argument("--type-trash", default=os.getenv("FRAME_TYPE_TRASH", "meme,blackscreen,ad,face"),
                    help="逗号分隔的低价值 type 类型，默认 meme,blackscreen,ad,face")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    learned_path = Path(args.learned_trash) if args.learned_trash else root / "trash_learned.json"
    learned_patterns = load_learned_trash(learned_path)

    patterns = parse_keywords(args.trash_keywords) + learned_patterns
    min_score = args.min_score
    type_trash = set(t.strip().lower() for t in args.type_trash.split(",") if t.strip())
    if learned_patterns:
        print(f"[learned] 已加载 {len(learned_patterns)} 条自进化黑名单特征（{learned_path}）")
    if type_trash:
        print(f"[type-trash] 低价值类型黑名单: {', '.join(sorted(type_trash))}")

    scores = json.load(open(args.scores, encoding="utf-8"))

    # 对候选帧进行 OCR 二次校验（尤其是识别图中广告文字）
    selected_dir = Path(args.selected_dir)
    ocr_cache = {}
    if patterns:
        try:
            from rapidocr_onnxruntime import RapidOCR
            ocr = RapidOCR()
            for k in scores:
                img = selected_dir / k
                if not img.exists():
                    continue
                try:
                    result = ocr(str(img))
                    if result and result[0]:
                        ocr_cache[k] = " ".join(item[1] for item in result[0])
                except Exception as e:
                    print(f"  [warn] OCR {k} 失败: {e}")
        except ImportError:
            print("  [warn] 未安装 rapidocr_onnxruntime，跳过 OCR 二次校验")

    # 过滤掉分析失败、分数过低、命中垃圾黑名单的帧
    valid = {}
    for k, v in scores.items():
        if v.get("error") is not None:
            continue
        trash, reason = is_trash(v, patterns, min_score, type_trash=type_trash,
                                 ocr_text=ocr_cache.get(k, ""))
        if trash:
            print(f"[trash] {k} 已剔除 ({reason})")
            continue
        valid[k] = v

    # 按分数降序
    ranked = sorted(valid.items(), key=lambda kv: kv[1].get("score", 0), reverse=True)

    final_path = Path(args.final_dir)
    final_path.mkdir(parents=True, exist_ok=True)
    # 清理 final 目录中可能残留的旧帧（上一次运行未完全删除时）
    for old in final_path.glob("*.jpg"):
        try:
            old.unlink()
        except Exception:
            try:
                old.rename(old.with_suffix(old.suffix + ".stale"))
            except Exception:
                print(f"[warn] 无法清理旧帧 {old.name}，已忽略")
    chosen, chosen_kw = [], []
    # 自适应上限：候选多（如操作步骤多）时放宽 max，但受 hard_max 绝对兜底
    n_valid = len(valid)
    effective_max = min(args.hard_max, max(args.max, int(n_valid * 0.6)))
    if effective_max != args.max:
        print(f"[select] 候选 {n_valid} 帧，max={args.max} 自动放宽至 {effective_max}"
              f"（hard_max={args.hard_max}）")

    for name, info in ranked:
        if len(chosen) >= effective_max:
            break
        kw = set(info.get("keywords", []))
        too_similar = any(jaccard(kw, ck) >= args.similarity_threshold for ck in chosen_kw)
        if too_similar:
            continue
        src = Path(args.selected_dir) / name
        if not src.exists():
            continue
        shutil.copy(src, Path(args.final_dir) / name)
        chosen.append(name)
        chosen_kw.append(kw)
        print(f"[select] {name} score={info.get('score')} theme={info.get('theme', '')[:30]}")

    # 若去重后不足 min，放宽阈值再补（仍不放宽黑名单/最低分）
    if len(chosen) < args.min:
        for name, info in ranked:
            if name in chosen:
                continue
            if len(chosen) >= args.min:
                break
            src = Path(args.selected_dir) / name
            if not src.exists():
                continue
            shutil.copy(src, Path(args.final_dir) / name)
            chosen.append(name)
            print(f"[select+] {name} score={info.get('score')}")

    print(f"\n[done] 精选 {len(chosen)} 帧 -> {args.final_dir}")

    out = Path(args.final_dir) / "_selected.json"
    json.dump(
        {"frames": chosen, "scores": {k: scores[k] for k in chosen}},
        open(out, "w", encoding="utf-8"),
        ensure_ascii=False, indent=2,
    )
    print(f"[done] 选中清单: {out}")


if __name__ == "__main__":
    main()
