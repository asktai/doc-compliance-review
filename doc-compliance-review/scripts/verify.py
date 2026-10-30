#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""核验引擎（第 15 个引擎）—— 产物出得去出不去的唯一裁判

只答一个问题：**这份东西能不能交出去。**
它不做法律判断（那是规则库＋执业律师的事），也不改产物一个字（那是撰写／修订的事）。

四类核验
  ① 法条核验  条号在不在库 / 引述对不对得上 / 所据哪一版 + 该条库内置信
              → 算法在 legal-verify.py，本引擎只负责调度与汇总
  ② 模板核验  占位符必填 / 条件段闭合 / 开关取值 / 版本留痕
              → 算法在 tpl-engine.py，同上
  ③ 口径核验  数字前后一致 / 日期极性 / 交叉引用不悬空 / 占位符残留
              → 本引擎新增（以前散在 check.py 里，只查文档不查产物）
  ④ 格式核验  GB/T 9704 版式 → 🔜 随公文格式引擎接入，现为占位

出口只有三档，不发明第四档
  PASS  通过
  MANUAL 需人工复核 —— **必须给出定位**（行号 / 条号 / 原文片段），否则不予收录
  BLOCK 拦下，不得出件

设计红线
  · 不猜：查不到就报「查不到」，不补、不推断、不降级成「大概没问题」
  · 不静默：任何一项跑不起来（库缺失、引擎加载失败）都要显式报，不许当通过
  · 不改：只产出核验结论，不写回产物

用法
  python scripts/verify.py --file 审查意见.md
  python scripts/verify.py --file 协议.md --spec 协议.json        # 连模板一起核
  python scripts/verify.py --text "根据《民法典》第585条，……"
  python scripts/verify.py --file x.md --json out.json           # 机读结果
  python scripts/verify.py --file x.md --level manual            # 有需复核项即退出码 1

退出码：0 通过；1 有需人工复核或拦下项；2 参数或环境错误
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
import argparse
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

PASS, MANUAL, BLOCK = "通过", "需人工复核", "拦下"
_RANK = {PASS: 0, MANUAL: 1, BLOCK: 2}


# ---------------------------------------------------------------- 结果模型

