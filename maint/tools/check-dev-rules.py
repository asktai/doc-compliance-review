#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发工程规范（铁律）· 全文自检（六维）
==============================================================================
对 `dev/DEV-RULES.md` 做机械自检，覆盖六个维度：

  (1) 结构        条号连续、**条标题格式统一**、章序号连续、章区间声明与覆盖
  (2) 导读表      文首"三条铁律"导读表的条号与名称，须与正文标题一致（双源比对）
  (3) 条号引用    引用的条号必须存在（悬空引用即报错）；--refs 另打印引用上下文供人工复核
  (4) 用词        已废止词（维护侧／开发端／实例侧等）不得在正文残留；术语说明语境除外
  (5) 表述        不得使用相对引用（"见下方"等）；日期月／日须补零；编号须可键入；条以下用十进制路径（禁 1.／(N)）；路径须连号；「表述纪律」条自身反例除外
  (6) 路径真实性  正文反引号中的文件／目录引用必须真实存在

归属说明
    · 本脚本属于**维护侧**（`/workspace/dev/maint/tools/`），**不随技能包分发**；
    · 与 `make-card.py` 同类：开发侧工具，不进包、不参与发布链。

为什么要它（铁律第 16 条）
    "能做成自动守卫的，就不要只靠人跑一次。"——**铁律自身也受此条约束**。
    2026-09-29 实测教训：首版检查用的是"人工 ＋ 临时脚本"，当场暴露两类问题——
    (1) 临时脚本**自身 4 处 bug**（正则漏抓、`str(i) in nums` 类型错、区间误计、路径白名单不全），
       每次都**先报出"问题"、经核实才知是误报**；
    (2) 第 3 条标题格式不统一（条号后缺空格）**长期潜伏**，正是它让脚本正则漏抓该条。
    结论：**检查工具本身也必须被验证**（第 16 条"守卫自身也要验证"）。故本脚本：
    保持零依赖、写法保守（凡拿不准一律不报），并以注入式负向测试验证过"真拦得住"。

用法
    python3 maint/tools/check-dev-rules.py                  # 六维检查
    python3 maint/tools/check-dev-rules.py --refs           # 另打印条号引用上下文（供人工复核指向）
    python3 maint/tools/check-dev-rules.py --install-hook   # 安装 pre-commit 钩子（只警告、不阻断）
    python3 maint/tools/check-dev-rules.py --quiet          # 只输出结论行

退出码
    0 ＝ 无错误；1 ＝ 有错误（可供 CI 使用）

    钩子为**只警告**模式：检出问题会打印，但**不阻断提交**——
    避免脚本自身万一有 bug 时卡死提交流程（本轮已实证脚本会出错）。
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))            # /workspace/dev
RULES = os.path.join(DEV, "DEV-RULES.md")
SKILL = os.path.join(DEV, "doc-compliance-review")
RUN = os.path.expanduser("~/.codebuddy/skills/doc-compliance-review")
# 跨侧比对时排除的项，与 publish.py 的 EXCLUDE 保持一致
# （生成物只应存在于运行实例，且 .git 等本就不该同步）
EXCLUDE = {".git", "__pycache__", ".DS_Store",
           ".integrity.json", "_rules-baseline.json", "_smoke-baseline.json"}
DIST = "/workspace/dist"
HOOK_SRC = os.path.join(HERE, "hooks", "pre-commit")
HOOK_DST = os.path.join(DEV, ".git", "hooks", "pre-commit")

# 已废止词 → 替代词（术语纪律 A.3）。"用户"单列：仅正文禁用，附录术语说明除外。
BANNED = {"维护侧": "开发侧", "开发端": "开发侧", "实例侧": "运行实例", "文献分工": None}
# 相对引用禁语（第 19 条第 2 项）
REL_REFS = ["见下", "如上所述", "前面那", "如图所示", "如后所述", "同下"]

ERRS, WARNS, INFOS = [], [], []
QUIET = False


def err(m):
    ERRS.append(m)
    if not QUIET:
        print("  [E] " + m)


def warn(m):
    WARNS.append(m)
    if not QUIET:
        print("  [W] " + m)


def info(m):
    INFOS.append(m)
    if not QUIET:
        print("  [i] " + m)


def ok(m):
    if not QUIET:
        print("  [OK] " + m)


