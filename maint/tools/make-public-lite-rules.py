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

    # 卷首自述：出身说明（"它是完整版的抽出版"）与验证记录，属"这一版从哪来、验过什么"，
    # 对外读者打开文件要的是规则。2026-10-21 用户指令：这两段不留。
    ("> **这份文件是什么。** 它是「开发工程规范（铁律）」的**方法论层抽出版**——只保留\n"
     "> **与具体产品形态无关**的条款，去掉项目账本（落实总表、漂移五类表、项目术语表）。\n"
     "> **条款本身可直接用，不需改动**；要办的是**附录 B 那 7 步**\n"
     "> （删账本、换名词、重填落实表、别搬工具、先跑一次空项目）。\n",
     "",
     "卷首整块自述（出身／可直接用／指附录 B）对外读者无用；附录 B 亦被本脚本删除，指过去即死路"),

    # 验证记录整段（2026-10-21 起本文件自带 --self-test，记录属开发侧留痕）
    ("> **验证记录（2026-10-21）**：本文件自检 **0 错 0 警告**；`--self-test` **17 个注入用例\n"
     "> 全部拦住 ＋ 7 个打瘸点全部由 (L0) 发现**。做法是把本文件逐处改坏（删条、款号跳号、\n"
     "> 引用悬空、表少列、表体删空、分隔行不符、写死本机路径、塞回项目名、目录编删项、\n"
     "> 空代码块、加粗无编号、圆圈数字、表格行虚指），断言**对应那维当场报错**；\n"
     "> 再把某维的报错调用全删掉，断言 (L0) 报\"判据失效\"。\n"
     "> **自测当场抓出三个洞，都已修**：款号正则把 `8.4.1` 读成\"款 8.4\"（跳号被掩盖）、\n"
     "> \"已定义款号\"把引用句也算成定义（引用永不悬空＝本维形同虚设）、豁免标注一免全免。\n",
     "",
     "验证记录属开发侧留痕；发布版只给规则与用法"),

    # 检查器用法：**保留**（发布版确实同目录附带检查器，读者要会用），
    # 但"按附录 B 第 5 步另写"必须改指正文——附录 B 已被本脚本删掉，指过去即死路。
    ("> **它只验本文件自身，不验你的项目**——你的项目检查须按附录 B 第 5 步另写\n"
     "> （第 6 步是\"拿另写好的检查去跑\"，第 5 步才是\"另写\"本身，**别指错**）。",
     "> **它只验本文件自身，不验你的项目**——你的项目检查要按第 9 条另写；\n"
     "> **\"另写\"与\"拿写好的去跑\"是两步，别指错**。",
     "附录 B 已删，须改指正文第 9 条（验证手法）"),

    ("在开发侧建一个 `DEVLOG.md` 用它，并在首次写入时注明\"暂定，待确认\"。",
     "在开发侧建一个**开发日志**用它，并在首次写入时注明\"暂定，待确认\"。",
     "`DEVLOG.md` 是本项目文件名 → 角色称谓"),

    # 8.3 例外：悬置若属"本文件自身"，原写"登记在文末版本沿革下的悬置栏"——
    # 版本沿革已删，改为"按开发侧台账登记"（发布版不维护自身沿革）。
    ("   登记在本文末「本文件版本沿革」下面的**悬置栏**，不占项目登记容器——\n"
     "   本文件要能被单独拿走用，不能反过来依赖某个项目的日志文件。",
     "   登记在**开发侧台账**（不随本文件分发）下面的**悬置栏**，不占项目登记容器——\n"
     "   本文件要能被单独拿走用，不能反过来依赖某个项目的日志文件。",
     "版本沿革已删；发布版不维护自身沿革，故悬置栏改挂开发侧台账"),
]

# 2026-10-21 改：**不再整块抹卷首**。上一版用 drop_preamble() 把版本行之后全删，
# 连"检查器怎么用"一起删了——而发布版本就**同目录附带**检查器，读者要会用。
# 现改为逐条精确删（见 RULES 里三条卷首规则），保留用法、删掉出身与验证记录。
DROP_PREAMBLE = False


def drop_preamble(text):
    """删掉卷首引用块（版本行之后、第一条 `---` 之前的全部 `>` 自述）。

    卷首自述是写给自己人看的："条款可直接用""抽自哪版""验过什么"——
    对外读者打开文件，要的是规则本身。清完须**只留一个分隔**，
    不能留下连续空行（2.3 版式：块与块之间一个空行＋一个 `---`）。
    """
    lines = text.splitlines(keepends=True)
    # 版本行 = 首个以 `**版本` 开头的行；其后到首个 `---` 之间为卷首自述区
    try:
        v = next(i for i, l in enumerate(lines) if l.startswith("**版本"))
        sep = next(i for i, l in enumerate(lines) if i > v and l.strip() == "---")
    except StopIteration:
        return text
    del lines[v + 1:sep]                       # 版本行之后、分隔线之前全删
    out = "".join(lines)
    # 版本行与 `---` 之间保留**恰好一个**空行
    out = re.sub(r"(\*\*版本[^\n]*\n)\n*(-{3,})", r"\1\n\2", out)
    return out


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
    # (4') 卷首结构：删段最容易在这里留疤——空 `>`、缺 `---`、缺目录。
    #      2026-10-21 实测两次：一次留了孤零零的 `>`，一次把 `---` 顶掉了。
    head = out.split("## 目录")[0]
    if re.search(r"(?m)^>\s*$", head):
        warn.append("卷首残留空引用行 `>`——删段留下的疤，须收掉")
    if not re.search(r"(?m)^-{3,}$", head):
        warn.append("卷首缺分隔线 `---`——引用块与目录之间须有一条")
    if "## 目录" not in out:
        warn.append("缺目录")

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

    # 替换必须在**删卷首之前**：卷首要删的那几段正是 RULES 的 old（先删就必然"未命中"）。
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

    if DROP_PREAMBLE:
        out = drop_preamble(out)
    # 删段留下的"空引用行"：`>` 单独成行是引用块的分段符，段删了它就变成孤零零一条。
    # 收掉卷首那个空 `>`，并保证**引用块与 `---` 之间留一个空行**（否则 `---` 会被
    # 当成引用块内部的续行，整段分隔线失效）。
    out = re.sub(r"(?m)^>\s*\n(?=>\s*\n|\n*-{3,})", "", out)
    out = re.sub(r"(?m)^>\s*\n", "", out, count=1)
    out = re.sub(r"(?m)^(>.*)\n(-{3,})$", r"\1\n\n\2", out)

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
