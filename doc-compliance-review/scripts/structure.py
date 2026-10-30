#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""结构化引擎 —— 把文档抽取成「可校验的字段树」

用途：从合同／文书中抽出关键要素（当事人、金额、期限、违约责任、标的、
      生效条件等），输出带**原文锚点**的字段树 JSON，供批量审查、要素比对、
      法规汇编等下游使用。

设计红线
  · **每个字段必须能指回原文**。抽不出来就留空并标 `missing`，**绝不猜测、
    绝不补全、绝不用模型记忆代填**。字段树的价值在于「可信」，不是「填满」。
  · **只抽显式表述**。合同写「甲方应于 30 日内付款」才抽期限；写「另行约定」
    就标 `deferred`（另约），不能当成没写，也不能编一个数。
  · **金额必带原文串与数值两份**。原文串供人核对，数值供机器比对；
    两者必须同源，解析不出数值时数值置 null 而非 0——0 会被当成真实金额。

为什么这是「法规汇编」的地基
    汇编的输入是「领域」，不是「一份文档」。但领域要落到条文，先要把领域
    拆成可检索的要素（主体类型、行为类型、标的、场景）。本引擎提供的就是
    这层「非结构化 → 字段」的转换，检索引擎再拿字段去法规库匹配。

用法：
  python scripts/structure.py --file 某合同.docx
  python scripts/structure.py --file 某合同.docx --json out.json
  python scripts/structure.py --text "甲方应于2026年1月1日前支付货款100万元。"
  python scripts/structure.py --file x.docx --check      # 只报抽取完整度

退出码：0 抽取完成（无论完整度）；2 输入不可读。
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
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, HERE)


# ─────────────────────────── 抽取规则 ───────────────────────────
#
# 每条规则：(字段名, 中文名, 正则, 取值方式)
# 正则一律带 `(?P<v>...)` 取原文片段。宁可抽不到，不可抽错。

PARTY_RE = re.compile(
    r"(?:甲\s*方|乙\s*方|丙\s*方|买受人|出卖人|出租人|承租人|委托人|受托人|"
    r"用人单位|劳动者|借款人|贷款人|供方|需方)[：:]\s*(?P<v>[^\n，,。；;]{2,40})")

AMOUNT_RE = re.compile(
    r"(?:人民币)?\s*(?P<v>(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?:万元|亿元|元|万圆|圆))")

# 比例型金额：「合同总价 20%」「按月租金 1.5%」——违约金最常见写法，漏了等于漏掉重点
# base 只取紧邻的名词性短语（不含动词），否则会吸进「应向对方支付」这类谓语
RATE_RE = re.compile(
    r"(?P<v>(?P<base>(?:合同总价|合同价款|合同金额|总价款|总价|货款|租金|月租金|"
    r"年租金|服务费|价款|本金|月工资|工资|费用)?)\s*(?P<num>\d+(?:\.\d+)?)\s*[%％])")

# 中文分数比例：「千分之一」「万分之五」「百分之三」——逾期付款违约金的标准写法
FRAC_RE = re.compile(r"(?P<v>(?P<u>[百千万])分之(?P<n>[一二三四五六七八九十\d]+))")

DATE_RE = re.compile(
    r"(?P<v>(?:\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}))")

PERIOD_RE = re.compile(
    r"(?P<v>(?:\d+|[一二三四五六七八九十百]+)\s*(?:个)?(?:工作日|日历日|日|天|月|年|小时)"
    r"\s*(?:内|以内|之内|届满))")

SUBJECT_RE = re.compile(
    r"(?:标的|货物名称|服务内容|项目名称|产品名称)[：:]\s*(?P<v>[^\n，,。；;]{2,50})")

CLAUSE_RE = re.compile(
    r"(?:违约责任|违约金|赔偿|争议解决|管辖|保密|知识产权|解除|终止)[：:]?\s*"
    r"(?P<v>[^\n]{6,200})")

DEFERRED_RE = re.compile(r"(?:另行|另订|另签|补充协议约定|以补充协议为准|待定|由双方协商)")

