#!/usr/bin/env python3
"""精简版铁律（dev/lite/DEV-RULES-LITE.md）专用的文档自洽检查。

**它只验本文件自身，不验任何项目。**

与完整版检查器（maint/tools/check-dev-rules.py）同源同理、**判据分叉**。
分叉不是偷懒，是因为精简版结构不同——只有 16 条、不分章、没有落实总表、没有导读表。
直接拿完整版检查器去跑，会因"章／导读表／24.3 落实总表"这些精简版**不存在的东西**
连报假错，把真问题淹掉（2026-10-21 实测：17 条报错里 16 条是结构不适用）。

七维，每维都问同一个问题：**"改坏它，这里能不能发现？"**
    (L1) 条号与款号连续      (L2) 引用不悬空        (L3) 表格完整
    (L4) 专有名词与路径零残留 (L5) 目录与正文一致    (L6) 版式
    (L7) 表格行数引用不虚指
另加 **(L0) 判据失效自检**：给每维喂一份必错样本，某维不报错即报 (L0)——
这不是文档有错，是该维的报错路径被删了（打瘸验证）。

用法：
    python3 lite-selfcheck.py DEV-RULES-LITE.md
退出码：0 全过；1 有问题；2 用法或读取错误。

**维号说明**：维号允许带字母子号（如 L4a／L4b）——新增维度**不重排既有编号**，
否则旧记录里引用的 (L4) 会指向另一件事（第 12 条：守卫自身须可追溯）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))      # 待检文件所在目录
ERR, WARN = [], []

# 豁免标注：`<!-- selfcheck-exempt: 依据 = 哪一条 -->` … `<!-- /selfcheck-exempt -->`
# 成对出现，中间的行**不参与 (L4)(L6) 两维**——规则本体必须能写出被禁形态才能立规矩，
# 否则守卫第一天就误报（第 12 条：守卫不加豁免条件，第一天就没人用得起）。
# 成对标注的**开始标记**必须自带维号：`<!-- selfcheck-exempt(L4): 依据 = … -->`。
# 为何强制带维号：成对标注若免"全部"，中间夹的无编号加粗段会连带被放过，
# 守卫当场变哑（2026-10-21 实测：豁免区里正好有五条记录性加粗段）。
EXEMPT_RE = re.compile(
    r"<!--\s*selfcheck-exempt\((?P<tags>[L0-9, ]+)\)\s*:?\s*(?P<why>.*?)-->"
    r"(?P<body>.*?)<!--\s*/selfcheck-exempt\s*-->",
    re.S)

# 单行式豁免：`<!-- selfcheck-exempt(L4): 依据 = … -->`
EXEMPT_ONE_RE = re.compile(
    r"^\s*<!--\s*selfcheck-exempt\((?P<tags>[L0-9, ]+)\)\s*:?\s*(?P<why>.*?)-->\s*$")


def head(t):
    print("\n%s" % t)


def err(m):
    ERR.append(m)
    print("  [E] " + m)


def warn(m):
    WARN.append(m)
    print("  [W] " + m)


def info(m):
    print("  [i] " + m)


# ---------------------------------------------------------------- 基础解析


def in_fence(s):
    """围栏代码块内的行号——代码块里的字面量不是规则文本。"""
    out, inside = set(), False
    for i, l in enumerate(s.splitlines(), 1):
        if l.strip().startswith("```"):
            inside = not inside
            out.add(i)
            continue
        if inside:
            out.add(i)
    return out


def exempt_lines(s):
    """豁免区行号（含标注行本身）。用途由 `依据 =` 里的维号决定：

        (L4) → 只免"专有名词／路径"扫描；(L6) → 只免"版式"扫描；(L7) → 只免"表格行引用"。
        写 `全部` 则三维全免。

    分维豁免是必须的：反例表写着 `CHECK.PY`、`/etc/passwd` 这类被禁形态，
    若一并免掉 (L6)，表里就会混进无编号加粗段而不自知（**豁免范围过宽 = 守卫变哑**）。
    """
    out = {"L4": set(), "L6": set(), "L7": set()}
    single = set()
    lines = s.splitlines()
    bad = []
    for m in EXEMPT_RE.finditer(s):
        why = m.group("why")
        if not re.search(r"依据\s*=", why):
            bad.append(why.strip()[:40])
            continue
        start = s[:m.start()].count("\n") + 1
        end = s[:m.end()].count("\n") + 1
        tags = m.group("tags")
        for tag in ("L4", "L6", "L7"):
            if tag in tags or "全部" in tags:
                out[tag].update(range(start, end + 1))
    # 单行式豁免（**放在本节最后**）：上述成对标注此前已消耗掉，剩下的必是单行式。
    # 语法：`<!-- selfcheck-exempt(L4): 依据 = … -->`——只免本行，不跨行。
    for i, l in enumerate(lines, 1):
        if "selfcheck-exempt" not in l:
            continue
        m = EXEMPT_ONE_RE.match(l)
        if not m:
            continue
        tags, why = m.group("tags"), m.group("why")
        if not re.search(r"依据\s*=", why):
            bad.append("第 %d 行单行豁免缺 `依据 =`" % i)
            continue
        for tag in ("L4", "L6", "L7"):
            if tag in tags or "全部" in tags:
                out[tag].add(i)
        single.add(i)

    # 落单的标注（有开无闭／有闭无开）同样视为未生效
    known = out["L4"] | out["L6"] | out["L7"] | single
    for i, l in enumerate(lines, 1):
        if "selfcheck-exempt" in l and i not in known:
            bad.append("第 %d 行标注不成对或未写维号（须写 `依据 = (L4) …`）" % i)
    return out, bad


def titles(s):
    """条标题：(条号, 标题余部, 行号)。**二、三级标题都认**——精简版用 `##`。"""
    return [(int(m.group(1)), m.group(2), i)
            for i, l in enumerate(s.splitlines(), 1)
            for m in [re.match(r"^#{2,3} 第 (\d+) 条(.*)$", l)] if m]


def _fold(t):
    """全角数字／全角点 → 半角。带子号的引用须两端一致 fold，否则一边放行一边误报。"""
    tbl = {ord("０") + i: ord("0") + i for i in range(10)}
    tbl[ord("．")] = ord(".")
    return t.translate(tbl)


# 引用动词：**强**动词出现在号之前 → 该号是引用；**弱**动词须紧跟"见"义。
REF_STRONG = re.compile(r"(参见|详见|见|按|依|据|照|引|沿用|回到|转下轮|落点|落在|违反|不符合)")
# 定义形态（依次）：
#   ① 款标题：行首 `**N.M ` 或列表项 `- **N.M `；
#   ② 子款标签：`- **N.M.K 标签**`；
#   ③ 全文任何 `N.M`（兜底，让"定义在句中"的写法也能被认）。
# 引用形态：号之前同一分句里有强引用动词，或本行没有定义形态、号却在句中被提到。
# 定义形态：行首（或列表项）`**N.M` / `**N.M.K`，号后紧跟空白或 `**`。
# `N.M.K` 也在这里一口气认下——缩进的子款（`**8.2.1 …**`）同样属定义，不是引用。
DEF_HEAD = re.compile(r"(?m)^\s*(?:[-*] )?\*\*(\d+\.\d+(?:\.\d+)?)(?=[\s*])")
DEF_SUB = re.compile(r"(?m)^\s*[-*] \*\*(\d+\.\d+\.\d+)")
ANY_NUM = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?)(?![\d.])")


def defined_clauses(s):
    """本文**真正定义过**的款号集合（`9.3`、`9.3.1`、`16.3.0` 等）。

    ⚠ 2026-10-21 冒烟抓出的两个洞，本函数因此改过两版：
      ① 初版把全文里一切 `N.M` 都算"已定义"——引用句自己把被引号注册成定义，
         **引用永远不悬空，本维等于哑的**（冒烟第一次就抓到）。
      ② 只看"行首 `**N.M`"又太窄：子款 `- **5.3.1 …**` 与句中定义全被漏掉，
         于是真文档里 16 处**假悬空**（误拦）。
    现值取两者之间：先去引用、再按三种形态收集。
    """
    t = _fold(s)
    full = set()
    for m in DEF_HEAD.finditer(t):
        full.add(m.group(1))
    for m in DEF_SUB.finditer(t):
        full.add(m.group(1))
    # 去掉引用句后，剩下的 `N.M` 才是"非引用出现"，也算定义（句中定义）
    for line in t.splitlines():
        segs = re.split(r"[。；;！？]", line)
        for seg in segs:
            if REF_STRONG.search(seg):
                continue
            for m in ANY_NUM.finditer(seg):
                full.add(m.group(1))
    return full


# ---------------------------------------------------------------- 各维


def l1_numbering(s):
    head("(L1) 条号与款号连续")
    ts = titles(s)
    if not ts:
        err("一条都没解析到——检查器自身的判据可能失效（条标题须为 `## 第 N 条`）")
        return
    arts = [n for n, _, _ in ts]
    if arts != list(range(1, len(arts) + 1)):
        # 报"第一个断点在哪"，而不是把号表整串倒出来——号表读者看不出来，断点才有用
        brk = next(((k, a) for k, a in enumerate(arts, 1) if k != a), None)
        err("条号不连续：第 %d 位应为 %d、实为 %d（共 %d 条）"
            % (brk[0], brk[0], brk[1], len(arts)))
    else:
        info("条号 1—%d 连续无缺" % len(arts))

    # 款号：同一条下自 1 连号；`N.0` 是总述位，参与连号序列（元规则明文）。
    # ⚠ 2026-10-21 冒烟抓出的洞：原判据 `^\s*(?:[-*] )?\*\*(\d+)\.(\d+)\s`
    #   会把 `**8.4.1 …` 误取成"款 8.4"（`\s` 匹配了第三个点之后的空格），
    #   于是把 8.2 改成 8.4 时**序列看上去仍是 1,2,3,4,5**，跳号被完全掩盖。
    #   现要求第二个号之后**只能是空白或 `**`**，且 `.` 也算违规形态——一并计入。
    by_art = {}
    for m in re.finditer(r"(?m)^\s*(?:[-*] )?\*\*(\d+)\.(\d+)(?=[\s*])", s):
        by_art.setdefault(int(m.group(1)), []).append(int(m.group(2)))
    bad = []
    for a, seq in sorted(by_art.items()):
        uniq = sorted(set(seq))
        if uniq and uniq != list(range(1, len(uniq) + 1)):
            bad.append((a, uniq))
    if bad:
        for a, u in bad[:5]:
            err("第 %d 条款号不连续：%s" % (a, u))
    else:
        info("款号自 1 连号（%d 条有款，含总述位 N.0）" % len(by_art))


def l2_refs(s):
    head("(L2) 引用不悬空")
    arts = {n for n, _, _ in titles(s)}
    full = defined_clauses(s)
    fence = in_fence(s)
    bad_art, bad_cl = [], []
    for i, l in enumerate(s.splitlines(), 1):
        if i in fence:
            continue
        flat = _fold(l)
        for m in re.finditer(r"第\s*(\d+)\s*条", flat):
            if int(m.group(1)) not in arts:
                bad_art.append((i, m.group(0)))
        # 数字路径式引用：`9.3`／`16.3.0`；排除版本号（v1.0.4／2026-10-20）
        for m in re.finditer(r"(?<![\d.v])(\d+)\.(\d+)(?:\.(\d+))?(?![\d.])", flat):
            num = m.group(0)
            if num in ("1.0", "1.43", "2.0", "3.0"):
                continue
            if num not in full:
                bad_cl.append((i, num))
    for i, n in bad_art[:5]:
        err("第 %d 行引用不存在的%s" % (i, n))
    if not bad_art:
        info("「第 N 条」引用全部指向存在的条")
    for i, n in bad_cl[:8]:
        err("第 %d 行引用不存在的款号 %s" % (i, n))
    if not bad_cl:
        info("数字路径式引用全部指向已定义的款（已排除版本号与围栏内）")


def _cells(line):
    """按**未转义**的 `|` 切单元格数（`\\|` 是单元格内的字面竖线，不是分列符）。

    2026-10-21 实测：原写法用 str.count("|")，把合法转义 `a \\| b` 数成两列，
    整行被误判"列数不符"——**误拦比漏报更伤**（12.4：第一天就没人用得起）。
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return len(re.split(r"(?<!\\)\|", body))


