#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
"""
文档合规审查助手AI合同 · 交付物产出脚本（10 类型 × WORD/MD，统一命名）
===============================================================================
交付物类型（勾选框 · 多选，**一次全部显示供勾选**，产出前询问用户）：
  1) 修订版（首选）        2) 审查意见批注版      3) 修改后清洁版
  4) 红线修订格式版        5) 审查意见报告        6) 原文脱敏版
  7) 原文照录版            8) 文件比对报告        9) 新旧比对       10) 模板版
  · 未勾选时默认产出 1、2、3 三类（--types 可显式指定，亦可用中文类型名）。
  · 类型 1（修订版）：Word 原生修订痕迹（w:ins/w:del），可逐条接受/拒绝；
    **只标到改动的最小范围**——句读对齐后对改写块再做字符级细分，差异过大才整段替换。
    **给 --source-docx 时走原稿级修订**：在原稿既有 run 之间插痕迹，版式沿用原稿。
  · 类型 4（红线修订格式版）：粒度同 1，痕迹改用灰色删除线／红色下划线，不依赖 Word 修订功能。
    **给 --source-docx 时同样以原稿为底**（同一套定位逻辑，痕迹换成纯格式标记）。
  · 类型 2（批注版）：每条意见以 Word 批注锚定到对应条款；需 python-docx>=1.2，
    低版本自动降级为「意见附于条款之后」。`--comments` 为兼容保留的等价开关。
  · **不人为增加抬头（保持原版观感）**：1、3、4、6、7 五类＝还原原文的交付物，
    标题即原文标题（**不加「（修订模式）」等类型后缀**）、正文**不加「说明：…」段**；
    类型／审查人／轮次／时间写入 **docx 核心属性**（资源管理器右键「属性」即见）与文件名。
    1、4 另在标题上挂 **1 条「这是什么文件」批注 ＋ 每处修改 1 条意见批注**；
    3、6、7 **零批注**（可能对外发出或纯原文转录，不夹带内部审查意见）。
    报告类（2、5、8、9、10）是本技能新写的文书，标题与报告免责声明属文书固有内容，不适用此节。
  · 类型 8（文件比对报告）：比对**两份文件 / 两个版本**（如对方回稿 ↔ 我方上版），
    输入 spec.compare{a_text,b_text,a_label,b_label}，或命令行 --cmp-a/--cmp-b 指定文本文件；
    未提供两份全文时，自动降级为「条款级变更台账」（原文 ↔ 修改后）。
  · 类型 9（新旧比对）：同一份文档的改前/改后条款级左右对照表。
  · 类型 10（模板版）：由「撰写合同模板」与「转模板」两条链路产出——
    占位符说明表 ＋ 模板正文 ＋ 可选条款区（逐条挂批注）＋ 使用须知；spec.template 见下方字段说明。
    占位符一旦填实即成为具体合同，须经执业律师复核。

文件格式（--formats，逗号分隔）：
  docx   —— Word
  md     —— Markdown
  excel  —— Excel（openpyxl；比对/报告/照录/脱敏/清洁均有对应工作面）
  pdf    —— PDF（由已生成的 docx 经 LibreOffice 无头转换；`render.pdf_export=false` 可关闭）
  html   —— 网页浏览版（**单文件、零外部资源**：CSS/JS 全内联，断网可开、可直接转发）
           · 顶部固定目录导航（锚点服务端生成，禁用 JS 也能跳）、点击标题折叠/展开条款、
             右上角「打印 / 存 PDF」（@media print 已排 A4 版心并隐藏导航与按钮）；
           · 由 md 转换；**优先用 markdown 库**，未安装则自动降级内置转换器（不报错、不阻断）；
           · 评级 ★/★★/★★★ 着色为三色标签（高红／中橙／低绿，与三色分级同一套色值）。

排版样式档位（--style，或 spec.style、config.json 的 render.style）：
  default  —— 不改动版式（保持既有的不居中、不缩进）
  contract —— 合同风（**默认**）：文档标题居中、条款标题加粗不缩进、正文首行缩进 2 字符、行距 1.5
  official —— 公文风：标题居中二号、正文三号首行缩进
  · 只对 **1、3、4、6、7** 五类（要还原原文观感的交付物）生效；报告类 2、5、8、9、10 本就是新写文档，不套用。
  · 说明：10 类 docx 均按 spec 重建、不读原文档格式（扫描件/OCR/粘贴文本亦无格式可继承），
    故以「按文本特征推断段落角色 ＋ 样式档位」补齐版式，而非还原原稿。

审查人：**必填**，不填不产出（写死）；写入文件名 `<审查人>` 字段，并作为 Word 真实修订的修订者（w:author）。读取顺序：--reviewer > spec.reviewer > 环境变量 REVIEWER；仍为空时，交互终端将现场追问，否则报错退出（纯自动化可用 --reviewer "AI 文档合规审查助手"）。

工具路径与默认工作目录由 `scripts/config.json` 提供（见 `_config.py`）；命令行参数优先。

用法：
  python make-docx.py spec.json --reviewer 胡皓 [--out D:\某目录] [--subdir 采购合同A] [--types ...] [--formats docx,md,excel,pdf,html] [--cmp-a 旧版.txt --cmp-b 新版.txt] [--ts ...]
  默认输出目录：<工作根目录>\输出（工作根目录按候选链自动探测，见 set-workdir.py；
                可用 --out 覆盖；--subdir 建子文件夹）
  （--ts 建议由 AI 传入准确时间，勿依赖本机时钟）
  --types 可用 slug（tracked/redline/clean/report/reportc/masked/original/diff/compare/template）或中文类型名。
  --source-docx <原稿.docx>：半档C 排版保真，对 1修订版/3清洁版/4红线版/6脱敏版/7照录版 生效；
                             1、4 在原稿既有 run 之间插修订痕迹（w:ins/w:del 或红线格式），
                             3、6、7 只做段落级替换文字；均保留原稿版式。
                             原稿不可用或条款定位不到则自动回退样式档位，并按降级口径标注。
spec.json 关键字段：
  name / source / report_title / disclaimer / reviewer / round
  clauses[]: heading / original / revised / rating / basis / comment
  original_text（可选）：原文照录版/原文脱敏版 需要（全文文本）
  compare{a_label,a_text,b_label,b_text}（可选）：文件比对报告 需要（两份全文）
  template{name,placeholders[],body,optional[],notes}（可选）：模板版 需要（转模板 / 撰写模板）
依赖：python-docx（>=1.2，支持批注）；openpyxl（Excel 导出）；LibreOffice（PDF 导出，可选）；
      markdown（HTML 导出，可选——缺失时自动降级内置转换器，HTML 照样出）。
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
import os, re, sys, json, argparse, datetime, random, difflib, copy, unicodedata
from docx import Document
from docx.shared import RGBColor, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import desensitize as _d
except Exception:
    _d = None
try:
    import _config as _cfgmod
    _CFG = _cfgmod.load()
except Exception:
    _cfgmod = None
    _CFG = {}

BASE_DIR = (_cfgmod.workdir(_CFG, "base_dir") if _cfgmod
            else os.path.join(os.path.expanduser("~"), "文档合规审查报告"))
IN_DIR   = os.path.join(BASE_DIR, "输入")
OUT_DIR  = (_cfgmod.workdir(_CFG, "out_dir") if _cfgmod else "") or os.path.join(BASE_DIR, "输出")
SOFFICE  = (_cfgmod.tool(_CFG, "soffice") if _cfgmod else "soffice")
PDF_EXPORT = (bool(_cfgmod.render_opt(_CFG, "pdf_export")) if _cfgmod else True)
PDF_TIMEOUT = (int(_cfgmod.render_opt(_CFG, "pdf_timeout_sec") or 180) if _cfgmod else 180)

REVIEWER = ""; ROUND = "1"; TS = ""; SOURCE = "contract"
SLUGS = {
    "tracked":  "修订版",
    "reportc":  "审查意见批注版",
    "clean":    "修改后清洁版",
    "redline":  "红线修订格式版",
    "report":   "审查意见报告",
    "masked":   "原文脱敏版",
    "original": "原文照录版",
    "diff":     "文件比对报告",
    "compare":  "新旧比对",
    "template": "模板版",
}
# 10 类交付物（勾选框 · 多选，一次全部显示供勾选；顺序即清单排列顺序）
# 1/2/3 为最常用三类，故置于最前；10 模板版由「撰写合同模板」与「转模板」两条链路产出
TYPE_ORDER = ["tracked", "reportc", "clean", "redline", "report",
              "masked", "original", "diff", "compare", "template"]
# 用户未勾选时的默认产出：1 修订版 / 2 审查意见批注版 / 3 修改后清洁版
DEFAULT_TYPES = ["tracked", "reportc", "clean"]
# 原文脱敏版默认 **12 类全脱**（含信用代码/金额/地址/人名；比例不脱）。
# 真源＝desensitize.py 的 ALL_TYPES，此处直接取用，避免两处各写一份而漂移。
MASK_TYPES = (_d.ALL_TYPES.split(",") if _d is not None
              else ["idcard", "phone", "bank", "email", "postcode", "im",
                    "uscc", "amount", "addr", "name"])

# 文件比对报告：变更内容命中以下词时，提示"涉实质条款、建议复核"
DIFF_KEY_TERMS = ["赔偿", "责任", "违约金", "定金", "付款", "支付", "价款", "价格", "税率", "发票",
                  "期限", "交付", "验收", "质量", "管辖", "仲裁", "诉讼", "保密", "知识产权",
                  "数据", "个人信息", "解除", "终止", "担保", "保证", "质保金", "转让", "独家"]

# ---------- 排版保真 · B 档：样式档位 ＋ 段落角色推断 ----------
# 背景：9 类 docx 均按 spec 从零重建，不读原文档格式，故居中/缩进/段间距必然丢失
# （扫描件、OCR、粘贴文本更无格式可继承）。B 档不改提取链路与 spec 约定，只在生成时
# 按文本特征推断段落角色并套用样式档位，使 1、3、4、6、7 五类具备可读版式。
# 报告类 2、5、8、9、10 本就是新写文档，无"原排版"概念，不套用。
STYLE_ORDER = ["default", "contract", "official"]
STYLE_PRESETS = {
    # default＝保持既有行为，供不需要改版式的场景使用
    "default": {"title_center": False, "title_size": None, "clause_bold": True,
                "body_indent": False, "body_size": None,
                "line_spacing": None, "space_before": None, "sign_right": False},
    # contract＝合同风（默认）：标题居中、条款标题加粗不缩进、正文首行缩进 2 字符
    "contract": {"title_center": True, "title_size": 16, "clause_bold": True,
                 "body_indent": True, "body_size": 12,
                 "line_spacing": 1.5, "space_before": 6, "sign_right": True},
    # official＝公文风：标题二号居中、正文三号首行缩进
    "official": {"title_center": True, "title_size": 22, "clause_bold": True,
                 "body_indent": True, "body_size": 16,
                 "line_spacing": 1.5, "space_before": 6, "sign_right": True},
}
STYLE = "contract"   # 由 --style / spec.style / config.render.style 覆盖

_ROLE_CLAUSE = re.compile(r"^(第[一二三四五六七八九十百千零〇\d]+条|[一二三四五六七八九十]+[、．.])")
_ROLE_NUM = re.compile(r"^\d+(\.\d+)*[、．.\s]")
_ROLE_SIGN = re.compile(r"(甲方|乙方|丙方|丁方|签署|签章|盖章|签字|日期|年月日)")

def set_style(name):
    """设置样式档位；无法识别的名称一律忽略（回落当前值）。"""
    global STYLE
    v = (str(name).strip().lower() if name else "")
    if v in STYLE_PRESETS:
        STYLE = v

def para_role(text, is_first=False):
    """按文本特征推断段落角色（命中即止）：doc_title / clause / num_title / sign / body。"""
    t = (text or "").strip()
    if not t:
        return "body"
    if is_first and len(t) <= 30 and not t.endswith(("。", "；", "！", "？", ".", "!", "?")):
        return "doc_title"
    if _ROLE_CLAUSE.match(t):
        return "clause"
    if _ROLE_NUM.match(t) and len(t) <= 40:
        return "num_title"
    if len(t) <= 20 and _ROLE_SIGN.search(t):
        return "sign"
    return "body"

def apply_role(p, role):
    """把样式档位套到段落。只设段落级属性与整段字号，**不覆盖 run 级既有格式**
    （红线版的删除线/下划线颜色、修订版的 w:ins/w:del 均不受影响）。"""
    s = STYLE_PRESETS[STYLE]
    pf = p.paragraph_format
    if s["space_before"]:
        pf.space_before = Pt(s["space_before"])
    if s["line_spacing"]:
        pf.line_spacing = s["line_spacing"]
    if role == "doc_title":
        if s["title_center"]:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if s["title_size"]:
            for r in p.runs:
                r.font.size = Pt(s["title_size"])
    elif role in ("clause", "num_title"):
        pf.first_line_indent = Pt(0)
        pf.space_after = Pt(0)
        if s["clause_bold"]:
            for r in p.runs:
                r.bold = True
    elif role == "sign":
        if s["sign_right"]:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        if s["body_indent"]:
            pf.first_line_indent = Pt((s["body_size"] or 12) * 2)   # 首行缩进 2 字符
        if s["body_size"]:
            for r in p.runs:
                r.font.size = Pt(s["body_size"])
    return p

def add_title(doc, text):
    """文档标题：保留 Title 大纲级别，再按样式档位居中/放大。"""
    return apply_role(doc.add_heading(text or "", 0), "doc_title")

def add_report_title(doc, text):
    """报告型文书标题（2/5/8/9）：保留 Title 级字号与大纲级别，标题恒居中。

    报告类不套样式档位（正文不缩进、行距不动），但标题对齐属报告固有版式——
    Title 样式默认左对齐，不显式居中就没有抬头观感，与文档型标题观感也不一致。
    """
    p = doc.add_heading(text or "", 0)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    return p

def add_clause_title(doc, text):
    p = doc.add_paragraph(text or "")
    for r in p.runs:
        r.bold = True
    return apply_role(p, "clause")

def apply_text(doc, text, first=False):
    """按角色生成正文段落（原文照录版/脱敏版逐行调用）。"""
    return apply_role(doc.add_paragraph(text or ""), para_role(text, first))

def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def _rid(): return str(random.randint(100000, 999999))

def sanitize(name):
    s = re.sub(r"[\s]+", "-", (name or "contract").strip())
    s = re.sub(r"[\\/:*?\"<>|（）()【】\[\]·、,，]+", "", s)
    return s[:40] or "contract"

REV_SLUGS = ("tracked", "redline")      # 需要「在原稿上改」的两类（1 修订版 / 4 红线版）
REV_DEGRADED = {}                       # slug → 降级原因；由 DOC_GEN 生成时写入，供 outname 判定


def outname(slug, ext="docx"):
    """文件名＝源_类型_审查人_r轮次_时间.ext；降级件在类型后加「-降级」标记。

    降级标记是「原稿底稿硬性要求」三处标注之一（另两处：文档属性、报告"总体评估"），
    取的是本件是否降级，而非本轮是否降级——同一轮里 1 降级、3 以原稿做底是正常情形。
    """
    tag = ""
    if slug in REV_SLUGS and REV_DEGRADED.get(slug):
        # 部分落位（仍是原稿件）标「-降级-部分」，完全重建才标「-降级」
        tag = "-降级-部分" if REV_FALLBACK.get("hit") else "-降级"
    return f"{SOURCE}_{SLUGS[slug]}{tag}_{REVIEWER}_r{ROUND}_{TS}.{ext}"

def tracked_ins(p, text):
    p._p.append(parse_xml(f'<w:ins {nsdecls("w")} w:id="{_rid()}" w:author="{esc(REVIEWER)}" w:date="{now()}"><w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:ins>'))

def tracked_del(p, text):
    p._p.append(parse_xml(f'<w:del {nsdecls("w")} w:id="{_rid()}" w:author="{esc(REVIEWER)}" w:date="{now()}"><w:r><w:delText xml:space="preserve">{esc(text)}</w:delText></w:r></w:del>'))

# ---------- 细粒度修订：句读对齐 ＋ 块内字符级细分 ----------
_SUB_SPLIT = re.compile(r"([。；！？：，、\n])")


def _units(text):
    """按句读切成片段（标点保留在前一片末尾）——中文无词边界，句读是修订的自然粒度。"""
    parts = _SUB_SPLIT.split(text or "")
    us = []
    for i in range(0, len(parts) - 1, 2):
        piece, sep = parts[i], parts[i + 1]
        if piece or sep:
            us.append(piece + sep)
    if parts and parts[-1]:
        us.append(parts[-1])
    return us


def _tokenize(s):
    """把字符串切成「不可再切」的最小单元：数字串（含千分位/小数/百分号）与英文单词各算一个。

    不这么做就会出「30% → 20%」被切成「删 3 / 增 20…4 / 留 0%」这种碎渣式修订——
    显示出来是「320%」，审阅者得逐片接受，人看着累也容易看漏。中文按字切即可（无词边界）。
    """
    return re.findall(
        r"\d{4}\s*年\s*(?:\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
        r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
        r"|\d[\d,.]*%?"
        r"|[A-Za-z]+(?:['-][A-Za-z]+)*"
        r"|.", s or "")


def _char_ops(a, b):
    """字符级 diff：把一段「整体改写」拆到改动的最小范围（数字与英文词不切开）。"""
    ta, tb = _tokenize(a), _tokenize(b)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(("equal", "".join(ta[i1:i2])))
        elif tag == "delete":
            ops.append(("delete", "".join(ta[i1:i2])))
        elif tag == "insert":
            ops.append(("insert", "".join(tb[j1:j2])))
        else:
            if ta[i1:i2]:
                ops.append(("delete", "".join(ta[i1:i2])))
            if tb[j1:j2]:
                ops.append(("insert", "".join(tb[j1:j2])))
    return ops


def _merge_ops(ops):
    out = []
    for tag, txt in ops:
        if not txt:
            continue
        if out and out[-1][0] == tag:
            out[-1] = (tag, out[-1][1] + txt)
        else:
            out.append((tag, txt))
    return out


def inline_diff(old, new, thr=0.4, max_ops=80):
    """原文→修改后 的差异序列 [(equal|delete|insert, text)]，供修订版与红线版渲染。

    两级比对：先按句读对齐（改动往往只在一两处，其余须原样保留），
    再对"整句被替换"的块降到字符级——这是"只改了某处却整段显示为改动"的根因：
    旧实现一旦发现条款文本不同就整段 del＋ins。
    差异过大（相似度 < thr）或碎片过多（> max_ops，审阅时会难以逐条处理）时
    退化为整段替换，保证可读性优先于极细粒度。
    """
    old, new = old or "", new or ""
    if not old:
        return [("insert", new)] if new else []
    if not new:
        return [("delete", old)]
    if old == new:
        return [("equal", old)]
    if difflib.SequenceMatcher(None, old, new, autojunk=False).ratio() < thr:
        return [("delete", old), ("insert", new)]
    ao, bo = _units(old), _units(new)
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ao, bo, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(("equal", "".join(ao[i1:i2])))
        elif tag == "delete":
            ops.append(("delete", "".join(ao[i1:i2])))
        elif tag == "insert":
            ops.append(("insert", "".join(bo[j1:j2])))
        else:
            A, B = "".join(ao[i1:i2]), "".join(bo[j1:j2])
            if not A:
                ops.append(("insert", B))
            elif not B:
                ops.append(("delete", A))
            elif difflib.SequenceMatcher(None, A, B, autojunk=False).ratio() < thr:
                ops.append(("delete", A)); ops.append(("insert", B))
            else:
                ops.extend(_char_ops(A, B))
    ops = _merge_ops(ops)
    if len(ops) > max_ops:
        return [("delete", old), ("insert", new)]
    return ops


# ---------- 交付物说明：写进文档属性／批注，不占正文版面 ----------
def set_meta(doc, spec, slug, fallback=""):
    """类型／审查人／轮次／时间 → docx 核心属性（资源管理器右键属性即见，正文不留痕）。

    10 类一律写入（报告类的标准 applicable 对象不同，但同样不该在正文里重复元数据）。
    fallback 非空＝本件属「原稿底稿硬性要求」的降级产出，降级原因一并写进属性
    （文件名与报告"总体评估"两处由调用方负责，三处缺一不可）。
    """
    try:
        cp = doc.core_properties
        if slug in ("report", "reportc"):
            t = spec.get("report_title") or "文档合规审查意见报告"
        elif slug == "template":
            t = template_spec(spec).get("name") or (title(spec) + "（模板版）")
        elif slug in ("compare", "diff"):
            t = "%s（%s）" % (title(spec), SLUGS.get(slug, slug))
        else:
            t = title(spec)
        cp.title = t
        cp.author = REVIEWER or "AI 文档合规审查助手"
        cp.category = SLUGS.get(slug, slug)
        cp.keywords = "%s; %s; r%s" % (SLUGS.get(slug, slug), REVIEWER, ROUND)
        cp.comments = ("交付物类型：%s ｜ 审查人：%s ｜ 轮次：r%s ｜ 生成时间：%s"
                       % (SLUGS.get(slug, slug), REVIEWER, ROUND, TS))
        if fallback:
            # 两种降级不能混为一谈：完全没落到原稿（重建）vs 部分条款没落位（仍是原稿件）
            if REV_FALLBACK.get("hit"):
                cp.comments += ("\n⚠ 降级（部分）：本件已在原稿上改，但%s——补全原稿或核对条款标题后可重跑"
                                % fallback)
            else:
                cp.comments += ("\n⚠ 降级：非原稿修改（原因：%s）——补交可编辑原稿 .docx 后可重跑获得原稿级修改"
                                % fallback)
    except Exception:
        pass
    return doc


DELIVERY_NOTE = {
    "tracked": "本文件为《{t}》的修订版：删除线是原文、下划线是修改后文本，可在 Word/WPS「审阅」中逐条接受或拒绝。",
    "redline": "本文件为《{t}》的红线修订格式版：灰色删除线是原文、红色下划线是修改后文本，不依赖 Word 修订功能。",
    "template": "本文件为《{t}》的模板版：{{ }} 占位符须逐项填写，可选条款区按本次交易情形取舍；"
                "占位符一旦填实即成为具体合同，须经执业律师复核后方可使用。",
}


def can_comment(doc):
    return hasattr(doc, "add_comment") and hasattr(doc, "comments")


def add_delivery_note(doc, runs, slug, spec=None):
    """标题上挂 1 条「这是什么文件」批注；批注不可用则静默跳过（不落到正文）。"""
    tpl = DELIVERY_NOTE.get(slug)
    if not tpl or not runs or not can_comment(doc):
        return False
    txt = tpl.format(t=title(spec)) + "\n审查人：%s ｜ 轮次：r%s" % (REVIEWER, ROUND)
    try:
        doc.add_comment(runs, text=txt, author=REVIEWER or "AI 文档合规审查助手",
                        initials=(REVIEWER or "AI")[:3])
        return True
    except Exception:
        return False


def add_clause_note(doc, runs, c):
    """条款标题上挂 1 条审查意见批注；无实质意见时不挂。

    锚点只能取条款标题：修订版的正文文字都在 w:ins／w:del 里，取不到可锚定的 run。
    """
    if not runs or not can_comment(doc):
        return False
    if not (c.get("rating") or c.get("comment") or c.get("basis") or c.get("revised")):
        return False
    txt = ("【%s】%s\n法律依据：%s\n修改建议：%s"
           % (c.get("rating") or "—", c.get("comment") or "—",
              c.get("basis") or "—", c.get("revised") or "—"))
    try:
        doc.add_comment(runs, text=txt, author=REVIEWER or "AI 文档合规审查助手",
                        initials=(REVIEWER or "AI")[:3])
        return True
    except Exception:
        return False


def render_diff_runs(p, o, v, kind):
    """把差异序列渲到一个段落：tracked=Word 原生修订，redline=删除线/下划线。"""
    for tag, txt in inline_diff(o, v):
        if tag == "equal":
            p.add_run(txt)
        elif tag == "delete":
            if kind == "tracked":
                tracked_del(p, txt)
            else:
                r = p.add_run(txt); r.font.strike = True; r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        else:
            if kind == "tracked":
                tracked_ins(p, txt)
            else:
                r = p.add_run(txt); r.font.underline = True; r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    return p

DISCLAIMER_REPORT = ("本报告仅基于所提供文档之文本字面表述和当事人表述以及需求，进行理解与风险提示，"
                     "不代表对交易背景、履约事实或商业安排的确认，所引法条、判例、法院名称、标准号、示范文本及链接"
                     "请以现行有效版本为准，使用者应自行核验其真实性与现行有效性。")
DISCLAIMER_USAGE = ("免责声明：AI不能替代人工，人工不能依赖AI，个人仅限研究、学习、交流、体验自用，商业使用须获作者书面授权；本技能仅作为辅助法律工作，不构成法律意见，不可直接作为决策依据；条文检索与适用要件呈现仅为法律信息提供，不预测案件结果、不判断具体情形是否成立；"
                    "输出内容须经执业律师复核后方可使用；使用风险与后果由使用者自行承担。"
                    "使用即为已知晓后果并免责作者，否则，请勿使用！")


def add_disclaimer(doc, spec):
    """报告头部固定免责声明：**报告专属段 ＋ 使用免责声明全文**（两段并存，缺一不可）。

    报告段可用 spec.disclaimer 覆盖；使用免责声明为固定全文，不可按调用方覆盖。
    """
    d = spec.get("disclaimer") or DISCLAIMER_REPORT
    r = doc.add_paragraph().add_run("免责声明：" + d); r.italic = True; r.font.size = Pt(9)
    r2 = doc.add_paragraph().add_run(DISCLAIMER_USAGE); r2.italic = True; r2.font.size = Pt(9)

def clauses(spec): return spec.get("clauses", [])
def title(spec): return spec.get("name", "合同")

# ---------- 第 10 类「模板版」：撰写合同模板（见 drafting-guide.md）与 转模板（第十七节）两条链路共用 ----------
# spec.template 结构（全部可选，缺哪一项就少哪一节，不会报错）：
#   {"name": "模板名称",
#    "placeholders": [{"name": "{{甲方全称}}", "meaning": "…", "example": "…", "required": true}],
#    "body": "模板正文全文（含占位符）",
#    "optional": [{"name": "竞业限制", "scene": "…", "advice": "…"}],
#    "notes": "使用须知"}
def template_spec(spec):
    """读 spec.template；缺省时退化为「用条款拼一份骨架」，保证任何 spec 都能出件。"""
    t = spec.get("template")
    t = t if isinstance(t, dict) else {}
    body = (t.get("body") or "").strip()
    if not body and clauses(spec):
        parts = []
        for c in clauses(spec):
            h = (c.get("heading") or "").strip()
            b = (c.get("revised") or c.get("original") or "").strip()
            parts.append((h + "\n" + b) if h else b)
        body = "\n\n".join([p for p in parts if p.strip()])
    return {"name": (t.get("name") or "").strip(),
            "placeholders": [p for p in (t.get("placeholders") or []) if isinstance(p, dict)],
            "body": body,
            "optional": [o for o in (t.get("optional") or []) if isinstance(o, dict)],
            "notes": (t.get("notes") or "").strip()}


def template_name(spec):
    return template_spec(spec)["name"] or (title(spec) + "（模板版）")


def add_template_note(doc, runs, text):
    """模板版专用批注：可选条款上挂「适用场景／取舍建议」，正文不留痕。"""
    if not runs or not can_comment(doc):
        return False
    try:
        doc.add_comment(runs, text=text, author=REVIEWER or "AI 文档合规审查助手",
                        initials=(REVIEWER or "AI")[:3])
        return True
    except Exception:
        return False

# ---------- docx 生成 ----------
def doc_trackchanges(spec):
    """1 修订版：标题保持原文标题，说明进文档属性＋批注，修订只标到改动的最小范围。

    有原稿 .docx 时走**原稿级修订**（在既有 run 之间插 w:ins/w:del，版式沿用原稿）；
    做不到则回退样式档位重建，并按「原稿底稿硬性要求」显式降级标注。
    """
    _sd = from_source_docx_rev(spec, "tracked")
    if _sd is not None:
        return set_meta(_sd, spec, "tracked", fallback=REV_FALLBACK["reason"])
    doc = Document(); h0 = add_title(doc, title(spec))
    set_meta(doc, spec, "tracked", fallback=REV_FALLBACK["reason"])
    add_delivery_note(doc, h0.runs[:1], "tracked", spec)
    for c in clauses(spec):
        h = add_clause_title(doc, c.get("heading", ""))
        o = c.get("original", ""); v = c.get("revised", "")
        changed = bool(v) and v != o
        p = apply_role(doc.add_paragraph(), "body")
        if changed:
            render_diff_runs(p, o, v, "tracked")
        else:
            p.add_run(o or v)
        add_clause_note(doc, h.runs, c)
    return doc

def doc_redline(spec):
    """4 红线修订格式版：同 tracked 的呈现口径，痕迹用删除线/下划线而非 Word 修订。

    有原稿 .docx 时同样走原稿级修订（痕迹是格式标记，不依赖 Word 修订功能）。
    """
    _sd = from_source_docx_rev(spec, "redline")
    if _sd is not None:
        return set_meta(_sd, spec, "redline", fallback=REV_FALLBACK["reason"])
    doc = Document(); h0 = add_title(doc, title(spec))
    set_meta(doc, spec, "redline", fallback=REV_FALLBACK["reason"])
    add_delivery_note(doc, h0.runs[:1], "redline", spec)
    for c in clauses(spec):
        h = add_clause_title(doc, c.get("heading", ""))
        o = c.get("original", ""); v = c.get("revised", "")
        changed = bool(v) and v != o
        p = apply_role(doc.add_paragraph(), "body")
        if changed:
            render_diff_runs(p, o, v, "redline")
        else:
            p.add_run(o or v)
        add_clause_note(doc, h.runs, c)
    return doc

def doc_clean(spec):
    """3 修改后清洁版：零批注（可能发对方），类型信息只进文档属性与文件名。"""
    _sd = from_source_docx(spec, "clean")
    if _sd is not None:
        return set_meta(_sd, spec, "clean")
    doc = Document(); add_title(doc, title(spec))
    set_meta(doc, spec, "clean")
    for c in clauses(spec):
        add_clause_title(doc, c.get("heading", ""))
        apply_role(doc.add_paragraph(c.get("revised") or c.get("original") or ""), "body")
    return doc

def doc_report(spec):
    doc = Document(); add_report_title(doc, spec.get("report_title", "文档合规审查意见报告"))
    set_meta(doc, spec, "report")
    add_disclaimer(doc, spec); doc.add_paragraph("源文件：" + title(spec) + "　审查人：" + REVIEWER + "　轮次：r" + ROUND)
    for i, c in enumerate(clauses(spec), 1):
        h = doc.add_heading(f"{i}. {c.get('heading','')}", level=2)
        rt = c.get("rating", "")
        if rt:
            r = h.add_run("  " + rt); r.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)  # 星级红色
        doc.add_paragraph("风险描述：" + (c.get("comment", "") or "—"))
        doc.add_paragraph("法律依据：" + (c.get("basis", "") or "—"))
        doc.add_paragraph("修改建议（可直接采用的条款文本）：" + (c.get("revised", "") or "—"))
    return doc

def doc_report_comments(spec):
    """审查意见报告·批注版：正文保持原条款，意见以 Word 批注锚定到对应条款（需 python-docx>=1.2）。"""
    doc = Document()
    add_report_title(doc, spec.get("report_title", "文档合规审查意见报告") + "（批注版）")
    set_meta(doc, spec, "reportc")
    add_disclaimer(doc, spec)
    doc.add_paragraph("源文件：" + title(spec) + "　审查人：" + REVIEWER + "　轮次：r" + ROUND)
    _ok_cm = can_comment(doc)   # 注意：局部变量不得叫 can_comment（会遮蔽同名函数）
    if not _ok_cm:
        doc.add_paragraph("提示：当前 python-docx 版本不支持批注（需 >=1.2），已降级为「意见附于条款之后」的呈现方式。")
    for i, c in enumerate(clauses(spec), 1):
        # 条款标题（批注锚点）
        h = doc.add_heading(f"{i}. {c.get('heading','')}", level=2)
        if c.get("rating"):
            r = h.add_run("  " + c.get("rating")); r.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)
        if c.get("original"):
            p = doc.add_paragraph(); p.add_run("原文：").bold = True; p.add_run(c.get("original", ""))
        if c.get("revised"):
            p = doc.add_paragraph(); p.add_run("修改后：").bold = True; p.add_run(c.get("revised", ""))
        note = (f"【评级】{c.get('rating') or '—'}\n"
                f"【风险描述】{c.get('comment') or '—'}\n"
                f"【法律依据】{c.get('basis') or '—'}\n"
                f"【修改建议】{c.get('revised') or '—'}")
        if _ok_cm:
            try:
                doc.add_comment(h.runs, text=note, author=REVIEWER or "AI 文档合规审查助手",
                                initials=(REVIEWER or "AI")[:3])
            except Exception:
                doc.add_paragraph("批注内容：" + note.replace("\n", " "))
        else:
            doc.add_paragraph("批注内容：" + note.replace("\n", " "))
    return doc


def doc_compare(spec):
    doc = Document(); add_report_title(doc, title(spec) + "（新旧比对）")
    set_meta(doc, spec, "compare")
    t = doc.add_table(rows=1, cols=3); t.style = "Table Grid"
    h = t.rows[0].cells; h[0].text = "条款"; h[1].text = "原文"; h[2].text = "修改后"
    for c in clauses(spec):
        r = t.add_row().cells; r[0].text = c.get("heading", ""); r[1].text = c.get("original", ""); r[2].text = c.get("revised", "")
    return doc

# ---------- 文件比对报告（两份文件 / 两个版本的差异台账） ----------
def _cmp_texts(spec):
    c = spec.get("compare") or {}
    a = c.get("a_text") or spec.get("compare_a_text") or ""
    b = c.get("b_text") or spec.get("compare_b_text") or ""
    la = c.get("a_label") or spec.get("compare_a_label") or "旧版"
    lb = c.get("b_label") or spec.get("compare_b_label") or "新版"
    return a, b, la, lb

def _diff_hint(text):
    hits = [k for k in DIFF_KEY_TERMS if k in (text or "")]
    return ("涉实质条款（%s），建议复核" % "、".join(hits[:4])) if hits else "建议核对上下文"

def _sim(a, b):
    if not a or not b:
        return ""
    return "%.0f%%" % (difflib.SequenceMatcher(None, a, b).ratio() * 100)

def _drow(no, kind, loc, old, new):
    old = (old or "").strip(); new = (new or "").strip()
    return {"no": str(no), "loc": loc, "kind": kind, "sim": _sim(old, new),
            "old": old or "—", "new": new or "—", "hint": _diff_hint(old + new)}

def _pair_replace(al, bl, i1, i2, j1, j2, thr=0.55):
    """替换块内按相似度配对：≥阈值视为「修改」，配不上的分别记为「删除」/「新增」。

    解决逐行比对把整段无完全相同行的文本并成一条「修改」的问题——
    合同文本常整段改写，需拆成可逐条核对的差异项。
    """
    news = list(range(j1, j2)); used = set(); pairs = []
    for oi in range(i1, i2):
        best, br = None, thr
        for nj in news:
            if nj in used:
                continue
            r = difflib.SequenceMatcher(None, al[oi], bl[nj]).ratio()
            if r >= br:
                best, br = nj, r
        if best is None:
            pairs.append((oi, None))
        else:
            used.add(best); pairs.append((oi, best))
    for nj in news:
        if nj not in used:
            pairs.append((None, nj))
    pairs.sort(key=lambda p: (p[0] if p[0] is not None else 10 ** 9,
                              p[1] if p[1] is not None else 10 ** 9))
    return pairs

def diff_rows(spec):
    """差异台账。返回 (rows, note)；rows 项含 no/loc/kind/sim/old/new/hint。

    优先按两份全文（spec.compare.a_text/b_text）逐行比对；
    未提供全文时降级为条款级变更台账（原文 ↔ 修改后），保证该类型始终可产出。
    """
    a, b, la, lb = _cmp_texts(spec)
    rows = []
    if a.strip() or b.strip():
        al, bl = a.splitlines(), b.splitlines()
        sm = difflib.SequenceMatcher(None, al, bl)
        n = 0
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if tag == "insert":
                for j in range(j1, j2):
                    n += 1; rows.append(_drow(n, "新增", f"{lb} 第 {j + 1} 行", "", bl[j]))
            elif tag == "delete":
                for i in range(i1, i2):
                    n += 1; rows.append(_drow(n, "删除", f"{la} 第 {i + 1} 行", al[i], ""))
            else:
                for oi, nj in _pair_replace(al, bl, i1, i2, j1, j2):
                    n += 1
                    if oi is None:
                        rows.append(_drow(n, "新增", f"{lb} 第 {nj + 1} 行", "", bl[nj]))
                    elif nj is None:
                        rows.append(_drow(n, "删除", f"{la} 第 {oi + 1} 行", al[oi], ""))
                    else:
                        rows.append(_drow(n, "修改",
                                          f"{la} 第 {oi + 1} 行 → {lb} 第 {nj + 1} 行",
                                          al[oi], bl[nj]))
        note = "数据来源：%s ↔ %s 全文逐行比对（difflib），共 %d 处差异。" % (la, lb, len(rows))
        if not rows:
            note += "两版文本经逐行比对无差异。"
        return rows, note
    for i, c in enumerate(clauses(spec), 1):
        o = (c.get("original") or "").strip(); v = (c.get("revised") or "").strip()
        if not o and not v:
            continue
        kind = "新增" if not o else ("删除" if not v else ("未变更" if o == v else "修改"))
        row = _drow(i, kind, c.get("heading") or "第 %d 条" % i, o, v)
        if kind == "未变更":
            row["hint"] = "无需处理"
        rows.append(row)
    return rows, "数据来源：未提供两份全文，已按条款级（原文 ↔ 修改后）生成变更台账。"

DIFF_HEADERS = ["序号", "差异定位", "变更类型", "相似度", "旧版内容", "新版内容", "影响提示"]
DIFF_KEYS = ("no", "loc", "kind", "sim", "old", "new", "hint")

def doc_diff(spec):
    rows, note = diff_rows(spec)
    doc = Document(); add_report_title(doc, title(spec) + "（文件比对报告）")
    set_meta(doc, spec, "diff")
    doc.add_paragraph(note)   # 数据来源与差异计数（实质信息；类型解释由文件名承担）
    t = doc.add_table(rows=1, cols=len(DIFF_HEADERS)); t.style = "Table Grid"
    for i, h in enumerate(DIFF_HEADERS):
        t.rows[0].cells[i].text = h
    for r in rows:
        cells = t.add_row().cells
        for i, k in enumerate(DIFF_KEYS):
            cells[i].text = r[k]
    return doc

def _original_text(spec):
    t = spec.get("original_text") or ""
    if not t and clauses(spec):
        t = "\n".join((c.get("heading", "") + "\n" + (c.get("original") or "")).strip() for c in clauses(spec))
    return t

# ---------- 半档 C：以原稿 docx 做底 ＋ 段落级替换（排版保真） ----------
# 只换文字、不增删段落：字体/字号/对齐/缩进/行距/页边距/页眉页脚/表格/图片全部沿用原稿。
# 适用于"不改段落数、只换文字"的三类：3清洁版 / 6脱敏版 / 7照录版。
SOURCE_DOCX = ""   # 由 --source-docx 或 spec.source_docx 注入；为空时走 B 档（样式档位重建）


def _has_drawing(run):
    """run 内是否含图形（图片/对象）——含图形的 run 不参与文字替换，避免丢图。"""
    try:
        from docx.oxml.ns import qn as _qn
        el = run._element
        for t in ("w:drawing", "w:pict", "w:object"):
            if el.findall(".//" + _qn(t)):
                return True
    except Exception:
        return False
    return False


def _replace_para_text(p, text):
    """替换段落文字但保留版式：段落属性不动，首个纯文本 run 的字符格式沿用。"""
    runs = [r for r in p.runs if not _has_drawing(r)]
    if not runs:
        p.add_run(text or "")
        return
    head = runs[0]
    for r in runs[1:]:
        r.text = ""
    head.text = text or ""


def _source_lines(spec, kind):
    """三类交付物的目标文本行：clean=改后条文、original=原文、masked=原文脱敏。"""
    if kind == "clean":
        lines = []
        for c in clauses(spec):
            h = (c.get("heading") or "").strip()
            if h:
                lines.append(h)
            lines.append((c.get("revised") or c.get("original") or "").strip())
        lines = [x for x in lines if x]
        return lines or [x for x in _original_text(spec).splitlines() if x.strip()]
    text = _original_text(spec)
    if kind == "masked" and _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    return [x for x in text.splitlines() if x.strip()]


def from_source_docx(spec, kind):
    """以原稿 docx 为底产出三类交付物；不可用（无原稿/非 docx/打开失败）时返回 None 走 B 档。"""
    path = SOURCE_DOCX or (spec.get("source_docx") or "")
    if not path or not str(path).lower().endswith(".docx") or not os.path.exists(path):
        return None
    try:
        doc = Document(path)
    except Exception as e:
        print("[make-docx] 半档C 回退：原稿打开失败（%s）" % e)
        return None
    lines = _source_lines(spec, kind)
    targets = list(doc.paragraphs)
    if not targets or not lines:
        return None
    n = min(len(lines), len(targets))
    for i in range(n):
        _replace_para_text(targets[i], lines[i])
    if len(lines) > len(targets):
        # 文本行多于原稿段落：余下并入末段（不新增段落 XML）
        tail = "\n".join(lines[len(targets):])
        _replace_para_text(targets[-1], lines[len(targets) - 1] + "\n" + tail)
    else:
        # 原稿段落多于文本行：多出的段落清空文字，保留结构
        for i in range(len(lines), len(targets)):
            _replace_para_text(targets[i], "")
        if len(lines) * 3 < len(targets):
            print("[make-docx] 半档C 提示：文本 %d 行远少于原稿 %d 段，末段起已留空——"
                  "请确认 spec 含全文条款（clauses）或 original_text，否则请去掉 --source-docx 走样式档位。"
                  % (len(lines), len(targets)))
    print("[make-docx] 半档C：以原稿做底替换 %d 段（文本 %d 行），版式沿用原稿 [%s]"
          % (len(targets), len(lines), os.path.basename(path)))
    return doc


# ---------- 半档 C 结束 ----------

# ---------- 半档 C·修订：以原稿做底注入修订痕迹（1 修订版 / 4 红线版） ----------
# 与上面「半档 C」的区别：那一档是**整段换字**（供 3/6/7），这一档是**在既有 run 之间插痕迹**
# （供 1/4）。前提是原稿段落与条款对得上：按 heading／原文片段定位；定位不到的逐处跳过，
# **绝不猜** —— 猜错会把修订痕迹打到不相干的条款上，比降级严重得多。
REV_FALLBACK = {"reason": "", "hit": 0, "miss": 0}   # 供主流程读取并在三处标注降级


def _rev_norm(s):
    """比对用归一：全半角、空白一律抹平，只留实质字符（原稿排版空格多，不归一会永远对不上）。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s\u3000]+", "", s)


