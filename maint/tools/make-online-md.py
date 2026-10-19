#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成"在线版"Markdown：把目录里的内联锚点链接改成纯文字大纲。

为什么要有它（2026-10-17）
--------------------------------------------------------------------------
铁律目录原用 GitHub 锚点（`- [第 1 条 适用与效力](#第-1-条-适用与效力)`）。
这些锚点在 GitHub 上**实测全部正确**（38 条 38/38），但腾讯文档在线版
**不按 GitHub 规则解析** `#中文标题` 链接——点下去"找不到锚点"。

两处阅读环境规则不同，只能各出一份：
  · **本地版**（`DEV-RULES.md`）：保留 GitHub 锚点，GitHub／VS Code／Typora 可跳转；
  · **在线版**（本脚本产物）：目录改为**纯文字大纲**，不依赖任何阅读器的锚点规则。

为什么不试图"按腾讯文档规则重算锚点"
--------------------------------------------------------------------------
腾讯文档官方文档只说明"支持六级标题"，**未说明 `[文字](#锚点)` 如何解析**。
在没有可复现依据的情况下另写一套算法，等于按猜测造规则（第 3 条：禁脑补）。
纯文字大纲**不依赖规则**：任何阅读器、打印、复制粘贴都成立；条号本身就是定位器
（这正是第 2 条"条号即锚点"的设计意图）。

用法
--------------------------------------------------------------------------
    python3 maint/tools/make-online-md.py                  # 生成在线版到 scratch/
    python3 maint/tools/make-online-md.py --out PATH       # 指定输出路径
    python3 maint/tools/make-online-md.py --stdout          # 打印到标准输出

归属：开发侧工具，不随包分发、不进发布链。
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(DEV, "DEV-RULES.md")
DEFAULT_OUT = os.path.join(DEV, "maint", "scratch", "DEV-RULES.online.md")

# 目录条目：`  - [文字](#锚点)` 或 `- [文字](#锚点)`
RE_TOC_LINK = re.compile(r"^(\s*)- \[([^\]]+)\]\(#[^)]+\)\s*$", re.M)

# 目录说明行：本地版写的是"锚点按 GitHub 规则生成…"，在线版不该这么写。
#
# **2026-10-19 修**：上一版是 `^目录.*锚点.*GitHub.*$`，只吃**单行**。而源文件的说明行
# 早就排成了**两行**（第二行以"由 `…/make-online-md.py` 派生"起头），于是替换只吃掉
# 第一行，第二行原样留下——在线版目录就变成：
#     （新说明）                  ← 第一行
#     由 `…/make-online-md.py` 派生——…   ← 第二行残句
# 读起来像两句不相干的话。根因是**正则假设了"说明行只有一行"**，而这个假设没有任何
# 守卫盯着：改文件版式时它不会报错，只会在产物里默默变形。
# 现在改成"从 `目录（` 起头，整段连续非空行全部吃掉"，并**断言只吃到一个连续块**——
# 若哪天目录前又插了别的以"目录（"起头的段落，这里会直接报错，而不是悄悄吞错行。
RE_TOC_NOTE = re.compile(r"^目录（[^\n]*(?:\n(?!\n)[^\n]*)*", re.M)
ONLINE_TOC_NOTE = "目录（在线版无锚点跳转，按条号定位；本地 Markdown 版保留可点击目录）"


def convert(text: str):
    """返回 (转换后文本, 转换条目数, 说明行替换情况)。

    说明行替换情况取值：
      · ``"ok"``      —— 正好匹配到一段、已整段替换；
      · ``"none"``    —— 没匹配到（版式变了，须人工确认）；
      · ``"multi:N"`` —— 匹配到 N 段（>1，说明有多处以"目录（"起头的段落，已全部替换但可疑）。
    """
    n = [0]

    def repl(m):
        indent, label = m.group(1), m.group(2)
        n[0] += 1
        return "%s- %s" % (indent, label)

    out = RE_TOC_LINK.sub(repl, text)

    hits = RE_TOC_NOTE.findall(out)
    if not hits:
        note = "none"
    else:
        out = RE_TOC_NOTE.sub(ONLINE_TOC_NOTE, out)
        note = "ok" if len(hits) == 1 else "multi:%d" % len(hits)

    return out, n[0], note


def main():
    ap = argparse.ArgumentParser(description="把铁律目录改成纯文字大纲（在线版）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出路径")
    ap.add_argument("--stdout", action="store_true", help="打印到标准输出，不落盘")
    ap.add_argument("--src", default=SRC, help="源文件（默认 dev/DEV-RULES.md）")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print("[E] 源文件不存在：%s" % a.src)
        return 1

    src_text = open(a.src, encoding="utf-8").read()
    out, count, note = convert(src_text)

    NOTES = {
        "ok": "是（整段替换为单行）",
        "none": "**否**（未匹配到说明行，请人工确认）",
    }
    note_msg = NOTES.get(note, "**多段**（匹配到 %s 处" % note.split(":", 1)[-1]
                         + "以「目录（」起头的段落，已全部替换，请人工确认）")

    if a.stdout:
        sys.stderr.write("目录说明行改写：%s\n" % note_msg)
        sys.stdout.write(out)
        return 0

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(out)

    # 打印摘要，顺带做断言（防止"转换没生效却静默通过"）
    print("源：%s" % os.path.relpath(a.src, DEV))
    print("出：%s" % os.path.relpath(a.out, DEV))
    print("目录条目去链接：%d 条" % count)
    print("目录说明行改写：%s" % note_msg)

    resid = re.findall(r"^\s*- \[[^\]]+\]\(#", out, re.M)
    if resid:
        print("[E] 转换后仍有 %d 条锚点链接残留" % len(resid))
        return 1
    if count == 0:
        print("[E] 一条都没转换——源文件目录形态可能已变，转换规则失效")
        return 1
    # 说明行是"整段替换"，若匹配到多段，说明目录区混进了别的段落——宁可报错，不静默吞掉
    if note.startswith("multi"):
        print("[E] 目录说明行匹配到 %s 段——说明区版式异常，拒绝产出" % note.split(":", 1)[-1])
        return 1
    print("校验：转换后零锚点链接残留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
