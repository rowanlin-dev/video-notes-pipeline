# -*- coding: utf-8 -*-
"""用 deepseek-chat 修正 ASR 字幕错词（术语级，保留时间戳）（通用版）。

用法:
    python fix_subtitles.py <字幕JSON> [--video-topic 视频主题] [--extra-terms 额外术语表]

从 .env 读 TEXT_BASE_URL(带 /v1) / TEXT_MODEL / TEXT_API_KEY（或 DEEPSEEK_*），
POST chat/completions。修正结果写回原 JSON（覆盖 body.content）+ 同步 .txt。

经验:
- 术语表要显式写进 prompt，否则 LLM 保守不改（如 poster man→Postman、moke→mock）
- 不要依赖 LLM 回传行号（每批重新编号会超出批内行数校验被丢弃），
  改为「按输出顺序拼接 + 只提取 [时间戳] 文本 行」，见 fix_subtitles_bv1wr.py 的精简版
"""
import json, os, sys, urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 读 .env 拿 key
env = {}
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")

API_KEY = env.get("DEEPSEEK_API_KEY") or env.get("TEXT_API_KEY") or os.environ.get("TEXT_API_KEY", "")
BASE_URL = env.get("DEEPSEEK_BASE_URL") or env.get("TEXT_BASE_URL") or "https://api.deepseek.com/v1"
MODEL = env.get("TEXT_MODEL") or "deepseek-chat"
if not API_KEY:
    print("错误: 未找到 API key（.env 的 TEXT_API_KEY/DEEPSEEK_API_KEY）")
    sys.exit(1)

# 确保 base url 正确拼接
if not BASE_URL.endswith("/chat/completions"):
    base = BASE_URL.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    CHAT_URL = base + "/chat/completions"
else:
    CHAT_URL = BASE_URL

SUBS_JSON = sys.argv[1] if len(sys.argv) > 1 else ""
if not SUBS_JSON:
    print("用法: python fix_subtitles.py <字幕JSON> [--video-topic 主题] [--extra-terms 术语表]")
    sys.exit(1)

TOPIC = ""
EXTRA_TERMS = ""
args = sys.argv[2:]
while args:
    a = args.pop(0)
    if a == "--video-topic" and args:
        TOPIC = args.pop(0)
    elif a == "--extra-terms" and args:
        EXTRA_TERMS = args.pop(0)

print("模型:", MODEL, "| key:", API_KEY[:6] + "...")

with open(SUBS_JSON, encoding="utf-8") as fh:
    data = json.load(fh)
body = data["body"]
print("原始字幕:", len(body), "条")

# 拼接全文（带序号）
full = "\n".join(f"{i+1}. {s['content']}" for i, s in enumerate(body))
print("总字数:", len(full))

topic_line = f"视频主题是: {TOPIC}。" if TOPIC else ""
term_line = f"额外术语表(如出现请修正): {EXTRA_TERMS}。" if EXTRA_TERMS else ""
sys_prompt = f"""你是字幕校对专家。以下是某 B 站技术视频的语音识别(ASR)字幕。{topic_line}
请逐条修正语音识别错误，只改错词/术语，不改变原意，不增删内容，不合并拆分条目。
常见修正方向: 英文术语还原(如 poster man→Postman、moke→mock、viewqueryplane→vue-query-plugin)、
繁转简(瀏览器→浏览器)、技术术语纠错(负载均衡、Round Robin、nginx、proxy_pass 等)、同音字纠错。
{term_line}
输出格式: 严格按输入行号逐条输出修正后的字幕，每行一条，格式"行号|修正后文本"，不要输出任何其他内容。"""

req = urllib.request.Request(
    CHAT_URL,
    data=json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": full},
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
    }).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    corrected_text = result["choices"][0]["message"]["content"]
    print("=== 修正结果(前 800 字) ===")
    print(corrected_text[:800])

    # 按行解析"行号|文本"，按输出顺序回填（不信任行号）
    out_lines = corrected_text.strip().splitlines()
    new_contents = []
    for line in out_lines:
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            new_contents.append(line.split("|", 1)[1].strip())
        else:
            # 兼容无分隔符的纯文本行：按顺序追加
            new_contents.append(line)
    print(f"解析出 {len(new_contents)} 行修正文本")

    if len(new_contents) == len(body):
        for i, c in enumerate(new_contents):
            body[i]["content"] = c
        with open(SUBS_JSON, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        # 同步 .txt
        txt_path = SUBS_JSON.rsplit(".json", 1)[0] + ".txt"
        if os.path.exists(txt_path):
            with open(txt_path, "w", encoding="utf-8") as fh:
                for s in body:
                    fh.write(f"[{s['from']:.1f}-{s['to']:.1f}] {s['content']}\n")
        print(f"已写回 {SUBS_JSON} + {txt_path}")
    else:
        print(f"[warn] 修正文本行数({len(new_contents)})与原始({len(body)})不一致，未写回")
except Exception as e:
    print("API 调用失败:", e)
    sys.exit(1)
