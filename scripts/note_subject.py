#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学科自适应笔记：学科桶模板 + 自动分类 + 字数预算
================================================
- SUBJECT_TEMPLATES：不同学科对应不同的笔记结构（section 大纲）与侧重点。
- classify_profile()：把视频归到学科桶 + 判断受众水平（无需 openai SDK，
  有兼容 OpenAI 的 HTTP 端点即可）；模型不可用时退回本地关键词启发式，绝不静默丢成 general。
- classify_subject()：只取学科桶的兼容封装。
- compute_note_budget()：按「内容信息量 × 受众水平」给出**篇幅区间**（下限/上限），
  不使用时长、帧数、播放量等与内容无关的变量，也不返回写死的单一目标值。

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
SUBJECT_HINTS = {
    "tech": ["编程", "代码", "开发", "前端", "后端", "javascript", "js", "python",
             "java", "api", "框架", "算法", "数据库", "服务器", "浏览器", "软件",
             "架构", "部署", "性能", "调试", "接口", "并发"],
    "humanities": ["历史", "文学", "人物", "访谈", "传记", "诗歌", "小说",
                   "文化", "艺术", "作家", "作品"],
    "social_philosophy": ["社会", "心理", "经济", "伦理", "法律", "政治",
                          "思辨", "争议", "制度", "哲学", "观点"],
}

BEGINNER_HINTS = ["入门", "零基础", "小白", "新手", "科普", "通识", "趣味",
                  "三分钟", "看懂", "详解", "什么是"]
PRO_HINTS = ["源码", "底层", "原理", "架构", "进阶", "性能优化", "实战",
             "深入", "工程化", "面试", "调优", "最佳实践"]

AUDIENCE_LABELS = {
    "professional": "从业者/有强基础（术语可直接用，允许压缩）",
    "informed": "有相关常识的爱好者/学生（解释术语，但不必从零讲）",
    "beginner": "零基础大众（需要类比、铺垫、逐步展开）",
}


def _guess_subject(title, desc, excerpt):
    text = f"{title} {desc} {excerpt}".lower()
    for bucket, words in SUBJECT_HINTS.items():
        if any(w in text for w in words):
            return bucket
    return DEFAULT_BUCKET


def _guess_audience(title, desc, excerpt):
    text = f"{title} {desc} {excerpt}".lower()
    if any(w in text for w in PRO_HINTS):
        return "professional"
    if any(w in text for w in BEGINNER_HINTS):
        return "beginner"
    return "informed"


def _chat(messages, api_key, base_url, model, timeout=60):
    """调用 OpenAI 兼容端点：优先 openai SDK，缺失时直接用 requests/HTTP。

    旧实现只认 openai SDK，导致未装 openai 的机器上分类**静默**退化成 general，
    学科模板（tech/humanities/...）永远不生效。
    """
    if OpenAI is not None:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0)
        return resp.choices[0].message.content or ""
    import requests
    url = (base_url or "").rstrip("/") + "/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0},
        timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("choices") or [{}])[0].get("message", {}) or {}).get("content", "") or ""


def classify_profile(title, desc="", subtitle_excerpt="",
                     api_key="", base_url="", model="", timeout=60) -> dict:
    """返回 {"subject": 桶名, "audience": 水平, "reason": 依据}。

    模型不可用 / 无 Key / 调用失败时，用本地关键词启发式兜底并打印提示，
    不再静默返回 general。
    """
    fallback = {
        "subject": _guess_subject(title, desc, subtitle_excerpt),
        "audience": _guess_audience(title, desc, subtitle_excerpt),
        "reason": "本地关键词启发式",
    }
    if not api_key:
        return fallback
    sys_p = (
        "你是内容分析器。阅读标题、简介与字幕片段，输出两件事：\n"
        "1) subject：最贴切的一个学科桶 tech | humanities | social_philosophy | general；\n"
        "   tech=编程/技术/IT/软件；humanities=人文/历史/文学/人物访谈/传记；"
        "social_philosophy=社会议题/哲学/心理/思辨/观点对谈；general=通用科普/通识/其他。\n"
        "2) audience：内容面向的读者水平 professional | informed | beginner；\n"
        "   professional=假定读者已掌握该领域基础，内容偏源码/原理/进阶/架构/面试，可刻意压缩；\n"
        "   informed=有相关常识的爱好者/学生，或面向开发者的入门与科普讲解，"
        "需解释术语但不必从零讲；\n"
        "   beginner=零基础大众，需要类比、铺垫、逐步展开。\n"
        "只返回 JSON：{\"subject\":\"桶名\",\"audience\":\"水平\",\"reason\":\"一句话理由\"}，不要其他内容。"
    )
    user_p = (f"标题：《{title}》\n简介：{(desc or '')[:300]}\n"
              f"字幕片段：{(subtitle_excerpt or '')[:800]}")
    try:
        text = _chat(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": user_p}],
            api_key, base_url, model, timeout)
        data = _extract_json(text)
        if isinstance(data, dict):
            s = str(data.get("subject") or "").strip().lower()
            a = str(data.get("audience") or "").strip().lower()
            return {
                "subject": s if s in _VALID else fallback["subject"],
                "audience": a if a in AUDIENCE_LABELS else fallback["audience"],
                "reason": str(data.get("reason") or "模型判定"),
            }
    except Exception as e:
        print(f"[warn] 学科/受众分类调用失败，使用本地启发式"
              f"（{fallback['subject']}/{fallback['audience']}）：{e}",
              file=__import__("sys").stderr)
    return fallback