def l3_tables(s):
    head("(L3) 表格完整")
    lines = s.splitlines()
    fence = in_fence(s)
    bad, i = 0, 0
    while i < len(lines):
        l = lines[i]
        if (i + 1) < len(lines) and l.strip().startswith("|") and \
           re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]) and (i + 1) not in fence:
            ncol = _cells(l)
            if _cells(lines[i + 1]) != ncol:
                err("第 %d 行表头 %d 列、分隔行 %d 列，不符"
                    % (i + 1, ncol, _cells(lines[i + 1])))
                bad += 1
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                if _cells(lines[j]) != ncol:
                    err("第 %d 行表体列数与表头不符（%d vs %d）"
                        % (j + 1, _cells(lines[j]), ncol))
                    bad += 1
                j += 1
            if j == i + 2:
                err("第 %d 行表格只有表头与分隔行、表体为空" % (i + 1))
                bad += 1
            i = j
        else:
            i += 1
    if not bad:
        info("表格列数一致、表体非空")


def l4_residue(s, path):
    head("(L4) 专有名词与路径零残留")
    fence = in_fence(s)
    ex, bad_marks = exempt_lines(s)
    ex4 = ex["L4"]
    PAT = [
        (r"(?<![\w.])/(?:home|root|Users|opt|etc|usr|var|tmp|mnt|srv|data)/[\w./-]+",
         "unix 绝对路径"),
        (r"~/[\w./-]+", "家目录写法"),
        (r"\b[A-Za-z]:[\\/][\w./\\-]+", "盘符路径"),
        (r"\\\\[\w.-]+\\[\w.$-]+", "UNC 路径"),
    ]
    NEG = ("误写", "应为", "不得", "禁止", "反例", "→", "错例", "示例")
    hits = 0
    for i, l in enumerate(s.splitlines(), 1):
        if i in fence or i in ex4:
            continue
        if any(c in l for c in NEG):        # 举例／反例，不是真路径
            continue
        for pat, name in PAT:
            for m in re.finditer(pat, l):
                err("第 %d 行出现%s：%s" % (i, name, m.group(0)))
                hits += 1
    # 项目／内部称呼残留：本文件要能被单独拿走用，不该带本项目名字
    # 判据**从窄**：只认"像路径／像文件名"的形态。`check.py` 这种既可能是一般文件名、
    # 又可能在本文件里作为**规则名称**出现（如"`check.py` 是出包脚本"），一律算残留会误拦。
    for w in ("doc-compliance-review", "maint/", "dist/", "/DEVLOG"):
        if w in s:
            err("残留内部称呼或项目绑定字样：%s" % w)
            hits += 1
    for b in bad_marks:
        err("豁免标注无效（缺 `依据 =` 或不成对）：%s" % b)
        hits += 1
    if not hits:
        info("无本机路径、无项目绑定字样、豁免标注均有效")

    # 同目录附带的文件须真实存在（本维只管"同目录"这一种承诺）
    for m in re.finditer(r"`([\w.-]+\.py)`", s):
        if not os.path.exists(os.path.join(ROOT, m.group(1))):
            err("文中承诺同目录附带 `%s`，实际不存在于 %s" % (m.group(1), ROOT))