def no_of(s, keyword):
    """按「条标题含关键词」动态取条号——**不写死条号**，挪号后自动跟上。

    教训：本脚本曾把「第 19 条」写死用于排除反例，V1.24.0 该条挪为第 20 条后，
    排除立即失效、连报 3 项误报（把该条自己的反例当成真问题）。
    """
    m = re.search(r"^### 第 (\d+) 条 [^\n]*" + re.escape(keyword), s, re.M)
    return int(m.group(1)) if m else None


def section_by_kw(s, keyword):
    n = no_of(s, keyword)
    return section(s, "### 第 %d 条" % n) if n else ""


def head(t):
    if not QUIET:
        print(t)


# ────────────────────────────── 工具 ──────────────────────────────

def read():
    if not os.path.exists(RULES):
        print("[E] 未找到规范文件：%s" % RULES)
        sys.exit(1)
    with open(RULES, encoding="utf-8") as f:
        return f.read()


def title_rows(s):
    """全部条标题：(条号, 条号后的原文)。**故意不要求条号后有空格**，
    否则格式一旦不统一就会漏抓该条（2026-09-29 踩过的坑）；格式问题由 (1) 单独报出。"""
    return [(int(n), rest) for n, rest in re.findall(r"^### 第 (\d+) 条(.*)$", s, re.M)]


def section(s, start_mark):
    """取从 start_mark 到下一个同级或更高级标题之间的文本。"""
    i = s.find(start_mark)
    if i < 0:
        return ""
    j = re.search(r"^#{2,3} ", s[i + len(start_mark):], re.M)
    return s[i:] if not j else s[i:i + len(start_mark) + j.start()]


def in_fence_lines(s):
    """返回被 ``` 围栏包裹的行号集合（这些行不参与"路径引用"检查）。"""
    fenced, inside, buf = set(), False, []
    for i, line in enumerate(s.splitlines(), 1):
        if line.strip().startswith("```"):
            if inside:
                fenced |= set(buf)
                buf = []
            inside = not inside
            continue
        if inside:
            buf.append(i)
    return fenced


# ────────────────────────────── (1) 结构 ──────────────────────────────

def check_structure(s):
    head("(1) 结构")
    rows = title_rows(s)
    if not rows:
        err("未找到任何条标题（`### 第 N 条`）")
        return
    nums = [n for n, _ in rows]
    exp = list(range(1, len(nums) + 1))
    if nums != exp:
        miss = [i for i in exp if i not in nums]
        dup = sorted({n for n in nums if nums.count(n) > 1})
        err("条号不连续：实际 %s；缺号 %s；重号 %s" % (nums, miss or "无", dup or "无"))
    else:
        info("条号 1—%d 连续无缺" % len(nums))

    bad_fmt = [n for n, rest in rows if rest and not rest.startswith(" ")]
    if bad_fmt:
        err("条标题格式不统一（条号后缺空格）：第 %s 条；应写作 `### 第 N 条 标题`"
            "（此格式会让按 `第 N 条␣` 匹配的工具漏抓该条）" % "、".join(map(str, bad_fmt)))
    else:
        info("条标题格式统一（条号后均有空格）")

    CN = "一二三四五六七八九十"
    chaps = re.findall(r"^## 第(.+?)章", s, re.M)
    want = [CN[i] for i in range(len(chaps))]
    if chaps != want:
        err("章序号不连续：实际 %s；应为 %s" % (chaps, want))
    else:
        info("章序号一至%s连续" % want[-1])

    # 章区间标注：支持两种形态——区间「（第 A—B 条）」与单条「（第 N 条）」
    # （单条章如第七章，只有一个条号，不写成 "21—21"）
    rng = []
    for name, a, b in re.findall(r"^## (第.+?章) .*?（第 (\d+)—(\d+) 条）\s*$", s, re.M):
        rng.append((name, int(a), int(b)))
    for name, a in re.findall(r"^## (第.+?章) .*?（第 (\d+) 条）\s*$", s, re.M):
        rng.append((name, int(a), int(a)))
    for name, a, b in rng:
        have = [n for n in nums if a <= n <= b]
        if len(have) != b - a + 1:
            err("章区间不实：%s 声明第 %s—%s 条，实际仅 %s" % (name, a, b, have or "无"))
    # 区间不得重叠：同一条被两章认领 = 章归属矛盾（本轮负向测试暴露的盲区）
    seen, reported = {}, set()
    for name, a, b in rng:
        for n in range(a, b + 1):
            if n in seen and n not in reported:
                err("章区间重叠：第 %d 条同时被 %s 与 %s 覆盖" % (n, seen[n], name))
                reported.add(n)
            else:
                seen.setdefault(n, name)
    covered = set()
    for _, a, b in rng:
        covered |= set(range(a, b + 1))
    uncov = sorted(set(nums) - covered)
    if uncov:
        err("有条未被任何章区间覆盖：%s（该章标题缺「（第 X—Y 条）」标注）" % uncov)
    else:
        info("章区间覆盖全部条、互不重叠（共 %d 个章带区间标注）" % len(rng))


