#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lite-selfcheck.py —— 只验 DEV-RULES-LITE.md 自身是否自洽。

刻意**不**复用完整版的 check-dev-rules.py：
完整版按本项目的条款写死（要 24 条、要附录 A 的术语表、要 24.3 落实总表），
拿它来跑 Lite 版会把"有意删掉的章"全报成缺陷——那验的是错的东西。
本脚本只查四项**任何同类文档都该成立**的事：
  (L1) 条号连续、款号连续
  (L2) 文档内引用的条号／款号真实存在（不得悬空）
  (L3) 表格列数一致（Markdown 表格不残缺）
  (L4) 无项目专有名词残留（可移植性的硬指标）
用法：python3 lite-selfcheck.py <文件路径>
"""
import re
import sys

# (L4) 项目专有名词清单——出现即为"没抽干净"
# ⚠ 按**整词**匹配，不用裸 `in`：写 `lite-selfcheck.py` 时若按子串判，
#   会命中 `check.py` 而误报（实测踩过：本文件自己的脚本名把自己拦下）。
PROPER = [
    "doc-compliance-review", "samples-manifest", "pack.py", "check.py",
    "check-separation.py", "check-dev-rules.py", "smoke-dev-rules.py",
    "DEVLOG", "CHANGELOG", "技能本体", "运行实例侧", "随包副本",
    "maint/", "samples/", "publish.py",
]
# 允许出现的完整词自身例外：本文件自带的检查器名 ＋ 通用占位名。
# `DEVLOG.md` 是 8.3 给"开发者未指定前"的**通用默认名**，不是原项目残留——
# 原项目的开发日志也叫这名，但那是因为它本来就是个通用名。按 (L4) 的判据
# （"换个项目还成立吗"），它成立，故豁免。
ALLOW = {"lite-selfcheck.py", "DEVLOG.md"}

errs = []
def err(m):
    errs.append(m)

def in_fence(lines):
    """返回代码块内的行号集合（1-based）。"""
    out, inside = set(), False
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("```"):
            inside = not inside
            out.add(i)
            continue
        if inside:
            out.add(i)
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "DEV-RULES-LITE.md"
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read()
    except FileNotFoundError:
        print("守卫失效：规范文件不存在（%s）" % path)
        return 2
    lines = s.splitlines()
    fenced = in_fence(lines)

    # 维度总表：结论行与"共几项"都由它派生，加维度只改这里
    CHECKS = [
        (1, "条号与款号连续性"), (2, "引用不悬空"), (3, "表格完整性"),
        (4, "专有名词残留"), (5, "绝对路径残留"),
        (6, "目录与正文标题一致"),
    ]

    # ---------- (L1) 条号连续 ----------
    print("(L1) 条号与款号连续性")
    arts = []
    for l in lines:
        m = re.match(r"^## 第 (\d+) 条", l)
        if m:
            arts.append(int(m.group(1)))
    if not arts:
        err("(L1) 一条都没找到——守卫失效")
    else:
        if arts != list(range(1, len(arts) + 1)):
            err("(L1) 条号不连续或跳号：%s" % arts)
        else:
            print("      条号连续：1—%d，共 %d 条" % (len(arts), len(arts)))

    # 款号：每条的 x.y 是否从 1 连续
    cur, seen = None, {}
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        m = re.match(r"^## 第 (\d+) 条", l)
        if m:
            cur = m.group(1)
            seen[cur] = []
            continue
        if cur is None:
            continue
        # 款号只认加粗形态 **x.y 或表格首列
        for mm in re.finditer(r"\*\*(\d+)\.(\d+)(?![\.\d])", l):
            if mm.group(1) != cur:
                continue
            seen[cur].append(int(mm.group(2)))
    bad_sub = []
    for a, lst in seen.items():
        uniq = sorted(set(lst))
        if not uniq:
            continue
        if uniq != list(range(1, len(uniq) + 1)):
            bad_sub.append("第 %s 条：%s" % (a, uniq))
    if bad_sub:
        err("(L1) 款号不连续：%s" % "；".join(bad_sub))
    else:
        print("      款号连续：全部条的 x.y 均自 1 起、不跳号")

    # ---------- (L2) 引用不悬空 ----------
    print("(L2) 文档内条号／款号引用是否悬空")
    defined = set()
    for l in lines:
        for m in re.finditer(r"\*\*((?:\d+)(?:\.\d+)+)\s*[^\d.]", l):
            defined.add(m.group(1))
    for a in arts:
        defined.add(str(a))

    VER = re.compile(r"(?<![\d.])(?:v)?\d+\.\d+\.\d+(?![\d.])")
    bad = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        scan = VER.sub(lambda m: " " * len(m.group(0)), l)
        scan = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), scan)
        for m in re.finditer(r"第\s*(\d+(?:\.\d+)*)\s*[条款]", scan):
            ref = m.group(1)
            if ref in defined or any(d.startswith(ref + ".") for d in defined):
                continue
            bad.append("第 %d 行「%s」" % (i, m.group(0)))
        for m in re.finditer(r"(?<![\d.])(\d+\.\d+(?:\.\d+)*)(?![\d.])", scan):
            ref = m.group(1)
            if ref in defined or any(d.startswith(ref + ".") for d in defined):
                continue
            bad.append("第 %d 行「%s」" % (i, ref))
    if bad:
        err("(L2) 悬空引用：%s" % "；".join(bad[:12]))
    else:
        print("      无悬空引用（比对基准：%d 个已定义的条／款号）" % len(defined))

    # ---------- (L3) 表格完整性 ----------
    print("(L3) Markdown 表格列数一致性")
    tbl_bad, i, n = [], 0, len(lines)
    while i < n:
        if (i + 1) in fenced or i + 1 in fenced:
            i += 1
            continue
        l = lines[i]
        if l.strip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            cols = len(l.strip().strip("|").split("|"))
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                if j + 1 in fenced:
                    break
                c = len(lines[j].strip().strip("|").split("|"))
                if c != cols:
                    tbl_bad.append("第 %d 行 %d 列（表头 %d 列）" % (j + 1, c, cols))
                j += 1
            i = j
            continue
        i += 1
    if tbl_bad:
        err("(L3) 表格列数不一致：%s" % "；".join(tbl_bad))
    else:
        print("      全部表格列数一致")

    # ---------- (L4) 专有名词残留 ----------
    print("(L4) 项目专有名词残留")
    hit = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        scan = l
        for a in ALLOW:
            scan = scan.replace(a, " " * len(a))
        for w in PROPER:
            # 整词：前不接字母数字与 . - _，后不接字母数字 . - _（防 check.py 命中 lite-selfcheck.py）
            pat = r"(?<![\w.\-])" + re.escape(w) + r"(?![\w\-])"
            if re.search(pat, scan):
                hit.append("第 %d 行「%s」" % (i, w))
    if hit:
        err("(L4) 专有名词残留：%s" % "；".join(hit[:12]))
    else:
        print("      零残留")

    # ---------- (L5) 绝对路径残留 ----------
    # ⚠ 2026-10-20 全量质检补：原 (L4) 只查专有名词，**不查路径**——
    #   于是 `/tmp/litetest`、`dev/DEV-RULES.md` 这类"某个具体项目的绝对路径"
    #   一路放行，文档自称"零残留"却带着作者本机的痕迹（复核者丙实测指出）。
    #   判据：绝对路径（以 / 开头且不是 URL）**一律视为项目残留**——
    #   通用文档里不该出现任何人的本机路径。
    print("(L5) 绝对路径残留（作者本机痕迹）")
    pbad = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        for m in re.finditer(r"(?<![\w:/])/(?:tmp|home|root|Users|var|opt|workspace)/[\w\-./]*", l):
            pbad.append("第 %d 行「%s」" % (i, m.group(0)))
    if pbad:
        err("(L5) 绝对路径残留：%s" % "；".join(pbad[:12]))
    else:
        print("      无绝对路径残留")

    # ---------- (L6) 目录与正文标题一致 ----------
    # ⚠ 2026-10-20 全量质检补：原检查**不查目录**——于是新加一节忘了补目录，
    #   六项全过（实测踩过：补「本文件版本沿革」后目录漏项，检查一声不吭）。
    #   判据：文中每个二级标题（## ）都须在目录里有对应条目，且目录条目都指向真实标题。
    print("(L6) 目录与正文标题一致")
    heads = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        m = re.match(r"^## (.+?)\s*$", l)
        if m and m.group(1).strip() != "目录":
            heads.append(m.group(1).strip())
    toc = []
    for l in lines:
        for m in re.finditer(r"^- \[(.+?)\]\(#(.+?)\)\s*$", l):
            toc.append(m.group(1).strip())
    miss = [h for h in heads if h not in toc]
    ghost = [t for t in toc if t not in heads]
    if miss:
        err("(L6) 正文有标题但目录漏项：%s" % "；".join(miss))
    if ghost:
        err("(L6) 目录有条目但正文无此标题：%s" % "；".join(ghost))
    if not miss and not ghost:
        print("      目录与正文一致（%d 个标题）" % len(heads))

    print()
    if errs:
        print("自洽检查未通过，%d 项：" % len(errs))
        for e in errs:
            print("  - " + e)
        return 1
    # ⚠ 数字从 CHECKS 派生，不手写——本行原写死"四项"，
    #   加 (L5) 后就变成了谎报（12.3.4 说的正是这种事，本条自己先犯了一次）。
    dims = "".join("(L%d)" % n for n, _ in CHECKS)
    print("自洽检查通过：%s %s项全过" % (dims, "一二三四五六"[len(CHECKS) - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
