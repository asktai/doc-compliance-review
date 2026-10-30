#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发规范（铁律）· 全文自检（**维数以实际输出为准**，本行不写死份数——
第 12 条：同一事实两处写必漂）
==============================================================================
对 `dev/DEV-RULES.md` 做机械自检，覆盖以下维度（**加维只往后排，不改既有编号**）：

  (1) 结构        条号连续、**条标题格式统一**、章序号连续、章区间声明与覆盖
  (2) 导读表      文首"三条铁律"导读表的条号与名称，须与正文标题一致（双源比对）
  (3) 条号引用    引用的条号必须存在（悬空引用即报错）；--refs 另打印引用上下文供人工复核
  (4) 用词        已废止词（维护侧／开发端／实例侧等）不得在正文残留；术语说明语境除外
  (5) 表述        不得使用相对引用（"见下方"等）；日期月／日须补零；编号须可键入；条以下用十进制路径（禁 1.／(N)）；路径须连号；**编号形态须完整（禁空段 `..`／前导点）**；「表述纪律」条自身反例除外
  (6) 路径真实性  正文反引号中的文件／目录引用必须真实存在
  (7) 版本串      开发侧各文档文件头的"铁律版本"须与真源（本文件文件头）一致
  (8) 跨侧一致    开发侧技能目录 ↔ 运行实例逐文件比对（排除运行侧生成物）
  (9) 目录锚点    目录中每条标题与其 GitHub 锚点须同步（标题改则锚点重生成）——**只保证按 GitHub 规则算得对，不保证你的阅读器认它**（见 (14)）
  (10) 引用锚点    表格内的"第 N 行"引用须带父级路径
  (11) 加粗编号    凡加粗行首段落，必须带 `N.M` 编号，不得以加粗冒充小标题
  (12) 元规则归属  编号体系／书写／表格例外／字符须在正文条文中成文，不得退回文首导读区
  (13) 落实总表    第 24.3 表须覆盖正文全部条（漏登／多登／重登即报错），落点属四态
  (14) 在线版      目录去锚点的派生版须与源同步（零锚点残留 ＋ 正文逐字节一致）

归属说明
    · 本脚本属于**维护侧**（`/workspace/dev/maint/tools/`），**不随技能包分发**；
    · 与 `make-card.py` 同类：开发侧工具，不进包、不参与发布链。

为什么要它（铁律第 13 条）
    "能做成自动守卫的，就不要只靠人跑一次。"——**铁律自身也受此条约束**。
    2026-09-29 实测教训：首版检查用的是"人工 ＋ 临时脚本"，当场暴露两类问题——
    (1) 临时脚本**自身 4 处 bug**（正则漏抓、`str(i) in nums` 类型错、区间误计、路径白名单不全），
       每次都**先报出"问题"、经核实才知是误报**；
    (2) 第 3 条标题格式不统一（条号后缺空格）**长期潜伏**，正是它让脚本正则漏抓该条。
    结论：**检查工具本身也必须被验证**（第 16 条"守卫自身也要验证"）。故本脚本：
    保持零依赖、写法保守（凡拿不准一律不报），并以注入式负向测试验证过"真拦得住"。

用法
    python3 maint/tools/check-dev-rules.py                  # 全维检查
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
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))            # /workspace/dev
RULES = os.path.join(DEV, "DEV-RULES.md")
SKILL = os.path.join(DEV, "doc-compliance-review")
RUN = os.path.expanduser("~/.codebuddy/skills/doc-compliance-review")
# 跨侧比对时排除的项，与 publish.py 的 EXCLUDE 保持一致
# （生成物只应存在于运行实例，且 .git 等本就不该同步）
EXCLUDE = {".git", "__pycache__", ".DS_Store",
           ".integrity.json", "_rules-baseline.json", "_smoke-baseline.json"}

