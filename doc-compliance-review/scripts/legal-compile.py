#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""法规汇编撰写 —— legal-articles.json 的第三个消费者

三个消费者的分工
    legal-verify ：**你已经在报告里引了某条**，我核原文对不对、是不是现行版（裁判）
    legal-search ：**你还没引、只想查**，我按问题或条号把条文找出来（找 + 呈现）
    legal-compile：**你要一册东西**，我把选定的条文按体例编成一份可交付的汇编（编 + 成册）

用途：把检索命中的、或显式指定的条文，按〔法名 → 条号〕的体例编成一份汇编文档，
      带封面要素、目录、每部法的版本与施行日、每条原文、多源校验状态、覆盖面声明。

体例（固定，不可由模型改写）
    一、编制说明（范围、来源、时效口径、免责）
    二、目录（法名 → 条数 → 页码范围由渲染器给）
    三、正文：按法名分组，组头列该法版本／施行日／修订注记；组内按条号升序；
        每条＝〔条号〕＋条旨（anchor）＋原文 ＋ 校验标记
    四、索引：条号 → 主题词（取自条文原文的词面，不生成）
    五、附录：本库覆盖面 ＋ 未收录提示

设计红线（改代码前先读，越界即违规）
  · **只搬运，不撰写**。条文原文逐字照录（有 sha256 校验）；条旨取库内 anchor 字段；
    目录、索引均由条文词面机械生成。**汇编里不出现任何一句由本脚本生成的"法律观点"**。
  · **不下结论**。不摘"要点"、不写"评析"、不标"重点"、不做适用判断。
  · **库外不猜**。请求的条号库内没有 → 在附录"未收录"里逐条列名，不补、不近似替换。
  · **时效必须报**。每部法必带 version／effective；status 非 multi-ok 的逐条标出。
  · **覆盖面必须报**。清册须说明"本汇编仅含所选条文，非该法全文，亦非法律全集"。

用法：
  python scripts/legal-compile.py --ask "竞业限制" --title "竞业限制法规汇编"
  python scripts/legal-compile.py --ask "违约金" --law 民法典 --out 汇编.md
  python scripts/legal-compile.py --articles 民法典:585,577 劳动合同法:23,24
  python scripts/legal-compile.py --ask "个人信息" --format docx --out 个人信息保护法规汇编.docx
  python scripts/legal-compile.py --ask "竞业限制" --no-requirements   # 只录原文，不附要件

退出码：0 已生成；1 所选条文全部未收录（不产出空册）；2 参数错误。
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__

# 输出编码自钉：本脚本可能被 check.py 等**作为子进程 spawn**，父侧按 UTF-8 解码 stdout。
# 不钉的话，中文 Windows（GBK 控制台）下会按 GBK 写出 → 父侧 UTF-8 解出 U+FFFD 乱码 →
# 判据一条都匹配不上，父侧误报「判据被删／脚本崩了」（v3.26.2 在千问办公实测到的假红）。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


import argparse
import datetime as _dt
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "core", "legal-articles.json")

_sys.path.insert(0, HERE)
import importlib.util as _ilu

# 复用 legal-search 的检索与要件抽取（不另造算法）；legal-search 内部又复用 legal-verify
_spec = _ilu.spec_from_file_location("ls", os.path.join(HERE, "legal-search.py"))
ls = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(ls)
lv = ls.lv

CONF_LABEL = ls.CONF_LABEL

DISCLAIMER = ("本汇编为法律信息汇编，条文原文照录、出处可核。"
              "**不构成法律意见，不预测案件结果、不判断具体情形是否成立**；"
              "具体适用须经执业律师结合事实认定。")


def load_db(path=DB):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── 选条 ───────────────────────────

def parse_articles(spec_str):
    """解析 --articles 「法名:条号,条号 法名:条号」→ [(law, no)]，保持给定顺序。"""
    out, missing = [], []
    for chunk in re.split(r"[\s；;]+", (spec_str or "").strip()):
        if not chunk:
            continue
        if ":" not in chunk and "：" not in chunk:
            missing.append(chunk)
            continue
        law, nos = re.split(r"[:：]", chunk, 1)
        law = law.strip()
        for n in re.split(r"[,，、]+", nos):
            n = n.strip()
            if not n:
                continue
            # 「205之一」「205.1」都要能写：增设条与主条是两个罪名，写成 205 会指错条
            _m = re.match(r"^(\d+)\s*(?:\.\s*(\d+)|条?\s*之\s*([一二三四五六七八九十]{1,3}))?$", n)
            if _m:
                no = lv.parse_no(_m.group(1),
                                 _m.group(3) or _m.group(2))
            else:
                no = lv.parse_no(n)
            if no:
                out.append((law, no))
    return out, missing


