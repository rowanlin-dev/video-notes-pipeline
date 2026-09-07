#!/usr/bin/env python3
"""单进程 ASR 转写（无分块，内存自适应）。
用法:
    python run_asr_direct.py <音频.wav> <输出.json> [输出.txt]

环境变量:
    OMP_NUM_THREADS / MKL_NUM_THREADS  控制 MKL 线程数（默认 2）
    ASR_MODEL_SIZE   tiny | base | small（默认 small，内存自适应）
"""
import json, os, sys, time
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

from faster_whisper import WhisperModel

MODEL_DIRS = {
    "tiny": "models/faster-whisper-tiny",
    "base": "models/faster-whisper-base",
    "small": "models/faster-whisper-small",
}


def _resolve_model_dir() -> str:
    env_size = os.environ.get("ASR_MODEL_SIZE", "").strip().lower()
    if env_size in MODEL_DIRS:
        return MODEL_DIRS[env_size]
    return MODEL_DIRS["small"]


AUDIO = sys.argv[1]
OUT_JSON = sys.argv[2]
OUT_TXT = sys.argv[3] if len(sys.argv) > 3 else OUT_JSON.replace(".json", ".txt")
MODEL_DIR = _resolve_model_dir()

_model_size_name = "unknown"
for k, v in MODEL_DIRS.items():
    if v == MODEL_DIR:
        _model_size_name = k
        break

print(f"加载模型 ({_model_size_name})...", flush=True)
model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8", cpu_threads=2, num_workers=1)
print("开始识别...", flush=True)
t0 = time.time()

segments, info = model.transcribe(AUDIO, language="zh", beam_size=5, vad_filter=False)
print(f"检测语言: {info.language} (p={info.language_probability:.2f})", flush=True)

body = []
for seg in segments:
    body.append({
        "from": round(seg.start, 1),
        "to": round(seg.end, 1),
        "content": seg.text.strip(),
    })
    if len(body) % 50 == 0:
        print(f"  进度: {len(body)} 条, 当前时间 {seg.start:.0f}s", flush=True)

os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)) or ".", exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump({"body": body}, fh, ensure_ascii=False, indent=1)
with open(OUT_TXT, "w", encoding="utf-8") as fh:
    for s in body:
        m1, s1 = divmod(int(round(s["from"])), 60)
        fh.write(f"[{m1:02d}m{s1:02d}s] {s['content']}\n")

print(f"完成: {len(body)} 条字幕, 耗时 {time.time()-t0:.0f}s", flush=True)
for s in body[:5]:
    print(f"  {s['from']:6.1f}-{s['to']:6.1f}  {s['content'][:60]}")