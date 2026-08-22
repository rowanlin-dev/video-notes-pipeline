# -*- coding: utf-8 -*-
"""对 B 站视频音频做 ASR，输出带时间戳字幕 JSON + TXT（通用版）。

用法:
    python asr_subtitle.py <音频文件> <输出JSON> [输出TXT] [模型目录]

示例:
    python asr_subtitle.py /tmp/audio_16k.wav runs/BV1xx411c7mD_p1/BV1xx411c7mD_p1_subtitles.json \
        runs/BV1xx411c7mD_p1/BV1xx411c7mD_p1_subtitles.txt models/faster-whisper-small

依赖: pip install faster-whisper（模型下载需 HF_ENDPOINT=https://hf-mirror.com，禁用 hf_xet）
"""
import json, os, sys, time

from faster_whisper import WhisperModel


def _mmss(s: float) -> str:
    """秒 -> MMmSSs（与 extract_frames 字幕 TXT 同构，md_note 可解析）。"""
    s = int(round(s))
    m, sec = divmod(s, 60)
    return f"{m:02d}m{sec:02d}s"

AUDIO = sys.argv[1] if len(sys.argv) > 1 else "/tmp/audio_16k.wav"
OUT_JSON = sys.argv[2] if len(sys.argv) > 2 else "subtitles.json"
OUT_TXT = sys.argv[3] if len(sys.argv) > 3 else "subtitles.txt"
MODEL_DIR = sys.argv[4] if len(sys.argv) > 4 else "models/faster-whisper-small"

print("加载模型...", flush=True)
model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8")
print("开始识别...", flush=True)
t0 = time.time()
segments, info = model.transcribe(AUDIO, language="zh", beam_size=5,
                                  vad_filter=True, vad_parameters={"min_silence_duration_ms": 500})
print(f"检测语言: {info.language} (p={info.language_probability:.2f})", flush=True)

body = []
for seg in segments:
    body.append({
        "from": round(seg.start, 1),
        "to": round(seg.end, 1),
        "content": seg.text.strip(),
    })

os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)), exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump({"body": body}, fh, ensure_ascii=False, indent=1)
with open(OUT_TXT, "w", encoding="utf-8") as fh:
    for s in body:
        fh.write(f"[{_mmss(s['from'])}] {s['content']}\n")

print(f"完成: {len(body)} 条字幕, 耗时 {time.time()-t0:.0f}s", flush=True)
for s in body[:15]:
    print(f"  {s['from']:6.1f}-{s['to']:6.1f}  {s['content'][:60]}")
