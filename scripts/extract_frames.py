"""
B站视频智能抽帧 + 字幕下载工具
功能：
  1. 下载B站视频（支持时间段裁剪）
  2. 场景检测 + 聚合去重抽帧（适合讲课视频）
  3. 固定间隔抽帧（对比用）
  4. 下载AI字幕（JSON + 带时间戳的TXT）

用法：
  python extract_frames.py <bvid> [--page N] [--start MM:SS] [--end MM:SS] [--mode scene|fixed|both] [--subtitle] [--interval 30] [--threshold 0.04] [--merge-gap 5]

示例：
  # 完整视频，场景检测 + 字幕
  python extract_frames.py BV1xx411c7mD --page 1 --mode scene --subtitle

  # 只处理 5:00-10:00 片段，固定 20s 间隔 + 字幕
  python extract_frames.py BV1xx411c7mD --page 1 --start 5:00 --end 10:00 --mode fixed --interval 20 --subtitle

  # 只下载字幕，不抽帧
  python extract_frames.py BV1xx411c7mD --page 1 --subtitle --mode fixed --interval 9999
"""

import argparse
import json
import os
import re
import subprocess
import sys
import glob
import time
from pathlib import Path

# 默认广告/卖课关键词（可在 .env 的 AD_KEYWORDS 覆盖，逗号分隔）
DEFAULT_AD_KEYWORDS = [
    "资料", "领取", "免费", "加微信", "小助理", "扣666", "扣个666",
    "点赞关注", "一键三连", "求赞", "白嫖", "课程", "训练营",
    "私教", "咨询", "优惠", "报名", "付费", "会员", "专栏",
    "买课", "卖课", "扫码", "公众号", "进群", "送", "福利",
]


# ============================================================
# 配置区 - 路径优先级：当前目录 > 环境变量 > 默认路径
# ============================================================
def _find_file(filename, env_var=None, default_dir=None):
    """在当前目录、环境变量目录、默认目录中查找文件"""
    # 1. 当前目录
    if os.path.exists(os.path.join(os.getcwd(), filename)):
        return os.getcwd()
    # 2. 环境变量目录
    if env_var and os.environ.get(env_var):
        d = os.environ[env_var]
        if os.path.exists(os.path.join(d, filename)):
            return d
    # 3. 脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(script_dir, filename)):
        return script_dir
    # 4. 默认目录
    if default_dir:
        return default_dir
    return os.getcwd()

_default_workspace = os.path.join(os.path.expanduser("~"), "bilibili-notes", "workspace")
_default_frames = os.path.join(os.path.expanduser("~"), "bilibili-notes", "frames")

WORKSPACE = os.environ.get("BILI_NOTES_WORKSPACE",
    _find_file("bilibili_cookies.txt", "BILI_NOTES_WORKSPACE", _default_workspace))
COOKIE_FILE = os.path.join(WORKSPACE, "bilibili_cookies.txt")
# 帧输出目录（必须是纯英文路径，vision工具不能识别中文路径）
FRAMES_DIR = os.environ.get("BILI_NOTES_FRAMES",
    os.environ.get("BILI_NOTES_WORKSPACE", _default_frames))

# ---- 音频转文本（ASR）兜底所需的本地路径 ----
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_SCRIPT_DIR)
ASR_SCRIPT = os.path.join(_SCRIPT_DIR, "asr_subtitle.py")
ASR_MODEL_DIR = os.path.join(ROOT_DIR, "models", "faster-whisper-small")


def time_to_seconds(t: str) -> int:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = t.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return int(t)


def seconds_to_time(s: float) -> str:
    """Convert seconds to MM-SS format (no colon, safe for filenames)."""
    m, sec = divmod(int(s), 60)
    return f"{m:02d}m{sec:02d}s"


def load_ad_keywords() -> list:
    """从 .env 读取 AD_KEYWORDS，否则用默认列表。"""
    raw = os.getenv("AD_KEYWORDS", "")
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    return DEFAULT_AD_KEYWORDS.copy()