# ────────────────────────────── (2) 导读表 ──────────────────────────────

def check_guide(s):
    head("(2) 导读表 vs 正文（双源比对）")
    body = {n: rest.strip() for n, rest in title_rows(s) if rest.strip()}
    rows = re.findall(r"^\| \*\*第 (\d+) 条\*\* \| (.+?) \| (.+?) \|\s*$", s, re.M)
    if not rows:
        err("未找到文首导读表（`| **第 N 条** | 名称 | 一句话 |`）")
        return
    for n, name, _ in rows:
        n = int(n)
        if n not in body:
            err("导读表引用第 %d 条，但正文无此条" % n)
        elif name.strip() not in body[n]:
            err("导读表「%s」与正文标题「%s」不符（第 %d 条）" % (name, body[n], n))
        else:
            info("第 %d 条：导读与正文一致" % n)


# ────────────────────────────── (3) 条号引用 ──────────────────────────────

def check_refs(s, show=False):
    head("(3) 条号引用")
    nums = {n for n, _ in title_rows(s)}
    dangling = sorted({int(r) for r in re.findall(r"第 (\d+) 条", s)} - nums)
    if dangling:
        err("悬空引用（指向不存在的条）：%s" % dangling)
    else:
        info("无悬空引用（全部指向存在的条）")
    if show and not QUIET:
        print("  ── 引用上下文（供人工复核**指向是否正确**，脚本查不出语义）──")
        fenced = in_fence_lines(s)
        for i, line in enumerate(s.splitlines(), 1):
            if i in fenced or line.lstrip().startswith("- ["):   # 排除代码块与目录
                continue
            if re.search(r"第 \d+ 条|(?<!V)(?<![\d.])\d+\.\d+(?![\d.])", line):
                print("     %4d│ %s" % (i, line.strip()[:96]))


# ────────────────────────────── (4) 用词 ──────────────────────────────

def tail_lines(s, mark):
    """返回以 mark 开头的行**及其之后所有行**的行号集合。

    用于"某节一直延伸到文件末"的场景（如附录 A）——此时不能用 `section()`：
    它取到下一个 `#{2,3} ` 标题为止，而 `## 附录 A` 的下一个标题是 `### A.1`，
    结果只取到一行，附录内部反而没被排除（2026-09-29 实测踩过）。
    """
    lines = s.splitlines()
    for i, l in enumerate(lines, 1):
        if l.startswith(mark):
            return set(range(i, len(lines) + 1))
    return set()


def check_wording(s):
    head("(4) 用词（术语纪律）")
    lines = s.splitlines()
    a3 = tail_lines(s, "### A.3")        # A.3「术语纪律」含废止词表，属**必要保留**
    app_a = tail_lines(s, "## 附录 A")   # 附录 A 全节都在讲术语，同样豁免「用户」

    for w, rep in BANNED.items():
        hits = []
        for i, l in enumerate(lines, 1):
            if i in a3:
                continue
            # 只查**裸用**：排除被更长术语包含的情形（如「运行实例侧」含「实例侧」）
            if re.search(r"(?<!运行)" + re.escape(w), l):
                hits.append(i)
        if hits:
            err("已废止词「%s」在正文残留（第 %s 行）；应改用「%s」"
                % (w, "、".join(map(str, hits)), rep or "见 A.3"))
    if not any(re.search(r"(?<!运行)" + re.escape(w), "\n".join(
            l for i, l in enumerate(lines, 1) if i not in a3)) for w in BANNED):
        info("废止词（%s）正文零残留（已排除 A.3 废止词表本身）" % "、".join(BANNED))

    u = [i for i, l in enumerate(lines, 1) if "用户" in l and i not in app_a]
    if u:
        err("「用户」在正文残留（第 %s 行）；指开发者时用「开发者」，指使用者时用「技能使用者」"
            % "、".join(map(str, u)))
    else:
        info("「用户」仅出现于附录 A 术语说明（必要时保留）")