def collect(db, ask=None, law=None, articles=None, limit=40):
    """按三种入口收集条文，返回 (选中列表, 未收录列表)。

    选中项为 dict：law, no, text, anchor, verified, status, sources, hit
    未收录项为 (law, no) —— 显式点名但库内没有的。
    """
    laws = db.get("laws") or {}
    picked, absent = [], []

    if articles:
        for law_name, no in articles:
            # 法名可简写（"民法典" vs "中华人民共和国民法典"），走 legal-verify 的归一化
            real = lv.pick_law(law_name) or law_name
            ent = (laws.get(real) or {}).get(lv.art_key(no))
            if not ent:
                # 再退一步：全库找同条号且法名互相包含的（避免简写/全称不一致误判未收录）
                for k, v in laws.items():
                    if (real in k or k in real) and lv.art_key(no) in v:
                        real, ent = k, v[str(no)]
                        break
            if ent:
                picked.append(ls._row(real, no, ent,
                                     1.0, "指定收录"))
            else:
                absent.append((real, no))
        return picked, absent

    if ask:
        res = ls.search_in_db(ask, db, law_filter=law, limit=limit)
        return res, absent

    return picked, absent


# ─────────────────────────── 编册 ───────────────────────────

def _ymd(s):
    """把 "2021-01-01" 写成 "2021 年 1 月 1 日"，读起来像正式文本。"""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", (s or "").strip())
    if not m:
        return s or ""
    y, mo, da = m.groups()
    return "%s 年 %d 月 %d 日" % (y, int(mo), int(da))


def group_by_law(picked):
    """按法名分组；组内条号升序。返回 [(law, [rows...])]，法名按首条出现顺序。"""
    order, bucket = [], {}
    for r in picked:
        if r["law"] not in bucket:
            bucket[r["law"]] = []
            order.append(r["law"])
        bucket[r["law"]].append(r)
    for k in bucket:
        bucket[k].sort(key=lambda x: (lv.art_base(x["no"]), lv.art_key(x["no"])))
    return [(k, bucket[k]) for k in order]


def _kw(anchor):
    """条旨词面：anchor 是库内已存的条旨片段，直接截取，不改写、不归纳。

    截断优先落在标点上（读起来是完整一截），落不到点才硬截并加省略号。
    """
    a = (anchor or "").strip()
    a = re.sub(r"[，。；：、]+$", "", a)
    if len(a) <= 48:
        return a
    head = a[:48]
    cut = max(head.rfind("，"), head.rfind("；"), head.rfind("、"))
    if cut >= 24:
        return head[:cut]
    return head[:47] + "…"


def _compact_nos(rows):
    """条号紧凑写法：连续区间写「23—25」，断开处用、分隔。

    「第X条之一」不能并进区间：区间是**主条号**的压缩写法，把 205 之一 压成
    「205」会让人以为收录的只是第 205 条本身——而那正是两个不同罪名。
    故主号走区间，增设条另用括注点名。
    """
    keys = [lv.art_key(r["no"]) for r in rows]
    if not keys:
        return "—"
    bases = sorted({lv.art_base(k) for k in keys})
    subs = sorted((k for k in keys if "." in k), key=lv.art_base)
    out, start, prev = [], bases[0], bases[0]
    for n in bases[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else "%d—%d" % (start, prev))
        start = prev = n
    out.append(str(start) if start == prev else "%d—%d" % (start, prev))
    txt = "、".join(out)
    if subs:
        txt += "（另含 %s）" % "、".join(lv.art_label(s) for s in subs)
    return txt


