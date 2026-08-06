#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发视觉分析脚本 - video-notes-pipeline

用途：对 selected/ 目录下的所有帧一次性并发进行 vision 分析，
输出结构化 JSON 供后续选帧和写笔记使用。

使用示例：
    # 第一步：给所有 selected/ 帧打分（用于选出最终帧）
    python score_frames_concurrent.py \\
        --frames "./frames/pXX/selected" \\
        --output "./workspace/vision_scores_pXX.json" \\
        --workers 16

    # 第二步：对最终选定的帧提取图中文字/公式/表格（用于写正文）
    python score_frames_concurrent.py \\
        --frames "./frames/pXX/final" \\
        --output "./workspace/vision_extract_pXX.json" \\
        --mode extract \\
        --workers 16

输出 JSON 格式（--mode score）：
    {
      "frame_0001.jpg": {
        "theme": "Introduction",
        "keywords": ["concept", "diagram"],
        "score": 8,
        "complete": true
      },
      ...
    }

输出 JSON 格式（--mode extract）：
    {
      "frame_0001.jpg": {
        "theme": "Introduction",
        "score": 8,
        "complete": true,
        "text": "All readable text...",
        "formulas": ["E = mc^2"],
        "tables": [...],
        "concepts": ["Concept: explanation with WHY"],
        "reasoning": "Core causal chain or logical explanation shown in the image."
      },
      ...
    }
"""

import os
import re
import sys
import base64
import json
import time
import argparse
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

# 尝试加载 skill 目录下的 .env 文件
try:
    from dotenv import load_dotenv
    skill_dir = Path(__file__).resolve().parent.parent
    dotenv_path = skill_dir / '.env'
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
except ImportError:
    pass

# 默认从 .env 读取 API 配置
DEFAULT_BASE_URL = os.getenv('VISION_BASE_URL', os.getenv('SOPHNET_BASE_URL', "https://api.openai.com/v1"))
DEFAULT_MODEL = os.getenv('VISION_MODEL', os.getenv('SOPHNET_MODEL', "gpt-4o"))
DEFAULT_API_KEY = os.getenv('VISION_API_KEY', os.getenv('SOPHNET_API_KEY', ""))
DEFAULT_WORKERS = 16
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_RETRIES = 3

# 模型有时会把 JSON 键名连同内容一起翻译成中文，导致字段取不到值。
# 这里把常见的中文键名映射回标准英文键名。
_KEY_ALIAS = {
    "主题": "theme", "标题": "theme", "题目": "theme",
    "关键词": "keywords", "关键字": "keywords",
    "分数": "score", "评分": "score", "得分": "score",
    "完整": "complete", "完整性": "complete", "是否完整": "complete",
    "文字": "text", "文本": "text", "内容": "text", "图中文字": "text",
    "公式": "formulas", "表格": "tables",
    "概念": "concepts", "知识点": "concepts",
    "推理": "reasoning", "逻辑": "reasoning", "逻辑链": "reasoning", "因果": "reasoning",
}


def normalize_keys(d):
    """把中文键名归一化成标准英文键名。模型原本就返回的英文键优先，不被翻译键覆盖。"""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    for k, v in d.items():
        std = _KEY_ALIAS.get(str(k).strip())
        if std and std not in out:
            out[std] = v
    return out


# 针对教育/讲课视频的 vision prompts

SCORE_PROMPT = """This is a screenshot from an educational video (likely a lecture or course).
Please answer strictly in the following JSON format, with no extra content:
{
  "theme": "A short title summarizing the frame (5-15 words)",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "type": "diagram",
  "has_educational_visual": true,
  "score": 8,
  "complete": true
}

