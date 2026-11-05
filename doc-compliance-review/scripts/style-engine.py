#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  只算段落属性、不接触文档内容外发 → 绝对离线，不得引入任何网络库
"""
文档风格引擎 · style-engine（v3.31.0 新增）
===============================================================================
**这一层只回答「版面长什么样」，不回答「内容是什么」「存成什么格式」**。
输入是一段文字与一个段落对象，输出是这个段落被套上样式档位之后的样子。

职责边界（三引擎分工）
-------------------------------------------------------------------------------
  doc-ir.py        内容层：要写什么（条款、差异台账、导图树）
  style-engine.py  **本文件**：写成什么样（标题居中否、正文缩进否、行距多少）
  format-engine.py 格式层：存成什么文件（docx/md/xlsx/pdf/html/pptx/svg/png/…）

档位设计：**按文档气质分档，不按用途分档**
-------------------------------------------------------------------------------
用户说「要正式一点」「像公文」「随便点」——这是气质。故档位以气质命名，
每档是一张 8 开关的开关表（STYLE_PRESETS），改档不改代码：

  default   不改版式（保持既有行为，供不需要改版式的场景使用）
  contract  合同风（**默认**）：标题居中 16pt、条款标题加粗不缩进、正文 12pt 首行缩进 2 字、行距 1.5
  official  公文风：标题二号（22pt）居中、正文三号（16pt）首行缩进、落款右对齐

八个开关（每档全部显式写死，缺省＝行为漂移）
-------------------------------------------------------------------------------
  title_center  标题居中        title_size   标题字号（None＝不动）
  clause_bold   条款标题加粗    body_indent  正文首行缩进 2 字符
  body_size     正文字号        line_spacing 行距倍数（None＝不动）
  space_before  段前距（pt）    sign_right   落款右对齐

段落角色推断（para_role）
-------------------------------------------------------------------------------
扫描件/OCR/粘贴文本没有格式可继承，故按**文本特征**猜角色：
  doc_title  首段、短、不以句末标点结尾
  clause     「第 X 条」或「一、」
  num_title  「1.」「1.2.」开头且短
  sign       ≤20 字且含「甲方/乙方/签署/盖章/日期」
  body       其余
这是**启发式**：猜错只影响缩进与字号，不影响内容与法律含义。

不改行为的约束
-------------------------------------------------------------------------------
default/contract/official 三档的 8 个开关值与抽出前**逐字段相等**；
抽出前后由 core/_byte-golden.json 逐字节比对守护。
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

import re
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


# ---------------------------------------------------------------- 档位真源
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
