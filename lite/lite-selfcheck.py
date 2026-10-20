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
# 允许出现的完整词自身例外：本文件自带的检查器名，不是项目专有物
ALLOW = {"lite-selfcheck.py"}

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

    print()
    if errs:
        print("自洽检查未通过，%d 项：" % len(errs))
        for e in errs:
            print("  - " + e)
        return 1
    print("自洽检查通过：(L1)(L2)(L3)(L4) 四项全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
