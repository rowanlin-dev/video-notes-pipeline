#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把笔记里的本地视频时间戳转换为 B 站线上视频可点击链接。

支持三种格式（时间支持 MM:SS 或 HH:MM:SS）：
  1. 图注单点： *xxx [MM:SS]*            -> *xxx [MM:SS](链接?p=N&t=秒)*
  2. 标题区间： ## 一、xxx（00:00 - 05:30）   -> （[00:00 - 05:30](链接?p=N&t=起点秒)）
               ### xxx [00:00-06:19]      -> [00:00-06:19](链接?p=N&t=起点秒)
  3. 时间节点行： **时间节点：00:00-04:00**   -> **时间节点：[00:00-04:00](链接?p=N&t=起点秒)**
  4. 表格时间段： | 00:00-06:19 | 模块 | ...   -> | [00:00-06:19](链接?p=N&t=起点秒) | ...

用法：
  python scripts/fix_bili_timestamps.py <file.md> <p编号> [<file.md> <p编号> ...]
  python scripts/fix_bili_timestamps.py <file.md> <p编号> --bvid BV1xxxx
已转换（后面带链接）的时间戳不会被重复处理。
"""
import re
import sys

DEFAULT_BV = "BV1fGwqzdES5"
URL = "https://www.bilibili.com/video/{bvid}/?p={p}&t={sec}"


def ts_to_sec(s: str) -> int:
    parts = [int(x) for x in s.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def convert(text: str, p: int, bvid: str = DEFAULT_BV) -> tuple[str, dict]:
    stats = {"bracket_range": 0, "paren_range": 0, "point": 0, "time_node": 0, "table": 0}

    # 时间格式：MM:SS 或 HH:MM:SS
    TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}"
    RANGE = rf"({TS})\s*([-–—])\s*({TS})"

    # 模式1：全角括号区间 （00:00 - 05:30）
    def b1(m):
        inner = m.group(0)[1:-1]  # 去掉首尾全角括号，保留原文显示
        start = m.group(1)
        stats["paren_range"] += 1
        return f"（[{inner}]({URL.format(bvid=bvid, p=p, sec=ts_to_sec(start))})）"

    text = re.sub(rf"（{RANGE}）", b1, text)

    # 模式2：方括号区间 [00:00-06:19]，后不跟 ( 表示未转换
    def b2(m):
        inner = m.group(0)[1:-1]
        start = m.group(1)
        stats["bracket_range"] += 1
        return f"[{inner}]({URL.format(bvid=bvid, p=p, sec=ts_to_sec(start))})"

    text = re.sub(rf"\[{RANGE}\](?!\()", b2, text)

    # 模式3：图注单点 [MM:SS]
    def a1(m):
        t = m.group(1)
        stats["point"] += 1
        return f"[{t}]({URL.format(bvid=bvid, p=p, sec=ts_to_sec(t))})"

    text = re.sub(rf"\[({TS})\](?!\()", a1, text)

    # 模式4：**时间节点：00:00-04:00**
    def n1(m):
        inner = m.group(1)
        start = m.group(2)
        stats["time_node"] += 1
        return f"**时间节点：[{inner}]({URL.format(bvid=bvid, p=p, sec=ts_to_sec(start))})**"

    text = re.sub(rf"\*\*时间节点[：:]\s*({RANGE})\s*\*\*", n1, text)

    # 模式5：表格行首时间段 | 00:00-06:19 |
    def t1(m):
        inner = m.group(1)
        start = m.group(2)
        stats["table"] += 1
        return f"| [{inner}]({URL.format(bvid=bvid, p=p, sec=ts_to_sec(start))})"

    text = re.sub(rf"^\|\s*({RANGE})\s*\|", t1, text, flags=re.M)

    return text, stats


def main():
    args = sys.argv[1:]
    bvid = DEFAULT_BV
    if "--bvid" in args:
        i = args.index("--bvid")
        bvid = args[i + 1]
        del args[i:i + 2]
    if not args or len(args) % 2 != 0:
        print(__doc__)
        sys.exit(1)
    total = {"bracket_range": 0, "paren_range": 0, "point": 0, "time_node": 0, "table": 0}
    for i in range(0, len(args), 2):
        path, p = args[i], int(args[i + 1])
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new_text, stats = convert(text, p, bvid)
        for k in total:
            total[k] += stats[k]
        if new_text != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"[ok] {path} (p={p})  区间[]:{stats['bracket_range']} "
                  f"区间()：{stats['paren_range']} 单点:{stats['point']} "
                  f"时间节点:{stats['time_node']} 表格:{stats['table']}")
        else:
            print(f"[--] {path} (p={p})  无变化")
    print(f"\n合计：区间[] {total['bracket_range']}，区间() {total['paren_range']}，单点 {total['point']}，"
          f"时间节点 {total['time_node']}，表格 {total['table']}")


if __name__ == "__main__":
    main()
