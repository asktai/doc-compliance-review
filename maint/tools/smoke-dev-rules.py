#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铁律全量冒烟——**证明守卫真的拦得住**，而不只是"跑一遍通过"。

依据：铁律 19.2「守卫自身也要验证」——新增／修改守卫后，须用**注入测试**
证明它真的拦得住；副本操作**不得污染正式文件**（改完校验源码哈希未变）。

做法（三段）：
  A 基线：正式文件跑一遍，必须全过（rc=0）；同时记录正式文件 sha256。
  B 注入：对自检脚本的**每一维**各构造一处"故意改坏"的**副本**，
          断言该维**必须报错**；拦不住即为守卫失效（或"摆样子"，见 10.5.2）。
  C 还原：全部注入只在副本上进行；收尾校验正式文件哈希与 git 状态均未变。

用法：
  python3 maint/tools/smoke-dev-rules.py            # 全量冒烟
  python3 maint/tools/smoke-dev-rules.py -v         # 连带打印每条守卫的报错原文

退出码：0＝全部通过（含"每维都拦得住"），1＝有维拦不住或基线未过。
"""

import os
import re
import sys
import shutil
import hashlib
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))            # /workspace/dev
RULES = os.path.join(DEV, "DEV-RULES.md")
CHECK = os.path.join(DEV, "maint", "tools", "check-dev-rules.py")
RUN = os.path.expanduser("~/.codebuddy/skills/doc-compliance-review")

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def digest(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_check(path=None):
    """跑自检脚本，返回 (rc, 输出文本)。path=None 即跑正式文件。"""
    cmd = [sys.executable, CHECK]
    if path:
        cmd += ["--file", path]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=DEV)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def parse_dims(out):
    """把自检输出按维度切分：{维号: [报错文本, ...]}。

    维度标题形如「(1) 结构」；其下的「  [E] …」为该维报错。
    """
    dims, cur = {}, None
    for line in out.splitlines():
        m = re.match(r"^\((\d+)\)", line.strip())
        if m:
            cur = int(m.group(1))
            dims.setdefault(cur, [])
            continue
        if cur is not None and "[E]" in line:
            dims[cur].append(line.strip())
    return dims


# ───────────────────────── 注入用例 ─────────────────────────
# 每条：维号 → (用例名, 注入函数, 期望报错关键词)
# 注入函数接收铁律全文，返回改坏后的文本；**只改传入的字符串**，不碰磁盘正式文件。

def _sub1(s, old, new):
    """替换第一处；找不到返回 None（由调用方判为"用例失效"）。"""
    return None if old not in s else s.replace(old, new, 1)


def inj_struct_gap(s):
    """(1) 条号连续性：把第 7 条改号为 8，造成缺 7。"""
    return _sub1(s, "### 第 7 条", "### 第 8 条")


def inj_struct_fmt(s):
    """(1) 条标题格式：去掉条号后的空格。"""
    m = re.search(r"^### 第 (\d+) 条 (\S)", s, re.M)
    if not m:
        return None
    return s.replace("### 第 %s 条 " % m.group(1), "### 第 %s 条" % m.group(1), 1)


def inj_guide(s):
    """(2) 导读表 vs 正文：篡改导读表里的条名称，使其与正文标题不符。

    注：最初改的是**正文标题**（在条号后插字），但导读表比对用 `name in 正文标题`，
    插入后名称仍是子串 → 抓不到。**注入须破坏被比对的那个字段本身。**
    """
    return re.sub(r"(\| \*\*第 \d+ 条\*\* \| )([^|]+?)(\s*\|)",
                  lambda m: m.group(1) + "注入篡改" + m.group(3), s, count=1)


def inj_refs(s):
    """(3) 悬空引用：引用一条不存在的第 99 条。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：详见第 99 条的相关规定。\n\n## 第一章")


def inj_wording(s):
    """(4) 术语纪律：正文插入废止词。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：该工作由维护侧负责。\n\n## 第一章")


def inj_reldir(s):
    """(5) 相对引用：插入"见下"。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：细节见下。\n\n## 第一章")


def inj_date(s):
    """(5) 日期形态：插入未补零日期。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：2026-1-5 记录。\n\n## 第一章")


def inj_circle(s):
    """(5) 编号字符：插入圆圈编号。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：其一①其二②。\n\n## 第一章")


