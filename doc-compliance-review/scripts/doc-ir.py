#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  纯文本与 spec 的中间表示 → 绝对离线，不得引入任何网络库
"""
文档内容层 · doc-ir（v3.31.0 新增）
===============================================================================
**这一层只回答「要写什么内容」，不回答「写成什么样子」**——一个函数都不得 import
python-docx / openpyxl / python-pptx / matplotlib / PIL。格式引擎（format-engine.py）
与风格引擎（style-engine.py）都依赖本层，本层不反向依赖任何一个渲染器。

为什么单独成层（v3.31.0 重构动因）
-------------------------------------------------------------------------------
重构前三件事混在一个 2900 行的 make-docx.py 里：内容怎么组织、产物什么格式、版面什么风格。
加格式要动内容函数、调风格会碰格式分支，改一处炸三处，且无法单独回归。
拆开后依赖单向：**渲染器 → 内容层**，内容层零渲染依赖，改格式不必读懂内容逻辑。

本层提供
-------------------------------------------------------------------------------
  · Artifact      渲染器统一返回契约（slug/ext/filename/payload/degraded）
  · RenderCtx     渲染上下文物件（审查人／轮次／时间／源类型／当前档位）
  · clauses() / title() / template_spec() / template_name() / original_text()
  · 差异台账      diff_rows() 及其句读对齐、字符级细分、相似度配对
  · 导图树        mm_tree()（HTML／PNG／SVG／PDF／OPML 各渲染器共用同一棵树）
  · md_diff_text() / meta_line()  与渲染器无关的文本级产出

**不改行为**：本层代码全部自 make-docx.py 原样搬迁＋改签名（全局变量改显式入参），
算法一字未动；搬迁前后由 core/_byte-golden.json 逐字节比对守护（同输入同内容）
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
import difflib
from dataclasses import dataclass, field


# ---------------------------------------------------------------- 契约对象
@dataclass
class Artifact:
    """一次渲染的产物契约。**渲染器只准返回这个**，不再各返回各的类型。

    重构前五种返回形态并存：Document（docx）／str（md/html/svg）／Workbook（xlsx）／
    list[str]（pdf 多件）／None 或 ""（生成失败只说一句原因）。调用方要按类型分支判断，
    每加一种格式就得再改一次调度循环。收成一个对象后，调度只看 ext 与 payload：

      slug       交付物类型（tracked/report/…），与 SLUGS 同键
      ext        文件扩展名，不含点（docx/md/xlsx/html/pdf/pptx/svg/png/…）
      filename   完整文件名（outname() 产出，含审查人／轮次／时间戳）
      payload    Document 对象 / 文本 / bytes / Workbook，由对应写出器消费
      degraded   降级原因；非空表示「这件是降级产物」，须在文件名与文档属性两处外显
    """
    slug: str
    ext: str
    filename: str = ""
    payload: object = None
    degraded: str = ""

    @property
    def ok(self):
        """payload 为空＝这件没出（而非出了个空文件）。"""
        return self.payload is not None and self.payload != ""


@dataclass
class RenderCtx:
    """渲染上下文：把原先的模块级全局（REVIEWER/ROUND/TS/SOURCE/档位）收成显式对象。

    全局变量的毛病是「谁改的、什么时候改的」看不出来——report 类被挪到最后生成，
    就为了等 TIER_LEDGER 填满，这种时序耦合藏在全局里没人看得出来。收成对象后，
    渲染器只拿到自己该看的字段，改上下文必须显式传。
    """
    reviewer: str = ""
    round: str = "1"
    ts: str = ""
    source: str = "contract"
    # 当前正在写入的档位（不属于档位体系的类保持空串）
    tier: str = ""
    tier_reason: str = ""
    src_kind: str = ""
    # 全轮档位台账：slug → (tier, reason)；报告类注记由此读取
    tier_ledger: dict = field(default_factory=dict)

    def meta_line(self, slug, slugs=None):
        """md/html 顶部元信息行。与渲染器无关，故留在本层。"""
        name = (slugs or {}).get(slug, slug)
        return "> %s ｜ 审查人：%s ｜ 轮次：r%s" % (name, self.reviewer, self.round)


# ---------------------------------------------------------------- 基础访问
def clauses(spec):
    """条款列表。spec 缺 clauses 时返回空表而非报错——降级由各渲染器自行决定。"""
    return spec.get("clauses", [])


def title(spec):
    """文书标题。缺 name 时退化为「合同」，保证任何 spec 都能出件。"""
    return spec.get("name", "合同")


def original_text(spec):
    """原文全文（原文照录版／原文脱敏版用）。缺 original_text 时由条款拼出。"""
    t = spec.get("original_text") or ""
    if not t and clauses(spec):
        t = "\n".join((c.get("heading", "") + "\n" + (c.get("original") or "")).strip()
                      for c in clauses(spec))
    return t


# 第 10 类「模板版」：撰写合同模板与转模板两条链路共用
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
            "notes": (t.get("notes") or "").strip(),
            # v3.34.0：《转模板溯源说明》的数据源。缺该段＝撰写模板链路（本来就没有源件），
            # 出件时不硬造一节；有该段才出，且逐项照录、不替使用者补写。
            "provenance": t.get("provenance") if isinstance(t.get("provenance"), dict) else {}}


def template_name(spec):
    return template_spec(spec)["name"] or (title(spec) + "（模板版）")


# ---------------------------------------------------------------- 细粒度修订
# 句读对齐 ＋ 块内字符级细分：只标到改动的最小范围
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


# ---------------------------------------------------------------- 差异台账
# 文件比对报告：变更内容命中以下词时，提示"涉实质条款、建议复核"
DIFF_KEY_TERMS = ["赔偿", "责任", "违约金", "定金", "付款", "支付", "价款", "价格", "税率", "发票",
                  "期限", "交付", "验收", "质量", "管辖", "仲裁", "诉讼", "保密", "知识产权",
                  "数据", "个人信息", "解除", "终止", "担保", "保证", "质保金", "转让", "独家"]
DIFF_HEADERS = ["序号", "差异定位", "变更类型", "相似度", "旧版内容", "新版内容", "影响提示"]
DIFF_KEYS = ("no", "loc", "kind", "sim", "old", "new", "hint")


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


# ---------------------------------------------------------------- 思维导图树
# 覆盖集见各渲染器的 MINDMAP_TYPES；原稿操作件不出导图（内容是逐句 diff，压成节点丢信息）。
# **数据结构单一真源**：HTML／PNG／SVG／PDF／OPML／MD 大纲各渲染器共用同一棵树，
# 不许各写一套（铁律第 12 条：一物多件须单一真源）。

def _mm_clip(s, limit=24):
    """节点文字 ≤limit 字截断（SKILL 第二十一节「一行以内」口径）；数值段不截（数字节点照录数值）。"""
    s = re.sub(r"<[^>]+>", "", s or "").strip().replace("\n", " ")
    if len(s) <= limit:
        return s
    m = re.match(r"^(.{0,%d}?)(\d[\d,.%%％]*)\s*(.*)$" % (limit - 6), s)
    if m and m.group(2) and len(m.group(3)) > 4:
        return m.group(1) + m.group(2) + "…"
    return s[:limit] + "…"


def mm_tree(slug, spec):
    """→ (root_label, [node])；node = {"text": str, "children": [node]}。层级固定 3 层（根/枝/叶）。"""
    if slug in ("report", "reportc"):
        root = spec.get("report_title", "文档合规审查意见报告")
        nodes = []
        for i, c in enumerate(clauses(spec), 1):
            leaf = []
            for k, lab in (("comment", "风险"), ("basis", "依据"), ("revised", "建议")):
                v = (c.get(k) or "").strip()
                if v:
                    leaf.append({"text": "%s：%s" % (lab, _mm_clip(v, 22)), "children": []})
            nodes.append({"text": "%d. %s %s" % (i, _mm_clip(c.get("heading") or "条款"),
                                                 c.get("rating") or ""),
                          "children": leaf})
        return root, nodes
    if slug == "diff":
        rows, note = diff_rows(spec)
        root = title(spec) + "（文件比对）"
        nodes = [{"text": "%s %s" % (r.get("loc") or ("差异" + str(r.get("no") or "")),
                                     _mm_clip(r.get("kind") or "", 10)),
                  "children": [{"text": "%s：%s" % (lab, _mm_clip(r.get(k) or "", 22)), "children": []}
                               for k, lab in (("old", "原文"), ("new", "对方稿"), ("hint", "提示"))
                               if (r.get(k) or "").strip()]}
                 for r in rows]
        return root, nodes
    if slug == "compare":
        root = title(spec) + "（新旧比对）"
        nodes = [{"text": _mm_clip(c.get("heading") or "条款"), "children": [
                    {"text": "原文：" + _mm_clip(c.get("original") or "—", 22), "children": []},
                    {"text": "修改后：" + _mm_clip(c.get("revised") or "—", 22), "children": []}]}
                 for c in clauses(spec)]
        return root, nodes
    if slug == "template":
        t = template_spec(spec)
        root = template_name(spec)
        nodes = [{"text": "占位符（%d）" % len(t["placeholders"]),
                  "children": [{"text": _mm_clip(p.get("name", "")) + ("（必填）" if p.get("required") else ""), "children": []}
                               for p in t["placeholders"][:12]]},
                 {"text": "可选条款（%d）" % len(t["optional"]),
                  "children": [{"text": _mm_clip(o.get("name") or "可选条款"), "children": []}
                               for o in t["optional"][:12]]},
                 {"text": "使用须知", "children": ([{"text": _mm_clip(t["notes"], 40), "children": []}]
                                                  if t["notes"] else [])}]
        return root, nodes
    return "", []
