#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown 图文笔记生成器
=======================
把「精选帧 + 图内文字提取 + 字幕全文」融合成一份结构化 Markdown 笔记，
每张配图下方带 B站时间戳跳转链接。

用法：
  python md_note.py \
    --bvid BV1xx411c7mD --page 1 --title "视频标题" \
    --final-dir ./frames/p1/final \
    --origin-map ./frames/p1/selected/_origin_map.json \
    --extract-json ./workspace/vision_extract_p1.json \
    --subtitle ./workspace/BV1xx411c7mD_p1_subtitles.txt \
    --output ./output/note.md
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# 学科自适应：从 scripts/ 导入模板 + 分类 + 字数预算
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
try:
    from note_subject import (SUBJECT_TEMPLATES, classify_subject, compute_note_budget)
except Exception:
    SUBJECT_TEMPLATES = {}
    def classify_subject(*a, **k): return "general"
    def compute_note_budget(*a, **k): return 3000


# ---------------------------------------------------------------- 时间戳解析
# extract_frames.py 的 seconds_to_time() 产出 "MMmSSs"（分钟数可超过 60），
# 帧名形如 frame_0007_01m23s.jpg
TS_MMSS_RE = re.compile(r"_(\d+)m(\d+)s")
# 兼容 HH-MM-SS 写法，便于将来换抽帧器
TS_HMS_RE = re.compile(r"_(\d{2})-(\d{2})-(\d{2})")


def parse_ts(origin_name: str, index: int, interval: int) -> int:
    """从原始帧名解析秒数；解析不到则按 index*interval 推算（fixed 模式）。"""
    name = origin_name or ""
    m = TS_MMSS_RE.search(name)
    if m:
        mm, s = (int(x) for x in m.groups())
        return mm * 60 + s
    m = TS_HMS_RE.search(name)
    if m:
        h, mm, s = (int(x) for x in m.groups())
        return h * 3600 + mm * 60 + s
    return max(0, (index - 1) * interval)


