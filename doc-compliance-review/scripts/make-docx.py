#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
#   · v3.28.0 起「HTML 在线增强版」（--html-online）只把白名单 CDN（HTML_CDN_ALLOW）的
#     <script src>/<link href> **写进产物 HTML 字符串**，本脚本自身不发起任何请求，故档位仍为 E0。
#     E0 的红线是「脚本不出网」，不是「产物不许含 http 字样」——二者不可混为一谈；
#     白名单域守卫见 check.py::check_html_online_guard。
"""
文档合规审查助手AI合同 · 交付物产出脚本（10 类型 × WORD/MD，统一命名）
===============================================================================
交付物类型（勾选框 · 多选，**一次全部显示供勾选**，产出前询问用户）：
  1) 修订版（首选）        2) 审查意见报告        3) 清洁版
  4) 红线标记修订版        5) 审查意见批注版      6) 原文脱敏版
  7) 原文照录版            8) 文件比对报告        9) 新旧比对       10) 模板版
  · 编号排序＝使用频率优先（1、2 默认两类置前）＋档位分组其次（保真类 3-6 → 照录 7 → 新建 8-10）；
    编号一经发布不再变动，新增取下一个空号（设计文档 §2.4）。
  · 未勾选时默认产出 1、2 两类（修订版／审查意见报告；--types 可显式指定，亦可用中文类型名）。
  · 类型 1（修订版）：Word 原生修订痕迹（w:ins/w:del），可逐条接受/拒绝；
    **只标到改动的最小范围**——句读对齐后对改写块再做字符级细分，差异过大才整段替换。
    **给 --source-docx 时走原稿级修订**：在原稿既有 run 之间插痕迹，版式沿用原稿。
  · 类型 4（红线标记修订版）：粒度同 1，痕迹改用灰色删除线／红色下划线，不依赖 Word 修订功能。
    **给 --source-docx 时同样以原稿为底**（同一套定位逻辑，痕迹换成纯格式标记）。
  · 类型 5（批注版）：**原稿就地批注**——给 `--source-docx` 时以原稿为底，正文一字不改，
    每条意见以 Word 批注锚定到原稿对应段落；无原稿时才回退「重建清单」形态，
    并在文件名与文档属性标注「非原稿批注」（与 1 修订版同一条硬性要求）。
    需 python-docx>=1.2，低版本回退重建形态并标注。`--comments` 为兼容保留的等价开关。
  · **不人为增加抬头（保持原版观感）**：1、3、4、6、7 五类＝还原原文的交付物，
    标题即原文标题（**不加「（修订模式）」等类型后缀**）、正文**不加「说明：…」段**；
    类型／审查人／轮次／时间写入 **docx 核心属性**（资源管理器右键「属性」即见）与文件名。
    1、4 另在标题上挂 **1 条「这是什么文件」批注 ＋ 每处修改 1 条意见批注**；
    3、6、7 **零批注**（可能对外发出或纯原文转录，不夹带内部审查意见）。
    5 批注版走原稿路线时正文即原稿，同样不加抬头；只有降级重建形态才是新写文书。
    报告类（5、8、9、10）是本技能新写的文书，标题与报告免责声明属文书固有内容，不适用此节。
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
  --source-docx <原稿.docx>：半档C 排版保真，对 1修订版/5批注版/3清洁版/4红线版/6脱敏版/7照录版 生效；
                            1、3 在原稿既有 run 之间插修订痕迹（w:ins/w:del 或红线格式），
                            4 只挂批注、正文一字不改，5、6、7 只做段落级替换文字；均保留原稿版式。
                             **格式预读**：按文件头判断真实格式（不看扩展名）——.docx 直接用；
                             Word 97-2003 二进制（.doc 及改过扩展名的）用 LibreOffice 转成 .docx 后使用；
                             转换不可用或条款定位不到则自动回退样式档位，并按降级口径标注。
spec.json 关键字段：
  name / source / report_title / disclaimer / reviewer / round
  clauses[]: heading / original / revised / rating / basis / comment
  original_text（可选）：原文照录版/原文脱敏版 需要（全文文本）
  compare{a_label,a_text,b_label,b_text}（可选）：文件比对报告 需要（两份全文）
  template{name,placeholders[],body,optional[],notes}（可选）：模板版 需要（转模板 / 撰写模板）
依赖：python-docx（>=1.2，支持批注）；openpyxl（Excel 导出）；LibreOffice（PDF 导出，可选；
      亦用于把 .doc/.wps/.rtf 转成 .docx 供原稿做底，缺失时这几类老格式降级并标注）；
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
import os, re, sys, json, argparse, datetime, random, difflib, copy, unicodedata, tempfile
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

# ---- 引擎加载（v3.31.0）：内容层 / 风格引擎 / 格式引擎 三个独立脚本 ----
#
# 为什么不能一句 `from doc_ir import …`：本项目的脚本名沿用连字符（make-docx.py、
# doc-ir.py、format-engine.py），而 **import 语句无法导入带连字符的模块名**——
# `import doc_ir` 直接 ModuleNotFoundError（实测）。故须先把文件按「下划线名」注册进
# sys.modules，之后那句 import 才成立。
#
# 三个坑（都实测踩过，别再踩）：
#   ① 不能直接用 importlib.util.spec_from_file_location("doc-ir", path)：模块 __name__
#      会带连字符，随后 `from doc_ir import …` 仍 ImportError——同一个坑换个入口。
#   ② 不能拿 FileFinder 找到的 loader 直接 exec：它绑定的名字是 'doc-ir'，会报
#      「loader for doc-ir cannot handle doc_ir」。
#   ③ 必须用**裸名导入**（from doc_ir import func），不能 `import doc_ir as X` 后调
#      X.func()：check.py 的「导图单一真源」守卫按 ast.Name 认调用点，属性调用会让守卫变瞎。
import importlib.util
from importlib.machinery import FileFinder, SourceFileLoader   # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_FINDER = FileFinder(_HERE, (SourceFileLoader, [".py"]))


def _load_engine(dashed, plain):
    """把 <dashed>.py 以 <plain> 之名载入 sys.modules；缺文件即报错（不许静默降级）。"""
    sp = _FINDER.find_spec(dashed)
    if sp is None:
        raise ImportError("引擎脚本 %s.py 缺失——本脚本无法完成任何产出" % dashed)
    lob = SourceFileLoader(plain, sp.origin)      # 名字相符的装载器（坑②）
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(plain, lob))
    _sys.modules[plain] = mod
    lob.exec_module(mod)
    return mod


_load_engine("doc-ir", "doc_ir")                  # 第 17 号引擎：内容层
_load_engine("style-engine", "style_engine")      # 第 19 号引擎：风格
_load_engine("format-engine", "format_engine")    # 第 18 号引擎：格式

from doc_ir import (clauses, title, template_spec, template_name, original_text,
                    inline_diff, md_diff_text, diff_rows,
                    DIFF_HEADERS, DIFF_KEYS, mm_tree)
# 风格引擎：样式档位 ＋ 段落角色推断 ＋ 版式套用（只认 python-docx 的段落对象；
# md/html/pptx/svg 各有自己的版式真源，不走这里）。
from style_engine import (STYLE_ORDER, STYLE_PRESETS, set_style, para_role, apply_role,
                          add_title, add_report_title, add_clause_title, apply_text)
import style_engine as _stylemod   # 读当前档位（STYLE 是可变全局，import 名字会固化旧值）
# 格式引擎：excel/md/html/pptx/svg/png/pdf 的写出与渲染＋格式家族真源
# （FORMAT_ALL / FORMAT_LABEL / HTML_CDN_ALLOW / PPT_TYPES / MINDMAP_TYPES 都在那边，
#   本脚本与 check.py 都从它读——格式真源只有一处，文档与守卫才不会各说各话）。
from doc_ir import RenderCtx, Artifact
from format_engine import (FORMAT_FALLBACK, FORMAT_ALL, FORMAT_LABEL, HTML_CDN_ALLOW,
                           PPT_TYPES, MINDMAP_TYPES, DOC_EXCEL_GEN, MD_GEN, PPT_GEN,
                           MINDMAP_GEN, IMAGE_TYPES, IMAGE_DEFAULT, IMG_TYPES,
                           export_pdf, export_pptx, export_mindmap,
                           export_image, export_image_mindmap,
                           summary_dir, export_summary_mindmap, html_page, md_to_html,
                           md_meta_line)
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
# 10 类交付物（勾选框 · 多选，一次全部显示供勾选；顺序即清单排列顺序）
# 编号排序规则（v3.27.0 定稿）：使用频率优先（默认两类 1、2 置前）＋档位分组其次
# （保真类 3清洁/4红线/5批注/6脱敏 → 照录类 7 → 新建类 8/9/10）。
# **编号一经发布不再变动**：新增交付物取下一个空号，不得插队重排（设计文档 §2.4）。
TYPE_ORDER = ["tracked", "report", "clean", "redline", "reportc",
              "masked", "original", "diff", "compare", "template"]
# 用户未勾选时的默认产出：1 修订版 / 2 审查意见报告
DEFAULT_TYPES = ["tracked", "report"]

# ---- 保真档位体系（设计文档：maint/design/保真档位体系-设计说明-v3.1-定稿.md）----
# 第 1 步（立体系，行为不变）：仅登记要求类型真源与解析器，生成流程暂不消费；
# 第 2 步（切档位）起由 resolve_tier() 统一判定并四处外显（文件名/属性/报告注记/终端汇总）。
# 键序必须与 TYPE_ORDER 完全一致（含顺序），由 check.py::check_tier_requirement 守卫。
TIER_REQUIREMENT = {
    "tracked":  "ORIGINAL_STRICT",       # 1 修订版：任何情况都必须原稿级
    "report":   "CITE_FIDELITY",         # 2 审查意见报告：版式 NEWDOC，引文须逐字取自原稿
    "clean":    "ORIGINAL_STRICT",       # 3 清洁版
    "redline":  "ORIGINAL_STRICT",       # 4 红线标记修订版
    "reportc":  "ORIGINAL_STRICT",       # 5 审查意见批注版
    "masked":   "CONTENT_ONLY",          # 6 原文脱敏版：只管内容，不管版式
    "original": "ORIGINAL_IF_AVAILABLE", # 7 原文照录版：有原稿必须原稿级，无原稿降级即合规
    "diff":     "NEWDOC_ONLY",           # 8 文件比对报告
    "compare":  "NEWDOC_ONLY",           # 9 新旧比对
    "template": "NEWDOC_ONLY",           # 10 模板版
}
# 五种要求类型（互斥）。新增取值须先过 check.py::check_tier_requirement 第 3 条。
TIER_LEVELS = ("ORIGINAL_STRICT", "ORIGINAL_IF_AVAILABLE",
               "CITE_FIDELITY", "CONTENT_ONLY", "NEWDOC_ONLY")
# 档位落点（运行时实际到达的档）：ORIGINAL / QUASI_A / QUASI_B / CONTENT_ONLY / NEWDOC
TIER_TIERS = ("ORIGINAL", "QUASI_A", "QUASI_B", "CONTENT_ONLY", "NEWDOC")
# 要求类型 → 允许落点（相容矩阵；check.py 第 4 条据此校验运行时产物）
TIER_ALLOWED = {
    "ORIGINAL_STRICT":       ("ORIGINAL", "QUASI_A", "QUASI_B"),
    "ORIGINAL_IF_AVAILABLE": ("ORIGINAL", "QUASI_A", "QUASI_B"),
    "CITE_FIDELITY":         ("NEWDOC",),
    "CONTENT_ONLY":          ("ORIGINAL", "QUASI_A", "QUASI_B", "NEWDOC"),
    "NEWDOC_ONLY":           ("NEWDOC",),
}


def resolve_tier(slug, src_probe, produced_state):
    """单一档位解析器（设计 §4.1）。第 1 步暂无消费者，行为不变。

    参数：
      slug            交付物代号（TYPE_ORDER 之一）
      src_probe       prepare_source 产出的探测结果（kind/reason/layout_hints）
      produced_state  {slug: "ok" | "fallback:<原因>"}，生成函数回填
    返回：
      (tier, reason, source_kind)——tier ∈ TIER_TIERS。
    """
    req = TIER_REQUIREMENT.get(slug, "NEWDOC_ONLY")
    state = produced_state.get(slug, "ok")
    if req == "NEWDOC_ONLY":
        return ("NEWDOC", "", src_probe.get("kind", "none"))
    if req == "CITE_FIDELITY":
        return ("NEWDOC", "", src_probe.get("kind", "none"))
    if req == "CONTENT_ONLY":
        return ("CONTENT_ONLY", "", src_probe.get("kind", "none"))
    # ORIGINAL_STRICT / ORIGINAL_IF_AVAILABLE：看是否拿到可用原稿
    kind = src_probe.get("kind", "missing")
    usable = kind in ("word", "ole2") and state in ("ok", "partial")
    if usable:
        # partial＝已在原稿上改/批、部分条款没落位——仍是原稿做底（ORIGINAL），
        # 部分落位详情由文档属性承担（set_meta fallback 段），文件名不打档位标记
        return ("ORIGINAL", ("部分条款未在原稿落位" if state == "partial" else ""), kind)
    # 无可用原稿
    if req == "ORIGINAL_IF_AVAILABLE":
        hints = src_probe.get("layout_hints")
        return (("QUASI_A", "无可用原稿，按可用版式线索重建", kind) if hints
                else ("QUASI_B", "无可用原稿且无版式线索，按模板重建", kind))
    return ("QUASI_B" if not src_probe.get("layout_hints") else "QUASI_A",
            "未达到原稿级（原稿不可用或做底失败）", kind)


def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def _rid(): return str(random.randint(100000, 999999))

def sanitize(name):
    s = re.sub(r"[\s]+", "-", (name or "contract").strip())
    s = re.sub(r"[\\/:*?\"<>|（）()【】\[\]·、,，]+", "", s)
    return s[:40] or "contract"

# 走原稿做底判定链的要求类型（v3.27.0：SRC_SLUGS 三类白名单废除，改由 TIER_REQUIREMENT 驱动，
# 避免新增保真类时漏登记白名单——clean/masked/original 正是漏在外面的那三类）
_SRC_REQ = ("ORIGINAL_STRICT", "ORIGINAL_IF_AVAILABLE")
# （v3.27.0）REV_DEGRADED 已废除：档位由 resolve_tier 统一判（fallback 状态直接传参），不再经全局中转


def outname(slug, ext="docx", tier=""):
    """文件名＝源_类型[_档位标记]_审查人_r轮次_时间.ext（v3.27.0 档位体系）。

    档位标记是保真档位「四处外显」之一（另三处：文档属性、报告注记、终端汇总）：
      ORIGINAL / NEWDOC / CONTENT_ONLY 不加标记（本就达标或本就不保版式）；
      QUASI_A → 「-准原稿A」（有版式线索，已尽量贴近原稿版式重建）；
      QUASI_B → 「-准原稿B」（无版式线索，纯模板重建）。
    旧的「-降级／-降级-部分」弃用——「降级」降到了哪里说不清，新标记直接说出档位；
    「-降级-部分」的部分落位信息改由文档属性承担（set_meta 的 fallback 段）。
    """
    tag = ""
    if tier in ("QUASI_A", "QUASI_B"):
        tag = "-准原稿" + tier[-1]
    return f"{SOURCE}_{SLUGS[slug]}{tag}_{REVIEWER}_r{ROUND}_{TS}.{ext}"

def tracked_ins(p, text):
    p._p.append(parse_xml(f'<w:ins {nsdecls("w")} w:id="{_rid()}" w:author="{esc(REVIEWER)}" w:date="{now()}"><w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:ins>'))

def tracked_del(p, text):
    p._p.append(parse_xml(f'<w:del {nsdecls("w")} w:id="{_rid()}" w:author="{esc(REVIEWER)}" w:date="{now()}"><w:r><w:delText xml:space="preserve">{esc(text)}</w:delText></w:r></w:del>'))

# 原文脱敏版默认 **12 类全脱**（含信用代码/金额/地址/人名；比例不脱）。
# 真源＝desensitize.py 的 ALL_TYPES，此处直接取用，避免两处各写一份而漂移。
MASK_TYPES = (_d.ALL_TYPES.split(",") if _d is not None
              else ["idcard", "phone", "bank", "email", "postcode", "im",
                    "uscc", "amount", "addr", "name"])

# 细粒度修订（句读对齐＋字符级细分）、差异台账、模板 spec 已抽到 doc-ir.py（v3.31.0）


# ---------- 交付物说明：写进文档属性／批注，不占正文版面 ----------
# 当前正在写入的档位（主流程在生成前设置，set_meta 写入文档属性；不属于档位体系的类保持空串）
CURRENT_TIER, CURRENT_TIER_REASON, CURRENT_SRC_KIND = "", "", ""
# 全轮档位台账：slug → (tier, reason)；2 审查意见报告的保真注记（§3.3）由此读取。
# report 在主流程中被挪到最后生成，正是为了保证台账到报告生成时已完整。
TIER_LEDGER = {}

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
        if CURRENT_TIER:
            # v3.27.0 档位体系「四处外显」之二：文档属性（文件名/报告注记/终端汇总为另三处）。
            # 写进 docProps/custom.xml：资源管理器不直接显示，但程序可读、审计可查。
            cp.comments += ("\n保真档位：%s%s" % (CURRENT_TIER,
                            ("（%s）" % CURRENT_TIER_REASON) if CURRENT_TIER_REASON else ""))
            cp.keywords += "; 档位:%s" % CURRENT_TIER
            doc.custom_properties["dcr-fidelity-tier"] = CURRENT_TIER
            if CURRENT_TIER_REASON:
                doc.custom_properties["dcr-fidelity-reason"] = CURRENT_TIER_REASON
            if CURRENT_SRC_KIND:
                doc.custom_properties["dcr-source-kind"] = CURRENT_SRC_KIND
        if fallback:
            # 两种降级不能混为一谈：完全没落到原稿（重建）vs 部分条款没落位（仍是原稿件）
            # 5 批注版的落位与否看 COMMENT_FALLBACK（tracked/redline 用 REV_FALLBACK），
            # 措辞也随类型变：批注版「没落位」＝这条意见没挂上，不是正文没改。
            _is_cm = (slug == "reportc")
            _st = COMMENT_FALLBACK if _is_cm else REV_FALLBACK
            _act = "批注" if _is_cm else "改"
            if _st.get("hit"):
                cp.comments += ("\n⚠ 降级（部分）：本件已在原稿上%s，但%s——补全原稿或核对条款标题后可重跑"
                                % (_act, fallback))
            else:
                cp.comments += ("\n⚠ 降级：%s（原因：%s）——补交可编辑原稿 .docx 后可重跑获得%s"
                                % ("非原稿批注" if _is_cm else "非原稿修改", fallback,
                                   "原稿就地批注" if _is_cm else "原稿级修改"))
    except Exception:
        pass
    return doc


DELIVERY_NOTE = {
    "tracked": "本文件为《{t}》的修订版：删除线是原文、下划线是修改后文本，可在 Word/WPS「审阅」中逐条接受或拒绝。",
    "redline": "本文件为《{t}》的红线标记修订版：灰色删除线是原文、红色下划线是修改后文本，不依赖 Word 修订功能（修订版在无可用 .docx 原稿时降级而来）。",
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


def _note_text(c):
    """一条审查意见的批注正文：5 批注版与 1／4 的条款批注共用同一份措辞（一概念一处）。"""
    if not (c.get("rating") or c.get("comment") or c.get("basis") or c.get("revised")):
        return ""
    return ("【评级】%s\n【风险描述】%s\n【法律依据】%s\n【修改建议】%s"
            % (c.get("rating") or "—", c.get("comment") or "—",
               c.get("basis") or "—", c.get("revised") or "—"))


def _attach_comment(doc, runs, text):
    """把批注挂到 runs 上；失败返回 False（由调用方记 miss，不静默吞掉）。"""
    try:
        doc.add_comment(runs, text=text, author=REVIEWER or "AI 文档合规审查助手",
                        initials=(REVIEWER or "AI")[:3])
        return True
    except Exception as e:
        print("[make-docx] 批注挂载失败：%s" % str(e)[:80])
        return False


def add_clause_note(doc, runs, c):
    """条款标题上挂 1 条审查意见批注；无实质意见时不挂。

    锚点只能取条款标题：修订版的正文文字都在 w:ins／w:del 里，取不到可锚定的 run。
    措辞与 5 批注版共用 _note_text（同一份「评级／风险描述／法律依据／修改建议」口径），
    避免同一条意见在两类交付物里长得不一样。
    """
    if not runs or not can_comment(doc):
        return False
    txt = _note_text(c)
    if not txt:
        return False
    return _attach_comment(doc, runs, txt)


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

# ---------- 第 10 类「模板版」：撰写合同模板（见 drafting-guide.md）与 转模板（第十七节）两条链路共用 ----------
# spec.template 结构（全部可选，缺哪一项就少哪一节，不会报错）：
#   {"name": "模板名称",
#    "placeholders": [{"name": "{{甲方全称}}", "meaning": "…", "example": "…", "required": true}],
#    "body": "模板正文全文（含占位符）",
#    "optional": [{"name": "竞业限制", "scene": "…", "advice": "…"}],
#    "notes": "使用须知"}
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
    """4 红线标记修订版：同 tracked 的呈现口径，痕迹用删除线/下划线而非 Word 修订。

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
    """3 清洁版：零批注（可能发对方），类型信息只进文档属性与文件名。"""
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
    # v3.27.0 保真注记（§3.3）：列全轮实际产出类型的贴合度，含 CONTENT_ONLY/NEWDOC 项
    # （不列＝默认"它没问题"，使用者无从判断）。report 挪到最后生成，台账此刻已完整。
    if TIER_LEDGER:
        _TIER_CN = {"ORIGINAL": "原稿级（以原稿为底，版式未动）",
                    "QUASI_A": "准原稿A（有版式线索，已尽量贴近原稿版式重建）",
                    "QUASI_B": "准原稿B（无版式线索，按模板重建）",
                    "CONTENT_ONLY": "内容保真（内容已处理，版式不保证）",
                    "NEWDOC": "新建文书（不适用版式保真）"}
        doc.add_heading("附：本次交付物保真说明", level=2)
        for _slug in TYPE_ORDER:
            if _slug not in TIER_LEDGER:
                continue
            _tier, _reason = TIER_LEDGER[_slug]
            _line = "%s %s — %s" % (TYPE_ORDER.index(_slug) + 1, SLUGS[_slug], _TIER_CN.get(_tier, _tier))
            if _reason:
                _line += "；%s" % _reason
            doc.add_paragraph(_line)
        doc.add_paragraph("本报告引用的原文均逐字取自原稿，未经模型改写。")
    return doc

