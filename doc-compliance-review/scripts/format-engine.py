#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
#   · 「HTML 在线增强版」（--html-online）只把白名单 CDN（HTML_CDN_ALLOW）的
#     <script src>/<link href> **写进产物 HTML 字符串**，本引擎自身不发起任何请求，故档位仍为 E0。
#     E0 的红线是「脚本不出网」，不是「产物不许含 http 字样」——二者不可混为一谈；
#     白名单域守卫见 check.py::check_html_online_guard。
"""
文档格式引擎 · format-engine（v3.31.0 新增）
===============================================================================
**这一层只回答「存成什么文件」，不回答「内容是什么」「版面什么风格」**。
它是 v3.31.0 三引擎拆分中的第二块，也是唯一直接持有第三方写出库的一层：

  内容层 doc-ir.py         clauses / 差异台账 / 导图树
  风格引擎 style-engine.py 段落角色 / 样式档位（只服务 docx）
  格式引擎 **本文件**       excel / md / html / mindmap / pptx / pdf 的写出与渲染

各家族的生成器字典（**覆盖集真源**）
-------------------------------------------------------------------------------
  EXCEL_GEN    10 类全覆盖                                              → xlsx
  MD_GEN       10 类全覆盖（html 复用本表：md 源 → html_page 包壳）      → md / html
  PPT_GEN      2/8/9 报告讲解类（PPT_TYPES）                            → pptx
  MINDMAP_GEN  2/8/9/10 讲解＋模板结构（MINDMAP_TYPES）                 → svg / html / png
  （docx 与 pdf 不在本文件：docx 由 make-docx.py 的 DOC_GEN 生成，
    pdf 由 docx 经 LibreOffice 无头转换——两条都不属于「纯写出」，故留在调用侧）

格式家族（v3.28.0 起 7 种，v3.32.0 起按家族归 8 种）
-------------------------------------------------------------------------------
  docx / md / excel / pdf / html / pptx / mindmap（＋v3.32.0 的 image 家族）
  索引真源是下面的 FORMAT_ALL／FORMAT_LABEL，help 串、门禁、文档三处都读它。

签名约定：所有渲染器显式收 ctx（doc-ir 的 RenderCtx）——重构前它们直读
REVIEWER/ROUND/TS/SOURCE 模块全局，「谁改的、何时改的」看不出来；收成入参后
改上下文必须显式传，report 类需等档位台账填满才生成的时序耦合也就看得见了。

不改行为：本文件代码自 make-docx.py 原样搬迁＋改签名，算法一字未动；
搬迁前后由 core/_byte-golden.json 逐字节比对守护（同输入同内容）。
"""
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）