def inj_oldnum(s):
    """(5) 编号形态：插入旧形态 (1)。

    注：须让 `(1)` 落在**行首**（守卫匹配 `^[ \\t]*(?:\\d+\\.|\\(\\d+\\))[ \\t]`）；
    写成「注入测试：(1) …」因不在行首而抓不到——**注入要落在正则的锚点上**。
    """
    return _sub1(s, "\n## 第一章", "\n(1) 注入测试旧编号形态。\n\n## 第一章")


def inj_paths(s):
    """(6) 路径引用真实性：引用一个不存在的文件。"""
    return _sub1(s, "\n## 第一章", "\n注入测试：见 `dev/NoSuchFileForSmoke.md`。\n\n## 第一章")


def inj_version(s):
    """(7) 铁律版本串：把真源头部版本号改旧，制造与 DEVLOG 文件头的漂移。"""
    return _sub1(s, "**版本 v1.", "**版本 v0.")


def inj_toc(s):
    """(9) 目录锚点：篡改目录里**条级**条目的标题，使其与正文不符。

    注：目录正则只认 `- [第 N 条 标题](#锚点)`；章级条目（`- [第一章 …]`）
    不在比对范围内，改它抓不到。
    """
    return re.sub(r"(- \[第 \d+ 条 )([^\]]+)(\]\(#)",
                  lambda m: m.group(1) + "注入篡改" + m.group(3), s, count=1)


def inj_ref_anchor(s):
    """(10) 引用锚点：裸写「第 N 行」而不带父级（历史事故的形态）。

    注：本维只管「第 N 行」这一种形态；写「参见表 3」不在其判定范围内。
    """
    return _sub1(s, "\n## 第一章", "\n注入测试：见第 4 行。\n\n## 第一章")


def inj_bold(s):
    """(11) 加粗行首段落须带编号：插入无编号的加粗行首段。

    注：须插在**正文区**（第 1 条之后）——插在首条之前会被判为「导读区」放行；
    且上一行须为空行，否则被判为「续行」放行。
    """
    return _sub1(s, "\n### 第 2 条",
                 "\n**注入测试的无编号加粗段落。**\n\n### 第 2 条")


def inj_meta(s):
    """(12) 编号元规则退回导读区：把"表格例外"的特征短句从正文里抹掉。

    这是**最贴近历史事故**的注入——原状就是这四条只活在导读区裸段里。
    只需让正文中的特征短句消失，即应被 (12) 抓到。
    """
    return _sub1(s, "表内行不编号", "表内行任意（注入抹去特征短句）")


CASES = [
    (1, "条号连续性（缺一条）", inj_struct_gap, "条号"),
    (1, "条标题格式（缺空格）", inj_struct_fmt, "标题格式"),
    (2, "导读表与正文不一致", inj_guide, "导读"),
    (3, "悬空引用（第 99 条）", inj_refs, "悬空"),
    (4, "废止词残留（维护侧）", inj_wording, "废止词"),
    (5, "相对引用（见下）", inj_reldir, "相对引用"),
    (5, "日期未补零", inj_date, "补零"),
    (5, "圆圈编号", inj_circle, "键入"),
    (5, "旧编号形态 (1)", inj_oldnum, "编号形态"),
    (6, "路径引用不存在", inj_paths, "路径引用不存在"),
    (7, "铁律版本串漂移", inj_version, "铁律版本"),
    (9, "目录锚点不一致", inj_toc, "目录"),
    (10, "表格行引用缺父级", inj_ref_anchor, "父级"),
    (11, "加粗行首无编号", inj_bold, "编号"),
    (12, "编号元规则掉出正文", inj_meta, "未在正文成文"),
]

# 第 (8) 维比对的是「开发侧技能目录 ↔ 运行实例」，改铁律副本碰不到，
# 单列一档：临时改运行实例一个文件 → 须报错 → 立即还原并校验哈希。
CROSS_SIDE_PROBE = "VERSION.md"