def doc_report_comments(spec):
    """5 审查意见批注版：**原稿就地批注**——正文保持原稿一字不改，意见以 Word 批注锚定到对应条款。

    有可读原稿时走 from_source_docx_comment（原稿做底，段落／run 格式／版式全不动）；
    无原稿、原稿打不开或一条都定位不到时，才回退下面「重建清单」形态——它是**新写文书**，
    不是原稿，因此必须在文件名（`-准原稿B` 档位标记）与文档属性两处标注「非原稿批注」。
    这与 1 修订版同一条硬性要求：**不得脱离原稿凭空重建正文再冒充原稿**。
    """
    _sd = from_source_docx_comment(spec)
    if _sd is not None:
        return set_meta(_sd, spec, "reportc", fallback=COMMENT_FALLBACK["reason"])
    doc = Document()
    add_report_title(doc, spec.get("report_title", "文档合规审查意见报告") + "（批注版·非原稿）")
    set_meta(doc, spec, "reportc",
             fallback=COMMENT_FALLBACK["reason"] or "未提供可编辑的 .docx 原稿")
    add_disclaimer(doc, spec)
    doc.add_paragraph("源文件：" + title(spec) + "　审查人：" + REVIEWER + "　轮次：r" + ROUND)
    doc.add_paragraph("⚠ 本件不是原稿：未拿到可编辑原稿（或原稿中一条意见都定位不到），"
                      "正文为按审查规格重建的清单，仅供阅读；意见未落在使用者上传的那份文件上。"
                      "补交原稿 .docx 后重跑即可获得原稿就地批注版。")
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
        note = _note_text(c) or "（本条款无实质意见）"
        if _ok_cm and not _attach_comment(doc, h.runs, note):
            doc.add_paragraph("批注内容：" + note.replace("\n", " "))
        elif not _ok_cm:
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