def l5_toc(s):
    head("(L5) 目录与正文标题一致")
    fence = in_fence(s)
    body = [l.lstrip("# ").strip() for i, l in enumerate(s.splitlines(), 1)
            if re.match(r"^#{1,3} ", l) and i not in fence]
    body_t = [t for t in body if t and t != "目录"]
    toc = [m.group(1).strip() for m in
           re.finditer(r"(?m)^\s*- \[(.+?)\]\(#", s)]
    if not toc:
        info("无目录——本维跳过")
        return
    # **只在"该进目录的标题"里比**：目录收条／附录／章；台账内部的小节
    # （`### 一、…`、`### 本文件的悬置栏…`）是层级小标题，进不进目录都算合理，
    # 强行要求会把"版本沿革写成多小节"变成违规——那不是本维要管的事（2.3.3 只管悬空）。
    def is_tocable(t):
        return bool(re.match(r"^(?:第 \d+ 条|附录 [A-Z]|本文件版本沿革)", t))
    must = [t for t in body_t if is_tocable(t)]
    missing = [t for t in toc if t not in body_t]
    extra = [t for t in must if t not in toc]
    for t in missing[:6]:
        err("目录有、正文无此标题：%s" % t)
    for t in extra[:6]:
        err("正文有、目录缺此项：%s" % t)
    if not missing and not extra:
        info("目录与正文一致（%d 个条目 / %d 个必收标题）" % (len(toc), len(must)))