Field definitions:
- "type": MUST be exactly one of: diagram, slide, code_ui, demo, meme, blackscreen, ad, face, other.
  * diagram: flowchart, architecture diagram, data visualization, graph, chart.
  * slide: dense PPT/keynote slide with educational text/formulas.
  * code_ui: code editor, terminal, IDE, configuration panel, API docs.
  * demo: live UI operation, product interface, browser dev tools, real workflow.
  * meme: internet meme, sticker, reaction image, cartoon/mascot with no educational diagram.
  * blackscreen: mostly black/dark background with only subtitles/captions and no other visual content.
  * ad: advertisement, course promo, "free materials", "免费领取", "完整资料", "面试题", "扫码领取", "加微信", "小助理", QR code, "add WeChat", "follow to get", sales page. Ads often show grids/lists of PDFs, courses, or titles with big promotional text.
  * face: only a talking head/lecturer face with no informative background.
  * other: anything not above.
- "has_educational_visual": true ONLY if the image contains a diagram, code, UI, formula, chart, or
  other visual element that adds value beyond the spoken subtitles. Black screens with only subtitles,
  memes, faces, and ads must be false.
- "score": content completeness from 1-10. Use the FULL range strictly:
  * 9-10: dense diagrams, architecture charts, code walkthroughs, complex formulas, multi-step workflows.
  * 7-8: clear slides with concepts/formulas, useful UI demos, code snippets.
  * 4-6: simple slides or generic UI with some value.
  * 2-3: talking head / lecturer face with no informative background.
  * 1: ads, course promos, free-material pages (e.g. "完整资料 免费领取", lists of PDFs/interview questions), QR codes, memes, reaction images, black screens with ONLY subtitles.
'complete' means the screenshot is fully visible, not cropped or blocked.

IMPORTANT: keep the JSON keys exactly as shown in English ("theme", "keywords", "type", "has_educational_visual", "score", "complete").
Do NOT translate the keys. Only the VALUES of "theme" and "keywords" must be written in Simplified Chinese,
since they are used as figure captions in a Chinese note.