# ---------- 半档 C：以原稿 docx 做底 ＋ 段落级替换（排版保真） ----------
# 只换文字、不增删段落：字体/字号/对齐/缩进/行距/页边距/页眉页脚/表格/图片全部沿用原稿。
# 适用于"不改段落数、只换文字"的三类：3清洁版 / 6脱敏版 / 7照录版。
SOURCE_DOCX = ""   # 预读后**可用**的原稿路径（.doc 已转换）；为空时走 B 档（样式档位重建）
RAW_SOURCE_DOCX = ""   # 使用者原样给的路径（可能是 .doc/.wps，也可能路径根本不存在）


# ---------- 原稿格式预读（docx 直接用 ／ 老格式转换 ／ 转不了降级并说清原因） ----------
# **为什么按文件头判断而不按扩展名**：使用者交上来的「合同.docx」有相当一部分其实是
# Word 97-2003 二进制（改过扩展名），也可能是 WPS 的 .wps、或干脆是个加密 zip。按扩展名
# 放行，失败会发生在 Document(path) 里抛「Package not found」这类内部异常——报出来是
# python-docx 的锅，与真实原因（这是 .doc，本机没装 LibreOffice）对不上，使用者无从下手。
# 按文件头判断，才能把话说成「这是 Word 97-2003 格式，转不了」。
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SRC_PROBE = {"raw": "", "path": "", "note": "", "reason": "", "done": False,
             "kind": "none", "layout_hints": None}   # kind/layout_hints 供 resolve_tier 判档
