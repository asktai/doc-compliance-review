#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铁律条号重排：为"新第 1 条（文档结构与编号）"腾位。

**动因**：编号体系／书写／表格例外／字符四段，此前只存在于**导读区**——
它是全文唯一写明"条以下一律十进制路径"的地方，却无条号、不可引用、
不受守卫覆盖，且长得像"多余的导读"，极易被误删（2026-10-14 开发者即有此疑问）。
本脚本把它升格为**第 1 条**，现第 1—22 条顺延为第 2—23 条。

**映射（唯一规则，纯 +1）**：条 `第 N 条`→`第 N+1 条`；小节 `**K.M`→`**{K+1}.M`；
章区间 `（第 A—B 条）`→`（第 A+1—B+1 条）`；目录锚点 `#第-N-条`→`#第-{N+1}-条`。

**实现要点（踩过的坑）**：
  早期版本分四步顺序替换，结果**章标题里的条号被全局规则改过一次、又被区间规则
  再改一次**（第八章 22→23→24），暴露"多规则叠加二次加"的级联错误。
  故改为**单遍逐行扫描**：每行只判定一次、只改一次，不同类型各行其道。
  教训与铁律 17.2 的"守卫自身也要验证"同源——**替换脚本也得先跑一遍核对映射**，
  否则改坏了正文，后面所有守卫都是在错的底稿上判对错。

