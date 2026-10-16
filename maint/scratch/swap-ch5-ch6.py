#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铁律第五章（版本控制）与第六章（校验）**整章对调 ＋ 条号重排**。

**动因**：校验（怎么验）应排在版本控制（怎么升版）**之前**——
先有验证才谈得上发布，逻辑顺序更顺（2026-10-16 开发者指令）。

**改法**（两章互换成新次序：第五章＝校验、第六章＝版本控制）：

| 章 | 原条号 | 新条号 | 映射 |
|---|---|---|---|
| 校验（升为第五章） | 16—19 | **13—16** | 各 **-3** |
| 版本控制（降为第六章） | 13—15 | **17—19** | 各 **+4** |

**关键**：条号变了，**其下全部小节号与路径引用**也跟着变
（如 `16.1→13.1`、`19.4.7.3→16.4.7.3`），故用**同一个映射**统一处理。

**做法**：整块对调（不逐行搬），再对**全文件**套用条号／路径映射，
章区间与目录两行重写、锚点重算。跑完**自动导出映射**供全库同步。

用法：python3 maint/scratch/swap-ch5-ch6.py <输入> <输出>
"""
import os
import re
import sys

# 两章的原条号区间
CH5_OLD = list(range(13, 16))    # 版本控制 13—15
CH6_OLD = list(range(16, 20))    # 校验     16—19

CH5_TITLE_OLD = "## 第五章 版本控制（第 13—15 条）"
CH6_TITLE_OLD = "## 第六章 校验（第 16—19 条）"
CH5_TITLE_NEW = "## 第五章 校验（第 13—16 条）"
CH6_TITLE_NEW = "## 第六章 版本控制（第 17—19 条）"


def build_mapping():
    """旧条号 → 新条号（含 1—3 级小节路径），供正文改写与全库同步共用。"""
    m = {}
    for n in CH6_OLD:                       # 校验：16—19 → 13—16（-3）
        m[str(n)] = str(n - 3)
        for k in range(1, 13):
            m["%d.%d" % (n, k)] = "%d.%d" % (n - 3, k)
            for j in range(1, 10):
                m["%d.%d.%d" % (n, k, j)] = "%d.%d.%d" % (n - 3, k, j)
    for n in CH5_OLD:                       # 版本控制：13—15 → 17—19（+4）
        m[str(n)] = str(n + 4)
        for k in range(1, 13):
            m["%d.%d" % (n, k)] = "%d.%d" % (n + 4, k)
            for j in range(1, 10):
                m["%d.%d.%d" % (n, k, j)] = "%d.%d.%d" % (n + 4, k, j)
    return m


# 条号／路径在文中的形态：`第 N 条`、行首 `**N.M`、列表 `- **N.M.K`、句中 `N.M.K`
RE_TIAO = re.compile(r"第 (\d+) 条")
# **一次抓满整串路径**，各自再 split——不要拆成多个捕获组。
#   实证事故（2026-10-16）：原写法 `(\d{1,2})\.(\d)((?:\.\d+)*)` 的第 3 组
#   **带前导点**（`.3.1`），与"前面组用点重拼"一叠加，就多出一个点：
#   `16.4.3.1` → 拼出 `13.4..3.1`；再经 `group(0).replace(...)` 二次套用 →
#   `13.4..3.1.3.1`。**两处错叠加**，把 36 处编号改成了四不像，
#   而当时的自检十二维**一处都没抓到**（守卫看不见"编号自身被改坏"）。
#   **教训**：正则分组的"点"归属必须在组内统一（要么都在组内、要么都在连接符），
#   且替换时**直接返回新串**，**不要**拿 `group(0).replace()` 二次套用。
RE_NUM = re.compile(r"(?<![\d.])(?<![vV])(\d{1,2}(?:\.\d+)+)(?![\d.])")

# **章号引用**（正文里"见第 N 章"这类）：两章对调，章号也随之互换。
#   ⚠ 本脚本**只在该两章对调的语境下**互换第五↔第六章——
#   其余章号（一～四、七～九）不动。目录行另由锚点重算处理，不走这里。
RE_CHREF = re.compile(r"第([五六])章")
_CH_SWAP = {"五": "六", "六": "五"}


def _num_key(s):
    return [int(x) for x in s.split(".")]


def apply_map_to_text(line, mapping):
    """把行内所有条号／十进制路径按映射改写（**前缀最长匹配，匹配不上则原样**）。"""
    def _tiao(mm):
        n = mm.group(1)
        return "第 %s 条" % mapping.get(n, n)

    def _num(mm):
        parts = mm.group(1).split(".")
        for cut in range(len(parts), 0, -1):
            old = ".".join(parts[:cut])
            if old in mapping:
                tail = ".".join(parts[cut:])
                # **直接返回新串**——`mm.group(1)` 就是 `old(+.tail)`，不必也不该
                # 再对 `group(0)` 做 `replace`（那会把尾巴重复一遍，见上方事故注）。
                return mapping[old] + (("." + tail) if tail else "")
        return mm.group(0)

    line = RE_TIAO.sub(_tiao, line)
    line = RE_NUM.sub(_num, line)
    # **章号引用**互换（如"见第六章"→"见第五章"）——
    #   条号映射管不到它，须单独处理；否则章引用会指向错章。
    line = RE_CHREF.sub(lambda mm: "第%s章" % _CH_SWAP[mm.group(1)], line)
    return line


def gh_anchor(title):
    """GitHub 锚点：保留字母/数字/CJK/空格/连字符，其余删；空格转 `-`。"""
    keep = []
    for ch in title.strip().lower():
        if ch.isalnum() or ch in " -":
            keep.append(ch)
        elif "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
    return "".join(keep).replace(" ", "-")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    lines = open(src, encoding="utf-8").read().splitlines()

    # ── 定位两章块边界：从各自标题行到下一个 `## ` 章标题之前 ──
    def find_chapter(title):
        try:
            i = next(k for k, l in enumerate(lines) if l == title)
        except StopIteration:
            return None, None
        j = next((k for k in range(i + 1, len(lines))
                  if lines[k].startswith("## ")), len(lines))
        return i, j

    i5, j5 = find_chapter(CH5_TITLE_OLD)
    i6, j6 = find_chapter(CH6_TITLE_OLD)
    if i5 is None or i6 is None or i5 >= i6:
        print("[E] 未按预期找到第五章／第六章（或次序不符），中止")
        return 1

    ch5 = lines[i5:j5]      # 版本控制整块
    ch6 = lines[i6:j6]      # 校验整块
    tail = lines[j6:]

    # ── 1. 块序对调：校验在前、版本控制在后 ──
    new = lines[:i5] + ch6 + ch5 + tail

    # ── 2. 章标题重写（含新区间）──
    new = [CH5_TITLE_NEW if l == CH6_TITLE_OLD else
           CH6_TITLE_NEW if l == CH5_TITLE_OLD else l
           for l in new]

    # ── 3. 全文件套用条号／路径映射 ──
    # **跳过两类行**：
    #   · 目录行（`- [` 开头）——第 4 步专门重写，此处若动会与锚点重建打架；
    #   · **章标题行**（`## ` 开头）——第 2 步已按新次序改写完毕，
    #     而本步的"章号互换"会**再换一次**（五↔六），造成**双重互换**回到原样。
    mapping = build_mapping()
    out = [l if (re.match(r"^\s*- \[", l) or l.startswith("## "))
           else apply_map_to_text(l, mapping)
           for l in new]

    # ── 4. 目录：**按新正文章序与标题整段重建**（不靠数字推算）──
    #
    # **为什么重建而非改数字**：目录行是**正文标题的镜像**——正文怎么排，目录就怎么排。
    # 若在目录行里"把 13 改成 17"式修补，一旦映射写错、或正文与目录本就不同步，
    # 就会**改出一个与正文不符的目录**（且守卫要到交付前才发现）。
    # 直接从**已重排好的正文**里取章标题与条标题重建，目录必然与正文一致。
    #
    # 定位目录块：从第一条 `- [第 1 章…]` 到附录行之前。
    toc_start = next(k for k, l in enumerate(out)
                     if re.match(r"^\s*- \[第一章 ", l))
    toc_end = next(k for k, l in enumerate(out)
                   if re.match(r"^\s*- \[附录 ", l))
    indent_ch = " " * (len(out[toc_start]) - len(out[toc_start].lstrip()))

    # 从正文抽章与条（保持文件次序，即新次序）
    chaps = []      # [(章标题, [条标题, ...]), ...]
    for l in out:
        m = re.match(r"^## (第[一二三四五六七八九]章 .+)$", l)
        if m:
            chaps.append([m.group(1), []])
        m = re.match(r"^### (第 \d+ 条 .+)$", l)
        if m and chaps:
            chaps[-1][1].append(m.group(1))

    rebuilt = []
    for ch_title, tiao_titles in chaps:
        rebuilt.append("%s- [%s](#%s)" % (indent_ch, ch_title, gh_anchor(ch_title)))
        for t in tiao_titles:
            rebuilt.append("%s  - [%s](#%s)" % (indent_ch, t, gh_anchor(t)))

    out = out[:toc_start] + rebuilt + out[toc_end:]

    # ── 5. 自校验：条号连续、章区间与实际条号吻合 ──
    nums = [int(x) for x in re.findall(r"(?m)^### 第 (\d+) 条", "\n".join(out))]
    ok_run = nums == list(range(1, len(nums) + 1))
    print("[i] 条号：%s" % ("1—%d 连续" % len(nums) if ok_run else nums))
    if not ok_run:
        print("[E] 条号不连续，中止")
        return 1

    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("[OK] 已写出 %s" % dst)

    # ── 6. 自动导出映射，供全库引用同步（复用上一轮的链）──
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "tools"))
    try:
        import clause_map
        clause_map.emit_map(mapping,
                            "第五章／第六章对调：校验 16—19→13—16、"
                            "版本控制 13—15→17—19",
                            "swap-ch5-ch6.py")
    except ImportError:
        print("[!] 未能导入 clause_map 工具，映射未导出——**请手动同步别处引用**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
