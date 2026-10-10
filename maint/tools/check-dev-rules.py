#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发工程规范（铁律）· 全文自检（六维）
==============================================================================
对 `dev/DEV-RULES.md` 做机械自检，覆盖六个维度：

  ① 结构        条号连续、**条标题格式统一**、章序号连续、章区间声明与覆盖
  ② 导读表      文首"三条铁律"导读表的条号与名称，须与正文标题一致（双源比对）
  ③ 条号引用    引用的条号必须存在（悬空引用即报错）；--refs 另打印引用上下文供人工复核
  ④ 用词        已废止词（维护侧／开发端／实例侧等）不得在正文残留；术语说明语境除外
  ⑤ 表述        不得使用相对引用（"见下方"等）；日期月／日须补零；第 19 条自身反例除外
  ⑥ 路径真实性  正文反引号中的文件／目录引用必须真实存在

归属说明
    · 本脚本属于**维护侧**（`/workspace/dev/maint/tools/`），**不随技能包分发**；
    · 与 `make-card.py` 同类：开发侧工具，不进包、不参与发布链。

为什么要它（铁律第 16 条）
    "能做成自动守卫的，就不要只靠人跑一次。"——**铁律自身也受此条约束**。
    2026-09-29 实测教训：首版检查用的是"人工 ＋ 临时脚本"，当场暴露两类问题——
    ① 临时脚本**自身 4 处 bug**（正则漏抓、`str(i) in nums` 类型错、区间误计、路径白名单不全），
       每次都**先报出"问题"、经核实才知是误报**；
    ② 第 3 条标题格式不统一（条号后缺空格）**长期潜伏**，正是它让脚本正则漏抓该条。
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
    否则格式一旦不统一就会漏抓该条（2026-09-29 踩过的坑）；格式问题由 ① 单独报出。"""
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


# ────────────────────────────── ① 结构 ──────────────────────────────

def check_structure(s):
    head("① 结构")
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

    rng = [(n, int(a), int(b)) for n, a, b in
           re.findall(r"^## (第.+?章) .*?（第 (\d+)—(\d+) 条）\s*$", s, re.M)]
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


# ────────────────────────────── ② 导读表 ──────────────────────────────

def check_guide(s):
    head("② 导读表 vs 正文（双源比对）")
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


# ────────────────────────────── ③ 条号引用 ──────────────────────────────

def check_refs(s, show=False):
    head("③ 条号引用")
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


# ────────────────────────────── ④ 用词 ──────────────────────────────

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
    head("④ 用词（术语纪律）")
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


# ────────────────────────────── ⑤ 表述 ──────────────────────────────

def check_expression(s):
    head("⑤ 表述（相对引用／日期形态）")
    seg19 = section(s, "### 第 19 条")           # 该条表格内是**反例**，须排除
    body = s.replace(seg19, "") if seg19 else s

    hits = [l.strip()[:70] for l in body.splitlines()
            if any(p in l for p in REL_REFS)]
    if hits:
        for h in hits:
            err("相对引用（应为绝对编号，如「见第 17 条」）：%s" % h)
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


# ────────────────────────────── ⑥ 路径真实性 ──────────────────────────────

def check_paths(s):
    head("⑥ 路径引用真实性")
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
    print("     作用：提交涉及 DEV-RULES.md 时自动跑本脚本并打印结果；不阻止提交。")
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
