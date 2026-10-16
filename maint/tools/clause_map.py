#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重排映射导出：让重排脚本把"自己改了哪些条号"吐出来，供跨文件同步工具消费。

**为什么要有这个**（本轮的设计要点）：
  重排脚本（`renumber-clauses.py` 等）**自己知道**它把哪个条号搬到了哪儿——
  但过去这份知识**随脚本跑完就丢了**，别处文件的引用只能靠**人回忆着抄**，
  于是漏抄、抄错、抄半截。这正是 2026-10-16 那次 27 处漂移的根因。

  "**能算出来的就不要手写**"（铁律 12）——映射既然算得出来，就该**机器传机器**：
  重排脚本 → `--emit-map` 写映射文件 → `sync-clause-refs.py --map-file` 读取并搬引用。

**映射文件格式**（简单文本，一行一条，便于人肉核对与 diff）：
    # 生成者：renumber-clauses.py
    # 说明：全体 +1（第 1—22 条 → 第 2—23 条）
    1=2
    1.1=2.1
    ...
"""
import io
import os

# 映射文件的默认落点（开发侧临时产物，不进 git）
DEFAULT_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "maint", "scratch", ".last-clause-map.txt")


def emit_map(mapping, note, generator, path=None):
    """写出映射文件。

    mapping: {旧号: 新号}，键形如 `7`／`7.4`／`7.4.3`
    note:    一句话说明本次重排做了什么
    generator: 生成者脚本名（便于回溯是哪个重排产生的）
    """
    path = path or DEFAULT_MAP_PATH
    lines = [
        "# 由 %s 生成——请勿手改（重排时自动覆盖）" % generator,
        "# %s" % note,
        "# 用法：python3 maint/tools/sync-clause-refs.py --apply --map-file %s"
        % os.path.relpath(path, os.path.dirname(DEFAULT_MAP_PATH)),
        "",
    ]
    for k in sorted(mapping, key=_num_key):
        lines.append("%s=%s" % (k, mapping[k]))
    io.open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("[map] 已写出重排映射 %d 条 → %s"
          % (len(mapping), os.path.relpath(path)))
    print("[map] 下一步（**必做**，否则别处引用会悬空）："
          "python3 maint/tools/sync-clause-refs.py --apply --map-file %s"
          % os.path.relpath(path))
    return path


def _num_key(s):
    """按数字段排序，让映射表读起来顺（`2` 在 `10` 前）。"""
    return [int(x) for x in s.split(".")]


def parse_map_file(path):
    """读回映射文件 → {旧号: 新号}。供 `sync-clause-refs.py` 使用。"""
    mapping = {}
    for raw in io.open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("映射文件行格式错（须 旧=新）：%r" % line)
        a, b = line.split("=", 1)
        mapping[a.strip()] = b.strip()
    return mapping