def classify_subject(title, desc="", subtitle_excerpt="",
                     api_key="", base_url="", model="", timeout=60) -> str:
    """兼容旧接口：只返回学科桶。"""
    return classify_profile(title, desc, subtitle_excerpt,
                            api_key, base_url, model, timeout)["subject"]


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
AUDIENCE_MULT = {"professional": 0.80, "informed": 1.00, "beginner": 1.35}
FLOOR_CHARS = 800
CEIL_CHARS = 45000


def compute_note_budget(subtitle_chars=0, audience="informed", subject="general",
                        evidence_chars=0, **ignored) -> tuple:
    """按「内容信息量 × 受众水平」给出篇幅**区间** (下限, 上限)。

    设计原则（与旧公式的本质区别）：
    - 只使用内容变量（字幕字符数 + 图中文字字符数）与受众变量，**不使用**时长、
      帧数、播放量、点赞、评论数等与内容无关或会误导的指标；
    - 返回区间而不是写死的目标值：真实写作是先按主题选大纲、再自然成篇，
      字数不该被当成硬指标；
    - 展开比随信息量增长而收敛：短视频信息密度高、需要展开到 1 倍以上；长视频
      口播重复多，笔记/字幕比会自然收敛到 0.12~0.2；
    - 受众决定系数：从业者可以压缩（0.8），零基础要铺垫与类比（1.35）。

    图中文字按 0.35 权重计入：纯演示/代码实录几乎没有口播，只看字幕会严重低估
    信息量；但截图 OCR 只有精选的 8~12 帧，全量计入又会抬高过多。

    例（informed）：字幕 3,500 字 → 约 3,100–5,000 字；字幕 96,000 字 →
    约 12,200–19,700 字；字幕 200 字 + 图中文字 6,000 字 → 约 2,200–3,600 字。
    上限只是「防注水」提示，不是必须写满的任务。
    """
    sub = max(0, int(subtitle_chars or 0))
    ev = max(0, int(evidence_chars or 0))
    info = max(300.0, sub + 0.35 * ev)
    ratio = 1.4 / (1 + info / 12000)          # 笔记/信息量 的展开比，随素材增长收敛
    mult = AUDIENCE_MULT.get(audience, 1.0)
    lo = info * ratio * 0.82 * mult
    hi = info * ratio * 1.32 * mult
    lo = max(FLOOR_CHARS * mult, min(lo, CEIL_CHARS))
    hi = max(lo + 600 * mult, min(hi, CEIL_CHARS))
    return int(round(lo, -2)), int(round(hi, -2))


if __name__ == "__main__":
    # 简单自测：分类 + 预算区间
    import sys
    print("buckets:", list(SUBJECT_TEMPLATES.keys()))
    for n, aud in [(3496, "informed"), (3496, "beginner"),
                   (96000, "informed"), (96000, "professional")]:
        print(f"budget(sub={n}, {aud}) =", compute_note_budget(n, aud))
    print("profile:",
          classify_profile("罗翔：在命运的剧本揭晓前", "法学教授聊人生", "",
                           os.getenv("TEXT_API_KEY"), os.getenv("TEXT_BASE_URL"),
                           os.getenv("TEXT_MODEL")))