# 期限里的中文数字
CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_int(s):
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + CN_NUM.get(s[1:2], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return CN_NUM.get(a, 0) * 10 + (CN_NUM.get(b, 0) if b else 0)
    return CN_NUM.get(s)


def _find_text(text):
    """返回文档全文中用于定位的规范化文本（去多余空白，保留换行以便按行取上下文）。"""
    t = (text or "").replace("\u3000", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _ctx(text, span, width=28):
    """取命中位置前后上下文——字段要能指回原文，光有值不够。"""
    a, b = span
    left = text[max(0, a - width):a].replace("\n", " ")
    right = text[b:b + width].replace("\n", " ")
    return ("…" + left if left else "") + text[a:b] + (right + "…" if right else "")


def _amount_value(numstr):
    """金额原文串 → 数值（元）。解析不出返回 None，**不返回 0**。"""
    s = (numstr or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract(text):
    """抽取字段树。返回 {fields: {...}, missing: [...], meta: {...}}。"""
    t = _find_text(text)
    fields = {}

    def put(name, label, val, span, extra=None):
        rec = {"label": label, "value": val, "anchor": _ctx(t, span)}
        if extra:
            rec.update(extra)
        fields.setdefault(name, []).append(rec)

    # 当事人
    for m in PARTY_RE.finditer(t):
        role = t[m.start():m.start() + 3]
        role = re.split(r"[：:]", role)[0].strip()
        put("party", "当事人", m.group("v").strip(), m.span("v"), {"role": role})

    # 金额（带数值）
    for m in AMOUNT_RE.finditer(t):
        raw = m.group("v").strip()
        put("amount", "金额", raw, m.span("v"),
            {"numeric": _amount_value(m.group("num"))})

    # 比例型金额（违约金常见写法）：「合同总价20%」——必须与固定金额分开记，
    # 因为它的实际金额取决于计算基数，不能直接当作一个确定数额使用
    for m in RATE_RE.finditer(t):
        raw = m.group("v").strip()
        put("rate", "比例金额", raw, m.span("v"),
            {"numeric": _amount_value(m.group("num")),
             "base": (m.group("base") or "").strip(),
             "note": "比例型，实际金额取决于计算基数"})

    # 中文分数比例：「千分之一」「万分之五」「百分之三」（日万分之五最常见）
    for m in FRAC_RE.finditer(t):
        put("rate", "比例金额", m.group("v"), m.span("v"),
            {"numeric": {"千": 0.001, "万": 0.0001, "百": 0.01}.get(m.group("u")),
             "base": "",
             "note": "分数型比例（按%s分之%s），实际金额取决于计算基数"
                     % (m.group("u"), m.group("n"))})

    # 日期
    for m in DATE_RE.finditer(t):
        put("date", "日期", re.sub(r"\s+", "", m.group("v")), m.span("v"))

    # 期限
    for m in PERIOD_RE.finditer(t):
        raw = re.sub(r"\s+", "", m.group("v"))
        mm = re.match(r"(\d+|[一二三四五六七八九十百]+)", raw)
        put("period", "期限", raw, m.span("v"),
            {"numeric": _cn_int(mm.group(1)) if mm else None})

    # 标的
    for m in SUBJECT_RE.finditer(t):
        put("subject", "标的", m.group("v").strip(), m.span("v"))

    # 关键条款（违约责任／争议解决等）
    for m in CLAUSE_RE.finditer(t):
        put("clause", "关键条款", m.group("v").strip()[:200], m.span("v"))

    # 另约标记：文档里明说「另行约定」的，不能当成漏抽
    deferred = [{"label": "另约", "value": m.group(0), "anchor": _ctx(t, m.span())}
                for m in DEFERRED_RE.finditer(t)]

    # 应有字段与实际抽到的对比
    expected = [("party", "当事人"), ("amount", "金额"), ("date", "日期"),
                ("period", "期限"), ("subject", "标的"), ("clause", "关键条款")]
    missing = [{"key": k, "label": lb,
                "note": "未识别——文档未出现显式表述，或表述方式不在已支持句式内"}
               for k, lb in expected if k not in fields]

    return {
        "fields": fields,
        "deferred": deferred,
        "missing": missing,
        "meta": {
            "chars": len(t),
            "field_kinds": len(fields),
            "total_values": sum(len(v) for v in fields.values()),
        },
    }


def render(tree, src=""):
    if not tree:
        return "（无可抽取内容）"
    out = []
    out.append("## 文档结构化抽取%s" % ("：" + src if src else ""))
    out.append("")
    m = tree["meta"]
    out.append("> 共 %d 类字段、%d 个取值（原文 %d 字）。"
               "**每个取值都带原文锚点，抽不到即标「未识别」，不猜测。**"
               % (m["field_kinds"], m["total_values"], m["chars"]))
    out.append("")

    LABELS = {"party": "当事人", "amount": "金额", "rate": "比例金额", "date": "日期",
              "period": "期限", "subject": "标的", "clause": "关键条款"}
    for key, label in LABELS.items():
        items = tree["fields"].get(key) or []
        if not items:
            out.append("### %s" % label)
            out.append("")
            out.append("> ⚠ 未识别（文档未出现显式表述）")
            out.append("")
            continue
        out.append("### %s（%d）" % (label, len(items)))
        out.append("")
        out.append("| 值 | 补充 | 原文锚点 |")
        out.append("|---|---|---|")
        for it in items:
            extra = ""
            if it.get("role"):
                extra = "主体：%s" % it["role"]
            elif key == "rate":
                extra = "基数：%s ｜ %s" % (it.get("base") or "未指明", it.get("note", ""))
            elif it.get("numeric") is not None and key == "amount":
                extra = "数值：%s" % it["numeric"]
            elif it.get("numeric") is not None and key == "period":
                extra = "数量：%s" % it["numeric"]
            anchor = (it.get("anchor") or "").replace("|", "\\|")
            val = str(it.get("value", "")).replace("|", "\\|")
            out.append("| %s | %s | %s |" % (val, extra, anchor))
        out.append("")

    if tree["deferred"]:
        out.append("### 标注为「另约」的表述（不是漏抽）")
        out.append("")
        for d in tree["deferred"]:
            out.append("- 「%s」——%s" % (d["value"], d["anchor"]))
        out.append("")

    if tree["missing"]:
        out.append("### 未识别字段")
        out.append("")
        for x in tree["missing"]:
            out.append("- **%s**：%s" % (x["label"], x["note"]))
        out.append("")

    out.append("---")
    out.append("")
    out.append("*抽取结果仅供审阅定位，不构成对条款含义的判断；"
               "字段是否成立须由执业律师结合原文认定。*")
    return "\n".join(out)


def load_text(path):
    """读入文档正文。优先走 preprocess 的提取链（含 OCR），失败则按纯文本读。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        import importlib.util as ilu
        sp = ilu.spec_from_file_location("pp", os.path.join(HERE, "preprocess.py"))
        pp = ilu.module_from_spec(sp)
        sp.loader.exec_module(pp)
        if ext in getattr(pp, "TXT_EXTS", ()):
            return io.open(path, encoding="utf-8", errors="ignore").read()
        ent = pp.process_one(path) if hasattr(pp, "process_one") else None
        if isinstance(ent, dict):
            return ent.get("text") or ""
        if isinstance(ent, str):
            return ent
    except Exception as e:                                    # noqa: BLE001
        print("[structure] 预处理器不可用（%s），尝试按文本直读。" % e, file=sys.stderr)
    try:
        return io.open(path, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        print("[structure] 无法读取 %s：%s" % (path, e), file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description="文档结构化抽取（字段树）")
    ap.add_argument("--file", help="输入文档（docx/pdf/txt/图片）")
    ap.add_argument("--text", help="直接给文本")
    ap.add_argument("--json", help="字段树输出到 JSON 文件")
    ap.add_argument("--check", action="store_true", help="只报抽取完整度，不输出明细")
    a = ap.parse_args()

    if not a.file and not a.text:
        ap.print_help()
        return 2

    src = a.file or "(inline)"
    text = a.text if a.text else load_text(a.file)
    if text is None:
        return 2

    tree = extract(text)

    if a.check:
        m = tree["meta"]
        print("抽取完整度：%d/%d 类字段，共 %d 个取值"
              % (m["field_kinds"], m["field_kinds"] + len(tree["missing"]),
                 m["total_values"]))
        for x in tree["missing"]:
            print("  未识别：%s" % x["label"])
        return 0

    print(render(tree, src if a.file else ""))

    if a.json:
        payload = {"source": src, **tree}
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[已写出字段树] %s" % a.json, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