Frames that are memes, black screens with only subtitles, ads/course promos, or pure talking heads
must receive score 1-3 and MUST NOT be selected for the final note.""".strip()

EXTRACT_PROMPT = """This is a screenshot from an educational video (likely a lecture or course).
Please extract all readable educational content from this image. Pay special attention to causal relationships, explanations, and logical chains shown or implied in the image.
Answer strictly in the following JSON format, with no extra content:
{
  "theme": "A short title summarizing the frame (5-15 words)",
  "score": 8,
  "complete": true,
  "text": "All readable text in the image, transcribed faithfully. If the image contains explanatory text, preserve the full causal chain (why / because / if...then / threshold / cost / overhead / retransmission, etc.).",
  "formulas": ["formula1", "formula2"],
  "tables": [
    {
      "caption": "table caption if any",
      "headers": ["col1", "col2"],
      "rows": [["a", "b"], ["c", "d"]]
    }
  ],
  "concepts": [
    "Concept name: its definition or explanation from the image, including WHY if present",
    "Another concept: its explanation, including WHY if present"
  ],
  "reasoning": "Core causal chain or logical explanation shown in the image. If no clear logic is shown, write 'None'."
}
'score' is content completeness from 1-10.
'complete' means the screenshot is fully visible, not cropped or blocked.
If there are no formulas or tables, use empty arrays [] for those fields.
IMPORTANT: keep the JSON keys exactly as shown in English ("theme", "score", "complete", "text",
"formulas", "tables", "concepts", "reasoning"). Do NOT translate the keys.
Only the VALUES of "theme", "text", "concepts" and "reasoning" must be written in Simplified Chinese
(keep formulas, code and proper nouns in their original form), since they go into a Chinese note verbatim.""".strip()

# 精简兜底 prompt：当主 extract prompt 因内容过密被 max_tokens 截断成非法 JSON 时，
# 用更少字段 + 明确要求「紧凑 JSON、≤800 tokens」再试一次，尽量补齐文字。
EXTRACT_PROMPT_SIMPLE = """这是教学视频的一张截图。请简洁提取其中关键教学内容。
严格只输出如下 JSON，不要任何额外文字：
{
  "theme": "简短标题(5-15字，简体中文)",
  "score": 8,
  "complete": true,
  "text": "图中可读文字的忠实转写，保留关键因果链",
  "concepts": ["概念名：简要解释(若有 WHY 一并保留)"]
}
JSON 键名保持英文(theme/score/complete/text/concepts)。值用简体中文。
务必输出紧凑且完整的 JSON，总长度控制在 800 tokens 以内。""".strip()


def encode_image(path: Path) -> str:
    """将图片转为 base64 data URL。"""
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def parse_json_response(text: str) -> dict:
    """尝试从模型返回中提取 JSON。"""
    text = text.strip()
    # 如果有代码块，去掉标记
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试从文本中提取第一个 JSON 对象
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise


def call_vision(headers, base_url, payload, timeout):
    """POST 到 chat/completions：处理 max_tokens 超限自适应降级，返回文本内容。"""
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers, json=payload, timeout=timeout
    )
    # 自适应降级：若因 max_tokens 超限被拒，按服务端提示的上限重试一次
    if resp.status_code == 400 and "max_tokens" in resp.text:
        m = re.search(r"\[\s*\d+\s*,\s*(\d+)\s*\]", resp.text)
        if m:
            payload["max_tokens"] = int(m.group(1))
            print(f"[warn] max_tokens 超限，自动降为 {payload['max_tokens']} 重试")
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers, json=payload, timeout=timeout
            )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def process_one_frame(
    frame_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int,
    max_retries: int,
    prompt: str,
    fallback_prompt: str = None
) -> tuple:
    """
    对单帧进行 vision 分析，失败时自动重试。
    若主 prompt 多次重试后仍 JSON 解析失败（常见原因：内容过密被 max_tokens 截断成
    非法 JSON），且提供了 fallback_prompt，则再用更精简的 prompt 兜底重试一次，尽量补齐文字。
    返回: (frame_name, result_dict)
    """
    frame_name = frame_path.name
    data_url = encode_image(frame_path)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    def build_payload(p: str) -> dict:
        return {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": p},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            "temperature": 0.1,
            # 不同厂商上限差异很大：智谱 glm-4v-flash 硬上限 1024，超了直接 400(code 1210)。
            # 默认取 1024（中文约 700 字，足够输出 JSON），可用 VISION_MAX_TOKENS 覆盖。
            "max_tokens": int(os.getenv("VISION_MAX_TOKENS", "1024"))
        }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            payload = build_payload(prompt)
            content = call_vision(headers, base_url, payload, timeout)
            parsed = parse_json_response(content)
            # 保留模型返回的全部字段（keywords / content 等在下游用于主题去重和正文生成）
            result = dict(parsed) if isinstance(parsed, dict) else {}
            # 要求「用中文输出」时，部分模型会把 JSON 键名一并翻译，导致字段取不到值，
            # 这里做一次键名归一化（英文键优先，不被翻译键覆盖）。
            result = normalize_keys(result)
            result.update({
                "theme": str(result.get("theme", "")),
                "score": int(result.get("score", 0) or 0),
                "complete": bool(result.get("complete", True)),
                "raw": content,
                "error": None,
                "attempts": attempt,
                "timestamp": datetime.now().isoformat()
            })
            kw = result.get("keywords")
            if isinstance(kw, str):
                result["keywords"] = [k.strip() for k in re.split(r"[,，、;；]", kw) if k.strip()]
            elif not isinstance(kw, list):
                result["keywords"] = []
            return frame_name, result
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # 指数退避

    # 主 prompt 多次失败（JSONDecodeError 多为内容被截断）→ 用精简 prompt 兜底重试一次
    if fallback_prompt and last_error and "JSONDecodeError" in last_error:
        try:
            payload = build_payload(fallback_prompt)
            content = call_vision(headers, base_url, payload, timeout)
            parsed = parse_json_response(content)
            result = dict(parsed) if isinstance(parsed, dict) else {}
            result = normalize_keys(result)
            result.update({
                "theme": str(result.get("theme", "")),
                "score": int(result.get("score", 0) or 0),
                "complete": bool(result.get("complete", True)),
                "raw": content,
                "error": None,
                "attempts": max_retries + 1,
                "fallback": True,
                "timestamp": datetime.now().isoformat()
            })
            return frame_name, result
        except Exception as e2:
            last_error = f"{type(e2).__name__}: {e2}"

    # 全部重试失败
    error_result = {
        "theme": "",
        "score": 0,
        "complete": False,
        "raw": "",
        "error": last_error,
        "attempts": max_retries,
        "timestamp": datetime.now().isoformat()
    }
    return frame_name, error_result


def main():
    parser = argparse.ArgumentParser(
        description="video-notes-pipeline: 并发视觉分析"
    )
    parser.add_argument("--frames", required=True, help="selected/ 帧目录路径")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--mode", choices=["score", "extract"], default="score",
                        help="分析模式: score=打分选帧（默认）, extract=提取图中文字/公式/表格")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY,
                        help="API key，默认先从 .env 文件 VISION_API_KEY 获取，再从环境变量获取")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"模型基础 URL，默认 {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"模型 ID，默认 {DEFAULT_MODEL}")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"并发线程数，默认 {DEFAULT_WORKERS}")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"单请求超时秒数，默认 {DEFAULT_TIMEOUT}")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"单帧最大重试次数，默认 {DEFAULT_MAX_RETRIES}")
    parser.add_argument("--resume", action="store_true",
                        help="断点续传：跳过已存在于输出 JSON 中的帧")
    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] 缺少 API key。请设置环境变量 VISION_API_KEY 或使用 --api-key")
        sys.exit(1)

    frames_dir = Path(args.frames)
    if not frames_dir.exists():
        print(f"[ERROR] 帧目录不存在: {frames_dir}")
        sys.exit(1)

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not frames:
        print(f"[ERROR] 目录中没有 frame_*.jpg: {frames_dir}")
        sys.exit(1)

    prompt = SCORE_PROMPT if args.mode == "score" else EXTRACT_PROMPT
    print(f"[INFO] 模式={args.mode}，发现 {len(frames)} 张帧，使用 {args.workers} 线程并发分析")
    print(f"[INFO] base_url={args.base_url}, model={args.model}")

    # 断点续传
    existing = {}
    if args.resume and Path(args.output).exists():
        existing = json.load(open(args.output, encoding="utf-8"))
        frames = [f for f in frames if f.name not in existing]
        print(f"[INFO] 断点续传: 已完成 {len(existing)} 帧，剩余 {len(frames)} 帧")

    results = dict(existing)
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_frame = {
            executor.submit(
                process_one_frame,
                frame,
                args.api_key,
                args.base_url,
                args.model,
                args.timeout,
                args.max_retries,
                prompt,
                EXTRACT_PROMPT_SIMPLE if args.mode == "extract" else None
            ): frame for frame in frames
        }

        completed = 0
        for future in as_completed(future_to_frame):
            frame = future_to_frame[future]
            try:
                frame_name, result = future.result()
                results[frame_name] = result
                completed += 1
                status = "✓" if not result["error"] else "✗"
                print(f"[{status}] {completed}/{len(frames)} {frame_name} "
                      f"score={result['score']} theme={result['theme'][:30]}...")
            except Exception as e:
                print(f"[✗] {frame.name} 异常: {e}")
                results[frame.name] = {
                    "theme": "", "score": 0,
                    "complete": False, "raw": "", "error": str(e),
                    "attempts": 0, "timestamp": datetime.now().isoformat()
                }

    elapsed = time.time() - start_time
    success = sum(1 for r in results.values() if not r["error"])
    failed = len(results) - success

    # 保存结果
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n[INFO] 完成：成功 {success}/{len(results)} 帧，失败 {failed} 帧，"
          f"耗时 {elapsed:.1f}秒，平均 {elapsed/max(len(results),1):.1f}秒/帧")
    print(f"[INFO] 结果已保存到: {out_path}")

    if failed > 0:
        print("[WARN] 部分帧分析失败，请检查输出 JSON 中的 error 字段")
        sys.exit(2)


if __name__ == "__main__":
    main()