用法：python3 maint/scratch/renumber-clauses.py <输入> <输出>
"""

import re
import sys

MAX_N = 22   # 现有最大条号；映射后为 MAX_N+1


def gh_anchor(title):
    """按 GitHub 规则生成锚点：转小写；保留字母/数字/中日韩/空格与连字符；
    其余（标点、括号、破折号、顿号……）一律删除；空格转 `-`。

    与 DEV-RULES.md 里"锚点按 GitHub 规则生成"的声明一致——
    **锚点是派生物**，正文标题才是真源，故重排一律"改标题、重算锚点"。"""
    keep = []
    for ch in title.strip().lower():
        if ch.isalnum() or ch == " " or ch == "-":
            keep.append(ch)
        elif "\u4e00" <= ch <= "\u9fff":   # CJK 统一表意文字
            keep.append(ch)
        # 其余丢弃
    return "".join(keep).replace(" ", "-")


def shift_paths(line):
    """把行内所有**十进制路径引用** +1（`17.4.7.3`→`18.4.7.3`、`13.3`→`14.3`）。

    **这是本脚本第三处、也是最险的一处坑**：铁律明令"引用一律写路径"，
    于是路径引用**散布在正文任何位置**——不只是行首编号单元。早期只改行首
    `**N.M`，漏掉了句中引用（实测：`见 **17.4.3.1**` 没改，而它指向的定义
    `- **17.4.3.1 不可逆**` 改了 → **引用悬空**，正是本文件自己要防的"引用漂移"）。

    **排除规则**（防误伤，实测逐条验过）：
      - 前置 `v`／`V` 的，是**版本号**（`v1.7.0`）——不动；
      - 首段不在 1—22 区间的，不是条号路径——不动（版本号 `1.0.0` 另由 `v` 规则挡住）。
    其余一律 +1：**无论顶格加粗、挂在列表项、还是夹在句子中间**。
    """
    def _rep(mm):
        head = int(mm.group(1)) + 1
        return "%d.%s%s" % (head, mm.group(2), mm.group(3))
    return re.sub(r"(?<![\d.])(?<![vV])(\d{1,2})\.(\d)((?:\.\d+)*)(?![\d.])",
                  lambda mm: _rep(mm) if 1 <= int(mm.group(1)) <= MAX_N else mm.group(0),
                  line)


def shift_line(line):
    """逐行 +1。每行只处理一次，避免多规则叠加。"""
    # ---- A. 条标题行：`### 第 N 条 …` ----
    m = re.match(r"^(### 第 )(\d+)( 条.*)$", line)
    if m:
        return shift_paths("%s%d%s" % (m.group(1), int(m.group(2)) + 1, m.group(3)))

    # ---- B. 章标题行：`## 第X章 …（第 A[—B] 条）` ----
    m = re.match(r"^(## 第)(\d+)(章.*?)(（第 \d+(?:—\d+)? 条）)(\s*)$", line)
    if m:
        body = m.group(4)
        mm = re.match(r"^（第 (\d+)(?:—(\d+))? 条）$", body)
        if mm:
            a = int(mm.group(1)) + 1
            b = mm.group(2)
            rng = "（第 %d—%d 条）" % (a, int(b) + 1) if b else "（第 %d 条）" % a
            return shift_paths("%s%d%s%s%s" % (m.group(1), int(m.group(2)) + 1,
                                               m.group(3), rng, m.group(5)))
        return shift_paths(line)

    # ---- C. 目录条目行：`- [标题](#锚点)` ----
    # **策略：改标题里的条号，然后从新标题重新生成锚点。**
    #
    # 为什么不能"数字 +1"式修补锚点？GitHub 生成锚点时会把 `—`（em dash）
    # 当标点删掉，于是 `（第 11—13 条）` 变成 `第-1113-条`——**两个数字粘在一起**，
    # 从锚点无法反推原文是 11—13 还是 111—3。任何"按数字段 +1"的做法都会
    # 改出与标题不一致的锚点（实测：15 条目录条目全错）。
    # 正解：**锚点是从标题派生的**，改完标题就照 GitHub 规则重算一次。
    if re.match(r"^\s*- \[", line):
        # 先改区间（`第 11—13 条`），再改单条（`第 2 条`）——顺序反了的话，
        # 单条规则会先吃掉 `第 11` 却留下 `—13 条`，变成 `第 12—13 条`。
        def _trng(mm):
            return "第 %d—%d 条" % (int(mm.group(1)) + 1, int(mm.group(2)) + 1)
        title = re.sub(r"第 (\d+)—(\d+) 条", _trng, line)

        def _tref(mm):
            return "第 %d 条" % (int(mm.group(1)) + 1)
        title = re.sub(r"第 (\d+) 条", _tref, title)
        m2 = re.match(r"^(\s*- \[)(.*?)(\]\(#)(.*?)(\)\s*)$", title)
        if m2:
            return "%s%s%s%s%s" % (m2.group(1), m2.group(2),
                                   m2.group(3), gh_anchor(m2.group(2)), m2.group(5))
        return title

    # ---- E. 其余行：行内 `第 N 条` / `第 A—B 条` 引用 ＋ `#第-N-条` 锚点 ＋ 十进制路径 ----
    # **注意 D 段已撤销**：原先单列一段"编号单元行首 **K.M"来处理小节编号，
    # 结果列表项（`- **5.1.1 …`）全部漏网。现统一并入 `shift_paths`——
    # 无论编号单元长在哪，只要是十进制路径就 +1，一套规则管到底。
    def _rng(mm):
        return "第 %d—%d 条" % (int(mm.group(1)) + 1, int(mm.group(2)) + 1)
    line = re.sub(r"第 (\d+)—(\d+) 条", _rng, line)

    def _ref(mm):
        return "第 %d 条" % (int(mm.group(1)) + 1)
    line = re.sub(r"第 (\d+) 条", _ref, line)

    def _anc(mm):
        return "#第-%d-条" % (int(mm.group(1)) + 1)
    line = re.sub(r"#第-(\d+)-条", _anc, line)

    return shift_paths(line)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    # **必须用 splitlines() 不带 keepends**：`shift_line` 内部的正则用 `.*$` 收尾，
    # Python 的 `.` 不匹配 `\n`，若行尾带着 `\n`，`$` 会停在 `\n` 之前、
    # 替换结果把换行**吃掉**——实测首轮跑完 836 行变 661 行（175 个换行消失）。
    # 这是在"行数都对不上"时才暴露的静默损坏：内容看着全对，文件却被压扁了。
    lines = open(src, encoding="utf-8").read().splitlines()

    n_clause = sum(1 for l in lines if re.match(r"^### 第 \d+ 条", l))
    if n_clause != MAX_N:
        print("[E] 预期 %d 条，实际 %d 条——文件可能已重排过，中止（防二次加）"
              % (MAX_N, n_clause))
        return 1

    out = "\n".join(shift_line(l) for l in lines)
    if not out.endswith("\n"):
        out += "\n"
    open(dst, "w", encoding="utf-8").write(out)

    nums = sorted(int(x) for x in re.findall(r"(?m)^### 第 (\d+) 条", out))
    print("[OK] 已写出 %s" % dst)
    print("     条号：%s" % ("1—23 连续" if nums == list(range(1, MAX_N + 2)) else nums))
    return 0


if __name__ == "__main__":
    sys.exit(main())