_CONV_TMP = ""          # 转换产物所在临时目录（进程退出时清掉，不在使用者目录留垃圾）


def _zip_is_word(path):
    """zip 包是否为 Word 文档：看包内有没有 word/document.xml。"""
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            if "word/document.xml" in z.namelist():
                return True
            ct = z.read("[Content_Types].xml").decode("utf-8", "replace")
            return "wordprocessingml" in ct
    except Exception:
        return False


def _file_kind(path):
    """读文件头判断真实承载：word（OOXML Word）／zip（非 Word 的压缩包）／ole2（97-2003 二进制）／other／missing。"""
    if not path or not os.path.exists(path):
        return "missing"
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "other"
    if head[:4] == b"PK\x03\x04":
        return "word" if _zip_is_word(path) else "zip"
    if head[:8] == _OLE2_MAGIC:
        return "ole2"
    return "other"


def _convert_to_docx(path):
    """LibreOffice 无头模式把 .doc/.wps/.rtf/.odt 转成 .docx；返回 (新路径, 失败原因)。"""
    global _CONV_TMP
    import subprocess, tempfile
    if _cfgmod and not _cfgmod.tool_available(_CFG, "soffice"):
        return "", "未检测到 LibreOffice"
    outdir = _CONV_TMP or tempfile.mkdtemp(prefix="dcc-src-")
    _CONV_TMP = outdir
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as e:
        return "", "临时目录不可写（%s）" % str(e)[:60]
    target = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + ".docx")
    # 先删旧件：同名残留会让「本次转换失败」被上一次的产物冒充成成功
    try:
        if os.path.exists(target):
            os.remove(target)
    except OSError:
        pass
    cmd = [SOFFICE, "-env:UserInstallation=file://" + os.path.join(outdir, "lo-profile"),
           "--headless", "--convert-to", "docx", "--outdir", outdir, path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PDF_TIMEOUT)
    except Exception as e:
        return "", "转换进程失败（%s）" % str(e)[:60]
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target, ""
    tail = ((r.stderr or "") + (r.stdout or "")).strip().replace("\n", " ")[:80]
    return "", "LibreOffice 未产出 .docx（返回码 %s%s）" % (r.returncode, "：" + tail if tail else "")