# 开发侧存在、但**按设计不入运行实例**的路径（开发侧生成物，与 EXCLUDE 相反的方向）。
# 为什么需要：本维是"开发侧 → 运行实例"的单向镜像检查，凡开发侧有而运行侧无即报"缺文件"。
# 但 `_发布包/`（pack.py 出包产物）与 `report/`（审查运行期产物）在 `.gitignore` 里
# 已明确**不入档**，自然也不该进运行实例——跑一次出包就会凭空多出两条"缺文件"错误。
# 实测（2026-10-22）：出包后本维必报 2 项、跑过法条交叉验证后再多 1 项，与代码改动无关，
# 属**检查口径缺陷**而非漂移；长期如此会让人习惯性忽略本维输出（狼来了）。
# 判据：与 `.gitignore` 已声明"运行期产物、不入档"的路径保持同一口径，两处须同步。
DEV_ONLY = {"_发布包", "report",
            # `VERSION.md`（版本沿革）：v3.26.2 起**不随包、也不入运行实例**——
            # 沿革属发布侧记录，历史版本信息不对外提供。开发侧保留它是维护真源，
            # 运行实例不该有；故按「开发侧存在但按设计不入实例」处理，不报缺文件。
            "VERSION.md"}
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
    m = re.search(r"^#{2,3} 第 (\d+) 条 [^\n]*" + re.escape(keyword), s, re.M)
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
    否则格式一旦不统一就会漏抓该条（2026-09-29 踩过的坑）；格式问题由 (1) 单独报出。

    2026-10-20 修：原来只认 `### 第 N 条`（三级），而**条标题用几级标题取决于文档
    有没有`章`这一层**——完整版是「章(##) → 条(###)」，条用三级；精简版不分章，
    条就直接挂在二级（`## 第 N 条`）。只认三级会让精简版解析出 0 条，然后所有依赖
    条标题的检查维度集体报假错（(1)(9)(10)(11)(13) 一次性刷出几十条），
    看起来像"文档结构崩了"，实则只是检查器不认这种层级。
    这里改为二级、三级都认——`## 第X章` 因带"章"字不会误入。
    """
    return [(int(n), rest)
            for n, rest in re.findall(r"^#{2,3} 第 (\d+) 条(.*)$", s, re.M)]


def section(s, start_mark):
    """取从 start_mark 到下一个同级或更高级标题之间的文本。"""
    i = s.find(start_mark)
    if i < 0:
        return ""
    j = re.search(r"^#{2,3} ", s[i + len(start_mark):], re.M)
    return s[i:] if not j else s[i:i + len(start_mark) + j.start()]


def _line_span(s, start_mark):
    """返回 start_mark 所在行**直到下一个同级或更高级标题之前**的行号集合。

    与 `section()` 的区别：`section()` 返回**文本**，本函数返回**行号**，
    供"某段整体豁免"类判据使用（2026-10-20 加：规则本体段落须能写出被禁形态）。
    """
    lines = s.splitlines()
    start = None
    for i, l in enumerate(lines, 1):
        if start is None:
            if l.startswith(start_mark):
                start = i
            continue
        if re.match(r"^#{2,3} ", l):
            return set(range(start, i))
    return set(range(start, len(lines) + 1)) if start else set()


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

    # 2026-10-23 自检崩溃实录：原式 `CN = "一二三四五六七八九十"` 配 `[CN[i] for i in ...]`，
    # **把"章数上限"写死进了字符串长度**——规范加到第十一章当天，自检 IndexError 裸崩，
    # 连 err 都没机会报。故改为按需生成（支持 1—99），不再有隐式上限。
    def _cn(n):
        d = "一二三四五六七八九"
        if n <= 9:
            return d[n - 1]
        if n == 10:
            return "十"
        if n < 20:
            return "十" + d[n - 11]
        return d[n // 10 - 1] + "十" + (d[n % 10 - 1] if n % 10 else "")

    chaps = re.findall(r"^## 第(.+?)章", s, re.M)
    want = [_cn(i + 1) for i in range(len(chaps))]
    if not chaps:
        # 2026-10-20 自检发现：原写法 `info("章序号一至%s连续" % want[-1])` 在"无章"时
        # 直接 IndexError 崩溃（裸 traceback，连 err 都没机会报）。而"不分章、只列条"
        # 是合法结构——精简版规范（16 条）就是这样。无章即跳过本项，不算错。
        info("无章划分（只有条、不分章）——本维跳过")
    elif chaps != want:
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
    if not rng:
        # 无章划分（精简结构）：本项要求的"章标题带（第 X—Y 条）"本就不存在，
        # 报"未被任何章区间覆盖"等于拿分章结构的标准去要求不分章的文档。
        info("无章划分（只有条、不分章）——本维跳过")
    elif uncov:
        err("有条未被任何章区间覆盖：%s（该章标题缺「（第 X—Y 条）」标注）" % uncov)
    else:
        info("章区间覆盖全部条、互不重叠（共 %d 个章带区间标注）" % len(rng))


# ────────────────────────────── (2) 导读表 ──────────────────────────────

def check_guide(s):
    head("(2) 导读表 vs 正文（双源比对）")
    body = {n: rest.strip() for n, rest in title_rows(s) if rest.strip()}
    rows = re.findall(r"^\| \*\*第 (\d+) 条\*\* \| (.+?) \| (.+?) \|\s*$", s, re.M)
    if not rows:
        # 导读表是**分章结构**的配套（每条一句话概览，供人速览全篇）；
        # 精简版只有 16 条、不分章，本就不设导读表——按缺失报错即误判。
        if not re.search(r"^## 第.+?章", s, re.M):
            info("无章划分（精简结构）——文首导读表不适用，本维跳过")
            return
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

    # ⚠ 2026-10-20 补：原先只查"第 N 条"这一种形态，
    #   而正文里大量引用写成数字路径（"见 19.6""按 12.5.4.3 办"）——
    #   **写错一个号（如 19.6 根本不存在）此维一声不吭**。
    #   实测：我自己写正文时凭空引了"19.6""8.5"两个不存在的款，本维全过。
    #   现补第二道：把正文里出现的 N.M(.K) 与附录 A.N.M 逐一对照"已定义编号"。
    #   **判据要有区分度**（12.5.4.3）：只认"该编号及其实父级都不存在"才算悬空，
    #   父级存在而子款号写错（如 12.5.9 而 12.5 存在）**同样算**——见下 exist 判定。
    defined = set()
    for l in s.splitlines():
        for m in re.finditer(r"\*\*((?:A\.)?\d+(?:\.\d+)+)\s*[^\d.]", l):
            defined.add(m.group(1))
    for n in nums:
        defined.add(str(n))
    # 版本号形态（v1.7.0 / 1.0.0）与日期不参与判定
    VER = re.compile(r"(?<![\d.])(?:v)?\d+\.\d+\.\d+(?![\d.])")

    bad_num = []
    fenced = in_fence_lines(s)
    for i, line in enumerate(s.splitlines(), 1):
        if i in fenced:
            continue
        scan = VER.sub(lambda m: " " * len(m.group(0)), line)   # 先抹掉版本号
        scan = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), scan)  # 抹掉反引号内
        for m in re.finditer(r"(?<![\d.])((?:A\.)?\d+\.\d+(?:\.\d+)*)(?![\d.])", scan):
            ref = m.group(1)
            if ref in defined:
                continue
            # 父级已定义但本号未定义 → 这是"款号写错"，比整条悬空更常见，**必须报**
            bad_num.append((i, ref))
    if bad_num:
        err("悬空编号引用（数字路径式，指向不存在的款）：%s"
            % "、".join("第 %d 行「%s」" % (i, r) for i, r in bad_num[:8]))
    else:
        info("数字路径式引用（N.M／A.N.M）全部指向已定义的款（已排除版本号与反引号内）")

    if show and not QUIET:
        print("  ── 引用上下文（供人工复核**指向是否正确**，脚本查不出语义）──")
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


def check_external_refs(s):
    """(3b) 外部文件里写死的铁律条号，是否还对得上。

    2026-10-20 新增。12.5.1.1 早就承认这是盲区："条号也被别处引用——
    脚本注释、随包文档里写死的'（铁律第 9.4 条）'，本文件一动即全部悬空，
    守卫一个也看不见"。**承认了却不做手段，等于把缺口写在墙上就走开**（12.5）。
    现补：扫开发侧 .py／.md 里的"铁律第 N.M"与"（铁律 A.B / C.D）"，
    逐个对 `DEV-RULES.md` 里**实际定义过的款号**。

    **判据边界**（避免误报）：
      · 只认带"铁律"二字的引用——裸写"第 9.4 条"可能是别家文档的编号；
      · 只认**款号形态**（N.M 起），条号（"铁律第 9 条"）另由 (3) 管；
      · 开发日志与历史记录**豁免**（DEVLOG 记述的是当时的条号，属史实，改了反而失真）。
    """
    head("(3b) 外部文件里的铁律条号引用")
    if not _is_rules_itself(s):
        # 本维扫的是**开发侧文件里对本体的条号引用**（`maint/tools/` 等）。
        # 待检若是发布版（16 条精简结构），那些引用指的是**本体 24 条**的款号，
        # 与待检文件不是同一套编号——照本体标准比对必报假错（2026-10-21 实测）。
        # 与 (7)(14) 维同口径：不是本体即不适用。
        info("待检内容不是铁律本体（%s）——外部文件引用的是本体条号，本维不适用，跳过"
             % os.path.basename(RULES))
        return
    defined = set()
    for l in s.splitlines():
        for m in re.finditer(r"\*\*((?:A\.)?\d+(?:\.\d+)+)\s*[^\d.]", l):
            defined.add(m.group(1))

    roots = [os.path.join(DEV, "maint", "tools"),
             os.path.join(DEV, "maint", "doc-compliance-review"),
             SKILL]
    EXEMPT_FILES = {"DEVLOG.md", "CHANGELOG.md"}
    EXEMPT_DIRS = ("scratch", "ai-notes", "test-data", "__pycache__")
    bad = []
    scanned = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXEMPT_DIRS]
            for fn in filenames:
                if not (fn.endswith(".py") or fn.endswith(".md")):
                    continue
                if fn in EXEMPT_FILES:
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    txt = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                scanned += 1
                for ln, line in enumerate(txt.splitlines(), 1):
                    for m in re.finditer(r"铁律\s*(?:第\s*)?(\d+\.\d+(?:\.\d+)*)", line):
                        ref = m.group(1)
                        if ref in defined or any(d.startswith(ref + ".") for d in defined):
                            continue
                        bad.append("%s:%d「铁律 %s」"
                                   % (os.path.relpath(p, DEV), ln, ref))
    if bad:
        err("外部文件里的铁律条号已悬空（真源改号后未同步搬迁）：%s" % "、".join(bad[:8]))
    else:
        info("外部文件（%d 份）里的铁律条号引用全部对得上现行条号" % scanned)


def check_wording(s):
    head("(4) 用词（术语纪律）")
    lines = s.splitlines()
    a3 = tail_lines(s, "### A.3")        # A.3「术语纪律」含废止词表，属**必要保留**
    app_a = tail_lines(s, "## 附录 A")   # 附录 A 全节都在讲术语，同样豁免「用户」

    # A.3.7（乙）的否定／脱离类修饰——"非运行实例侧""脱离运行实例侧"不指代那个侧别，
    # 按废词处理。此处用**显式清单**兜常见的，清单外靠人工（A.3.7 已声明本项为"部分覆盖"）。
    NEG_DECOUPLE = ("非", "不是", "属于", "脱离", "绕过", "抛开", "并非")

    for w, rep in BANNED.items():
        hits = []
        for i, l in enumerate(lines, 1):
            if i in a3:
                continue
            # 只查**裸用**：排除被更长术语包含的情形。
            # "运行实例侧"是**正式用词**——依据是 A.3.7（甲）的字面条：紧前是"运行"即放行。
            # **注意（2026-10-20 二次修正）**：原注释写"且与另一侧对仗"，该条件已从条文删除
            #   （A.3.7 自举的反例即是"单说一侧"也合法）——注释与条文必须同步，否则守卫的
            #   依据与条文对不上，日后改条文的人看不出这里绑着什么（12.3.3 引用漂移）。
            # 另按 A.3.7（乙）：即便紧前是"运行"，若整体前带否定／脱离修饰，**仍按废词处理**。
            bare = False
            for m in re.finditer(r"(?<!运行)" + re.escape(w), l):
                bare = True
                break
            if bare:
                hits.append(i)
                continue
            # 走到这里说明"所有出现处"都紧跟"运行"。再检查是否带否定修饰。
            for m in re.finditer("运行" + re.escape(w), l):
                pre = l[max(0, m.start() - 3):m.start()]
                if any(pre.endswith(n) for n in NEG_DECOUPLE):
                    hits.append(i)
                    break
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
    # 否定语境豁免：规则**必须能写出被禁形态**（"不写 `2026-9-5`"本身就在教读者别这么写），
    # 否则守卫会逼着规则作者删掉反例、只留正例，反例一没、读者就不知道边界在哪。
    # 本体原先把反例写在表格里（表格被排除，侥幸躲过）；精简版写在正文段落，
    # 2026-10-20 自检时暴露本条无豁免 → 补上与 (6) 维"否定语境豁免"同口径的判据。
    NEG_CUES = ("不写", "不得", "不可", "禁止", "反例", "错误", "误写", "应为", "→")
    for i, l in enumerate(body.splitlines(), 1):
        cue_line = any(c in l for c in NEG_CUES)
        for m in re.finditer(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", l):
            if len(m.group(2)) != 2 or len(m.group(3)) != 2:
                # 同行含否定／对照措辞，且该行同时给出了补零后的正确形态 → 判为反例，豁免
                if cue_line and re.search(r"\b20\d{2}-\d{2}-\d{2}\b", l):
                    continue
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

    # 编号**形态**完整性：编号 token 不得含空段（`..`）、不得有前导／后导点、不得超深。
    # 2026-10-16 实证：章序重排脚本一度产出 `16.4..1.1`（`..` 右侧是"真值重复两遍"）
    # 一类错乱 41 处，而原守卫的 `kids` 正则要求每段非空，**整段匹配失败**——
    # 既不入 `kids`（连续性查不到），也不报任何错。**守卫看不见"编号本身被改坏"**，
    # 是为结构性盲区。此处补一条**独立形态断言**，专治此类。
    #
    # 判据（只审"编号形态"，不碰版本号／小数／表格序号）：
    #   · 只抓"**含 `..`**"与"**前导点紧跟数字**"两种**明确坏形态**——
    #     它们是"编号被改坏"的充分特征，且不与任何合法写法相撞。
    #   · 段数上限与"段内含前导零"不在此处审：前者已由 2.1 约束、后者由肉眼与 (11) 兜，
    #     在此重审只会引入误报（如版本号 `1.39.0`、小数 `0.5`）。
    bad_form = []
    fenced_f = in_fence_lines(s)
    for i, l in enumerate(s.splitlines(), 1):
        if i in fenced_f:
            continue
        # 坏形态一：数字间出现连续点（`16.4..1.1` 的核心特征）
        for m in re.finditer(r"\d+(?:\.\d+)*\.\.\d+", l):
            bad_form.append("第 %d 行 「%s」（含 `..` 空段）" % (i, m.group(0)))
        # 坏形态二：点号**前导**紧跟数字且前面不是数字（形如 `..1` 已被上式覆盖，
        # 这里兜住 `.1.1` 这类孤立的"点起头编号"，但**排除**句末句点后接数字的情形）
        for m in re.finditer(r"(?<![\d.])\.(?=\d+(?:\.\d+){1,})(?=[^\d]|$)", l):
            bad_form.append("第 %d 行 「%s…」（编号以前导点起）" % (i, l[max(0, m.start() - 6):m.start() + 8]))
    bad_form = sorted(set(bad_form))
    if bad_form:
        err("编号形态异常（不得含空段 `..`／前导点）：%s"
            % "；".join(bad_form[:12]))
    else:
        info("编号形态完整（无空段 `..`、无前导点起编号）")


# ────────────────────────────── (6) 路径真实性 ──────────────────────────────

def check_paths(s):
    head("(6) 路径引用真实性")
    fenced = in_fence_lines(s)
    cands = set()
    # 占位符豁免（2026-10-20 补）：规则讲"别怎么写"时必然举出**假文件名**
    # （"记『改了 `X.md`』等于没记"——`X.md` 是占位范例，本就不该存在）。
    # 判据**刻意从窄**：只认"单字母/字母占位 + 常见扩展名"，且**同行须有否定措辞**。
    # 不用宽泛的"如/例如"——实测那样会豁免全文 30% 的行，等于把本维改哑（12.4）。
    PLACEHOLDER = re.compile(r"^[A-Za-z]{1,2}(?:[-_][A-Za-z]{1,2})?\.(md|py|json|txt|docx)$")
    NEG_CUES = ("等于没记", "不写", "不得", "禁止", "反例", "须写成", "应为", "→")
    for i, line in enumerate(s.splitlines(), 1):
        if i in fenced:
            continue
        for c in re.findall(r"`([^`\n]+)`", line):
            c = c.strip()
            if " " in c or not c:
                continue
            if re.search(r"[\\*?]", c):
                continue
            # 占位范例：仅在同行带否定／对照措辞时放行
            if PLACEHOLDER.match(c) and any(cue in line for cue in NEG_CUES):
                continue
            # ⚠ 2026-10-20 修正：原把 `SKILL|Skill` 列入合法扩展名白名单，
            #   而 20.4 明令**大写 `.Skill` 回流须当场报错**——于是写 `` `.Skill` ``
            #   既不当作路径去查，也不报违规，**两头都漏**（全量质检实测）。
            #   现只保留小写写法在"纯扩展名"里，大写形态由下面的 EXT_BAD 单独断言。
            if "/" in c or re.match(r"^[\w\-.·]+\.(md|py|json|zip)$", c):
                cands.add(c)

    # 纯扩展名不是路径
    exts = {".skill", ".zip", ".py", ".md", ".json"}
    prefix = {"dev/": DEV + "/", "maint/": DEV + "/maint/", "dist/": DIST + "/",
              "~/.codebuddy/skills/": RUN + "/", "scripts/": SKILL + "/scripts/"}
    # 搜索目录：开发侧若干固定位置 ＋ **被检文件自己所在的目录**。
    # 2026-10-21 补最后一项：对外发布版放在 /workspace 根、与自己的检查器同目录，
    # 若不搜它所在目录，发布版"检查器与本文件同目录附带"这句话就永远被判"路径不存在"
    # ——**检查器无法为它自己参与构造的承诺作证**（12.5.4.3 判据须能区分真假）。
    search = [DEV, os.path.join(DEV, "maint"), SKILL, os.path.join(SKILL, "scripts"),
              os.path.join(SKILL, "core"), os.path.join(SKILL, "assets"),
              os.path.dirname(os.path.abspath(RULES))]
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

    # 单列一道：**大写扩展名 `.Skill` 回流**（20.4 明令报错，原先无人管——
    # 它既不是能查的真路径，又被白名单放过，等于三不管）。
    # **判据须有区分度（12.5.4.3）**：20.4 本条自己就要写出 `.Skill` 来立规矩、
    #   还要引述历史写法（20.4.3 的"例外"），故**规则本体段与否定语境必须放行**，
    #   否则这道守卫第一天就误报。三道豁免：
    #     （甲）20.4 本条及其子款所在的整段（规则本体，必须能写出禁用形态）；
    #     （乙）同一行内 `非／不得／禁用／改为／回流` 等否定或纠正词在前；
    #     （丙）22 条那张"错误写法 → 正确写法"对照表（它整张都是反例样本）。
    body20 = _line_span(s, "**20.4") | _line_span(s, "**20.5")
    bad_ext = []
    NEG_WORDS = ("不得", "禁用", "非", "不应", "禁止", "改为", "回流", "大小写敏感")
    for i, l in enumerate(s.splitlines(), 1):
        if i in in_fence_lines(s) or i in body20:
            continue
        for m in re.finditer(r"`[^`\n]*\.(Skill|SKILL)[^`\n]*`", l):
            pre = l[:m.start()]
            if any(w in pre[-40:] or w in l[max(0, m.end() - 6):m.end() + 24] for w in NEG_WORDS):
                continue
            bad_ext.append("第 %d 行「%s」" % (i, m.group(0)[:40]))
    if bad_ext:
        err("出现大写扩展名 `.Skill`／`.SKILL`（20.4：分发包一律小写 `.skill`，大写即违规）：%s"
            % "、".join(bad_ext[:6]))
    else:
        info("无大写扩展名回流（规则本体与否定语境已豁免）")


# 开发侧需要跟随铁律版本号的文档（真源＝DEV-RULES.md 顶部版本行）
VER_FILES = ["maint/DEVLOG.md", "CHANGELOG.md", "publish.py"]
# 只匹配"当前状态陈述"：现 **Vx.y.z** ／ 当前 **Vx.y.z**（历史流水里的旧值不算）
VER_RE = re.compile(r"(?:现|当前)\s*\*{0,2}([Vv]\d+\.\d+\.\d+)\*{0,2}")


def _is_rules_itself(s):
    """待检内容是不是"铁律本体"（而非别的文档）——**按内容判，不按路径判**。

    ⚠ 2026-10-20 修：先写成"路径必须等于 DEV-RULES.md"，结果**把全量冒烟打断**——
    冒烟把注入后的副本写到临时目录再 `--file` 传入，路径永远不等于本体，于是 (7)(14)
    两维全被跳过，冒烟当场报"(7) 未报错（守卫失效）"。**这正是"改 A 把 B 改坏"**。
    现改为看内容特征：有本规范的条号元规则 ＋ 落实总表，才算本体；副本改了版本号
    仍是本体（否则打瘸点打不进去）。
    """
    # 路径判定：本体本身，**或冒烟/元自测写出的临时副本**（它们在 /tmp 下，
    # 但内容就是本体的打瘸版——必须照样跑这两维，否则打瘸点打不进去）。
    if os.path.abspath(RULES) == os.path.abspath(os.path.join(DEV, "DEV-RULES.md")):
        return True
    real = os.path.realpath(RULES)
    tmp = os.path.realpath(tempfile.gettempdir())
    return real.startswith(tmp + os.sep)


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
    # ⚠ 2026-10-20 修（实测发现假过/假报）：本维拿"待检文件的版本串"当**真源**，
    #   却比的是**固定的一份开发侧文档集**。用 --file 检别的文档（如对外发布版）时，
    #   真源变成了那份文档的版本号、文档集却还是本项目的——比出来的错全是假的。
    #   故：待检文件不是铁律本体时，本维不适用（跳过并说明），不得静默给"通过"。
    if not _is_rules_itself(s):
        info("待检内容不是铁律本体（%s）——本维不比跨文档版本，跳过"
             % os.path.basename(RULES))
        return
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
        dirs[:] = [d for d in dirs if d not in EXCLUDE and d not in DEV_ONLY]
        for fn in files:
            # 文件层也要认 DEV_ONLY：它此前只用于目录过滤，导致「开发侧有、按设计
            # 不入实例」的单文件（如 VERSION.md）被误报「运行实例缺此文件」。
            if fn in EXCLUDE or fn in DEV_ONLY:
                continue
            fp = os.path.join(root, fn)
            dev_files[os.path.relpath(fp, SKILL)] = fp
    def _norm_version_json(path):
        """两侧归一后再比 version.json。

        开发侧带 history、运行实例按设计被 `dist-mode.py` 剥离并加 `_分发副本` 标记——
        这是**分发形态**的正常差异，不是漂移。故只比「去掉 history 与 _分发副本 之后」
        的其余内容：latest 版本号／日期／说明／直链变了照样抓得住，不会因归一而失守。
        """
        import json as _json      # 本模块未在顶层 import json，函数内局部导入更稳
        try:
            with open(path, encoding="utf-8") as f:
                d = _json.load(f)
        except Exception as e:
            # 解析失败**必须判为不一致**，不能返回 None：两侧都 None 时 `None == None`
            # 会被当成"一致"而静默放行——这正是 12.5.9「输入不可信不得默认相等」的反例。
            # 带路径的差异串保证两侧永不相等，从而必然触发一条错误。
            return "__PARSE_ERROR__:%s:%r" % (path, e)
        if isinstance(d, dict):
            d.pop("history", None)
            d.pop("_分发副本", None)
        return _json.dumps(d, ensure_ascii=False, sort_keys=True, indent=2)

    for rel, fp in sorted(dev_files.items()):
        rp = os.path.join(RUN, rel)
        if not os.path.exists(rp):
            drift.append("运行实例缺此文件：%s" % rel)
        elif rel == "version.json":
            if _norm_version_json(fp) != _norm_version_json(rp):
                drift.append("两侧不一致：version.json（latest 段；history 差异按分发形态忽略）")
        elif digest(fp) != digest(rp):
            drift.append("两侧不一致：%s" % rel)
    if drift:
        for d in drift[:10]:
            err(d)
        if len(drift) > 10:
            err("……另有 %d 处，不逐一列出" % (len(drift) - 10))
    else:
        info("开发侧 %d 个文件与运行实例一致（已排除运行侧生成物与开发侧产物 %s）"
             % (len(dev_files), "、".join(sorted(DEV_ONLY))))


# ────────────────────── (9) 目录锚点一致性 ──────────────────────

def _gh_anchor(n, title):
    """按 GitHub 规则由条标题重算锚点。

    **2026-10-17 复核更正**：原注释写"已实测 20/20 吻合"，但那是**用本函数自己
    去比目录**——两边同源，吻合只证明"目录与本函数一致"，**不证明**与真实 GitHub 一致
    （典型的"判据没有区分度"，见 12.5.4.3）。
    现改为**按 github-slugger 的公开规则独立重算**（小写 → 删非字母数字／非空格／
    非 `-` 字符 → 空格转连字符），并对全部 38 条目录项逐一核对，结果全部吻合。
    **但它仍只回答"GitHub 上对不对"**：腾讯文档等阅读器不按此规则解析，
    故另有第 (14) 维负责"在线版改纯文字大纲"。
    """
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

    铁律 12.3.3「引用漂移」含"语义已变"，而语义**无法自动化**（脚本做不到）。
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
        # ⚠ 2026-10-20 修正：原为 `line.lstrip().startswith(("|", ">", "- ["))` 一律跳过，
        #   结果是**整张表的引用一概不查**——第 22 条那张讲"引用须带父级"的表自己就漏检，
        #   他处表格里裸写"第 N 行"同样放行（实测注入不报）。
        #   现改为：**表格行照查**，只跳过两类真正的"举例"——
        #   ① 反引号内的代码片段（规则示例，不是实际引用）；
        #   ② 目录行与引用块（`- [` / `>`）——那里本就不写行引用。
        if line.lstrip().startswith(("- [", ">")):
            continue
        # 抹掉反引号内内容后再匹配，避免把规则示例当实际引用。
        # 2026-10-21：**中文引号内同样豁免**——`| **标题锚** | "第 8 条下 8.2 那张表的第 2 行" |`
        #   这种表格示例整段都在引号里，是在**演示引用长什么样**，不是真在引用。
        #   只抹反引号时它会漏进来（实测报假错），与反引号内豁免同口径补上。
        scan = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
        scan = re.sub(r"[\"“]([^\"”]*)[\"”]", lambda m: " " * len(m.group(0)), scan)
        # 裸写"第 N 行"（前面既非 `N.M` 也非条级"第 N 条"／`N`）→ 违规。
        # **父级有两种合法形态**：款级 `17.3`、条级 `14` 或 `第 14 条`（实测都出现过）。
        for m in re.finditer(r"(?<![\.\d])(?<!M )第 (\d+) 行", scan):
            pre = scan[:m.start()]
            ok_parent = re.search(r"(?:\d+\.\d+|\d+)\s*$", pre) or re.search(r"第\s*\d+\s*条\s*$", pre)
            if ok_parent:
                continue
            # ③ 明确标为**反例／错误写法**的引述 → 放行。
            #    第 22 条那张表自己就写着「**不得裸写"第 4 行"**」——它是在**讲规则**，
            #    不是在引用某行。判据看紧邻前文是否有否定标记词（"不得／禁止／反例／错误写法／应写作"）。
            #    只在**同一行**内看，且限 20 字以内，避免"整段有否定词"把真引用也放行。
            seg20 = pre[max(0, m.start() - 20):m.start()]
            # 2026-10-21 补「不写／不记作／误写」：精简版写的是"不写\"第 2 行\""，
            #   否定词表原先只有"不得／禁止／…"，"不写"不在其中 → 反例被当真引用报出。
            if re.search(r"(不得|不写|不记作|误写|禁止|反例|错误写法|应写作|应改为|不得再)", seg20):
                continue
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
    # 第 1 条标题行号
    first_art = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^#{2,3} 第 1 条", l):
            first_art = i
            break
    # 文首两个**结构单元**可免编号，边界一律由结构定，不按行号数：
    #   ① 元信息块：第 1 行 → 导读区起点之前；
    #   ② 导读区：含"导读 ·"字样的行 → 其**紧邻**的结束分隔线（含）。
    # 二者**之外**、第 1 条标题**之前**的地带（目录区、过渡说明）**不免检**——
    # 2026-10-20 实测：原写法 `i <= 40` 与"第 1 条之前一律放行"两处，
    # 都会让该地带的无编号加粗段落**照样通过**（门槛卡位置、不卡内容）。
    #
    # ⚠ 同日复核又抓出一处**假过**：若只取"导读起点后第一条 `---`"，那么把导读区
    #   自己的结束线删掉后，守卫会把**目录区的分隔线**当成导读区边界，
    #   于是整片目录区被静默豁免（实测：删线后在目录内插无编号加粗，不报）。
    #   故此处加两道约束：①导读区**跨度上限**（超过 GUIDE_MAX 行即判边界可疑）；
    #   ②导读区内若出现"目录"字样，说明已跨进目录区，边界同样可疑。可疑即报错、
    #   且**不放行**该区间（宁可按违规查，不许静默豁免）。
    GUIDE_MAX = 40
    g_start = None
    guide_end = None
    for i, l in enumerate(lines, 1):
        if g_start is None and "导读 ·" in l:
            g_start = i
            continue
        if g_start is not None and l.strip() == "---":
            guide_end = i
            break
    if g_start is None:
        # 结构被改：只豁免元信息块（按"第一条 `---` 之前"），**不把 g_start 置 1**，
        # 否则元信息块也失去豁免，会连带误报文件头的版本行（复核实测）。
        for i, l in enumerate(lines, 1):
            if l.strip() == "---":
                guide = set(range(1, i + 1))
                break
        else:
            guide = set()
        if not re.search(r"^## 第.+?章", s, re.M):
            # 导读区（卷首速览）同样是分章结构的配套；精简版无此结构，
            # 报"结构被改"是拿 24 条版的版式去量 16 条版。本维降级为提示。
            info("无章划分（精简结构）——文首导读区不适用，按元信息块豁免")
        else:
            err("找不到导读区起点（含「导读 ·」的段落）——结构被改，仅按元信息块豁免")
    else:
        span = (guide_end - g_start + 1) if guide_end else 0
        if guide_end is None:
            # 只豁免元信息块 ＋ 导读标题行（标题行本身是无编号加粗，属正常）
            guide = set(range(1, g_start + 1))
            err("找不到导读区的结束分隔线（`---`）——边界不明，导读区此后不豁免")
        elif span > GUIDE_MAX:
            guide = set(range(1, g_start + 1))
            err("导读区跨度异常（%d 行，上限 %d）——疑似把目录区误并入，"
                "导读区此后不豁免，请检查导读区结束分隔线是否被删"
                % (span, GUIDE_MAX))
        elif any("目录" in l for l in lines[g_start - 1:guide_end]):
            guide = set(range(1, g_start + 1))
            err("导读区区间内出现「目录」字样——结束分隔线可能被删，导读区此后不豁免")
        else:
            guide = set(range(1, g_start + 1)) | set(range(g_start, guide_end + 1))

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
        # 文首元信息块与导读区（边界见函数开头，按结构定）→ 放行
        if i in guide:
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


# ──────────────── (12) 编号元规则须在正文条文中成文 ────────────────

# 元规则的"特征短句"——这些是**全文唯一成文处**的独有措辞。
# 每项 = (说明, 必须出现的特征子串)。任一缺失即判该规则"掉出正文"。
META_RULES = [
    ("编号体系", "条以下一律十进制路径"),
    ("编号总述位例外", "总述位"),
    ("书写规范", "行首加粗即声明"),
    ("表格例外", "表内行不编号"),
    ("字符规则", "可直接键入"),
]


def check_meta_rules(s):
    """(12) 编号元规则须在**正文条文**里成文，不得退回导读区"裸段"。

    **本条守卫的是一件历史事故**：编号体系／书写／表格例外／字符四段，
    2026-10-14 之前只存在于**导读区**——无条号、不可引用、不受任何守卫覆盖，
    长得就像"多余的导读"（开发者当天即质疑"这个导读是不是多余的"），
    删掉它**不会有任何一个守卫报警**，因为**它本就在守卫视野之外**。

    故本守卫做两件事（缺一不可）：
      A. **正向**：这五条元规则的"特征短句"必须能在**带编号的正文单元**里找到；
      B. **反向**：它们**不得**以无编号裸段的形式出现在 `### 第 1 条` 之前的导读区
         （即"退回导读区"这一具体病征须能被抓住）。

    归属：正文 = 第 1 条（文档结构与编号）。若将来挪号，须同步改本条守卫——
    这正是"守卫自身也要被验证"（16 条 16.2）的又一实例。
    """
    head("(12) 编号元规则须在正文条文中成文")
    lines = s.splitlines()
    fenced = in_fence_lines(s)

    # 正文起点：第 1 条标题行
    first_art = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^#{2,3} 第 1 条", l):
            first_art = i
            break
    if first_art is None:
        err("未找到「第 1 条」标题——编号元规则的归属条缺失")
        return

    body = "\n".join(l for i, l in enumerate(lines, 1)
                     if i > first_art and i not in fenced)
    head_area = "\n".join(l for i, l in enumerate(lines, 1)
                          if i < first_art and i not in fenced)

    bad = 0
    for name, phrase in META_RULES:
        # A. 正向：特征短句须在正文出现
        if phrase not in body:
            err("元规则「%s」未在正文成文（正文中找不到特征短句：%s）"
                % (name, phrase))
            bad += 1
            continue
        # B. 反向：不得同时以无编号裸段留在导读区
        if phrase in head_area:
            # 只有在导读区**未加粗编号**时才算"退回"
            err("元规则「%s」退回导读区（特征短句同时出现在第 1 条之前的裸段中）" % name)
            bad += 1

    # C. 导读区不得再声明"四段不属编号单元"这类自我豁免（正是退回的病征）
    if re.search(r"以上.{0,6}段为\**导读说明", head_area):
        err("导读区出现「以上…段为导读说明」式自我豁免——编号元规则又退回裸段了")

    if bad == 0:
        info("编号元规则（编号体系／书写／表格例外／字符）均在正文条文中成文，导读区无裸段残留")


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
    print("     一档：提交涉及 DEV-RULES.md → 自动跑本脚本（全维自检）。")
    print("     二档：提交涉及守卫本体（check-dev-rules.py／smoke-dev-rules.py）")
    print("          → 自动跑 maint/tools/smoke-dev-rules.py 全量冒烟，")
    print("            用注入测试证明守卫**仍然拦得住**（铁律 16.2）。")
    print("     均不阻止提交；要强制门禁请手动运行并看退出码。")
    print("     卸载：删除该文件即可。换机器：重跑本命令一装即可。")
    return 0


# ──────────────── (16) 结转遗留清单格式与态（OPEN-ISSUES.md） ────────────────

OPEN_ISSUES = os.path.join(DEV, "maint", "OPEN-ISSUES.md")


def check_open_issues(s_ignored=None):
    """(16) 结转遗留清单须在、六字段齐、编号唯一、态合法、「转下轮」须有再见条件。

    **本维的来历（2026-10-29）**：遗留清单原先寄居 `DEVLOG.md` 顶部，并在表头自注
    「**本表无守卫**」——靠每轮开工人工读。人工读得住格式，读不住的两件事：
    ① 新登记的行**漏了「态」或「再见条件」**（18.2 明写"缺一不算登记"，可当时没有任何东西盯着）；
    ② 把已办的项**直接删行**（而不是划号保留），于是"这坑踩过"的教训一并消失。
    故迁出为独立文件的同时补本维——**只补机械可判的那部分**。

    判什么：
      A. 文件在（铁律 7.2 的闭环入口，缺了 18.2 的回收环就断在这里）；
      B. 表头六列、每行六列（六字段缺一不算登记）；
      C. 编号 `H-NN` 唯一（**允许 `~~H-02~~` 划号形态**——已解决项保留不删）；
      D. 「态」只许取 转下轮／已解决／明确关闭；
      E. 标「转下轮」的行，「在等什么」与「再见条件」不得为空、不得写「无」。

    **不判什么（写明边界，免得被当成"清单没问题"的证明）**：
    内容是否属实、是否真回收——机器读不懂「包侧已排除」是不是真的排除过。
    这条**只能人工**（16.4 独立复核）。**不得为它写假守卫**（24.3.5）。
    """
    head("(16) 结转遗留清单格式与态")
    e0 = len(ERRS)          # 只判"本维有没有新增错"，不用全局 ERRS——
                            # 前面维度的错会让本维的 ok 被吞掉，看着像"这维没跑"
    if not os.path.exists(OPEN_ISSUES):
        err("结转遗留清单不存在：%s —— 这是铁律 7.2 的闭环入口，缺了它 18.2 的回收环就断在这里"
            % os.path.relpath(OPEN_ISSUES, DEV))
        return
    try:
        src = open(OPEN_ISSUES, encoding="utf-8").read()
    except Exception as e:                                  # noqa: BLE001
        err("结转遗留清单读取失败：%r" % (e,))
        return

    lines = src.splitlines()
    hi = None
    for i, l in enumerate(lines):
        if re.match(r"^\|\s*编号\s*\|", l):
            hi = i
            break
    if hi is None:
        err("结转遗留清单找不到表头（应形如「| 编号 | 问题 | 现状与卡点 | 在等什么 | 再见条件 | 态 |」）"
            "——表被删或表头被改，本维无从核对")
        return
    hdr = [c.strip() for c in lines[hi].strip().strip("|").split("|")]
    if len(hdr) != 6:
        err("结转清单表头应 6 列（编号／问题／现状与卡点／在等什么／再见条件／态），"
            "实为 %d 列：%s" % (len(hdr), "｜".join(hdr)))

    rows, i = [], hi + 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        rows.append((i + 1, lines[i]))
        i += 1
    if not rows:
        err("结转清单表体为空——只留表头等于清单没了，比不登记更坏（看着像查过了）")
        return

    OK_STATES = ("转下轮", "已解决", "明确关闭")
    seen = {}
    for ln, l in rows:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) != 6:
            err("结转清单第 %d 行有 %d 列（应 6 列）——六字段缺一不算登记；"
                "若单元格里写了裸 `|` 也会破列，同理" % (ln, len(cells)))
            continue
        no = re.sub(r"[~*\s]", "", cells[0])
        if not re.match(r"^H-\d{2}$", no):
            err("结转清单第 %d 行编号「%s」不是 H-NN 形态（已解决项写 ~~H-02~~ 亦可）"
                % (ln, cells[0]))
            continue
        if no in seen:
            err("结转清单编号 %s 重复（另见第 %d 行）——同一事项挂两个号，回收时必漏一个"
                % (no, seen[no][0]))
        seen[no] = (ln, None)
        # 态列允许带加粗／删除线强调（原表就写 `**已解决**`、`~~H-02~~`）：
        # **剥掉强调标记后仍须精确等于三值之一**，不是模糊匹配——区分度不受影响。
        state = re.sub(r"[~*\s]", "", cells[5])
        seen[no] = (ln, state)
        if state not in OK_STATES:
            err("结转清单第 %d 行（%s）「态」写的是「%s」，只许取 %s —— "
                "「待决定」「进行中」「处理中」这类都不算三态（18.2）"
                % (ln, no, state, "／".join(OK_STATES)))
            continue
        if state == "转下轮":
            wait, cond = cells[3], cells[4]
            if not wait or wait in ("无", "—", "-", "／"):
                err("%s 标了「转下轮」，但「在等什么」没写——不知道在等谁，下轮没人会去推" % no)
            if not cond or cond in ("无", "—", "-", "／"):
                err("%s 标了「转下轮」，但「再见条件」没写——没有再见条件就永远闭不了" % no)
    if len(ERRS) == e0:
        open_n = sum(1 for _, st in seen.values() if st == "转下轮")
        ok("结转清单 %d 条（%d 条转下轮）：%s"
           % (len(seen), open_n, "、".join(sorted(seen))))



# ────────────────────────────── 主流程 ──────────────────────────────

# ──────────────── (13) 落实总表须覆盖全部条 ────────────────

def check_closure_table(s):
    """(13) 第 24.3「全文落实总表」须覆盖正文全部条，且落点取值合法。

    **本条守卫的是一件真实缺陷**：24.3 表逐条登记"靠什么兜住"，但表是**手写的**——
    新增一条后忘了登记，不会有人发现（表照样通过，只是少了一行）。
    2026-10-17 质检时即由人工发现此缺口，此前无任何守卫覆盖。

    三件事（缺一不可）：
      A. **完整性**：正文第 1—N 条的条号集合，须与总表"条"列集合**完全相等**；
      B. **落点合法**：每行落点须是四态之一（守卫／人工／流程／守卫＋人工）；
      C. **表在**：找不到 24.3 表即报错（防止整表被删而无人知）。

    注：本维**只比集合与词表**，不判断"标得对不对"——那属人工复核（16.4）。
    """
    head("(13) 落实总表须覆盖全部条")
    lines = s.splitlines()

    arts = [int(m.group(1)) for m in
            (re.match(r"^#{2,3} 第 (\d+) 条", l) for l in lines) if m]
    if not arts:
        err("未解析出任何条——无法校验落实总表")
        return

    # 定位「落实总表」：本体的收束条款是 24.3。**精简版没有这一章**（16 条版不分章、
    # 不收束），对它报"未找到 24.3"是拿 24 条体系的标准去要求 16 条体系——不适用。
    # 2026-10-20 自检发现：原写法硬编码 "24.3"，精简版必报一条假错。
    # 判据改为：先看本文有没有第 24 条；没有即判"本结构不含落实总表"，跳过本维。
    if 24 not in arts:
        info("本文共 %d 条、无第 24 条（精简结构）——本维不适用，跳过" % len(arts))
        return
    start = None
    for i, l in enumerate(lines, 1):
        if re.match(r"^\*\*24\.3 ", l):
            start = i
            break
    if start is None:
        err("未找到 24.3「落实总表」——收束条款缺失，全文落实无从核对")
        return

    rows, header, i = [], None, start
    while i < len(lines):
        l = lines[i]
        if l.startswith("|"):
            # 表头：以「条」开头的那一行（如 `| 条 | 名称 | 落点 | 兜在何处 |`）
            if header is None and re.match(r"^\|\s*条\s*\|", l):
                header = [c.strip() for c in l.strip().strip("|").split("|")]
            elif re.match(r"^\|\s*\d+\s*\|", l):
                rows.append((i + 1, l))
        elif header is not None:
            # 2026-10-30 修（**读数越界**，此前让「表体删空」用例失效）：
            # 原条件 `elif rows: break`——只有已收到数据行才断。于是表体被删空时
            # rows 始终为空，循环一路扫到文件末尾，把后面**别的表**的 `| 数字 |` 行
            # （如 28.1 门禁三要件表 `| 1 | 有断言 |`）当成 24.3 的续表收进来，
            # 于是"表体为空"报不出来，反而报"第 1/2/3 条落点不合四态"。
            # 表头之后紧接表体，中间不隔空行；故**表头一旦定位，遇非表格行即为表末**。
            break
        i += 1

    # **表体不得为空**：只留标题、把表删干净，同样算缺失——此前漏判（2026-10-17 复核发现）。
    if header is None:
        err("24.3 未找到表头（须为 `| 条 | 名称 | 落点 | 兜在何处 |`）——表可能已被删或改形")
        return
    if not rows:
        err("24.3 表未解析出任何数据行——表体为空，等同缺失")
        return

    # **列序须与表头一致**：不写死"落点在第 3 列"，改为按表头定位。
    # 此前写死 cols[2]，表头列序一改就查错列、且不报错（2026-10-17 复核发现）。
    try:
        i_name = header.index("名称")
        i_state = header.index("落点")
        i_where = header.index("兜在何处")
    except ValueError:
        err("24.3 表头缺必需列（须含 条／名称／落点／兜在何处）：%s" % "｜".join(header))
        return

    table_nums, bad_state = [], []
    VALID_STATES = {"守卫", "人工", "流程", "守卫＋人工"}
    for lineno, l in rows:
        cols = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cols) < len(header):
            err("第 %d 行：24.3 表列数不足（表头 %d 列，此行 %d 列）"
                % (lineno, len(header), len(cols)))
            continue
        try:
            n = int(cols[0])
        except ValueError:
            err("第 %d 行：首列不是条号" % lineno)
            continue
        table_nums.append(n)
        state = cols[i_state].replace("*", "").strip()
        if state not in VALID_STATES:
            bad_state.append("第 %d 行（第 %d 条）落点「%s」不合四态：%s"
                             % (lineno, n, state, "／".join(sorted(VALID_STATES))))
        if not cols[i_name].strip():
            bad_state.append("第 %d 行（第 %d 条）「名称」为空" % (lineno, n))
        if not cols[i_where].strip():
            bad_state.append("第 %d 行（第 %d 条）「兜在何处」为空——须写明落点位置"
                             % (lineno, n))

    if bad_state:
        for b in bad_state:
            err(b)

    missing = sorted(set(arts) - set(table_nums))
    extra = sorted(set(table_nums) - set(arts))
    dup = sorted({n for n in table_nums if table_nums.count(n) > 1})
    if missing:
        err("24.3 表漏登记以下条（新增条款须同时登记落点，见 24.3.1）：第 %s 条"
            % "、".join(map(str, missing)))
    if extra:
        err("24.3 表登记了不存在的条：第 %s 条" % "、".join(map(str, extra)))
    if dup:
        err("24.3 表重复登记：第 %s 条" % "、".join(map(str, dup)))
    if not (missing or extra or dup or bad_state):
        info("24.3 落实总表覆盖全部 %d 条，落点均合法（守卫／人工／流程／守卫＋人工）"
             % len(arts))



# ──────────────── (15) 承诺条文不得含糊（第 25 条） ────────────────

# 含糊词：用在**承诺句**里就等于没承诺（25.3「模糊承诺」）。
# 只扫"承诺类"条文所在的段落，不扫全文——"基本上"在别处（如论述"基本上可以认为"）
# 未必是承诺，全文扫会误伤，本维就失去区分度（24.3.5：给真病征，不给假想病征）。
VAGUE_WORDS = ("基本上", "基本上都", "绝大多数情况下", "一般情况下都", "大致上")


def check_promise(s):
    """(15) 第 25 条须成文，且承诺条文里不得出现含糊词。

    **为什么需要这一维**：25.3 把"模糊承诺"列为三禁之一，但"禁止"若只写在条文里、
    没有断言盯着，写的人仍然会顺手写"基本上都不联网"——**这正是 25.2 事故的原话**。
    本维做两件事：
      A. 第 25 条**须存在**（删掉整条即报错，防"改着改着把约束改没了"）；
      B. 第 25 条正文的**承诺句**（含"承诺／声明／保证／不得／须"的句子）里
         **不得出现含糊词**。

    边界：本维**判不了"这句话是不是真的"**（那属 25.4 人工核对），
    只能判"这句话里有没有含糊词"。**不得据此认为"跑过＝承诺为真"**。
    """
    head("(15) 承诺条文不得含糊（第 25 条）")
    if not _is_rules_itself(s):
        info("非铁律本体，本维跳过")
        return
    m = re.search(r"(?ms)^### 第 25 条 .*?(?=^### 第 26 条 |^---\s*\n\s*## 附录)", s)
    if not m:
        err("未找到第 25 条（对外承诺的守门）——承诺约束缺失，SECURITY／README 里的"
            "承诺将无人看管")
        return
    body = m.group(0)

    # 按"**连续文字块**"判，不按单行判。
    # 2026-10-22 实测踩坑：中文长句在源码里是**折行**的，一句话被拆成两三行，
    # 「承诺」二字常落在上一行、含糊词落在下一行——若按行判，注入用例当场漏过
    # （冒烟报"第 15 维未报错"，而当时我以为是守卫写对了）。**段落才是语义单位，行不是。**
    blocks, cur = [], []
    for line in body.splitlines():
        st = line.strip()
        # 表格与引用块属"举例／引用"：里面出现含糊词往往正是在批判它，不该算违规
        if not st or st.startswith("|") or st.startswith(">") or re.match(r"^#{2,4} ", st):
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            continue
        cur.append(st)
    if cur:
        blocks.append(" ".join(cur))

    # 自指豁免：条文里**引述并批判**含糊写法的那一段（25.2 引述事故原话），
    # 里面必然含含糊词——不豁免就会"条文不能描述它自己禁止的东西"。
    # 判据取"与含糊词同段出现的批判标记"，而不是放行整条或放行某个固定句子：
    # 只要同段里明说了要禁（引用形式加引号 ＋ 出现"禁"或"不许"），即视为批判性引述。
    hits = []
    for b in blocks:
        if not re.search(r"承诺|声明|保证|不得|须", b):
            continue          # 非承诺性论述（背景、举例、分工说明）不扫
        # 批判性引述的判据（同段须同时具备三条，缺一不放）：
        #   ① 明说这是错的（"不是笔误""事故""错"）；
        #   ② 含糊词被引号括起来（是被引的原话，不是自己在承诺时用的词）；
        #   ③ 该段整体在讲"为什么会犯"或"为什么要禁"，不是承诺正文本体。
        is_quote = ("\u201c" in b or "\u300c" in b)
        is_critique = bool(re.search(r"(不是笔误|事故|错误|反例|本就错|是错的)", b))
        if is_quote and is_critique:
            continue
        for w in VAGUE_WORDS:
            if w in b:
                i = b.find(w)
                hits.append((w, b[max(0, i - 24):i + 24]))
                break
    if hits:
        for w, seg in hits:
            err("第 25 条承诺性文字里出现含糊词「%s」——按 25.3，用含糊词覆盖例外等于没承诺"
                "（上下文：…%s…）" % (w, seg))
        return
    info("第 25 条已成文，承诺句无含糊词（「基本上」类词只许出现在举例批判处）"
         "——注意：本维只查措辞，承诺是否为真须人工按 25.4 核")

# ──────────────── (14) 在线版须与源同步 ────────────────

ONLINE_MD = os.path.join(DEV, "maint", "scratch", "DEV-RULES.online.md")

# 目录**说明段**：从「目录（」起头，吃满连续非空行（含跨行续写）。
# 2026-10-19 修：旧版归一化用的 `^目录.*锚点.*$` 是**单行**正则，而源的说明段本就是
# **两行**——于是归一化只吃掉第一行，第二行「由 `…make-online-md.py` 派生…」留了下来，
# 与在线版（整段已被替换成单行）对不上，本维当场报「约 963 行有差异」。
# 那次报错**报的是伪问题**（两版其实同步）：判据把「版式差异」误当成了「内容漂移」。
RE_TOC_NOTE = re.compile(r"^目录（[^\n]*(?:\n(?!\n)[^\n]*)*", re.M)
RE_TOC_LINK = re.compile(r"^(\s*)- \[([^\]]+)\]\(#[^)]+\)\s*$", re.M)


def _normalize_for_compare(t):
    """把「目录区两版必然不同的部分」抹平，只留可逐字比对的正文。

    三步（次序有讲究）：
      1. 整段删掉目录说明段（源为两三行、在线版为一行，段落边界才是可比单位）；
      2. 目录条目 `[文字](#锚点)` → `文字`（源有链接、在线版无）；
      3. 兜底删掉残余的「目录（…」行（若第 1 步因版式再变而漏网，这里不至于把说明
         当正文比出假差异）。
    """
    t = RE_TOC_NOTE.sub("", t)
    t = RE_TOC_LINK.sub(lambda m: "%s- %s" % (m.group(1), m.group(2)), t)
    return re.sub(r"^目录（.*$", "", t, flags=re.M)


def check_online_md(s):
    """(14) 在线版（目录去链接）须与源文件同步生成，不得陈旧。

    **为什么需要这一维**（2026-10-17 实证）：
    铁律同时要在两处阅读——本地/GitHub（认 GitHub 锚点）与腾讯文档在线版
    （**不认** GitHub 锚点，点目录"找不到锚点"）。两处规则不同，只能各出一份：
    源文件保留锚点，在线版由 `make-online-md.py` 派生（目录改纯文字大纲）。

    派生文件的风险是**陈旧**：源改了、忘了重跑转换，在线版就停在旧内容。
    所以本维做三件事：
      A. 在线版**存在**（不存在先提示生成，不判错——可能还没上传过）；
      B. 在线版**零锚点链接残留**（转换必须彻底）；
      C. 两版**归一化后逐字节相等**（即"除了目录区，正文一模一样"）。

    C 是关键：它同时防住"转发时误伤正文"与"源改了没重生成"。
    **归一化只抹「两版必然不同」的部分**（目录说明段、目录链接形态）——抹多了，
    本维就失去区分度；抹少了，又会把版式差异误报成内容漂移（2026-10-19 就栽在后者）。
    """
    head("(14) 在线版须与源同步")
    # ⚠ 2026-10-20 修（同上）：在线版是**铁律本体**的派生件，拿别的文档来比必假报。
    if not _is_rules_itself(s):
        info("待检内容不是铁律本体（%s）——在线版是铁律本体的派生物，本维不适用，跳过"
             % os.path.basename(RULES))
        return
    if not os.path.exists(ONLINE_MD):
        info("在线版未生成（%s）——需要上传时再跑 "
             "`maint/tools/make-online-md.py`" % os.path.relpath(ONLINE_MD, DEV))
        return

    online = open(ONLINE_MD, encoding="utf-8").read()

    # B：零锚点残留
    resid = re.findall(r"^\s*- \[[^\]]+\]\(#", online, re.M)
    if resid:
        err("在线版仍有 %d 条锚点链接（目录须为纯文字）——重跑 "
            "`maint/tools/make-online-md.py`" % len(resid))
        return

    # B2：说明段必须是**单行**。转换会把多行说明折成一行；若在线版里说明仍跨行，
    # 要么转换只吃掉了第一行（旧 bug 的形态），要么有人手工改过。
    note_block = RE_TOC_NOTE.search(online)
    if note_block and "\n" in note_block.group(0):
        err("在线版目录说明段仍为多行（%d 行）——转换未整段替换；重跑 "
            "`maint/tools/make-online-md.py`" % (note_block.group(0).count("\n") + 1))
        return

    # C：归一化后逐字节比对
    a, b = _normalize_for_compare(s), _normalize_for_compare(online)
    if a == b:
        info("在线版与源同步（目录已去锚点，正文逐字节一致）")
    else:
        # 只提示不一致的规模与**头一处**差异，不猜原因
        la, lb = a.splitlines(), b.splitlines()
        diff = sum(1 for x, y in zip(la, lb) if x != y) + abs(len(la) - len(lb))
        first = next(((i + 1, x, y) for i, (x, y) in enumerate(zip(la, lb)) if x != y),
                     None)
        where = ""
        if first:
            where = "；头一处差异在第 %d 行：「%s」↔「%s」" % (
                first[0], first[1].strip()[:40], first[2].strip()[:40])
        err("在线版与源**不同步**（约 %d 行有差异）——源改动后须重跑 "
            "`maint/tools/make-online-md.py`，否则上传的是旧内容%s" % (diff, where))


# ── (17) 正文零实现名 · 对照表路径真实 ─────────────────────────────────────
# 2026-10-30 结构性改造。此前规范是**两份**：源（含本机路径）＋ 对外派生版（全角色称谓），
# 靠"改了源记得重跑生成器"维持一致。实测靠不住——派生件的版本行没跟上文件名（v1.0.3 内文
# 仍写 v1.0.2）、三份对外版并存无人标当前版、台账漏登最新那份，最后生成器把输出路径写死在
# 源码里，一次没改就先跑，把已交付的 v1.0.2 整个覆盖掉（那份不在版本控制里，只能靠旧源＋旧
# 生成器重建）。根因不是手滑：**93.8% 逐字相同的两份文件，差异散在 92 个变更块里**，任何一处
# 漏改都不会被发现。
# 现改为**一份正文**：正文一律角色称谓，两端通用、对外直接给这一份；角色到本机落点的映射
# 集中在同目录的实现对照表。本维守这个新结构的两头：
#   A. 正文不许把路径写回去（否则"一份"又退化成"一种写法两份维护"）；
#   B. 对照表写的路径必须真存在（否则读者顺着表去找，找不到）。
# **判据刻意从窄**：只认清单里的实现名与本机路径前缀；示例代码（`shell=True`、`urlopen`）、
# 平台通用文件名（`SKILL.md`／`VERSION.md`）、通用目录建议名（`samples/`）一律不算——
# 它们既是真实材料，也不是"读者照着找会落空"的东西。
IMPL_NAMES = (
    "maint/", "dist/", "doc-compliance-review",
    "DEVLOG", "OPEN-ISSUES", "CHANGELOG.md",
    "pack.py", "check.py", "publish.py", "version.py",
    "smoke-test", "make-docx", "gen-ledger", "make-online-md",
    "check-dev-rules", "check-separation", "meta-smoke", "sync-clause-refs",
    "build-legal-db",
)
IMPL_TABLE = os.path.join(DEV, "DEV-RULES.实现对照.md")


def check_impl_table(s):
    head("(17) 正文零实现名 · 对照表路径真实")

    # ── A 正文不得含本机实现名 ──
    # `dev/` 单列并**要求前有空白或反引号**：正文卷首与 12.1.1 要写出对照表的文件名
    # `DEV-RULES.实现对照.md`，裸子串匹配不会命中它（大小写不同），但若日后有人写
    # `dev/DEV-RULES.md` 就会命中——那正是要抓的。
    hits = []
    for i, l in enumerate(s.splitlines(), 1):
        for w in IMPL_NAMES:
            if w in l:
                hits.append("第 %d 行含 `%s`：%s" % (i, w, l.strip()[:44]))
                break
    if hits:
        for h in hits:
            err("正文出现本机实现名（应改角色称谓，落点写进实现对照表）——" + h)
    else:
        info("正文零本机实现名（%d 项清单全未命中）——同一份文件可原样对外"
             % len(IMPL_NAMES))

    # ── B 对照表内路径须真实存在 ──
    if not os.path.exists(IMPL_TABLE):
        err("实现对照表缺失：%s——正文卷首与 12.1.1 都指向它，缺了每一处角色称谓都无落点"
            % IMPL_TABLE)
        return
    tbl = open(IMPL_TABLE, encoding="utf-8").read()
    fenced = in_fence_lines(tbl)
    cands = set()
    for i, line in enumerate(tbl.splitlines(), 1):
        if i in fenced:
            continue
        for c in re.findall(r"`([^`\n]+)`", line):
            c = c.strip()
            # 排除：空、含空格（是句子不是路径）、命令行参数、代码片段（`# net-tier: L0`）
            if not c or " " in c or c.startswith("--") or c.startswith("#"):
                continue
            if "/" in c or re.match(r"^[\w\-.·]+\.(md|py|json|zip)$", c):
                cands.add(c)

    PREFIX = {"maint/": DEV + "/maint/", "dev/": DEV + "/", "dist/": DIST + "/",
              "doc-compliance-review/": SKILL + "/",
              "scripts/": SKILL + "/scripts/",
              "~/.codebuddy/skills/": RUN + "/"}
    SEARCH = [DEV, os.path.join(DEV, "maint"), os.path.join(DEV, "maint", "tools"),
              os.path.join(DEV, "maint", "scratch"), SKILL,
              os.path.join(SKILL, "scripts"), os.path.join(SKILL, "core"),
              os.path.join(SKILL, "assets"), os.path.join(SKILL, "samples"),
              DIST, "/workspace"]
    exts = {".skill", ".zip", ".py", ".md", ".json"}
    missing = []
    for c in sorted(cands):
        if c in exts:
            continue
        p = c if c.startswith("/") else None
        if p is None:
            for k, v in PREFIX.items():
                if c.startswith(k):
                    p = v + c[len(k):]
                    break
        if p is None:
            for d in SEARCH:
                if os.path.exists(os.path.join(d, c)):
                    p = os.path.join(d, c)
                    break
            else:
                if re.match(r"^[\w\-.·]+\.(md|py|json)$", c):
                    missing.append("%s（各搜索目录均无）" % c)
                continue
        if not os.path.exists(p):
            missing.append("%s → %s" % (c, p))
    if missing:
        for m in missing:
            err("实现对照表里的路径不存在：%s（改名或删除后未同步本表——两处不一致时"
                "以正文的角色为准，改表，不得反过来改正文迁就路径）" % m)
    else:
        info("对照表 %d 项路径引用全部真实存在" % len(cands))


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
    print("开发规范（铁律）· 全文自检")
    print("=" * 62)
    check_structure(s)
    check_guide(s)
    check_refs(s, show="--refs" in args)
    check_external_refs(s)
    check_wording(s)
    check_expression(s)
    check_paths(s)
    check_rules_version(s)
    check_cross_side()
    check_toc_anchor(s)
    check_ref_anchor(s)
    check_bold_heading(s)
    check_meta_rules(s)
    check_closure_table(s)
    check_online_md(s)
    check_promise(s)
    check_open_issues(s)
    check_impl_table(s)
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
