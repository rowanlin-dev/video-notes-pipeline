#!/usr/bin/env python3
"""快速 ASR 转写（无 VAD 过滤器，用小模型，适合长音频）。
用法:
    python asr_fast.py <音频> <输出JSON> [输出TXT]

环境变量:
    OMP_NUM_THREADS / MKL_NUM_THREADS  控制 MKL 线程数（默认 2），
    避免 mkl_malloc: failed to allocate memory。
"""
import json, os, sys, time

# 在导入 faster_whisper 之前设环境变量，避免 MKL 内存分配失败
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

from faster_whisper import WhisperModel

AUDIO = sys.argv[1]
OUT_JSON = sys.argv[2]
OUT_TXT = sys.argv[3] if len(sys.argv) > 3 else OUT_JSON.replace(".json", ".txt")
MODEL_DIR = "models/faster-whisper-small"

def _mmss(s: float) -> str:
    s = int(round(s))
    m, sec = divmod(s, 60)
    return f"{m:02d}m{sec:02d}s"

print("加载模型 (small)...", flush=True)
model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8", cpu_threads=2)
print("开始识别...", flush=True)
t0 = time.time()

# 无 VAD 过滤器，速度快很多，但内存占用稍高
segments, info = model.transcribe(AUDIO, language="zh", beam_size=5, vad_filter=False)
print(f"检测语言: {info.language} (p={info.language_probability:.2f})", flush=True)

body = []
for seg in segments:
    body.append({
        "from": round(seg.start, 1),
        "to": round(seg.end, 1),
        "content": seg.text.strip(),
    })

os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)) or ".", exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump({"body": body}, fh, ensure_ascii=False, indent=1)
with open(OUT_TXT, "w", encoding="utf-8") as fh:
    for s in body:
        fh.write(f"[{_mmss(s['from'])}] {s['content']}\n")

print(f"完成: {len(body)} 条字幕, 耗时 {time.time()-t0:.0f}s", flush=True)
for s in body[:5]:
    print(f"  {s['from']:6.1f}-{s['to']:6.1f}  {s['content'][:60]}")