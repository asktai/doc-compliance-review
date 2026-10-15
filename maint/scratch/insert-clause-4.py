#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在铁律第 3 条之后插入新条，并把**自第 4 条起**的所有条号 +1。

与 `renumber-clauses.py` 的区别：后者是**全体 +1**（1—22 → 2—23）；
本脚本只对**从第 START 条起**的条号 +1（第 1—3 条不动），故须另写。

**唯一规则**：凡条号 ≥ START 者 +1：
  - 条标题 `### 第 N 条`（N ≥ START）
  - 小节号 `**K.M…`（K ≥ START，含列表项）
  - 行内 `第 N 条` 引用（N ≥ START）
  - 章区间 `（第 A—B 条）` 中 ≥ START 的端点
  - 路径引用 `N.M…`（首段 N ≥ START）
  - 目录锚点 `#第-N-条`（N ≥ START）
条号 < START 者一律不动。

**用法**：python3 insert-clause-4.py <输入> <输出>
"""
import re
import sys

START = 4          # 自该条起 +1（第 1—3 条不动）


def bump(n):
    return n + 1 if n >= START else n


def _path(mm):
    """十进制路径引用：首段 ≥ START 才 +1。"""
    if int(mm.group(1)) < START:
        return mm.group(0)
    return "%d.%s%s" % (bump(int(mm.group(1))), mm.group(2), mm.group(3))


def shift_paths(line):
    return re.sub(r"(?<![\d.])(?<![vV])(\d{1,2})\.(\d)((?:\.\d+)*)(?![\d.])",
                  _path, line)


def shift_line(line, in_clause=None):
    # A. 条标题
    m = re.match(r"^(### 第 )(\d+)( 条.*)$", line)
    if m:
        return "%s%d%s" % (m.group(1), bump(int(m.group(2))), m.group(3))

    # B. 章标题
    m = re.match(r"^(## 第)(\d+)(章.*?)(（第 \d+(?:—\d+)? 条）)(\s*)$", line)
    if m:
        mm = re.match(r"^（第 (\d+)(?:—(\d+))? 条）$", m.group(4))
        if mm:
            a, b = int(mm.group(1)), mm.group(2)
            rng = ("（第 %d—%d 条）" % (bump(a), bump(int(b)))
                   if b else "（第 %d 条）" % bump(a))
            return shift_paths("%s%d%s%s%s" % (m.group(1), int(m.group(2)) + 1,
                                               m.group(3), rng, m.group(5)))
        return shift_paths(line)

    # C. 目录条目：改标题条号后重算锚点
    if re.match(r"^\s*- \[", line):
        def _rng(mm):
            return "第 %d—%d 条" % (bump(int(mm.group(1))), bump(int(mm.group(2))))
        t = re.sub(r"第 (\d+)—(\d+) 条", _rng, line)

        def _ref(mm):
            return "第 %d 条" % bump(int(mm.group(1)))
        t = re.sub(r"第 (\d+) 条", _ref, t)
        m2 = re.match(r"^(\s*- \[)(.*?)(\]\(#)(.*?)(\)\s*)$", t)
        if m2:
            return "%s%s%s%s%s" % (m2.group(1), m2.group(2),
                                   m2.group(3), gh_anchor(m2.group(2)), m2.group(5))
        return t

    # E. 其余：行内引用 + 锚点 + 路径
    def _rng(mm):
        return "第 %d—%d 条" % (bump(int(mm.group(1))), bump(int(mm.group(2))))
    line = re.sub(r"第 (\d+)—(\d+) 条", _rng, line)

    def _ref(mm):
        return "第 %d 条" % bump(int(mm.group(1)))
    line = re.sub(r"第 (\d+) 条", _ref, line)

    def _anc(mm):
        return "#第-%d-条" % bump(int(mm.group(1)))
    line = re.sub(r"#第-(\d+)-条", _anc, line)

    return shift_paths(line)


def gh_anchor(title):
    """GitHub 锚点规则：保留字母/数字/CJK/空格/连字符，其余删除，空格转 -。"""
    keep = []
    for ch in title.strip().lower():
        if ch.isalnum() or ch in " -" or "\u4e00" <= ch <= "\u9fff":
            keep.append(ch)
    return "".join(keep).replace(" ", "-")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    lines = open(src, encoding="utf-8").read().splitlines()

    # 防二次加：第 4 条现在应是「询问方式」
    n4 = [l for l in lines if re.match(r"^### 第 4 条", l)]
    if not n4 or "询问方式" not in n4[0]:
        print("[E] 第 4 条不是「询问方式」——文件可能已重排，中止")
        return 1

    out = "\n".join(shift_line(l) for l in lines) + "\n"
    open(dst, "w", encoding="utf-8").write(out)

    nums = sorted(int(x) for x in re.findall(r"(?m)^### 第 (\d+) 条", out))
    print("[OK] 已写出 %s" % dst)
    print("     条号：%s" % nums)
    return 0


if __name__ == "__main__":
    sys.exit(main())
