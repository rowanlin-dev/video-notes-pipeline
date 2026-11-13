#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video-notes-pipeline 安装后自检（跨 Windows / macOS / Linux）。

为什么需要它：只检查 `import` 成功、WhisperModel 能构造是不够的。
例如 PyAV 15+ 移除了 av.open(..., metadata_errors=...)，静态检查全部通过，
但真正跑 ASR 时会崩。本脚本用「1 秒音频 → 解码 → 实际转写」做端到端冒烟，
把这类破坏性变更拦在安装阶段。

用法:
    python scripts/doctor.py            # 离线自检（快，不消耗 API 额度）
    python scripts/doctor.py --live     # 额外校验 API Key / B站 Cookie 真实可用

退出码: 0 = 无 FAIL；1 = 存在 FAIL。
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

RESULTS = []


def report(status: str, label: str, detail: str = ""):
    RESULTS.append(status)
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def version(pkg: str) -> str:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return ""


def check_python():
    v = sys.version.split()[0]
    ok = sys.version_info >= (3, 9)
    report("PASS" if ok else "FAIL", f"Python {v}", str(sys.executable))
    if not ok:
        print("       建议升级到 Python 3.10+")


def check_deps():
    required = {
        "yt-dlp": "视频下载",
        "imagehash": "帧去重",
        "av": "音频解码（由 audio_compat 兼容新旧版本）",
        "rapidocr-onnxruntime": "OCR 预筛",
        "python-docx": "文档",
        "markdown": "Markdown → HTML（PDF 渲染必需）",
        "Pillow": "图像",
        "requests": "HTTP",
        "python-dotenv": ".env",
        "faster-whisper": "本地 ASR",
        "ctranslate2": "ASR 推理",
        "onnxruntime": "OCR 推理",
        "numpy": "音频数组",
    }
    missing = []
    parts = []
    for pkg, why in required.items():
        v = version(pkg)
        if not v:
            missing.append(f"{pkg}（{why}）")
        else:
            parts.append(f"{pkg} {v}")
    report("PASS" if not missing else "FAIL", "Python 依赖", ", ".join(parts[:6]) + " …")
    if missing:
        print("       缺失：" + ", ".join(missing))
        print("       修复：pip install -r scripts/requirements.txt")
    # 关键组合：把已知的破坏性变更显式报出来
    av_v = version("av")
    fw_v = version("faster-whisper")
    if av_v and fw_v:
        try:
            major = int(av_v.split(".")[0])
            if major >= 15:
                report("PASS", f"av {av_v} + faster-whisper {fw_v} 组合",
                       "新版 av 已移除 metadata_errors，兼容层将自动走 ffmpeg 解码")
        except ValueError:
            pass


def check_ffmpeg():
    try:
        from audio_compat import find_ffmpeg
        exe = find_ffmpeg()
    except Exception as e:
        report("FAIL", "ffmpeg", str(e))
        return ""
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=15)
        first = out.stdout.splitlines()[0][:70] if out.stdout else ""
        report("PASS", "ffmpeg", f"{exe} | {first}")
    except Exception as e:
        report("FAIL", "ffmpeg", f"无法执行：{e}")
    return exe


def check_asr(ffmpeg: str):
    """端到端冒烟：生成 1s 静音 → 转成 m4a 容器 → 解码 → 真实转写。"""
    if not ffmpeg:
        report("FAIL", "ASR 端到端", "缺少 ffmpeg，跳过")
        return
    tmp = []
    try:
        import numpy as np
        wav = tempfile.mktemp(suffix=".wav", prefix="vnp_doctor_")
        m4a = tempfile.mktemp(suffix=".m4a", prefix="vnp_doctor_")
        tmp = [wav, m4a]
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", wav, "-c:a", "aac", m4a],
            check=True, capture_output=True, text=True, timeout=30,
        )
        from audio_compat import decode_audio_any
        audio = decode_audio_any(m4a)

        # 明确显示当前环境走的是哪条解码路径，便于排障
        backend = "av 原生解码"
        try:
            import av
            try:
                with av.open(m4a, mode="r", metadata_errors="ignore"):
                    pass
            except TypeError:
                backend = "ffmpeg 兜底（新版 av 已移除 metadata_errors）"
        except Exception:
            backend = "ffmpeg 兜底"

        models = [ROOT / "models" / n for n in
                  ("faster-whisper-small", "faster-whisper-base", "faster-whisper-tiny")]
        model = next((m for m in models if (m / "model.bin").exists()), None)
        if not model:
            report("WARN", "ASR 端到端",
                   f"解码成功（{len(audio)/16000:.1f}s，{backend}），但未找到本地模型，跳过实际转写；"
                   "用 HF_ENDPOINT=https://hf-mirror.com hf download Systran/faster-whisper-small "
                   "--local-dir models/faster-whisper-small 下载")
            return
        from faster_whisper import WhisperModel
        m = WhisperModel(str(model), device="cpu", compute_type="int8", cpu_threads=2)
        segments, info = m.transcribe(audio, language="zh", beam_size=1, vad_filter=False)
        list(segments)  # 消费生成器，确保真的跑完
        report("PASS", "ASR 端到端",
               f"1.0s m4a → 解码 → 转写成功 | {backend} | 模型 {model.name}")
    except Exception as e:
        report("FAIL", "ASR 端到端", f"{type(e).__name__}: {str(e)[:180]}")
        print("       这是最容易漏掉的一环：静态 import 通过不代表能真正转写")
    finally:
        for p in tmp:
            try:
                os.remove(p)
            except OSError:
                pass