# ────────────────────────────── (5) 表述 ──────────────────────────────

def check_expression(s):
    head("(5) 表述（相对引用／日期形态／编号形态与连续性）")
    seg = section_by_kw(s, "表述纪律")   # 该条表格内是**反例**，须排除（按关键词定位，不写死条号）
    body = s.replace(seg, "") if seg else s

    # 引号内豁免：引号里的软指代是**列举反例**（如 A.4「禁用软指代（"见下款"…）」），
    # 属"提到那个说法"而非"使用那个说法"——与 (7) 版本串守卫同一判据。
    def _strip_quotes(x):
        return re.sub(r"[“\"]([^”\"]*)[”\"]", "", x)

    hits = [l.strip()[:70] for l in body.splitlines()
            if any(p in _strip_quotes(l) for p in REL_REFS)]
    if hits:
        for h in hits:
            err("相对引用（应为绝对编号，如「见第 %d 条」）：%s" % (no_of(s, "分发包命名") or 0, h))
    else:
        info("无相对引用（%s）" % "／".join(REL_REFS))

    bad_d = []
    for i, l in enumerate(body.splitlines(), 1):
        for m in re.finditer(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", l):
            if len(m.group(2)) != 2 or len(m.group(3)) != 2:
                bad_d.append("第 %d 行 %s" % (i, m.group(0)))
    if bad_d:
        err("日期月／日未补零：%s" % "；".join(bad_d))
    else:
        info("日期形态无未补零项")

    # 编号须用**可直接键入**的字符（表述纪律第 8 项）：不得用圆圈数字等特殊符号
    sp = re.findall(r"[①-⑩⑴-⑽㈠-㈩]", body)
    if sp:
        err("使用了难以键入的特殊编号字符（表述纪律第 8 项）：%s —— 应改用 (1)(2)(3)…"
            % "".join(sorted(set(sp))))
    else:
        info("编号字符均可直接键入（无圆圈数字等特殊符号）")

    # 旧编号形态（1.／(N)）已废止：编号体系要求条以下一律十进制路径
    fence = in_fence_lines(s)
    seg_lines = set()
    if seg:
        off = s.index(seg)
        first = s[:off].count("\n") + 1
        seg_lines = set(range(first, first + len(seg.splitlines()) + 1))
    lines_all = s.splitlines()
    ind_code = set()
    for i, l in enumerate(lines_all):
        if i > 0 and lines_all[i - 1].strip() == "" and re.match(r"^( {4,}|\t)\S", l):
            ind_code.add(i + 1)
    bad_old = []
    for i, l in enumerate(lines_all, 1):
        if i in fence or i in seg_lines or i in ind_code:
            continue
        if re.match(r"^[ \t]*(?:\d+\.|\(\d+\))[ \t]", l):
            bad_old.append("第 %d 行 %s" % (i, l.strip()[:44]))
    if bad_old:
        err("仍在使用旧编号形态 1.／(N)（编号体系：条以下用十进制路径 N.M(.K)）：%s" % "；".join(bad_old))
    else:
        info("编号形态合规（无 1.／(N) 旧形态）")

    # 路径连续性：N.M / N.M.K / N.M.K.L 同级须自 1 连号、不跳号、不重号
    # **例外**：`N.0` 为"总述位"（见铁律编号体系"唯一例外"条）——某条需在首个子项
    # 之前先作总述时用 `N.0`，其后子项仍自 `N.1` 起连号。故同级序列允许
    # `[0,1,...,n]`（0 至多一个且必在首位）或 `[1,...,n]`。
    kids = {}
    for m in re.finditer(r"(?m)^(?: {0,2}- )?\*\*((?:\d+|A\.\d)(?:\.\d+)+)(?:\s|\*\*)", s):
        path = m.group(1); parent, child = path.rsplit(".", 1)
        kids.setdefault(parent, []).append(int(child))
    bad_path = []
    for par, v in sorted(kids.items()):
        sv = sorted(v)
        # 合法形态一：自 1 连号
        ok = sv == list(range(1, len(sv) + 1))
        # 合法形态二：0 在首位且其后自 1 连号（总述位）
        if not ok and sv and sv[0] == 0:
            ok = sv[1:] == list(range(1, len(sv)))
        if not ok:
            bad_path.append("%s → %s" % (par, sv))
    if bad_path:
        err("路径编号不连续或重号：%s" % "；".join(bad_path))
    else:
        info("路径编号连续（%d 组父级，均自 1 连号；含总述位 `N.0` 例外）" % len(kids))


# ────────────────────────────── (6) 路径真实性 ──────────────────────────────

def check_paths(s):
    head("(6) 路径引用真实性")
    fenced = in_fence_lines(s)
    cands = set()
    for i, line in enumerate(s.splitlines(), 1):
        if i in fenced:
            continue
        for c in re.findall(r"`([^`\n]+)`", line):
            c = c.strip()
            if " " in c or not c:
                continue
            if re.search(r"[\\*?]", c):
                continue
            if "/" in c or re.match(r"^[\w\-.·]+\.(md|py|json|SKILL|zip|Skill)$", c):
                cands.add(c)

    # 纯扩展名不是路径
    exts = {".Skill", ".zip", ".py", ".md", ".json"}
    prefix = {"dev/": DEV + "/", "maint/": DEV + "/maint/", "dist/": DIST + "/",
              "~/.codebuddy/skills/": RUN + "/", "scripts/": SKILL + "/scripts/"}
    search = [DEV, os.path.join(DEV, "maint"), SKILL, os.path.join(SKILL, "scripts"),
              os.path.join(SKILL, "core"), os.path.join(SKILL, "assets")]
    missing = []
    for c in sorted(cands):
        if c in exts:
            continue
        p = None
        for k, v in prefix.items():
            if c.startswith(k):
                p = v + c[len(k):]
                break
        if p is None and c.startswith("~"):
            p = os.path.expanduser(c)
        if p is None:
            for d in search:
                if os.path.exists(os.path.join(d, c)):
                    p = os.path.join(d, c)
                    break
            else:                                  # 纯文件名，逐个目录找
                if re.match(r"^[\w\-.·]+\.(md|py|json)$", c):
                    missing.append(c)
                continue
        if p and not os.path.exists(p):
            missing.append("%s → %s" % (c, p))
    if missing:
        for m in missing:
            err("路径引用不存在：%s" % m)
    else:
        info("路径／文件引用 %d 项全部真实存在（已排除围栏代码块与纯扩展名）" % len(cands))


# 开发侧需要跟随铁律版本号的文档（真源＝DEV-RULES.md 顶部版本行）
VER_FILES = ["maint/DEVLOG.md", "CHANGELOG.md", "publish.py"]
# 只匹配"当前状态陈述"：现 **Vx.y.z** ／ 当前 **Vx.y.z**（历史流水里的旧值不算）
VER_RE = re.compile(r"(?:现|当前)\s*\*{0,2}([Vv]\d+\.\d+\.\d+)\*{0,2}")


def check_rules_version(s):
    """(7) 铁律版本串跨文档一致性。

    真源＝DEV-RULES.md 顶部"**版本 vx.y.z**"。开发侧文档里凡以"**现** vx.y.z／
    **当前** vx.y.z"形式陈述**当前**铁律版本的，必须与真源一致。

    **只查各文档的文件头**（顶部 40 行）：文件头写的是"当前状态"，必须准；
    正文属历史流水，"v1.0.0 时…"是当时记录，不查——否则每篇历史条目都会误报
    （范围过宽是第一次写这个守卫时踩的坑）。

    **引号内豁免**：文中**引述**历史值时会带引号（如 `停留在"现 v1.22.0"`），
    这类是"提到那个字符串"而非"声明当前版本"，一律不判——与第 20 条"指代明确"
    同理：引号即"这是转述"的标记。
    教训：DEVLOG 文件头"现 v1.22.0"长期未随真源更新，脚本此前只扫本文件内部，查不出漂移。

    **大小写**：v1.32.0 起铁律版本写法由大写 V 改为小写 v，故正则用 `[Vv]` 兼容，
    比对时**逐字**比较（大小写不同即报错）——这样"真源写了小写、文档还留大写"
    的漂移同样能拦下（第 20 条：口径须全处一致）。
    """
    head("(7) 铁律版本串一致性（跨开发侧文档·限文件头）")
    m = re.search(r"\*\*版本 ([Vv]\d+\.\d+\.\d+)\*\*", s)
    if not m:
        err("未能从真源解析铁律版本（顶部应为「**版本 vx.y.z**」）")
        return
    truth = m.group(1)
    HEAD_LINES = 40
    bad = []
    for rel in VER_FILES:
        p = os.path.join(DEV, rel)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if i > HEAD_LINES:
                    break
                # 只在"铁律"语境行上比对，避免误抓技能自身版本号
                if "铁律" not in line:
                    continue
                # 引号内的版本串＝引述历史值，剔除后再查
                stripped = re.sub(r"[“\"]([^”\"]*)[”\"]", "", line)
                for got in VER_RE.findall(stripped):
                    if got != truth:
                        bad.append("%s:%d 铁律版本 %s ≠ 真源 %s" % (rel, i, got, truth))
    if bad:
        for b in bad:
            err(b)
    else:
        info("真源 %s；开发侧 %d 份文档文件头的铁律版本串一致" % (truth, len(VER_FILES)))


# ────────────────────── (8) 跨侧漂移（开发侧 ↔ 运行实例） ──────────────────────

def check_cross_side(s_ignored=None):
    """开发侧与运行实例比对——**须排除运行侧生成物**。

    实查（2026-10-13）：开发侧 66 个文件、运行实例 69 个，差 3 个正是运行侧生成物
    （`_rules-baseline.json`、`.integrity.json`、`_smoke-baseline.json`）——
    它们**只应存在于运行实例**，故不能全量比对，须按 EXCLUDE 排除后再比。
    比对内容：应镜像文件的**相对路径 ＋ sha256**。
    """
    head("(8) 跨侧一致性（开发侧 ↔ 运行实例）")
    if not os.path.isdir(RUN):
        info("运行实例不存在（未装机），跳过——不视为漂移")
        return
    import hashlib

    def digest(p):
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    drift = []
    dev_files = {}
    for root, dirs, files in os.walk(SKILL):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for fn in files:
            if fn in EXCLUDE:
                continue
            fp = os.path.join(root, fn)
            dev_files[os.path.relpath(fp, SKILL)] = fp
    for rel, fp in sorted(dev_files.items()):
        rp = os.path.join(RUN, rel)
        if not os.path.exists(rp):
            drift.append("运行实例缺此文件：%s" % rel)
        elif digest(fp) != digest(rp):
            drift.append("两侧不一致：%s" % rel)
    if drift:
        for d in drift[:10]:
            err(d)
        if len(drift) > 10:
            err("……另有 %d 处，不逐一列出" % (len(drift) - 10))
    else:
        info("开发侧 %d 个文件与运行实例一致（已排除运行侧生成物）" % len(dev_files))


# ────────────────────── (9) 目录锚点一致性 ──────────────────────

def _gh_anchor(n, title):
    """按 GitHub 规则由条标题重算锚点（已实测：现目录 20 条 20/20 吻合）。"""
    t = title.lower()
    t = re.sub(r"[（）、，：；／·]", "", t)
    return "第-%d-条-%s" % (n, t.replace(" ", "-"))


def check_toc_anchor(s):
    """(9) 目录的条标题／锚点须与正文同步。

    目录是正文标题的**引用**——标题改了目录没改，即引用漂移（2.3.3）。
    V1.30.0 改第 2 条标题时目录未跟，而当时七维查不出（只查条号连续性）。
    """
    head("(9) 目录锚点一致性")
    toc = re.findall(r"^\s*- \[第 (\d+) 条 ([^\]]+)\]\(#([^)]+)\)", s, re.M)
    if not toc:
        info("无目录（跳过）")
        return
    body = {n: rest.strip() for n, rest in title_rows(s)}
    bad = []
    for ns, title, anchor in toc:
        n = int(ns)
        bt = body.get(n)
        if bt is None:
            bad.append("目录有第 %d 条，正文无此条" % n)
            continue
        if bt != title:
            bad.append("第 %d 条：目录「%s」≠ 正文「%s」" % (n, title, bt))
            continue
        exp = _gh_anchor(n, title)
        if exp != anchor:
            bad.append("第 %d 条：锚点 `#%s` ≠ 重算 `#%s`" % (n, anchor, exp))
    if len(toc) != len(body):
        bad.append("目录 %d 条 ≠ 正文 %d 条" % (len(toc), len(body)))
    if bad:
        for b in bad:
            err(b)
    else:
        info("目录 %d 条的标题与锚点均与正文一致" % len(toc))


# ────────────────────── (10) 引用锚点完整性 ──────────────────────

def check_ref_anchor(s):
    """(10) 引用表格行须带父级。

    铁律 2.3.3「引用漂移」含"语义已变"，而语义**无法自动化**（脚本做不到）。
    本项只覆盖其中**可自动化的形态部分**：引用表格行时须写 `N.M 第 K 行`，
    不得裸写"第 K 行"（不知是哪张表）——正是历史事故的形态（第 14 条"（第 4 行）"）。
    **语义理解仍靠人工复核（17.4），本项不覆盖，也不得据本项通过而认为该类已闭合。**
    """
    head("(10) 引用锚点完整性（表格行引用须带父级）")
    fenced = in_fence_lines(s)
    seg = section_by_kw(s, "表格例外")          # 该处是规则说明，含反例，排除
    bad = []
    for i, line in enumerate(s.splitlines(), 1):
        if i in fenced or (seg and line in seg.splitlines()):
            continue
        if line.lstrip().startswith(("- [", "|", ">")):   # 目录／表格／引用块里的举例跳过
            continue
        # 裸写"第 N 行"（前面既非 `N.M` 也非条级"第 N 条"／`N`）→ 违规。
        # **父级有两种合法形态**：款级 `17.3`、条级 `14` 或 `第 14 条`（实测都出现过）。
        for m in re.finditer(r"(?<![\.\d])(?<!M )第 (\d+) 行", line):
            pre = line[:m.start()]
            ok_parent = re.search(r"(?:\d+\.\d+|\d+)\s*$", pre) or re.search(r"第\s*\d+\s*条\s*$", pre)
            if not ok_parent:
                bad.append("第 %d 行：裸写「第 %s 行」，应带父级（如 `17.3 第 %s 行`）：%s"
                           % (i, m.group(1), m.group(1), line.strip()[:60]))
    if bad:
        for b in bad:
            err(b)
    else:
        info("表格行引用均带父级（无语义判定——语义仍靠人工复核）")


# ──────────────────── (11) 加粗行首段落须带编号 ────────────────────

def check_bold_heading(s):
    """(11) 凡"行首加粗段落"，须带 `N.M` 编号（编号体系／书写段规则的守卫）。

    规则（DEV-RULES.md「书写」段）：**行首加粗即声明"这是一个编号单元"**，
    故加粗行首段落必须带 `N.M`（`N` 为条号或章号），不得以加粗冒充小标题。

    背景：V1.30.3 曾靠**人工截图**才发现 11 处无编号加粗段落；做本守卫时又查出
    **9 处更隐蔽的**（真·段落起点而无编号）。**人眼与裸 grep 均会漏，故必须固化。**

    放行（不算违规）：
    - 带编号者：`**N.M …**`、`**N.M.K …**`、`**A.N …**`、`**N.0 …**`（0 为总述位）；
    - **续行**：上一非空行不是空行／标题／表格／引用块，即本行是上句的继续，非段落起点；
    - **文件头元信息**（首 40 行内、含 `｜` 或"导读"者）；
    - **导读区**（第 1 条之前）：该区本就声明"不属编号单元"（见「导读说明」行）；
    - **明确声明游离的段**：加粗文字中含"非本规范组成部分"字样；
    - 围栏代码块内、表格行、列表项（`- ` 开头，走二级编号规则）、引用块（`> `）。
    """
    head("(11) 加粗行首段落须带编号")
    lines = s.splitlines()
    fenced = in_fence_lines(s)
    # 第 1 条标题行号——之前的属"导读区"，放行
    first_art = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^### 第 1 条", l):
            first_art = i
            break

    bad = []
    for i, l in enumerate(lines, 1):
        if i in fenced:
            continue
        # 二级编号单元（列表项 `- **N.M.K …**`）——**也须带编号**。
        # 负向测试暴露的盲区：只查 `^**` 会漏掉列表项，而 9.3／9.4／9.5 正是此形态。
        m_li = re.match(r"^(\s*)- \*\*([^*]+)\*\*", l)
        if m_li:
            if not re.match(r"^(?:\d+(?:\.\d+)+|A\.\d+(?:\.\d+)*)\b", m_li.group(2).strip()):
                # 排除：明确声明游离的段
                if "非本规范组成部分" not in l:
                    bad.append((i, l.strip()[:56]))
            continue
        # 一级编号单元（加粗行首段落 `**N.M …**`）
        if not re.match(r"^\*\*[^*]", l):
            continue
        # 带编号 → 合规（N.M / N.M.K / A.N / N.0）
        if re.match(r"^\*\*(?:\d+(?:\.\d+)+|A\.\d+(?:\.\d+)*)\b", l):
            continue
        # 导读区（第 1 条之前）与文件头元信息 → 放行
        if first_art and i < first_art:
            continue
        if i <= 40:
            continue
        # 明确声明"非本规范组成部分"的游离段 → 放行
        if "非本规范组成部分" in l:
            continue
        # 续行判定：上一非空行不是空行／标题／表格／引用块 → 本行是续行，放行
        prev = lines[i - 2].strip() if i >= 2 else ""
        if prev and not prev.startswith(("#", "|", ">", "---")):
            continue
        bad.append((i, l.strip()[:56]))
    if bad:
        for i, t in bad:
            err("第 %d 行：加粗行首段落无编号（须带 `N.M`，或以不加粗改写）：%s" % (i, t))
    else:
        info("加粗行首段落／编号列表项均带编号（放行续行／导读区／元信息／围栏／游离声明段）")


# ────────────────────────────── 钩子 ──────────────────────────────

def install_hook():
    """安装 pre-commit 钩子（只警告、不阻断）。钩子源码受 git 跟踪，可重装。"""
    if not os.path.isdir(os.path.dirname(HOOK_DST)):
        print("[E] 未找到 .git/hooks 目录：%s" % os.path.dirname(HOOK_DST))
        return 1
    if not os.path.exists(HOOK_SRC):
        print("[E] 未找到钩子源码：%s" % HOOK_SRC)
        return 1
    shutil.copyfile(HOOK_SRC, HOOK_DST)
    os.chmod(HOOK_DST, 0o755)
    print("[OK] 已安装 pre-commit 钩子 → %s（只警告、不阻断）" % HOOK_DST)
    print("     一档：提交涉及 DEV-RULES.md → 自动跑本脚本（十一维自检）。")
    print("     二档：提交涉及守卫本体（check-dev-rules.py／smoke-dev-rules.py）")
    print("          → 自动跑 maint/tools/smoke-dev-rules.py 全量冒烟，")
    print("            用注入测试证明守卫**仍然拦得住**（铁律 17.2）。")
    print("     均不阻止提交；要强制门禁请手动运行并看退出码。")
    print("     卸载：删除该文件即可。换机器：重跑本命令一装即可。")
    return 0


# ────────────────────────────── 主流程 ──────────────────────────────

def main():
    global QUIET, RULES
    args = sys.argv[1:]
    if "--install-hook" in args:
        return install_hook()
    if "--file" in args:                      # 指定待检文件（默认铁律本身）；注入式自测用
        i = args.index("--file")
        if i + 1 >= len(args):
            print("[E] --file 需要一个路径参数")
            return 1
        RULES = os.path.abspath(args[i + 1])
    QUIET = "--quiet" in args

    s = read()
    print("开发工程规范（铁律）· 全文自检")
    print("=" * 62)
    check_structure(s)
    check_guide(s)
    check_refs(s, show="--refs" in args)
    check_wording(s)
    check_expression(s)
    check_paths(s)
    check_rules_version(s)
    check_cross_side()
    check_toc_anchor(s)
    check_ref_anchor(s)
    check_bold_heading(s)
    print("=" * 62)
    if ERRS:
        print("结果：错误 %d 项，警告 %d 项 —— **未通过**" % (len(ERRS), len(WARNS)))
        for e in ERRS:
            print("  · " + e)
        return 1
    print("结果：无错误（警告 %d 项，提示 %d 项）—— 通过" % (len(WARNS), len(INFOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
