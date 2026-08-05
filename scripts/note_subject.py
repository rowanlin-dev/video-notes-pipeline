#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学科自适应笔记：学科桶模板 + 自动分类 + 字数预算
================================================
- SUBJECT_TEMPLATES：不同学科对应不同的笔记结构（section 大纲）与侧重点。
- classify_subject()：用文本模型把视频归到某个学科桶（tech/humanities/
  social_philosophy/general），失败回退 general。
- compute_note_budget()：移植自 Rimagination 的 write_note_budget（MIT），
  按视频时长 / 字幕量 / 证据帧数 / 评论数 / 播放质量动态控制笔记字数，
  避免信息量小的短视频写出注水长文，或信息量大的长视频被截短。

碎片式学习分支（用户暂缓）：当前未单独建模，统一走 general 桶。
"""
import os
import re
import json

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ---------------------------------------------------------------- 学科模板
SUBJECT_TEMPLATES = {
    "tech": {
        "label": "编程/技术/IT",
        "role": "你是一名擅长把技术课程、编程教学类视频整理成结构化学习笔记的助手。",
        "outline": ["内容概要", "背景与问题", "核心概念/原理",
                     "关键代码/命令/API", "最佳实践与避坑", "核心要点回顾"],
        "guidance": (
            "保留关键代码块、命令与 API 签名；清晰区分「是什么 / 为什么 / 怎么做」；"
            "指出常见误区与边界情况；把示例代码的意图讲明白，而不只是贴代码。"
        ),
    },
    "humanities": {
        "label": "人文/历史/文学/人物访谈",
        "role": "你是一名擅长把人物访谈、人文对谈类内容整理成有结构、有温度的笔记的助手。",
        "outline": ["内容概要", "人物与背景", "核心观点与金句",
                    "思辨脉络", "个人启示/可践行之处", "延伸思考"],
        "guidance": (
            "保留关键金句原文并标注说话人（如「罗翔：……」）；呈现对话中的观点交锋与转折；"
            "区分「事实陈述」与「主观观点」；避免剧透式复述，重在思想脉络。"
        ),
    },
    "social_philosophy": {
        "label": "社会议题/哲学/心理/思辨",
        "role": "你是一名擅长把社会议题、哲学思辨、心理学类内容整理成结构化笔记的助手。",
        "outline": ["内容概要", "议题/问题", "多方观点", "论证与论据",
                    "争议与张力", "我的启发/可行动点", "延伸思考"],
        "guidance": (
            "客观呈现不同立场，不预设立场；为每种观点标注支撑论据；"
            "点明论证中的薄弱环节或隐含前提；区分「描述性结论」与「规范性主张」。"
        ),
    },
    "general": {
        "label": "通用/科普/通识",
        "role": "你是一名擅长把知识科普、通识类视频整理成结构化笔记的助手。",
        "outline": ["内容概要", "是什么", "为什么重要", "关键机制/怎么做",
                    "核心要点回顾", "延伸阅读"],
        "guidance": (
            "用通俗语言讲清机制；善用类比帮助理解；突出可迁移的结论与行动建议；"
            "若涉及数据或研究，注明来源与不确定性。"
        ),
    },
}

DEFAULT_BUCKET = "general"
_VALID = set(SUBJECT_TEMPLATES.keys())


# ---------------------------------------------------------------- 自动分类
def classify_subject(title, desc="", subtitle_excerpt="",
                     api_key="", base_url="", model="", timeout=60) -> str:
    """把视频归到某个学科桶；任何失败都回退 general。"""
    if not api_key or OpenAI is None:
        return DEFAULT_BUCKET
    sys_p = (
        "你是内容分类器。把下面的视频归到最贴切的一个学科桶："
        "tech | humanities | social_philosophy | general。\n"
        "tech=编程/技术/IT/软件；humanities=人文/历史/文学/人物访谈/传记；"
        "social_philosophy=社会议题/哲学/心理/思辨/观点对谈；"
        "general=通用科普/通识/其他或难以归类。\n"
        "只返回 JSON，形如 {\"subject\":\"桶名\",\"reason\":\"一句话理由\"}，不要其他内容。"
    )
    user_p = (f"标题：《{title}》\n简介：{(desc or '')[:300]}\n"
              f"字幕片段：{(subtitle_excerpt or '')[:800]}")
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_p},
                      {"role": "user", "content": user_p}],
            temperature=0,
        )
        data = _extract_json(resp.choices[0].message.content or "")
        if isinstance(data, dict):
            s = str(data.get("subject") or "").strip().lower()
            return s if s in _VALID else DEFAULT_BUCKET
    except Exception as e:
        print(f"[warn] 学科分类失败，回退 general：{e}", file=__import__("sys").stderr)
    return DEFAULT_BUCKET


def _extract_json(text):
    """容错解析 JSON（兼容模型偶尔包了 ```json 或夹杂文字）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- 字数预算
def compute_note_budget(duration=0, subtitle_chars=0, evidence_blocks=0,
                        comment_count=0, stats=None) -> int:
    """按信息密度动态控制目标字数（移植自 Rimagination write_note_budget，适配）。

    base = 600 + 时长*35 + 字幕字数*0.025 + 证据帧数*8 + min(评论数,300)*3
    再 clamp 到 [1200, 45000]，最后乘质量乘数（播放/点赞/收藏占比，1.0~1.5）。
    """
    dur = float(duration or 0)
    sub = int(subtitle_chars or 0)
    ev = int(evidence_blocks or 0)
    cm = min(int(comment_count or 0), 300)

    base = 600 + dur * 35 + sub * 0.025 + ev * 8 + cm * 3
    base = max(1200.0, min(base, 45000.0))

    mult = 1.0
    stats = stats or {}
    view = float(stats.get("view") or 0)
    like = float(stats.get("like") or 0)
    fav = float(stats.get("favorite") or 0)
    if view > 0:
        mult = 1.0 + 0.25 * (like / view) + 0.15 * (fav / view)
        mult = max(1.0, min(mult, 1.5))

    return int(round(base * mult))


if __name__ == "__main__":
    # 简单自测：分类 + 预算
    import sys
    print("buckets:", list(SUBJECT_TEMPLATES.keys()))
    print("budget(5400s,20000字,10帧,0评论):",
          compute_note_budget(5400, 20000, 10, 0, {"view": 1e6, "like": 5e4, "favorite": 1e4}))
    print("classify('罗翔谈法治'):",
          classify_subject("罗翔：在命运的剧本揭晓前", "法学教授聊人生", "",
                           os.getenv("TEXT_API_KEY"), os.getenv("TEXT_BASE_URL"),
                           os.getenv("TEXT_MODEL")))