def l6_format(s):
    head("(L6) 版式")
    lines = s.splitlines()
    fence = in_fence(s)
    ex, _ = exempt_lines(s)
    ex6 = ex["L6"]
    bad = 0
    # (a) 空代码块：开闭紧邻 = 内容被删空，读者无法照做
    open_at = None
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("```"):
            if open_at is None:
                open_at = i
            else:
                if i - open_at == 1:
                    err("空代码块（第 %d—%d 行）：内容被删空" % (open_at, i))
                    bad += 1
                open_at = None
    # (b) 加粗行首段落须带编号（否则无从引用）。
    #     续行判定与完整版一致：上一非空行不是空行／标题／表格／引用块／列表项 → 本行是续行。
    #     **缩进不作为续行证据**——实测那样会把"款下的加粗小节"全放过去（2026-10-21）。
    first_art = next((i for i, l in enumerate(lines, 1)
                      if re.match(r"^#{2,3} 第 1 条", l)), len(lines) + 1)
    for i, l in enumerate(lines, 1):
        if i in fence or i in ex6:
            continue
        body = l.strip()
        if body.startswith((">", "|", "#")):
            continue
        # 列表项**不强制编号**：元规则原文是"凡**加粗行首段落**必须带 `N.M`"，
        # 列表项属二级单元、自有一套 `N.M.K` 约定但不覆盖叙述型条目。
        # 2026-10-21 实测：强制后会误拦"区分度回归 15/15"这类**记录性条目**（不是规则单元）。
        if re.match(r"^\s*[-*] ", l):
            continue
        m = re.match(r"^\*\*([^*]+?)(?:。|：)?\*\*", l)   # 行首（不缩进）才算
        if not m:
            continue
        txt = m.group(1).strip()
        if re.match(r"^(?:\d+(?:\.\d+)+|A\.\d+|v\d)", txt):
            continue
        if i < first_art:                                  # 文首元信息
            continue
        if "非本规范组成部分" in l:
            continue
        # 续行：上一非空行不是块边界
        prev = ""
        for k in range(i - 2, -1, -1):
            if lines[k].strip():
                prev = lines[k].strip()
                break
        if prev and not prev.startswith(("#", "|", ">", "---", "- ", "* ")) \
           and not re.match(r"^\d+\. ", prev):
            continue
        err("第 %d 行：加粗行首段落无编号（须带 `N.M`，或以不加粗改写）：%s" % (i, txt[:32]))
        bad += 1
    # (c) 编号字符须可直接键入
    for i, l in enumerate(lines, 1):
        if i in fence:
            continue
        if re.search(r"[①-⑳]", l):
            err("第 %d 行含圆圈数字（不可直接键入，应写作 (1)(2)）" % i)
            bad += 1
    if not bad:
        info("无空代码块、加粗行首均带编号、无圆圈数字")


