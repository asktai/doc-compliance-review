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
import os
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

EXEMPT_OPEN = "<!-- selfcheck-exempt:"
EXEMPT_CLOSE = "<!-- /selfcheck-exempt -->"


def _fold(s):
    """统一大小写与全半角，供专有名词／路径匹配用。

    ⚠ 2026-10-20 二轮质检加：原匹配区分大小写、不折全角，
    于是 `CHECK.PY`、`ＣＨＡＮＧＥＬＯＧ`、`pack．py`（全角点）全漏。
    **专有名词残留最容易藏在大小写变体里**——这是 (L4) 的判据漏洞，不是文档的问题。
    """
    out = []
    for ch in s:
        # 全角 ASCII（！到～）折回半角
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            ch = chr(o - 0xFEE0)
        out.append(ch)
    return "".join(out).casefold()


def exempt_lines(lines):
    """返回"作者显式声明为反例、应豁免扫描"的行号集合。

    ⚠ 2026-10-20 二轮质检加（12.4 的口径）：守卫**必须允许规则本体写出被禁形态**。
    实测踩到：本文档"检查器自身的洞"那张表为了举例，写进了 `CHECK.PY`、`/etc/passwd`、
    `~/x` 等真·违规样例，于是 (L4)(L5) 把自己文档拦下了——
    **这不是文档脏，是守卫不给规则本体留出口**。没有出口的守卫，第一天就会被关掉。
    用法：在反例段落前后各加一行标记（见下 EXEMPT_OPEN/CLOSE），
    **并写明豁免依据**（哪条规则要求写出该形态），否则不算合法豁免。
    """
    out, inside = set(), False
    for i, l in enumerate(lines, 1):
        if EXEMPT_OPEN in l:
            inside = True
            out.add(i)
            continue
        if EXEMPT_CLOSE in l:
            inside = False
            out.add(i)
            continue
        if inside:
            out.add(i)
    return out


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



def lines_of_source():
    """读本脚本自身的源码行。供 (L0) 静态自检用。"""
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        return f.read().splitlines()


