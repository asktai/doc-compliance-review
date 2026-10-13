#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""章序重排工具（V1.31.0）——一次性迁移脚本，非常驻守卫。

把 DEV-RULES.md 的章按新框架重排，并整体重映射条号／款号／交叉引用。

用法：
  python3 reorder-chapters.py --dry      # 干跑：重排结果写到 /tmp/reordered.md，不碰正式文件
  python3 reorder-chapters.py --apply    # 落盘（并备份原文件到 /tmp/reorder-backup.md）

新框架：总则 → 提问与确认 → 开发侧分工 → 预防漂移 → 版本控制 → 验校 → 命名编号表述 → 落实原则
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))
RULES = os.path.join(DEV, "DEV-RULES.md")

ART_MAP = {1: 1, 2: 10, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 11, 9: 12, 10: 13,
           11: 7, 12: 8, 13: 9, 14: 14, 15: 15, 16: 16, 17: 17,
           18: 18, 19: 19, 20: 20, 21: 21}

# 新章：(新序, 章名, [(旧条号, 新条号), ...])
NEW = [
    (1, "总则", [(1, 1)]),
    (2, "提问与确认", [(3, 2), (4, 3), (5, 4), (6, 5), (7, 6)]),
    (3, "开发侧分工", [(11, 7), (12, 8), (13, 9)]),
    (4, "预防漂移", [(2, 10)]),
    (5, "版本控制", [(8, 11), (9, 12), (10, 13)]),
    (6, "验校", [(14, 14), (15, 15), (16, 16), (17, 17)]),
    (7, "命名、编号与表述", [(18, 18), (19, 19), (20, 20)]),
    (8, "落实原则", [(21, 21)]),
]

CN = "零一二三四五六七八九十"


def cn_num(n):
    if n <= 10:
        return CN[n]
    if n < 20:
        return "十" + CN[n - 10]
    if n == 20:
        return "二十"
    return "二十一"


def rng_text(nums):
    nums = sorted(nums)
    if len(nums) == 1:
        return "第 %d 条" % nums[0]
    return "第 %d—%d 条" % (nums[0], nums[-1])


def parse_articles(body_lines):
    """把正文区拆成 {旧条号: [行...]}；章标题行（`## `）一律丢弃（随后统一重建）。"""
    arts, cur_no, cur = {}, None, []
    for l in body_lines:
        if l.startswith("## "):          # 章标题：丢弃，稍后重建
            continue
        m = re.match(r"^### 第 (\d+) 条 ", l)
        if m:
            if cur_no is not None:
                arts[cur_no] = cur
            cur_no = int(m.group(1))
            cur = [l]
        elif cur_no is not None:
            cur.append(l)
    if cur_no is not None:
        arts[cur_no] = cur
    # 去掉每块首尾的空行与分隔线（分隔线统一在重组时补）
    for k in arts:
        while arts[k] and arts[k][0].strip() == "":
            arts[k].pop(0)
        while arts[k] and arts[k][-1].strip() in ("", "---"):
            arts[k].pop()
    return arts


def renumber_block(lines, old_no, new_no):
    """块内重映射条号与款号。**统一走占位符，杜绝二次替换。**

    三趟：
      A) 条号引用（`第 N 条`、`第 A—B 条`）→ 占位符
      B) 款号（`N.M(.K)`，含标题与引用；跳过反引号内）→ 占位符（按旧条号记）
      C) 占位符统一还原为新号
    """
    txt = "\n".join(lines)

    # ── A) 条号引用 → 占位符（先区间后单条）──
    txt = re.sub(r"第 ?(\d+)[ ]?—[ ]?(\d+)[ ]?条",
                 lambda m: "\x00R%s_%s\x00" % (m.group(1), m.group(2)), txt)
    txt = re.sub(r"第 ?(\d+)[ ]?条", lambda m: "\x00A%s\x00" % m.group(1), txt)

    # ── B) 款号 → 占位符（跳过反引号内；跳过前面带字母/数字/点的）──
    def enc(t):
        parts = t.split("`")
        for i in range(0, len(parts), 2):        # 偶数段 = 反引号外
            parts[i] = re.sub(r"(?<![\d.A-Za-z])(\d+)(\.\d+(?:\.\d+)*)(?![\d.])",
                              lambda m: "\x00V%s%s\x00" % (m.group(1), m.group(2)), parts[i])
        return "`".join(parts)

    txt = enc(txt)
    # 条标题（### 第 N 条）此刻仍是字面（因为"第 N 条"已被 A 步换掉 → 实为 ### \x00A N\x00）
    # 直接改标题：把行首 ### 那条的编号换掉（此时标题形如 "### \x00A旧\x00 标题"）
    txt = re.sub(r"^### \x00A\d+\x00 ", lambda m: "### \x00ANEW\x00 ", txt, count=1, flags=re.M)

    # ── C) 还原 ──
    def dec_v(m):
        top = int(m.group(1))
        return "%d%s" % (ART_MAP.get(top, top), m.group(2))

    txt = re.sub(r"\x00V(\d+)(\.[\d.]+)\x00", dec_v, txt)
    txt = re.sub(r"\x00R(\d+)_(\d+)\x00",
                 lambda m: rng_text([ART_MAP[x] for x in range(int(m.group(1)), int(m.group(2)) + 1)]), txt)
    txt = re.sub(r"\x00ANEW\x00", "第 %d 条" % new_no, txt)
    txt = re.sub(r"\x00A(\d+)\x00", lambda m: "第 %d 条" % ART_MAP[int(m.group(1))], txt)
    return txt.split("\n")
    # 4) 还原条号引用
    def back_single(m):
        n = int(m.group(1))
        return "第 %d 条" % ART_MAP[n]

    def back_range(m):
        a, b = int(m.group(1)), int(m.group(2))
        ns = sorted({ART_MAP[x] for x in range(a, b + 1)})
        if len(ns) == 1:
            return "第 %d 条" % ns[0]
        return "第 %d—%d 条" % (ns[0], ns[-1])

    txt = re.sub(r"\x00R(\d+)_(\d+)\x00", back_range, txt)
    txt = re.sub(r"\x00A(\d+)\x00", back_single, txt)
    return txt.split("\n")