def l7_rowref(s):
    head("(L7) 表格行数引用不虚指")
    """`N.M 第 K 行` 须在 N.M 那张表里真有第 K 行（表头不算）。"""
    lines = s.splitlines()
    spans, cur = {}, None
    for l in lines:
        m = re.match(r"^\s*\*\*(\d+\.\d+)\s", l)
        if m:
            cur = m.group(1)
            spans.setdefault(cur, 0)
            continue
        if cur and l.strip().startswith("|") and \
           not re.match(r"^\s*\|[\s:|-]+\|\s*$", l):
            spans[cur] += 1
    spans = {k: v - 1 for k, v in spans.items() if v >= 1}   # 去表头
    fence = in_fence(s)
    ex, _ = exempt_lines(s)
    ex7 = ex["L7"]
    bad = 0
    for i, l in enumerate(lines, 1):
        if i in fence or i in ex7:
            continue
        if "示例非实指" in l:                    # 元规则允许的明示豁免
            continue
        for m in re.finditer(r"(\d+\.\d+)\s*第\s*(\d+)\s*行", l):
            key, k = m.group(1), int(m.group(2))
            if key not in spans:
                err("第 %d 行引用 %s 第 %d 行，但 %s 下无表格" % (i, key, k, key))
                bad += 1
            elif k > spans[key]:
                err("第 %d 行引用 %s 第 %d 行，但该表只有 %d 行" % (i, key, k, spans[key]))
                bad += 1
    if not bad:
        info("表格行引用不虚指")


