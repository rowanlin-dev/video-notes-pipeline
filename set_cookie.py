#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 B站 cookie 文件（Netscape 格式）
=====================================
yt-dlp 要求的是 Netscape 格式的 cookies.txt（TAB 分隔），手写极易出错。
本工具只需要你提供 SESSDATA 的值。

获取方法：
  浏览器登录 B站 → F12 → Application → Cookies → https://www.bilibili.com
  → 找到 SESSDATA → 复制它的 Value

用法：
  python set_cookie.py <你的SESSDATA值>
  python set_cookie.py            # 不带参数则进入交互输入
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COOKIE = ROOT / "bilibili_cookies.txt"

TEMPLATE = """# Netscape HTTP Cookie File
# 由 set_cookie.py 生成
.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\t{sessdata}
"""


def main():
    if len(sys.argv) > 1:
        sessdata = sys.argv[1].strip()
    else:
        sessdata = input("请粘贴 SESSDATA 的值（F12 → Application → Cookies）：").strip()

    # 容错：用户可能连 "SESSDATA=" 一起粘贴进来
    if sessdata.lower().startswith("sessdata="):
        sessdata = sessdata.split("=", 1)[1].strip()
    sessdata = sessdata.strip('"').strip("'").rstrip(";").strip()

    if not sessdata:
        print("[error] SESSDATA 为空", file=sys.stderr)
        sys.exit(1)
    if len(sessdata) < 20:
        print(f"[warn] SESSDATA 看起来偏短（{len(sessdata)} 字符），请确认没复制错")

    COOKIE.write_text(TEMPLATE.format(sessdata=sessdata), encoding="utf-8", newline="\n")
    print(f"[done] 已写入 {COOKIE}")
    print("[note] SESSDATA 有效期约 1 个月，失效后重新执行本命令即可")


if __name__ == "__main__":
    main()