import os
import re
import json
import tempfile
import importlib.util
from importlib.machinery import SourceFileLoader

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_local(dashed, plain):
    """同一目录下的连字符脚本按「下划线名」载入（同 make-docx.py 的 _load_engine）。"""
    lob = SourceFileLoader(plain, os.path.join(_HERE, dashed + ".py"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(plain, lob))
    _sys.modules[plain] = mod
    lob.exec_module(mod)
    return mod


_load_local("doc-ir", "doc_ir")

from doc_ir import (clauses, title, template_spec, template_name, original_text,
                    inline_diff, md_diff_text, diff_rows,
                    DIFF_HEADERS, DIFF_KEYS, mm_tree)

try:
    import _config as _cfgmod
    _CFG = _cfgmod.load()
except Exception:
    _cfgmod = None
    _CFG = {}

SOFFICE  = (_cfgmod.tool(_CFG, "soffice") if _cfgmod else "soffice")
PDF_EXPORT = (bool(_cfgmod.render_opt(_CFG, "pdf_export")) if _cfgmod else True)
PDF_TIMEOUT = (int(_cfgmod.render_opt(_CFG, "pdf_timeout_sec") or 180) if _cfgmod else 180)

# 与 make-docx.py 同值的脱敏依赖（原文脱敏版的 Excel 工作面要它）
try:
    import desensitize as _d
except Exception:
    _d = None
MASK_TYPES = (_d.ALL_TYPES.split(",") if _d is not None
              else ["idcard", "phone", "bank", "email", "postcode", "im",
                    "uscc", "amount", "addr", "name"])

# 交付物类型中文名（与 make-docx.py 的 SLUGS 同值；两处由 check.py 的引擎表反查守护
# 只保证文件存在，不保证内容相等——故本处注释点名真源，改动须两处同步）
SLUGS = {
    "tracked":  "修订版",
    "report":   "审查意见报告",
    "clean":    "清洁版",
    "redline":  "红线标记修订版",
    "reportc":  "审查意见批注版",
    "masked":   "原文脱敏版",
    "original": "原文照录版",
    "diff":     "文件比对报告",
    "compare":  "新旧比对",
    "template": "模板版",
}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def outname(slug, ext="docx", tier="", ctx=None):
    """文件名真源在 make-docx.py（含档位标记规则）；本引擎只按同一规则取用。"""
    tag = "-准原稿" + tier[-1] if tier in ("QUASI_A", "QUASI_B") else ""
    return "%s_%s%s_%s_r%s_%s.%s" % (ctx.source, SLUGS[slug], tag, ctx.reviewer,
                                     ctx.round, ctx.ts, ext)


# 用户未指定 --formats 时的兜底格式（v3.25.7）。
# 真源在此一处：argparse 的 default 是哨兵 None，实际取值与门禁登记都读这个常量，
# 避免「default 一改、文档又没跟上」这类分家。
FORMAT_FALLBACK = "docx"
# 全部可用格式（v3.28.0 起 7 种；v3.32.0 加 image 家族 → 8 种），用于未指定时提示「你还可以拿到什么」
# **一级键按家族归**：image 是一个家族（png/jpg/webp/gif/svg/ico 六子格式），
# 用 --image-formats 选子格式，不再把六个扩展名塞进一级清单——
# 否则 --formats 会变成 13 项长串，用户与文档都会被拖垮（详见下方 IMAGE_TYPES）。
FORMAT_ALL = ["docx", "md", "excel", "html", "pdf", "pptx", "mindmap", "image"]
FORMAT_LABEL = {"docx": "WORD", "md": "MD", "excel": "Excel", "html": "HTML",
                "pdf": "PDF", "pptx": "PPT", "mindmap": "思维导图", "image": "图片"}

# ---- v3.32.0 image 家族 ----
# 图片家族回答的是「这份文书要发出去，对方要的是图」——微信/钉钉里转一张长图比转 docx 常见。
# 每个子格式的定位不同，不是同一个东西换皮：
#   png   无损位图，**默认**：长图（整份文书纵向拼一张）＋报告概览卡片，文字锐利
#   jpg   有损位图：发给别人看的长图，体积小；白底，不留透明
#   webp  有损/无损皆可、体积最小：网页与移动端用；公众号/小程序贴图
#   gif   256 色调色板：只适合**示意图/概览卡**，长文正文会糊——故长图不做 gif，见下方说明
#   svg   矢量：概览卡与流程示意；无限放大不糊，可直接插进 Word/PPT
#   ico   多尺寸窗体图标：站点/文档套壳的图标位；单文件按最大尺寸存
# 缺 Pillow 时位图四档记 SKIP 不阻断（与 matplotlib 缺库同口径）；svg 是纯字符串拼接，零依赖。
IMAGE_TYPES = ("png", "jpg", "webp", "gif", "svg", "ico")
IMAGE_DEFAULT = "png"
# 图片覆盖集：图片是「讲给人看」的形态，与 PPT/导图同一原则——
# 仅 NEWDOC_ONLY / CITE_FIDELITY 类；原稿操作件做成图片既不保真也无意义。
IMG_TYPES = ("report", "diff", "compare", "template")
# 长图（整份文书纵向拼一张）只对这几档有意义；gif 因 256 色限制作图质量差，**明确不做长图**
IMG_LONG_TYPES = ("report", "reportc", "clean", "compare", "original")
# ---- v3.28.0 新增格式 ----
# HTML 在线增强版：默认离线（零外部资源）；--html-online 才在产物里挂下列白名单域的外链。
# 白名单是安全口径的**唯一真源**——check.py::check_html_online_guard 与 SECURITY.md 都读它，不另写一份。
# 注意：本脚本自身不发起任何请求（E0 红线是「脚本不出网」），出网的是打开产物的使用者浏览器。
HTML_CDN_ALLOW = ("cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com")
# 格式 × 类型覆盖矩阵：docx/md/html/excel/pdf 为 10 类全覆盖（既有行为），下表只登记**有子集限制**的两档。
# 不在覆盖集内、又被 --formats 选中 → 跳过并在终端汇总提示（不阻断、不静默）。
# 原则：PPT/导图是「讲给人看」的形态，仅覆盖 NEWDOC_ONLY / CITE_FIDELITY 类；
# 原稿操作件（1/3/4/5/6/7）的交付承诺是原稿观感/痕迹，做成幻灯片/导图既不保真也无意义（守卫 check_format_matrix 第 5 条）。
PPT_TYPES = ("report", "diff", "compare")            # 2/8/9：报告讲解类
MINDMAP_TYPES = ("report", "diff", "compare", "template")  # 2/8/9/10：讲解类＋模板结构
# 原文脱敏版默认 **12 类全脱**（含信用代码/金额/地址/人名；比例不脱）。
# 真源＝desensitize.py 的 ALL_TYPES，此处直接取用，避免两处各写一份而漂移。
MASK_TYPES = (_d.ALL_TYPES.split(",") if _d is not None
              else ["idcard", "phone", "bank", "email", "postcode", "im",
                    "uscc", "amount", "addr", "name"])

# ---------- excel 生成（openpyxl） ----------
def _new_sheet(title, headers):
    """返回 (workbook, worksheet)；openpyxl 缺失时返回 (None, None)。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except Exception:
        return None, None
    wb = Workbook(); ws = wb.active; ws.title = (title or "sheet")[:28]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    return wb, ws

def _widths(ws, widths):
    try:
        from openpyxl.utils import get_column_letter
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
    except Exception:
        pass

def xl_compare(spec):
    wb, ws = _new_sheet("新旧比对", ["序号", "条款定位", "原文", "修改后", "评级", "法律依据"])
    if wb is None: return None
    for i, c in enumerate(clauses(spec), 1):
        ws.append([i, c.get("heading", ""), c.get("original", ""), c.get("revised", ""), c.get("rating", ""), c.get("basis", "")])
    _widths(ws, [6, 34, 60, 60, 12, 34])
    return wb

def xl_report(spec):
    wb, ws = _new_sheet("审查意见", ["序号", "条款定位", "评级", "风险描述", "修改建议", "法律依据"])
    if wb is None: return None
    for i, c in enumerate(clauses(spec), 1):
        ws.append([i, c.get("heading", ""), c.get("rating", ""), c.get("comment", ""), c.get("revised", ""), c.get("basis", "")])
    _widths(ws, [6, 34, 12, 60, 60, 34])
    return wb

def xl_clause_table(spec):
    wb, ws = _new_sheet("条款清单", ["序号", "条款定位", "原文", "修订后文本", "评级"])
    if wb is None: return None
    for i, c in enumerate(clauses(spec), 1):
        ws.append([i, c.get("heading", ""), c.get("original", ""), c.get("revised", ""), c.get("rating", "")])
    _widths(ws, [6, 34, 60, 60, 12])
    return wb

def xl_text(spec, masked=False):
    wb, ws = _new_sheet("原文脱敏版" if masked else "原文照录版", ["行号", "文本"])
    if wb is None: return None
    text = original_text(spec)
    if masked and _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    for i, line in enumerate(text.splitlines(), 1):
        ws.append([i, line])
    _widths(ws, [6, 120])
    return wb

def xl_diff(spec):
    wb, ws = _new_sheet("文件比对", DIFF_HEADERS)
    if wb is None: return None
    rows, _ = diff_rows(spec)
    for r in rows:
        ws.append([r[k] for k in DIFF_KEYS])
    _widths(ws, [6, 30, 10, 10, 55, 55, 26])
    return wb

def xl_template(spec):
    """模板版的 Excel 呈现：有占位符出《占位符说明表》，无占位符出《模板正文》逐行表。"""
    t = template_spec(spec)
    if t["placeholders"]:
        wb, ws = _new_sheet("占位符说明表", ["序号", "占位符", "含义", "填写示例", "是否必填"])
        if wb is None: return None
        for i, p in enumerate(t["placeholders"], 1):
            ws.append([i, p.get("name", ""), p.get("meaning", ""), p.get("example", ""),
                       "必填" if p.get("required") else "选填"])
        _widths(ws, [6, 26, 40, 40, 10])
        return wb
    wb, ws = _new_sheet("模板正文", ["行号", "文本"])
    if wb is None: return None
    for i, line in enumerate(t["body"].splitlines(), 1):
        ws.append([i, line])
    _widths(ws, [6, 120])
    return wb


EXCEL_GEN = {
    "tracked": xl_clause_table, "redline": xl_clause_table, "clean": xl_clause_table,
    "report": xl_report, "reportc": xl_report, "compare": xl_compare,
    "original": lambda s: xl_text(s, False), "masked": lambda s: xl_text(s, True),
    "diff": xl_diff, "template": xl_template,
}
# 兼容别名：调用侧（make-docx.py）原先读的就是这个名字，改名不必要地扩大改动面。
DOC_EXCEL_GEN = EXCEL_GEN

def export_pdf(docx_paths, outdir):
    """用 LibreOffice 无头模式把 docx 转 PDF；不可用时返回空列表（不阻断主流程）。"""
    if not docx_paths:
        return []
    if not PDF_EXPORT:
        print("[format-engine] 提示：config.render.pdf_export=false，跳过 PDF 导出。")
        return []
    if _cfgmod and not _cfgmod.tool_available(_CFG, "soffice"):
        print("[format-engine] 提示：未检测到 LibreOffice，跳过 PDF 导出（装好 LibreOffice 或改 config.json 后可重跑）。")
        return []
    import subprocess
    try:
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", outdir] + docx_paths,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=PDF_TIMEOUT)
        if r.returncode != 0:
            print("[format-engine] PDF 导出返回码非 0：", (r.stderr or r.stdout or "")[:200])
    except Exception as e:
        print("[format-engine] PDF 导出失败（不影响其它交付物）：", e)
        return []
    outs = [os.path.splitext(os.path.basename(p))[0] + ".pdf" for p in docx_paths]
    return [o for o in outs if os.path.exists(os.path.join(outdir, o))]

# ---------- md 生成 ----------
def md_meta_line(slug, ctx):
    """md/html 顶部元信息行。"""
    return "> %s ｜ 审查人：%s ｜ 轮次：r%s" % (SLUGS.get(slug, slug), ctx.reviewer, ctx.round)


def md_trackchanges(spec, ctx):
    out = ["# " + title(spec), "", md_meta_line("tracked", ctx) + "　图例：`<del>`=删除、`<ins>`=新增。"]
    for c in clauses(spec):
        o, v = c.get("original", ""), c.get("revised", "")
        out.append(f"\n**{c.get('heading','')}**\n\n" + md_diff_text(o, v, "tracked"))
    return "\n".join(out) + "\n"

def md_redline(spec, ctx):
    out = ["# " + title(spec), "", md_meta_line("redline", ctx) + "　图例：`~~删除~~`、`**新增**`。"]
    for c in clauses(spec):
        o, v = c.get("original", ""), c.get("revised", "")
        out.append(f"\n**{c.get('heading','')}**\n\n" + md_diff_text(o, v, "redline"))
    return "\n".join(out) + "\n"

def md_clean(spec, ctx):
    out = ["# " + title(spec), "", md_meta_line("clean", ctx)]
    for c in clauses(spec):
        out.append(f"\n**{c.get('heading','')}**\n\n{c.get('revised') or c.get('original') or ''}")
    return "\n".join(out) + "\n"

def md_report(spec, ctx):
    out = ["# " + (spec.get("report_title", "文档合规审查意见报告")), "",
           "> 源文件：" + title(spec) + "｜审查人：" + ctx.reviewer + "｜轮次：r" + ctx.round, ""]
    for i, c in enumerate(clauses(spec), 1):
        out.append(f"## {i}. {c.get('heading','')}  {c.get('rating','')}")
        out.append(f"- 风险描述：{c.get('comment') or '—'}")
        out.append(f"- 法律依据：{c.get('basis') or '—'}")
        out.append(f"- 修改建议：{c.get('revised') or '—'}")
    return "\n".join(out) + "\n"

def md_compare(spec, ctx):
    out = ["# " + title(spec) + "（新旧比对）", "", "| 条款 | 原文 | 修改后 |", "|---|---|---|"]
    for c in clauses(spec):
        out.append(f"| {c.get('heading','')} | {(c.get('original') or '').replace(chr(10),'<br>')} | {(c.get('revised') or '').replace(chr(10),'<br>')} |")
    return "\n".join(out) + "\n"

def md_original(spec, ctx):
    return "# " + title(spec) + "\n\n" + md_meta_line("original", ctx) + \
           "　内部留存，勿对外。\n\n" + original_text(spec) + "\n"

def md_masked(spec, ctx):
    text = original_text(spec)
    if _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    return "# " + title(spec) + "\n\n" + md_meta_line("masked", ctx) + \
           "　已脱敏（信用代码/金额/地址/人名；比例不脱）。\n\n" + text + "\n"

def md_diff(spec, ctx):
    rows, note = diff_rows(spec)
    out = ["# " + title(spec) + "（文件比对报告）", "", "> " + note, "",
           "| " + " | ".join(DIFF_HEADERS) + " |",
           "|" + "---|" * len(DIFF_HEADERS)]
    for r in rows:
        cells = [r[k].replace("|", "\\|").replace("\n", "<br>") for k in DIFF_KEYS]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"

def md_reportc(spec, ctx):
    """批注版的 Markdown 等效呈现（Markdown 无批注锚定能力，正文即意见清单）。"""
    return md_report(spec, ctx) + "\n> 说明：Markdown 不支持 Word 批注；本文件为该类型的等效文本呈现，" \
                             "需逐条批注锚定请选 WORD 格式。\n"

def md_template(spec, ctx):
    t = template_spec(spec)
    out = ["# " + template_name(spec), "", md_meta_line("template", ctx), ""]
    if t["placeholders"]:
        out += ["## 一、占位符说明表", "",
                "| 占位符 | 含义 | 填写示例 | 是否必填 |", "|---|---|---|---|"]
        for p in t["placeholders"]:
            out.append("| %s | %s | %s | %s |" % (p.get("name", ""), p.get("meaning", ""),
                                                  p.get("example", ""),
                                                  "必填" if p.get("required") else "选填"))
        out.append("")
    if t["body"]:
        out += ["## 二、模板正文", "", t["body"], ""]
    if t["optional"]:
        out += ["## 三、可选条款区", ""]
        for o in t["optional"]:
            out += ["**%s**" % (o.get("name") or "可选条款"),
                    "- 适用场景：%s" % (o.get("scene") or "—"),
                    "- 取舍建议：%s" % (o.get("advice") or "—"), ""]
    if t["notes"]:
        out += ["## 四、使用须知", "", t["notes"], ""]
    return "\n".join(out) + "\n"


MD_GEN = {
    "tracked": md_trackchanges, "redline": md_redline, "clean": md_clean,
    "report": md_report, "reportc": md_reportc, "compare": md_compare,
    "original": md_original, "masked": md_masked, "diff": md_diff,
    "template": md_template,
}

# ---------- 思维导图导出（v3.28.0 · 一物两件：交互折叠树 HTML ＋ matplotlib PNG） ----------
# 覆盖集见 MINDMAP_TYPES（2/8/9/10）；原稿操作件不出导图（内容是逐句 diff，压成节点丢信息）。
# 数据结构单一真源 mm_tree()：HTML 与 PNG 两个渲染器共用同一棵树，不许各写一套（铁律第 12 条）。

def mindmap_svg(root, nodes):
    """静态 SVG（v3.29.0 起为 mindmap 默认静态形态）。

    **纯 Python 字符串拼接、零外部依赖**——不依赖 matplotlib/字体探测（文字用 font-family
    回落链，由查看方渲染），解决了 PNG「缺中文字体不出图」与「体积大」两个老问题。
    SVG 浏览器双击直开；Word/PPT 2016+ 与 WPS 原生支持插入；矢量缩放不糊。
    布线与 mindmap_png 同一棵树（mm_tree 单一数据源），坐标全 data 语义，勿混。
    """
    lines = [(0, root, None)]
    for br in nodes:
        r_br = len(lines)
        lines.append((1, br["text"], 0))
        for lf in br["children"]:
            lines.append((2, lf["text"], r_br))
    xs = (10, 130, 280)
    fs = (15, 13, 12)
    col = {0: "#0b2038", 1: "#8a6d2f", 2: "#5a6478"}
    lh = 30
    w = max(xs[lv] + int(len(t) * fs[lv] * 1.05) + 40 for lv, t, _ in lines)
    h = 24 + lh * len(lines)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="Microsoft YaHei,PingFang SC,'
           'Noto Sans CJK SC,sans-serif">' % (w, h, w, h),
           '<rect width="%d" height="%d" fill="white"/>' % (w, h)]
    for i, (lv, txt, par) in enumerate(lines):
        y = 24 + lh * i + fs[lv]
        if par is not None:
            py = 24 + lh * par + fs[lines[par][0]]
            out.append('<path d="M %d %d H %d V %d H %d" fill="none" '
                       'stroke="#b9c2d0" stroke-width="1.2"/>'
                       % (xs[lv] - 6, py, xs[lv] - 20, y, xs[lv] - 6))
    for i, (lv, txt, par) in enumerate(lines):
        y = 24 + lh * i + fs[lv]
        bold = ' font-weight="bold"' if lv == 0 else ""
        out.append('<text x="%d" y="%d" font-size="%d" fill="%s"%s>%s</text>'
                   % (xs[lv], y, fs[lv], col[lv], bold, esc(txt)))
    out.append("</svg>")
    return "\n".join(out)

# 缺库降级真源：matplotlib 可用性在模块加载时判定（照 openpyxl 既有模式）。
_MPL_OK = False
try:
    os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())  # 防 mpl 缓存写进技能目录污染打包
    import matplotlib  # noqa: E402
    matplotlib.use("Agg")   # 纯本地渲染，无 GUI（E0：matplotlib 不发网络请求）
    from matplotlib import font_manager as _fm
    _MPL_OK = True
except Exception:
    pass

def mindmap_png(root, nodes, path):
    """静态 PNG（300dpi 横向树）。缺中文字体→返回失败原因、不出豆腐图。"""
    if not _MPL_OK:
        return "未安装 matplotlib"
    want = ("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Noto Sans CJK JP",
            "SimHei", "WenQuanYi Zen Hei", "Source Han Sans SC")
    have = {f.name for f in _fm.fontManager.ttflist}
    fam = next((w for w in want if w in have), None)
    if not fam:
        return "本机缺中文字体（探测链 %s 均未命中），PNG 跳过；交互 HTML 导图不受影响" % "、".join(want)
    import matplotlib.pyplot as _plt
    # 树形布线（全部 data 坐标，勿混 axes-fraction——首版混用导致连线错位）：
    # 行 0＝根，其后逐行「枝→该枝的叶」；连线从上一级文字右侧出发到本级左侧。
    lines = []   # (level, text, parent_row)
    lines.append((0, root, None))
    for br in nodes:
        r_br = len(lines)
        lines.append((1, br["text"], 0))
        for lf in br["children"]:
            lines.append((2, lf["text"], r_br))
    fig_h = max(4.0, 0.42 * len(lines) + 1.0)
    fig_w = max(10.0, 0.10 * max(len(t) for _, t, _ in lines) + 6.0)
    fig, ax = _plt.subplots(figsize=(fig_w, fig_h))
    ys = {i: len(lines) - 1 - i for i in range(len(lines))}
    xs = (0.01, 0.14, 0.30)
    col = {0: "#0b2038", 1: "#8a6d2f", 2: "#5a6478"}
    for i, (lv, txt, par) in enumerate(lines):
        ax.text(xs[lv], ys[i], txt, fontsize=(12, 10, 9)[lv], color=col[lv],
                fontfamily=fam, va="center",
                fontweight=("bold" if lv == 0 else "normal"))
        if par is not None:
            ax.plot([xs[lv] - 0.015, xs[lv] - 0.004], [ys[par], ys[i]],
                    color="#b9c2d0", lw=0.9, clip_on=False)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.8, len(lines) - 0.2)
    ax.axis("off")
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    _plt.close(fig)
    return ""

def mindmap_html(root, nodes, slug, spec, ctx):
    """交互折叠树：纯内联 CSS/JS，点节点折叠/展开，断网可开（与精要总结导图同一套口径）。"""
    def render(nds):
        if not nds:
            return ""
        lis = "".join(
            '<li><span class="mm-node%s">%s</span>%s</li>' % (
                " has-kids" if n["children"] else "", esc(n["text"]), render(n["children"]))
            for n in nds)
        return "<ul>%s</ul>" % lis
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>思维导图 · %(t)s</title>
<style>%(css)s</style></head><body>
<div class="mm-top">思维导图 · %(slug)s ｜ 点节点折叠/展开 · 断网可开</div>
<main class="mm-page">
  <h1>%(root)s</h1>
  %(body)s
  <div class="mm-foot">%(meta)s　｜　本文件由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成最终法律意见。</div>
</main>
<script>%(js)s</script>
</body></html>
""" % {"t": esc(title(spec)), "slug": esc(SLUGS.get(slug, slug)), "root": esc(root),
       "css": MM_CSS, "body": render(nodes), "js": MM_JS,
       "meta": esc(md_meta_line(slug, ctx))}

MM_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f6f7fa;color:#1f2430;font-size:15px;line-height:1.7;
     font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif}