def l0_guard():
    """(L0) 判据失效自检：给每维喂一份**必错样本**，不报错即判该维哑了。

    为什么不靠"运行时是否报过错"：干净文档下所有维都不报错，那样判不了哑。
    改为注入必错样本——某维对"一定有错"的微文档放行，就是它自己的报错路径被删了（12.3）。
    """
    head("(L0) 判据失效自检")
    probes = [
        ("L1", l1_numbering, "## 第 1 条 甲\n\n## 第 3 条 丙\n"),
        ("L2", l2_refs, "## 第 1 条 甲\n\n见第 9 条。\n"),
        ("L3", l3_tables, "| a | b |\n|---|---|\n| 1 |\n"),
        ("L6", l6_format, "## 第 1 条 甲\n\n```\n```\n"),
    ]
    dead = []
    for name, fn, doc in probes:
        if _quiet(fn, doc) == 0:
            dead.append(name)
    if _quiet(l5_toc, "## 甲\n\n- [不存在](#x)\n") == 0:
        dead.append("L5")
    if _quiet(l4_residue, "见 /root/secret/x.txt\n", "probe.md") == 0:
        dead.append("L4")
    if _quiet(l7_rowref, "**1.1 甲。**\n\n| a |\n|---|\n| 1 |\n\n见 1.1 第 5 行。\n") == 0:
        dead.append("L7")
    if dead:
        err("(L0) 判据失效：维度 %s 对必错样本不报错——该维的报错路径可能被删了"
            % "、".join(dead))
    else:
        info("七维对注入的必错样本均当场报错（探针每维跑一次，共 7 次注入）")


