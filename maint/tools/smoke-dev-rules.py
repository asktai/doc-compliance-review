#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""铁律全量冒烟——**证明守卫真的拦得住**，而不只是"跑一遍通过"。

依据：铁律 16.2「守卫自身也要验证」——新增／修改守卫后，须用**注入测试**
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
    return _sub1(s, "### §7", "### §8")


def inj_struct_fmt(s):
    """(1) 条标题格式：去掉条号后的空格。"""
    m = re.search(r"^### §(\d+) (\S)", s, re.M)
    if not m:
        return None
    return s.replace("### §%s " % m.group(1), "### §%s" % m.group(1), 1)


def inj_guide(s):
    """(2) 导读表 vs 正文：篡改导读表里的条名称，使其与正文标题不符。

    注：最初改的是**正文标题**（在条号后插字），但导读表比对用 `name in 正文标题`，
    插入后名称仍是子串 → 抓不到。**注入须破坏被比对的那个字段本身。**
    """
    return re.sub(r"(\| \*\*§\d+\*\* \| )([^|]+?)(\s*\|)",
                  lambda m: m.group(1) + "注入篡改" + m.group(3), s, count=1)


def inj_refs(s):
    """(3) 悬空引用：引用一个不存在的 §99。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：详见 §99 的相关规定。\n\n## 总则与文档结构")


def inj_refs_dotted(s):
    """(3) 悬空引用（数字路径式）：引用一个不存在的款号 19.6。

    2026-10-20 补：原用例只覆盖"第 99 条"这一形态，
    而正文大量引用写成"见 19.6""按 12.5.4.3 办"——凭空写一个不存在的款号，守卫原先不报。
    """
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：按 §19.6 办。\n\n## 总则与文档结构")


def inj_ext_ref(s):
    """(3b) 外部文件里的铁律条号悬空：临时把 check-separation.py 的条号改坏再还原。

    **注意**：本条要改磁盘文件，故不用 CASES 机制——见 main() 里的单列档。
    """
    return None


def inj_wording(s):
    """(4) 术语纪律：正文插入废止词。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：该工作由维护侧负责。\n\n## 总则与文档结构")


def inj_wording_neg(s):
    """(4) 术语纪律：A.3.7（乙）——"非运行实例侧"虽紧带"运行"，仍须按废词拦下。

    2026-10-20 复核指出：原判据只看"紧前是不是'运行'"，于是**反义**写法也被放行。
    """
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：非运行实例侧的改动须另走流程。\n\n## 总则与文档结构")


def inj_reldir(s):
    """(5) 相对引用：插入"见下"。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：细节见下。\n\n## 总则与文档结构")


def inj_date(s):
    """(5) 日期形态：插入未补零日期。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：2026-1-5 记录。\n\n## 总则与文档结构")