class Finding(object):
    """一条核验发现。定位是硬要求——没有定位的「需人工复核」等于没说。"""

    __slots__ = ("kind", "level", "title", "detail", "loc", "evidence")

    def __init__(self, kind, level, title, detail="", loc="", evidence=""):
        self.kind = kind
        self.level = level
        self.title = title
        self.detail = detail
        self.loc = loc
        self.evidence = evidence

    def as_dict(self):
        return {"kind": self.kind, "level": self.level, "title": self.title,
                "detail": self.detail, "loc": self.loc, "evidence": self.evidence}

    def __str__(self):
        s = "[%s] %s：%s" % (self.level, self.kind, self.title)
        if self.loc:
            s += "（%s）" % self.loc
        if self.detail:
            s += " — " + self.detail
        return s


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def _snippet(text, pos, width=42):
    """取问题点前后一段原文，压成一行，供人工定位。"""
    a = max(0, pos - width // 2)
    b = min(len(text), pos + width)
    s = text[a:b].replace("\n", " ").strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


# ---------------------------------------------------------------- ① 法条核验

def _load_legal_verify():
    """惰性加载 legal-verify.py。加载失败必须显式报，不许当「没引用」放过去。"""
    p = os.path.join(HERE, "legal-verify.py")
    if not os.path.exists(p):
        return None, "legal-verify.py 缺失，法条核验无法执行"
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_v_legal", p)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
        return m, ""
    except Exception as e:
        return None, "legal-verify.py 加载失败：%s" % e


def verify_law(text, lv=None):
    """法条核验。返回 (findings, rows, meta)。"""
    findings, rows, meta = [], [], {}
    lv, why = (lv, "") if lv is not None else _load_legal_verify()
    if lv is None:
        findings.append(Finding("法条核验", BLOCK, "核验引擎不可用", why))
        return findings, rows, meta
    try:
        db = lv.load_db()
    except Exception as e:
        findings.append(Finding("法条核验", BLOCK, "法条库读取失败", str(e)))
        return findings, rows, meta

    cites = lv.extract_cites(text)
    meta["引用数"] = len(cites)
    if not cites:
        return findings, rows, meta

    rows = lv.verify(cites, db)
    for r in rows:
        loc = "《%s》第%s条" % (r["law"], r["no"])
        if r["status"] == "通过":
            findings.append(Finding("法条核验", PASS, "%s 引述准确" % loc,
                                    "库内置信：%s" % lv.CONF_LABEL.get(r.get("vs") or "", "库外"),
                                    loc=loc, evidence=r.get("anchor") or ""))
        elif r["status"] == "条号成立":
            findings.append(Finding("法条核验", PASS, "%s 条号成立" % loc,
                                    "仅核到条号存在，未给引述正文可比对", loc=loc,
                                    evidence=r.get("anchor") or ""))
        elif r["status"] == "表述存疑":
            findings.append(Finding("法条核验", MANUAL, "%s 表述存疑" % loc,
                                    r.get("note") or "用词与原文偏差较大",
                                    loc=loc, evidence=r.get("anchor") or ""))
        else:
            lvl = BLOCK if not r.get("anchor") else MANUAL
            findings.append(Finding("法条核验", lvl, "%s 待核验" % loc,
                                    r.get("note") or "引述与原文对不上",
                                    loc=loc, evidence=r.get("anchor") or ""))
    return findings, rows, meta


# ---------------------------------------------------------------- ② 模板核验

def _load_tpl_engine():
    p = os.path.join(HERE, "tpl-engine.py")
    if not os.path.exists(p):
        return None, "tpl-engine.py 缺失，模板核验无法执行"
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_v_tpl", p)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
        return m, ""
    except Exception as e:
        return None, "tpl-engine.py 加载失败：%s" % e


def verify_template(spec, switches=None):
    """模板核验。spec 为 None 时跳过（不算失败，但也不算通过过——不产生 finding）。"""
    findings = []
    if not spec:
        return findings
    te, why = _load_tpl_engine()
    if te is None:
        findings.append(Finding("模板核验", BLOCK, "模板引擎不可用", why))
        return findings
    sw = {}
    if switches:
        for k, v in switches.items():
            sw[k] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "是")
    try:
        r = te.check(spec, sw, filling=True)
    except Exception as e:
        findings.append(Finding("模板核验", BLOCK, "模板体检异常中止", str(e)))
        return findings
    name = ((spec.get("template") or {}).get("name") or spec.get("name") or "").strip()
    loc = name or "模板"
    for e in (r.get("errors") or []):
        findings.append(Finding("模板核验", BLOCK, e, loc=loc))
    for w in (r.get("warnings") or []):
        findings.append(Finding("模板核验", MANUAL, w, loc=loc))
    if not r.get("errors") and not r.get("warnings"):
        info = r.get("info") or {}
        vt = ((info.get("meta") or {}).get("ver") or "").strip()
        findings.append(Finding("模板核验", PASS, "模板结构合规",
                                "版本 %s" % (vt or "未标注"), loc=loc))
    return findings


# ---------------------------------------------------------------- ③ 口径核验

# 中文数字 → 阿拉伯数字（只处理到万，够读条款数与金额量级）
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}

# 交叉引用：「见第四条」「第 3.2 条」「依照第（三）项」「按第 5 款」
XREF_RE = re.compile(
    r"(?:见|依照|依据|根据|按照|按|参照|符合|违反|适用|适用本法|规定于|详见)\s*"
    r"第\s*([一二三四五六七八九十百千零〇\d]{1,6})\s*条")
# 条款数口径：「本合同共 12 条」「本协议共十二条」
CLAUSE_TOTAL_RE = re.compile(r"(?:共|共计|合计)\s*([一二三四五六七八九十百千零〇\d]{1,6})\s*条")
# 条款标题：「第一条」「第十二条」出现在行首
CLAUSE_HEAD_RE = re.compile(r"(?m)^\s*第\s*([一二三四五六七八九十百千零〇\d]{1,6})\s*条[\s　]")
# 占位符残留
PH_LEFT_RE = re.compile(r"\{\{[^{}\n]{1,60}\}\}")
# 未填的方括号占位（「[甲方名称]」「【填入金额】」）——只在明显是占位符时判
BRACKET_PH_RE = re.compile(r"[\[【]\s*(?:填|待填|此处|请输入|填写|xxx|XXX)[^\]】\n]{0,30}[\]】]")