def check_models():
    found = [p.name for p in (ROOT / "models").glob("faster-whisper-*")
             if (p / "model.bin").exists()] if (ROOT / "models").exists() else []
    report("PASS" if found else "WARN", "本地 ASR 模型",
           ", ".join(found) if found else "未预下载，运行时会自动联网拉取（国内建议用 hf-mirror）")


def check_env():
    env = ROOT / ".env"
    if not env.exists():
        report("WARN", ".env", "不存在；cp .env.example .env 后填写 VISION_API_KEY")
        return {}
    cfg = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    need = ["VISION_API_KEY", "VISION_BASE_URL", "VISION_MODEL"]
    empty = [k for k in need if not cfg.get(k)]
    report("PASS" if not empty else "WARN", ".env 关键项",
           "齐全" if not empty else "缺失/为空：" + ", ".join(empty))
    if not cfg.get("TEXT_API_KEY"):
        report("WARN", "TEXT_API_KEY", "未单独配置时正文会回退到 VISION_* / 免费档，长文可能截断")
    # 与 score_frames_concurrent.py 的取值顺序一致（该脚本会 load_dotenv）：
    # 环境变量 VISION_WORKERS → 旧键 WORKERS → .env → 代码默认 4。
    # 别把默认值写成 16：那正是免费档连锁 429 的元凶。
    raw = (os.getenv("VISION_WORKERS") or os.getenv("WORKERS")
           or cfg.get("VISION_WORKERS") or cfg.get("WORKERS") or "4")
    try:
        workers = int(raw)
    except ValueError:
        workers = 4
    src = ("环境变量" if (os.getenv("VISION_WORKERS") or os.getenv("WORKERS"))
           else ".env" if (cfg.get("VISION_WORKERS") or cfg.get("WORKERS"))
           else "代码默认")
    ok = workers <= 4
    report("PASS" if ok else "WARN", "视觉打分并发",
           f"实际 {workers} 线程（来源 {src}）"
           + ("，免费档建议 2-4" if ok else "，>4 极易触发 429，建议 VISION_WORKERS=2~4"))
    return cfg


# 旧模板里这些中性词会把正文截图 / 结论段当成广告或垃圾帧剔除。
_NEUTRAL_WORDS = {"资料", "免费", "课程", "福利", "送", "链接"}


def check_legacy_env(cfg: dict):
    """旧版 .env 会覆盖代码里已收敛的默认值，静态 PASS 很容易掩盖误伤。"""
    hints = []
    if cfg.get("WORKERS") and not cfg.get("VISION_WORKERS"):
        hints.append("WORKERS=… 是旧键，建议改名 VISION_WORKERS（旧键仍兼容）")
    try:
        ctx = int(cfg.get("AD_CONTEXT_SECONDS", "10"))
        if ctx > 10:
            hints.append(f"AD_CONTEXT_SECONDS={ctx} 过大，会连结论段一起跳过（建议 10）")
    except ValueError:
        hints.append("AD_CONTEXT_SECONDS 不是整数")
    for key in ("AD_KEYWORDS", "FRAME_TRASH_KEYWORDS"):
        words = {w.strip() for w in (cfg.get(key) or "").replace("，", ",").split(",")
                 if w.strip()}
        bad = sorted(words & _NEUTRAL_WORDS)
        if bad:
            hints.append(f"{key} 含中性词 {'/'.join(bad)}，可能误删正文（对照新 .env.example 收敛）")
    if not cfg.get("AD_MIN_HITS"):
        hints.append("未设 AD_MIN_HITS，代码按默认 2 组合判定（建议显式写 =2）")
    if hints:
        report("WARN", "旧版 .env 配置",
               "；".join(hints) + " | 对照 .env.example 更新即可消除本 WARN")
    else:
        report("PASS", ".env 配置版本", "与当前 .env.example 一致")


