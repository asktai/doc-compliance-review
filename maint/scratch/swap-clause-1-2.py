#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""互换铁律第 1 条与第 2 条（效力在前、体例在后）。

**动因**：第 2 条「适用与效力」是规范的**前提**（管不管我、说了算不算），
第 1 条「文档结构与编号」是**体例**（本文件长什么样）。效力先于体例，
法条通例亦然。原次序列颠倒，实为 v1.36.0 迁就"导读区四段找个位置"所致。

**做法**（精确对调，非 +1/-1）：
  1. 条标题：`### 第 1 条 文档结构与编号` ↔ `### 第 2 条 适用与效力`
     （内容块整体对调，标题名跟着走）；
  2. 小节号：第 1 条内 `**1.x` → `**2.x`；第 2 条内 `**2.x` → `**1.x`；
  3. 目录两行对调 + 锚点重生成；
  4. 章区间 `（第 1—2 条）` 不变（两条仍同章）。
**不动**：其余各条、其余引用（经查全文无他处引用第 1／2 条）。

用法：python3 swap-clause-1-2.py <输入> <输出>
"""
import re
import sys


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    lines = open(src, encoding="utf-8").read().splitlines()

    # ── 定位两条标题行与大块边界 ──
    i1 = i2 = None
    for i, l in enumerate(lines):
        if re.match(r"^### 第 1 条 文档结构与编号$", l):
            i1 = i
        elif re.match(r"^### 第 2 条 适用与效力$", l):
            i2 = i
    if i1 is None or i2 is None or i1 > i2:
        print("[E] 未按预期找到第 1／2 条标题")
        return 1

    # 第 1 条块：[i1, i2)  第 2 条块：[i2, 下一条/章末)
    # 第 2 条块结束：下一个 `### ` 或 `## ` 或 `---`
    j = i2 + 1
    while j < len(lines) and not re.match(r"^(### |## |---)", lines[j]):
        j += 1
    blk1 = lines[i1:i2]      # 含标题行
    blk2 = lines[i2:j]       # 含标题行

    # ── 标题对调（名称跟着内容走，故标题整体互换）──
    blk1[0] = "### 第 2 条 文档结构与编号"
    blk2[0] = "### 第 1 条 适用与效力"

    # ── 小节号对调：1.x → 2.x（原第 1 条块），2.x → 1.x（原第 2 条块）──
    def renum(block, frm, to):
        out = []
        for l in block:
            # 行首编号单元 `**K.x ...`
            m = re.match(r"^(\*\*)(\d+)(\.\d+.*)$", l)
            if m and int(m.group(2)) == frm:
                l = "%s%d%s" % (m.group(1), to, m.group(3))
            out.append(l)
        return out

    blk1 = renum(blk1, 1, 2)
    blk2 = renum(blk2, 2, 1)

    # ── 组装：把 [i1, j) 区间替换为 blk2 + blk1 ──
    # blk2 的**尾随空行**要去掉（否则与拼接用的空行重复 → 多一行，实测 877→878）；
    # blk1 的尾随空行要**保留**（它是与后面 `---` 之间的间隔，去了会贴在一起）。
    while blk2 and blk2[-1] == "":
        blk2.pop()
    if not blk1 or blk1[-1] != "":
        blk1.append("")
    new_mid = blk2 + [""] + blk1
    out = lines[:i1] + new_mid + lines[j:]

    # ── 目录两行对调 ──
    for i, l in enumerate(out):
        if "第 1 条 文档结构与编号" in l and l.lstrip().startswith("- ["):
            out[i] = "  - [第 2 条 文档结构与编号](#第-2-条-文档结构与编号)"
        elif "第 2 条 适用与效力" in l and l.lstrip().startswith("- ["):
            # 暂不动，下面统一重排次序
            pass

    # 更稳的做法：找到目录里这两行，直接按新次序重写
    d1 = d2 = None
    for i, l in enumerate(out):
        if re.match(r"^\s*- \[第 [12] 条 文档结构与编号\]", l):
            d1 = i
        elif re.match(r"^\s*- \[第 [12] 条 适用与效力\]", l):
            d2 = i
    if d1 is not None and d2 is not None:
        lo, hi = min(d1, d2), max(d1, d2)
        out[lo] = "  - [第 1 条 适用与效力](#第-1-条-适用与效力)"
        out[hi] = "  - [第 2 条 文档结构与编号](#第-2-条-文档结构与编号)"

    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("[OK] 已写出 %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