def main():
    global CHECK
    # --check <path>：指定被测的自检脚本（**元自测用**——把某维守卫临时禁用，
    # 冒烟必须报"该维未拦住"，否则说明冒烟自己在走过场，见铁律 12.5.2）
    a = sys.argv[1:]
    if "--check" in a:
        i = a.index("--check")
        if i + 1 >= len(a):
            print("[E] --check 需要一个路径参数")
            return 1
        CHECK = os.path.abspath(a[i + 1])
    print("铁律全量冒烟（注入式 · 证明守卫拦得住）")
    print("=" * 62)
    print("被测自检脚本：%s" % os.path.relpath(CHECK, DEV))

    if not os.path.exists(RULES):
        print("[E] 未找到铁律：%s" % RULES)
        return 1
    base_hash = digest(RULES)
    src = open(RULES, encoding="utf-8").read()

    # ── A 基线 ──
    print("\n[A] 基线：正式文件须全过")
    rc, out = run_check()
    if rc != 0:
        print("  [E] 基线未过（rc=%d）——先修正式文件，再谈冒烟" % rc)
        print(out)
        return 1
    dims = parse_dims(out)
    covered = sorted(dims)
    print("  [OK] 基线通过；自检共 %d 维：%s" % (len(covered), covered))

    # 覆盖性自检：脚本声称的每一维，用例表里都得有对应注入
    cased = sorted({c[0] for c in CASES} | {8})
    missing = [d for d in covered if d not in cased]
    if missing:
        print("  [E] 以下维度**无注入用例**（守卫未被验证）：%s" % missing)
        return 1
    print("  [OK] 每一维都有注入用例（含第 8 维单独一档）")

    # ── B 注入 ──
    print("\n[B] 注入：逐维断言「必须拦住」")
    tmp = tempfile.mkdtemp(prefix="rules-smoke-")
    fails = []
    try:
        for dim, name, fn, kw in CASES:
            bad = fn(src)
            if bad is None:
                fails.append((dim, name, "用例失效：注入点未命中，需更新用例"))
                print("  [E] (%d) %-22s 用例失效（注入点未命中）" % (dim, name))
                continue
            if bad == src:
                fails.append((dim, name, "用例失效：注入后文本未变"))
                print("  [E] (%d) %-22s 用例失效（文本未变）" % (dim, name))
                continue
            p = os.path.join(tmp, "case.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(bad)
            rc2, out2 = run_check(p)
            d2 = parse_dims(out2)
            hit = d2.get(dim, [])
            ok = rc2 != 0 and hit and any(kw in h for h in hit)
            if ok:
                print("  [OK] (%d) %-22s 拦住：%s" % (dim, name, hit[0][:60]))
            else:
                why = "未报错（守卫失效）" if rc2 == 0 else \
                      "第 %d 维未报错" % dim if not hit else \
                      "报错但不含关键词「%s」" % kw
                fails.append((dim, name, why))
                print("  [E] (%d) %-22s %s" % (dim, name, why))
                if hit and VERBOSE:
                    for h in hit:
                        print("        %s" % h)

        # ── 第 (8) 维：跨侧一致性 ──
        print("  [--] (8) 跨侧一致性（开发侧 ↔ 运行实例）单独一档")
        rp = os.path.join(RUN, CROSS_SIDE_PROBE)
        if not os.path.exists(rp):
            print("      跳过：运行实例不存在（未装机）")
        else:
            bak = open(rp, "rb").read()
            try:
                with open(rp, "wb") as f:
                    f.write(bak + b"\n<!-- smoke-injected -->\n")
                rc8, out8 = run_check()
                d8 = parse_dims(out8)
                hit8 = d8.get(8, [])
                if rc8 != 0 and hit8 and CROSS_SIDE_PROBE in "".join(hit8):
                    print("  [OK] (8) %-22s 拦住：%s" % ("跨侧漂移", hit8[0][:60]))
                else:
                    why = "未报错（守卫失效）" if rc8 == 0 else "第 8 维未报错"
                    fails.append((8, "跨侧漂移", why))
                    print("  [E] (8) %-22s %s" % ("跨侧漂移", why))
            finally:
                with open(rp, "wb") as f:
                    f.write(bak)
            if digest(rp) != hashlib.sha256(bak).hexdigest():
                fails.append((8, "跨侧漂移", "还原失败：运行实例文件哈希未复原"))
                print("  [E] (8) 还原失败——**运行实例被污染**，请立即检查 %s" % rp)
            else:
                print("  [OK] (8) 运行实例已逐字节还原")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── 第 (12) 档：分离守卫（铁律第 9 条）──
    # 分离守卫查的是"技能目录里有没有不该在那的东西"，与铁律正文的十二维不同源，
    # 故与第 (8) 维同法：**造真违规 → 断言拦住 → 立即还原**。
    # 三个用例覆盖三条判定（白名单混入／未登记素材／开发资料越界）。
    print("  [--] (12) 分离守卫（开发侧／技能侧分离）单独一档")
    SEP = os.path.join(DEV, "maint", "tools", "check-separation.py")
    if not os.path.exists(SEP):
        print("      跳过：未找到 %s" % SEP)
    else:
        probe_dir = os.path.join(DEV, "doc-compliance-review", "core")
        probe = os.path.join(probe_dir, "_smoke_ai学习参考.md")
        probe2 = os.path.join(DEV, "doc-compliance-review", "samples", "_smoke_未登记样本.docx")
        cases12 = [
            (probe, "白名单目录混入开发资料", "学习"),
            (probe2, "samples/ 出现未登记素材", "未登记"),
        ]
        for path, name, kw in cases12:
            existed = os.path.exists(path)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("smoke probe\n")
                r = subprocess.run([sys.executable, SEP], capture_output=True,
                                   text=True, cwd=DEV)
                o = (r.stdout or "") + (r.stderr or "")
                if r.returncode != 0 and kw in o:
                    print("  [OK] (12) %-22s 拦住" % name)
                else:
                    why = "未报错（守卫失效）" if r.returncode == 0 else \
                          "报错但不含关键词「%s」" % kw
                    fails.append((12, name, why))
                    print("  [E] (12) %-22s %s" % (name, why))
            finally:
                if not existed and os.path.exists(path):
                    os.remove(path)
        # 还原校验：探针不得残留（否则污染技能目录）
        leftover = [p for p, _, _ in cases12 if os.path.exists(p)]
        if leftover:
            print("  [E] (12) 探针未清理干净：%s" % leftover)
            fails.append((12, "探针清理", "技能目录被污染"))
        else:
            print("  [OK] (12) 探针已清理，技能目录零污染")

    # ── C 还原校验 ──
    print("\n[C] 还原：正式文件不得被污染（铁律 19.2）")
    now = digest(RULES)
    if now != base_hash:
        print("  [E] 铁律文件哈希已变！%s → %s" % (base_hash[:12], now[:12]))
        return 1
    print("  [OK] 铁律 sha256 未变（%s…）" % base_hash[:16])
    # **判据：只看"冒烟运行期间"是否动过东西，而非"工作区是否干净"。**
    # 早期版本拿 `git status` 的未提交改动当泄漏判据——但使用者（或 AI）**正常工作
    # 本就有未提交改动**（例如正在改铁律升版），会被冤枉成"注入泄漏"（2026-10-14
    # 升版 v1.35.0 时实测误报）。故改为：比对**运行前后**各受保护文件的哈希，
    # 只有"冒烟自己动过"才算泄漏——这既可判、又不冤枉人。
    watched = {
        RULES: base_hash,
        os.path.join(DEV, "doc-compliance-review", "scripts", "pack.py"): None,
        os.path.join(DEV, "publish.py"): None,
    }
    leaked = []
    for p, before in watched.items():
        if not os.path.exists(p):
            continue
        if before is None:
            # 运行前未记录（本轮引入的受保护集扩充）——只做存在性提示，不判错
            continue
        if digest(p) != before:
            leaked.append(os.path.relpath(p, DEV))
    g = subprocess.run(["git", "status", "--porcelain"],
                       capture_output=True, text=True, cwd=DEV)
    self_rel = os.path.relpath(os.path.abspath(__file__), DEV)
    dirty = [l for l in (g.stdout or "").splitlines()
             if l.strip() and self_rel not in l]
    if leaked:
        print("  [E] 冒烟运行期间以下受保护文件被改动（注入泄漏）：%s" % leaked)
        return 1
    print("  [OK] 受保护文件在运行期间零改动")
    if dirty:
        # 仅提示：无法区分"使用者正在改"与"泄漏"，不判错（守卫不得冤枉好人）
        print("  [i] 工作区另有 %d 处未提交改动（可能是你正在做的事，不计为泄漏）"
              % len(dirty))

    # ── 汇总 ──
    print("=" * 62)
    if fails:
        print("冒烟**未通过**：%d 项守卫未证明能拦住" % len(fails))
        for dim, name, why in fails:
            print("  · (%d) %s —— %s" % (dim, name, why))
        return 1
    print("冒烟通过：%d 个注入用例全部被拦住，正式文件零污染" % (len(CASES) + 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