def _rev_para_text(p):
    """段落可见文字：w:t 正常文字 ＋ w:delText 已删文字（防二次处理时偏移错位）。"""
    try:
        return "".join(t.text or "" for t in p._p.iter(qn("w:t")))
    except Exception:
        return p.text or ""


def _rev_plain_runs(p):
    """可参与改写的 run：排除图形、域、脚注引用、制表与换行（这些 run 动了会丢对象）。"""
    out = []
    for r in p.runs:
        el = r._element
        if any(el.findall(".//" + qn(t)) for t in
               ("w:drawing", "w:pict", "w:object", "w:fldChar", "w:instrText",
                "w:footnoteReference", "w:endnoteReference", "w:br", "w:tab")):
            continue
        if r.text:
            out.append(r)
    return out


def _rev_merge_runs(p):
    """run 合并预处理：同段落相邻纯文字 run 合为一个（保留首个 run 的字符格式）。

    Word 常把一句话切成多个 run（拼写检查、中英混排、格式微差）；不合并则插入位置碎裂、
    痕迹读数失真。返回合并掉的 run 数。
    """
    runs = _rev_plain_runs(p)
    if len(runs) < 2:
        return 0
    head = runs[0]
    for r in runs[1:]:
        head.text = (head.text or "") + (r.text or "")
        r._element.getparent().remove(r._element)
    return len(runs) - 1


