#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨 PyAV / FFmpeg 版本的音频解码兼容层。

背景：faster-whisper <= 1.2.x 的 ``audio.decode_audio()`` 会调用
``av.open(..., metadata_errors="ignore")``；PyAV 15+ 移除了该参数。
在只装了新版 av 的环境里，所有本地 ASR 路径都会抛
``TypeError: open() got an unexpected keyword argument 'metadata_errors'``。
把 av 钉死到旧版并不通用（部分平台/Python 版本没有预编译 wheel），
因此这里让解码路径对 av 版本免疫。

decode_audio_any() 按以下顺序取第一条可用路径：

1. 标准 16k / 单声道 / s16le WAV：用 wave + numpy 直接读，完全不碰 av；
2. faster-whisper 自带的 decode_audio（旧版 av 的正常路径）；
3. 上述失败（含新版 av 的 TypeError）时，用 ffmpeg 把任意音视频容器
   转成 16k 单声道 PCM WAV 再读。

返回 float32 ndarray（取值 [-1, 1]），可直接传给 WhisperModel.transcribe()。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave

import numpy as np

SAMPLE_RATE = 16000


def find_ffmpeg() -> str:
    """跨平台定位 ffmpeg：PATH、Windows 便携版、winget 安装的 Gyan.FFmpeg。"""
    candidates = [shutil.which("ffmpeg")]
    if os.name == "nt":
        candidates.append(r"C:\ffmpeg\bin\ffmpeg.exe")
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            base = os.path.join(local_app, "Microsoft", "WinGet", "Packages")
            try:
                for name in os.listdir(base):
                    if not name.startswith("Gyan.FFmpeg"):
                        continue
                    pkg = os.path.join(base, name)
                    for sub in os.listdir(pkg):
                        exe = os.path.join(pkg, sub, "bin", "ffmpeg.exe")
                        if os.path.isfile(exe):
                            candidates.append(exe)
            except OSError:
                pass
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise RuntimeError(
        "未找到 ffmpeg：请安装 FFmpeg 并加入 PATH，"
        "Windows 也可解压便携版到 C:\\ffmpeg\\bin"
    )


def _read_pcm_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if (w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1
                or w.getsampwidth() != 2):
            raise ValueError("not a 16k/mono/s16le wav")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _ffmpeg_to_array(src: str) -> np.ndarray:
    ffmpeg = find_ffmpeg()
    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="vnp_asr_")
    os.close(fd)
    try:
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", src, "-vn",
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", tmp],
            check=True, capture_output=True, text=True,
        )
        return _read_pcm_wav(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def decode_audio_any(audio_path: str, sampling_rate: int = SAMPLE_RATE) -> np.ndarray:
    """把音频/视频文件解成 16k 单声道 float32 ndarray，兼容任意 av 版本。"""
    path = str(audio_path)
    if path.lower().endswith((".wav", ".wave")):
        try:
            return _read_pcm_wav(path)
        except Exception:
            pass
    try:
        from faster_whisper.audio import decode_audio
        return decode_audio(path, sampling_rate=sampling_rate)
    except Exception:
        # 新版 PyAV 的 metadata_errors 报错、或容器解码失败，统一交给 ffmpeg
        pass
    return _ffmpeg_to_array(path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python audio_compat.py <audio-or-video-file>")
        sys.exit(2)
    arr = decode_audio_any(sys.argv[1])
    print(f"OK: {len(arr) / SAMPLE_RATE:.1f}s audio, dtype={arr.dtype}, "
          f"peak={float(np.abs(arr).max()):.4f}")
