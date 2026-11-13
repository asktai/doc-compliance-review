#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""模板引擎加固：占位符必填校验 ＋ 条件条款段渲染 ＋ 模板版本留痕

用途：模板版（第 10 类交付物）在**出件之前**先过这一道——
      模板里写了的占位符必须出现在说明表里，说明表标了必填的必须在出件前填实，
      条件段的开关必须有明确取值。查出来的问题逐条列出，不带病出件。

三件事：
  1. **占位符校验**：`{{名称}}` 与说明表双向对齐（模板里有而表里没有的算「未登记」，
     表里有而模板里没用的算「无用登记」）；必填项未填、或填了还是 `{{…}}` 原样，一律拦下。
  2. **条件条款段**：`{{#开关}}…{{/开关}}` 单布尔条件，取值由调用方给（True/False）。
     未给取值的开关 → 报「开关未定」，**不默认按 True 出件**（默认保留等于偷偷加条款）。
     支持一层嵌套；`{{^开关}}` 为反选（开关为假时保留本段）。
  3. **版本留痕**：元数据有三个来源，优先级 body 内的 `<!-- tpl: … -->` 行 >
     spec.template.meta > 无。解析出的版本号写进出件文档属性与文末，模板改过就换版本号。

设计红线：
  · 只校验、只渲染，**不猜**。缺值就报缺值，不拿「（待填）」之类占位词糊过去。
  · 拦下的是「出件前就能确定的问题」，不做法律判断；条款实体是否合适仍归审查判断。
  · 零联网、零上传。

用法：
  python scripts/tpl-engine.py check  <spec.json>              # 只体检，不出件
  python scripts/tpl-engine.py render <spec.json> [--switch 有第三方=1 ...]
  python scripts/tpl-engine.py manifest <模板目录>              # 派生模板清单
  python scripts/tpl-engine.py use <spec.json> --value 名=值      # 套用模板，填实占位符出具体合同
  python scripts/tpl-engine.py audit <spec.json>                 # 通用化加固自检（只报疑似，不判对错）
  python scripts/tpl-engine.py baseline <模板目录> [--update]     # 指纹基线校验／重刷

**render 与 use 的分工（别混）**：render 出的是「模板版」——正文**保留** `{{占位符}}`，
那是给使用者下次填的骨架；use 才是「套用模板」——把值填实、展开条件段，出一份**具体合同草案**。
两者共用同一套校验（必填／开关／版本留痕），但产物语义相反，故不合并成一个函数。
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）

# 输出编码自钉：本脚本可能被 check.py 等**作为子进程 spawn**，父侧按 UTF-8 解码 stdout。
# 不钉的话，中文 Windows（GBK 控制台）下会按 GBK 写出 → 父侧 UTF-8 解出 U+FFFD 乱码 →
# 判据一条都匹配不上，父侧误报「判据被删／脚本崩了」（v3.26.2 在千问办公实测到的假红）。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import argparse
import io
import json
import os
import re
import sys
import hashlib

# 占位符：{{名称}}；允许中文、字母、数字、下划线与短横，内部不许再有花括号
PH_RE = re.compile(r"\{\{\s*([^{}#/^][^{}]*?)\s*\}\}")
# 条件段：{{#开关}} … {{/开关}}；反向段 {{^开关}} … {{/开关}}
OPEN_RE = re.compile(r"\{\{\s*([#^])\s*([^{}/]+?)\s*\}\}")
CLOSE_RE = re.compile(r"\{\{\s*/\s*([^{}/]+?)\s*\}\}")
# 版本留痕行：<!-- tpl: 名称 | ver: 1.0.0 | date: 2026-01-01 | 变更: … -->
META_RE = re.compile(r"<!--\s*tpl\s*:(.*?)-->", re.S)

# 出件时允许留白的「非实质」占位符（签名、日期这类允许手签手填），仍会提示但不拦
SOFT_NAME_HINT = ("签字", "签章", "盖章", "签名", "日期", "年月日", "附件")


class TplError(Exception):
    pass