def _quiet(fn, *a):
    """静默跑一次维度函数，返回它报了几条错——**报错不进正式清单**。

    探针是给 (L0) 自己用的假样本，它的错误**不属于被检文档**。
    2026-10-21 实测：初版把探针的 err() 混进了 ERR，于是"七维全过"之后
    报告仍列着 7 条属于假样本的错误——**守卫自己制造假错**，比不查更糟。
    故此处临时替换掉全局 ERR：探针只数数，不记账。
    """
    import contextlib
    import io
    global ERR
    saved, ERR = ERR, []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fn(*a)
        return len(ERR)
    finally:
        ERR = saved


def self_test():
    """`--self-test`：**给本检查器自己做的冒烟**（不是检文档）。

    17 个注入用例：每次把一份真实铁律改坏一处（删条、款号跳号、引用悬空、
    表少列、表体删空、分隔行不符、写死路径、塞项目名、目录编／删项、空代码块、
    加粗无编号、圆圈数字、表格行虚指…），断言**该维当场报错**；
    7 个打瘸用例：把某维的 `err(` 全改成 `info(`（该维变哑），断言 (L0) 报"判据失效"。

    为什么这段要长在检查器里而不是另写一个脚本：**守卫要能被单独拿走验**（12.3）——
    使用者拿到这一个文件，就能自己证明"它真的会报错"，不必相信作者的截图。
    """
    import shutil
    import subprocess
    import tempfile
    base = os.path.join(ROOT, "DEV-RULES-LITE.md")
    if not os.path.isfile(base):
        print("[E] 找不到 DEV-RULES-LITE.md，无法自测（须与本文件同目录）")
        return 2
    SRC = open(base, encoding="utf-8").read()

    def run(text, tool=None):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "t.md")
            open(p, "w", encoding="utf-8").write(text)
            shutil.copy(tool or __file__, os.path.join(d, "lite-selfcheck.py"))
            r = subprocess.run([sys.executable, tool or os.path.abspath(__file__), p],
                               capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        finally:
            shutil.rmtree(d)

    def mut(old, new):
        assert old in SRC, "变异失败：原文不匹配 → %s" % old[:40]
        return SRC.replace(old, new, 1)

    def widen_sep(text):
        ls = text.splitlines(keepends=True)
        for k in range(1, len(ls)):
            if ls[k].strip() == "|---|---|":
                ls[k] = "|---|---|---|\n"
                return "".join(ls)
        raise AssertionError("变异失败：找不到两列表的分隔行")

    E = "## 第 1 条 适用与效力\n"
    cases = [
        ("删掉一整条", "条号不连续",
         re.sub(r"## 第 7 条[^\n]*\n.*?(?=## 第 8 条)", "", SRC, flags=re.S)),
        ("款号跳号", "款号不连续", mut("**8.2 ", "**8.4 ")),
        ("引用不存在的条", "第 77 条", mut(E, E + "\n见第 77 条。\n")),
        ("引用不存在的款", "9.9", mut(E, E + "\n见 9.9 的做法。\n")),
        ("表体少一列", "列数与表头不符",
         mut("| **部分** | 一部分可自动检，另一部分只能人工 |", "| **部分** |")),
        ("表体整段删空", "表体为空",
         re.sub(r"(\|[^\n]*\|\n\|[\s:|-]+\|\n)(?:\|[^\n]*\|\n)+", r"\1", SRC, count=1)),
        ("分隔行与表头不符", "分隔行", widen_sep(SRC)),
        ("写进 unix 绝对路径", "unix 绝对路径", mut(E, E + "\n存于 /opt/proj/docs。\n")),
        ("写进盘符路径", "盘符路径", mut(E, E + "\n另见 D:\\work\\a.md。\n")),
        ("塞回项目绑定字样", "doc-compliance-review",
         mut(E, E + "\ndoc-compliance-review 里这么写。\n")),
        ("承诺附带却不存在的脚本", "实际不存在", mut(E, E + "\n另附 `ghost-tool.py`。\n")),
        ("目录编一条", "正文无此标题",
         mut("- [第 1 条 适用与效力](#第-1-条-适用与效力)\n",
             "- [第 1 条 适用与效力](#第-1-条-适用与效力)\n- [第 99 条 幽灵](#第-99-条)\n")),
        ("目录删一条", "目录缺此项", mut("- [第 4 条 冲突先查文本](#第-4-条-冲突先查文本)\n", "")),
        ("空代码块", "空代码块", mut(E, E + "\n```\n```\n")),
        ("加粗行首无编号", "加粗行首段落无编号", mut(E + "\n", E + "\n**没有编号的加粗。**\n\n")),
        ("圆圈数字", "圆圈数字", mut(E, E + "\n① 二 ③\n")),
        ("表格行虚指", "该表只有", mut(E, E + "\n见 8.2 第 99 行。\n")),
    ]
    print("=" * 66)
    print("lite-selfcheck 冒烟：%d 个注入用例 ＋ 7 个打瘸用例" % len(cases))
    print("=" * 66)
    fails = 0
    for name, want, text in cases:
        rc, out = run(text)
        ok = rc == 1 and want in out
        print("  [%s] %-24s → 须报「%s」" % ("OK" if ok else "NG", name, want))
        if not ok:
            fails += 1

    print("\n打瘸检查器自身（该维的 err 全改 info，须由 (L0) 报「判据失效」）：")
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    for fn in ("l1_numbering", "l2_refs", "l3_tables", "l4_residue",
               "l5_toc", "l6_format", "l7_rowref"):
        i = src.index("def %s(" % fn)
        j = src.index("\ndef ", i + 5)
        crippled = src[:i] + src[i:j].replace("err(", "info(") + src[j:]
        d = tempfile.mkdtemp()
        try:
            cp = os.path.join(d, "lite-selfcheck.py")
            open(cp, "w", encoding="utf-8").write(crippled)
            rc, out = run(SRC, tool=cp)
        finally:
            shutil.rmtree(d)
        ok = rc == 1 and "判据失效" in out
        print("  [%s] 打瘸 %-14s → (L0) %s" % ("OK" if ok else "NG", fn,
                                              "当场报失效" if ok else "没发现！"))
        if not ok:
            fails += 1
    print("\n" + "=" * 66)
    if fails:
        print("冒烟未通过：%d 个用例没被拦住（守卫有洞，不是文档有错）" % fails)
        return 1
    print("冒烟通过：%d 个注入用例全部拦住，7 个打瘸点全部由 (L0) 发现" % len(cases))
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        return self_test()
    if len(sys.argv) < 2:
        print("用法：python3 lite-selfcheck.py DEV-RULES-LITE.md")
        print("      python3 lite-selfcheck.py --self-test   # 给检查器自己做冒烟")
        return 2
    p = sys.argv[1]
    if not os.path.isfile(p):
        print("[E] 找不到文件：%s" % p)
        return 2
    try:
        s = open(p, encoding="utf-8").read()
    except UnicodeDecodeError:
        print("[E] 不是 UTF-8 文本：%s" % p)
        return 2

    print("%s · 自洽检查" % os.path.basename(p))
    print("=" * 62)
    l0_guard()
    l1_numbering(s)
    l2_refs(s)
    l3_tables(s)
    l4_residue(s, p)
    l5_toc(s)
    l6_format(s)
    l7_rowref(s)
    print("\n" + "=" * 62)
    if ERR:
        print("未通过：错误 %d 项、警告 %d 项" % (len(ERR), len(WARN)))
        for e in ERR[:12]:
            print("  · " + e)
        return 1
    # 警告同样须逐条列出——只报计数等于让读者自己去数（(L0) 之外的路径，不会混入探针）
    if WARN:
        print("自洽检查通过：错误 0 项、警告 %d 项（逐条如下）" % len(WARN))
        for w in WARN:
            print("  · " + w)
    else:
        print("自洽检查通过：错误 0 项、警告 0 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
