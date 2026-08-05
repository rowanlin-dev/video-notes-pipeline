#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站评论区抓取（WBI 签名，无需登录 cookie）
==========================================
移植自 Rimagination/bili-note 的公开接口思路（MIT），重写为本项目独立模块。

- 通过 /x/web-interface/nav 取 wbi img_key/sub_key，做 mixin key + md5 签名；
- 调 /x/v2/reply/wbi/main 拉评论（热门优先，分页游标），无需 SESSDATA。
- 三种输出模式（对应 run_pipeline 的 --comments）：
    list    : 按点赞排序的评论列表（默认最多 50 条），供「查看评论列表」
    top     : 高赞评论（默认 30 条），供「看高赞」
    summary : LLM 垃圾过滤 + 精选 10~20 条有用评论（纠错/补充/实战/争议）
              + 评论区情绪 / 趋势 / 关键词总结
  默认 off（不抓取）。

既可作为脚本独立运行，也可被 run_pipeline.py import（fetch_and_format）。
"""
import os
import re
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
import hashlib
from pathlib import Path

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
REPLY_URL = "https://api.bilibili.com/x/v2/reply/wbi/main"
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}


# ---------------------------------------------------------------- 网络
def _http_get_json(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers=_UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_aid(bvid: str) -> tuple:
    """返回 (aid, title)。"""
    try:
        d = _http_get_json(VIEW_URL, {"bvid": bvid}).get("data") or {}
        return d.get("aid"), d.get("title", "")
    except Exception as e:
        print(f"[warn] 获取 aid 失败：{e}", file=sys.stderr)
        return None, ""


# ---------------------------------------------------------------- WBI 签名
def _get_wbi_keys():
    data = _http_get_json(NAV_URL, {}).get("data") or {}
    wbi = data.get("wbi_img") or {}
    img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    return img, sub


def _mixin_key(img: str, sub: str) -> str:
    raw = img + sub
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _sign(params: dict) -> dict:
    img, sub = _get_wbi_keys()
    mk = _mixin_key(img, sub)
    params = dict(sorted(params.items()))
    params["wts"] = int(time.time())
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    params["w_rid"] = hashlib.md5((query + mk).encode()).hexdigest()
    return params


# ---------------------------------------------------------------- 抓取
_SPAM_PAT = re.compile(
    r"(https?://|b23\.tv|t\.cn|www\.)"                              # 外链
    r"|加微信|微信[：:\s]|扫码|二维码|公众号|免费领取|领取资料|私聊我|引流"
    r"|小助理|点击链接|限时|秒杀|报名优惠|课程咨询|代购|加我好友",
    re.I,
)


def _is_spam(msg: str) -> bool:
    m = msg or ""
    if _SPAM_PAT.search(m):
        return True
    if len(re.sub(r"\W", "", m)) < 4:   # 纯表情 / 超短灌水
        return True
    return False


def fetch_comments(aid: int, max_comments: int = 200) -> list:
    """分页拉取评论，返回按点赞降序的评论列表。每条含 uname/message/like/ctime/is_top/sub。"""
    collected = []
    seen = set()
    nxt = 0
    pages = 0
    while len(collected) < max_comments and pages < 25:
        params = _sign({
            "type": 1, "oid": aid, "mode": 3,
            "ps": 20, "next": nxt, "web_location": 1315875,
        })
        try:
            d = _http_get_json(REPLY_URL, params).get("data") or {}
        except Exception as e:
            print(f"[warn] 评论分页失败：{e}", file=sys.stderr)
            break
        for r in (d.get("top_replies") or []):
            r["_is_top"] = True
        for r in (d.get("replies") or []):
            r.setdefault("_is_top", False)
        batch = (d.get("top_replies") or []) + (d.get("replies") or [])
        for r in batch:
            rpid = r.get("rpid")
            if rpid in seen:
                continue
            seen.add(rpid)
            msg = (r.get("content") or {}).get("message", "") or ""
            if not msg.strip() or _is_spam(msg):
                continue
            subs = []
            for s in (r.get("replies") or [])[:3]:
                sm = (s.get("content") or {}).get("message", "") or ""
                su = (s.get("member") or {}).get("uname", "")
                if sm.strip():
                    subs.append({"uname": su, "text": sm, "like": s.get("like", 0)})
            collected.append({
                "rpid": rpid,
                "uname": (r.get("member") or {}).get("uname", ""),
                "message": msg,
                "like": r.get("like", 0),
                "ctime": r.get("ctime", 0),
                "is_top": r.get("_is_top", False),
                "sub": subs,
            })
        cursor = d.get("cursor") or {}
        if cursor.get("is_end") or not cursor.get("next"):
            break
        nxt = cursor.get("next")
        pages += 1
        time.sleep(0.3)
    collected.sort(key=lambda x: x["like"], reverse=True)
    return collected[:max_comments]


# ---------------------------------------------------------------- 格式化
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _block_list(comments: list, limit: int = 50) -> str:
    lines = ["## 💬 评论区（按点赞排序）", ""]
    shown = comments[:limit]
    for c in shown:
        lines.append(f"- **{c['uname']}**（赞 {c['like']}）：{_clean(c['message'])}")
        for s in c["sub"]:
            lines.append(f"    - ↳ {s['uname']}：{_clean(s['text'])}")
    if len(comments) > limit:
        lines.append("")
        lines.append(f"> 仅显示点赞最高的 {limit} / 共 {len(comments)} 条。")
    return "\n".join(lines) + "\n"


def _block_top(comments: list, n: int = 30) -> str:
    lines = [f"## 💬 高赞评论 Top {min(n, len(comments))}", ""]
    for c in comments[:n]:
        lines.append(f"- **{c['uname']}**（赞 {c['like']}）：{_clean(c['message'])}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- LLM 总结（summary）
# 各模型输出 token 硬上限（未知模型按 DEFAULT_CAP 保守处理）。
# 上限 ≤1024 的模型用紧凑 schema（只回编号+标签，原文代码回填）；
# 上限 >1024 的模型用富文本 schema（可附一句点评 + 综合论述），发挥富余能力。
MODEL_TOKEN_CAP = {
    "glm-4v-flash": 1024, "glm-4-flash": 1024, "glm-4v": 1024,
    "gpt-4o-mini": 16384, "gpt-4o": 16384, "gpt-4": 4096, "gpt-3.5-turbo": 4096,
    "deepseek-chat": 8192, "deepseek-reasoner": 8192,
    "claude-3-5-sonnet": 8192, "claude-3-opus": 4096, "claude-3-haiku": 4096,
    "qwen-max": 8192, "qwen-plus": 8192, "qwen-turbo": 8192,
    "glm-4-plus": 4096, "glm-4": 4096, "glm-4-air": 4096, "glm-4-airx": 4096,
    "moonshot-v1-8k": 8192, "moonshot-v1-32k": 8192,
}
DEFAULT_CAP_UNKNOWN = 2048  # 未知模型假设现代能力，允许富文本；若实际更弱会安全回退


def _resolve_schema(model: str, requested: int = None):
    """返回 (schema_mode, effective_max_tokens)。"""
    cap = MODEL_TOKEN_CAP.get((model or "").strip().lower(), DEFAULT_CAP_UNKNOWN)
    if requested:
        cap = min(cap, int(requested))
    return ("rich" if cap > 1024 else "compact"), cap


def _llm_summary(comments: list, title: str, api_key: str, base_url: str, model: str,
                 max_in: int = 40) -> dict:
    """让模型回「编号 + 短标签 + 简短总结」。

    自适应：弱模型（token 上限≤1024）只回编号+标签，原文在代码侧按编号回填；
    强模型额外允许每条附一句点评(note)与顶层综合论述(synthesis)，输出更优。
    """
    try:
        import requests
    except ImportError:
        print("[warn] 未安装 requests，summary 回退为 top 模式", file=sys.stderr)
        return {}
    schema_mode, eff_cap = _resolve_schema(model)
    if schema_mode == "rich":
        schema_hint = (
            "4) 每条精选可在 30 字内补充一句 note（转述/点评，可选）；\n"
            "5) 在顶层补充 synthesis（≤120 字综合论述，可选）。\n"
            "【重要】不要大段抄写评论原文，只需引用编号。严格只返回如下 JSON 对象：\n"
            '{"sentiment":"...","trend":"...","keywords":["..."],'
            '"picks":[{"id":编号,"type":"纠错|补充|实战经验|争议观点","note":"可选一句点评"}],'
            '"synthesis":"可选综合论述"}'
        )
    else:
        schema_hint = (
            "3) 用一句总结整体情绪倾向、一句总结主要讨论趋势、给出 3~8 个高频关键词。\n"
            "【重要】不要抄写评论原文，只需引用编号。严格只返回如下 JSON 对象：\n"
            '{"sentiment":"...","trend":"...","keywords":["..."],'
            '"picks":[{"id":编号,"type":"纠错|补充|实战经验|争议观点"}]}'
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "你是B站评论区分析助手。给定视频标题与按点赞排序、带编号的评论列表，请：\n"
                "1) 剔除广告/引流/纯表情/灌水等垃圾；\n"
                "2) 精选最多 20 条最有价值的评论，引用其编号，并标注类型：\n"
                "   纠错=指出视频或他人说法的错误；补充=补充信息或更优做法；\n"
                "   实战经验=亲身经历或可操作建议；争议观点=存在分歧的看法。\n"
                "   请按真实类别标注，不要全部归为同一类；\n"
                + schema_hint
            )},
            {"role": "user", "content": _build_summary_text(comments, title, max_in)},
        ],
        "temperature": 0.3,
        "max_tokens": eff_cap,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            r = requests.post(f"{base_url.rstrip('/')}/chat/completions",
                              headers=headers, json=payload, timeout=120)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            data = _extract_json(content)
            if isinstance(data, list):  # 极少数情况返回数组，视作 picks
                data = {"picks": data}
            return data or {}
        except Exception as e:
            print(f"[warn] 评论总结 LLM 调用失败（{attempt+1}/3）：{e}", file=sys.stderr)
            time.sleep(2)
    return {}


def _extract_json(text: str):
    """容错解析：优先直接解析，失败则抽取第一个 {...} 或 [...] 片段。"""
    text = (text or "").strip()
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
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _build_summary_text(comments: list, title: str, max_in: int = 40) -> str:
    head = (f"视频标题：《{title}》\n"
            f"以下是按点赞排序、已编号的评论（共 {min(max_in, len(comments))} 条）：\n")
    rows = []
    for i, c in enumerate(comments[:max_in], 1):
        rows.append(f"{i}. [赞{c['like']}] {c['uname']}: {_clean(c['message'])}")
    return head + "\n".join(rows)


def _block_summary(summary, comments: list) -> str:
    if not isinstance(summary, dict):
        # 兼容旧 schema（直接给了 essence 列表）
        if isinstance(summary, list):
            summary = {"essence": summary}
        else:
            return _block_top(comments)
    # 旧 schema：模型直接回了 essense 列表
    if summary.get("essence") and not summary.get("picks"):
        picks = [{"id": None, "type": (e.get("type", "") if isinstance(e, dict) else ""),
                  "_text": (e.get("text", "") if isinstance(e, dict) else str(e))}
                 for e in summary["essence"][:20]]
    else:
        picks = summary.get("picks") or []
    if not picks:
        return _block_top(comments)

    lines = ["## 💬 评论区精选", ""]
    if summary.get("sentiment"):
        lines.append(f"**整体情绪**：{summary['sentiment']}")
    if summary.get("trend"):
        lines.append(f"**讨论趋势**：{summary['trend']}")
    kw = summary.get("keywords") or []
    if kw:
        lines.append(f"**高频关键词**：{', '.join(str(k) for k in kw)}")
    synth = summary.get("synthesis")
    if synth:
        lines.append("")
        lines.append(f"> 📌 {_clean(synth)}")
    lines.append("")
    lines.append("**精选评论**（标注类型）：")
    for p in picks[:20]:
        t = p.get("type", "") if isinstance(p, dict) else ""
        # 旧 schema 自带文本
        if p.get("_text"):
            lines.append(f"- 【{t}】{_clean(p['_text'])}")
            continue
        idx = p.get("id")
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        c = comments[idx - 1] if 1 <= idx <= len(comments) else None
        if not c:
            continue
        note = p.get("note")
        if note:
            # 富文本模式：模型点评置顶，原文作引用备查
            lines.append(f"- 【{t}】{c['uname']}（赞 {c['like']}）：{_clean(note)}")
            lines.append(f"  > 原文：{_clean(c['message'])}")
        else:
            lines.append(f"- 【{t}】{c['uname']}（赞 {c['like']}）：{_clean(c['message'])}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 对外接口
def fetch_and_format(bvid: str, mode: str = "summary",
                     max_comments: int = 200, top_n: int = 30,
                     list_limit: int = 50) -> str:
    """返回可直接追加进笔记 Markdown 的评论区块字符串（mode=off 返回空串）。"""
    if mode in (None, "off"):
        return ""
    aid, title = get_aid(bvid)
    if not aid:
        print("[warn] 无法获取 aid，跳过评论抓取", file=sys.stderr)
        return ""
    comments = fetch_comments(aid, max_comments)
    if not comments:
        print("[warn] 未抓到评论", file=sys.stderr)
        return ""
    print(f"[comments] 抓到 {len(comments)} 条评论，模式={mode}")
    if mode == "list":
        return _block_list(comments, list_limit)
    if mode == "top":
        return _block_top(comments, top_n)
    # summary
    api_key = os.getenv("TEXT_API_KEY") or os.getenv("VISION_API_KEY", "")
    base_url = os.getenv("TEXT_BASE_URL") or os.getenv("VISION_BASE_URL", os.getenv("SOPHNET_BASE_URL", "https://api.openai.com/v1"))
    model = os.getenv("TEXT_MODEL") or os.getenv("VISION_MODEL", os.getenv("SOPHNET_MODEL", "gpt-4o"))
    summary = {}
    if api_key:
        summary = _llm_summary(comments, title, api_key, base_url, model)
    else:
        print("[warn] 未配置 VISION_API_KEY，summary 回退为 top 模式", file=sys.stderr)
    return _block_summary(summary, comments)


# ---------------------------------------------------------------- CLI
def _load_env():
    """读取项目根目录 .env 到进程环境（不覆盖已有变量）。"""
    f = Path(__file__).resolve().parent.parent / ".env"
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
    _load_env()
    ap = argparse.ArgumentParser(description="B站评论区抓取（WBI，无需登录）")
    ap.add_argument("bvid")
    ap.add_argument("--mode", choices=["list", "top", "summary"], default="summary")
    ap.add_argument("--max", type=int, default=200, help="最多抓取评论条数")
    ap.add_argument("--top-n", type=int, default=30, help="top 模式展示条数")
    ap.add_argument("--list-limit", type=int, default=50, help="list 模式展示条数")
    ap.add_argument("--out", default=None, help="输出目录（默认当前目录）")
    args = ap.parse_args()

    block = fetch_and_format(args.bvid, args.mode, args.max, args.top_n, args.list_limit)
    if not block:
        print("无评论内容输出", file=sys.stderr)
        sys.exit(1)
    out_dir = Path(args.out) if args.out else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{args.bvid}_comments.md"
    md_path.write_text(block, encoding="utf-8")
    print(f"\n[ok] 评论区块已写入：{md_path}")


if __name__ == "__main__":
    main()