# ------------------------------------------------------------------ 加固自检（v3.34.0）
# 只查**形态**，不做法律判断：命中只报「疑似残留」，由执业律师复核决定改不改。
# 词表收的是「个案限定语」这类一看就是某一次交易专属的写法，不是条款实体是否妥当。
CASE_SPECIFIC_PATS = (
    (r"就本合同项下[^，。；\n]{0,40}而言", "个案限定语「就本合同项下…而言」"),
    (r"\d{4}\s*年\s*\d{1,2}\s*月\s*批次", "具体年月批次"),
    (r"(?:本项目|本次交易|该批次|本批次|上述批次|这一次)", "个案指代（本项目／本次交易／该批次）"),
    (r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*(?:签订|签署|生效)", "具体签约/生效日期"),
    (r"(?:甲方|乙方)\s*于\s*\d{4}", "个案时间锚点"),
    (r"(?:特定|一次性)\s*(?:项目|报价|豁免|安排)", "一次性条款用语"),
)
# 合同八大核心条款（真源：SKILL.md 第五节 B 组）。只查**关键词是否露面**，
# 不判条款写得对不对、全不全——故名称一律带「须人工核对」，不作通过/不通过结论。
CORE_CLAUSE_HINTS = (
    ("定义条款", ("定义", "术语")),
    ("标的条款", ("标的", "规格", "型号", "数量")),
    ("价格与支付", ("价款", "价格", "支付", "付款", "含税")),
    ("交付与验收", ("交付", "交货", "验收")),
    ("质量保证", ("质量保证", "保证期", "质保", "售后")),
    ("知识产权", ("知识产权", "成果归属", "许可")),
    ("违约责任", ("违约责任", "违约金", "赔偿")),
    ("争议解决", ("争议解决", "管辖", "仲裁", "诉讼")),
)

# ------------------------------------------------------------------ 元数据
def parse_meta_line(text):
    """从 `<!-- tpl: 名称 | ver: 1.0.0 | date: … | 变更: … -->` 里取字段。"""
    out = {}
    for m in META_RE.finditer(text or ""):
        for seg in re.split(r"[|｜]", m.group(1)):
            seg = seg.strip()
            if not seg:
                continue
            parts = re.split(r"[:：]", seg, 1)
            k = parts[0].strip()
            v = parts[1].strip() if len(parts) == 2 else ""
            key = {"名称": "name", "ver": "version", "version": "version",
                   "版本": "version", "date": "date", "日期": "date",
                   "变更": "change", "change": "change", "notes": "change"}.get(
                       k.lower() if k.isascii() else k)
            if key:
                out[key] = v
    if not out.get("version"):
        raise TplError("模板版本留痕缺版本号：请在模板首行写 "
                       "<!-- tpl: 名称 | ver: 1.0.0 | date: YYYY-MM-DD | 变更: … -->")
    if not re.match(r"^\d+\.\d+\.\d+$", out["version"]):
        raise TplError("模板版本号须为 X.Y.Z 形式，现为「%s」" % out["version"])
    return out


def resolve_meta(spec):
    """版本留痕三来源取其一：body 内注释行 > spec.template.meta > 报错。"""
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    body = t.get("body") or ""
    m = META_RE.search(body)
    if m:
        meta = parse_meta_line(m.group(0))
        meta["source"] = "body"
        return meta
    given = t.get("meta") if isinstance(t.get("meta"), dict) else {}
    if given.get("version"):
        if not re.match(r"^\d+\.\d+\.\d+$", str(given["version"])):
            raise TplError("模板版本号须为 X.Y.Z 形式，现为「%s」" % given["version"])
        g = dict(given)
        g["source"] = "spec"
        return g
    raise TplError("模板版没有版本留痕：在模板正文首行加 "
                   "<!-- tpl: 名称 | ver: 1.0.0 | date: YYYY-MM-DD | 变更: 初版 -->，"
                   "或在 spec.template.meta 里给 version/date/change")


def strip_meta(text):
    """版本留痕行是给机器读的，出件正文里不留。"""
    return META_RE.sub("", text or "").strip()


# ------------------------------------------------------------------ 条件段
def find_switches(text):
    """返回 (开关名集合, 错误列表)：开关必须成对、且不得交叉嵌套。"""
    errs, stack, names = [], [], set()
    tokens = []
    for m in OPEN_RE.finditer(text or ""):
        tokens.append((m.start(), "open", m.group(1), m.group(2).strip()))
    for m in CLOSE_RE.finditer(text or ""):
        tokens.append((m.start(), "close", None, m.group(1).strip()))
    tokens.sort()
    for _, kind, sigil, name in tokens:
        if kind == "open":
            stack.append(name)
            names.add(name)
        else:
            if not stack:
                errs.append("条件段闭合多余：{{/%s}} 没有对应的开始标记" % name)
                continue
            top = stack.pop()
            if top != name:
                errs.append("条件段交叉嵌套：{{#%s}} 里闭合了 {{/%s}}（须成对且不得交叉）"
                            % (top, name))
    for left in stack:
        errs.append("条件段未闭合：{{#%s}} 缺少 {{/%s}}" % (left, left))
    named = set(names)
    for m in CLOSE_RE.finditer(text or ""):
        if m.group(1).strip() not in named:
            errs.append("条件段闭合无对应开始：{{/%s}}" % m.group(1).strip())
    return names, errs


def _match_close(text, start):
    """从 start（{{#x}} 的结尾）起找配对的 {{/x}}，返回 (inner_start, inner_end, after) 。"""
    depth, pos = 1, start
    while True:
        nxt_o = OPEN_RE.search(text, pos)
        nxt_c = CLOSE_RE.search(text, pos)
        if not nxt_c:
            raise TplError("条件段未闭合")
        if nxt_o and nxt_o.start() < nxt_c.start():
            depth += 1
            pos = nxt_o.end()
            continue
        depth -= 1
        if depth == 0:
            return start, nxt_c.start(), nxt_c.end()
        pos = nxt_c.end()


def _render_segments(text, switches, errs, depth=0):
    """逐段展开条件块。不支持嵌套超过 1 层——超了直接报，避免实现与预期不一致。"""
    if depth > 1:
        raise TplError("条件段只支持一层嵌套")
    out, pos = [], 0
    while True:
        m = OPEN_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        name, sigil = m.group(2).strip(), m.group(1)
        inner_s, inner_e, after = _match_close(text, m.end())
        inner = text[inner_s:inner_e]
        if name not in switches:
            errs.append("条件段开关未定：{{%s%s}}（须显式给值，不默认保留）" % (sigil, name))
            val = False
        else:
            val = bool(switches[name])
        if sigil == "^":
            val = not val
        if val:
            out.append(_render_segments(inner, switches, errs, depth + 1))
        pos = after
    return "".join(out)


# ------------------------------------------------------------------ 占位符
def scan_placeholders(text):
    """模板正文里实际用到的占位符名（去重保序，排除条件段语法）。"""
    body = OPEN_RE.sub("", CLOSE_RE.sub("", text or ""))
    seen = []
    for m in PH_RE.finditer(body):
        n = m.group(1).strip()
        if n and n not in seen:
            seen.append(n)
    return seen


def _norm_name(s):
    return (s or "").strip().strip("{}").strip()


def check(spec, switches=None, strict_sign=True, filling=True):
    """体检：返回 dict(errors, warnings, info)。不抛异常，供出件前统一拦。

    filling=True  —— 出件模式：必填占位符必须有值（值可来自 template.values）；
    filling=False —— 体检模式：只查结构（登记是否齐、条件段是否成对、版本是否有留痕），
                     不管现在填没填。模板刚写出来时就该用这个。
    """
    errors, warns = [], []
    switches = switches or {}
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    raw_body = t.get("body") or ""
    if not raw_body.strip():
        return {"errors": ["模板正文为空：spec.template.body 缺失"], "warnings": [], "info": {}}
    try:
        meta = resolve_meta(spec)
    except TplError as ex:
        return {"errors": [str(ex)], "warnings": [], "info": {}}

    body = strip_meta(raw_body)
    # ① 条件段结构
    _, sw_errs = find_switches(body)
    errors.extend(sw_errs)
    sw_names, _ = find_switches(body)

    # ② 说明表登记
    declared = {}
    for p in (t.get("placeholders") or []):
        if not isinstance(p, dict):
            continue
        n = _norm_name(p.get("name"))
        if n:
            declared[n] = p
    used = scan_placeholders(body)
    unreg = [n for n in used if n not in declared]
    unused = [n for n in declared if n not in used]
    if unreg:
        errors.append("模板里有、说明表没登记（模板作者补说明表）：%s"
                      % "、".join("{{%s}}" % n for n in unreg))
    if unused:
        warns.append("说明表登记了、模板正文没用（删掉或补进正文）：%s"
                     % "、".join("{{%s}}" % n for n in unused))

    # ③ 必填未填（体检模式不看这一项——模板刚写出来时就该能过结构检查）
    values = t.get("values") if isinstance(t.get("values"), dict) else {}
    filled = {_norm_name(k): v for k, v in values.items()}
    blanks, still_tpl = [], []
    for n in used:
        p = declared.get(n) or {}
        req = bool(p.get("required"))
        v = filled.get(n)
        if v is None or str(v).strip() == "":
            if req:
                blanks.append(n)
            continue
        if re.search(r"\{\{[^{}]*\}\}", str(v)):
            still_tpl.append(n)
    if blanks and not filling:
        warns.append("必填占位符尚未填值（体检模式不拦，出件时必须填实）：%s"
                     % "、".join("{{%s}}" % n for n in blanks))
        blanks = []
    if blanks:
        soft = [n for n in blanks if any(k in n for k in SOFT_NAME_HINT)] if not strict_sign else []
        hard = [n for n in blanks if n not in soft]
        if hard:
            errors.append("必填占位符未填实：%s" % "、".join("{{%s}}" % n for n in hard))
        if soft:
            warns.append("签名/日期类未填（可留待手签，出件前仍建议核对）：%s"
                         % "、".join("{{%s}}" % n for n in soft))
    if still_tpl:
        errors.append("占位符填的还是占位符（等于没填）：%s"
                      % "、".join("{{%s}}" % n for n in still_tpl))

    # ④ 开关未给值（仅出件模式要求；体检模式只提示有哪些开关）
    for s in sw_names:
        if s not in switches:
            msg = "条件段开关未给值：%s（可取值 1/0、true/false、是/否）" % s
            (errors if filling else warns).append(msg)

    info = {"meta": meta, "switches": sorted(sw_names), "used": used,
            "declared": list(declared), "body": body, "template_name": (t.get("name") or "").strip()}
    return {"errors": errors, "warnings": warns, "info": info}


def render(spec, switches=None):
    """出件前渲染：必填必须已填实（filling=True），再展开条件段。"""
    r = check(spec, switches, filling=True)
    if r["errors"]:
        raise TplError("模板未通过校验，不能出件：\n  - " + "\n  - ".join(r["errors"]))
    body = r["info"]["body"]
    errs = []
    out = _render_segments(body, switches or {}, errs)
    if errs:
        raise TplError("条件段渲染失败：\n  - " + "\n  - ".join(errs))
    # 去掉因条件段被裁掉而留下的空行堆积
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, r["info"]


# ------------------------------------------------------------------ 套用模板（v3.34.0）
def fill_placeholders(body, values):
    """把 `{{名}}` 填实。返回 (正文, 未填名列表)。**不猜、不补**：没给值就报名字。"""
    v = {_norm_name(k): val for k, val in (values or {}).items()}
    missing = []

    def _sub(m):
        n = m.group(1).strip()
        if n not in v or str(v[n]).strip() == "":
            missing.append(n)
            return m.group(0)
        return str(v[n])

    out = PH_RE.sub(_sub, body or "")
    return out, sorted(set(missing))


def use_template(spec, switches=None):
    """套用：按出件口径校验 → 展开条件段 → 填实占位符 → 查残留。

    与 render() 的差别：render 保留 `{{…}}`（那是模板版），use 把值填进去（那是具体合同）。
    校验口径完全一致（必填、开关、版本留痕），不另立一套判据。
    """
    sw = switches or {}
    r = check(spec, sw, filling=True)
    if r["errors"]:
        raise TplError("套用前校验未通过：\n  - " + "\n  - ".join(r["errors"]))
    seg_errs = []
    out = _render_segments(r["info"]["body"], sw, seg_errs)
    if seg_errs:
        raise TplError("条件段渲染失败：\n  - " + "\n  - ".join(seg_errs))
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    out, missing = fill_placeholders(out, t.get("values"))
    if missing:
        raise TplError("以下占位符未给值（套用不替使用者猜）：%s"
                       % "、".join("{{%s}}" % n for n in missing))
    left = scan_placeholders(out)
    if left:
        raise TplError("填实后仍有占位符残留：%s" % "、".join("{{%s}}" % n for n in left))
    # 与 render() 同口径：条件段被裁掉后留下的空行堆积要收掉，别出一份空行连篇的合同
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, r["info"]


def spec_from_tpl(path, values=None, switches=None):
    """把库里一份 `.tpl.md` 读成 spec——「存→取→用」闭环的「取」。

    没有这份转换，use 只认 spec.json，使用者得手工把模板抄成 spec 才能套用，
    模板存下来也等于没用。占位符一律按**必填**处理（不猜哪些可选），
    开关须显式给值，沿用「不替使用者决定」的口径。
    """
    text = io.open(path, encoding="utf-8").read()
    lines = text.splitlines()
    m = META_RE.search(lines[0]) if lines else None
    if not m:
        raise TplError("模板文件首行缺版本留痕：%s" % os.path.basename(path))
    meta = parse_meta_line(m.group(0))
    body = strip_meta(text)
    used = scan_placeholders(body)
    sw_names, sw_errs = find_switches(body)
    if sw_errs:
        raise TplError("模板条件段结构有误：%s" % "；".join(sw_errs))
    return {"template": {
        "name": meta.get("name") or os.path.basename(path),
        "body": text,                      # 保留首行留痕，resolve_meta 从它取版本
        "placeholders": [{"name": "{{%s}}" % n, "meaning": "（由模板正文扫描，必填）",
                          "required": True} for n in used],
        "values": values or {},
        "switches": switches or {},
        "_from_tpl": os.path.basename(path),
    }}


def load_any(path, values=None, switches=None):
    """use/audit 的输入既可是 spec.json，也可是库里的 .tpl.md。"""
    if path.endswith(".tpl.md"):
        return spec_from_tpl(path, values, switches)
    return _read_spec(path)


# ------------------------------------------------------------------ 通用化加固自检（v3.34.0）
def audit_reinforcement(spec):
    """转模板第 4 步「通用化与加固」的**机械可检出部分**。

    返回 (疑似残留列表, 未见条款关键词列表, 留痕提示列表)。三条都只是「提示」级：
    条款实体是否合适、不利条款该不该改、必备条款是否真齐——全是法律判断，
    本函数一律不下结论，措辞固定带「须人工核对」。
    """
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    body = strip_meta(t.get("body") or "")
    suspects = []
    for i, line in enumerate(body.splitlines(), 1):
        for pat, label in CASE_SPECIFIC_PATS:
            if re.search(pat, line):
                suspects.append("第 %d 行疑似%s：%s" % (i, label, line.strip()[:60]))
                break
    unseen = [name for name, kws in CORE_CLAUSE_HINTS
              if not any(k in body for k in kws)]
    pr = t.get("provenance") if isinstance(t.get("provenance"), dict) else {}
    notes = []
    if not pr:
        notes.append("未附《转模板溯源说明》——源件、剔除项、改写项均无从反查")
    else:
        if not pr.get("rewritten"):
            notes.append("溯源说明未登记「按标准立场改写的条款」——须人工核对是否有不利条款被固化")
        if not pr.get("removed"):
            notes.append("溯源说明未登记「剔除的一次性条款」——须人工核对个案信息是否清干净")
    return suspects, unseen, notes


def audit_md(spec):
    """把自检结果排成人读的提示清单。**不产出通过/不通过结论**。"""
    suspects, unseen, notes = audit_reinforcement(spec)
    L = ["# 转模板加固自检（机械可检出部分）", "",
         "> 本清单只报**形态**疑点，不判条款对错；每条都须执业律师人工核对。",
         "> 「未见关键词」不等于条款缺失——可能是用了别的措辞，机器读不出来。", ""]
    L.append("## 一、个案限定语疑似残留（%d 处）" % len(suspects))
    L += ["- " + s for s in suspects] or ["- 未检出明显个案限定语形态（仍须人工通读）"]
    L += ["", "## 二、未见关键词的核心条款（%d 项）" % len(unseen)]
    L += ["- %s —— 须人工核对是否已用其他措辞写明" % n for n in unseen] or ["- 八组关键词均露面（仍须人工核对条款实体）"]
    L += ["", "## 三、溯源留痕提示（%d 条）" % len(notes)]
    L += ["- " + s for s in notes] or ["- 溯源说明三项齐备"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 清单派生
def scan_dir(d):
    """扫模板目录里所有 `*.tpl.md`，抽**首行**版本留痕，派生清单。

    两条收窄（v3.34.0 修）：① 只认 `.tpl.md` 后缀——原先连 `.md` 一起扫，
    派生的《模板清单.md》自己写着 `<!-- tpl: … -->` 这句示例，会被 META_RE
    当成又一份模板收进清单，清单越扫越胖；② 只认**首行**留痕，正文里引用
    这句写法的地方不再误命中。真源约定本来就是「首行写」，这里对齐它。
    """
    rows = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".tpl.md"):
            continue
        p = os.path.join(d, fn)
        try:
            text = io.open(p, encoding="utf-8").read()
        except Exception:
            continue
        first = text.splitlines()[0] if text.splitlines() else ""
        m = META_RE.search(first)
        if not m:
            continue
        try:
            meta = parse_meta_line(m.group(0))
        except TplError as ex:
            rows.append({"file": fn, "error": str(ex)})
            continue
        body = strip_meta(text)
        rows.append({"file": fn, "name": meta.get("name") or fn,
                     "version": meta.get("version"), "date": meta.get("date") or "",
                     "change": meta.get("change") or "",
                     "placeholders": scan_placeholders(body),
                     "switches": sorted(find_switches(body)[0]),
                     "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]})
    return rows


def manifest_md(rows):
    L = ["# 模板清单（自动派生，勿手改）", "",
         "> 真源是各模板首行的 `<!-- tpl: … -->` 留痕；本清单由 `scripts/tpl-engine.py manifest` 扫描生成，",
         "> `check.py` 的 check_template_library() 会比对两者是否一致——改了模板忘更新清单会直接报错。", "",
         "| 模板 | 版本 | 日期 | 占位符 | 条件开关 | 正文指纹 | 变更 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("error"):
            L.append("| %s | — | — | — | — | — | ⚠ %s |" % (r["file"], r["error"]))
            continue
        L.append("| %s | %s | %s | %d 个 | %s | `%s` | %s |"
                 % (r["name"], r["version"], r["date"], len(r["placeholders"]),
                    "、".join(r["switches"]) or "—", r["sha256"], r["change"]))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 模板库真源（v3.34.0）
MANIFEST_NAME = "模板清单.md"
BASELINE_NAME = "_tpl-baseline.json"


def manifest_path(d):
    return os.path.join(d, MANIFEST_NAME)


def verify_manifest(d):
    """清单 ↔ 实扫 逐项比对。返回问题列表（空＝一致）。

    这是把 tpl-engine.py 注释里那句「check.py 会比对」兑现成真判据：
    · 清单缺一行／多一行 → 报出双方读数；
    · 同一模板的版本、占位符数、开关、正文指纹任一项不符 → 报出双方读数；
    · 清单不存在 → 视作未建库（调用方决定要不要报错，不静默跳过）。
    """
    want = manifest_md(scan_dir(d))
    p = manifest_path(d)
    if not os.path.exists(p):
        return ["模板清单缺失：%s（跑 tpl-engine.py manifest <目录> --out <文件> 生成）" % p]
    got = io.open(p, encoding="utf-8").read()
    if got.strip() == want.strip():
        return []
    # 逐行报差，别只说「不一致」（12.5 要求报出双方读数）
    wl, gl = want.strip().splitlines(), got.strip().splitlines()
    diffs = []
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<缺行>"
        g = gl[i] if i < len(gl) else "<缺行>"
        if w != g:
            diffs.append("第 %d 行：实扫「%s」／清单「%s」" % (i + 1, w[:70], g[:70]))
        if len(diffs) >= 6:
            break
    return ["模板清单与实扫不一致（改了模板须重刷清单）：" + "；".join(diffs)]


def baseline_scan(d):
    """实扫：{文件名: {ver, sha256(正文全文)}}。"""
    out = {}
    for r in scan_dir(d):
        if r.get("error"):
            out[r["file"]] = {"error": r["error"]}
            continue
        p = os.path.join(d, r["file"])
        body = strip_meta(io.open(p, encoding="utf-8").read())
        out[r["file"]] = {"ver": r["version"],
                          "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    return out


def verify_baseline(d):
    """「改了模板没换版本号，脚本会拦下」这句承诺的判据（template-guide.md 第 23 行）。

    逐模板比对：正文 sha256 变了而 ver 没变 → 报错（改了内容必须升版本）；
    ver 变了而 sha256 没变 → 也报（版本号不能空转，须同时重刷基线）；
    基线缺该文件 → 报「未登记」，不许静默放行。返回问题列表。
    """
    p = os.path.join(d, BASELINE_NAME)
    if not os.path.exists(p):
        return ["模板指纹基线缺失：%s（跑 tpl-engine.py baseline <目录> --update 建立）" % p]
    try:
        base = json.loads(io.open(p, encoding="utf-8").read()).get("templates") or {}
    except Exception as e:
        return ["模板指纹基线解析失败：%s" % e]
    real = baseline_scan(d)
    bad = []
    for fn, cur in real.items():
        old = base.get(fn)
        if not old:
            bad.append("%s 未登记基线（跑 baseline --update）" % fn)
            continue
        if cur.get("error"):
            bad.append("%s 留痕不合规：%s" % (fn, cur["error"]))
            continue
        if old.get("ver") != cur["ver"] and old.get("sha256") == cur["sha256"]:
            bad.append("%s 版本号从 %s 改成 %s 但正文未变（空转，须同步说明）"
                       % (fn, old.get("ver"), cur["ver"]))
        elif old.get("sha256") != cur["sha256"] and old.get("ver") == cur["ver"]:
            bad.append("%s 正文已改但版本号仍是 %s（改模板须换版本号并重刷基线）"
                       % (fn, cur["ver"]))
    for fn in base:
        if fn not in real:
            bad.append("基线里的 %s 在库中已不存在（删模板须重刷基线）" % fn)
    return bad


def write_baseline(d):
    """重刷指纹基线（人工确认改动后跑）。"""
    p = os.path.join(d, BASELINE_NAME)
    io.open(p, "w", encoding="utf-8").write(json.dumps({
        "_说明": "模板正文指纹基线（tpl-engine.py baseline --update 生成）。"
                 "改模板须同时换版本号并重刷本文件；check.py 的 check_template_library() 会比对。",
        "templates": baseline_scan(d)}, ensure_ascii=False, indent=2) + "\n")
    return p


# ------------------------------------------------------------------ CLI
def _read_spec(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_switches(pairs):
    out = {}
    for s in pairs or []:
        if "=" not in s:
            raise SystemExit("开关须写成 名称=1/0，收到：%s" % s)
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().lower() in ("1", "true", "yes", "y", "是", "有")
    return out


def main():
    ap = argparse.ArgumentParser(description="模板引擎加固：占位符校验／条件段／版本留痕")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="体检模板结构（不要求必填已填，不出件）")
    c.add_argument("spec")
    c.add_argument("--switch", action="append", default=[], help="开关=1/0，可重复")

    r = sub.add_parser("render", help="按出件口径校验（必填须已填实）并渲染正文")
    r.add_argument("spec")
    r.add_argument("--switch", action="append", default=[])
    r.add_argument("--out", default=None)

    m = sub.add_parser("manifest", help="扫描模板目录，派生清单 Markdown")
    m.add_argument("dir")
    m.add_argument("--out", default=None)

    u = sub.add_parser("use", help="套用模板：填实占位符出具体合同草案（不是模板版）")
    u.add_argument("spec")
    u.add_argument("--switch", action="append", default=[])
    u.add_argument("--value", action="append", default=[], help="占位符名=值，可重复")
    u.add_argument("--out", default=None)

    au = sub.add_parser("audit", help="转模板加固自检（只报疑似残留，不判条款对错）")
    au.add_argument("spec")
    au.add_argument("--out", default=None)

    b = sub.add_parser("baseline", help="模板指纹基线：校验／--update 重刷")
    b.add_argument("dir")
    b.add_argument("--update", action="store_true")

    v = sub.add_parser("verify", help="模板库总检：清单咬合＋指纹基线")
    v.add_argument("dir")

    a = ap.parse_args()

    if a.cmd == "manifest":
        rows = scan_dir(a.dir)
        md = manifest_md(rows)
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(md)
            print("已写：%s（%d 个模板）" % (a.out, len(rows)))
        else:
            print(md)
        return 0

    if a.cmd == "baseline":
        if a.update:
            print("已重刷基线：%s" % write_baseline(a.dir))
            return 0
        bad = verify_baseline(a.dir)
        print("[E] 基线不一致（%d 项）" % len(bad) if bad else "[OK] 基线一致")
        for x in bad:
            print("  - " + x)
        return 1 if bad else 0

    if a.cmd == "verify":
        bad = verify_manifest(a.dir) + verify_baseline(a.dir)
        print("[E] 模板库总检（%d 项）" % len(bad) if bad else "[OK] 模板库清单与基线均一致")
        for x in bad:
            print("  - " + x)
        return 1 if bad else 0

    # 各分支各自读输入：audit 可吃 .tpl.md，use 还要等 --value 解析完才构造 spec，
    # check/render 才用 JSON。**不要**在这里统一 _read_spec——会把 .tpl.md 当 JSON 解析而崩。
    if a.cmd == "audit":
        spec = load_any(a.spec)
        md = audit_md(spec)
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(md)
            print("已写：%s" % a.out)
        else:
            print(md)
        return 0   # 自检只出提示，不用退出码判「过不过」——那是法律判断，不归机器

    if a.cmd == "use":
        # --value 覆盖/补齐 spec.template.values（命令行优先，便于一次性套用）
        vals, swi = {}, _parse_switches(a.switch)
        for pair in a.value:
            if "=" not in pair:
                raise SystemExit("占位符值须写成 名称=值，收到：%s" % pair)
            k, val = pair.split("=", 1)
            vals[k.strip()] = val.strip()
        # .tpl.md 直接入库取值；spec.json 则命令行覆盖 spec 里的 values/switches
        if a.spec.endswith(".tpl.md"):
            spec = load_any(a.spec, vals, swi)
        else:
            spec = _read_spec(a.spec)
            t = spec.setdefault("template", {})
            t.setdefault("values", {}).update(vals)
            t.setdefault("switches", {}).update(swi)
            swi = dict(t.get("switches") or {})
        try:
            body, info = use_template(spec, swi)
        except TplError as e:
            print("[E] " + str(e))
            return 1
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(body)
            print("[OK] 已套用：%s（模板 %s ver %s）"
                  % (a.out, info["template_name"] or "未命名", info["meta"].get("version")))
        else:
            print("-" * 60)
            print(body)
        return 0

    spec = _read_spec(a.spec)
    sw = _parse_switches(a.switch)
    filling = (a.cmd == "render")
    res = check(spec, sw, filling=filling)
    if res["errors"]:
        print("[E] 模板校验未通过（%d 项）" % len(res["errors"]))
        for e in res["errors"]:
            print("  - " + e)
    for w in res["warnings"]:
        print("[W] " + w)
    if res["info"]:
        mt = res["info"]["meta"]
        print("[i] 模板：%s ｜ 版本 %s（%s）｜ 占位符 %d 个 ｜ 开关 %d 个"
              % (res["info"]["template_name"] or "未命名", mt.get("version"),
                 mt.get("date") or "—", len(res["info"]["used"]), len(res["info"]["switches"])))

    if res["errors"]:
        return 1
    if a.cmd == "render":
        body, _ = render(spec, sw)
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(body)
            print("[OK] 已渲染：%s" % a.out)
        else:
            print("-" * 60)
            print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
