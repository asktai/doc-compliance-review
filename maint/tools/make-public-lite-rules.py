#!/usr/bin/env python3
"""把精简版铁律（dev/lite/DEV-RULES-LITE.md）派生为**对外发布版**。

与完整版派生脚本（make-public-dev-rules.py）同源同理，但**精简版的发布改动是"删块"
多于"改词"**——发布版要删掉三块只对本开发侧有意义的内容，故本脚本用**结构切分**
（按标题切块）而不是逐条替换。

删哪三块、为什么删（2026-10-20 定，用户指定）：
  ① 附录 B「从完整版迁移的检查单」——那是**从完整版迁过来时**用的一次性清单，
     对外读者没迁过、用不上；留着反而让人以为必须先读完整版。
  ② 本文件版本沿革——发布版版本体系独立（重起 v1.0.0），沿革属开发侧台账。
  ③ 卷首「这份文件是什么」——正文只讲规则，不讲"这一版改了什么、从哪来的"。

每条改动都必须给出理由；改完由 `audit()` 做整篇级复核（空块、残留字样、标题连续性），
有问题即以非 0 退出——**不静默产出**。
"""
import os
import re
import sys

SRC = "/workspace/dev/lite/DEV-RULES-LITE.md"
OUT = "/workspace/技能开发规范（通用铁律）-v1.0.0.md"

# 待删块（按二级标题精确匹配，两块都删到文件末或下一个二级标题之前）
DROP_SECTIONS = ("## 附录 B 从完整版迁移的检查单", "## 本文件版本沿革")

# (原文, 替换, 说明)
RULES = [
    ("# 开发工程规范 · 通用精简版（铁律 Lite）",
     "# 技能开发规范（通用铁律）",
     "发布版标题：面向技能开发与通用项目，去掉内部称呼「Lite」"),

    # 适用范围：保留"技能开发 ＋ 任意项目"的扩张意图，但**消除两解**。
    # 原文案「技能开发与任意项目的开发工作规范通用适配」里"通用适配"是形容、不是范围，
    # 读者无法据此判断效力边界；改为显式的"既…也…"，与 1.1 的"全部开发工作"对齐。
    ("**版本 v1.0.4** ｜ 首次成文：2026-10-20 ｜ **适用范围：任意项目的开发工作**",
     "**版本 v1.0.0** ｜ 首次成文：2026-10-20 ｜ "
     "**适用范围：既适用于技能开发，也适用于任意项目的开发工作**",
     "版本重起算；适用范围改为显式'既…也…'，消除'通用适配'这种形容词式范围"),

    # 卷首自述：删掉"它是完整版的抽出版"这类出身说明（正文只讲规则）
    ("> **这份文件是什么。** 它是「开发工程规范（铁律）」的**方法论层抽出版**——只保留\n"
     "> **与具体产品形态无关**的条款，去掉项目账本（落实总表、漂移五类表、项目术语表）。",
     "",
     "卷首出身说明属'这一版从哪来'，对外读者不需要；正文只讲规则"),

    ("在开发侧建一个 `DEVLOG.md` 用它，并在首次写入时注明\"暂定，待确认\"。",
     "在开发侧建一个**开发日志**用它，并在首次写入时注明\"暂定，待确认\"。",
     "`DEVLOG.md` 是本项目文件名 → 角色称谓"),

    # 卷首"怎么用检查器"整段：发布版**不带检查器**（检查器是开发侧工具），
    # 且原段引用了本脚本要删掉的两块（附录 B 第 5 步、文末版本沿革）——
    # 不改写就会留下两处指向已删块的悬空引用，读者按它去找会扑空。
    # 卷首第 2 段仍指"附录 B 那 7 步"——附录 B 是**从完整版迁移时用**的一次性清单，
    # 对外读者没迁过、也拿不到；发布版里它已被删，指过去就是死路。
    ("> **条款本身可直接用，不需改动**；要办的是**附录 B 那 7 步**\n"
     "> （删账本、换名词、重填落实表、别搬工具、先跑一次空项目）。",
     "> **条款本身可直接用，不需改动**；使用者只需按第 9 条为自己的项目配好验证手段，\n"
     "> 并按第 16 条逐条登记落点（**不附落实总表**——那是每个项目自己的账，见 16.4）。",
     "附录 B 属迁移期一次性清单，发布版已删该块，此处须改指正文条款"),

    # 8.3 例外：悬置若属"本文件自身"，原写"登记在文末版本沿革下的悬置栏"——
    # 版本沿革已删，改为"按开发侧台账登记"（发布版不维护自身沿革）。
    ("   登记在本文末「本文件版本沿革」下面的**悬置栏**，不占项目登记容器——\n"
     "   本文件要能被单独拿走用，不能反过来依赖某个项目的日志文件。",
     "   登记在**开发侧台账**（不随本文件分发）下面的**悬置栏**，不占项目登记容器——\n"
     "   本文件要能被单独拿走用，不能反过来依赖某个项目的日志文件。",
     "版本沿革已删；发布版不维护自身沿革，故悬置栏改挂开发侧台账"),

    ("> 检查脚本随本文件**同目录**附带：`lite-selfcheck.py`\n"
     "> （用法：`python3 lite-selfcheck.py DEV-RULES-LITE.md`）。\n"
     "> **它只验本文件自身，不验你的项目**——你的项目检查须按附录 B 第 5 步另写\n"
     "> （第 6 步是\"拿另写好的检查去跑\"，第 5 步才是\"另写\"本身，**别指错**）。\n"
     "> 本版相对 v1.0.0 的改动见文末**「本文件版本沿革」**；**每版的取舍与推翻记录都在那里**\n"
     "> （正文只讲规则，不讲\"这一版改了什么\"）。",
     "> **本版不附带检查器**——检查器属开发侧工具，随开发侧维护版走，不随本发布版分发。\n"
     "> 使用者须按第 9 条为自己的项目另写检查；**\"另写\"与\"拿写好的去跑\"是两步，别指错**。\n"
     "> 本文件**不设版本沿革段**：正文只讲规则，不讲\"这一版改了什么\"。",
     "发布版不带检查器；原段引用附录 B 与版本沿革，二者均被本脚本删除，须一并改写"),
]