def build(db, picked, absent, title, ask=None, law=None,
          with_req=True, note="", today=None):
    """生成汇编 Markdown。返回 (md, stats)。"""
    laws_all = db.get("laws") or {}
    meta = db.get("meta") or {}
    total_in_db = sum(len(v) for v in laws_all.values())
    groups = group_by_law(picked)
    n_art = len(picked)
    today = today or _dt.date.today().strftime("%Y-%m-%d")

    L = []
    A = L.append

    # ── 封面要素 ──
    A("# %s" % title)
    A("")
    A("| 项目 | 内容 |")
    A("|---|---|")
    A("| 汇编范围 | %s |" % ("按主题检索：%s" % ask if ask and not law
                              else ("限定法名：%s%s" % (law, "；主题：" + ask if ask else "")
                                    if law else "逐条指定")))
    A("| 收录法数 | %d 部 |" % len(groups))
    A("| 收录条数 | %d 条 |" % n_art)
    A("| 成册日期 | %s |" % _ymd(today))
    A("| 条文来源 | 本技能随包法规库（%d 部法 %d 条，逐条多源校验） |"
      % (len(laws_all), total_in_db))
    A("")

    # ── 一、编制说明 ──
    A("## 一、编制说明")
    A("")
    A("1. **条文原文照录**：正文每条均为库内条文原文，逐字照录、未作删节改写；"
      "每条带内容指纹，可与来源页比对。")
    A("2. **条旨取自条文**：条号后的概括语取自该条首句，属条文自身表述，非编者归纳。")
    A("3. **时效以库为准**：每部法标注版本与施行日期；条文校验状态逐条标注，"
      "「单源未核」「多源冲突」的不作为定论。")
    A("4. **范围有限**：本汇编**仅含下列所选条文**，不是该法全文，更不是法律全集；"
      "本库为审查场景精选的条文子集。")
    if note:
        A("5. **编制嘱托**：%s" % note)
    A("")
    A("> %s" % DISCLAIMER)
    A("")

    # ── 二、目录 ──
    A("## 二、目录")
    A("")
    A("| 序 | 法名 | 版本 | 施行日期 | 条数 | 条号 |")
    A("|---:|---|---|---|---:|---|")
    for i, (law_name, rows) in enumerate(groups, 1):
        m = meta.get(law_name) or {}
        nos = _compact_nos(rows)
        if len(nos) > 46:
            nos = "%s…（共 %d 条）" % (nos[:44], len(rows))
        A("| %d | 《%s》 | %s | %s | %d | %s |"
          % (i, law_name, m.get("version") or "—",
             _ymd(m.get("effective")) or "—", len(rows), nos))
    A("")

    # ── 三、正文 ──
    A("## 三、条文")
    A("")
    for gi, (law_name, rows) in enumerate(groups, 1):
        m = meta.get(law_name) or {}
        A("### %d. 《%s》" % (gi, law_name))
        A("")
        head = []
        if m.get("version"):
            head.append("**版本**：%s" % m["version"])
        if m.get("effective"):
            head.append("**施行**：%s" % _ymd(m["effective"]))
        if head:
            A("　｜　".join(head))
            A("")
        if m.get("note"):
            A("> 版本提示：%s" % m["note"])
            A("")

        for r in rows:
            conf = CONF_LABEL.get(r["status"], r["status"] or "未标")
            mark = "✓ %s" % conf
            if not r.get("verified"):
                mark += "　⚠ 未通过多源验证"
            A("#### 第%s　%s" % (lv.art_label(r["no"]), _kw(r.get("anchor"))))
            A("")
            A("`%s`" % mark)
            A("")
            # 原文逐行引用，保留分段
            for para in [p for p in r["text"].split("\n") if p.strip()]:
                A("> %s" % para)
                A("")
            if with_req:
                req = ls.split_requirements(r["text"])
                if req["reqs"] or req["excepts"]:
                    A("**本条结构**（摘自原文句式，未作改写）")
                    A("")
                    for i, x in enumerate(req["reqs"], 1):
                        A("%d. %s" % (i, x))
                    for x in req["excepts"]:
                        A("- 除外／但书：%s" % x)
                    A("")
                else:
                    A("<sub>本条无「……的，应当……」类可拆解句式（多为定义性／限制性条文），"
                      "依上引原文为准，不作归纳。</sub>")
                    A("")
            if r.get("sources"):
                A("<sub>来源 %d 处：%s</sub>"
                  % (len(r["sources"]), "；".join(r["sources"])))
                A("")

    # ── 四、索引 ──
    A("## 四、条号索引")
    A("")
    A("| 法名 | 条号 | 条旨 |")
    A("|---|---:|---|")
    for law_name, rows in groups:
        for r in rows:
            A("| %s | %s | %s |" % (law_name, lv.art_label(r["no"]),
                                    _kw(r.get("anchor")) or "—"))
    A("")

    # ── 五、附录 ──
    A("## 五、附录")
    A("")
    A("### 5.1 本库覆盖面")
    A("")
    A("| 法名 | 收录条数 |")
    A("|---|---:|")
    for k, n in sorted(((k, len(v)) for k, v in laws_all.items()), key=lambda x: -x[1]):
        mark = "" if any(k == g[0] for g in groups) else "　（本法未入选）"
        A("| %s%s | %d |" % (k, mark, n))
    A("| **合计** | **%d** |" % total_in_db)
    A("")

    if absent:
        A("### 5.2 未收录（点名但库内没有）")
        A("")
        A("> 下列条号**本库未收录**。汇编不补入、不以近似条文替代、不凭记忆补写；"
          "如需收录，请先经法规库更新流程核验入库。")
        A("")
        for law_name, no in absent:
            A("- 《%s》第%s" % (law_name, lv.art_label(no)))
        A("")

    A("### 5.%d 校验口径" % (3 if absent else 2))
    A("")
    A("| 状态 | 含义 |")
    A("|---|---|")
    A("| 多源一致 | 两个以上独立来源逐字一致，内容指纹相符 |")
    A("| 单源未核 | 仅一个来源，未经第二源比对——不作为定论 |")
    A("| 多源冲突 | 来源间存在差异，须人工核对——不作为定论 |")
    A("")
    A("---")
    A("")
    A("*%s*" % DISCLAIMER)

    md = "\n".join(L)
    stats = {
        "laws": len(groups), "articles": n_art, "absent": len(absent),
        "db_laws": len(laws_all), "db_articles": total_in_db,
        "unverified": sum(1 for r in picked if not r.get("verified")),
        "conflict": sum(1 for r in picked if r.get("status") == "conflict"),
        "single": sum(1 for r in picked if r.get("status") == "single"),
    }
    return md, stats