def inj_circle(s):
    """(5) 编号字符：插入圆圈编号。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：其一①其二②。\n\n## 总则与文档结构")


def inj_oldnum(s):
    """(5) 编号形态：插入旧形态 (1)。

    注：须让 `(1)` 落在**行首**（守卫匹配 `^[ \\t]*(?:\\d+\\.|\\(\\d+\\))[ \\t]`）；
    写成「注入测试：(1) …」因不在行首而抓不到——**注入要落在正则的锚点上**。
    """
    return _sub1(s, "\n## 总则与文档结构", "\n(1) 注入测试旧编号形态。\n\n## 总则与文档结构")


def inj_paths(s):
    """(6) 路径引用真实性：引用一个不存在的文件。"""
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：见 `dev/NoSuchFileForSmoke.md`。\n\n## 总则与文档结构")


def inj_impl_name(s):
    """(17) 正文零实现名：把本机路径写回正文（改造前的旧形态）。

    这条守的是**结构**，不是措辞：2026-10-30 起规范只有一份正文，正文一律角色称谓，
    对外直接给这一份；一旦有人把 `maint/DEVLOG.md` 这类路径写回正文，"一份两端通用"
    就倒退成"一份要改、一份给外人"两种维护，派生版的历史问题会原样复发。
    """
    return _sub1(s, "\n**1.2**", "\n记入 `maint/DEVLOG.md` 即可。\n\n**1.2**")


def inj_skill_ext(s):
    """(6) 大写扩展名回流：写 `xxx.Skill` 当格式引用（20.4 明令报错）。

    2026-10-20 补：原 `SKILL|Skill` 在白名单里，写了既不查也不报。
    """
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：产物名须为 `xxx.Skill`。\n\n## 总则与文档结构")


def inj_version(s):
    """(7) 铁律版本串：把真源头部版本号改旧，制造与 DEVLOG 文件头的漂移。"""
    return _sub1(s, "**版本 v1.", "**版本 v0.")


def inj_toc(s):
    """(9) 目录锚点：篡改目录里**条级**条目的标题，使其与正文不符。

    注：目录正则只认 `- [§N 标题](#锚点)`；分组条目（`- [分组名 …]`）
    不在比对范围内，改它抓不到。
    """
    return re.sub(r"(- \[§\d+ )([^\]]+)(\]\(#)",
                  lambda m: m.group(1) + "注入篡改" + m.group(3), s, count=1)


def inj_ref_anchor(s):
    """(10) 引用锚点：裸写「第 N 行」而不带父级（历史事故的形态）。

    注：本维只管「第 N 行」这一种形态；写「参见表 3」不在其判定范围内。
    """
    return _sub1(s, "\n## 总则与文档结构", "\n注入测试：见第 4 行。\n\n## 总则与文档结构")


def inj_ref_anchor_table(s):
    """(10) **表格内**裸写「第 N 行」（2026-10-20 补）。

    针对一处实测漏检：守卫原把**所有以 `|` 开头的行整行跳过**（本意是避开
    "表格里的举例"），结果是整张表的行引用**一概不查**——第 22 条那张
    专讲"引用须带父级"的表自己也漏检。现改为：表格行照查，仅跳过
    ① 反引号内片段、② 紧跟否定词（不得／反例／错误写法…）的规则引述。
    """
    return _sub1(s, "| 4 | **数字带口径与出处** |",
                 "| 4 | **数字带口径与出处**（见第 7 行） |")


def inj_bold(s):
    """(11) 加粗行首段落须带编号：插入无编号的加粗行首段。

    注：须插在**正文区**（第 1 条之后）——插在文首块内仍会被放行；
    且上一行须为空行，否则被判为「续行」放行。文首地带的漏判见下一条用例。
    """
    return _sub1(s, "\n### §2",
                 "\n**注入测试的无编号加粗段落。**\n\n### §2")


def inj_bold_letter(s):
    """(11) 字母编号（`A.`／`C.`）判据回归（2026-11-06 补）。

    背景：该维原只认以 `A.` 打头的字母编号，附录 C 用 `C.` 打头时整片误报；
    修法是改成「单个字母 + 点分数字」的通配形态，而不是把 `C` 也写进白名单
    （写死字母等于把版式绑在守卫上，下次换字母又漏）。

    本用例钉住两端：把**一段合法字母编号的列表项**改成无编号，守卫须报；
    若只验证"合法时放行"，那守卫退回"只认 A/C"也能过，等于没钉住。
    """
    marker = "**C.1.1 不新增规则。**"
    if marker not in s:
        raise RuntimeError("找不到附录 C 的字母编号段落（版式变了须同步本用例）")
    return _sub1(s, marker, "**不新增规则。（编号被拆掉）**")


def inj_table_num(s):
    """(5) **表格首列**的编号单元也要查连号（2026-11-06 补）。

    背景：19.4 的 `.1—.4` 改写进表格首列后，连续性守卫看不见（原正则只认段落与列表项），
    父级 19.4 下只剩 `.5`，**报的是"只剩 5"而不是"少了 1—4"**——报错理由错，比不报更难查。
    修法是认表格首列，但**只认"格内有标题文字"的**；格内只有编号的（如 18.5 索引 `| **18.2** |`）
    是指路不是定义，收进来会误报重号。

    本用例钉住"定义"这一端：把表格里某行的编号改坏，须报不连续。
    """
    marker = "| **19.4.2 升级永远由使用者决定** |"
    if marker not in s:
        raise RuntimeError("找不到 19.4 的表格编号行（版式变了须同步本用例）")
    return _sub1(s, marker, "| **19.4.9 升级永远由使用者决定** |")


def inj_table_num_ref(s):
    """(5) 对照组：表格里**只有编号**的格子不得算作定义（2026-11-06 补）。

    反方向钉住：18.5 索引里 `| **18.2** |` 是指路，若被当成定义，18.2 就成了重号，
    守卫会误报"18 → [1,2,2,3,4,5]"。本用例把那一格改成**带标题**的形态——
    此时它**确实**变成了第二次定义，守卫**应当**报重号；若仍不报，说明守卫又把带标题的表格单元漏了。
    """
    marker = "| **18.2** | **遗留**（本条） |"
    if marker not in s:
        raise RuntimeError("找不到 18.5 闭环条款索引行（版式变了须同步本用例）")
    return _sub1(s, marker, "| **18.2 遗留** | **遗留**（本条） |")


def inj_bold_headgap(s):
    """(11) **文首"目录区／过渡段"地带**插入无编号加粗段落（2026-10-20 补）。

    这一例针对的是一处**实测漏判**：守卫原用 `i <= 40` 放行"文件头元信息"，
    且"第 1 条标题之前一概放行"——两处都卡位置、不卡内容。
    于是目录区之后、第 1 条之前（本例约第 44 行）的无编号加粗段落**照样通过**。
    现改为：只有"元信息块（第 1 行→导读起点前）＋ 导读区（导读·→其后第一条 ---）"
    这两个**结构单元**免检，其余须带编号。
    """
    i = s.find("\n### §1")
    if i < 0:
        raise RuntimeError("找不到 §1 标题")
    return s[:i] + "\n**注入测试：文首地带的无编号加粗段落。**\n" + s[i:]


def inj_bold_guide_broken(s):
    """(11) **删掉导读区自己的结束分隔线**（2026-10-20 复核发现的假过）。

    病征：守卫按"导读起点后第一条 `---`"取边界。删掉导读区真正的结束线后，
    它会把**目录区的分隔线**当成边界，于是整片目录区被**静默豁免**——
    在目录里插无编号加粗**不报**（复核实测）。
    现加两道约束：跨度上限（>40 行）与"区间内出现'目录'字样"，任一命中即报错
    且**不豁免**该区间。

    判据：须报"导读区跨度异常"（或"区间内出现目录"），**且**注入行也须报——
    只报边界异常、不报注入，说明仍然放行了。
    """
    lines = s.split("\n")
    g = next((i for i, x in enumerate(lines) if "导读 ·" in x), None)
    if g is None:
        raise RuntimeError("找不到导读区起点")
    for j in range(g, len(lines)):
        if lines[j].strip() == "---":
            del lines[j]
            break
    else:
        raise RuntimeError("导读区起点后找不到分隔线")
    # 在目录块内插入（第 26 行附近），前后留空行以免被判为续行
    head = "\n".join(lines[:25])
    tail = "\n".join(lines[25:])
    return head + "\n\n**注入测试：目录区内的无编号加粗段落。**\n\n" + tail


def inj_meta(s):
    """(12) 编号元规则退回导读区：把"表格例外"的特征短句从正文里抹掉。

    这是**最贴近历史事故**的注入——原状就是这四条只活在导读区裸段里。
    只需让正文中的特征短句消失，即应被 (12) 抓到。
    """
    return _sub1(s, "表内行不编号", "表内行任意（注入抹去特征短句）")


def inj_dotdot(s):
    """(5) 编号形态：注入含空段 `..` 的编号（2026-10-16 实证的真实缺陷形态）。

    注：注入点选在**引用**处（`（如 `16.4.7.3`）`），而非定义处——这样
    **不影响"路径编号连续性"**那条判定，从而单独证明**新的形态断言**有效
    （否则会被连续性那条掩盖：两条同时报错，分不清是谁拦住的）。
    """
    return _sub1(s, "`§16.4.7.3`", "`§16.4..7.3`")


def inj_closure(s):
    """(13) 落实总表：**整行删掉**第 7 条那一行（模拟"新增条款忘了登记落点"）。

    注：必须整行删，不能只改首列——改成非数字会让解析把该行当成"表结束"，
    后面 8—24 条会一并判为漏登记，**测的就不是"漏一行"了**。
    """
    # 锚点随正文用词走：2026-10-30 正文把 `DEVLOG` 改为「开发日志」，
    # 锚点没跟上就会"注入点未命中"——报错文案改了，按文案匹配的用例须同步（16.2 连带判据）。
    return _sub1(s, "| §7 | 前置提问 | 流程 | 无检测；留痕见开发日志 |\n", "")


def inj_closure_empty(s):
    """(13) 落实总表：**把表体删空、只留表头**。

    这是 2026-10-17 复核发现的漏洞：初版只查"有没有 24.3 标题"，
    表被删干净但标题还在时**照样通过**。现要求"表体不得为空"。
    """
    import re as _re
    return _re.sub(r"(\| 节 \| 名称 \| 落点 \| 兜在何处 \|\n\|[-| ]+\|\n)(?:\| §\d+ \|.*\n)+",
                   r"\1", s, count=1)


def inj_closure_hdr(s):
    """(13) 落实总表：**表头被删**（只剩数据行）。

    同一轮复核发现的另一漏洞：不校验表头，列序一改就查错列且不报错。
    现要求表头存在且含 条／名称／落点／兜在何处 四列。
    """
    return _sub1(s, "| 节 | 名称 | 落点 | 兜在何处 |\n", "")


def inj_closure_colswap_hdr(s):
    """(13) 落实总表：**表头两列互换**（条 <-> 名称），数据行不动。

    2026-10-20 实测补：24.3.4 声称能拦"列序改动"，此前**无用例证明**。
    实测两种改法——表头换序、数据换序——**均被拦住**，故各补一条用例固住，
    防日后改解析逻辑时退化（12.5.4.3：判据须有区分度，须正反验）。
    """
    return _sub1(s, "| 节 | 名称 | 落点 | 兜在何处 |",
                 "| 名称 | 节 | 落点 | 兜在何处 |")


def inj_closure_colswap_row(s):
    """(13) 落实总表：**数据行两列互换**（第 1 条行：条号 <-> 名称），表头不动。

    这类改动**表头完好**，只有解析"按列取值"的写法才拦得住；若守卫改成
    "整行文本匹配"就会漏，故单独成例。须报"漏登记第 1 条"。
    """
    return _sub1(s, "| §1 | 适用与效力 | 流程 | 本文件自身即约束，无检测对象 |",
                 "| 适用与效力 | §1 | 流程 | 本文件自身即约束，无检测对象 |")


def inj_promise_gone(s):
    """(15) 第 25 条被整条删掉 —— 承诺约束消失须报错。

    实证背景：25.2 的事故就是"承诺没有守卫盯着"，若连条文本身都能被无声删掉，
    这条约束等于不存在。注入方式：把条标题改成非条标题形态。
    """
    old = "### §25 对外承诺的守门：例外须显式，承诺须有门禁"
    return _sub1(s, old, "### 25 对外承诺的守门（标题被改坏）")


def inj_promise_vague(s):
    """(15) 在一句**真承诺**里塞进含糊词「基本上」—— 正是 25.2 事故的原话。

    改的是 25.4.2 的实证写法那句（"处理文档的 20 个脚本零联网"），
    它落在含"承诺"字样的段落里，属本维扫描范围；改成"基本上零联网"若不被拦，
    就等于 25.3「模糊承诺」这一禁形同虚设。
    """
    old = "\u5904\u7406\u6587\u6863\u7684 20 \u4e2a\u811a\u672c\u96f6\u8054\u7f51"
    return _sub1(s, old, old.replace("\u96f6\u8054\u7f51", "\u57fa\u672c\u4e0a\u96f6\u8054\u7f51"))


def inj_promise_vague2(s):
    """(15) 换一处（25.4.1 的"能消掉就消掉"句）注入含糊词，验证不认固定句子。

    任一含"承诺"的段落里出现含糊词都应被拦；只认某一句的守卫是没有区分度的。
    """
    old = "\u4f7f\u4e8b\u5b9e\u91cd\u65b0\u914d\u5f97\u4e0a\u539f\u6765\u7684\u627f\u8bfa"
    return _sub1(s, old, "\u4f7f\u4e8b\u5b9e\u57fa\u672c\u4e0a\u914d\u5f97\u4e0a\u539f\u6765\u7684\u627f\u8bfa")



CASES = [
    (1, "节号连续性（缺一节）", inj_struct_gap, "节号"),
    (1, "节标题格式（缺空格）", inj_struct_fmt, "标题格式"),
    (2, "导读表与正文不一致", inj_guide, "导读"),
    (3, "悬空引用（§99）", inj_refs, "悬空"),
    (3, "悬空款号（§19.6 数字路径式）", inj_refs_dotted, "悬空编号引用"),
    (4, "废止词残留（维护侧）", inj_wording, "废止词"),
    (4, "「非运行实例侧」按反义废词拦（A.3.7 乙）", inj_wording_neg, "废止词"),
    (5, "相对引用（见下）", inj_reldir, "相对引用"),
    (5, "日期未补零", inj_date, "补零"),
    (5, "圆圈编号", inj_circle, "键入"),
    (5, "旧编号形态 (1)", inj_oldnum, "编号形态"),
    (5, "编号含空段 `..`", inj_dotdot, "编号形态异常"),
    (5, "表格首列编号断档（原看不见表格）", inj_table_num, "路径编号不连续"),
    (5, "表格指路格变成第二次定义（须报重号）", inj_table_num_ref, "路径编号不连续"),
    (6, "路径引用不存在", inj_paths, "路径引用不存在"),
    (6, "大写扩展名 .Skill 回流", inj_skill_ext, "大写扩展名"),
    (7, "铁律版本串漂移", inj_version, "铁律版本"),
    (9, "目录锚点不一致", inj_toc, "目录"),
    (10, "表格行引用缺父级", inj_ref_anchor, "父级"),
    (10, "表格内裸写行引用（原整行跳过）", inj_ref_anchor_table, "父级"),
    (11, "加粗行首无编号", inj_bold, "编号"),
    (11, "字母编号（C.）被拆掉编号", inj_bold_letter, "无编号"),
    (11, "文首地带加粗无编号（原按行号放行）", inj_bold_headgap, "无编号"),
    (11, "导读结束线被删（假过：目录区被豁免）", inj_bold_guide_broken, "目录区内的无编号加粗"),
    (12, "编号元规则掉出正文", inj_meta, "未在正文成文"),
    (13, "落实总表漏登记一条", inj_closure, "漏登记"),
    (13, "落实总表表体删空", inj_closure_empty, "表体为空"),
    (13, "落实总表表头被删", inj_closure_hdr, "未找到表头"),
    (13, "落实总表表头列序互换", inj_closure_colswap_hdr, "未找到表头"),
    (13, "落实总表数据行列序互换", inj_closure_colswap_row, "漏登记"),
    (15, "§25 被删（承诺约束消失）", inj_promise_gone, "未找到 §25"),
    (15, "承诺句出现含糊词（事故原话）", inj_promise_vague, "含糊词"),
    (15, "另一处承诺句被改成基本上零联网", inj_promise_vague2, "含糊词"),
    (17, "正文写回本机路径（实现名回流）", inj_impl_name, "实现名"),
]

# 第 (8) 维比对的是「开发侧技能目录 ↔ 运行实例」，改铁律副本碰不到，
# 单列一档：临时改运行实例一个文件 → 须报错 → 立即还原并校验哈希。
# 探针文件：**必须是两种形态下都存在的应镜像文件**。
# 原先用 `VERSION.md`——但 `publish.py` 出包后把实例转**分发形态**时**删掉** VERSION.md，
# 于是探针整段跳过（还写成"未装机"），而元自测立刻发现「(8) 打瘸后冒烟仍通过」：
# **守卫在、验不了**。2026-10-29 由元自测暴露（此前一直以为第 8 维有注入保护）。
# 改用 `SKILL.md`：两侧都有、内容确在比对范围内，注入尾巴不影响其语义。
CROSS_SIDE_PROBE = "SKILL.md"

# 自检脚本应输出的**最少**维度数。**用于防"自检没跑起来"被当成"全过"**——
# 见 main() 里 A 段的那道防线。
#
# **不写死数字**（2026-10-17 改）：上一版是手写常量 12／13，与自检脚本的真实维度数
# **各有来源、靠注释维持一致**——正是铁律第 12 条说的"同一事实两处写，必漂"。
# 改为**从用例表派生**：用例覆盖到第 N 维，自检就必须至少报出 N 维；
# 再配合下方的"覆盖性自检"（每维都要有用例、没用例即报错），两个方向夹住，
# 增删维度时**不必再手改这里**。
#
# 单列档的维度（改磁盘文件才能注入，无法用 CASES 的字符串机制表达）**也算"有注入用例"**，
# 故一并纳入派生——2026-10-30 加第 (18) 维时暴露：只在 CASES 里取 max 的话，
# 若最大维恰好是单列档，EXPECTED_DIMS 会少一维，`absent` 检查就漏掉它（守卫缺了不报）。
STANDALONE_DIMS = {8, 14, 16, 18}
EXPECTED_DIMS = max([d for d, _, _, _ in CASES] + sorted(STANDALONE_DIMS)) if CASES else 0


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
    # **第 (8) 维（跨侧一致性）不参与基线门槛**——它比的是"开发侧 ↔ 运行实例"，
    # 反映的是**发布链走到哪一步**，不是"守卫自身能不能拦"。开发侧改了、尚未重出包时
    # 它**必然**报错（这是正常中间态），拿它当基线门槛会让冒烟在这一步**根本跑不起来**。
    # 故基线只要求"除第 8 维外全过"；第 8 维**照样要验**，验法是它自己那一档注入
    # （CROSS_SIDE_PROBE：临时改运行实例一个文件 → 须报错 → 还原）。
    print("\n[A] 基线：正式文件须全过（第 8 维除外——它反映发布进度，见下）")
    rc, out = run_check()
    dims = parse_dims(out)
    # **防线：自检脚本得先"真的跑起来"**。曾踩过——被 --check 指定的脚本因路径不对
    # 启动失败，输出里一个维度标题都没有，`dims` 为空 → "零个维度自然零个错误" →
    # **假通过**。故要求：至少解析出 EXPECTED_DIMS 个维度，否则判失效。
    # **缺维有两种成因，判据必须分开**（2026-10-22 实测踩坑）：
    #   ① 脚本根本没跑起来（路径／语法／依赖问题）——输出里一个维度标题都没有；
    #   ② 被 `--check` 指定的**打瘸体**（元自测把某维函数改成 `return`）——
    #      该维头都没打，于是"少一维"，但其余维照常跑、照常输出。
    # 原先一律判"未正常运行"，结果元自测打瘸第 (8) 或第 (15) 维时冒烟直接中止，
    # 被打瘸的那一维根本走不到注入环节 → 元自测报"守卫失效"，其实是**误判**（12.5.4.3）。
    # 故改为：一个维度都没解析出 ＝ 没跑起来（硬失败）；少几维但 ≥ 半数 ＝ 打瘸体，放行。
    if not dims or len(dims) < EXPECTED_DIMS // 2:
        print("  [E] 自检只解析出 %d 个维度（应 ≥ %d）——**自检脚本未正常运行**，"
              "基线无从判定" % (len(dims), EXPECTED_DIMS // 2))
        print(out)
        return 1
    if len(dims) < EXPECTED_DIMS:
        print("  [i] 只解析出 %d 维（应有 %d）——判为**打瘸体**（元自测把某维函数改成 "
              "`return`），其缺的那一维将由注入环节判" % (len(dims), EXPECTED_DIMS))
    base_errs = {d: e for d, e in dims.items() if e and d != 8}
    if base_errs:
        print("  [E] 基线未过（除第 8 维外仍有错）——先修正式文件，再谈冒烟")
        print(out)
        return 1
    if dims.get(8):
        print("  [i] 第 8 维报错 %d 项（开发侧与运行实例不一致）——**不阻断**："
              "属发布链中间态，出包后自会一致" % len(dims[8]))
    base_dim8 = list(dims.get(8, []))          # 基线态第 8 维报错（供跨侧探针比对"是否新增"）
    covered = sorted(dims)
    print("  [OK] 基线通过；自检共 %d 维：%s" % (len(covered), covered))

    # 覆盖性自检：脚本声称的每一维，用例表里都得有对应注入
    # 第 8 维（跨侧）、第 14 维（在线版）、第 16 维（结转清单）、第 18 维（台账新鲜度）
    # 都要**改磁盘文件**才能注入，无法用 CASES 的"只改字符串"机制表达，各自单列一档，
    # 故在上方模块级 STANDALONE_DIMS 里登记为已覆盖。
    cased = sorted({c[0] for c in CASES} | STANDALONE_DIMS)
    absent = sorted(set(range(1, EXPECTED_DIMS + 1)) - set(covered))
    if absent:
        print("  [i] 打瘸体缺维：%s（该维未执行，其注入用例跳过——元自测据此判「守卫失效」）"
              % absent)
    missing = [d for d in covered if d not in cased]
    if missing:
        print("  [E] 以下维度**无注入用例**（守卫未被验证）：%s" % missing)
        return 1
    print("  [OK] 每一维都有注入用例（第 %s 维各单列一档）"
          % "、".join(str(d) for d in sorted(STANDALONE_DIMS)))

    # ── B 注入 ──
    print("\n[B] 注入：逐维断言「必须拦住」")
    tmp = tempfile.mkdtemp(prefix="rules-smoke-")
    fails = []
    # 单独档的用例数**从执行处累加**，不在结论行里手写常量——
    # 2026-10-19 改：原结论行写死 `len(CASES) + 3`，而"3"是第 (8)×1 + 第 (14)×2 的
    # 手算结果；第 (14) 维加到 3 个病征后这个数字就**立刻变成了谎报**。
    # 同一事实两处写必漂（铁律第 12 条）——改为单处来源。
    standalone_n = [0]
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
        # **判据是"新增"，不是"报错"**：基线态若已因发布进度不一致而报错（正常中间态），
        # 拿"报错与否"当判据就**没有区分度**——注不注入都报错，等于没验。
        # 故只认"注入后才出现、基线态没有"的那条含 CROSS_SIDE_PROBE 的告警。
        print("  [--] (8) 跨侧一致性（开发侧 ↔ 运行实例）单独一档")
        rp = os.path.join(RUN, CROSS_SIDE_PROBE)
        if not os.path.exists(rp):
            # 两种成因要说清，别混：① 真没装机；② 装了但已转**分发形态**
            # （`publish.py` 出包后删掉 VERSION.md 与 history，这是发布后的正常态）。
            # 原先一律写"未装机"，把正常态说成异常，读日志的人会去查根本不存在的故障。
            print("      跳过：实例缺探针文件 %s——%s"
                  % (CROSS_SIDE_PROBE,
                     "已转分发形态但探针不在（探针选错了文件）" if os.path.isdir(RUN)
                     else "未装机"))
        else:
            bak = open(rp, "rb").read()
            try:
                with open(rp, "wb") as f:
                    f.write(bak + b"\n<!-- smoke-injected -->\n")
                rc8, out8 = run_check()
                d8 = parse_dims(out8)
                # 报错文本只写"两侧不一致：<文件>"，不含内容差异——故**不能靠文本区分**。
                # 判据：注入后第 8 维**报错里含探针文件名**，且**条数不少于基线态**。
                # （基线态若已含它——发布中间态——条数持平；若不含，则 +1。两种都算拦住。）
                hit8 = d8.get(8, [])
                n8, n8b = len(hit8), len(base_dim8)
                prop_hit = any(CROSS_SIDE_PROBE in h for h in hit8)
                if rc8 != 0 and prop_hit and n8 >= n8b:
                    standalone_n[0] += 1
                    print("  [OK] (8) %-22s 拦住（第 8 维报错 %d→%d 项，含探针文件）"
                          % ("跨侧漂移", n8b, n8))
                else:
                    why = ("未报该文件（守卫失效）" if not prop_hit
                           else "报错项反比基线少（守卫失效）")
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

        # ── 第 (14) 维：在线版须与源同步 ──
        # 与第 (8) 维同法：**造真"陈旧"→ 断言拦住 → 立即还原**。
        # 病征：源改了、忘了重跑转换，在线版停在旧内容（上传出去的就是旧的）。
        # 另含第二个病征：转换没做干净（在线版仍留锚点链接）。
        print("  [--] (14) 在线版须与源同步　单独一档")
        ONLINE = os.path.join(DEV, "maint", "scratch", "DEV-RULES.online.md")
        if not os.path.exists(ONLINE):
            print("      跳过：在线版尚未生成（未上传过，属正常）")
        else:
            obak = open(ONLINE, "rb").read()
            try:
                # 病征一：在线版正文里插入一行（模拟"源改过、在线版没重生成"）
                with open(ONLINE, "ab") as f:
                    f.write("\n<!-- smoke-injected: 在线版已陈旧 -->\n".encode("utf-8"))
                rc14, out14 = run_check()
                d14 = parse_dims(out14)
                hit14 = [h for h in d14.get(14, []) if "不同步" in h]
                if rc14 != 0 and hit14:
                    standalone_n[0] += 1
                    print("  [OK] (14) %-22s 拦住（报「不同步」）" % "在线版陈旧")
                else:
                    fails.append((14, "在线版陈旧", "未报「不同步」（守卫失效）"))
                    print("  [E] (14) %-22s 未报「不同步」（守卫失效）" % "在线版陈旧")

                # 病征二：把目录改回锚点链接（模拟"转换没做干净"）
                stale = obak.decode("utf-8").replace(
                    "- §1 适用与效力", "- [§1 适用与效力](#1-适用与效力)", 1)
                with open(ONLINE, "w", encoding="utf-8") as f:
                    f.write(stale)
                rc14b, out14b = run_check()
                d14b = parse_dims(out14b)
                hit14b = [h for h in d14b.get(14, []) if "锚点链接" in h]
                if rc14b != 0 and hit14b:
                    standalone_n[0] += 1
                    print("  [OK] (14) %-22s 拦住（报「仍有锚点链接」）" % "转换不彻底")
                else:
                    fails.append((14, "转换不彻底", "未报「锚点链接残留」（守卫失效）"))
                    print("  [E] (14) %-22s 未报锚点残留（守卫失效）" % "转换不彻底")

                # 病征三：**说明段折成多行的旧 bug 形态**（2026-10-19 实证过的真 bug）
                # 旧转换只吃掉说明段第一行，剩下的半句「由 `…make-online-md.py` 派生…」
                # 孤零零留在目录里。本项验"守卫认不认这个形态"。
                # 注意：这个病征的两面**必须都验**——
                #   · 守卫要报它（否则下次再出同样产物没人拦）；
                #   · 归一化比对**不得**把「说明段行数不同」误算成正文漂移
                #     （2026-10-19 曾因此报出"约 963 行有差异"的伪问题）。
                ONELINE = "目录（在线版无锚点跳转，按节号定位；本地 Markdown 版保留可点击目录）"
                broken = obak.decode("utf-8")
                if ONELINE not in broken:
                    print("      跳过病征三：在线版说明行已非预期形态（%s）" % ONELINE[:12])
                else:
                    broken = broken.replace(
                        ONELINE, "目录（在线版无锚点跳转，按节号定位；\n由 `maint/tools/make-online-md.py` 派生，见 §23 在线分发）", 1)
                    with open(ONLINE, "w", encoding="utf-8") as f:
                        f.write(broken)
                    rc14c, out14c = run_check()
                    d14c = parse_dims(out14c)
                    hit14c = [h for h in d14c.get(14, []) if "说明段仍为多行" in h]
                    # 且**不得**同时报「不同步」——那说明归一化把版式差异当成内容漂移
                    noise = [h for h in d14c.get(14, []) if "不同步" in h]
                    if rc14c != 0 and hit14c and not noise:
                        standalone_n[0] += 1
                        print("  [OK] (14) %-22s 拦住（报「说明段仍为多行」，且不误报不同步）"
                              % "说明段折行")
                    else:
                        why = ("未报「说明段仍为多行」（守卫失效）" if not hit14c
                               else "同时误报「不同步」（归一化区分度不足）")
                        fails.append((14, "说明段折行", why))
                        print("  [E] (14) %-22s %s" % ("说明段折行", why))
            finally:
                with open(ONLINE, "wb") as f:
                    f.write(obak)
            if digest(ONLINE) != hashlib.sha256(obak).hexdigest():
                fails.append((14, "在线版", "还原失败：在线版哈希未复原"))
                print("  [E] (14) 还原失败——**在线版被污染**，请立即检查 %s" % ONLINE)
            else:
                print("  [OK] (14) 在线版已逐字节还原")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── 第 (16) 档：结转遗留清单（OPEN-ISSUES.md）──
    # 本维读的是**独立文件**，改铁律副本碰不到它 → 与其他单列档同法：
    # **造真坏形态 → 断言拦住 → 立即还原**。
    # 两个病征都取自 18.2 明写、却一直没东西盯着的两件事：
    #   ① 「态」写成三态之外的值（如"进行中"）——写明"不算登记"，可没人拦；
    #   ② 标了「转下轮」却把「再见条件」清成「无」——没有再见条件就永远闭不了。
    # 注意：**不测"内容是否属实"**，那个机器判不了（见第 (16) 维 docstring 的边界）。
    print("  [--] (16) 结转遗留清单格式与态　单独一档")
    OI = os.path.join(DEV, "maint", "OPEN-ISSUES.md")
    if not os.path.exists(OI):
        fails.append((16, "结转清单", "文件不存在"))
        print("  [E] (16) 结转清单不存在（%s）" % OI)
    else:
        obak16 = open(OI, "rb").read()
        try:
            txt16 = obak16.decode("utf-8")

            # 病征一：「态」换成三态之外的值
            if "| 转下轮 |" not in txt16:
                fails.append((16, "态非法", "注入点未命中（找不到「| 转下轮 |」）"))
                print("  [E] (16) %-22s 注入点未命中" % "态非法")
            else:
                with open(OI, "w", encoding="utf-8") as f:
                    f.write(txt16.replace("| 转下轮 |", "| 进行中 |", 1))
                rc16, out16 = run_check()
                hit16 = [h for h in parse_dims(out16).get(16, []) if "只许取" in h]
                if rc16 != 0 and hit16:
                    standalone_n[0] += 1
                    print("  [OK] (16) %-22s 拦住（报「只许取」）" % "态非法")
                else:
                    fails.append((16, "态非法", "未报「只许取」（守卫失效）"))
                    print("  [E] (16) %-22s 未拦住（守卫失效）" % "态非法")

            # 病征二：转下轮行把「再见条件」清成「无」
            bad2 = re.sub(r"\|[^|]*最迟下次出包前[^|]*\|", "| 无 |", txt16, count=1)
            if bad2 == txt16:
                fails.append((16, "缺再见条件", "注入点未命中（H-01 行已改形）"))
                print("  [E] (16) %-22s 注入点未命中" % "缺再见条件")
            else:
                with open(OI, "w", encoding="utf-8") as f:
                    f.write(bad2)
                rc16b, out16b = run_check()
                hit16b = [h for h in parse_dims(out16b).get(16, []) if "再见条件" in h]
                if rc16b != 0 and hit16b:
                    standalone_n[0] += 1
                    print("  [OK] (16) %-22s 拦住（报「没有再见条件」）" % "缺再见条件")
                else:
                    fails.append((16, "缺再见条件", "未报「再见条件」（守卫失效）"))
                    print("  [E] (16) %-22s 未拦住（守卫失效）" % "缺再见条件")
        finally:
            with open(OI, "wb") as f:
                f.write(obak16)
        if digest(OI) != hashlib.sha256(obak16).hexdigest():
            fails.append((16, "结转清单", "还原失败：哈希未复原"))
            print("  [E] (16) 还原失败——**结转清单被污染**，请立即检查 %s" % OI)
        else:
            print("  [OK] (16) 结转清单已逐字节还原")

    # ── 第 (18) 档：产出物台账新鲜度（2026-10-30 新增）──
    # 本维读的是**工作区根的《产出物台账》**，改铁律副本碰不到它 → 与其他单列档同法：
    # **造真坏形态 → 断言拦住 → 立即还原**。
    # 三个病征全部取自**真实发生过的过期形态**：两次全检都抓到台账停在旧读数
    # （v3.26.8 停在 v3.12.1；v3.26.12 写 98 个包／49 个版本，实际 6 个／3 版）。
    # 读数不在此写死：从台账现文里现抠，改一处即可——写死就会在下次删包后失效。
    print("  [--] (18) 产出物台账须与 dist 实际一致　单独一档")
    LEDGER = os.path.join(os.path.dirname(DEV), "产出物台账.md")
    if not os.path.exists(LEDGER):
        fails.append((18, "台账新鲜度", "台账不存在"))
        print("  [E] (18) 台账不存在（%s）——生成器可重建" % LEDGER)
    else:
        lbak = open(LEDGER, "rb").read()
        try:
            ltxt = lbak.decode("utf-8")
            m18 = re.search(r"分发包总数：\*\*(\d+)\*\*\s*个（覆盖\s*\*\*(\d+)\*\*\s*个版本："
                            r"\s*(v\d+\.\d+\.\d+)\s*—\s*(v\d+\.\d+\.\d+)）", ltxt)
            if not m18:
                fails.append((18, "台账新鲜度", "注入点未命中（找不到读数行）"))
                print("  [E] (18) %-22s 注入点未命中（生成器输出格式已变）" % "读数行")
            else:
                n18, mv18 = int(m18.group(1)), int(m18.group(2))
                lo18, hi18 = m18.group(3), m18.group(4)
                rng18 = "%s — %s" % (lo18, hi18)
                cases18 = [
                    ("包数对不上",
                     "分发包总数：**%d** 个" % n18,
                     "分发包总数：**%d** 个" % (n18 + 1), "包数"),
                    ("版本数对不上",
                     "覆盖 **%d** 个版本" % mv18,
                     "覆盖 **%d** 个版本" % (mv18 + 1), "版本数"),
                    # 区间改成一个绝不存在的版本：只错误区间、不动读数，验的是第三项判据
                    ("版本区间对不上",
                     rng18, "v0.0.1 — %s" % hi18, "版本区间"),
                ]
                for cname, cold, cnew, kw18 in cases18:
                    if cold not in ltxt:
                        fails.append((18, cname, "注入点未命中"))
                        print("  [E] (18) %-22s 注入点未命中" % cname)
                        continue
                    with open(LEDGER, "w", encoding="utf-8") as f:
                        f.write(ltxt.replace(cold, cnew, 1))
                    rc18, out18 = run_check()
                    hit18 = [h for h in parse_dims(out18).get(18, []) if kw18 in h]
                    if rc18 != 0 and hit18:
                        standalone_n[0] += 1
                        print("  [OK] (18) %-22s 拦住（报「%s」）" % (cname, kw18))
                    else:
                        fails.append((18, cname, "未报「%s」（守卫失效）" % kw18))
                        print("  [E] (18) %-22s 未拦住（守卫失效）" % cname)
                    # 每个病征后立即复原，下一个病征基于干净文本注入
                    with open(LEDGER, "w", encoding="utf-8") as f:
                        f.write(ltxt)
        finally:
            with open(LEDGER, "wb") as f:
                f.write(lbak)
        if digest(LEDGER) != hashlib.sha256(lbak).hexdigest():
            fails.append((18, "台账新鲜度", "还原失败：台账哈希未复原"))
            print("  [E] (18) 还原失败——**台账被污染**，请立即检查 %s" % LEDGER)
        else:
            print("  [OK] (18) 台账已逐字节还原")

    # ── 第 (3b) 档：外部文件里的铁律条号引用（2026-10-20 新增）──
    # 12.5.1.1 承认的盲区：条号被脚本注释、随包文档写死引用，真源改号后全部悬空，
    # 而 (3) 维只扫 DEV-RULES.md 自身。这道守卫要读别处的文件，故单列一档：
    # **造一个不存在的号 → 断言拦住 → 立即还原**。
    print("  [--] (3b) 外部文件里的铁律条号　单独一档")
    SEP3B = os.path.join(DEV, "maint", "tools", "check-separation.py")
    if not os.path.exists(SEP3B):
        print("      跳过：check-separation.py 不存在")
    else:
        bak3b = open(SEP3B, "rb").read()
        try:
            btxt = bak3b.decode("utf-8")
            # 把一个真实存在的款号改成绝不存在的号（号在下面拼，不在此写字面量）。
            # **号要拼出来，不得在源码里写字面量**——(3b) 守卫会扫本文件，
            # 写死的假号会让冒烟自己变成违规样本（实测踩过：自指报错，守卫在骂自己）。
            REAL = "铁律 §" + "9.4"
            FAKE = "铁律 §" + "77" + ".4"
            if REAL not in btxt:
                fails.append((3, "外部条号悬空", "注入点未命中（check-separation.py 已改形）"))
                print("  [E] (3b) 外部条号悬空            注入点未命中")
            else:
                with open(SEP3B, "w", encoding="utf-8") as f:
                    f.write(btxt.replace(REAL, FAKE, 1))
                rc3b, out3b = run_check()
                hit3b = "悬空" in out3b and "77.4" in out3b
                if rc3b != 0 and hit3b:
                    standalone_n[0] += 1
                    print("  [OK] (3b) %-22s 拦住（报「外部文件里的铁律条号已悬空」）"
                          % "外部条号悬空")
                else:
                    why = "未报外部条号悬空（守卫失效）"
                    fails.append((3, "外部条号悬空", why))
                    print("  [E] (3b) %-22s %s" % ("外部条号悬空", why))
        finally:
            with open(SEP3B, "wb") as f:
                f.write(bak3b)
        if digest(SEP3B) != hashlib.sha256(bak3b).hexdigest():
            fails.append((3, "外部条号悬空", "还原失败：check-separation.py 哈希未复原"))
            print("  [E] (3b) 还原失败——**源文件被污染**，请立即检查 %s" % SEP3B)
        else:
            print("  [OK] (3b) check-separation.py 已逐字节还原")

    # ── 第 (12) 档：分离守卫（铁律 §9）──
    # 分离守卫查的是"技能目录里有没有不该在那的东西"，与铁律正文的十六维不同源，
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
                    standalone_n[0] += 1
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

        # 常驻反证（2026-11-11）：钉死「read_pack_consts 不维护手写常量名单」这一
        # 一劳永逸机制，防回潮。全部在临时副本上做（铁律 16.2），不碰正式 pack.py。
        #   ① pack.py 新增一个常量并放进 FULL_DIRS → 守卫须自动解析（无需同步名单）
        #   ② FULL_DIRS 引用一个未定义的名字 → 守卫须明确报错并点名（不得静默降级）
        # 用例本身按行首定位 FULL_DIRS、在 ] 前插名字，不硬编码该行内容，
        # 否则用例自己又变成一处漂移源。
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("_sep_probe", SEP)
            _sep = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_sep)
            _pack_real = os.path.join(DEV, "doc-compliance-review", "scripts", "pack.py")
            _pack_src = open(_pack_real, encoding="utf-8").read()
            _plines = _pack_src.splitlines(True)
            _fd = next((i for i, l in enumerate(_plines)
                        if l.lstrip().startswith("FULL_DIRS")), None)
            _ptmp = tempfile.mkdtemp(prefix="rules-smoke-packconst-")
            try:
                if _fd is None:
                    raise RuntimeError("pack.py 里找不到 FULL_DIRS 赋值行")

                def _inject(extra, define):
                    ls = list(_plines)
                    line = ls[_fd]
                    k = line.rfind("]")
                    if k < 0:
                        raise RuntimeError("FULL_DIRS 行没有 ]")
                    ls[_fd] = line[:k] + ", " + extra + line[k:]
                    if define:
                        ls.insert(_fd, '%s = "%s"\n' % (extra, extra.lower()))
                    return "".join(ls)

                # ① 未来常量：加定义并塞进 FULL_DIRS，守卫须自动解析出来
                _p1 = os.path.join(_ptmp, "pack_future.py")
                open(_p1, "w", encoding="utf-8").write(_inject("FUTURE_DIR", True))
                _sep.ERRS.clear(); _sep.WARNS.clear()
                _g1 = _sep.read_pack_consts(_p1)
                _ok1 = "future_dir" in (_g1.get("FULL_DIRS") or []) and not _sep.ERRS

                # ② 未定义引用：FULL_DIRS 里放一个没有定义的名字，守卫须报错点名
                _p2 = os.path.join(_ptmp, "pack_ghost.py")
                open(_p2, "w", encoding="utf-8").write(_inject("GHOST_DIR", False))
                _sep.ERRS.clear(); _sep.WARNS.clear()
                _sep.read_pack_consts(_p2)
                _j2 = " ".join(_sep.ERRS)
                _ok2 = ("FULL_DIRS" in _j2 and "GHOST_DIR" in _j2
                        and "INTEGRITY_REL" not in _j2 and "STEM_RE" not in _j2)

                for _nm, _ok, _why in (
                    ("新增常量自动解析（无需同步名单）", _ok1,
                     "FULL_DIRS 未含新常量或守卫报错"),
                    ("未定义引用必须报错并点名", _ok2,
                     "守卫未报错/未点名/混入噪声（静默降级复活）"),
                ):
                    if _ok:
                        standalone_n[0] += 1
                        print("  [OK] (12) %s" % _nm)
                    else:
                        fails.append((12, _nm, _why))
                        print("  [E] (12) %s —— %s" % (_nm, _why))
            finally:
                shutil.rmtree(_ptmp, ignore_errors=True)
        except Exception as e:
            fails.append((12, "read_pack_consts 反证", "加载/执行异常：%s" % e))
            print("  [E] (12) read_pack_consts 反证异常：%s" % e)

    # ── C 还原校验 ──
    print("\n[C] 还原：正式文件不得被污染（铁律 16.2）")
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
    print("冒烟通过：%d 个注入用例全部被拦住，正式文件零污染"
          % (len(CASES) + standalone_n[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