def prepare_source(path):
    """原稿格式预读：按文件头定格式 → .docx 直接用／老格式转 .docx／不行给出人话原因。

    返回可用 `.docx` 路径（不可用返回空串）；过程与原因记在 SRC_PROBE，供各处降级标注引用。
    **同一路径只做一次**：转一次 Word 要几秒，六类交付物各转一遍纯属浪费。
    """
    path = (path or "").strip().strip('"')
    if SRC_PROBE["done"] and SRC_PROBE["raw"] == path:
        return SRC_PROBE["path"]
    SRC_PROBE.update({"raw": path, "path": "", "note": "", "reason": "", "done": True,
                      "kind": "none", "layout_hints": None})
    if not path:
        SRC_PROBE["reason"] = "未提供原稿文件"
        SRC_PROBE["kind"] = "missing"
        return ""
    ext = os.path.splitext(path)[1].lower()
    kind = _file_kind(path)
    SRC_PROBE["kind"] = kind
    if kind == "missing":
        SRC_PROBE["reason"] = "原稿路径不存在：%s" % path
        return ""
    if kind == "word":
        SRC_PROBE["path"] = path
        if ext not in ("", ".docx"):
            SRC_PROBE["note"] = ("文件头判定为 Word 文档（扩展名是 %s、实际是 .docx），已按 .docx 使用"
                                 % ext)
        return path
    if kind == "zip":
        SRC_PROBE["reason"] = ("文件是压缩包但不是 Word 文档（可能是 .xlsx/.pptx、加密包，"
                               "或扩展名标错）")
        return ""
    if kind == "ole2":
        conv, why = _convert_to_docx(path)
        if conv:
            SRC_PROBE["path"] = conv
            SRC_PROBE["note"] = ("原稿是 Word 97-2003 二进制格式（%s），已用 LibreOffice 转成 .docx 做底"
                                 "——转换只换容器不改文字，表格/图片/页眉页脚一并带来；"
                                 "若版式异常复杂，建议使用者另存为 .docx 后重跑" % (ext or ".doc"))
            return conv
        SRC_PROBE["reason"] = ("原稿是 Word 97-2003 二进制格式（%s），本机转不成 .docx：%s"
                               % (ext or ".doc", why))
        return ""
    SRC_PROBE["reason"] = "无法识别的文件格式（既不是 .docx 也不是 .doc）%s" % (("：" + ext) if ext else "")
    return ""


def _ensure_src(spec=None):
    """取已预读的原稿路径；尚未预读时按 SOURCE_DOCX → spec.source_docx 顺序补做一次。"""
    if SRC_PROBE["done"]:
        return SRC_PROBE["path"]
    return prepare_source(SOURCE_DOCX or ((spec or {}).get("source_docx") or ""))


def _cleanup_conv():
    """清掉转换用临时目录（只在进程内转过东西时才有）；失败无关紧要。"""
    if not _CONV_TMP:
        return
    try:
        import shutil
        shutil.rmtree(_CONV_TMP, ignore_errors=True)
    except Exception:
        pass


import atexit as _atexit
_atexit.register(_cleanup_conv)


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
        return lines or [x for x in original_text(spec).splitlines() if x.strip()]
    text = original_text(spec)
    if kind == "masked" and _d is not None:
        text, _, _ = _d.mask_text(text, MASK_TYPES, True)
    return [x for x in text.splitlines() if x.strip()]