.mm-top{position:sticky;top:0;background:#0b2038;color:#fff;padding:10px 16px;font-size:13px;
        letter-spacing:.3px}
.mm-page{max-width:980px;margin:0 auto;padding:24px 22px 60px;background:#fff;min-height:100vh}
h1{font-size:22px;margin:4px 0 14px;padding-bottom:10px;border-bottom:2px solid #c9a24a}
ul{list-style:none;margin:0;padding-left:22px}
.mm-page>ul{padding-left:0}
li{margin:4px 0;position:relative}
li::before{content:"";position:absolute;left:-14px;top:.9em;width:12px;height:1px;background:#b9c2d0}
li::after{content:"";position:absolute;left:-14px;top:0;bottom:0;width:1px;background:#e3e7ef}
li:last-child::after{height:.9em}
.mm-node{display:inline-block;padding:3px 10px;border-radius:6px;cursor:pointer;
         background:#f2f4f8;border:1px solid #e3e7ef;font-size:14px}
.mm-node.has-kids{background:#0b2038;color:#fff;border-color:#0b2038}
.mm-node.has-kids::after{content:" −";color:#c9a24a}
.mm-node.closed.has-kids::after{content:" +"}
li.closed>ul{display:none}
.mm-foot{margin-top:30px;padding-top:12px;border-top:1px solid #e3e7ef;color:#8b93a6;font-size:12.5px}
@media print{.mm-top{display:none}.mm-node{cursor:auto}}
"""

MM_JS = """
(function(){
  document.addEventListener('click',function(e){
    var n=e.target.closest('.mm-node');
    if(!n||!n.classList.contains('has-kids'))return;
    n.classList.toggle('closed');
    n.parentElement.classList.toggle('closed');
  });
})();
"""

MINDMAP_GEN = {"report": mm_tree, "diff": mm_tree, "compare": mm_tree, "template": mm_tree}

# ---------- 图片导出（v3.32.0 · image 家族：png/jpg/webp/gif/svg/ico） ----------
# 覆盖集见 IMG_TYPES；原稿操作件不出图片（与 PPT/导图同一原则）。
# 三种画面（画什么）：
#   card   概览卡 —— 标题＋档位色带＋关键指标数字块，横版 1600×900，适合贴群/贴朋友圈
#   long   长图   —— 整份文书纵向拼接（标题区＋逐段正文），宽 1080，高按内容自适应
#   mind   导图   —— 复用 mm_tree 的树，压成 SVG/位图（同一棵树，不许另写一套）
# 六种子格式（画成什么文件）：
#   svg 是纯字符串拼接、零依赖——这样即使本机没装 Pillow，图片家族也**不会全军覆没**；
#   gif 的 256 色限制让长图正文糊成一团，故 **长图不做 gif**（选了就降级为概览卡并说明）。
_IMG_FONT_CANDIDATES = (
    # (字体路径, 是否等宽) —— 中文字体优先；找不到中文就退回 DejaVu（只影响观感，不出豆腐块以外的问题）
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", False),
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", False),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", False),
    ("C:/Windows/Fonts/msyh.ttc", False),
    ("C:/Windows/Fonts/simhei.ttf", False),
    ("/System/Library/Fonts/PingFang.ttc", False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
)
_IMG_PALETTE = {
    "navy": "#0B2038", "gold": "#C9A24A", "fg": "#1F2430", "fg2": "#5A6478",
    "line": "#E3E7EF", "bg": "#FFFFFF", "soft": "#F6F7FA",
    "r3": "#D8443C", "r2": "#E3A637", "r1": "#3E9B6B",
}


def _img_hex(c):
    return _IMG_PALETTE.get(c, c)


def _img_font(size):
    """返回 (PIL ImageFont, 是否命中中文字体)。缺 Pillow 由调用方先判。"""
    from PIL import ImageFont
    for path, _ in _IMG_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size), ("CJK" in path or "msyh" in path
                                                    or "simhei" in path or "PingFang" in path)
        except Exception:
            continue
    return ImageFont.load_default(), False


def _img_wrap(draw, text, font, width):
    """按像素宽度折行（中文按字切，英文按词切；标点不吃行首）。返回行列表。"""
    text = (text or "").replace("\r", "")
    lines = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for ch in para:
            probe = cur + ch
            try:
                w = draw.textlength(probe, font=font)
            except Exception:
                w = len(probe) * 10
            if w > width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = probe
        if cur:
            lines.append(cur)
    return lines


def _img_rating_color(rating):
    r = rating or ""
    if "★★★" in r:
        return "r3"
    if "★★" in r:
        return "r2"
    return "r1"


def _img_stats(spec):
    """概览卡的数字块：总条数＋三档风险计数。真源＝clauses(spec) 的 rating。"""
    cs = clauses(spec)
    st = {"★★★": 0, "★★": 0, "★": 0, "—": 0}
    for c in cs:
        r = (c.get("rating") or "—").strip()
        st[r if r in st else "—"] += 1
    return len(cs), st


def _img_card_canvas(spec):
    """概览卡画布（1600×900）。返回 (img, draw, font_ok)。"""
    from PIL import Image, ImageDraw
    W, H = 1600, 900
    img = Image.new("RGB", (W, H), _img_hex("bg"))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W, 150], fill=_img_hex("navy"))
    dr.rectangle([0, 150, W, 158], fill=_img_hex("gold"))
    f_title, ok1 = _img_font(54)
    f_sub, ok2 = _img_font(30)
    f_num, ok3 = _img_font(96)
    f_lab, ok4 = _img_font(28)
    dr.text((70, 46), (title(spec) or "文档合规审查")[:22], font=f_title, fill="#FFFFFF")
    dr.text((70, 110), "文档合规审查意见报告 ｜ %s" % (spec.get("reviewer") or ""),
            font=f_sub, fill=_img_hex("gold"))
    n, st = _img_stats(spec)
    dr.text((70, 210), "共 %d 条审查意见" % n, font=_img_font(40)[0], fill=_img_hex("fg"))
    boxes = (("★★★ 高风险", st["★★★"], "r3", 70),
             ("★★ 中风险", st["★★"], "r2", 570),
             ("★ 低风险", st["★"], "r1", 1070))
    for lab, val, col, x in boxes:
        dr.rounded_rectangle([x, 320, x + 460, 640], radius=24,
                             fill=_img_hex("soft"), outline=_img_hex("line"), width=2)
        dr.rectangle([x, 320, x + 460, 332], fill=_img_hex(col))
        dr.text((x + 40, 380), str(val), font=f_num, fill=_img_hex(col))
        dr.text((x + 40, 540), lab, font=f_lab, fill=_img_hex("fg2"))
    dr.text((70, 730), "本图由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成最终法律意见。",
            font=_img_font(24)[0], fill=_img_hex("fg2"))
    dr.text((70, 780), "逐条意见与法律依据以 WORD / HTML 报告正文为准。",
            font=_img_font(24)[0], fill=_img_hex("fg2"))
    return img, dr, (ok1 and ok2 and ok3 and ok4)


def _img_long_canvas(spec, slug):
    """长图画布（宽 1080，高按内容自适应）。返回 (img, draw)。

    逐段画：标题 → 元信息 → 每条「条款标题（评级）」＋原文/修改后/风险/依据/建议。
    高度先算后画——Pillow 不支持先画再裁剪，须两遍：一遍估高，一遍实画。
    """
    from PIL import Image, ImageDraw
    W = 1080
    pad, maxw = 60, W - 120
    f_h1, _ = _img_font(44)
    f_h2, _ = _img_font(30)
    f_body, _ = _img_font(24)
    f_meta, _ = _img_font(20)

    # 第一遍：估高（用一个 1×1 画布量文字宽度即可）
    probe = Image.new("RGB", (10, 10))
    pdr = ImageDraw.Draw(probe)
    blocks = []          # (kind, payload, height)
    t_lines = _img_wrap(pdr, title(spec), f_h1, maxw)
    blocks.append(("title", t_lines, len(t_lines) * 56 + 30))
    for i, c in enumerate(clauses(spec), 1):
        head = "%d. %s %s" % (i, c.get("heading") or "条款", c.get("rating") or "")
        hl = _img_wrap(pdr, head, f_h2, maxw)
        segs = []
        for k, lab in (("original", "原文"), ("revised", "修改后"),
                       ("comment", "风险"), ("basis", "依据")):
            v = (c.get(k) or "").strip()
            if not v:
                continue
            for ln in _img_wrap(pdr, "%s：%s" % (lab, v), f_body, maxw):
                segs.append(ln)
        h = len(hl) * 38 + len(segs) * 34 + 34
        blocks.append(("clause", (hl, segs), h))
    total_h = 180 + sum(b[2] for b in blocks) + 140
    img = Image.new("RGB", (W, max(720, total_h)), _img_hex("bg"))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W, 96], fill=_img_hex("navy"))
    dr.rectangle([0, 96, W, 102], fill=_img_hex("gold"))
    dr.text((pad, 26), "文档合规审查 · 长图", font=f_h2, fill="#FFFFFF")
    y = 140
    for kind, payload, h in blocks:
        if kind == "title":
            for ln in payload:
                dr.text((pad, y), ln, font=f_h1, fill=_img_hex("fg"))
                y += 56
            dr.text((pad, y + 4), "审查人：%s ｜ 轮次：r%s ｜ 共 %d 条"
                    % (spec.get("reviewer") or "", spec.get("round") or "1",
                       len(clauses(spec))), font=f_meta, fill=_img_hex("fg2"))
            y += 44
        else:
            hl, segs = payload
            for ln in hl:
                dr.text((pad, y), ln, font=f_h2, fill=_img_hex("navy"))
                y += 38
            y += 4
            for ln in segs:
                dr.text((pad + 14, y), ln, font=f_body, fill=_img_hex("fg"))
                y += 34
            dr.line([pad, y + 8, W - pad, y + 8], fill=_img_hex("line"), width=1)
            y += 26
    dr.text((pad, y + 20), "本图由「文档合规审查助手AI合同」生成，仅供参考，不构成最终法律意见。",
            font=f_meta, fill=_img_hex("fg2"))
    return img, dr


def img_svg(root, nodes, spec):
    """概览卡的 SVG 版（零依赖、无限缩放）。与位图概览卡同一套版式与文案。"""
    n, st = _img_stats(spec)
    boxes = (("★★★ 高风险", st["★★★"], "r3", 70),
             ("★★ 中风险", st["★★"], "r2", 570),
             ("★ 低风险", st["★"], "r1", 1070))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" '
             'viewBox="0 0 1600 900" font-family="Microsoft YaHei,PingFang SC,'
             'Noto Sans CJK SC,sans-serif">',
             '<rect width="1600" height="900" fill="#FFFFFF"/>',
             '<rect width="1600" height="150" fill="#0B2038"/>',
             '<rect y="150" width="1600" height="8" fill="#C9A24A"/>',
             '<text x="70" y="90" font-size="54" fill="#FFFFFF">%s</text>' % esc((title(spec) or "文档合规审查")[:22]),
             '<text x="70" y="136" font-size="30" fill="#C9A24A">文档合规审查意见报告 ｜ %s</text>'
             % esc(spec.get("reviewer") or ""),
             '<text x="70" y="250" font-size="40" fill="#1F2430">共 %d 条审查意见</text>' % n]
    for lab, val, col, x in boxes:
        parts.append('<rect x="%d" y="320" width="460" height="320" rx="24" fill="#F6F7FA" '
                     'stroke="#E3E7EF" stroke-width="2"/>' % x)
        parts.append('<rect x="%d" y="320" width="460" height="12" rx="6" fill="%s"/>'
                     % (x, _IMG_PALETTE[col]))
        parts.append('<text x="%d" y="480" font-size="96" fill="%s">%d</text>'
                     % (x + 40, _IMG_PALETTE[col], val))
        parts.append('<text x="%d" y="580" font-size="28" fill="#5A6478">%s</text>'
                     % (x + 40, esc(lab)))
    parts.append('<text x="70" y="760" font-size="24" fill="#5A6478">'
                 '本图由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成最终法律意见。</text>')
    parts.append('<text x="70" y="810" font-size="24" fill="#5A6478">'
                 '逐条意见与法律依据以 WORD / HTML 报告正文为准。</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def img_mind(root, nodes, spec, fmt):
    """导图的图片形态：svg 直接复用 mindmap_svg；位图经 matplotlib（复用 mindmap_png 的布线）。

    返回 (payload, reason)：payload 为 str（svg）或 bytes（已落盘前的图）；reason 非空＝跳过。
    """
    if fmt == "svg":
        return mindmap_svg(root, nodes), ""
    if not _MPL_OK:
        return None, "未安装 matplotlib（导图位图需它；纯 svg 可换 --image-formats svg）"
    import io
    import matplotlib.pyplot as _plt
    want = ("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Noto Sans CJK JP",
            "SimHei", "WenQuanYi Zen Hei", "Source Han Sans SC")
    have = {f.name for f in _fm.fontManager.ttflist}
    fam = next((w for w in want if w in have), None)
    if not fam:
        return None, "本机缺中文字体（探测链 %s 均未命中）" % "、".join(want)
    lines = [(0, root, None)]
    for br in nodes:
        r_br = len(lines)
        lines.append((1, br["text"], 0))
        for lf in br["children"]:
            lines.append((2, lf["text"], r_br))
    fig_h = max(4.0, 0.42 * len(lines) + 1.0)
    fig_w = max(10.0, 0.10 * max(len(t) for _, t, _ in lines) + 6.0)
    fig, ax = _plt.subplots(figsize=(fig_w, fig_h))
    ys = {i: len(lines) - 1 - i for i in range(len(lines))}
    xs = (0.01, 0.14, 0.30)
    col = {0: "#0b2038", 1: "#8a6d2f", 2: "#5a6478"}
    for i, (lv, txt, par) in enumerate(lines):
        ax.text(xs[lv], ys[i], txt, fontsize=(12, 10, 9)[lv], color=col[lv],
                fontfamily=fam, va="center",
                fontweight=("bold" if lv == 0 else "normal"))
        if par is not None:
            ax.plot([xs[lv] - 0.015, xs[lv] - 0.004], [ys[par], ys[i]],
                    color="#b9c2d0", lw=0.9, clip_on=False)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.8, len(lines) - 0.2)
    ax.axis("off")
    buf = io.BytesIO()
    fig.savefig(buf, dpi=300, bbox_inches="tight", facecolor="white")
    _plt.close(fig)
    return buf.getvalue(), ""


def _img_encode(img, fmt, out_path):
    """按子格式落盘。返回 "" 成功，否则返回失败原因（不抛异常，跳过即可）。"""
    from PIL import Image   # 局部导入：本函数是 gif 调色板量化的唯一用点
    try:
        if fmt in ("png", "gif", "ico"):
            if fmt == "png":
                img.save(out_path, "PNG", optimize=True)
            elif fmt == "gif":
                # 256 色：调色板量化；只用于概览卡（长图不做 gif，见上方说明）
                img.convert("P", palette=Image.ADAPTIVE, colors=256).save(out_path, "GIF")
            else:
                # ico 单文件按最大尺寸存（用户口径：ico 单尺寸，不做多分辨率叠加）
                img.save(out_path, "ICO", sizes=[(256, 256)])
        elif fmt == "jpg":
            img.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)
        elif fmt == "webp":
            img.save(out_path, "WEBP", quality=88, method=4)
        else:
            return "不支持的图片子格式 %s" % fmt
    except Exception as e:  # noqa: BLE001
        return "写盘失败：%s" % e
    return ""


def export_image(pairs, spec, outdir, ctx, want=("png",), want_long=True):
    """图片家族出口。pairs: [(slug, tier)]。

    返回 (made, skips)：made 为产出文件名列表；skips 为 [(slug, fmt, reason)]，
    由调用方汇总提示——**不许静默跳过**（缺 Pillow / 缺字体都要说清）。
    """
    made, skips = [], []
    try:
        from PIL import Image  # noqa: F401
        _pil = True
    except Exception:
        _pil = False
    for t, tier in pairs:
        base = outname(t, "png", tier=tier, ctx=ctx)[:-4]     # 公共主干（去掉 .png）
        for fmt in want:
            name = "%s.%s" % (base, fmt)
            path = os.path.join(outdir, name)
            if fmt == "svg":
                open(path, "w", encoding="utf-8").write(img_svg(None, None, spec))
                made.append(name)
                continue
            if not _pil:
                skips.append((t, fmt, "未安装 Pillow（pip install Pillow 后重跑）"))
                continue
            # 长图 vs 概览卡：gif 不做长图（256 色会把正文糊掉）
            use_long = bool(want_long) and fmt != "gif" and t in IMG_LONG_TYPES
            if use_long:
                img, _ = _img_long_canvas(spec, t)
            else:
                img, _, _ = _img_card_canvas(spec)
            why = _img_encode(img, fmt, path)
            if why:
                skips.append((t, fmt, why))
            else:
                made.append(name)
    return made, skips


def export_image_mindmap(pairs, spec, outdir, ctx, want=("png",)):
    """导图的图片形态（与图片家族共用 --image-formats，但数据来自 mm_tree）。"""
    made, skips = [], []
    try:
        from PIL import Image  # noqa: F401
        _pil = True
    except Exception:
        _pil = False
    for t, tier in pairs:
        root, nodes = mm_tree(t, spec)
        if not nodes:
            continue
        base = outname(t, "png", tier=tier, ctx=ctx)[:-4]
        stem = "%s_导图" % base
        for fmt in want:
            name = "%s.%s" % (stem, fmt)
            path = os.path.join(outdir, name)
            if fmt == "svg":
                open(path, "w", encoding="utf-8").write(mindmap_svg(root, nodes))
                made.append(name)
                continue
            if not _pil:
                skips.append((t, fmt, "未安装 Pillow"))
                continue
            payload, why = img_mind(root, nodes, spec, fmt)
            if why:
                skips.append((t, fmt, why))
                continue
            try:
                import io
                from PIL import Image as _Im
                im = _Im.open(io.BytesIO(payload)).convert("RGB")
                w2 = _img_encode(im, fmt, path)
                (made.append(name) if not w2 else skips.append((t, fmt, w2)))
            except Exception as e:  # noqa: BLE001
                skips.append((t, fmt, "转码失败：%s" % e))
    return made, skips


# ---------- PPT 讲解版导出（v3.28.0 · python-pptx，覆盖 2/8/9 报告讲解类） ----------
# 覆盖集见 PPT_TYPES；原稿操作件不套 PPT（幻灯片冒充原稿是保真体系的破口，守卫第 5 条拦）。
# PPT 不承载 Word 批注锚点/修订痕迹——那是 docx 格式的物理边界，SKILL 文档已写明。
try:
    from pptx import Presentation as _Presentation
    from pptx.util import Inches as _In, Pt as _Pt
    from pptx.dml.color import RGBColor as _RGB
    _PPTX_OK = True
except Exception:
    _PPTX_OK = False

# 配色与 HTML_CSS 同一套色值（第三处引用非第三份定义；CSS 是普通字符串，f-string 化代价高，
# 故本表独立声明并在注释里指回 HTML_CSS——改色须两处同步，check 无从咬合，见 DEVLOG 记录）
BRAND = {"navy": (0x0B, 0x20, 0x38), "gold": (0xC9, 0xA2, 0x4A),
         "r3": (0xD8, 0x44, 0x3C), "r2": (0xE3, 0xA6, 0x37), "r1": (0x3E, 0x9B, 0x6B),
         "fg2": (0x5A, 0x64, 0x78), "line": (0xE3, 0xE7, 0xEF)}
PPT_DISCLAIM = "本演示由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成最终法律意见；须人工复审核查后方可据此决策。"
PPT_MAX_SLIDES = 80   # 逐条意见一页一条，大合同封顶；超出并入分组页

def _ppt_text(slide, x, y, w, h, text, size=18, bold=False, color="fg2", align=None):
    box = slide.shapes.add_textbox(_In(x), _In(y), _In(w), _In(h))
    tf = box.text_frame
    tf.word_wrap = True
    lines = (text or "").split("\n")
    for i, ln in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = para.add_run()
        run.text = ln
        run.font.size = _Pt(size)
        run.font.bold = bold
        c = BRAND.get(color, BRAND["fg2"])
        run.font.color.rgb = _RGB(*c)
        run.font.name = "Microsoft YaHei"
        # python-pptx 只设 latin 字体，中文须补 a:ea（东亚字体）节点，否则回落默认体
        try:
            from pptx.oxml.ns import qn as _qn
            _ea = run._r.get_or_add_rPr().makeelement(_qn("a:ea"), {"typeface": "Microsoft YaHei"})
            run._r.get_or_add_rPr().append(_ea)
        except Exception:
            pass
    if align:
        for para in tf.paragraphs:
            para.alignment = align
    return box

def _ppt_slide(prs, title_txt=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # 空白版式
    if title_txt:
        _ppt_text(slide, 0.6, 0.35, 12.1, 0.9, title_txt, size=26, bold=True, color="navy")
        bar = slide.shapes.add_shape(1, _In(0.62), _In(1.18), _In(2.6), _In(0.06))
        bar.fill.solid(); bar.fill.fore_color.rgb = _RGB(*BRAND["gold"]); bar.line.fill.background()
    _ppt_text(slide, 0.6, 6.9, 12.1, 0.5, PPT_DISCLAIM, size=9, color="fg2")
    return slide

def _ppt_rating_color(rating):
    r = rating or ""
    if "★★★" in r: return "r3"
    if "★★" in r: return "r2"
    return "r1"

def _ppt_report(prs, spec, ctx):
    _ppt_text(_ppt_slide(prs), 0.6, 2.2, 12.1, 1.0,
              spec.get("report_title", "文档合规审查意见报告"), size=40, bold=True, color="navy")
    _ppt_text(_ppt_slide(prs), 0.6, 2.6, 12.1, 1.4,
              "源文件：%s\n审查人：%s　轮次：r%s" % (title(spec), ctx.reviewer, ctx.round), size=18)
    cs = clauses(spec)
    stats = {}
    for c in cs:
        stats[c.get("rating") or "—"] = stats.get(c.get("rating") or "—", 0) + 1
    s = _ppt_slide(prs, "总体风险概览")
    _ppt_text(s, 0.6, 1.6, 12.1, 0.8, "共 %d 条审查意见" % len(cs), size=22, bold=True)
    y = 2.6
    for r, n in sorted(stats.items()):
        _ppt_text(s, 0.9, y, 3.0, 0.6, r, size=18, bold=True, color=_ppt_rating_color(r))
        _ppt_text(s, 4.0, y, 8.0, 0.6, "%d 条" % n, size=18)
        y += 0.7
    idx = 0
    for c in cs:
        idx += 1
        if idx > PPT_MAX_SLIDES - 4:
            _ppt_text(_ppt_slide(prs, "（其余 %d 条意见见 WORD/HTML 报告）" % (len(cs) - idx + 1)),
                      0.6, 2.5, 12.1, 1.0, "逐条页已达 %d 页上限，完整清单以报告正文为准。" % PPT_MAX_SLIDES)
            break
        s = _ppt_slide(prs, "%d. %s" % (idx, (c.get("heading") or "条款")[:26]))
        _ppt_text(s, 0.6, 1.5, 2.2, 0.6, c.get("rating") or "", size=20, bold=True,
                  color=_ppt_rating_color(c.get("rating")))
        for j, (k, lab) in enumerate((("comment", "风险描述"), ("basis", "法律依据"), ("revised", "修改建议"))):
            _ppt_text(s, 0.6, 2.3 + j * 1.35, 2.0, 0.5, lab, size=14, bold=True, color="gold")
            _ppt_text(s, 2.7, 2.3 + j * 1.35, 10.0, 1.3, c.get(k) or "—", size=14)
    s = _ppt_slide(prs, "使用说明")
    _ppt_text(s, 0.6, 1.8, 12.1, 4.0,
              "· 本讲解版为报告的演示形态，完整逐条意见以 WORD/HTML 报告为准\n"
              "· 三色分级：★★★ 高风险 ／ ★★ 中风险 ／ ★ 低风险\n"
              "· 免责声明见每页页脚；引用法条以正式文本为准", size=16)

def _ppt_diff(prs, spec, ctx):
    rows, note = diff_rows(spec)
    _ppt_text(_ppt_slide(prs), 0.6, 2.2, 12.1, 1.0, title(spec) + " · 文件比对报告",
              size=36, bold=True, color="navy")
    _ppt_text(_ppt_slide(prs), 0.6, 1.5, 12.1, 0.8, note, size=16)
    for r in rows[:PPT_MAX_SLIDES - 4]:
        s = _ppt_slide(prs, "%s %s" % (r.get("loc") or "差异", r.get("kind") or ""))
        for j, (k, lab) in enumerate((("old", "原稿"), ("new", "对方稿"), ("hint", "提示"))):
            v = (r.get(k) or "").strip()
            if not v:
                continue
            _ppt_text(s, 0.6, 1.5 + j * 1.6, 1.6, 0.5, lab, size=14, bold=True, color="gold")
            _ppt_text(s, 2.3, 1.5 + j * 1.6, 10.4, 1.5, v[:200], size=13)

def _ppt_compare(prs, spec, ctx):
    _ppt_text(_ppt_slide(prs), 0.6, 2.2, 12.1, 1.0, title(spec) + " · 新旧比对",
              size=36, bold=True, color="navy")
    for c in clauses(spec)[:PPT_MAX_SLIDES - 4]:
        s = _ppt_slide(prs, (c.get("heading") or "条款")[:26])
        _ppt_text(s, 0.6, 1.5, 5.9, 4.6, "【原文】\n" + (c.get("original") or "—")[:260], size=13)
        _ppt_text(s, 6.9, 1.5, 5.9, 4.6, "【修改后】\n" + (c.get("revised") or "—")[:260], size=13)

PPT_GEN = {"report": _ppt_report, "diff": _ppt_diff, "compare": _ppt_compare}

def export_pptx(pairs, spec, outdir, ctx):
    """pairs: [(slug, tier)]。缺 python-pptx → 返回 None（上层照 openpyxl 模式提示跳过）。"""
    if not _PPTX_OK:
        return None
    made = []
    for t, tier in pairs:
        prs = _Presentation()          # 每类独立成册——共用 prs 会把前一类幻灯片带进后一册
        prs.slide_width = _In(13.333)
        prs.slide_height = _In(7.5)   # 16:9
        PPT_GEN[t](prs, spec, ctx)
        p = outname(t, "pptx", tier=tier, ctx=ctx)
        prs.save(os.path.join(outdir, p))
        made.append(p)
    return made


def summary_dir(outdir):
    """精要总结产物的隔离目录（v3.30.0）。**只提炼、不审查**——其产物若与审查交付物
    混放同一目录，归档/外发时分不清「总结件」与「审查件」，故物理隔离到 `_精要总结/`。"""
    d = os.path.join(outdir, "_精要总结")
    os.makedirs(d, exist_ok=True)
    return d


def export_summary_mindmap(outdir, title_txt, nodes, ctx, want_html=False, want_png=False):
    """精要总结入口的导图产出（v3.30.0）——**与交付物导图同一套渲染器**（mindmap_svg/html/png）。

    数据来源不同（这里吃「文档正文大纲」的节点树，不是审查规格），但呈现形态、视觉规范、
    截断规则全部复用交付物那三个函数——"同源"由代码保证，不只靠文档承诺
    （守卫 check_mindmap_single_source 断言本函数确实调用三者）。
    产物落 `_精要总结/` 子目录，文件名带 `_总结` 段，与审查件物理区分。
    """
    d = summary_dir(outdir)
    stem = "%s_精要总结导图_%s_r%s_%s" % (ctx.source, ctx.reviewer, ctx.round, ctx.ts)
    made = []
    s = stem + ".svg"
    open(os.path.join(d, s), "w", encoding="utf-8").write(mindmap_svg(title_txt, nodes))
    made.append(os.path.join("_精要总结", s))
    if want_html:
        h = stem + ".html"
        open(os.path.join(d, h), "w", encoding="utf-8").write(
            mindmap_html(title_txt, nodes, "summary", {"name": title_txt}, ctx))
        made.append(os.path.join("_精要总结", h))
    if want_png:
        p = stem + ".png"
        why = mindmap_png(title_txt, nodes, os.path.join(d, p))
        if why:
            print("[format-engine] 提示：精要总结导图 PNG 跳过（%s）。" % why)
        else:
            made.append(os.path.join("_精要总结", p))
    return made


def export_mindmap(pairs, spec, outdir, ctx, want_html=False, want_png=False,
                   want_pdf=False, want_opml=False, want_md=False):
    """pairs: [(slug, tier)]。v3.29.0 起默认出 SVG（零依赖）；--mindmap-html 追加折叠树 HTML；
    --mindmap-png 追加 PNG（老环境兜底，matplotlib 缺库/缺中文字体仅提示不阻断）。返回产出文件名列表。"""
    made = []
    for t, tier in pairs:
        root, nodes = mm_tree(t, spec)
        if not nodes:
            continue
        # 命名：在 slug 名称后插「思维导图」段，与正文 HTML 同目录不冲突
        # （outname 形如 {SOURCE}_{SLUG}{tier标记}_{REVIEWER}_r{ROUND}_{TS}.html；
        #   tier 标记以 - 开头、可能不存在，故按「SLUG 后第一处」插段最稳）
        base = outname(t, "html", tier=tier, ctx=ctx)
        head = "%s_%s" % (ctx.source, SLUGS[t])
        stem = base.replace(head, "%s_思维导图" % head, 1)[:-5]   # 去扩展名的公共主干
        s = stem + ".svg"
        open(os.path.join(outdir, s), "w", encoding="utf-8").write(mindmap_svg(root, nodes))
        made.append(s)
        if want_html:
            h = stem + ".html"
            open(os.path.join(outdir, h), "w", encoding="utf-8").write(mindmap_html(root, nodes, t, spec, ctx))
            made.append(h)
        if want_png:
            p = stem + ".png"
            why = mindmap_png(root, nodes, os.path.join(outdir, p))
            if why:
                print("[format-engine] 提示：思维导图 PNG 跳过（%s）。" % why)
            else:
                made.append(p)
        # v3.32.0：导图再添三态——PDF（LibreOffice 转 SVG，老环境兜底）、
        # OPML（outliner 通用交换格式，幕布/WorkFlowy/OmniOutliner 直接导入）、
        # MD 大纲（纯文本缩进大纲，任何编辑器可读，进 git diff 也友好）。
        # 三者都从同一棵 mm_tree 渲染——数据仍然只有一份，渲染器各管各的格式。
        if want_pdf:
            pdfname = stem + ".pdf"
            _why = _mm_to_pdf(os.path.join(outdir, stem + ".svg"), os.path.join(outdir, pdfname))
            if _why:
                print("[format-engine] 提示：思维导图 PDF 跳过（%s）。" % _why)
            else:
                made.append(pdfname)
        if want_opml:
            o = stem + ".opml"
            open(os.path.join(outdir, o), "w", encoding="utf-8").write(mindmap_opml(root, nodes))
            made.append(o)
        if want_md:
            m = stem + ".md"
            open(os.path.join(outdir, m), "w", encoding="utf-8").write(mindmap_md(root, nodes))
            made.append(m)
    return made


def mindmap_opml(root, nodes):
    """OPML 2.0 大纲（幕布/WorkFlowy/OmniOutliner 等通用交换格式）。

    纯字符串拼接、零依赖；text 属性须做 XML 转义（esc 只处理 &<>，引号在属性里也须转）。
    """
    def esc_attr(x):
        return esc(x).replace('"', "&quot;")
    def outline(nds, depth):
        out = []
        for n in nds:
            out.append('%s<outline text="%s">' % ("  " * depth, esc_attr(n["text"])))
            out.extend(outline(n["children"], depth + 1))
            out.append('%s</outline>' % ("  " * depth))
        return out
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<opml version="2.0">\n<head>\n<title>%s</title>\n</head>\n<body>\n%s\n</body>\n</opml>\n'
            % (esc_attr(root), "\n".join(outline(nodes, 1))))


def mindmap_md(root, nodes):
    """Markdown 缩进大纲（根为 H1，枝为 H2，叶为列表项）——任何编辑器可读、git diff 友好。"""
    out = ["# " + root, ""]
    for br in nodes:
        out.append("## " + br["text"])
        out.append("")
        for lf in br["children"]:
            out.append("- " + lf["text"])
        out.append("")
    return "\n".join(out) + "\n"


def _mm_to_pdf(svg_path, pdf_path):
    """SVG → PDF（LibreOffice 无头转换；与 docx→pdf 同一条链、同一套降级口径）。
    返回 "" 成功，否则返回跳过原因（不阻断主流程）。"""
    if not PDF_EXPORT:
        return "config.render.pdf_export=false"
    if _cfgmod and not _cfgmod.tool_available(_CFG, "soffice"):
        return "未检测到 LibreOffice"
    import subprocess
    try:
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf",
                            "--outdir", os.path.dirname(pdf_path), svg_path],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PDF_TIMEOUT)
        if r.returncode != 0:
            return "LibreOffice 返回码 %d" % r.returncode
    except Exception as e:  # noqa: BLE001
        return "转换失败：%s" % e
    return "" if os.path.exists(pdf_path) else "转换后未见产物"

# ---------- html 导出（10 类 × 网页浏览版 · 单文件） ----------
# 设计要点：
#   · **优先用 markdown 库**（表格、围栏代码等语法覆盖更全）；未安装则自动降级到内置
#     转换器 `_md_fallback`——降级不报错、不阻断出件，产物照样可用（缺库只影响极少数语法）。
#   · 产出**单文件网页**：CSS/JS 全内联，**零外部资源**，断网可开、可直接转发给别人。
#   · 交互三件套：顶部固定目录导航（锚点由**服务端**生成，不依赖 JS 也能跳转）、
#     点击标题折叠/展开条款、右上角打印（Ctrl+P 亦可；@media print 隐藏导航与按钮并排 A4 版心）。
#   · 评级符号 ★/★★/★★★ 着色为三色标签——色值与 SKILL.md 三色分级同一套（高红/中橙/低绿）。
try:
    import markdown as _mdlib
except Exception:
    _mdlib = None

_MD_EXT = ["tables", "fenced_code", "sane_lists", "nl2br"]
_SAFE_TAGS = ("ins", "del", "br", "span", "strong", "em", "code", "b", "i")


def _risk_spans(s):
    """评级符号 → 三色标签。在转 HTML **之前**做：raw HTML 会被 markdown 原样保留。"""
    def rep(m):
        n = len(m.group(0))
        cls = "r3" if n >= 3 else ("r2" if n == 2 else "r1")
        return '<span class="risk %s">%s</span>' % (cls, m.group(0))
    return re.sub(r"★+", rep, s)


def _esc_keep(s):
    """转义 < &，但放行白名单内联标签（<ins>/<del>/<br>/<span> 是 md 生成器有意写出的）。"""
    s = re.sub(r"&(?!#?\w+;)", "&amp;", s)
    s = re.sub(r"<(?!/?(?:%s)\b[^>]*>)" % "|".join(_SAFE_TAGS), "&lt;", s)
    return s


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _md_fallback(md):
    """内置 Markdown → HTML 转换器（markdown 库缺失时的降级通道）。

    只需覆盖本脚本自身 md 生成器会吐出的语法：ATX 标题、引用块、分隔线、管道表格、
    无序/有序列表、段落，以及行内 **粗体** / ~~删除线~~ / `代码` 与白名单内联标签。
    """
    def inline(s):
        s = _esc_keep(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s, flags=re.S)
        s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s, flags=re.S)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s.replace("\n", "<br>")

    def is_table_start(i, lines):
        if "|" not in lines[i] or i + 1 >= len(lines):
            return False
        return bool(re.match(r"^\s*\|?[\s:\-|]*-[\s:\-|]*$", lines[i + 1])) and "-" in lines[i + 1]

    out, i, lines = [], 0, md.splitlines()
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            out.append("<h%d>%s</h%d>" % (len(m.group(1)), inline(m.group(2)), len(m.group(1))))
            i += 1
            continue
        if re.match(r"^\s*(---+|\*\*\*+)\s*$", ln):
            out.append("<hr>")
            i += 1
            continue
        if ln.lstrip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline("\n".join(buf)))
            continue
        if is_table_start(i, lines):
            head = _split_row(lines[i])
            i += 2
            body = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                body.append(_split_row(lines[i]))
                i += 1
            th = "".join("<th>%s</th>" % inline(c) for c in head)
            tb = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in body)
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (th, tb))
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(t) for t in items))
            continue
        if re.match(r"^\s*\d+[.)]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]))
                i += 1
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(t) for t in items))
            continue
        buf = []
        while i < len(lines) and lines[i].strip():
            if re.match(r"^\s*(#{1,6}\s|>|[-*]\s|\d+[.)]\s)", lines[i]) or is_table_start(i, lines):
                break
            buf.append(lines[i])
            i += 1
        out.append("<p>%s</p>" % inline("\n".join(buf)))
    return "\n".join(out)


def md_to_html(md_text):
    """Markdown → HTML 正文片段。markdown 库可用则用之，否则降级内置转换器。"""
    src = _risk_spans(md_text)
    if _mdlib is not None:
        try:
            return _mdlib.markdown(src, extensions=_MD_EXT)
        except Exception as e:
            print("[format-engine] 提示：markdown 库转换失败（%s），改用内置转换器。" % e)
    return _md_fallback(src)


HTML_CSS = """
:root{--navy:#0b2038;--gold:#c9a24a;--fg:#1f2430;--fg2:#5a6478;--line:#e3e7ef;--bg:#f6f7fa}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);
     font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;
     font-size:15px;line-height:1.75}
.topbar{position:fixed;top:0;left:0;right:0;height:46px;z-index:50;display:flex;align-items:center;
        gap:10px;padding:0 14px;background:var(--navy);color:#fff;box-shadow:0 2px 10px rgba(0,0,0,.18)}
.topbar .brand{font-weight:700;letter-spacing:.3px;white-space:nowrap}
.topbar .brand em{font-style:normal;color:var(--gold)}
.toc{flex:1;overflow-x:auto;white-space:nowrap;scrollbar-width:thin}
.toc::-webkit-scrollbar{height:4px}
.toc::-webkit-scrollbar-thumb{background:rgba(255,255,255,.25);border-radius:4px}
.toc a{color:#cfd8e6;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:12px;
       display:inline-block}
.toc a:hover{background:rgba(255,255,255,.12);color:#fff}
.toc a.lv3{opacity:.82;font-size:12px}
.btn{background:var(--gold);color:#20180a;border:0;border-radius:14px;padding:5px 12px;
     font-size:13px;cursor:pointer;white-space:nowrap;font-family:inherit}
.btn.ghost{background:transparent;color:#cfd8e6;border:1px solid rgba(255,255,255,.35)}
.btn:hover{filter:brightness(1.06)}
.page{max-width:980px;margin:0 auto;padding:66px 22px 60px;background:#fff;min-height:100vh;
      box-shadow:0 0 0 1px var(--line)}
h1{font-size:25px;margin:6px 0 14px;padding-bottom:10px;border-bottom:2px solid var(--gold)}
h2{font-size:19px;margin:26px 0 10px;padding-left:10px;border-left:4px solid var(--gold);
   cursor:pointer;user-select:none}
h3{font-size:16px;margin:18px 0 8px;color:#33405a;cursor:pointer;user-select:none}
h2:hover,h3:hover{color:var(--gold)}
h2::after,h3::after{content:" ▾";font-size:12px;color:#9aa4b8}
h2.closed::after,h3.closed::after{content:" ▸"}
blockquote{margin:10px 0;padding:8px 12px;background:#fbfaf6;border-left:3px solid var(--gold);
           color:var(--fg2);font-size:13.5px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
th,td{border:1px solid var(--line);padding:7px 9px;vertical-align:top;text-align:left}
th{background:#f2f4f8;font-weight:600}
tbody tr:nth-child(even){background:#fcfcfe}
ul,ol{margin:8px 0 8px 22px;padding:0}
li{margin:3px 0}
code{background:#f2f4f8;padding:1px 5px;border-radius:4px;font-size:13px}
ins{background:#e6f6ec;color:#1c7a45;text-decoration:none}
del{background:#fdeceb;color:#b0302a}
.risk{display:inline-block;padding:0 7px;border-radius:10px;color:#fff;font-size:12.5px;
      line-height:1.6;letter-spacing:1px}
.risk.r3{background:#d8443c}.risk.r2{background:#e3a637}.risk.r1{background:#3e9b6b}
.foot{margin-top:34px;padding-top:12px;border-top:1px solid var(--line);color:#8b93a6;font-size:12.5px}
@media print{
  body{background:#fff;font-size:11pt}
  .topbar{display:none!important}
  .page{box-shadow:none;padding:0;max-width:none}
  h2::after,h3::after{content:""}
  @page{size:A4;margin:16mm}
}
@media (max-width:640px){.page{padding:60px 14px 40px}.topbar .brand{font-size:13px}}
"""

HTML_JS = """
(function(){
  var hs=[].slice.call(document.querySelectorAll('h2,h3'));
  hs.forEach(function(h){
    if(!h.id){h.id='s'+hs.indexOf(h);}
    h.addEventListener('click',function(){
      h.classList.toggle('closed');
      var show=!h.classList.contains('closed'), el=h.nextElementSibling;
      while(el && !/^H[23]$/.test(el.tagName)){ el.style.display=show?'':'none'; el=el.nextElementSibling; }
    });
  });
  var fold=document.getElementById('btn-fold'), exp=document.getElementById('btn-expand');
  function setAll(closed){
    hs.forEach(function(h){
      h.classList.toggle('closed',closed);
      var el=h.nextElementSibling;
      while(el && !/^H[23]$/.test(el.tagName)){ el.style.display=closed?'none':''; el=el.nextElementSibling; }
    });
  }
  if(fold) fold.onclick=function(){setAll(true)};
  if(exp) exp.onclick=function(){setAll(false)};
  var p=document.getElementById('btn-print'); if(p) p.onclick=function(){window.print()};
})();
"""


def html_page(slug, spec, body, ctx, online=False):
    """把正文片段包成单文件网页：**顶部固定目录导航 + 可折叠条款 + 打印按钮**。

    目录锚点在**服务端**生成（正则扫 h2/h3 后回填 id），所以即使浏览器禁用 JS，
    导航与跳转照样能用；JS 只负责折叠与打印。

    v3.28.0 在线增强版（online=True，须显式 --html-online）：在产物里挂 HTML_CDN_ALLOW
    白名单域的字体/渲染增强外链，文件更小、需联网；**核心交互（折叠/打印/目录）仍全部内联**，
    断网时页面照常可用，只是少了增强效果。默认 online=False——产物零外部资源，与 v3.27.0 逐字节一致。
    """
    toc = []

    def _mk(m):
        lv, inner = int(m.group(1)), m.group(2)
        if lv not in (2, 3):
            return m.group(0)
        idx = len(toc)
        toc.append((lv, re.sub(r"<[^>]+>", "", inner)))
        return '<h%d id="s%d">%s</h%d>' % (lv, idx, inner, lv)

    body = re.sub(r"<h([23])[^>]*>(.*?)</h\1>", _mk, body, flags=re.S)
    nav = "".join('<a class="lv%d" href="#s%d" title="%s">%s</a>'
                  % (lv, i, esc(t), (t[:14] + "…") if len(t) > 15 else t)
                  for i, (lv, t) in enumerate(toc))
    if not nav:
        nav = '<span style="color:#8b93a6;font-size:13px">（本类型无小节标题，无目录）</span>'
    doc_title = "%s · %s" % (title(spec), SLUGS.get(slug, slug))
    # 在线增强外链（仅 online=True）：字体走 Google Fonts，交互增强走 jsdelivr。
    # 注意 URL 一律字面量拼接——不得引入 URL 处理库做拼接（会命中 E0 的网络库清单）。
    cdn = ""
    banner = ""
    if online:
        cdn = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
               '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
               '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600&display=swap">'
               '<script src="https://cdn.jsdelivr.net/npm/anchor-js@5.0.0/anchor.min.js" defer></script>')
        banner = ('\n<style>.online-note{max-width:980px;margin:52px auto 0;padding:8px 14px;'
                  'background:#fbf6e9;border:1px solid var(--gold);color:#6b5a1e;'
                  'font-size:12.5px;border-radius:6px}</style>'
                  '<div class="online-note">在线增强版：字体与渲染脚本由 CDN 白名单（%s）加载，需联网；'
                  '断网时自动使用内联样式，内容不受影响。</div>' % "、".join(HTML_CDN_ALLOW))
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(t)s</title>
<style>%(css)s</style>%(cdn)s</head><body>
<div class="topbar">
  <span class="brand">文档合规审查助手 <em>%(slug)s</em></span>
  <nav class="toc">%(nav)s</nav>
  <button class="btn ghost" id="btn-fold">全部折叠</button>
  <button class="btn ghost" id="btn-expand">全部展开</button>
  <button class="btn" id="btn-print">打印 / 存 PDF</button>
</div>%(banner)s
<main class="page">
%(body)s
<div class="foot">%(meta)s　｜　本文件由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成最终法律意见；须人工复审核查后方可据此决策。</div>
</main>
<script>%(js)s</script>
</body></html>
""" % {"t": esc(doc_title), "css": HTML_CSS, "nav": nav, "slug": esc(SLUGS.get(slug, slug)),
       "body": body, "meta": esc(md_meta_line(slug, ctx)), "js": HTML_JS,
       "cdn": cdn, "banner": banner}