def fmt_ts(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def frame_index(name: str) -> int:
    m = re.search(r"frame_(\d+)", name)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------- 数据装载
def load_frames(final_dir, origin_map_path, extract_json, scores_json, interval, bvid, page):
    """汇总每一帧的：文件名、时间戳、主题、关键词、图内文字。"""
    origin_map = {}
    if origin_map_path and Path(origin_map_path).exists():
        origin_map = json.load(open(origin_map_path, encoding="utf-8"))

    extracted = {}
    if extract_json and Path(extract_json).exists():
        extracted = json.load(open(extract_json, encoding="utf-8"))

    scores = {}
    sel_file = Path(final_dir) / "_selected.json"
    if sel_file.exists():
        scores = json.load(open(sel_file, encoding="utf-8")).get("scores", {})
    elif scores_json and Path(scores_json).exists():
        scores = json.load(open(scores_json, encoding="utf-8"))

    frames = []
    for img in sorted(Path(final_dir).glob("*.jpg"), key=lambda p: frame_index(p.name)):
        name = img.name
        idx = frame_index(name)
        sec = parse_ts(origin_map.get(name, ""), idx, interval)
        info = extracted.get(name, {}) or {}
        sinfo = scores.get(name, {}) or {}
        frames.append({
            "file": name,
            "path": str(img),
            "seconds": sec,
            "timestamp": fmt_ts(sec),
            "url": f"https://www.bilibili.com/video/{bvid}/?p={page}&t={sec}",
            "theme": info.get("theme") or sinfo.get("theme") or "",
            "keywords": sinfo.get("keywords") or info.get("keywords") or [],
            "content": (info.get("text") or info.get("content") or
                        info.get("description") or "").strip(),
            "concepts": info.get("concepts") or [],
            "formulas": info.get("formulas") or [],
            "reasoning": (info.get("reasoning") or "").strip(),
            "tables": info.get("tables") or [],
            "score": sinfo.get("score", 0),
        })
    return frames


def load_subtitle(path, limit=60000):
    if not path or not Path(path).exists():
        return ""
    text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    if len(text) > limit:
        head = text[: int(limit * 0.6)]
        tail = text[-int(limit * 0.4):]
        text = head + "\n\n...（中段省略）...\n\n" + tail
    return text


def parse_subtitle_entries(path):
    """解析字幕 .txt 为 [(秒, 文本), ...]；忽略 # 头行。用于长视频切块。
    支持两种时间戳格式：
      - extract_frames 默认产出的 'MMmSSs'（分钟数可超过 60，如 [186m00s]）
      - 兼容 'HH:MM:SS' / 'MM:SS'
    """
    if not path or not Path(path).exists():
        return []
    entries = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[(\d+)m(\d+)s\]", line)          # MMmSSs
        if m:
            sec = int(m.group(1)) * 60 + int(m.group(2))
        else:
            m = re.match(r"^\[(?:(\d+):)?(\d+):(\d+)\]", line)  # HH:MM:SS / MM:SS
            if not m:
                continue
            sec = (int(m.group(1) or 0)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        txt = line[line.rfind("]") + 1:].strip()
        if txt:
            entries.append((sec, txt))
    return entries


def split_segments(entries, duration, seg_min=25, max_seg=12, min_seg=3):
    """按时长把字幕切成若干段，返回 [(start_sec, end_sec, idx), ...]。"""
    if not entries:
        return []
    last = entries[-1][0] or (duration or 0)
    if last < 60:
        last = max(last, 60)
    n = max(1, round(last / (seg_min * 60)))
    n = min(max(n, min_seg), max_seg)
    bounds = [round(last * i / n) for i in range(n + 1)]
    return [(bounds[i], bounds[i + 1], i + 1) for i in range(n)]


# ---------------------------------------------------------------- 学科自适应 prompt 拼装
# 图文穿插占位符：发给模型的必须是双花括号 {{FRAME:文件名}}（与 inject_frames 的宽松正则匹配）。
# 这里用普通字符串常量，避免 f-string 把双花括号误转义。
_FRAME_RULE = (
    "★ 最重要的一条：图文必须穿插 ★\n"
    "上面每张截图，都要在正文中它对应的那段内容处，单独一行插入占位符：\n"
    "    {{FRAME:文件名}}\n"
    "例如写到某个概念处，就在那一段后单独起一行写 `{{FRAME:frame_0003.jpg}}`。\n"
    "- 每张截图恰好插入一次，不能漏也不能重复。\n"
    "- 占位符必须独占一行，前后各空一行。\n"
    "- 严禁把所有占位符堆在文章末尾——必须分散在正文各处。\n"
    "- 截图已按时间顺序给出，插入顺序应与之大致一致。"
)
_NO_FRAME_NOTE = "（本视频无配图，纯文字笔记，不需要插入截图占位符。）"


def build_prompt(title, frames_desc, subtitle, template, target_chars, has_frames, sub_level=2):
    """按学科模板 + 目标字数拼装笔记生成 prompt（保留图文穿插规则）。
    sub_level: 小节标题层级（切块章节内用 3=###，单篇用 2=##）。"""
    h = "#" * sub_level
    role = template.get("role", "你是一名擅长做学习笔记的助手。")
    label = template.get("label", "通用")
    outline = template.get("outline", ["内容概要", "核心内容", "核心要点回顾"])
    guidance = template.get("guidance", "用通俗语言讲清机制，突出可迁移结论。")

    head = (f"{role}\n\n"
            f"请基于以下素材，写一份结构清晰、可直接入知识库的 Markdown 笔记。"
            f"本视频学科归类为「{label}」，请使用与之匹配的行文结构与侧重点。\n\n"
            f"【视频标题】{title}\n\n")
    if has_frames:
        head += (f"【视频关键截图】（已按时间顺序排列，每张图带编号、时间点、主题与图中文字）\n"
                 f"{frames_desc}\n\n")
    head += f"【字幕全文】\n{subtitle}\n\n"

    outline_txt = "\n".join(f"{i}. {s}" for i, s in enumerate(outline, 1))
    parts = ["写作要求："]
    if has_frames:
        parts.append(_FRAME_RULE)
    else:
        parts.append(_NO_FRAME_NOTE)
    parts.append(
        f"结构要求（严格按以下小节组织，每节一个 `{h}` 标题，顺序保持一致）：\n"
        f"{outline_txt}")
    parts.append(f"学科专属要求：\n{guidance}")
    parts.append(
        "其余通用要求：\n"
        f"1. 用 Markdown 输出，从{h}级标题 `{h}` 开始（不写一级标题，不用代码块包裹整篇）。\n"
        "2. 正文按知识点分节，逻辑连贯、有信息密度，避免复述口语。\n"
        "3. 若截图/字幕里是流程图、架构图、公式、代码或操作步骤，要在正文用文字把逻辑讲清，让人不看图也懂。\n"
        "4. 不出现「本视频」「UP主」「这个视频」之类口语，直接讲内容本身。\n"
        "5. 全文简体中文。")
    parts.append(
        f"★ 字数控制：本笔记目标约 {target_chars} 字（允许 ±15% 浮动）。"
        "信息密度优先——既不要注水凑字数，也不要过简漏掉关键论证。")
    return head + "\n".join(parts) + "\n"


def build_frames_desc(frames):
    lines = []
    for f in frames:
        parts = [f"- 文件名: {f['file']} | 时间点: {f['timestamp']}"]
        if f["theme"]:
            parts.append(f"  主题: {f['theme']}")
        if f["keywords"]:
            parts.append(f"  关键词: {', '.join(map(str, f['keywords']))}")
        if f["content"]:
            parts.append(f"  图中文字: {f['content'][:900]}")
        if f.get("concepts"):
            cs = "; ".join(str(c) for c in f["concepts"][:6])
            parts.append(f"  图中概念: {cs[:700]}")
        if f.get("formulas"):
            parts.append(f"  图中公式: {'; '.join(str(x) for x in f['formulas'][:6])}")
        if f.get("reasoning") and f["reasoning"].lower() not in ("none", "无"):
            parts.append(f"  图中逻辑链: {f['reasoning'][:500]}")
        if f.get("tables"):
            try:
                for t in f["tables"][:2]:
                    cap = t.get("caption") or "表格"
                    hd = ", ".join(map(str, t.get("headers", [])))
                    parts.append(f"  图中表格({cap}): 列[{hd}] 共{len(t.get('rows', []))}行")
            except Exception:
                pass
        lines.append("\n".join(parts))
    return "\n".join(lines)


def build_overview_prompt(title, label, seg_summaries):
    """用各段小结首句合成全局「内容概要」（小上下文、低成本）。"""
    lines = "\n".join(f"{i}. （{ts}–{ts2}）{summary}"
                      for i, (ts, ts2, summary) in enumerate(seg_summaries, 1))
    return (
        "你是笔记总编辑。下面是一支长视频各时间段的小结首句，请据此写一段 "
        "3-5 句的全局「内容概要」，概括整支视频的主题与脉络（写成连贯段落，不要列点）。\n\n"
        f"【视频标题】{title}\n"
        f"【学科】{label}\n\n"
        "各时间段小结：\n" + lines + "\n"
    )


def generate_chunked(title, entries, frames, segs, template, target,
                     api_key, base_url, model, img_prefix):
    """
    长视频切块生成：每段取自身字幕切片+该段帧，按学科模板独立生成一节（## 章节，
    内部 ### 小节），最后用一次轻量调用合成全局「内容概要」置于最前；插图全局统一编号。
    """
    n = len(segs)
    chapters = []
    seg_summaries = []
    total_entries = len(entries) or 1
    for (s0, s1, idx) in segs:
        seg_entries = [(sec, t) for (sec, t) in entries if s0 <= sec < s1]
        seg_sub = "\n".join(f"[{fmt_ts(sec)}] {t}" for sec, t in seg_entries)
        seg_frames = [f for f in frames if s0 <= f["seconds"] < s1]
        weight = len(seg_entries) / total_entries
        seg_target = max(600, int(target * weight))
        # 章节内省略全局概述小节（全局概述放最前），小节用 ###
        chap_template = dict(template)
        outline = chap_template.get("outline", [])
        if len(outline) > 1:
            chap_template["outline"] = outline[1:]
        prompt = build_prompt(
            f"{title}（第{idx}/{n}段，{fmt_ts(s0)}–{fmt_ts(s1)}）",
            build_frames_desc(seg_frames) if seg_frames else "",
            seg_sub or "（本段无字幕，请仅依据截图信息撰写）",
            chap_template, seg_target, has_frames=bool(seg_frames), sub_level=3)
        print(f"[md] 生成第 {idx}/{n} 段（{fmt_ts(s0)}–{fmt_ts(s1)}，"
              f"{len(seg_entries)} 条字幕，{len(seg_frames)} 帧）...")
        body_i = strip_code_fence(call_llm(prompt, api_key, base_url, model))
        # 章节内小节统一升为 ###（章节本身用 ##），防止模型误用 ## 破坏层级
        body_i = re.sub(r"(?m)^(#{1,2})\s+",
                        lambda m: "#" * max(3, len(m.group(1))) + " ", body_i)
        chapters.append(f"## 第{idx}段（{fmt_ts(s0)}–{fmt_ts(s1)}）\n\n" + body_i)
        first = re.sub(r"[#>\*\s]+", " ", body_i).strip()[:120]
        seg_summaries.append((fmt_ts(s0), fmt_ts(s1), first))

    # 全局「内容概要」：一次轻量调用（输入仅为各段首句，上下文很小）
    overview = ""
    try:
        ov_prompt = build_overview_prompt(title, template.get("label", "通用"), seg_summaries)
        overview = strip_code_fence(call_llm(ov_prompt, api_key, base_url, model))
    except Exception as e:
        print(f"[warn] 全局概述生成失败，跳过：{e}")
        overview = "（概述生成失败）"

    full = "## 内容概要\n\n" + overview + "\n\n" + "\n\n".join(chapters)
    if frames:  # 全局统一插图编号
        full = inject_frames(full, frames, img_prefix)
    return full


def call_llm(prompt, api_key, base_url, model, timeout=300):
    if OpenAI is None:
        raise RuntimeError("缺少依赖：pip install openai")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def strip_code_fence(text):
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t)
    return t.strip()


# ---------------------------------------------------------------- 占位符替换
# 图号占位符：渲染时先写它，全文组装完毕后再按出现顺序替换成 1、2、3…
NO = "\x00NO\x00"

# 弱模型几乎不会严格照抄 {{FRAME:x}}，实测出现过这些变体：
#   {{FRAME:frame_0001.jpg}}   预期写法
#   【FRAME:frame_0001.jpg】   中文书名号
#   [FRAME:frame_0001.jpg]     半角方括号
#   （FRAME:frame_0001.jpg）   全角括号
#   （{{FRAME:frame_0001.jpg}}） 全角括号包着双花括号
#   ({{FRAME:frame_0001.jpg}})  半角括号包着双花括号
# 下面用宽松匹配兜住所有括号形式，只精准捕获文件名（落在 group(1)），
# 否则占位符会以纯文本形式残留在正文里。
FRAME_RE = re.compile(
    r"(?:【|\[|（|\(|\{)*\s*FRAME[：:]\s*"
    r"([A-Za-z0-9_][A-Za-z0-9_\-]*\.[A-Za-z0-9]+)"
    r"\s*(?:】|\]|）|\)|\})*"
)


def renumber(text):
    """按图片在最终文档中的实际出现顺序统一编号。"""
    n = [0]

    def bump(m):
        # 一张图会产生两处编号（图片 alt 与下方说明行），成对递增
        n[0] += 1
        return str((n[0] + 1) // 2)

    return re.sub(re.escape(NO), bump, text)


def inject_frames(body, frames, img_prefix):
    """把 {{FRAME:xxx.jpg}} 替换成 Markdown 图片 + 时间戳跳转链接。"""
    used = set()

    def render(f, no=None):
        rel = f"{img_prefix}/{f['file']}" if img_prefix else f["file"]
        cap = f["theme"] or "截图"
        # 编号先占位，等全文组装完再按实际出现顺序统一编号，
        # 否则"兜底补入"的图会带着靠后的编号插在前面，出现图 3 后面跟着图 9。
        # 前后各留空行，保证图片独占一段（模型常把占位符黏在段落末尾）。
        return (f"\n\n![图 {NO} {cap}]({rel})\n\n"
                f"<div align=\"center\">图 {NO} {cap} — "
                f"<a href=\"{f['url']}\" target=\"_blank\" rel=\"noopener noreferrer\">▶ {f['timestamp']}</a></div>\n\n")

    order = {f["file"]: f for f in frames}
    counter = [0]

    def repl(m):
        fname = m.group(1).strip()
        f = order.get(fname)
        if not f or fname in used:
            return ""
        used.add(fname)
        counter[0] += 1
        return render(f)

    # 小模型几乎不会严格照抄 {{FRAME:x}}，实测出现过 【FRAME:x】、[FRAME:x]、
    # （{{FRAME:x}}）等各种变体。这里用宽松匹配兜住所有括号形式，
    # 否则占位符会以纯文本形式残留在正文里。
    body = FRAME_RE.sub(repl, body)

    missing = [f for f in frames if f["file"] not in used]
    if not missing:
        return renumber(tidy(body))

    # 兜底：小模型经常无视占位符指令，导致整篇图文脱节。
    # 这里按截图时间戳在视频中的相对位置，把漏掉的图分配到正文对应小节末尾，
    # 而不是一股脑堆在文末——堆在文末会让"图文笔记"退化成"文字+图片附录"。
    placed = distribute_by_time(body, missing, render, counter)
    if placed is not None:
        return renumber(tidy(placed))

    body += "\n\n## 补充截图\n\n"
    for f in missing:
        body += render(f) + "\n"
    return renumber(tidy(body))


def tidy(text):
    """收拾插图后遗留的空括号与多余空行。"""
    text = re.sub(r"[（(]\s*[）)]", "", text)      # 空括号
    text = re.sub(r"\n{4,}", "\n\n\n", text)       # 过多空行
    return text


# 概要/总结类小节不适合插图，配图应落在讲具体内容的小节里
_SKIP_SECTION = re.compile(r"(概要|简介|导读|要点回顾|总结|小结|参考)")


def distribute_by_time(body, missing, render, counter):
    """
    按时间戳把截图分散到正文小节。成功返回新正文，无法分配时返回 None。
    """
    # 按 ## 标题切块：blocks[0] 是标题前的引言部分
    parts = re.split(r"(?m)^(##\s+.*)$", body)
    if len(parts) < 3:
        return None

    blocks = [{"head": None, "text": parts[0]}]
    for i in range(1, len(parts), 2):
        blocks.append({"head": parts[i], "text": parts[i + 1] if i + 1 < len(parts) else ""})

    # 可插图的小节下标
    slots = [i for i, b in enumerate(blocks)
             if b["head"] and not _SKIP_SECTION.search(b["head"])]
    if not slots:
        return None

    span = max((f.get("seconds") or 0) for f in missing) or 1
    buckets = {i: [] for i in slots}
    for f in missing:
        ratio = (f.get("seconds") or 0) / span
        idx = min(int(ratio * len(slots)), len(slots) - 1)
        buckets[slots[idx]].append(f)

    for i in slots:
        for f in buckets[i]:
            counter[0] += 1
            blocks[i]["text"] = blocks[i]["text"].rstrip() + "\n\n" + render(f, counter[0]) + "\n"

    out = blocks[0]["text"]
    for b in blocks[1:]:
        out += b["head"] + "\n" + b["text"]
    print(f"[md] 模型未插入占位符，已按时间戳把 {len(missing)} 张图自动分配到 {len(slots)} 个小节")
    return out


# ---------------------------------------------------------------- 主流程
def _load_dotenv():
    """独立运行时加载项目根目录 .env（流水线里由 run_pipeline 代劳，这里自愈）。"""
    f = Path(__file__).resolve().parent / ".env"
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


def main():
    _load_dotenv()
    ap = argparse.ArgumentParser(description="生成 Markdown 图文笔记")
    ap.add_argument("--bvid", required=True)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--title", default="")
    ap.add_argument("--final-dir", required=True)
    ap.add_argument("--origin-map", default=None)
    ap.add_argument("--extract-json", default=None)
    ap.add_argument("--scores-json", default=None)
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--interval", type=int, default=30,
                    help="fixed 模式抽帧间隔，用于无时间戳文件名的时间推算")
    ap.add_argument("--img-prefix", default="images",
                    help="Markdown 中图片的相对目录前缀")
    ap.add_argument("--output", required=True)
    ap.add_argument("--subject", default=None,
                    help="学科桶(tech/humanities/social_philosophy/general)，缺省自动分类")
    ap.add_argument("--desc", default="", help="视频简介，用于学科自动分类")
    ap.add_argument("--duration", type=float, default=0, help="视频时长(秒)，用于字数预算")
    ap.add_argument("--segment-minutes", type=int, default=25,
                    help="长视频切块生成：每段约多少分钟（<=1 关闭切块）")
    ap.add_argument("--max-segments", type=int, default=12,
                    help="长视频切块最大段数")
    ap.add_argument("--comment-enabled", type=int, default=0,
                    help="是否启用评论(1/0)，用于字数预算")
    ap.add_argument("--stat-view", type=float, default=0)
    ap.add_argument("--stat-like", type=float, default=0)
    ap.add_argument("--stat-favorite", type=float, default=0)
    ap.add_argument("--api-key", default=os.getenv("TEXT_API_KEY") or os.getenv("VISION_API_KEY", ""))
    ap.add_argument("--base-url", default=os.getenv("TEXT_BASE_URL")
                    or os.getenv("VISION_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"))
    ap.add_argument("--model", default=os.getenv("TEXT_MODEL", "glm-4-flash"))
    args = ap.parse_args()

    frames = load_frames(args.final_dir, args.origin_map, args.extract_json,
                         args.scores_json, args.interval, args.bvid, args.page)
    print(f"[md] 载入 {len(frames)} 帧")

    subtitle = load_subtitle(args.subtitle)
    print(f"[md] 字幕 {len(subtitle)} 字")

    title = args.title or args.bvid
    subject = args.subject or classify_subject(
        title, args.desc, subtitle[:800], args.api_key, args.base_url, args.model)
    template = SUBJECT_TEMPLATES.get(subject) or SUBJECT_TEMPLATES.get("general")
    if not SUBJECT_TEMPLATES:  # note_subject 未导入时的降级模板
        template = {"role": "你是一名擅长做学习笔记的助手。",
                    "label": "通用",
                    "outline": ["内容概要", "核心内容", "核心要点回顾"],
                    "guidance": "用通俗语言讲清机制。"}
    target = compute_note_budget(
        duration=args.duration, subtitle_chars=len(subtitle),
        evidence_blocks=len(frames),
        comment_count=(200 if args.comment_enabled else 0),
        stats={"view": args.stat_view, "like": args.stat_like,
               "favorite": args.stat_favorite})
    print(f"[md] 学科：{subject}（{template.get('label')}）  目标字数：{target}")

    if not args.api_key:
        print("[error] 缺少 API Key（设置 TEXT_API_KEY 或 VISION_API_KEY）", file=sys.stderr)
        sys.exit(1)

    # 长视频切块：解析字幕时间戳，分段生成，避免一次性塞爆上下文
    entries = parse_subtitle_entries(args.subtitle)
    segs = (split_segments(entries, args.duration, args.segment_minutes, args.max_segments)
            if (args.segment_minutes or 0) > 1 else [])
    if len(segs) > 1:
        print(f"[md] 长视频切块模式：{len(segs)} 段（每段约 {args.segment_minutes} 分钟）")
        body = generate_chunked(title, entries, frames, segs, template, target,
                                args.api_key, args.base_url, args.model, args.img_prefix)
    else:
        prompt = build_prompt(
            title,
            build_frames_desc(frames) if frames else "",
            subtitle or "（无字幕，请仅依据截图信息撰写）",
            template, target, has_frames=bool(frames))
        print(f"[md] 调用 {args.model} 生成正文 ...")
        body = strip_code_fence(call_llm(prompt, args.api_key, args.base_url, args.model))
        if frames:
            body = inject_frames(body, frames, args.img_prefix)

    header = (f"# {title}\n\n"
              f"> 来源：[{args.bvid}](https://www.bilibili.com/video/{args.bvid}/?p={args.page})"
              f" · P{args.page} · 共 {len(frames)} 张图解\n\n---\n\n")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + body + "\n", encoding="utf-8")
    print(f"[done] 笔记已生成: {out}")

    # 同步导出帧清单，供后续 PDF/入库使用
    meta = out.with_suffix(".frames.json")
    json.dump(frames, open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[done] 帧清单: {meta}")


if __name__ == "__main__":
    main()