def _dim_spans(src):
    """把源码按"每维的起止"切片：从 RAN.append(n) 那一行，到下一个 RAN.append 之前。
    返回 {维度号: 该维的代码体文本}。"""
    marks = []
    for m in re.finditer(r"(?m)^\s*RAN\.append\((\d+)\)\s*$", src):
        marks.append((int(m.group(1)), m.start()))
    marks.sort(key=lambda t: t[1])
    spans = {}
    for idx, (n, st) in enumerate(marks):
        en = marks[idx + 1][1] if idx + 1 < len(marks) else len(src)
        spans[n] = src[st:en]
    return spans

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "DEV-RULES-LITE.md"
    # ⚠ 2026-10-20 二轮质检修：原只捕 FileNotFoundError，传目录／非 UTF-8 文件
    #   会**打出一屏堆栈**（复核者戊实测）。堆栈与"检出问题"的退出码都是非零，
    #   下游会**分不清"脚本崩了"和"文档真有问题"**——这正是 12.1 说的"假过"的反面：
    #   **崩了也算报错，等于判据被噪声污染**。
    #   治法：把所有"读不出来"的情形收成一条清晰报错，退出码 2（与"检出问题"的 1 分开）。
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read()
    except FileNotFoundError:
        print("守卫失效：规范文件不存在（%s）—— 不是文档有问题，是没找到文件" % path)
        return 2
    except IsADirectoryError:
        print("守卫失效：给的是目录不是文件（%s）—— 请指向 .md 文件本身" % path)
        return 2
    except UnicodeDecodeError as e:
        print("守卫失效：文件不是 UTF-8（%s）：%s —— 先转码，别让脚本带病跑" % (path, e))
        return 2
    except OSError as e:
        print("守卫失效：读文件出错（%s）：%s" % (path, e))
        return 2
    lines = s.splitlines()
    fenced = in_fence(lines)
    exempt = exempt_lines(lines)

    # 维度总表：结论行与"共几项"都由它派生，加维度只改这里
    CHECKS = [
        (1, "条号与款号连续性"), (2, "引用不悬空"), (3, "表格完整性"),
        (4, "专有名词残留"), (5, "绝对路径残留"),
        (6, "目录与正文标题一致"),
        (7, "表格行数引用不虚指"),
    ]
    RAN = []   # 每维跑完 append 自己的编号，结论行只认它

    # ---------- (L1) 条号连续 ----------
    print("(L1) 条号与款号连续性")
    RAN.append(1)
    arts = []
    # ⚠ 2026-10-20 三轮质检修（复核者壬实测）：原正则只认半角数字与行首无空格，
    #   `## 第９条`（全角）／`  ## 第 3 条`（缩进）被静默放行——
    #   而且只要目录也配套全角、正文不引用，**这个"幽灵条"谁都看不见**（L2/L6 才有兜底）。
    #   治法：匹配前先 fold（全角转半角），并允许行首空白。
    weird = []
    for i, l in enumerate(lines, 1):
        # ⚠ 2026-10-20 二轮质检修：原**不跳代码块**，正文示例里写一行
        #   "## 第 9 条 示例"（在 ``` 内）就被算成真的条号，报"重号"——误拦。
        if i in fenced:
            continue
        lf = _fold(l)
        m = re.match(r"^\s*##\s*第\s*(\d+)\s*条", lf)
        if m:
            n0 = int(m.group(1))
            # 检出"写法不正"但数值可用的（全角/缩进/多空格）——放行但记一笔
            if l != l.lstrip() or not re.match(r"^## 第 \d+ 条", l):
                weird.append("第 %d 行「%s」（写法不标准：缩进或含多余空格）" % (i, l.strip()[:30]))
            arts.append(n0)
    if weird:
        err("(L1) 条号写法不标准（虽然能识别，但换工具会漏）：%s" % "；".join(weird))
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
    RAN.append(2)
    defined = set()
    # ⚠ 2026-10-20 三轮质检修：原不 fold——`第 ９ 条`（全角）引用一个
    #   **存在**的第 9 条时会被误判"悬空"，因为 defined 里收的是半角 "9"。
    #   L1 已 fold、这里不 fold，两侧对不齐。统一在收集与查询两端都 fold。
    for l in lines:
        for m in re.finditer(r"\*\*((?:\d+)(?:\.\d+)+)\s*[^\d.]", _fold(l)):
            defined.add(m.group(1))
    for a in arts:
        defined.add(str(a))

    VER = re.compile(r"(?<![\d.])(?:v)?\d+\.\d+\.\d+(?![\d.])")
    bad = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        scan = VER.sub(lambda m: " " * len(m.group(0)), _fold(l))
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
    # ⚠ 2026-10-20 二轮质检修三处（复核者戊实测指出，全部坐实）：
    #   (甲) 原只看表头列数、**不比分隔行**——表头 2 列配 `|---|---|---|` 照样全过；
    #   (乙) 原不查**空表**（只有表头、表体 0 行）——表体整段被删也全过；
    #   (丙) 原按裸 `split("|")` 数格子，**不认 Markdown 合法转义 `\|`**，
    #        单元格写 `a \| b` 就被误判成 3 列（误拦）。
    #   **这是"假过"＋"误拦"两个方向同时出错**，正是 12.1 说的三种失效里的两种。
    print("(L3) Markdown 表格完整性（列数／分隔行／空表）")
    RAN.append(3)

    def _cols(row):
        """数一行表格的格子数，`\|` 是转义、不算分隔。"""
        r = row.strip()
        if r.startswith("|"):
            r = r[1:]
        if r.endswith("|") and not r.endswith("\\|"):
            r = r[:-1]
        # 先把 \| 换成占位符，split 完再换回来位置无所谓（只数个数）
        return len(re.split(r"(?<!\\)\|", r))

    tbl_bad, i, n = [], 0, len(lines)
    while i < n:
        if (i + 1) in fenced:
            i += 1
            continue
        l = lines[i]
        is_head = l.strip().startswith("|")
        is_sep = (i + 1 < n) and bool(re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]))
        if is_head and is_sep:
            hcols = _cols(l)
            scols = _cols(lines[i + 1])
            if scols != hcols:
                tbl_bad.append("第 %d 行 分隔行 %d 列 ≠ 表头 %d 列" % (i + 2, scols, hcols))
            body = 0
            j = i + 2
            while j < n and lines[j].strip().startswith("|"):
                if (j + 1) in fenced:
                    break
                body += 1
                c = _cols(lines[j])
                if c != hcols:
                    tbl_bad.append("第 %d 行 %d 列（表头 %d 列）" % (j + 1, c, hcols))
                j += 1
            if body == 0:
                tbl_bad.append("第 %d 行的表格**只有表头、没有表体**（表体 0 行）" % (i + 1))
            i = j
            continue
        i += 1
    if tbl_bad:
        err("(L3) 表格不完整：%s" % "；".join(tbl_bad))
    else:
        print("      全部表格：列数一致、分隔行相符、无空表")

    # ---------- (L4) 专有名词残留 ----------
    print("(L4) 项目专有名词残留")
    RAN.append(4)
    hit = []
    for i, l in enumerate(lines, 1):
        if i in fenced or i in exempt:
            continue
        # ⚠ 2026-10-20 二轮质检修：原**区分大小写、不折全角**——
        #   `CHECK.PY`、`DevLog`、`ＣＨＡＮＧＥＬＯＧ`（全角）、`pack．py`（全角点）
        #   全部漏过（复核者戊实测）。专有名词残留恰恰**最容易出现在大小写变体里**，
        #   所以先 fold 成小写、再把全角转半角，然后才匹配。
        scan = _fold(l)
        for a in ALLOW:
            scan = scan.replace(_fold(a), " " * len(a))
        for w in PROPER:
            wf = _fold(w)
            # 整词：前不接字母数字与 . - _，后不接字母数字 . - _（防 check.py 命中 lite-selfcheck.py）
            pat = r"(?<![\w.\-])" + re.escape(wf) + r"(?![\w\-])"
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
    RAN.append(5)
    pbad = []
    for i, l in enumerate(lines, 1):
        if i in fenced or i in exempt:
            continue
        # ⚠ 2026-10-20 二轮质检修：原只认 unix 绝对路径的少数几个根，
        #   下列全部漏过（复核者戊逐条实测）：
        #   `~/x`（家目录）、`C:\tmp\x`（盘符）、`\\server\share`（UNC）、`/etc/passwd`（其它根）。
        #   判据统一为：**任何指向"某台具体机器上某个位置"的写法**，都是本机痕迹。
        line_f = _fold(l)
        # ⚠ 2026-10-20 三轮质检修两处（复核者壬实测）：
        #   (甲) 原 unix 根目录用**白名单**（tmp/home/root/...），`/data/x`、`/opt2/`
        #        全漏——注释自称"任何根"但实现不是，**注释与判据漂移**。改黑名单：
        #        排除 URL 协议后，凡 `/小写字母开头/` 的写法一律视为本机路径。
        #   (乙) Windows 盘符只认反斜杠 `C:\`，`C:/tmp/x` 正斜杠漏过。补上。
        for pat, why in [
            (r"(?<![\w:/.])/(?!/)[a-z][\w\-]*(?:/[\w\-./]*)+", "unix 风格绝对路径"),
            (r"(?<![\w])~/[\w\-./]*", "家目录写法"),
            (r"(?<![\w])[A-Za-z]:[\\/][\w\-./\\]*", "Windows 盘符路径"),
            (r"\\\\[\w.\-]+\\[\w\-.$]*", "UNC 网络路径"),
        ]:
            for m in re.finditer(pat, l):
                pbad.append("第 %d 行「%s」（%s）" % (i, m.group(0)[:40], why))
    if pbad:
        err("(L5) 绝对路径残留：%s" % "；".join(pbad[:12]))
    else:
        print("      无绝对路径残留")

    # ---------- (L6) 目录与正文标题一致 ----------
    # ⚠ 2026-10-20 全量质检补：原检查**不查目录**——于是新加一节忘了补目录，
    #   六项全过（实测踩过：补「本文件版本沿革」后目录漏项，检查一声不吭）。
    #   判据：文中每个二级标题（## ）都须在目录里有对应条目，且目录条目都指向真实标题。
    print("(L6) 目录与正文标题一致")
    RAN.append(6)
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

    # ---------- (L7) 表格行数引用不虚指 ----------
    # ⚠ 2026-10-20 三轮质检加（复核者辛指出，且**这是复发**）：
    #   v1.0.2 修过 6.3 的"示例指向不存在的 8.5 第 3 行"；v1.0.3 里 15.2 又写了
    #   "7.3 第 4 行"——7.3 根本没有表格，也没有第 4 行。**同类病在修过之后又犯**，
    #   说明它**必须靠守卫**，不能靠"我记得检查"。
    #   判据：文中出现 "`X 第 N 行`"（X 是款号），且该处**确指**而非"示例非实指"，
    #   那么 X 对应的段落下**必须有至少 N 行表格行**。例外：该行已标"示例非实指"。
    print("(L7) 表格行数引用不虚指")
    RAN.append(7)
    ref_bad = []
    # 先算出每个款号下的表格行数
    tbl_rows = {}   # 款号 -> 该行数
    cur_sec = None
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        m = re.match(r"^\*\*((?:\d+)(?:\.\d+)+)[^\d.]", l)
        if m:
            cur_sec = m.group(1)
            tbl_rows.setdefault(cur_sec, 0)
            continue
        if cur_sec and l.strip().startswith("|") and not re.match(r"^\s*\|[\s:|-]+\|\s*$", l):
            tbl_rows[cur_sec] = tbl_rows.get(cur_sec, 0) + 1
    # 再扫引用
    for i, l in enumerate(lines, 1):
        if i in fenced or i in exempt:
            continue
        if "示例非实指" in l or "非实指" in l:
            continue
        for m in re.finditer(r"`((?:\d+)(?:\.\d+)+) 第 (\d+) 行`", l):
            sec, nrows = m.group(1), int(m.group(2))
            if sec in tbl_rows and tbl_rows[sec] >= nrows:
                continue
            ref_bad.append("第 %d 行「%s 第 %s 行」——该款下没有那么多表格行（实际 %d 行）"
                           % (i, sec, nrows, tbl_rows.get(sec, 0)))
    if ref_bad:
        err("(L7) 虚指表格行：%s" % "；".join(ref_bad))
    else:
        print("      无表格行数虚指")

    print()
    if errs:
        print("自洽检查未通过，%d 项：" % len(errs))
        for e in errs:
            print("  - " + e)
        return 1

    # ⚠ 2026-10-20 二轮质检修（这是本轮最重要的一处，复核者戊实测指出）：
    #   原来结论行只说"CHECKS 里有几维就报几维全过"——**表不等于实现**。
    #   实测：往 CHECKS 塞一个 "(7, 假维度)" 而根本没有 L7 的代码，
    #   结论行照样会说"七项全过"（旧版更直接崩栈，但那同样是"结论不由执行决定"）。
    #   这正是 12.1 说的**假过**：零个维度自然零个错误，于是判"通过"。
    #   治法：**以"实际跑过的维度"为准**，不是以表为准；
    #   且**表里有、实际没跑**的，本身就要报错（说明实现漏了）。
    # ⚠ 2026-10-20 三轮质检修（本轮最严重，复核者壬实测坐实）：
    #   把某维的 err(...) 改成 pass，维度"跑了但哑了"——文档真有问题时
    #   照样报"全过"、exit=0。RAN 只核"跑没跑"，核不出"报错路径被删了"。
    #   **判据**：每一维的代码体里必须**静态存在至少一个可调用的 err(** 调用。
    #   （不看这次实际报没报——干净文档下所有维都不报，那不算哑；
    #     看的是**代码里还有没有报错这条路**，被删了才算哑。）
    src = "\n".join(lines_of_source())
    dim_spans = _dim_spans(src)
    mute = []
    for n, _ in CHECKS:
        body = dim_spans.get(n, "")
        # 至少要有一个真正的 err( 调用（不是注释、不是字符串里的字样）
        if not re.search(r"(?m)^\s*err\(", body):
            mute.append(n)
    if mute:
        print("自洽检查未通过，1 项：")
        print("  - (L0) 判据失效：维度 %s 的代码里没有一个可调用的 err( —— "
              "报错路径被删了，跑也白跑（打瘸点打在了错误路径上）"
              % "、".join("(L%d)" % n for n in mute))
        return 1

    ran = set(RAN)
    declared = set(n for n, _ in CHECKS)
    never = sorted(declared - ran)
    extra = sorted(ran - declared)

    if never:
        print("自洽检查未通过，1 项：")
        print("  - (L0) 判据失效：声明的维度 %s 一声没吭——没实现的维度不算通过"
              % "、".join("(L%d)" % n for n in never))
        return 1
    if extra:
        print("自洽检查未通过，1 项：")
        print("  - (L0) 声明缺项：实际跑了 %s，但 CHECKS 表里没登记——结论行会漏报它"
              % "、".join("(L%d)" % n for n in extra))
        return 1
    if not ran:
        print("自洽检查未通过，1 项：")
        print("  - (L0) 判据失效：一个维度都没跑起来，零维自然零错误，不得判通过")
        return 1

    dims = "".join("(L%d)" % n for n in sorted(ran))
    print("自洽检查通过：%s %d 项全过（按实际执行维度计，非按声明表计）" % (dims, len(ran)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
