#!/usr/bin/env python3
"""ASR 转写（ctranslate2 直连，绕过 MKL 内存问题）。
用法:
    python asr_ct2.py <音频> <输出JSON> [输出TXT]
"""
import json, os, sys, time
import ctranslate2
import numpy as np
import soundfile as sf
from tokenizers import Tokenizer as HFTokenizer
from faster_whisper.feature_extractor import FeatureExtractor

AUDIO = sys.argv[1]
OUT_JSON = sys.argv[2]
OUT_TXT = sys.argv[3] if len(sys.argv) > 3 else OUT_JSON.replace(".json", ".txt")
MODEL_DIR = "models/faster-whisper-small"

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

def _mmss(s: float) -> str:
    s = int(round(s))
    m, sec = divmod(s, 60)
    return f"{m:02d}m{sec:02d}s"

def _decode_tokens(tokenizer, tokens):
    """Decode token IDs to text."""
    return tokenizer.decode(tokens, skip_special_tokens=True)

print("加载模型...", flush=True)
t0 = time.time()
model = ctranslate2.models.Whisper(MODEL_DIR, device="cpu", compute_type="int8")
fe = FeatureExtractor()
# Load HF tokenizer
tk_path = os.path.join(MODEL_DIR, "tokenizer.json")
hf_tk = HFTokenizer.from_file(tk_path)
print(f"模型加载耗时: {time.time()-t0:.0f}s", flush=True)

print("读取音频...", flush=True)
audio, sr = sf.read(AUDIO, dtype="float32")
if sr != 16000:
    import scipy.signal
    audio = scipy.signal.resample(audio, int(len(audio) * 16000 / sr))
duration = len(audio) / 16000
print(f"音频时长: {duration:.0f}s ({_mmss(duration)})", flush=True)

print("开始识别...", flush=True)
t0 = time.time()

body = []
offset = 0.0
seg_id = 0

while offset * 16000 < len(audio):
    start_sample = int(offset * 16000)
    end_sample = min(start_sample + 30 * 16000, len(audio))
    chunk = audio[start_sample:end_sample]

    features = fe(chunk)
    # Pad or truncate to exactly 3000 frames (30s @ 100fps)
    if features.shape[1] < 3000:
        pad = np.zeros((features.shape[0], 3000 - features.shape[1]))
        features = np.concatenate([features, pad], axis=1)
    elif features.shape[1] > 3000:
        features = features[:, :3000]
    features = np.expand_dims(features, 0)

    storage = ctranslate2.StorageView.from_array(np.ascontiguousarray(features))
    # <|startoftranscript|> <|zh|> <|transcribe|> <|notimestamps|>
    prompt_ids = [50258, 50260, 50359, 50363]
    result = model.generate(storage, prompts=[prompt_ids],
                            beam_size=5, suppress_blank=True)

    tokens = result[0].sequences_ids[0] if result[0].sequences_ids else []
    text = _decode_tokens(hf_tk, tokens).strip() if tokens else ""

    if text:
        seg_from = round(offset, 1)
        seg_to = round(offset + (end_sample - start_sample) / 16000, 1)
        body.append({"from": seg_from, "to": seg_to, "content": text})

    seg_id += 1
    offset += 30

    if seg_id % 10 == 0:
        progress = min(offset / duration * 100, 100)
        elapsed = time.time() - t0
        eta = elapsed / max(progress / 100, 0.01) - elapsed if progress > 0 else 0
        print(f"  [{seg_id}] {_mmss(offset)} / {_mmss(duration)} ({progress:.0f}%) ETA {_mmss(eta)}", flush=True)

os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)) or ".", exist_ok=True)
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump({"body": body}, fh, ensure_ascii=False, indent=1)
with open(OUT_TXT, "w", encoding="utf-8") as fh:
    for s in body:
        fh.write(f"[{_mmss(s['from'])}] {s['content']}\n")

print(f"完成: {len(body)} 条字幕, 耗时 {time.time()-t0:.0f}s", flush=True)
for s in body[:5]:
    print(f"  {s['from']:6.1f}-{s['to']:6.1f}  {s['content'][:60]}")