def main(apply=False):
    src = open(RULES, encoding="utf-8").read()
    if "预防漂移（第 10 条）" in src:
        print("[!] 检测到已重排，拒绝重复执行。")
        return 1
    lines = src.splitlines()
    i_body = next(i for i, l in enumerate(lines) if l.startswith("## 第一章"))
    i_app = next(i for i, l in enumerate(lines) if l.startswith("## 附录 A"))

    head_lines = lines[:i_body]          # 前置区（含目录，随后单独重建）
    app_lines = lines[i_app:]            # 附录区（单独处理引用）
    arts = parse_articles(lines[i_body:i_app])
    print("识别到 %d 个条块：%s" % (len(arts), sorted(arts)))

    # 组装新正文
    out = []
    for no, name, arts_in in NEW:
        nums = [nw for _old, nw in arts_in]
        out.append("## 第%s章 %s（%s）" % (cn_num(no), name, rng_text(nums)))
        out.append("")
        for old_no, new_no in arts_in:
            out.extend(renumber_block(arts[old_no], old_no, new_no))
            out.append("")
            out.append("---")
            out.append("")
    while out and out[-1].strip() in ("", "---"):
        out.pop()

    # 附录区：条号引用 + 款号引用都要改号（同样走占位符，跳过反引号内）
    app_txt = "\n".join(app_lines)
    app_txt = re.sub(r"第 ?(\d+)[ ]?—[ ]?(\d+)[ ]?条",
                     lambda m: "\x00R%s_%s\x00" % (m.group(1), m.group(2)), app_txt)
    app_txt = re.sub(r"第 ?(\d+)[ ]?条", lambda m: "\x00A%s\x00" % m.group(1), app_txt)
    # 款号引用（跳过反引号内；跳过前带字母/数字/点者）
    _parts = app_txt.split("`")
    for _i in range(0, len(_parts), 2):
        _parts[_i] = re.sub(r"(?<![\d.A-Za-z])(\d+)(\.\d+(?:\.\d+)*)(?![\d.])",
                            lambda m: "\x00V%s%s\x00" % (m.group(1), m.group(2)), _parts[_i])
    app_txt = "`".join(_parts)
    app_txt = re.sub(r"\x00V(\d+)(\.[\d.]+)\x00",
                     lambda m: "%d%s" % (ART_MAP.get(int(m.group(1)), int(m.group(1))), m.group(2)), app_txt)
    app_txt = re.sub(r"\x00R(\d+)_(\d+)\x00",
                     lambda m: rng_text([ART_MAP[x] for x in range(int(m.group(1)), int(m.group(2)) + 1)]), app_txt)
    app_txt = re.sub(r"\x00A(\d+)\x00", lambda m: "第 %d 条" % ART_MAP[int(m.group(1))], app_txt)

    # ── 前置区：导读表改号 + 目录整块重建 ──
    def make_anchor(text):
        t = text.lower()
        # GitHub 规则：去标点（含破折号、句点、括号等）→ 空格转 -
        t = re.sub(r"[（）、，：；／·—\.]", "", t)
        return t.replace(" ", "-")

    head_txt = "\n".join(head_lines)
    # 导读表三行的条号（按内容匹配 → 新号）
    guide_fix = [("不确定就问", 2), ("改动次序与收口", 12), ("版本与迭代", 13)]
    for name, newno in guide_fix:
        head_txt = re.sub(r"\| \*\*第 \d+ 条\*\* \| %s \|" % re.escape(name),
                          "| **第 %d 条** | %s |" % (newno, name), head_txt)

    # 重建目录：从新正文收集章与条
    body_txt = "\n".join(out)
    toc = []
    for lm in re.finditer(r"^(## 第.+?章 .+?|### 第 \d+ 条 .+)$", body_txt, re.M):
        line = lm.group(1)
        if line.startswith("## "):
            title = line[3:].strip()
            toc.append("- [%s](#%s)" % (title, make_anchor(title)))
        else:
            title = line[4:].strip()
            toc.append("  - [%s](#%s)" % (title, make_anchor(title)))
    # 附录条目（保持原有附录目录结构）
    for lm in re.finditer(r"^(## 附录 .+?|### A\.\d+ .+)$", "\n".join(app_lines), re.M):
        line = lm.group(1)
        title = (line[3:] if line.startswith("## ") else line[4:]).strip()
        pre = "" if line.startswith("## ") else "  "
        toc.append("%s- [%s](#%s)" % (pre, title, make_anchor(title)))

    # 替换原目录块（从"目录（锚点"到首个"---"）
    toc_new = "目录（锚点按 GitHub 规则生成；阅读器若不认，按章名／条名定位即可）\n\n" + "\n".join(toc)
    head_txt = re.sub(r"目录（锚点.*?(?=\n---\n)",
                      toc_new, head_txt, flags=re.S)

    result = head_txt + "\n" + body_txt + "\n\n---\n\n" + app_txt + "\n"
    if apply:
        open("/tmp/reorder-backup.md", "w", encoding="utf-8").write(src)
        open(RULES, "w", encoding="utf-8").write(result)
        print("已落盘（备份：/tmp/reorder-backup.md）")
    else:
        open("/tmp/reordered.md", "w", encoding="utf-8").write(result)
        print("干跑完成 → /tmp/reordered.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