def drop_sections(text):
    """按二级标题整块删除——返回 (新文本, 已删块名列表)。"""
    lines = text.splitlines(keepends=True)
    # 定位所有二级标题及其行号
    heads = [(i, l.rstrip("\n")) for i, l in enumerate(lines) if l.startswith("## ")]
    dropped, cut = [], []
    for idx, (i, head) in enumerate(heads):
        if head not in DROP_SECTIONS:
            continue
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        cut.append((i, end))
        dropped.append(head)
    for i, end in reversed(cut):          # 倒序删，避免行号位移
        del lines[i:end]
    text = "".join(lines)

    # 目录是正文标题的**引用**——块删了、目录项还留着，就是悬空引用（2.3.3）。
    # 2026-10-21 实测：上一轮手工派生正是漏了这一步，目录里至今挂着两条已删条目。
    for d in dropped:
        name = d.lstrip("# ").strip()
        text = re.sub(r"^\s*- \[%s\]\([^)]*\)\n" % re.escape(name), "", text, flags=re.M)
    return text, dropped


def audit(out, dropped):
    """整篇级复核：**派生动作自己制造出来的缺陷**。

    逐条替换都是局部正确的，但删块会留下空洞（目录还指着已删的条目）、
    删词会留下悬念（标题改了目录没跟）。这类副作用只有看整篇才暴露。
    """
    warn = []
    # (1) 目录里是否还留着已删掉的条目
    for d in dropped:
        name = d.lstrip("# ").strip()
        for l in out.splitlines():
            if l.strip().startswith("- [") and name in l:
                warn.append("目录仍指向已删块「%s」：%s" % (name, l.strip()[:60]))
    # (2) 正文是否仍**引用**已删块——删了块、正文还写着"见附录 B 第 5 步"，读者会扑空。
    #     2026-10-21 实测：卷首那段正是这种情况，而只查目录项抓不到（引用在正文里）。
    for d in dropped:
        name = d.lstrip("# ").strip()
        # 取"附录 B"这种**可指代的最短形态**；只取首词会变成"附录"，把附录 A 也误报进来
        parts = name.replace("## ", "").split(" ")
        short = " ".join(parts[:2]) if len(parts) > 1 else parts[0]
        for i, l in enumerate(out.splitlines(), 1):
            if short in l and not l.strip().startswith("- ["):
                warn.append("正文仍引用已删块「%s」（行 %d）：%s" % (name, i, l.strip()[:60]))
    # (3) 空代码块
    lines = out.splitlines()
    open_at = None
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("```"):
            if open_at is None:
                open_at = i
            else:
                if i - open_at == 1:
                    warn.append("空代码块（行 %d-%d）" % (open_at, i))
                open_at = None
    # (3) 条号连续性：删块不应打断正文条号
    arts = [int(m.group(1)) for m in
            (re.match(r"^#{2,3} 第 (\d+) 条", l) for l in lines) if m]
    if arts and arts != list(range(1, len(arts) + 1)):
        warn.append("条号不连续：%s" % arts[:20])
    # (4) 残留的内部称呼／项目绑定
    for w in ("DEVLOG", "maint/", "dist/", "铁律 Lite", "完整版迁移"):
        if w in out:
            warn.append("残留字样：%s" % w)
    return warn


def main():
    src = open(SRC, encoding="utf-8").read()

    out, dropped = drop_sections(src)
    missing_drop = [d for d in DROP_SECTIONS if d not in src]
    if missing_drop:
        print("[E] 待删块未找到（源结构已变，需重核）：%s" % "、".join(missing_drop))
        return 1

    missed = []
    for old, new, why in RULES:
        if old not in out:
            missed.append(old.split("\n")[0][:60])
            continue
        out = out.replace(old, new, 1)
    if missed:
        print("以下替换未命中（原文已变，需重核）：")
        for m in missed:
            print("  - " + m)
        return 1

    warn = audit(out, dropped)
    open(OUT, "w", encoding="utf-8").write(out)
    print("已写出 %s（替换 %d 条，删块 %d 个）" % (OUT, len(RULES), len(dropped)))
    for d in dropped:
        print("  [i] 已删块：" + d)
    for w in warn:
        print("  [W] " + w)
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