def to_docx(md, out_path, title):
    """把汇编 Markdown 转 Word：套公文风（标题居中、正文三号仿宋）。

    只做版式，不改一个字——段落文字与 md 一致，转换失败不静默。
    """
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
    except Exception as e:
        return None, "python-docx 不可用（%s）" % e

    doc = Document()
    def _font(run, name="仿宋", size=16, bold=False):
        run.font.name = name
        run.font.size = Pt(size)
        run.bold = bold
        run._element.rPr.rFonts.set(qn("w:eastAsia"), name)

    sec = doc.sections[0]
    for p in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, p, Pt(72))   # 25.4mm 左右，先给个舒展页边距

    in_table = []

    def plain(s):
        """去掉 Markdown 标记，只留文字——Word 里不需要星号与反引号。

        标题、引用、列表、表格单元格全部走这里，否则会漏出 ** 或 <sub>。
        """
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"`(.+?)`", r"\1", s)
        s = re.sub(r"<sub>(.+?)</sub>", r"\1", s)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
        s = re.sub(r"^\s*[-*_]{3,}\s*$", "", s)
        return s.strip()

    def flush_table():
        rows = [r for r in in_table if r.strip().strip("|")]
        if not rows:
            in_table.clear()
            return
        cells = [[plain(c.strip()) for c in r.strip().strip("|").split("|")] for r in rows]
        cells = [c for c in cells if not all(re.fullmatch(r":?-{2,}:?", x or "") for x in c)]
        if not cells:
            in_table.clear()
            return
        ncol = max(len(c) for c in cells)
        t = doc.add_table(rows=len(cells), cols=ncol)
        t.style = "Table Grid"
        for i, row in enumerate(cells):
            for j in range(ncol):
                cell = t.cell(i, j)
                cell.text = ""
                run = cell.paragraphs[0].add_run(row[j] if j < len(row) else "")
                _font(run, size=10.5, bold=(i == 0))
        in_table.clear()

    for raw in md.split("\n"):
        line = raw.rstrip()
        if line.startswith("|"):
            in_table.append(line)
            continue
        if in_table:
            flush_table()
        if line.startswith(">"):
            # 引用块（条文原文）在 Word 里按正文排，去掉引用符即可，文字不动
            txt = plain(line.lstrip("> "))
            if not txt:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(32)
            _font(p.add_run(txt), size=16)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            lvl, txt = len(m.group(1)), plain(m.group(2))
            if not txt:
                continue
            p = doc.add_paragraph()
            if lvl == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _font(p.add_run(txt), "方正小标宋简体", 22, False)
            elif lvl == 2:
                _font(p.add_run(txt), "黑体", 16, False)
            else:
                _font(p.add_run(txt), "黑体", 16, False)
            continue
        if re.fullmatch(r"[-*_]{3,}", line.strip() or "-"):
            continue
        if line.startswith(("- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            _font(p.add_run(plain(line[2:])), size=16)
            continue
        m2 = re.match(r"^\d+\.\s+(.*)$", line)
        if m2:
            p = doc.add_paragraph(style="List Number")
            _font(p.add_run(plain(m2.group(1))), size=16)
            continue
        if not line.strip():
            continue
        txt = plain(line)
        if not txt:
            continue
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(32)
        _font(p.add_run(txt), size=16)

    if in_table:
        flush_table()
    doc.save(out_path)
    return out_path, ""


def main():
    ap = argparse.ArgumentParser(description="法规汇编撰写（编册，不改写条文）")
    ap.add_argument("--ask", help="按主题检索后汇编")
    ap.add_argument("--law", help="限定法名")
    ap.add_argument("--articles", help="逐条指定，如「民法典:585,577 劳动合同法:23」")
    ap.add_argument("--title", help="汇编标题（缺省按主题/法名生成）")
    ap.add_argument("--note", default="", help="编制嘱托（写进编制说明第 5 条）")
    ap.add_argument("--limit", type=int, default=40, help="主题检索最多收录条数")
    ap.add_argument("--no-requirements", action="store_true", help="只录原文，不附本条结构")
    ap.add_argument("--format", default="md", choices=["md", "docx"], help="输出格式")
    ap.add_argument("--out", help="输出路径（缺省写到当前目录）")
    ap.add_argument("--json", help="统计结果另存 JSON")
    a = ap.parse_args()

    if not (a.ask or a.articles):
        print("[legal-compile] 需要 --ask 或 --articles 指定收录范围。", file=sys.stderr)
        return 2

    db = load_db()
    arts, bad = parse_articles(a.articles) if a.articles else (None, [])
    picked, absent = collect(db, ask=a.ask, law=a.law, articles=arts, limit=a.limit)

    if not picked:
        total = sum(len(v) for v in (db.get("laws") or {}).values())
        print("[legal-compile] 未收录：所选条文不在库内（本库 %d 部法 %d 条，审查场景精选）。"
              % (len(db.get("laws") or {}), total), file=sys.stderr)
        print("                 汇编不凭记忆补条文、不以近似条替代。"
              "可先用 legal-search.py --coverage 看覆盖面，或 --online 扩充。",
              file=sys.stderr)
        for law_name, no in (absent or []):
            print("                 未收录：《%s》第%s" % (law_name, lv.art_label(no)),
                  file=sys.stderr)
        return 1

    title = a.title
    if not title:
        if a.ask and not a.law:
            title = "%s法规汇编" % a.ask
        elif a.law:
            title = "《%s》条文汇编" % a.law
        else:
            title = "条文汇编"

    md, stats = build(db, picked, absent, title, ask=a.ask, law=a.law,
                      with_req=not a.no_requirements, note=a.note)
    stats["title"] = title

    out = a.out or os.path.join(os.getcwd(), title + "." + a.format)
    if a.format == "docx":
        got, err = to_docx(md, out, title)
        if not got:
            print("[legal-compile] Word 渲染失败：%s" % err, file=sys.stderr)
            return 2
    else:
        with io.open(out, "w", encoding="utf-8") as f:
            f.write(md)

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    print("[legal-compile] 已生成：%s" % out)
    print("                %d 部法 %d 条；校验：单源未核 %d 条、多源冲突 %d 条%s"
          % (stats["laws"], stats["articles"], stats["single"], stats["conflict"],
             ("；未收录 %d 条" % stats["absent"]) if stats["absent"] else ""))
    print("                红线：条文照录未改写，不摘要点、不作评析、不下结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