def from_source_docx(spec, kind):
    """以原稿 docx 为底产出三类交付物；不可用（无原稿/打不开）时返回 None 走 B 档。

    原稿格式由 prepare_source 预读：.docx 直接用，Word 97-2003 先转 .docx 再做底。
    """
    path = _ensure_src(spec)
    if not path:
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
# 与上面「半档 C」的区别：那一档是**整段换字**（供 5/6/7），这一档是**在既有 run 之间插痕迹**
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
    原稿格式由 prepare_source 预读（.doc 会先转 .docx）。
    成功返回 doc；返回 None 表示降级（原因已写入 REV_FALLBACK["reason"]）。
    """
    path = _ensure_src(spec)
    REV_FALLBACK.update({"reason": "", "hit": 0, "miss": 0})
    if not path:
        REV_FALLBACK["reason"] = SRC_PROBE["reason"] or "未提供可编辑的 .docx 原稿"
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


# ---------- 半档 C·批注：以原稿做底挂批注（4 审查意见批注版） ----------
# 与「原稿级修订」同一套定位逻辑，区别只在**不写痕迹**：段落文字、run 格式、版式一律不动，
# 只把 note 绑到定位段落的 run 上。**不做 run 合并**——合并会重写原稿的 run 切分（同一处
# 文字被拆成多个 run 往往是因为局部加粗/下划线），批注版正文必须与原稿逐段一致，格式也不例外。
COMMENT_FALLBACK = {"reason": "", "hit": 0, "miss": 0}   # 供主流程读取并在两处标注降级


def from_source_docx_comment(spec):
    """5 批注版·原稿就地批注：以原稿为底，**正文一字不改**，每条意见挂成 Word 批注。

    成功返回 doc（原稿件，段落序列与原稿完全一致）；返回 None 表示降级，原因写入
    COMMENT_FALLBACK["reason"]，调用方回退「重建清单」形态并显式标注「非原稿批注」。

    定位**不前进 cursor**：clauses 常按风险高低排序、而非原稿顺序，前进式定位会漏掉
    排在前面的条款；批注多条挂同一段只影响观感，漏挂则等于意见没提。
    """
    COMMENT_FALLBACK.update({"reason": "", "hit": 0, "miss": 0})
    path = _ensure_src(spec)
    if not path:
        COMMENT_FALLBACK["reason"] = SRC_PROBE["reason"] or "未提供可编辑的 .docx 原稿"
        return None
    cs = clauses(spec)
    if not cs:
        COMMENT_FALLBACK["reason"] = "审查规格缺条款（clauses），无法定位批注位置"
        return None
    try:
        doc = Document(path)
    except Exception as e:
        COMMENT_FALLBACK["reason"] = "原稿打开失败（%s）" % str(e)[:60]
        print("[make-docx] 原稿就地批注回退：%s" % COMMENT_FALLBACK["reason"])
        return None
    if not can_comment(doc):
        COMMENT_FALLBACK["reason"] = "当前 python-docx 不支持批注（需 >=1.2）"
        return None

    paras = _rev_all_paras(doc)
    hit, miss = 0, []
    for c in cs:
        txt = _note_text(c)
        if not txt:
            continue                        # 无实质意见，原稿不动（与 1／4 同一口径）
        idx, mode = _rev_locate(paras, c, 0)
        if idx < 0:
            miss.append(c.get("heading") or (c.get("original") or "")[:16] or "（无标题条款）")
            continue
        p = paras[idx]
        runs = [r for r in p.runs if (r.text or "").strip()] or list(p.runs)
        if not runs:
            miss.append(c.get("heading") or (c.get("original") or "")[:16] or "（空段落）")
            continue
        if _attach_comment(doc, runs, txt):
            hit += 1
        else:
            miss.append(c.get("heading") or (c.get("original") or "")[:16])
    COMMENT_FALLBACK["hit"], COMMENT_FALLBACK["miss"] = hit, len(miss)
    if hit == 0:
        # 一条都没挂上就不叫「部分」：说成部分会让日志读起来像「大部分已挂上」，
        # 而实际交付的是重建件。此处直说回退，原因带上没对上的条款名。
        _names = "、".join(miss[:3])
        COMMENT_FALLBACK["reason"] = ("原稿中未能定位任何待批注条款%s"
                                      % (("（%s）" % _names) if _names else ""))
        print("[make-docx] 原稿就地批注回退：%s" % COMMENT_FALLBACK["reason"])
        return None
    if miss:
        COMMENT_FALLBACK["reason"] = ("%d 条意见无法在原稿中定位对应段落（%s），该部分未挂上"
                                      % (len(miss), "、".join(miss[:3])))
        print("[make-docx] 原稿就地批注（部分）：%s" % COMMENT_FALLBACK["reason"])
    print("[make-docx] 原稿就地批注：以原稿做底挂 %d 条批注、正文一字未改（%s）"
          % (hit, os.path.basename(path)))
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
    for line in original_text(spec).splitlines():
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
    text = original_text(spec)
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







def main():
    global REVIEWER, ROUND, TS, SOURCE, SOURCE_DOCX, RAW_SOURCE_DOCX
    global CURRENT_TIER, CURRENT_TIER_REASON, CURRENT_SRC_KIND, TIER_LEDGER
    ap = argparse.ArgumentParser(description="文档合规审查交付物产出（10 类型，审查人必填；类型以勾选框多选、一次全部显示供用户勾选）")
    ap.add_argument("spec")
    ap.add_argument("--out", default=None, help="输出目录（默认 D:\\文档合规审查报告\\输出）")
    ap.add_argument("--subdir", default=None, help="输出目录下再建子文件夹（按合同归档用）")
    ap.add_argument("--reviewer", default=None, help="审查人名称（必填；未提供时交互追问或报错退出）")
    ap.add_argument("--round", default=None); ap.add_argument("--ts", default=None)
    ap.add_argument("--types", default=None,
                    help="逗号分隔：tracked,report,clean,redline,reportc,masked,original,diff,compare,template（默认 1、2 两类（修订版／审查意见报告）；全部 10 类请显式列出；亦可写中文类型名）")
    # v3.25.7：默认值改哨兵 None，为的是能区分「用户没指定」与「用户显式写了 docx」。
    # 二者结果相同（都只出 WORD），但前者必须留一句提示——缺省不许不声不响。
    # 真正的兜底值在 FORMAT_FALLBACK 常量，门禁按它而不是按 default 守文档一致性。
    ap.add_argument("--formats", default=None,
                    help="逗号分隔：docx,md,excel,pdf,html,pptx,mindmap,image（不写则仅 docx；PDF 由 docx 转换；HTML 由 md 转换，加 --html-online 出在线增强版；PPT 仅 2/8/9 报告讲解类；思维导图默认出 SVG，加 --mindmap-html/--mindmap-png 追加折叠树/PNG，覆盖 2/8/9/10 四类；图片 6 种见 --image-formats，覆盖 2/8/9/10 四类）")
    # v3.32.0 image 家族的子格式开关。**必须排在 --formats 之后**：
    # check.py 的数字口径守卫用 `'"--formats".*?help="逗号分隔：([a-z,]+)'` 惰性匹配，
    # 且跨行（re.S）——若把本参数插在 --formats 之上，help 串里的 "png,jpg,..." 会被
    # 抢先匹配成格式清单，格式数守卫当场把 8 读成 6。这条注释是给下一位改参数顺序的人看的。
    ap.add_argument("--image-formats", default=None,
                    help="逗号分隔：png,jpg,webp,gif,svg,ico（仅当 --formats 含 image 时生效；不写则仅 png；"
                         "png/jpg/webp 出长图，gif 因 256 色只出概览卡，svg 零依赖，ico 按 256×256 单尺寸；"
                         "缺 Pillow 时位图跳过、svg 照出）")
    ap.add_argument("--html-online", action="store_true",
                    help="HTML 出在线增强版（渲染脚本/字体走 CDN 白名单，文件更小、需联网；默认离线单文件、零外部资源）。仅当 --formats 含 html 时生效；涉密/内网件请勿开启")
    ap.add_argument("--mindmap-html", action="store_true",
                    help="思维导图追加交互折叠树 HTML（点节点折叠/展开，断网可开）。仅当 --formats 含 mindmap 时生效")
    ap.add_argument("--mindmap-png", action="store_true",
                    help="思维导图追加 PNG 位图（老环境兜底：Office 2013 等不支持插 SVG 的场景；依赖 matplotlib＋中文字体，缺失自动跳过）。仅当 --formats 含 mindmap 时生效")
    ap.add_argument("--mindmap-pdf", action="store_true",
                    help="思维导图追加 PDF（SVG 经 LibreOffice 无头转换；依赖 soffice，缺失自动跳过）。仅当 --formats 含 mindmap 时生效")
    ap.add_argument("--mindmap-opml", action="store_true",
                    help="思维导图追加 OPML 大纲（幕布/WorkFlowy/OmniOutliner 通用交换格式，可直接导入）。仅当 --formats 含 mindmap 时生效")
    ap.add_argument("--mindmap-md", action="store_true",
                    help="思维导图追加 Markdown 大纲（H1/H2/列表，任何编辑器可读）。仅当 --formats 含 mindmap 时生效")
    ap.add_argument("--comments", action="store_true", help="兼容保留：等价于在 --types 中追加 reportc（审查意见批注版）")
    ap.add_argument("--style", default=None,
                    help="排版样式档位：default（不改动）/contract（合同风，默认）/official（公文风）；亦可写 spec.style 或 config.json 的 render.style；只对 1、3、4、6、7 五类生效（修订版/清洁版/红线/脱敏/照录）")
    ap.add_argument("--source-docx", default=None,
                    help="半档C 排版保真：原稿路径。指定后 1修订版/4红线版 在原稿 run 之间插修订痕迹、"
                         "5批注版 只在原稿上挂批注（正文一字不改）、3清洁版/6脱敏版/7照录版 只替换段落文字"
                         "（均保留字体/对齐/缩进/页边距/页眉页脚/表格）。**按文件头预读真实格式**："
                         ".docx 直接用；Word 97-2003 二进制（.doc 或改过扩展名的）自动用 LibreOffice 转 .docx；"
                         "转不了或条款定位不到则回退并按档位口径标注（文件名＋文档属性＋报告注记＋终端汇总四处）")
    ap.add_argument("--strict-fidelity-exit", action="store_true",
                    help="严格档位退出码：硬性原稿级类（1/3/4/5）落到准原稿档、或 7 有原稿却未达原稿级时，"
                         "进程退出码返回 3（默认关闭——默认只在终端汇总显式列出，不影响自动化退出码）")
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
    # 原稿格式预读：.docx 直接用，Word 97-2003 转 .docx，转不了就说清为什么——
    # 这一步在**取类型之前**做，六类交付物共用同一次预读结果（否则 .doc 会被转六遍）。
    RAW_SOURCE_DOCX = (a.source_docx or spec.get("source_docx") or "")
    SOURCE_DOCX = prepare_source(RAW_SOURCE_DOCX)
    if RAW_SOURCE_DOCX and not SOURCE_DOCX:
        print("[make-docx] 提示：原稿不可用，原稿级修订/批注类回退（降级件会标注）：%s"
              % SRC_PROBE["reason"])
    elif SRC_PROBE["note"]:
        print("[make-docx] 原稿预读：%s" % SRC_PROBE["note"])
    set_style(a.style or spec.get("style")
              or (_cfgmod.render_opt(_CFG, "style") if _cfgmod else None) or "contract")
    if _stylemod.STYLE != "default":
        print("[make-docx] 排版档位：%s（--style default 可关闭；仅对 1、3、4、6、7 五类生效）" % _stylemod.STYLE)
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
    # 修订版→红线标记修订版 降级链（仅「未提供可用 .docx 原稿」触发，详见 SKILL.md「修订类两种形态」）：
    # 选了 1 修订版但本次未提供可用 .docx 原稿时，1 自动降级为 4 红线标记修订版，
    # 差异在干净文本上以删除线/下划线标出；降级须显式提示，不静默。
    if "tracked" in types and not RAW_SOURCE_DOCX:
        _has_redline = "redline" in types
        types = [t for t in types if t != "tracked"]
        if not _has_redline:
            types.append("redline")
        print("[make-docx] 降级：修订版（1）未提供可用 .docx 原稿，自动降级为红线标记修订版（4）；"
              "审查意见报告等其余类型不受影响")
    # v3.25.7：区分「没指定」与「显式写了 docx」——结果一样，但前者要留提示。
    fmt_explicit = a.formats is not None
    fmts = [f.strip().lower() for f in (a.formats or FORMAT_FALLBACK).split(",") if f.strip()]
    bad = [f for f in fmts if f not in FORMAT_ALL]
    if bad:
        print("[make-docx] 提示：忽略无法识别的格式名 %s（可用：%s）"
              % (",".join(bad), ",".join(FORMAT_ALL)))
        fmts = [f for f in fmts if f in FORMAT_ALL]
    if not fmts:
        print("[make-docx] 错误：--formats 至少包含 %s 之一。" % " / ".join(FORMAT_ALL)); sys.exit(2)
    # v3.28.0 在线版开关的前置提示：开关被忽略/涉密提醒——不许不声不响
    if a.html_online and "html" not in fmts:
        print("[make-docx] 提示：--html-online 已忽略——本次 --formats 未含 html。")
    elif a.html_online:
        print("[make-docx] 提示：HTML 将出在线增强版（外链域白名单 %s，需联网）；"
              "涉密/内网件请去掉 --html-online 改用默认离线版。" % "、".join(HTML_CDN_ALLOW))
    # 兼容：--comments 等价于选中 reportc（批注版＝正式交付物类型 5）
    if a.comments and "reportc" not in types:
        types.append("reportc")
    # 2 审查意见报告挪到最后生成：报告注记（§3.3）要引用**全轮**档位台账，
    # 而台账只有各类都生成完才完整——报告先出就会漏注其余类的档位。
    _rep_last = "report" in types
    if _rep_last:
        types = [t for t in types if t != "report"] + ["report"]
    # 预判档位（§4.2 数据流）：tier 只依赖原稿可用性与类型要求，生成前即可判；
    # 生成后再按 fallback 修正（有原稿但定位失败 → QUASI_B）。
    _probe = {"kind": SRC_PROBE.get("kind", "none"),
              "layout_hints": SRC_PROBE.get("layout_hints")}
    TIER_MAP = {}
    for _t in types:
        TIER_MAP[_t] = resolve_tier(_t, _probe, {})[0]   # 生成前按「生成成功」预判
    made, docx_paths, TIER_LEDGER = [], [], {}   # TIER_LEDGER: slug → (tier, reason)（§3.3 注记与 §3.5 汇总共用）
    for t in types:
        if t in ("original", "masked") and not original_text(spec):
            print(f"[make-docx] 跳过 {SLUGS[t]}：spec 缺少 original_text。"); continue
        if "docx" in fmts:
            # 先产对象再取名：档位只有生成完才知道（fallback 情形会把预判档修正为 QUASI_B）
            docobj = DOC_GEN[t](spec)
            _st = ((COMMENT_FALLBACK if t == "reportc" else REV_FALLBACK)
                   if t in ("tracked", "redline", "reportc") else None)
            if _st is None:
                _state = "ok"
            elif _st.get("hit"):
                _state = "partial"   # 部分落位：仍是原稿做底，详情进属性
            else:
                _state = "fallback:%s" % (_st.get("reason") or "")
            _tier, _reason, _skind = resolve_tier(t, _probe, {t: _state})
            TIER_MAP[t] = _tier
            TIER_LEDGER[t] = (_tier, _reason)
            CURRENT_TIER, CURRENT_TIER_REASON, CURRENT_SRC_KIND = _tier, _reason, _skind
            name = outname(t, "docx", tier=_tier); p = os.path.join(a.out, name)
            docobj.save(p); made.append(name); docx_paths.append(p)
            CURRENT_TIER, CURRENT_TIER_REASON, CURRENT_SRC_KIND = "", "", ""
        # 渲染上下文（v3.31.0）：格式/风格引擎不再直读模块全局，改为显式入参。
        # 档位台账随件累积，report 类挪到最后生成正是为了让台账到此已填满。
        _ctx = RenderCtx(reviewer=REVIEWER, round=ROUND, ts=TS, source=SOURCE,
                         tier=CURRENT_TIER, tier_reason=CURRENT_TIER_REASON,
                         src_kind=CURRENT_SRC_KIND, tier_ledger=dict(TIER_LEDGER))
        if "md" in fmts and t in MD_GEN:
            name = outname(t, "md", tier=TIER_MAP.get(t, ""))
            open(os.path.join(a.out, name), "w", encoding="utf-8").write(MD_GEN[t](spec, _ctx)); made.append(name)
        if "html" in fmts and t in MD_GEN:
            name = outname(t, "html", tier=TIER_MAP.get(t, ""))
            open(os.path.join(a.out, name), "w", encoding="utf-8").write(
                html_page(t, spec, md_to_html(MD_GEN[t](spec, _ctx)), _ctx, online=a.html_online)); made.append(name)
        if "excel" in fmts:
            wb = DOC_EXCEL_GEN[t](spec)
            if wb is None:
                print("[make-docx] 提示：未安装 openpyxl，跳过 Excel 导出（pip install openpyxl 后重跑）。")
            else:
                name = outname(t, "xlsx", tier=TIER_MAP.get(t, "")); wb.save(os.path.join(a.out, name)); made.append(name)
    # 出循环后再算一次 ctx（档位台账此时才完整，供 docx 之外的家族使用）
    ctx = RenderCtx(reviewer=REVIEWER, round=ROUND, ts=TS, source=SOURCE,
                    tier_ledger=dict(TIER_LEDGER))
    if "pdf" in fmts:
        if "docx" not in fmts:
            print("[make-docx] 提示：PDF 由 docx 转换，请在 --formats 中一并包含 docx；本次跳过 PDF。")
        else:
            made += export_pdf(docx_paths, a.out)
    # v3.28.0：思维导图（一物两件）与 PPT 讲解版——覆盖集外的类型跳过并汇总提示，不许静默
    _pairs = [(t, TIER_MAP.get(t, "")) for t in types]
    if "mindmap" in fmts:
        _miss = [SLUGS[t] for t in types if t not in MINDMAP_TYPES]
        if _miss:
            print("[make-docx] 提示：思维导图仅覆盖 %s（2/8/9/10），%s 不在其列、未产出。"
                  % ("、".join(SLUGS[t] for t in MINDMAP_TYPES), "、".join(_miss)))
        made += export_mindmap([(t, TIER_MAP.get(t, "")) for t in types if t in MINDMAP_TYPES],
                               spec, a.out, ctx, want_html=a.mindmap_html, want_png=a.mindmap_png,
                               want_pdf=a.mindmap_pdf, want_opml=a.mindmap_opml, want_md=a.mindmap_md)
    if "pptx" in fmts:
        _miss = [SLUGS[t] for t in types if t not in PPT_TYPES]
        if _miss:
            print("[make-docx] 提示：PPT 讲解版仅覆盖 %s（2/8/9），%s 不在其列、未产出。"
                  % ("、".join(SLUGS[t] for t in PPT_TYPES), "、".join(_miss)))
        made += export_pptx([(t, TIER_MAP.get(t, "")) for t in types if t in PPT_TYPES], spec, a.out, ctx) or []
    if "image" in fmts:
        # v3.32.0：图片家族。子格式走 --image-formats（不写则 png 一种）。
        # 覆盖集外的类型跳过并汇总提示——与 PPT/导图同一口径，不许静默。
        _imf = [x.strip().lower() for x in (a.image_formats or IMAGE_DEFAULT).split(",") if x.strip()]
        _bad = [x for x in _imf if x not in IMAGE_TYPES]
        if _bad:
            print("[make-docx] 提示：忽略无法识别的图片子格式 %s（可用：%s）"
                  % (",".join(_bad), ",".join(IMAGE_TYPES)))
            _imf = [x for x in _imf if x in IMAGE_TYPES]
        if not _imf:
            print("[make-docx] 提示：--image-formats 无有效值，本次不出图片。")
        else:
            _hit = [t for t in types if t in IMG_TYPES]
            _miss = [SLUGS[t] for t in types if t not in IMG_TYPES]
            if _miss:
                print("[make-docx] 提示：图片仅覆盖 %s（2/8/9/10），%s 不在其列、未产出。"
                      % ("、".join(SLUGS[t] for t in IMG_TYPES), "、".join(_miss)))
            _im, _sk = export_image([(t, TIER_MAP.get(t, "")) for t in _hit], spec, a.out, ctx,
                                    want=_imf, want_long=True)
            made += _im
            for _t, _f, _why in _sk:
                print("[make-docx] 提示：图片 %s／%s 跳过（%s）。" % (SLUGS.get(_t, _t), _f, _why))
    print(f"[make-docx] 审查人={REVIEWER} 轮次=r{ROUND} 产出 {len(made)} 个文件于", os.path.abspath(a.out))
    for m in made: print("  -", m)
    # ---- v3.27.0 保真档位终端汇总（§3.5；第四外显渠道，无需选 2 也存在）----
    _TIER_CN = {"ORIGINAL": "原稿级", "QUASI_A": "准原稿A", "QUASI_B": "准原稿B",
                "CONTENT_ONLY": "内容保真", "NEWDOC": "新建"}
    _REQ3 = ("ORIGINAL_STRICT", "ORIGINAL_IF_AVAILABLE")
    _below = []   # (slug, tier, 有原稿可用)——硬性项未达原稿级
    if TIER_LEDGER:
        for _t in types:
            if _t not in TIER_LEDGER:
                continue
            _tier, _reason = TIER_LEDGER[_t]
            print("[保真汇总] %s %-14s %-11s %s"
                  % (_t, SLUGS[_t], _TIER_CN.get(_tier, _tier), _reason or ""))
            req = TIER_REQUIREMENT.get(_t, "NEWDOC_ONLY")
            if req in _REQ3 and _tier in ("QUASI_A", "QUASI_B"):
                # ORIGINAL_IF_AVAILABLE（7）：无原稿时降级即合规，不计未达标
                _orig_available = bool(SOURCE_DOCX)
                if req == "ORIGINAL_IF_AVAILABLE" and not _orig_available:
                    continue
                _below.append((_t, _tier, _orig_available))
        if _below:
            print("[保真汇总] 未达标 %d 项%s" % (len(_below),
                  ("（受 --strict-fidelity-exit 控制，本次退出码 %d）" % (3 if a.strict_fidelity_exit else 0))))
        # §3.5.2 解释行：仅当「存在未达标项 且 7 因无原稿走了准原稿档」时打印
        if _below and TIER_MAP.get("original") in ("QUASI_A", "QUASI_B") and not SOURCE_DOCX \
                and TIER_REQUIREMENT.get("original") == "ORIGINAL_IF_AVAILABLE" and "original" in TIER_MAP:
            print("[保真汇总] 说明：原文照录版（7）在无原稿时允许降级，故不计入未达标；"
                  "其余修订版/红线/批注/清洁版必须原稿级。")
    # ---- 退出码（§3.4：开关控制，默认兼容）----
    if _below and a.strict_fidelity_exit:
        sys.exit(3)
    # v3.25.7：格式缺省不许不声不响。SKILL 要求「产出前必须问一次」，但模型若不问，
    # 用户拿到手的仍只有 WORD 且毫不知情——这道尾注是那句承诺的兜底，不是替它问。
    if not fmt_explicit:
        rest = [FORMAT_LABEL[f] for f in FORMAT_ALL if f not in fmts]
        if rest:
            print("[make-docx] 提示：本次未指定 --formats，按默认只出了 %s；"
                  "另有 %s 共 %d 种可勾选获得（--formats %s），需要请说明。"
                  % (FORMAT_LABEL.get(fmts[0], fmts[0]), "／".join(rest), len(rest), ",".join(FORMAT_ALL)))

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