def check_cookies():
    p = ROOT / "bilibili_cookies.txt"
    if not p.exists():
        report("WARN", "B站 Cookie", "未配置，官方 AI 字幕大概率拿不到（会自动走本地 ASR）")
        return
    sess = ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) == 7 and f[5] == "SESSDATA":
            sess = f[6]
    ok = bool(sess) and "YOUR_" not in sess
    report("PASS" if ok else "WARN", "B站 Cookie",
           "Netscape 格式 / SESSDATA 已填" if ok else "SESSDATA 为空或仍是占位值")


def check_pdf():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    found = next((c for c in candidates if os.path.isfile(c)), None)
    if not found:
        found = shutil.which("chromium") or shutil.which("google-chrome")
    if found:
        report("PASS", "PDF 渲染", found)
    elif version("weasyprint"):
        report("PASS", "PDF 渲染", "无浏览器，使用 weasyprint 兜底")
    else:
        report("WARN", "PDF 渲染", "未发现 Edge/Chrome，也未装 weasyprint；PDF 步骤可能失败")


def check_live(cfg: dict):
    """可选：真实打一次 API / B站 接口，会消耗极少量额度。"""
    import requests
    key = cfg.get("VISION_API_KEY") or os.getenv("VISION_API_KEY", "")
    base = (cfg.get("VISION_BASE_URL") or os.getenv("VISION_BASE_URL", "")).rstrip("/")
    if key and base:
        try:
            r = requests.get(base + "/models", headers={"Authorization": "Bearer " + key}, timeout=20)
            report("PASS" if r.status_code == 200 else "FAIL", "视觉 API 连通",
                   f"GET /models → HTTP {r.status_code}")
        except Exception as e:
            report("FAIL", "视觉 API 连通", str(e)[:120])
    else:
        report("WARN", "视觉 API 连通", "缺少 Key / Base URL，跳过")
    p = ROOT / "bilibili_cookies.txt"
    if p.exists():
        sess = ""
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) == 7 and f[5] == "SESSDATA":
                sess = f[6]
        try:
            r = requests.get("https://api.bilibili.com/x/web-interface/nav",
                             headers={"Cookie": "SESSDATA=" + sess,
                                      "User-Agent": "Mozilla/5.0",
                                      "Referer": "https://www.bilibili.com/"}, timeout=20)
            login = (r.json().get("data") or {}).get("isLogin")
            report("PASS" if login else "WARN", "B站 SESSDATA",
                   "已登录" if login else "无效或已过期（不影响 ASR 兜底）")
        except Exception as e:
            report("WARN", "B站 SESSDATA", str(e)[:120])


def main():
    ap = argparse.ArgumentParser(description="video-notes-pipeline 安装后自检")
    ap.add_argument("--live", action="store_true", help="额外做真实 API / Cookie 连通性检查")
    args = ap.parse_args()

    print("=" * 68)
    print("video-notes-pipeline 安装自检" + ("（含联网校验）" if args.live else "（离线）"))
    print("=" * 68)
    check_python()
    check_deps()
    ffmpeg = check_ffmpeg()
    check_asr(ffmpeg)
    check_models()
    cfg = check_env()
    check_legacy_env(cfg)
    check_cookies()
    check_pdf()
    if args.live:
        check_live(cfg)
    print("-" * 68)
    n = {s: RESULTS.count(s) for s in ("PASS", "WARN", "FAIL")}
    print(f"汇总：{n['PASS']} PASS / {n['WARN']} WARN / {n['FAIL']} FAIL")
    if n["FAIL"]:
        print("存在 FAIL，请先修复后再跑视频。")
        sys.exit(1)
    print("可以开始跑：python run_pipeline.py <BV号> --no-ima")
    sys.exit(0)


if __name__ == "__main__":
    main()