def _rev_rpr(run):
    """取 run 字符格式（rPr 深拷贝），供新建 run 继承原样式。"""
    if run is None:
        return None
    rpr = run._element.find(qn("w:rPr"))
    return copy.deepcopy(rpr) if rpr is not None else None


def _rev_make_run(text, rpr, kind, tracked=True):
    """构造 run。

    tracked=True（修订版）：删除文字必须放 `<w:delText>` —— 这是 OOXML 规定，
    放 `w:t` 进 `<w:del>` 里 Word 会当成非法内容；
    tracked=False（红线版）：删除只是"打了个删除线的普通文字"，必须用 `w:t`，
    否则离开修订功能后这段字在 Word 里根本不显示。
    """
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = OxmlElement("w:delText" if (kind == "del" and tracked) else "w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    return r


def _rev_existing_ids(doc):
    """收集全文档已用的 w:id，避免新痕迹 id 与原稿已有修订撞号（撞号 Word 会静默合并）。"""
    used = set()
    for el in doc.element.body.iter():
        v = el.get(qn("w:id"))
        if v and v.lstrip("-").isdigit():
            used.add(int(v))
    return used


_REV_IDS = [set()]


def _rev_next_id():
    _REV_IDS[0].add(max(_REV_IDS[0] | {1000}) + 1)
    return max(_REV_IDS[0])


def _rev_write_para(p, ops, kind, author, date):
    """按 diff 结果重建段落内的 run 序列，段落属性（pPr）与样式一概不动。

    kind=tracked：新增包 `<w:ins>`、删除包 `<w:del>`（内为 `<w:delText>`）——Word 可逐条接受/拒绝；
    kind=redline：不生成修订标记，改为红字下划线／灰字删除线。
    返回痕迹处数。
    """
    runs = _rev_plain_runs(p)
    if not runs:
        return 0
    base = _rev_rpr(runs[0])
    # 原文逐字符 → 归属格式（"没改的字"尽量保持原样，中英混排不会整段变字体）
    flat = []
    for r in runs:
        rpr = _rev_rpr(r) or base
        for ch in r.text or "":
            flat.append((ch, rpr))
    for r in runs:
        r._element.getparent().remove(r._element)

    pend = []
    marks = [0]

    def flush():
        if not pend:
            return
        buf = []
        for txt, rpr, k in pend:
            if buf and buf[-1][2] == k and _rev_rpr_key(buf[-1][1]) == _rev_rpr_key(rpr):
                buf[-1] = (buf[-1][0] + txt, buf[-1][1], k)
            else:
                buf.append((txt, rpr, k))
        for txt, rpr, k in buf:
            el = _rev_make_run(txt, rpr, k, tracked=(kind == "tracked"))
            if kind == "tracked" and k in ("ins", "del"):
                wrap = OxmlElement("w:ins" if k == "ins" else "w:del")
                wrap.set(qn("w:id"), str(_rev_next_id()))
                wrap.set(qn("w:author"), author)
                wrap.set(qn("w:date"), date)
                wrap.append(el)
                p._p.append(wrap)
            else:
                p._p.append(el)
                if kind == "redline" and k in ("ins", "del"):
                    from docx.text.run import Run as _Run
                    _rev_style_mark(_Run(el, p), k)
        pend.clear()

    pos = 0
    for op, txt in ops:
        if op == "equal":
            for ch in txt:
                rpr = flat[pos][1] if pos < len(flat) else base
                pos += 1
                pend.append((ch, rpr, "keep"))
        elif op == "delete":
            rpr = flat[pos][1] if pos < len(flat) else base
            pos += len(txt)
            marks[0] += 1
            pend.append((txt, rpr, "del"))
        else:
            rpr = flat[pos][1] if pos < len(flat) else (flat[-1][1] if flat else base)
            marks[0] += 1
            pend.append((txt, rpr, "ins"))
        flush()
    flush()
    return marks[0]


def _rev_rpr_key(rpr):
    try:
        return etree.tostring(rpr) if rpr is not None else b""
    except Exception:
        return b""


def _rev_style_mark(run, kind):
    """红线版：删除→灰色删除线；新增→红色下划线（与既有红线版同色值）。"""
    try:
        if kind == "del":
            run.font.strike = True
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
        elif kind == "ins":
            run.font.underline = True
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    except Exception:
        pass


def _rev_all_paras(doc):
    """全文档段落（含表格内）——表格里的条款同样要能改。"""
    out = list(doc.paragraphs)
    for tb in doc.tables:
        for row in tb.rows:
            for cell in row.cells:
                out.extend(cell.paragraphs)
    return out


def _rev_locate(paras, c, start=0):
    """定位条款段落的索引：先标题精确等值，再标题包含，最后原文片段。

    返回 (index, mode)，找不到返回 (-1, None)。start 用于顺序前进，避免同一标题重复命中。
    **标题命中不算数**：标题对上但 original 不在该段时，视同没找到——否则修订痕迹会
    打到不相干的段落上（AI 给的 heading 常带前缀，如把前言当标题、把条款正文当 original）。
    """
    texts = [_rev_norm(_rev_para_text(p)) for p in paras]
    o = _rev_norm(c.get("original"))

    def _fits(i):
        if not o:
            return True
        return o[:40] in texts[i] if len(o) > 8 else True

    h = _rev_norm(c.get("heading"))
    if h:
        for i in range(start, len(texts)):
            if texts[i] == h and _fits(i):
                return i, "heading"
        for i in range(start, len(texts)):
            if texts[i] and h in texts[i] and _fits(i):
                return i, "heading~"
    if len(o) >= 8:
        probe = o[:24]
        for i in range(start, len(texts)):
            if probe and probe in texts[i]:
                return i, "fragment"
    # 标题/片段都对不上，但标题段存在 → 仍然返回标题段（调用方会因 original 不匹配而跳过）
    if h:
        for i in range(start, len(texts)):
            if texts[i] and h in texts[i]:
                return i, "heading!"
    return -1, None


def _rev_find_span(cur, o):
    """在段落现存文字里找原文片段起止（归一化匹配后映射回原始下标）。"""
    if not o:
        return -1, -1
    i = cur.find(o)
    if i >= 0:
        return i, i + len(o)
    # 归一化差异（多空格/全角）时的模糊定位：逐字符在归一化后的串上定位
    nc, no_ = _rev_norm(cur), _rev_norm(o)
    j = nc.find(no_)
    if j < 0:
        return -1, -1
    # 把归一化下标映射回原文下标
    idx_map, k = [], 0
    for ch in cur:
        if not re.match(r"[\s\u3000]", ch):
            idx_map.append(k)
        k += 1
    if j >= len(idx_map) or j + len(no_) - 1 >= len(idx_map):
        return -1, -1
    return idx_map[j], idx_map[j + len(no_) - 1] + 1


def from_source_docx_rev(spec, kind):
    """原稿级修订：以原稿 docx 为底，把 clauses 的修订注入为痕迹。

    kind=tracked（1 修订版）／redline（4 红线版）。
    成功返回 doc；返回 None 表示降级（原因已写入 REV_FALLBACK["reason"]）。
    """
    path = SOURCE_DOCX or (spec.get("source_docx") or "")
    REV_FALLBACK.update({"reason": "", "hit": 0, "miss": 0})
    if not path or not str(path).lower().endswith(".docx") or not os.path.exists(path):
        REV_FALLBACK["reason"] = "未提供可编辑的 .docx 原稿"
        return None
    try:
        doc = Document(path)
    except Exception as e:
        REV_FALLBACK["reason"] = "原稿打开失败（%s）" % str(e)[:60]
        print("[make-docx] 原稿级修订回退：%s" % REV_FALLBACK["reason"])
        return None
    cs = clauses(spec)
    if not cs:
        REV_FALLBACK["reason"] = "审查规格缺条款（clauses），无法定位修改位置"
        return None

    paras = _rev_all_paras(doc)
    for p in paras:                       # run 合并预处理
        _rev_merge_runs(p)

    author = (REVIEWER or "AI 文档合规审查助手").replace('"', "")
    date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _REV_IDS[0] = _rev_existing_ids(doc)

    hit, miss, cursor = 0, [], 0
    for c in cs:
        o = (c.get("original") or "").strip()
        v = (c.get("revised") or "").strip()
        if not v or _rev_norm(v) == _rev_norm(o):
            continue                        # 无修改项，原稿一个字都不动
        idx, mode = _rev_locate(paras, c, cursor)
        if idx < 0:
            miss.append(c.get("heading") or o[:16] or "（无标题条款）")
            continue
        cursor = idx
        p = paras[idx]
        cur = _rev_para_text(p)
        newtext = v
        if _rev_norm(cur) != _rev_norm(v):
            # 原稿段落与 spec 的 original 可能只是"包含"关系（AI 截取了片段）→ 局部替换
            s, e = _rev_find_span(cur, o)
            if s < 0:
                if _rev_norm(v) and _rev_norm(v) in _rev_norm(cur):
                    continue                # 原稿已是改后文字，无需痕迹
                miss.append(c.get("heading") or o[:16] or cur[:16])
                continue
            newtext = cur[:s] + v + cur[e:]
        ops = inline_diff(cur, newtext)
        if not ops or [t for t in ops if t[0] != "equal"] == []:
            continue
        n = _rev_write_para(p, ops, kind, author, date)
        if not n:
            miss.append(c.get("heading") or o[:16])
            continue
        hit += 1
        if c.get("heading"):
            tail = [r for r in p.runs if r.text and r.text.strip()]
            add_clause_note(doc, (tail or p.runs)[-1:], c)
    REV_FALLBACK["hit"], REV_FALLBACK["miss"] = hit, len(miss)
    if miss:
        REV_FALLBACK["reason"] = ("%d 处修改无法在原稿中定位对应条款（%s），该部分未能落到原稿"
                                  % (len(miss), "、".join(miss[:3])))
        print("[make-docx] 原稿级修订（部分）：%s" % REV_FALLBACK["reason"])
    if hit == 0:
        REV_FALLBACK["reason"] = REV_FALLBACK["reason"] or "原稿中未能定位任何待修改条款"
        return None
    print("[make-docx] 原稿级修订：以原稿做底注入 %d 处%s痕迹（%s）"
          % (hit, "修订" if kind == "tracked" else "红线", os.path.basename(path)))
    return doc


# ---------- 原稿级修订结束 ----------


def doc_original(spec):
    """7 原文照录版：零批注，标题保持原文标题；"内部留存、勿对外"由文件名与文档属性承担。"""
    _sd = from_source_docx(spec, "original")
    if _sd is not None:
        return set_meta(_sd, spec, "original")
    doc = Document(); add_title(doc, title(spec))
    set_meta(doc, spec, "original")
    first = True
    for line in _original_text(spec).splitlines():
        role = para_role(line, first)
        if line.strip():
            first = False
        apply_role(doc.add_paragraph(line), role)
    return doc

def doc_masked(spec):
    """6 原文脱敏版：零批注（可能对外或上传平台），脱敏口径由文档属性与文件名承担。"""
    _sd = from_source_docx(spec, "masked")
    if _sd is not None:
        return set_meta(_sd, spec, "masked")
    doc = Document(); add_title(doc, title(spec))
    set_meta(doc, spec, "masked")
    text = _original_text(spec)
    if _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    first = True
    for line in text.splitlines():
        role = para_role(line, first)
        if line.strip():
            first = False
        apply_role(doc.add_paragraph(line), role)
    return doc

_TPL_MOD = None


def _tpl_engine():
    """惰性加载同目录的 tpl-engine.py（文件名带短横，不能直接 import）。失败返回 None。"""
    global _TPL_MOD
    if _TPL_MOD is not False and _TPL_MOD is None:
        try:
            import importlib.util as _ilu
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tpl-engine.py")
            _s = _ilu.spec_from_file_location("_tpl_engine", _p)
            _m = _ilu.module_from_spec(_s)
            _s.loader.exec_module(_m)
            _TPL_MOD = _m
        except Exception:
            _TPL_MOD = False
    return _TPL_MOD or None


def _tpl_switches(spec):
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    raw = t.get("switches")
    sw = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            sw[str(k)] = bool(v)
    elif isinstance(raw, list):
        for k in raw:
            sw[str(k)] = True
    return sw


def tpl_gate(spec):
    """模板版出件前的硬闸：占位符登记是否齐、必填是否填实、条件段是否定案、版本是否有留痕。

    走 tpl-engine（纯标准库，不联网）。**不过就拦住不出件**——模板缺版本号或必填没填，
    带病出件的后果是使用者拿着半成品签合同，比不出件坏得多。
    返回 (ok, info, errors, warnings)。
    """
    mod = _tpl_engine()
    if mod is None:
        # 引擎自身不可用时不拦出件，但要明说——静默降级等于没有这道闸
        return True, {}, [], ["模板引擎未加载，本次未做占位符与版本校验"]
    try:
        r = mod.check(spec, _tpl_switches(spec), filling=True)
    except Exception as ex:
        return False, {}, ["模板校验异常：%s" % ex], []
    return (not r["errors"]), r.get("info") or {}, r["errors"], r["warnings"]


def tpl_body(spec):
    """渲染后的模板正文：条件段已按开关取舍，占位符保持原样（模板本就该带占位符）。"""
    mod = _tpl_engine()
    if mod is None:
        return template_spec(spec)["body"]
    try:
        body, _ = mod.render(spec, _tpl_switches(spec))
        return body
    except Exception:
        return template_spec(spec)["body"]


def doc_template(spec):
    """10 模板版：占位符说明表 ＋ 模板正文（条件段已取舍）＋ 可选条款区 ＋ 使用须知 ＋ 版本留痕。

    报告型文书（本技能新写），故标题居中并带报告免责声明；可选条款逐条挂批注（正文不留痕）。
    """
    t = template_spec(spec)
    _ok, _info, _errs, _warns = tpl_gate(spec)
    if not _ok:
        raise SystemExit("[E] 模板版校验未通过，已拦下不出件：\n  - "
                         + "\n  - ".join(_errs)
                         + "\n  改好 spec.template 后重跑；只体检不出件可用："
                           "python scripts/tpl-engine.py check <spec.json>")
    _meta = (_info.get("meta") or {})
    doc = Document()
    h0 = add_report_title(doc, template_name(spec))
    set_meta(doc, spec, "template")
    # 模板版本写进文档属性（资源管理器右键即见），报告归档后可反查用的是哪版模板
    if _meta.get("version"):
        try:
            cp = doc.core_properties
            cp.subject = "模板版本 %s（%s）" % (_meta.get("version"), _meta.get("date") or "日期未记")
            cp.comments = (cp.comments or "") + "\n模板：%s ｜ 版本 %s ｜ %s ｜ 变更：%s" % (
                _meta.get("name") or template_name(spec), _meta.get("version"),
                _meta.get("date") or "—", _meta.get("change") or "—")
        except Exception:
            pass
    add_disclaimer(doc, spec)
    doc.add_paragraph("来源：" + title(spec) + "　审查人：" + REVIEWER + "　轮次：r" + ROUND)
    if _meta.get("version"):
        r = doc.add_paragraph().add_run(
            "模板版本：%s（%s）　变更：%s"
            % (_meta.get("version"), _meta.get("date") or "—", _meta.get("change") or "—"))
        r.font.size = Pt(9)
    add_delivery_note(doc, h0.runs[:1], "template", spec)
    if t["placeholders"]:
        doc.add_heading("一、占位符说明表", level=2)
        for i, p in enumerate(t["placeholders"], 1):
            doc.add_paragraph("%d. %s　含义：%s｜填写示例：%s｜%s"
                              % (i, p.get("name") or "—", p.get("meaning") or "—",
                                 p.get("example") or "—", "必填" if p.get("required") else "选填"))
    _body = tpl_body(spec)
    if _body:
        doc.add_heading("二、模板正文", level=2)
        for line in _body.splitlines():
            doc.add_paragraph(line)
    if t["optional"]:
        doc.add_heading("三、可选条款区", level=2)
        _ok_cm = can_comment(doc)   # 局部变量不得叫 can_comment（会遮蔽同名函数）
        for o in t["optional"]:
            p = doc.add_paragraph()
            r = p.add_run(o.get("name") or "可选条款"); r.bold = True
            doc.add_paragraph("适用场景：" + (o.get("scene") or "—")
                              + "　取舍建议：" + (o.get("advice") or "—"))
            if _ok_cm:
                add_template_note(doc, [r], "【可选条款】%s\n适用场景：%s\n取舍建议：%s"
                                  % (o.get("name") or "—", o.get("scene") or "—", o.get("advice") or "—"))
    if t["notes"]:
        doc.add_heading("四、使用须知", level=2)
        for line in t["notes"].splitlines():
            doc.add_paragraph(line)
    if _meta.get("version"):
        doc.add_heading("五、模板版本留痕", level=2)
        doc.add_paragraph("模板名称：%s" % (_meta.get("name") or template_name(spec)))
        doc.add_paragraph("版本：%s　定稿日期：%s" % (_meta.get("version"), _meta.get("date") or "—"))
        doc.add_paragraph("本次变更：%s" % (_meta.get("change") or "—"))
        doc.add_paragraph("留痕来源：%s"
                          % ("模板正文首行 <!-- tpl: … --> 注释" if _meta.get("source") == "body"
                             else "spec.template.meta"))
    return doc


DOC_GEN = {
    "tracked": doc_trackchanges, "redline": doc_redline, "clean": doc_clean,
    "report": doc_report, "reportc": doc_report_comments, "compare": doc_compare,
    "original": doc_original, "masked": doc_masked, "diff": doc_diff,
    "template": doc_template,
}
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
    wb, ws = _new_sheet("审查意见", ["序号", "条款定位", "评级", "风险描述", "法律依据", "修改建议"])
    if wb is None: return None
    for i, c in enumerate(clauses(spec), 1):
        ws.append([i, c.get("heading", ""), c.get("rating", ""), c.get("comment", ""), c.get("basis", ""), c.get("revised", "")])
    _widths(ws, [6, 34, 12, 60, 34, 60])
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
    text = _original_text(spec)
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

def export_pdf(docx_paths, outdir):
    """用 LibreOffice 无头模式把 docx 转 PDF；不可用时返回空列表（不阻断主流程）。"""
    if not docx_paths:
        return []
    if not PDF_EXPORT:
        print("[make-docx] 提示：config.render.pdf_export=false，跳过 PDF 导出。")
        return []
    if _cfgmod and not _cfgmod.tool_available(_CFG, "soffice"):
        print("[make-docx] 提示：未检测到 LibreOffice，跳过 PDF 导出（装好 LibreOffice 或改 config.json 后可重跑）。")
        return []
    import subprocess
    try:
        r = subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir", outdir] + docx_paths,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=PDF_TIMEOUT)
        if r.returncode != 0:
            print("[make-docx] PDF 导出返回码非 0：", (r.stderr or r.stdout or "")[:200])
    except Exception as e:
        print("[make-docx] PDF 导出失败（不影响其它交付物）：", e)
        return []
    outs = [os.path.splitext(os.path.basename(p))[0] + ".pdf" for p in docx_paths]
    return [o for o in outs if os.path.exists(os.path.join(outdir, o))]

# ---------- md 生成 ----------
def md_diff_text(o, v, kind):
    """Markdown 的细粒度差异文本（与 docx 同一套 inline_diff，粒度一致）。"""
    if not (v and v != o):
        return o or v
    if not o:
        return ("<ins>%s</ins>" if kind == "tracked" else "**%s**") % v
    if not v:
        return ("<del>%s</del>" if kind == "tracked" else "~~%s~~") % o
    dm = ("<del>%s</del>" if kind == "tracked" else "~~%s~~")
    im = ("<ins>%s</ins>" if kind == "tracked" else "**%s**")
    parts, prev = [], None
    for tag, txt in inline_diff(o, v):
        if prev and prev != tag and tag != "equal" and prev != "equal":
            parts.append(" ")          # 删除段与插入段之间留一个空格，避免渲染粘连
        parts.append(txt if tag == "equal" else ((dm % txt) if tag == "delete" else (im % txt)))
        prev = tag
    return "".join(parts)


def md_meta_line(slug):
    return "> %s ｜ 审查人：%s ｜ 轮次：r%s" % (SLUGS.get(slug, slug), REVIEWER, ROUND)


def md_trackchanges(spec):
    out = ["# " + title(spec), "", md_meta_line("tracked") + "　图例：`<del>`=删除、`<ins>`=新增。"]
    for c in clauses(spec):
        o, v = c.get("original", ""), c.get("revised", "")
        out.append(f"\n**{c.get('heading','')}**\n\n" + md_diff_text(o, v, "tracked"))
    return "\n".join(out) + "\n"

def md_redline(spec):
    out = ["# " + title(spec), "", md_meta_line("redline") + "　图例：`~~删除~~`、`**新增**`。"]
    for c in clauses(spec):
        o, v = c.get("original", ""), c.get("revised", "")
        out.append(f"\n**{c.get('heading','')}**\n\n" + md_diff_text(o, v, "redline"))
    return "\n".join(out) + "\n"

def md_clean(spec):
    out = ["# " + title(spec), "", md_meta_line("clean")]
    for c in clauses(spec):
        out.append(f"\n**{c.get('heading','')}**\n\n{c.get('revised') or c.get('original') or ''}")
    return "\n".join(out) + "\n"

def md_report(spec):
    out = ["# " + (spec.get("report_title", "文档合规审查意见报告")), "",
           "> 源文件：" + title(spec) + "｜审查人：" + REVIEWER + "｜轮次：r" + ROUND, ""]
    for i, c in enumerate(clauses(spec), 1):
        out.append(f"## {i}. {c.get('heading','')}  {c.get('rating','')}")
        out.append(f"- 风险描述：{c.get('comment') or '—'}")
        out.append(f"- 法律依据：{c.get('basis') or '—'}")
        out.append(f"- 修改建议：{c.get('revised') or '—'}")
    return "\n".join(out) + "\n"

def md_compare(spec):
    out = ["# " + title(spec) + "（新旧比对）", "", "| 条款 | 原文 | 修改后 |", "|---|---|---|"]
    for c in clauses(spec):
        out.append(f"| {c.get('heading','')} | {(c.get('original') or '').replace(chr(10),'<br>')} | {(c.get('revised') or '').replace(chr(10),'<br>')} |")
    return "\n".join(out) + "\n"

def md_original(spec):
    return "# " + title(spec) + "\n\n" + md_meta_line("original") + \
           "　内部留存，勿对外。\n\n" + _original_text(spec) + "\n"

def md_masked(spec):
    text = _original_text(spec)
    if _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    return "# " + title(spec) + "\n\n" + md_meta_line("masked") + \
           "　已脱敏（信用代码/金额/地址/人名；比例不脱）。\n\n" + text + "\n"

def md_diff(spec):
    rows, note = diff_rows(spec)
    out = ["# " + title(spec) + "（文件比对报告）", "", "> " + note, "",
           "| " + " | ".join(DIFF_HEADERS) + " |",
           "|" + "---|" * len(DIFF_HEADERS)]
    for r in rows:
        cells = [r[k].replace("|", "\\|").replace("\n", "<br>") for k in DIFF_KEYS]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"

def md_reportc(spec):
    """批注版的 Markdown 等效呈现（Markdown 无批注锚定能力，正文即意见清单）。"""
    return md_report(spec) + "\n> 说明：Markdown 不支持 Word 批注；本文件为该类型的等效文本呈现，" \
                             "需逐条批注锚定请选 WORD 格式。\n"

def md_template(spec):
    t = template_spec(spec)
    out = ["# " + template_name(spec), "", md_meta_line("template"), ""]
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
            print("[make-docx] 提示：markdown 库转换失败（%s），改用内置转换器。" % e)
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


def html_page(slug, spec, body):
    """把正文片段包成单文件网页：**顶部固定目录导航 + 可折叠条款 + 打印按钮**。

    目录锚点在**服务端**生成（正则扫 h2/h3 后回填 id），所以即使浏览器禁用 JS，
    导航与跳转照样能用；JS 只负责折叠与打印。
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
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(t)s</title>
<style>%(css)s</style></head><body>
<div class="topbar">
  <span class="brand">文档合规审查助手 <em>%(slug)s</em></span>
  <nav class="toc">%(nav)s</nav>
  <button class="btn ghost" id="btn-fold">全部折叠</button>
  <button class="btn ghost" id="btn-expand">全部展开</button>
  <button class="btn" id="btn-print">打印 / 存 PDF</button>
</div>
<main class="page">
%(body)s
<div class="foot">%(meta)s　｜　本文件由「文档合规审查助手AI合同」生成，仅供辅助参考，不构成法律意见；须经执业律师复核后方可据此决策。</div>
</main>
<script>%(js)s</script>
</body></html>
""" % {"t": esc(doc_title), "css": HTML_CSS, "nav": nav, "slug": esc(SLUGS.get(slug, slug)),
       "body": body, "meta": esc(md_meta_line(slug)), "js": HTML_JS}


def main():
    global REVIEWER, ROUND, TS, SOURCE, SOURCE_DOCX
    ap = argparse.ArgumentParser(description="文档合规审查交付物产出（10 类型，审查人必填；类型以勾选框多选、一次全部显示供用户勾选）")
    ap.add_argument("spec")
    ap.add_argument("--out", default=None, help="输出目录（默认 D:\\文档合规审查报告\\输出）")
    ap.add_argument("--subdir", default=None, help="输出目录下再建子文件夹（按合同归档用）")
    ap.add_argument("--reviewer", default=None, help="审查人名称（必填；未提供时交互追问或报错退出）")
    ap.add_argument("--round", default=None); ap.add_argument("--ts", default=None)
    ap.add_argument("--types", default=None,
                    help="逗号分隔：tracked,reportc,clean,redline,report,masked,original,diff,compare,template（默认 1、2、3 三类；全部 10 类请显式列出；亦可写中文类型名）")
    ap.add_argument("--formats", default="docx", help="逗号分隔：docx,md,excel,pdf,html（PDF 由 docx 转换；HTML 由 md 转换）")
    ap.add_argument("--comments", action="store_true", help="兼容保留：等价于在 --types 中追加 reportc（审查意见批注版）")
    ap.add_argument("--style", default=None,
                    help="排版样式档位：default（不改动）/contract（合同风，默认）/official（公文风）；亦可写 spec.style 或 config.json 的 render.style；只对 1、3、4、6、7 五类生效")
    ap.add_argument("--source-docx", default=None,
                    help="半档C 排版保真：原稿 .docx 路径。指定后 1修订版/4红线版 在原稿 run 之间插修订痕迹、"
                         "3清洁版/6脱敏版/7照录版 只替换段落文字（均保留字体/对齐/缩进/页边距/页眉页脚/表格），"
                         "不可用或条款定位不到则自动回退样式档位并按降级口径标注")
    ap.add_argument("--cmp-a", default=None, help="文件比对报告：旧版文本文件（.txt/.md；亦可用 spec.compare.a_text）")
    ap.add_argument("--cmp-b", default=None, help="文件比对报告：新版文本文件（.txt/.md；亦可用 spec.compare.b_text）")
    a = ap.parse_args()
    if _cfgmod and bool(_cfgmod.privacy_opt(_CFG, "warn_before_context")):
        print("[make-docx] 数据出域提示：审查模式需将文档全文读入模型上下文。涉密/敏感文档请改用 "
              "`python local-only.py <文件>`（纯本地提取+脱敏，全程不联网、不进模型）。")
    spec = json.load(open(a.spec, encoding="utf-8-sig"))
    if a.cmp_a or a.cmp_b:
        # 文件比对报告：允许直接用两个文本文件覆盖/补充 spec.compare.*
        cmpmap = dict(spec.get("compare") or {})
        if a.cmp_a:
            cmpmap["a_text"] = open(a.cmp_a, encoding="utf-8-sig", errors="ignore").read()
            cmpmap.setdefault("a_label", os.path.basename(a.cmp_a))
        if a.cmp_b:
            cmpmap["b_text"] = open(a.cmp_b, encoding="utf-8-sig", errors="ignore").read()
            cmpmap.setdefault("b_label", os.path.basename(a.cmp_b))
        spec["compare"] = cmpmap
        print("[make-docx] 文件比对报告：已读取比对文本（%s ↔ %s）"
              % (cmpmap.get("a_label") or "旧版", cmpmap.get("b_label") or "新版"))
    REVIEWER = (a.reviewer or spec.get("reviewer") or os.environ.get("REVIEWER") or "").strip()
    if not REVIEWER and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            REVIEWER = input("请输入审查人名称（必填，将写入文件名与 Word 修订者）：").strip()
        except (EOFError, KeyboardInterrupt):
            REVIEWER = ""
    if not REVIEWER:
        print("[make-docx] 已停止：审查人名称必填，未提供不产出交付物。")
        print("  提供方式：--reviewer、spec.reviewer 或环境变量 REVIEWER（纯自动化可用 --reviewer \"AI 文档合规审查助手\"）。")
        sys.exit(2)
    ROUND = str(a.round or spec.get("round") or "1")
    if a.ts:
        TS = a.ts
    else:
        TS = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        print("[make-docx] 提示：未提供 --ts，时间戳取本机时钟（可能不准确）；建议由 AI 传入准确时间 --ts YYYYMMDD-HHMM。")
    SOURCE = sanitize(spec.get("source") or spec.get("name") or "contract")
    SOURCE_DOCX = (a.source_docx or spec.get("source_docx") or "")
    if SOURCE_DOCX and not os.path.exists(SOURCE_DOCX):
        print("[make-docx] 提示：--source-docx 路径不存在，1、3、4、6、7 回退样式档位：%s" % SOURCE_DOCX)
        SOURCE_DOCX = ""
    set_style(a.style or spec.get("style")
              or (_cfgmod.render_opt(_CFG, "style") if _cfgmod else None) or "contract")
    if STYLE != "default":
        print("[make-docx] 排版档位：%s（--style default 可关闭；仅对 1、3、4、6、7 五类生效）" % STYLE)
    outdir = a.out or OUT_DIR
    if a.subdir:
        outdir = os.path.join(outdir, a.subdir)
    elif not a.out and _cfgmod and bool(_cfgmod.output_opt(_CFG, "per_source_subdir")):
        # 低危-2：未显式指定 --out/--subdir 时，自动按文档名建子目录，
        # 避免多客户文档在输出目录平铺混放、被整体打包外泄。
        outdir = os.path.join(outdir, SOURCE)
        print("[make-docx] 输出隔离：已自动建立文档专属子目录 %s（可用 --out/--subdir 覆盖，config.json output.per_source_subdir=false 可关闭）" % SOURCE)
    try:
        os.makedirs(outdir, exist_ok=True)
        os.makedirs(IN_DIR, exist_ok=True)
    except Exception:
        outdir = os.path.join(os.getcwd(), "文档合规审查报告", "输出")
        os.makedirs(outdir, exist_ok=True)
        print("[make-docx] 提示：默认目录不可用，已改用", outdir)
    a.out = outdir
    NAME2SLUG = {v: k for k, v in SLUGS.items()}
    raw = [t.strip() for t in (a.types or ",".join(DEFAULT_TYPES)).split(",") if t.strip()]
    types, unknown = [], []
    for t in raw:
        s = t if t in SLUGS else NAME2SLUG.get(t)
        (types if s else unknown).append(s or t)
    if unknown:
        print("[make-docx] 提示：忽略无法识别的类型名 %s（可用 slug：%s）" % (",".join(unknown), ",".join(TYPE_ORDER)))
    if not types:
        print("[make-docx] 错误：--types 未包含任何有效类型。"); sys.exit(2)
    fmts = [f.strip().lower() for f in a.formats.split(",") if f.strip()]
    if not fmts:
        print("[make-docx] 错误：--formats 至少包含 docx / md / excel / pdf / html 之一。"); sys.exit(2)
    # 兼容：--comments 等价于选中 reportc（批注版＝正式交付物类型 5）
    if a.comments and "reportc" not in types:
        types.append("reportc")
    made, docx_paths = [], []
    for t in types:
        if t in ("original", "masked") and not _original_text(spec):
            print(f"[make-docx] 跳过 {SLUGS[t]}：spec 缺少 original_text。"); continue
        if "docx" in fmts:
            # 先产对象再取名：1、4 是否降级只有生成完才知道（降级件名里要带「-降级」标记）
            docobj = DOC_GEN[t](spec)
            if t in REV_SLUGS:
                REV_DEGRADED[t] = REV_FALLBACK.get("reason") or ""
            name = outname(t, "docx"); p = os.path.join(a.out, name)
            docobj.save(p); made.append(name); docx_paths.append(p)
        if "md" in fmts and t in MD_GEN:
            name = outname(t, "md")
            open(os.path.join(a.out, name), "w", encoding="utf-8").write(MD_GEN[t](spec)); made.append(name)
        if "html" in fmts and t in MD_GEN:
            name = outname(t, "html")
            open(os.path.join(a.out, name), "w", encoding="utf-8").write(
                html_page(t, spec, md_to_html(MD_GEN[t](spec)))); made.append(name)
        if "excel" in fmts:
            wb = EXCEL_GEN[t](spec)
            if wb is None:
                print("[make-docx] 提示：未安装 openpyxl，跳过 Excel 导出（pip install openpyxl 后重跑）。")
            else:
                name = outname(t, "xlsx"); wb.save(os.path.join(a.out, name)); made.append(name)
    if "pdf" in fmts:
        if "docx" not in fmts:
            print("[make-docx] 提示：PDF 由 docx 转换，请在 --formats 中一并包含 docx；本次跳过 PDF。")
        else:
            made += export_pdf(docx_paths, a.out)
    print(f"[make-docx] 审查人={REVIEWER} 轮次=r{ROUND} 产出 {len(made)} 个文件于", os.path.abspath(a.out))
    for m in made: print("  -", m)

if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError,
            json.JSONDecodeError, OSError) as e:
        # ⚠ 2026-10-20 全量质检修（独立复核实测坐实）：spec 文件不存在/非 JSON
        #   原来直接抛裸 traceback。统一：用法/输入故障 exit 2。
        print("[make-docx] 输入错误：%s —— 请核对 spec 路径与 JSON 格式" % e,
              file=sys.stderr)
        sys.exit(2)