def detect_ad_segments(subtitle_txt_path: str, keywords: list = None,
                       context_seconds: float = 10.0) -> list:
    """
    扫描字幕文本，定位包含广告/卖课关键词的时间区间。
    返回 [(start_sec, end_sec), ...]，区间会按 context_seconds 向前后扩展并合并。
    """
    if not subtitle_txt_path or not os.path.exists(subtitle_txt_path):
        return []
    keywords = keywords or load_ad_keywords()
    if not keywords:
        return []

    pattern = re.compile("|".join(re.escape(k) for k in keywords))
    hits = []

    # 字幕行格式：[MMmSSs] 内容  或  [HH:MM:SS] 内容
    ts_re = re.compile(r"^\[(\d+)m(\d+)s\]\s*(.*)$")
    ts_hms_re = re.compile(r"^\[(\d+):(\d+):(\d+)\]\s*(.*)$")

    for line in open(subtitle_txt_path, "r", encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        m = ts_re.match(line)
        if m:
            mm, s, content = int(m.group(1)), int(m.group(2)), m.group(3)
            sec = mm * 60 + s
        else:
            m = ts_hms_re.match(line)
            if m:
                h, mm, s, content = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                sec = h * 3600 + mm * 60 + s
            else:
                continue

        if pattern.search(content):
            hits.append((max(0.0, sec - context_seconds), sec + context_seconds))

    if not hits:
        return []

    # 合并重叠区间
    hits.sort()
    merged = [list(hits[0])]
    for s, e in hits[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    print(f"[ad-filter] 字幕命中 {len(keywords)} 个广告关键词，合并为 {len(merged)} 个过滤区间")
    for s, e in merged:
        print(f"  跳过 {seconds_to_time(s)} ~ {seconds_to_time(e)}")
    return [(s, e) for s, e in merged]


def get_video_info(bvid: str) -> dict:
    """Get video metadata from Bilibili API."""
    import urllib.request
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    if data["code"] != 0:
        raise RuntimeError(f"API error: {data}")
    return data["data"]


def get_cookie_value(cookie_file: str, name: str) -> str:
    """Extract a specific cookie value from Netscape cookie file."""
    with open(cookie_file, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 7 and parts[5] == name:
                return parts[6]
    return ""


def _asr_fallback(bvid: str, page: int, workspace: str) -> str:
    """无字幕轨（官方AI/内嵌/外挂均不可用）时的兜底：直接对视频音频跑本地
    faster-whisper，产出与官方字幕同构的 JSON + TXT。返回 TXT 路径，失败返回空串。

    这是「检测不到任何字幕 → 果断进入音频转文本」的自动化落点，避免流水线卡死
    或退化成粗糙的场景检测。
    """
    import subprocess as _sp
    safe = re.sub(r'[<>:"/\\|?*]', '_', f"{bvid}_p{page}")
    # 1) 找流水线已下载到工作目录的视频
    video = None
    for cand in (f"{safe}.mp4", f"{safe}.webm", f"{safe}.mkv", "video.mp4"):
        p = os.path.join(workspace, cand)
        if os.path.exists(p):
            video = p
            break
    if not video:
        print("[asr] 工作目录未找到视频文件，跳过 ASR")
        return ""
    out_json = os.path.join(workspace, f"{safe}_subtitles.json")
    if os.path.exists(out_json):
        print("[asr] 复用已存在的 ASR 字幕")
    else:
        if not (os.path.exists(ASR_SCRIPT) and os.path.exists(ASR_MODEL_DIR)):
            print("[asr] 缺少 asr_subtitle.py 或本地模型，跳过 ASR")
            return ""
        out_txt = out_json.replace(".json", ".txt")
        print(f"[asr] 未检测到任何字幕轨，果断进入音频转文本（本地 faster-whisper）...")
        env = os.environ.copy()
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            _sp.run([sys.executable, ASR_SCRIPT, video, out_json, out_txt, ASR_MODEL_DIR],
                    check=True, env=env)
        except Exception as e:
            print(f"[asr] ASR 失败，跳过字幕：{e}")
            return ""
    # 保证 TXT 与官方字幕同构（[MMmSSs] 格式，md_note 可解析）
    txt = out_json.replace(".json", ".txt")
    if not os.path.exists(txt) and os.path.exists(out_json):
        try:
            data = json.load(open(out_json, "r", encoding="utf-8"))
            with open(txt, "w", encoding="utf-8") as f:
                for it in data.get("body", []):
                    f.write(f"[{seconds_to_time(it['from'])}] {it.get('content', '')}\n")
        except Exception:
            pass
    return txt if os.path.exists(txt) else ""


def download_subtitles(bvid: str, page: int, start: float = None, end: float = None) -> str:
    """Download AI subtitles from Bilibili. Returns path to saved subtitle file."""
    import urllib.request

    info = get_video_info(bvid)
    cid = info["pages"][page - 1]["cid"]
    title = info["pages"][page - 1]["part"]

    safe_name = re.sub(r'[<>:"/\\|?*]', '_', f"{bvid}_p{page}")
    sub_path = os.path.join(WORKSPACE, f"{safe_name}_subtitles.json")

    if os.path.exists(sub_path):
        print(f"[skip] Subtitles already exist: {sub_path}")
        with open(sub_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        # Get subtitle URL from player API
        # cookie 文件可能不存在，此时以未登录状态请求（多数情况下拿不到字幕，但不应崩溃）
        sessdata = ""
        if os.path.exists(COOKIE_FILE):
            try:
                sessdata = get_cookie_value(COOKIE_FILE, "SESSDATA")
            except Exception as e:
                print(f"[warn] 读取 cookie 失败：{e}")
        if not sessdata:
            print("[warn] 无 SESSDATA，官方AI字幕大概率不可用。"
                  "如需字幕请配置 bilibili_cookies.txt（Netscape 格式）")
        player_url = f"https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}"
        req = urllib.request.Request(player_url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com",
            "Cookie": f"SESSDATA={sessdata}",
        })
        with urllib.request.urlopen(req) as resp:
            player_data = json.loads(resp.read())

        subtitles = player_data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            print("[warn] 未检测到官方AI/内嵌/外挂字幕（may need login 或无字幕轨）")
            return _asr_fallback(bvid, page, WORKSPACE)

        sub_url = subtitles[0]["subtitle_url"]
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url

        print(f"[subtitle] Downloading: {subtitles[0].get('lan_doc', 'unknown')}")
        req = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        with open(sub_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[subtitle] Saved: {sub_path}")

    # Filter by time range if specified
    body = data.get("body", [])
    if start is not None or end is not None:
        filtered = []
        for item in body:
            t = item["from"]
            if start is not None and t < start:
                continue
            if end is not None and t > end:
                continue
            filtered.append(item)
        body = filtered
        print(f"[subtitle] Filtered to {len(body)} entries ({start or 0}s - {end or 'end'}s)")

    # Save as readable text with timestamps
    txt_path = sub_path.replace(".json", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n")
        f.write(f"# 来源: {bvid} P{page}\n")
        if start or end:
            f.write(f"# 时间段: {start or 0}s - {end or 'end'}s\n")
        f.write(f"# 字幕条数: {len(body)}\n\n")
        for item in body:
            ts = seconds_to_time(item["from"])
            f.write(f"[{ts}] {item['content']}\n")
    print(f"[subtitle] Text: {txt_path} ({len(body)} entries)")

    return txt_path


def download_video(bvid: str, page: int, start: str = None, end: str = None) -> str:
    """Download video with yt-dlp, optionally trimming to a time range."""
    info = get_video_info(bvid)
    cid = info["pages"][page - 1]["cid"]
    title = info["pages"][page - 1]["part"]

    safe_name = re.sub(r'[<>:"/\\|?*]', '_', f"{bvid}_p{page}")
    output_path = os.path.join(WORKSPACE, f"{safe_name}.mp4")

    # If time range specified, use a different filename to avoid overwriting full video
    if start or end:
        range_tag = f"_{start or '0'}-{end or 'end'}".replace(":", "")
        range_path = os.path.join(WORKSPACE, f"{safe_name}{range_tag}.mp4")
        if os.path.exists(range_path):
            print(f"[skip] Trimmed video already exists: {range_path}")
            return range_path
        output_path = range_path
    elif os.path.exists(output_path):
        print(f"[skip] Video already exists: {output_path}")
        return output_path

    url = f"https://www.bilibili.com/video/{bvid}?p={page}"
    # 用当前解释器调用 yt_dlp 模块，避免依赖 PATH 里是否有 yt-dlp.exe（venv 场景下常没有）
    # 长视频(>60min)自动降分辨率：体积砍半~三分之二，显著降低 mcdn CDN 超时概率
    duration = (info.get("duration") or 0)
    if duration and duration > 3600 and not (start or end):
        fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        print(f"[info] 长视频({duration // 60}min) 降分辨率至 480p 以减小体积、降低下载超时风险")
    else:
        fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", fmt,
        "-o", output_path,
        # 不加 UA/Referer 极易被 B站风控拦成 HTTP 412
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "--referer", "https://www.bilibili.com/",
        "--continue",                       # 断点续传：保留 .part 部分文件，中断后可续拉
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "exp=1:20",          # 指数退避(1~20s)，避免对偶发超时的 CDN 节点猛刷
    ]
    # cookie 是可选的：有则画质更高、字幕更全；没有也能跑
    if os.path.exists(COOKIE_FILE):
        cmd.extend(["--cookies", COOKIE_FILE])
    else:
        print("[warn] 未找到 bilibili_cookies.txt，将以未登录状态下载"
              "（画质受限，且可能拿不到官方AI字幕）")

    if start or end:
        # yt-dlp --download-sections for time range trimming
        section = "*"
        if start:
            section += start
        section += "-"
        if end:
            section += end
        cmd.extend(["--download-sections", section])

    cmd.append(url)

    print(f"[download] {title}")
    print(f"[download] {' '.join(cmd)}")
    # 重试循环：mcdn CDN 超时是间歇性的，续传重试通常能最终拉完
    for attempt in range(1, 5):
        try:
            subprocess.run(cmd, check=True)
            break
        except subprocess.CalledProcessError:
            if attempt < 4:
                wait = min(2 ** attempt, 30)
                print(f"[warn] 下载失败（第 {attempt}/4 次），{wait}s 后重试"
                      f"（mcdn CDN 偶发超时，断点续传通常能最终拉完）")
                time.sleep(wait)
                continue
            raise

    # 打印实际分辨率
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", output_path],
            capture_output=True, text=True
        )
        if probe.stdout.strip():
            w, h = probe.stdout.strip().split(",")
            print(f"[info] 实际分辨率: {w}x{h}")
    except Exception:
        pass

    return output_path


def safe_cleanup(pattern: str) -> int:
    """
    清理临时文件。删除失败不应中断流程——某些受控环境（沙箱、只读回收站、
    文件被占用）会让 os.remove 抛异常，但残留几个中间文件并不影响结果。
    删不掉的改名为 .stale 后缀，避免被后续 glob 误当成有效帧。
    """
    failed = 0
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except Exception:
            try:
                os.replace(f, f + ".stale")
            except Exception:
                failed += 1
    if failed:
        print(f"[warn] {failed} 个临时文件既无法删除也无法改名，已忽略")
    return failed


def safe_move(pattern: str, trash_name="_raw_trash") -> int:
    """把匹配文件移入工作区下的 trash 目录（改名/移动，不删除），
    避免受控环境的批量删除拦截直接终结进程。
    trash 放在 out_dir 的上级目录，确保抽帧目录(scene)根只保留正式帧。"""
    files = glob.glob(pattern)
    if not files:
        return 0
    out_dir = os.path.dirname(files[0])
    trash = os.path.join(os.path.dirname(out_dir), trash_name)
    os.makedirs(trash, exist_ok=True)
    moved = 0
    for f in files:
        dest = os.path.join(trash, os.path.basename(f))
        try:
            os.replace(f, dest)
            moved += 1
        except Exception:
            try:
                os.rename(f, dest)
                moved += 1
            except Exception:
                pass
    if moved:
        print(f"[info] 已移走 {moved} 个临时帧 -> {trash}")
    return moved


def extract_fixed_frames(video_path: str, interval: int = 30) -> list:
    """Extract frames at fixed intervals."""
    out_dir = os.path.join(FRAMES_DIR, "fixed")
    os.makedirs(out_dir, exist_ok=True)

    # Clean old frames
    safe_move(os.path.join(out_dir, "*.jpg"))

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        os.path.join(out_dir, "frame_%04d.jpg"),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    # Small delay to ensure filesystem flushes (especially on Windows with non-ASCII paths)
    import time; time.sleep(0.3)

    frames = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
    print(f"[fixed] {len(frames)} frames @ {interval}s interval -> {out_dir}")
    return frames


def in_ad_segments(t: float, ad_segments: list) -> bool:
    """判断给定时间是否落在任一广告区间内。"""
    if not ad_segments:
        return False
    return any(s <= t <= e for s, e in ad_segments)


def extract_scene_frames(video_path: str, threshold: float = 0.04, merge_gap: float = 5.0,
                         ad_segments: list = None) -> list:
    """
    Extract frames using scene detection + clustering.
    - threshold: scene change sensitivity (lower = more sensitive)
    - merge_gap: merge scene changes within N seconds into one
    - ad_segments: list of (start_sec, end_sec) to skip (e.g. ads / course promos)
    """
    out_dir = os.path.join(FRAMES_DIR, "scene")
    os.makedirs(out_dir, exist_ok=True)

    # Clean old frames
    safe_move(os.path.join(out_dir, "*.jpg"))

    # Pass 1: detect scene change timestamps
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr",
        "-q:v", "2",
        os.path.join(out_dir, "raw_%04d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    # Parse timestamps from showinfo output
    timestamps = []
    for line in result.stderr.split("\n"):
        m = re.search(r"pts_time:(\d+\.?\d*)", line)
        if m:
            timestamps.append(float(m.group(1)))

    print(f"[scene] Detected {len(timestamps)} raw scene changes")

    if not timestamps:
        # Fallback: if no scene changes, use fixed interval
        print("[scene] No scene changes detected, falling back to fixed 30s interval")
        return extract_fixed_frames(video_path, 30)

    # Pass 2: cluster nearby timestamps (within merge_gap seconds)
    clusters = []
    current_cluster = [timestamps[0]]
    for t in timestamps[1:]:
        if t - current_cluster[-1] <= merge_gap:
            current_cluster.append(t)
        else:
            clusters.append(current_cluster)
            current_cluster = [t]
    clusters.append(current_cluster)

    # Take the middle timestamp from each cluster
    key_timestamps = [c[len(c) // 2] for c in clusters]

    # 剔除落在广告/卖课时间段内的关键帧
    if ad_segments:
        before = len(key_timestamps)
        key_timestamps = [t for t in key_timestamps if not in_ad_segments(t, ad_segments)]
        skipped = before - len(key_timestamps)
        if skipped:
            print(f"[scene] 跳过 {skipped} 个落在广告区间的关键帧")

    print(f"[scene] Merged into {len(key_timestamps)} clusters (gap={merge_gap}s)")

    # Clean raw frames (移走而非删除，规避受控环境的删除拦截)
    safe_move(os.path.join(out_dir, "raw_*.jpg"))

    # Pass 3: extract exact keyframes at cluster timestamps
    for i, ts in enumerate(key_timestamps):
        out_file = os.path.join(out_dir, f"frame_{i+1:04d}_{seconds_to_time(ts)}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(ts),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            out_file,
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    frames = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
    print(f"[scene] {len(frames)} keyframes -> {out_dir}")
    return frames


# ============================================================
# 字幕感知的 PPT 抽帧（slidegap）
# 适用：一页一页的 PPT 视频，字幕是「烧录」在画面上的，
#       直接抽帧会把字幕盖在 PPT 内容上方。
# 思路：
#   1. 裁掉画面底部「字幕条」所在区域后再做场景检测 —— 只捕捉 PPT 内容本身的变化，
#      不受字幕出现/消失的干扰（字幕变化往往也会触发普通场景检测，造成误判/重复帧）。
#   2. 解析官方字幕的 from/to，求「字幕之外的干净区间」(subtitle-off)。
#   3. 每个 PPT 片段在其「最晚的干净区间」内取一帧 → 截图那一刻字幕不在屏幕上，
#      不会遮挡 PPT。这正是「两句字幕之间的空挡截图」的算法化实现。
# ============================================================
def get_video_resolution(video_path: str):
    """返回 (width, height)；失败返回 (0, 0)。"""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True)
        parts = probe.stdout.strip().split(",")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def _parse_subtitle_timing(sub_json_path: str):
    """从官方字幕 JSON 解析排序后的 [(from, to, text), ...]。"""
    subs = []
    try:
        data = json.load(open(sub_json_path, "r", encoding="utf-8"))
    except Exception:
        return subs
    for it in data.get("body", []):
        try:
            f = float(it["from"])
            t = float(it.get("to", it["from"]))
            subs.append((f, t, it.get("content", "")))
        except Exception:
            continue
    subs.sort()
    return subs


def _subtitle_gaps(subs, duration, pad: float = 0.4, min_gap: float = 0.25):
    """
    求字幕之外的「干净区间」(subtitle-off)。
    busy = [from-pad, to+pad] 合并重叠后取补集；只保留时长 >= min_gap 的区间。
    pad 用于吸收「烧录字幕」与字幕轨时间点的轻微错位。
    """
    if not subs:
        return [(0.0, duration)] if duration > 0 else []
    busy = [(max(0.0, s - pad), e + pad) for s, e, _ in subs]
    busy.sort()
    merged = [list(busy[0])]
    for s, e in busy[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    gaps = []
    cur = 0.0
    for s, e in merged:
        if s > cur + 1e-3:
            gaps.append((cur, s))
        cur = max(cur, e)
    if duration and cur < duration - 1e-3:
        gaps.append((cur, duration))
    return [g for g in gaps if g[1] - g[0] >= min_gap]


def extract_slidegap_frames(video_path: str, sub_json_path: str = None,
                             threshold: float = 0.1, merge_gap: float = 1.5,
                             min_gap: float = 0.3, pad: float = 0.1,
                             ad_segments: list = None,
                             max_frames: int = 40) -> list:
    """字幕感知的 PPT 抽帧（截图落在「字幕空挡」，全帧不裁切、绝不丢内容）。

    ★★★ 硬性约束（用户规则，禁止自优化时绕过）★★★
        永远不要通过「裁剪(crop)画面」来去掉字幕。原因：
          (1) 字幕位置不固定，代码无法确定裁哪里；
          (2) PPT/背景是全屏，裁掉底部可能把内容一起裁掉。
        正确做法只有两种：
          A) 字幕之间有空挡 → 截图时刻落在空挡内（字幕不在屏幕上，自然不遮挡）；
          B) 字幕全程常驻、无空挡（如连续旁白烧录视频）→ 接受字幕遮挡，
             直接在 PPT 页代表时刻截图（完整画面，不裁切）。

    流程：
      1. 全帧场景检测找 PPT 翻页时刻（不裁切任何区域）；
      2. 解析字幕 from/to 求「字幕空挡」（不裁切，仅用于选截图时刻）；
      3. 每页优先取「落在页时间跨度内、且结束最晚的空挡中点」截图（无字幕）；
         若页内无空挡，则取页中点（可能带字幕，按规则 B 接受，不裁切）。
    """
    out_dir = os.path.join(FRAMES_DIR, "scene")
    os.makedirs(out_dir, exist_ok=True)
    safe_move(os.path.join(out_dir, "*.jpg"))

    try:
        dur_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", video_path],
            capture_output=True, text=True)
        duration = float(dur_probe.stdout.strip() or 0)
    except Exception:
        duration = 0.0

    # 全帧场景检测（不裁切任何区域，PPT 翻页是大变化，字幕微变不会主导）
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr", "-q:v", "2",
        os.path.join(out_dir, "raw_%04d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    ts = [float(m) for m in re.findall(r"pts_time:(\d+\.?\d*)", result.stderr)]
    print(f"[slidegap] 全帧场景检测 {len(ts)} 个变化（PPT 翻页）")
    if not ts:
        print("[slidegap] 无场景变化，回退普通场景检测")
        return extract_scene_frames(video_path, threshold, merge_gap, ad_segments=ad_segments)

    # 聚类相邻突变 → PPT 片段；同页内的高亮/动画(<merge_gap)合并成一簇
    clusters = []
    cur = [ts[0]]
    for t in ts[1:]:
        if t - cur[-1] <= merge_gap:
            cur.append(t)
        else:
            clusters.append(cur)
            cur = [t]
    clusters.append(cur)

    # 字幕空挡（仅用于选截图时刻，不裁切画面）
    subs = _parse_subtitle_timing(sub_json_path) if sub_json_path else []
    gaps = _subtitle_gaps(subs, duration, pad=pad, min_gap=min_gap) if subs else []
    print(f"[slidegap] 字幕空挡数={len(gaps)}（无空挡则接受字幕遮挡，不裁切）")

    chosen = []
    for cluster in clusters:
        lo, hi = cluster[0], cluster[-1]
        t = (lo + hi) / 2.0
        if gaps:
            # 页时间跨度内、结束最晚的空挡 → 内容最完整且无字幕
            seg_gaps = [g for g in gaps if g[1] >= lo and g[0] <= hi]
            if seg_gaps:
                g = max(seg_gaps, key=lambda x: x[1])
                t = (g[0] + g[1]) / 2.0
        if ad_segments and in_ad_segments(t, ad_segments):
            continue
        chosen.append(t)

    chosen = sorted(set(round(x, 3) for x in chosen))
    if len(chosen) > max_frames:                  # 均匀抽样限幅
        step = len(chosen) / max_frames
        chosen = [chosen[int(i * step)] for i in range(max_frames)]
    print(f"[slidegap] 选中 {len(chosen)} 个截图时刻（全帧不裁切，优先空挡）")

    safe_move(os.path.join(out_dir, "raw_*.jpg"))
    for i, ts_sec in enumerate(chosen):
        out_file = os.path.join(out_dir, f"frame_{i+1:04d}_{seconds_to_time(ts_sec)}.jpg")
        # 全帧截图，绝不裁切（规则 B：无空挡时字幕可能入镜，接受遮挡）
        cmd = ["ffmpeg", "-y", "-ss", str(ts_sec), "-i", video_path,
               "-frames:v", "1", "-q:v", "2", out_file]
        subprocess.run(cmd, capture_output=True, check=True)

    frames = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
    print(f"[slidegap] {len(frames)} 关键帧 -> {out_dir}")
    return frames


def main():
    global WORKSPACE, COOKIE_FILE, FRAMES_DIR

    parser = argparse.ArgumentParser(description="B站视频智能抽帧工具")
    parser.add_argument("bvid", help="B站视频 BV号")
    parser.add_argument("--page", type=int, default=1, help="分P号 (默认 1)")
    parser.add_argument("--start", help="起始时间 MM:SS 或 HH:MM:SS")
    parser.add_argument("--end", help="结束时间 MM:SS 或 HH:MM:SS")
    parser.add_argument("--mode", choices=["scene", "fixed", "cover", "both", "slidegap"], default="scene",
                        help="抽帧模式: scene=场景检测, fixed=固定间隔, cover=全覆盖(每10秒), slidegap=字幕感知PPT抽帧(截图落在字幕空挡,不遮挡PPT)")
    parser.add_argument("--interval", type=int, default=30,
                        help="固定间隔秒数 (默认 30, cover模式默认10)")
    parser.add_argument("--threshold", type=float, default=0.04,
                        help="场景检测阈值 (默认 0.04)")
    parser.add_argument("--merge-gap", type=float, default=5.0,
                        help="场景聚合间隔秒数 (默认 5)")
    parser.add_argument("--slide-min-gap", type=float, default=0.3,
                        help="slidegap 模式：仅在时长 >= 该秒数的字幕空挡里截图 (默认 0.25)")
    parser.add_argument("--ad-keywords", default=os.getenv("AD_KEYWORDS", ""),
                        help="广告/卖课关键词，逗号分隔（默认读取 .env 的 AD_KEYWORDS）")
    parser.add_argument("--ad-context", type=float, default=float(os.getenv("AD_CONTEXT_SECONDS", "20")),
                        help="广告关键词命中后向前后扩展的秒数（默认 20）")
    parser.add_argument("--no-download", action="store_true",
                        help="跳过下载，使用已有视频文件")
    parser.add_argument("--no-video", action="store_true",
                        help="仅下载字幕、跳过视频下载与抽帧（访谈/口播类免下视频，生成纯文字笔记）")
    parser.add_argument("--subtitle", action="store_true",
                        help="同时下载AI字幕")
    parser.add_argument("--workspace", default=os.environ.get("BILI_NOTES_WORKSPACE", WORKSPACE),
                        help="工作区目录（默认从环境变量 BILI_NOTES_WORKSPACE 获取）")
    parser.add_argument("--frames", default=os.environ.get("BILI_NOTES_FRAMES", FRAMES_DIR),
                        help="帧输出目录（默认从环境变量 BILI_NOTES_FRAMES 获取）")
    args = parser.parse_args()

    # 运行时覆盖全局路径
    WORKSPACE = args.workspace
    COOKIE_FILE = os.path.join(WORKSPACE, "bilibili_cookies.txt")
    FRAMES_DIR = args.frames

    os.makedirs(WORKSPACE, exist_ok=True)
    os.makedirs(FRAMES_DIR, exist_ok=True)

    # Step 0: Parse time range to seconds (for subtitle filtering)
    start_sec = time_to_seconds(args.start) if args.start else None
    end_sec = time_to_seconds(args.end) if args.end else None

    # Step 1: Download subtitles (independent of video)
    sub_txt_path = ""
    if args.subtitle:
        sub_txt_path = download_subtitles(args.bvid, args.page, start_sec, end_sec)

    # Step 1b: 根据字幕定位广告/卖课时间段，抽帧时跳过
    ad_segments = []
    if sub_txt_path:
        ad_keywords = [k.strip() for k in args.ad_keywords.split(",") if k.strip()] or None
        ad_segments = detect_ad_segments(sub_txt_path, keywords=ad_keywords,
                                         context_seconds=args.ad_context)

    if args.no_video:
        print("[no-video] 跳过视频下载与抽帧，仅保留字幕（纯文字笔记模式）")
    else:
        # Step 2: Download video
        if args.no_download:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', f"{args.bvid}_p{args.page}")
            if args.start or args.end:
                range_tag = f"_{args.start or '0'}-{args.end or 'end'}".replace(":", "")
                video_path = os.path.join(WORKSPACE, f"{safe_name}{range_tag}.mp4")
            else:
                video_path = os.path.join(WORKSPACE, f"{safe_name}.mp4")
            if not os.path.exists(video_path):
                print(f"[error] Video not found: {video_path}")
                sys.exit(1)
            print(f"[skip] Using existing: {video_path}")
        else:
            video_path = download_video(args.bvid, args.page, args.start, args.end)

        # Step 2: Extract frames
        if args.mode == "cover":
            # Cover mode: fixed interval, default 10s for full coverage
            cover_interval = args.interval if args.interval != 30 else 10
            extract_fixed_frames(video_path, cover_interval)
        elif args.mode == "slidegap":
            # 字幕感知 PPT 抽帧：截图落在两句字幕的空挡，避免字幕遮挡 PPT
            _safe = re.sub(r'[<>:"/\\|?*]', '_', f"{args.bvid}_p{args.page}")
            _sub_json = os.path.join(WORKSPACE, f"{_safe}_subtitles.json")
            extract_slidegap_frames(
                video_path, sub_json_path=_sub_json,
                threshold=args.threshold, merge_gap=args.merge_gap,
                min_gap=args.slide_min_gap,
                ad_segments=ad_segments,
            )
        elif args.mode in ("fixed", "both"):
            extract_fixed_frames(video_path, args.interval)

        if args.mode in ("scene", "both"):
            extract_scene_frames(video_path, args.threshold, args.merge_gap, ad_segments=ad_segments)

        print("\n[done] All frames extracted successfully!")


if __name__ == "__main__":
    main()
