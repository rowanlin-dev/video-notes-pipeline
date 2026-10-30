#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书笔记页 → 视频下载 + 元数据提取
=====================================
同一个笔记页 HTML 里嵌有 `window.__INITIAL_STATE__`，其中包含作品标题、正文、
作者、互动数据和视频流地址，无需登录签名接口即可解析（参考 XHS-Downloader 的
HTML 解析思路，只保留本项目需要的视频下载部分）。

用法：
  python scripts/xhs_download.py --url "https://www.xiaohongshu.com/explore/<id>?xsec_token=..."
  python scripts/xhs_download.py --url "https://xhslink.com/xxx" --out-dir runs/xhs_<id>
  python scripts/xhs_download.py --url "<链接>" --cookie-file xiaohongshu_cookies.txt

产物（--out-dir 下）：
  xhs_video.mp4    下载校验后的视频
  xhs_meta.json    标题 / 正文 / 作者 / 标签 / 互动数据 / 时长 / 原始链接

退出码：0 成功；1 失败（图文笔记、需要登录、解析不到视频地址等，均有明确提示）。
"""
import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COOKIE_FILE = ROOT / "xiaohongshu_cookies.txt"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
ACCEPT = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
          "image/avif,image/webp,image/apng,*/*;q=0.8")
REFERER = "https://www.xiaohongshu.com/"

# 作品链接：/explore/<id>、/discovery/item/<id>、/notes/<id>
NOTE_ID_RE = re.compile(r"(?:explore|discovery/item|notes)/([0-9a-zA-Z]+)")
SHORT_RE = re.compile(r"(?:https?://)?xhslink\.(?:com|cn)/[^\s\"'<>]+")


# ---------------------------------------------------------------- 基础工具
def _curl_bin():
    return shutil.which("curl") or shutil.which("curl.exe")


def _resolve_ffprobe():
    """优先完整版 ffmpeg（WinGet Gyan.FFmpeg / C:\\ffmpeg），否则回退 PATH。"""
    for p in (Path("C:/ffmpeg/bin/ffprobe.exe"),):
        if p.exists():
            return str(p)
    pkgs = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        for d in sorted(pkgs.glob("Gyan.FFmpeg_*/ffmpeg-*-full_build/bin"), reverse=True):
            p = d / "ffprobe.exe"
            if p.exists():
                return str(p)
    return shutil.which("ffprobe") or "ffprobe"


def parse_cookie_file(path: Path) -> str:
    """解析 Netscape cookies.txt（浏览器导出格式）或普通 `k=v; k=v` 文本。"""
    if not path or not Path(path).exists():
        return ""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            pairs.append((parts[5].strip(), parts[6].strip()))
        elif "=" in line:
            pairs.append(tuple(x.strip().split("=", 1) for x in line.split(";") if "=" in x)[0])
    return "; ".join(f"{k}={v}" for k, v in pairs if k)


def load_cookie(cookie: str = "", cookie_file: str = "") -> str:
    """命令行 --cookie > --cookie-file > .env XHS_COOKIE > 默认 cookie 文件。"""
    if cookie:
        return cookie.strip()
    if cookie_file and Path(cookie_file).exists():
        return parse_cookie_file(Path(cookie_file))
    env = os.getenv("XHS_COOKIE", "").strip()
    if env:
        return env
    return parse_cookie_file(DEFAULT_COOKIE_FILE)


def _http_get(url: str, cookie: str = "", timeout: int = 30) -> str:
    """抓取页面 HTML：curl（已验证可过小红书风控）→ urllib 兜底。"""
    curl = _curl_bin()
    if curl:
        cmd = [curl, "-sSL", "--http1.1", "-m", str(timeout),
               "-A", UA, "-H", f"accept: {ACCEPT}",
               "-H", "accept-language: zh-CN,zh;q=0.9", "-H", f"referer: {REFERER}"]
        if cookie:
            cmd += ["-H", f"cookie: {cookie}"]
        cmd.append(url)
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode == 0 and r.stdout:
            return r.stdout
    # 兜底：urllib（部分环境无 curl）
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": ACCEPT, "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": REFERER, **({"Cookie": cookie} if cookie else {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def resolve_url(url: str) -> str:
    """xhslink 短链 → 展开为最终 explore 链接。"""
    url = url.strip()
    if not SHORT_RE.search(url):
        return url
    full = url if url.startswith("http") else f"https://{url}"
    curl = _curl_bin()
    if curl:
        r = subprocess.run([curl, "-sSL", "-m", "30", "-A", UA, "-o", os.devnull,
                            "-w", "%{url_effective}", full],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode == 0 and r.stdout.strip().startswith("http"):
            print(f"[xhs] 短链展开：{r.stdout.strip()}")
            return r.stdout.strip()
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(full, headers={"User-Agent": UA}),
                                timeout=30) as resp:
        return resp.geturl()


def extract_note_id(url: str) -> str:
    m = NOTE_ID_RE.search(url)
    if not m:
        raise ValueError(f"无法从小红书链接中解析作品 ID：{url}")
    return m.group(1)


# ---------------------------------------------------------------- 页面解析
def parse_initial_state(html: str) -> dict:
    """提取 window.__INITIAL_STATE__ 的 JSON 对象（括号配对，兼容 undefined）。"""
    m = re.search(r"window\.__INITIAL_STATE__\s*=", html)
    if not m:
        return {}
    start = html.find("{", m.end())
    if start < 0:
        return {}
    depth, in_str, esc = 0, False, False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start:i + 1].replace("undefined", "null")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}
    return {}


def _find_note(state: dict, note_id: str) -> dict:
    detail = ((state.get("note") or {}).get("noteDetailMap") or {})
    for key in (note_id, *detail.keys()):
        note = ((detail.get(key) or {}).get("note") or {})
        if note:
            return note
    return {}


def _stream_items(note: dict) -> list:
    """汇总 media.stream（camelCase）与 mediaV2.stream（snake_case）的视频条目。"""
    items = []

    def add(master, backups, width=0, height=0, bitrate=0, size=0, codec=""):
        if not master:
            return
        master = master.replace("\\u0026", "&").replace("\\/", "/")
        if master.startswith("//"):
            master = "https:" + master
        urls = [master] + [u.replace("\\u0026", "&").replace("\\/", "/") for u in (backups or [])]
        items.append({"urls": list(dict.fromkeys(u for u in urls if u)), "width": width or 0,
                      "height": height or 0, "bitrate": bitrate or 0, "size": size or 0,
                      "codec": codec or ""})

    stream = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
    for _, arr in stream.items():
        for it in (arr or []):
            add(it.get("masterUrl"), it.get("backupUrls"), it.get("width"), it.get("height"),
                it.get("videoBitrate") or it.get("avgBitrate"), it.get("size"))

    media_v2 = (note.get("video") or {}).get("mediaV2")
    if isinstance(media_v2, str):
        try:
            media_v2 = json.loads(media_v2)
        except Exception:
            media_v2 = None
    if isinstance(media_v2, dict):
        for key, arr in (media_v2.get("stream") or {}).items():
            for it in (arr or []):
                add(it.get("master_url"), it.get("backup_urls"), it.get("width"), it.get("height"),
                    it.get("video_bitrate") or it.get("avg_bitrate"), it.get("size"),
                    it.get("video_codec") or key)

    # 兜底：原片 key（画质最高，但体积最大，放最后）
    key = (((note.get("video") or {}).get("consumer") or {}).get("originVideoKey") or "")
    if key:
        add(f"https://sns-video-bd.xhscdn.com/{key}", [])

    # media.stream 与 mediaV2.stream 常含同一组地址，按主地址去重
    seen, unique = set(), []
    for it in items:
        k = it["urls"][0] if it["urls"] else ""
        if k and k not in seen:
            seen.add(k)
            unique.append(it)
    return unique


def _sort_items(items: list, preference: str) -> list:
    if preference == "bitrate":
        key = lambda x: (x["bitrate"], x["height"])
    elif preference == "size":
        key = lambda x: (x["size"], x["height"])
    else:
        key = lambda x: (x["height"], x["bitrate"], x["size"])
    # 原片兜底项没有宽高信息，保持在最后
    known = [i for i in items if i["height"] or i["bitrate"] or i["size"]]
    unknown = [i for i in items if not (i["height"] or i["bitrate"] or i["size"])]
    return sorted(known, key=key, reverse=True) + unknown


def extract_meta(note: dict, note_id: str, url: str) -> dict:
    user = note.get("user") or {}
    video = note.get("video") or {}
    capa = video.get("capa") or {}
    duration = capa.get("duration")
    if not duration:
        media_v2 = video.get("mediaV2")
        if isinstance(media_v2, str):
            try:
                media_v2 = json.loads(media_v2)
            except Exception:
                media_v2 = None
        if isinstance(media_v2, dict):
            duration = ((media_v2.get("video") or {}).get("duration") or 0)
            duration = duration / 1000 if duration and duration > 100000 else duration
    return {
        "note_id": note_id,
        "url": f"https://www.xiaohongshu.com/explore/{note_id}",
        "source_url": url,
        "type": note.get("type") or "",
        "title": (note.get("title") or "").strip(),
        "desc": (note.get("desc") or "").strip(),
        "author": user.get("nickname") or user.get("nickName") or "",
        "author_id": user.get("userId") or "",
        "tags": [t.get("name") for t in (note.get("tagList") or []) if t.get("name")],
        "duration": float(duration or 0),
        "interact": note.get("interactInfo") or {},
        "published_ms": note.get("time"),
    }


# ---------------------------------------------------------------- 下载与校验
def probe_video(path: str) -> dict:
    """ffprobe 校验：是否含视频流 / 音频流 / 时长。失败返回 {}。"""
    ffprobe = _resolve_ffprobe()
    r = subprocess.run([ffprobe, "-v", "error",
                        "-show_entries", "stream=codec_type,codec_name,width,height",
                        "-show_entries", "format=duration,size",
                        "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "has_video": bool(video),
        "has_audio": bool(audio),
        "width": video.get("width", 0),
        "height": video.get("height", 0),
        "duration": float(fmt.get("duration") or 0),
        "size": int(fmt.get("size") or 0),
    }


def download(url: str, out_path: Path, cookie: str = "") -> bool:
    curl = _curl_bin()
    if not curl:
        raise RuntimeError("未找到 curl，无法下载小红书视频")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [curl, "-sS", "-L", "--fail", "--http1.1", "--connect-timeout", "15",
           "--retry", "3", "--retry-delay", "2", "-A", UA, "-e", REFERER,
           "-o", str(out_path), url]
    if cookie:
        cmd[-1:-1] = ["-H", f"cookie: {cookie}"]
    print(f"[xhs] 下载：{url[:120]}...")
    r = subprocess.run(cmd)
    return r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 10240


def fetch(url: str, out_dir: str, cookie: str = "", preference: str = "resolution",
          redownload: bool = False) -> dict:
    """解析笔记并下载视频，返回元数据（含 video_path / probe）。失败抛异常。"""
    url = resolve_url(url)
    note_id = extract_note_id(url)
    html = _http_get(url, cookie=cookie)
    if not html:
        raise RuntimeError("页面抓取失败：网络异常或被小红书风控拦截")

    state = parse_initial_state(html)
    note = _find_note(state, note_id)
    if not note:
        raise RuntimeError(
            "页面中没有笔记数据：可能需要登录 / xsec_token 过期。\n"
            "  处理办法：浏览器登录小红书后导出 Cookie（Netscape 格式）保存为 "
            f"{DEFAULT_COOKIE_FILE}，或在 .env 填 XHS_COOKIE=web_session=...;a1=...")

    meta = extract_meta(note, note_id, url)
    if meta["type"] != "video":
        raise RuntimeError(f"该笔记类型为「{meta['type'] or '图文'}」，不是视频笔记，暂不支持")

    items = _sort_items(_stream_items(note), preference)
    if not items:
        raise RuntimeError("未解析到视频下载地址（可能是付费/受限内容，或页面结构已更新）")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    video_path = out / "xhs_video.mp4"
    probe = {}
    if video_path.exists() and not redownload:
        probe = probe_video(str(video_path))
        if probe.get("has_video") and probe.get("duration", 0) > 0:
            print("[xhs] 已存在校验通过的视频，跳过下载（加 --redownload 可强制重下）")
            meta.update({
                "video_path": str(video_path),
                "width": probe["width"], "height": probe["height"],
                "duration": probe["duration"], "filesize": probe["size"],
            })
            (out / "xhs_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta
    for idx, item in enumerate(items):
        for u in item["urls"]:
            if video_path.exists():
                video_path.unlink()
            if not download(u, video_path, cookie):
                print(f"[xhs] 该地址下载失败，尝试下一备用地址")
                continue
            probe = probe_video(str(video_path))
            if probe.get("has_video") and probe.get("duration", 0) > 0:
                if not probe.get("has_audio"):
                    print("[xhs][warn] 该视频流无音轨（后续 ASR 将无字幕），尝试其他地址")
                    continue
                print(f"[xhs] 下载完成：{probe['width']}x{probe['height']} "
                      f"{probe['duration']:.0f}s {probe['size'] / 1e6:.1f}MB")
                meta.update({
                    "video_path": str(video_path),
                    "width": probe["width"], "height": probe["height"],
                    "duration": probe["duration"], "filesize": probe["size"],
                })
                (out / "xhs_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                return meta
            print("[xhs][warn] 下载文件校验失败，尝试下一地址")
    raise RuntimeError("所有视频地址均下载失败或校验不通过")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="小红书视频下载 + 元数据提取")
    ap.add_argument("--url", required=True, help="小红书笔记链接（explore / discovery / xhslink 短链）")
    ap.add_argument("--out-dir", default="", help="输出目录（默认 runs/xhs_<作品ID>）")
    ap.add_argument("--cookie", default="", help="直接给 cookie 字符串")
    ap.add_argument("--cookie-file", default="", help="Netscape 格式 cookie 文件路径")
    ap.add_argument("--quality", default="resolution", choices=["resolution", "bitrate", "size"],
                    help="清晰度偏好（默认分辨率最高）")
    ap.add_argument("--meta-only", action="store_true", help="只解析作品信息，不下载视频")
    ap.add_argument("--redownload", action="store_true", help="已有视频也强制重新下载")
    args = ap.parse_args()

    cookie = load_cookie(args.cookie, args.cookie_file)
    try:
        url = resolve_url(args.url)
        note_id = extract_note_id(url)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)
    out_dir = args.out_dir or str(ROOT / "runs" / f"xhs_{note_id}")
    if args.meta_only:
        html = _http_get(url, cookie=cookie)
        state = parse_initial_state(html)
        note = _find_note(state, note_id)
        if not note:
            print("[error] 页面中没有笔记数据：可能需要登录或 xsec_token 过期", file=sys.stderr)
            sys.exit(1)
        meta = extract_meta(note, note_id, url)
        items = _sort_items(_stream_items(note), args.quality)
        meta["video_candidates"] = [u for it in items for u in it["urls"]][:5]
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "xhs_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return
    try:
        meta = fetch(args.url, out_dir, cookie=cookie, preference=args.quality,
                     redownload=args.redownload)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    print("[xhs] 作品信息：")
    print(f"  标题：{meta['title'] or '（无标题）'}")
    print(f"  作者：@{meta['author']}   时长：{meta['duration']:.0f}s")
    print(f"  视频：{meta['video_path']}")
    print(f"  元数据：{Path(out_dir) / 'xhs_meta.json'}")


if __name__ == "__main__":
    main()
