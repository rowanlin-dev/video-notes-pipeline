#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书视频 → 图文笔记  一键流水线
==================================
下载小红书视频（解析笔记页内嵌的 __INITIAL_STATE__，无需登录签名接口），
再复用本地视频流水线做 ASR + 抽帧 + 视觉打分 + 笔记 + PDF。

用法：
  python run_xhs_pipeline.py "https://www.xiaohongshu.com/explore/xxx?xsec_token=..."
  python run_xhs_pipeline.py "https://xhslink.com/xxx" --title "自定义标题"
  python run_xhs_pipeline.py "<链接>" --interval 8 --no-mind-map
  python run_xhs_pipeline.py "<链接>" --emit-brief          # 交给宿主 Agent 写笔记
  python run_xhs_pipeline.py "<链接>" --no-ima              # 不归档 ima

需要登录的笔记：浏览器登录小红书后导出 Cookie（Netscape 格式）保存为
`xiaohongshu_cookies.txt`，或在 .env 填写 XHS_COOKIE=web_session=...;a1=...
"""
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if os.name == "nt":
    venv_py = ROOT / "venv" / "Scripts" / "python.exe"
else:
    venv_py = ROOT / "venv" / "bin" / "python"
PY = str(venv_py) if venv_py.exists() else sys.executable
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from xhs_download import fetch, load_cookie, resolve_url, extract_note_id  # noqa: E402


def load_env():
    """读取 .env 到进程环境（不覆盖已有变量）。"""
    f = ROOT / ".env"
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


def build_context(meta: dict) -> str:
    """把作者正文 / 标签 / 互动数据整理成笔记的补充素材。"""
    tags = " ".join(f"#{t}" for t in (meta.get("tags") or []))
    it = meta.get("interact") or {}
    lines = [
        "【小红书作品信息】",
        f"标题：{meta.get('title') or '（无标题）'}",
        f"作者：@{meta.get('author') or '未知'}",
        f"作品链接：{meta.get('url')}",
    ]
    if tags:
        lines.append(f"标签：{tags}")
    if it:
        lines.append(
            f"互动：点赞 {it.get('likedCount') or 0} · 收藏 {it.get('collectedCount') or 0}"
            f" · 评论 {it.get('commentCount') or 0} · 分享 {it.get('shareCount') or 0}")
    if meta.get("desc"):
        lines += ["", "作者正文：", meta["desc"]]
    return "\n".join(lines).strip()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="小红书视频转图文笔记流水线")
    ap.add_argument("url", help="小红书笔记链接（explore / discovery / xhslink 短链）")
    ap.add_argument("--title", default=None, help="笔记标题（缺省用作品标题）")
    ap.add_argument("--cookie", default="", help="直接给 cookie 字符串")
    ap.add_argument("--cookie-file", default="", help="Netscape 格式 cookie 文件路径")
    ap.add_argument("--quality", default="resolution",
                    choices=["resolution", "bitrate", "size"], help="下载清晰度偏好")
    ap.add_argument("--redownload", action="store_true", help="已有视频也强制重新下载")
    ap.add_argument("--interval", type=int, default=5, help="抽帧间隔（秒，默认 5）")
    ap.add_argument("--min-frames", type=int, default=5, help="最少精选帧数")
    ap.add_argument("--max-frames", type=int, default=12, help="精选基础上限")
    ap.add_argument("--hard-max-frames", type=int, default=30, help="精选绝对上限")
    ap.add_argument("--brain-map", dest="brain_map", action="store_true", default=None,
                    help="只做脑图：跳过抽帧/OCR/打分（默认按视频时长自动判定）")
    ap.add_argument("--no-brain-map", dest="brain_map", action="store_false",
                    help="强制截图流程")
    ap.add_argument("--mind-map", dest="mind_map", action="store_true", default=None,
                    help="生成思维脑图（默认全开）")
    ap.add_argument("--no-mind-map", dest="mind_map", action="store_false",
                    help="不生成脑图")
    ap.add_argument("--segment-minutes", type=int, default=0,
                    help="长视频切块：每段约多少分钟（<=1 关闭，默认关闭）")
    ap.add_argument("--max-segments", type=int, default=12, help="切块最大段数")
    ap.add_argument("--no-ima", action="store_true", help="跳过上传 ima 知识库")
    ap.add_argument("--emit-brief", action="store_true",
                    help="Agent 原生模式：生成笔记简报后停止，由宿主 Agent 写笔记")
    ap.add_argument("--from-step", type=int, default=1, help="从第几步开始（断点续跑）")
    ap.add_argument("--parallel-asr", dest="parallel_asr", action="store_true", default=None)
    ap.add_argument("--no-parallel-asr", dest="parallel_asr", action="store_false")
    ap.add_argument("--asr-workers", type=int, default=None, help="并行 ASR 进程数（默认 auto）")
    ap.add_argument("--asr-chunk-minutes", type=int, default=None, help="ASR 分块分钟数（默认 auto）")
    ap.add_argument("--asr-model-size", type=str, default=None,
                    choices=["tiny", "base", "small"], help="ASR 模型尺寸（默认 auto）")
    args = ap.parse_args()

    load_env()
    cookie = load_cookie(args.cookie, args.cookie_file)

    try:
        url = resolve_url(args.url)
        note_id = extract_note_id(url)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    run_id = f"xhs_{note_id}"
    run_dir = ROOT / "runs" / f"{run_id}_p1"
    print(f"[xhs] 作品 {note_id} → 工作目录 {run_dir}")

    try:
        meta = fetch(url, str(run_dir), cookie=cookie, preference=args.quality,
                     redownload=args.redownload)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    title = (args.title or meta.get("title") or "").strip()
    if not title:
        title = (meta.get("desc") or "").strip().splitlines()[0][:40] or note_id

    # 作者正文 → 补充素材，写作时与字幕融合
    context_path = run_dir / "xhs_caption.txt"
    context_path.write_text(build_context(meta), encoding="utf-8")

    duration_min = (meta.get("duration") or 0) / 60
    estimate = max(6, 5 + 0.56 * duration_min)
    print(f"[xhs] 标题：{title}")
    print(f"[xhs] 作者：@{meta.get('author')}   时长：{duration_min:.1f}min")
    print(f"[xhs] 预估处理耗时约 {estimate:.0f} 分钟（下载已完成，含 ASR / 抽帧 / 笔记 / PDF）")

    cmd = [PY, str(ROOT / "run_local_pipeline.py"),
           "--video", meta["video_path"],
           "--run-id", run_id,
           "--title", title,
           "--desc", (meta.get("desc") or "")[:1500],
           "--context-file", str(context_path),
           "--source-label", f"小红书 · @{meta.get('author')}" if meta.get("author") else "小红书",
           "--source-link", meta["url"],
           "--interval", str(args.interval),
           "--min-frames", str(args.min_frames),
           "--max-frames", str(args.max_frames),
           "--hard-max-frames", str(args.hard_max_frames),
           "--from-step", str(args.from_step)]
    if args.brain_map is not None:
        cmd += ["--brain-map" if args.brain_map else "--no-brain-map"]
    if args.mind_map is not None:
        cmd += ["--mind-map" if args.mind_map else "--no-mind-map"]
    if args.segment_minutes and args.segment_minutes > 1:
        cmd += ["--segment-minutes", str(args.segment_minutes),
                "--max-segments", str(args.max_segments)]
    if args.no_ima:
        cmd += ["--no-ima"]
    if args.emit_brief:
        cmd += ["--emit-brief"]
    if args.parallel_asr is not None:
        cmd += ["--parallel-asr" if args.parallel_asr else "--no-parallel-asr"]
    if args.asr_workers is not None:
        cmd += ["--asr-workers", str(args.asr_workers)]
    if args.asr_chunk_minutes is not None:
        cmd += ["--asr-chunk-minutes", str(args.asr_chunk_minutes)]
    if args.asr_model_size is not None:
        cmd += ["--asr-model-size", args.asr_model_size]

    print("[xhs] 进入笔记流水线 ...")
    r = subprocess.run(cmd, env=os.environ.copy())
    if r.returncode != 0:
        print(f"[error] 笔记流水线失败（exit {r.returncode}）", file=sys.stderr)
        sys.exit(r.returncode)

    out_dir = run_dir / "output"
    md_files = sorted(out_dir.glob("*.md")) if out_dir.exists() else []
    if md_files:
        print(f"[xhs] 完成：{md_files[-1]}")
        pdf = md_files[-1].with_suffix(".pdf")
        if pdf.exists():
            print(f"[xhs] PDF：{pdf}")
    else:
        print(f"[xhs] 完成，产物目录：{out_dir}")


if __name__ == "__main__":
    main()