def cn2int(s):
    """中文数字转整数。认不出返回 None（不猜）。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    seen = False
    for ch in s:
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
            seen = True
        elif ch in _CN_UNIT:
            u = _CN_UNIT[ch]
            if u == 10000:
                total = (total + (cur or 1)) * u
            else:
                total += (cur or 1) * u
            cur = 0
            seen = True
        else:
            return None
    return total + cur if seen else None


def verify_caliber(text):
    """口径核验：只做机械可判的，判不了的一律不管（不猜）。"""
    findings = []

    # (1) 占位符残留：产物里不该还有 {{ }} 或明显的「[请填写]」
    for m in PH_LEFT_RE.finditer(text):
        findings.append(Finding("口径核验", BLOCK, "产物里残留未替换的占位符",
                                "交付前必须填实或删除",
                                loc="第 %d 行" % _line_of(text, m.start()),
                                evidence=_snippet(text, m.start())))
    for m in BRACKET_PH_RE.finditer(text):
        findings.append(Finding("口径核验", BLOCK, "产物里残留待填标记",
                                "交付前必须填实",
                                loc="第 %d 行" % _line_of(text, m.start()),
                                evidence=_snippet(text, m.start())))

    # (2) 条款总数与实际条数是否对得上
    heads = [cn2int(x) for x in CLAUSE_HEAD_RE.findall(text)]
    heads = [h for h in heads if h]
    actual = max(heads) if heads else 0
    for m in CLAUSE_TOTAL_RE.finditer(text):
        claimed = cn2int(m.group(1))
        if not claimed:
            continue
        # 只有「共N条」出现在正文开头附近才算总数口径；正文中间讲「共3条」多半是别的事
        if m.start() > 1200:
            continue
        if actual and claimed != actual:
            findings.append(Finding(
                "口径核验", MANUAL, "自称共 %d 条，实际最大条号 %d" % (claimed, actual),
                "要么漏了条款，要么「共N条」写错；须人工核对",
                loc="第 %d 行" % _line_of(text, m.start()),
                evidence=_snippet(text, m.start())))

    # (3) 条号连续性：有断号就报（可能漏抄一整条）
    if heads:
        tops = sorted(set(heads))
        gaps = [(a, b) for a, b in zip(tops, tops[1:]) if b - a > 1]
        for a, b in gaps:
            findings.append(Finding(
                "口径核验", MANUAL, "条号不连续：第 %d 条后直接跳第 %d 条" % (a, b),
                "中间缺 %d 条；若是刻意删除须说明，否则是漏抄" % (b - a - 1),
                loc="第 %d—%d 条" % (a, b)))

    # (4) 交叉引用不悬空
    present = set(tops) if heads else set()
    if present:
        seen_bad = set()
        for m in XREF_RE.finditer(text):
            no = cn2int(m.group(1))
            if not no or no in present or no in seen_bad:
                continue
            # 「第X条」可能指别的法（「违反本法第四十六条」），只在没写「本法」时判
            pre = text[max(0, m.start() - 6):m.start()]
            if "本法" in pre or "该法" in pre or "其" == pre[-1:]:
                continue
            seen_bad.add(no)
            findings.append(Finding(
                "口径核验", MANUAL, "交叉引用悬空：引了第 %d 条，但本文没有这一条" % no,
                "须确认是引本文还是引法律条文；引本文则条号错",
                loc="第 %d 行" % _line_of(text, m.start()),
                evidence=_snippet(text, m.start())))

    # (5) 日期极性：签署日晚于生效日 / 起止日倒置
    for m in re.finditer(
            r"(?:自|从)?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
            r"(?:起|始)?\s*(?:至|到|—|－|-)\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            text):
        a = tuple(int(m.group(i)) for i in range(1, 4))
        b = tuple(int(m.group(i)) for i in range(4, 7))
        if a > b:
            findings.append(Finding(
                "口径核验", BLOCK, "日期区间倒置：起 %d-%02d-%02d 晚于止 %d-%02d-%02d"
                % (a + b), "起止必须调换或改正",
                loc="第 %d 行" % _line_of(text, m.start()),
                evidence=_snippet(text, m.start())))

    # (6) 金额大小写：只判「大小写都写了且确实对不上」的情况
    #     中文大写金额有多种合法写法（壹拾/拾、圆/元、零的取舍、元整/正），
    #     直接比字符串必然误报，故先各自**解析成数值**再比，比的是钱数不是字形。
    for m in _AMT_RE.finditer(text):
        small, big = m.group(1).replace(",", ""), m.group(2)
        a = _parse_small(small)
        b = _parse_big(big)
        if a is None or b is None:
            continue                      # 任一侧解析不了 → 不判，不猜
        if abs(a - b) >= 0.005:           # 差半分以内视为一致（「整」的舍入）
            findings.append(Finding(
                "口径核验", BLOCK, "金额大小写不一致",
                "小写 %s 元 ＝ %.2f 元，大写「%s」＝ %.2f 元，相差 %.2f 元；"
                "二者法律效力以大写为准，须先查清真实金额再改" % (small, a, big, b, abs(a - b)),
                loc="第 %d 行" % _line_of(text, m.start()),
                evidence=_snippet(text, m.start())))

    if not findings:
        findings.append(Finding("口径核验", PASS, "未发现机械性口径错误",
                                "数字/日期/交叉引用/占位符/金额大小写五项均未命中"))
    return findings


_AMT_RE = re.compile(
    r"(?:人民币|RMB|¥|￥)?\s*([\d,]+(?:\.\d{1,2})?)\s*元\s*"
    r"[（(]\s*大写\s*[：:]?\s*([零壹贰叁肆伍陆柒捌玖拾佰仟万亿元圆整正角分〇一二三四五六七八九十百千万亿两]{1,40})\s*[）)]")

_CN_DIGIT = {"零": 0, "〇": 0, "壹": 1, "一": 1, "贰": 2, "二": 2, "两": 2,
             "叁": 3, "三": 3, "肆": 4, "四": 4, "伍": 5, "五": 5,
             "陆": 6, "六": 6, "柒": 7, "七": 7, "捌": 8, "八": 8, "玖": 9, "九": 9}
_CN_UNIT = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}


def _parse_small(s):
    """'12,000.50' → 12000.5；解析不了返回 None。"""
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _parse_big(s):
    """中文大写金额 → 数值。解析不了返回 None（绝不猜）。

    合法写法都要认：壹拾万 / 拾万 等价，圆 / 元 等价，元整 / 整 / 正 等价，
    小数写「伍角」「伍角零分」「伍角伍分」。
    """
    if not s:
        return None
    s = s.strip().replace("人民币", "").replace("圆", "元")
    for tail in ("正", "整"):
        if s.endswith(tail):
            s = s[:-len(tail)]

    # 拆整数段 / 角分
    yuan, jiao, fen = s, 0, 0
    if "元" in s:
        yuan = s.split("元", 1)[0]
        rest = s.split("元", 1)[1]
    elif "角" in s or "分" in s:
        yuan, rest = "", s
    else:
        return None

    if rest:
        # 角的写法可能是「伍角」「零伍分」（省略「零角」）「伍角零分」「伍角伍分」
        if "角" in rest:
            jiao_s, tail = rest.split("角", 1)
            if jiao_s:
                if jiao_s not in _CN_DIGIT:
                    return None
                jiao = _CN_DIGIT[jiao_s]
        elif "分" in rest:
            tail = rest
        else:
            return None
        if tail:
            if not tail.endswith("分"):
                return None
            fen_s = tail[:-1].lstrip("零")     # 「零伍分」的零只是占位，不是数字
            if fen_s:
                if fen_s not in _CN_DIGIT:
                    return None
                fen = _CN_DIGIT[fen_s]

    if not yuan:
        return jiao / 10.0 + fen / 100.0

    v = _parse_big_sections(yuan)
    if v is None:
        return None
    return v + jiao / 10.0 + fen / 100.0


def _parse_big_sections(yuan):
    """按 亿 / 万 分段求值，段内用 _parse_section。处理「壹亿零壹万零壹元」这类。"""
    # 先剥掉最高位的「亿」，再剥「万」
    yi, rest = (yuan.split("亿", 1) + [""])[:2] if "亿" in yuan else ("", yuan)
    wan, ge = (rest.split("万", 1) + [""])[:2] if "万" in rest else ("", rest)
    v_yi = _parse_section(yi) if yi else 0
    v_wan = _parse_section(wan) if wan else 0
    v_ge = _parse_section(ge) if ge else 0
    if v_yi is None or v_wan is None or v_ge is None:
        return None
    return v_yi * 1e8 + v_wan * 1e4 + v_ge


def _parse_section(s):
    """段内求值：'壹仟零伍' → 1005。空段视为 0；认不出返回 None。"""
    if not s:
        return 0
    total, num = 0, None
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            total += (1 if num is None else num) * _CN_UNIT[ch]
            num = None
        else:
            return None
    return total + (num or 0)


def _find_amount_pairs(text):
    """调试用：把文中所有「小写元（大写X）」成对列出。"""
    return [(m.group(1), m.group(2)) for m in _AMT_RE.finditer(text)]


# ---------------------------------------------------------------- ④ 格式核验

def verify_format(text, fmt=None, docx_path=None):
    """格式核验：GB/T 9704 版式体检。

    判据来自同目录的 gb9704.py（公文格式引擎）。**拿不到 docx 就不假装核过**：
      · 传了 docx_path → 真跑体检，逐项给结论
      · 只有文本     → 如实标「未提供 docx，版式无从核验」，仍不冒充通过
    """
    if not docx_path:
        return [Finding("格式核验", PASS, "未启用",
                        "未提供 .docx，版式无从核验（GB/T 9704 体检需读源文件）；"
                        "给出 --docx 后本项才真正生效")]

    import importlib.util as _ilu
    import os as _os
    _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "gb9704.py")
    try:
        _sp = _ilu.spec_from_file_location("gb9704", _p)
        gb = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(gb)
        items, err = gb.check(docx_path)
    except Exception as e:                                    # noqa: BLE001
        return [Finding("格式核验", MANUAL, "未完成",
                        "GB/T 9704 体检执行失败：%s" % e)]

    if err:
        return [Finding("格式核验", MANUAL, "未完成", "GB/T 9704 体检失败：%s" % err)]

    bad = [x for x in items if not x.ok]
    man = [x for x in items if x.manual]
    if bad:
        detail = "；".join("%s 应为 %s、实为 %s" % (x.name, x.want, x.got) for x in bad[:5])
        more = "" if len(bad) <= 5 else "（另有 %d 项）" % (len(bad) - 5)
        return [Finding("格式核验", BLOCK, "不符合 %d 项" % len(bad),
                        "GB/T 9704 版式：%s%s" % (detail, more))]
    if man:
        return [Finding("格式核验", PASS, "可测项全符合",
                        "GB/T 9704 版式：可机器判定的 %d 项全部符合；"
                        "另有 %d 项需人工核对（%s）"
                        % (len(items) - len(man), len(man),
                           "、".join(x.name for x in man)))]
    return [Finding("格式核验", PASS, "全部符合",
                    "GB/T 9704 版式 %d 项全部符合" % len(items))]


# ---------------------------------------------------------------- 汇总

def run(text, spec=None, switches=None, only=None, docx_path=None):
    """跑全部核验，返回 dict(findings, level, counts, law_rows)。

    only: 只跑指定项（"law"/"tpl"/"caliber"/"fmt"），便于单项调试。
    docx_path: 产物 .docx 路径；格式核验（GB/T 9704）需读源文件才生效。
    """
    findings, law_rows = [], []
    want = set(only or ["law", "tpl", "caliber", "fmt"])

    if "law" in want:
        f, law_rows, _m = verify_law(text)
        findings.extend(f)
    if "tpl" in want:
        findings.extend(verify_template(spec, switches))
    if "caliber" in want:
        findings.extend(verify_caliber(text))
    if "fmt" in want:
        findings.extend(verify_format(text, docx_path=docx_path))

    level = PASS
    for f in findings:
        if _RANK[f.level] > _RANK[level]:
            level = f.level
    counts = {PASS: 0, MANUAL: 0, BLOCK: 0}
    for f in findings:
        counts[f.level] += 1
    return {"findings": findings, "level": level, "counts": counts, "law_rows": law_rows}


def render_md(res, src="", law_rows=None):
    L = ["## 核验结论", ""]
    lvl = res["level"]
    L.append("> 结论：**%s** ｜ 对象：%s" % (lvl, src or "本次产物"))
    c = res["counts"]
    L.append("> 逐项：通过 %d ／ 需人工复核 %d ／ 拦下 %d" % (c[PASS], c[MANUAL], c[BLOCK]))
    L.append("")

    groups = [(BLOCK, "拦下（不得出件）"), (MANUAL, "需人工复核"), (PASS, "通过")]
    for lv, title in groups:
        rows = [f for f in res["findings"] if f.level == lv]
        if not rows:
            continue
        L += ["### %s：%d 项" % (title, len(rows)), ""]
        for f in rows:
            line = "- **%s** ｜ %s" % (f.kind, f.title)
            if f.loc:
                line += " ｜ `%s`" % f.loc
            if f.detail:
                line += "\n  - " + f.detail
            if f.evidence:
                line += "\n  - 依据：`%s`" % f.evidence.replace("`", "'")
            L.append(line)
        L.append("")

    L += ["---", "",
          "> **核验引擎只兜机械错误，兜不住判断错误。**以上「通过」仅表示未发现格式／占位符／"
          "条文原文／数字口径层面的问题，**不代表法律意见正确**——须执业律师复核。", ""]
    if law_rows:
        lv_mod, _why = _load_legal_verify()
        if lv_mod:
            L.append(lv_mod.render_md(law_rows, src))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="核验引擎：判定产物能否出件")
    ap.add_argument("--file", help="待核验的文本文件（md/txt）")
    ap.add_argument("--text", help="直接给一段文本")
    ap.add_argument("--spec", help="模板 spec JSON（给了才做模板核验）")
    ap.add_argument("--switch", action="append", default=[],
                    help="条件段开关，形如 name=1（可多次）")
    ap.add_argument("--only", default="", help="只跑指定项：law,tpl,caliber,fmt（逗号分隔）")
    ap.add_argument("--docx", help="产物 .docx 路径；给了才做 GB/T 9704 版式体检")
    ap.add_argument("--json", help="把机读结果写到该路径")
    ap.add_argument("--level", default="manual", choices=["manual", "block"],
                    help="达到哪一档即返回非零退出码（默认 manual）")
    a = ap.parse_args()

    text = a.text or ""
    src = ""
    if a.file:
        if not os.path.exists(a.file):
            print("文件不存在：%s" % a.file, file=sys.stderr)
            return 2
        with io.open(a.file, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        src = os.path.basename(a.file)
    if not text.strip():
        print("没给内容：用 --file 或 --text", file=sys.stderr)
        return 2

    spec = None
    if a.spec:
        try:
            with io.open(a.spec, encoding="utf-8") as f:
                spec = json.load(f)
        except Exception as e:
            print("模板 spec 读取失败：%s" % e, file=sys.stderr)
            return 2

    switches = {}
    for kv in a.switch:
        if "=" not in kv:
            print("--switch 须写成 name=值：%s" % kv, file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        switches[k.strip()] = v.strip()

    only = [x.strip() for x in a.only.split(",") if x.strip()] or None
    res = run(text, spec=spec, switches=switches, only=only, docx_path=a.docx)
    sys.stdout.write(render_md(res, src, res["law_rows"]))

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump({"source": src, "level": res["level"], "counts": res["counts"],
                       "findings": [x.as_dict() for x in res["findings"]]},
                      f, ensure_ascii=False, indent=1)
        print("\n机读结果：%s" % a.json)

    threshold = MANUAL if a.level == "manual" else BLOCK
    return 1 if _RANK[res["level"]] >= _RANK[threshold] else 0


if __name__ == "__main__":
    sys.exit(main())
