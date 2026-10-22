#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法条核验（legal-articles.json 的唯一消费者）

用途：把报告／意见稿里引用的法条，逐条与本地原文库核对，输出可归档的核验表。
      核验三件事——①条号存不存在 ②引述的句子能不能在本条原文里找到 ③引的是哪一版。

设计红线：
  · 只核验，不补写。库里没有的条号一律判「待核验」，绝不凭记忆补条文。
  · 不确定就报不确定：匹配度低但高于阈值时判「表述存疑」并给出库中原文，交人裁决。
  · 零联网、零上传。库是开发侧一次性抓取落盘的，随包分发。

用法：
  python scripts/legal-verify.py --file 报告.md
  python scripts/legal-verify.py --text "根据《民法典》第五百八十五条，……"
  python scripts/legal-verify.py --file 报告.md --json out.json      # 机读结果
  python scripts/legal-verify.py --list 民法典                        # 看库里收了哪些条

退出码：0 全部通过（或全部不涉及）；1 存在「待核验／表述存疑」（不阻断出件，但须在报告中标注）。
"""
import argparse
import difflib
import io
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "core", "legal-articles.json")

# 法名识别：全称优先，简称兜底；同一法只保留最长匹配
LAW_NAMES = [
    ("中华人民共和国民法典", "民法典", ("民法典",)),
    ("中华人民共和国劳动合同法", "劳动合同法", ("劳动合同法",)),
    ("中华人民共和国劳动法", "劳动法", ("劳动法",)),
    ("中华人民共和国个人信息保护法", "个人信息保护法", ("个人信息保护法", "个保法")),
    ("中华人民共和国民事诉讼法", "民事诉讼法", ("民事诉讼法",)),
    ("中华人民共和国反不正当竞争法", "反不正当竞争法", ("反不正当竞争法",)),
    ("中华人民共和国反垄断法", "反垄断法", ("反垄断法",)),
    ("中华人民共和国著作权法", "著作权法", ("著作权法",)),
    ("中华人民共和国商标法", "商标法", ("商标法",)),
    ("中华人民共和国广告法", "广告法", ("广告法",)),
    ("中华人民共和国食品安全法", "食品安全法", ("食品安全法",)),
    ("中华人民共和国公司法", "公司法", ("公司法",)),
    ("中华人民共和国网络安全法", "网络安全法", ("网络安全法", "网安法")),
    ("中华人民共和国数据安全法", "数据安全法", ("数据安全法",)),
    ("中华人民共和国电子商务法", "电子商务法", ("电子商务法", "电商法")),
    ("中华人民共和国消费者权益保护法", "消费者权益保护法",
     ("消费者权益保护法", "消保法", "消费者保护法")),
    ("最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
     "合同编通则解释",
     ("合同编通则解释", "合同编通则司法解释", "民法典合同编通则解释")),
]

CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
      "六": 6, "七": 7, "八": 8, "九": 9}
UNIT = {"十": 10, "百": 100, "千": 1000}


def cn2int(s):
    s = (s or "").strip()
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch in CN:
            cur = CN[ch]
        elif ch in UNIT:
            total += (cur or 1) * UNIT[ch]
            cur = 0
        else:
            return None
    return total + cur


NUM = r"[一二三四五六七八九十百千零〇\d]{1,8}"
# 「《民法典》第五百八十五条」「《民法典》第 585 条」「民法典585条」
CITE_RE = re.compile(r"(《?[^》，。；：、\s（）()]{2,20}?》?)\s*第\s*(" + NUM + r")\s*条")


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s\u3000]+", "", s)


def pick_law(name):
    # 上游 CITE_RE 已要求「法名＋第X条」相邻，故此处不必再防「公司法务」这类误配——
    # 加了反而会把「…公司法」正常写法误改。只做最长匹配。
    n = norm(name).strip("《》")
    best = None
    for full, short, aliases in LAW_NAMES:
        for a in (full,) + aliases + (short,):
            if n == a or n.endswith(a) or a in n:
                if best is None or len(a) > best[0]:
                    best = (len(a), short)
    return best[1] if best else None


def load_db(path=DB):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def ratio(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def _split_items(text):
    """把条文与引述都切成「句 + 条款项」，逐段比对——整句比会被列举项稀释。"""
    t = norm(text)
    parts = re.split(r"[。；;]", t)
    out = []
    for p in parts:
        if not p:
            continue
        out.append(p)
        # 拆（一）（二）… 列举项，单项也能独立命中
        items = re.split(r"[（(][一二三四五六七八九十\d]{1,3}[）)]", p)
        out.extend(items)
    return [x for x in out if len(x) >= 4]


def _units(s, n=4):
    """取 4 字滑窗作「实质片段」。法条文言味重，4 字已能区分是否同一句话。"""
    s = norm(s)
    s = re.sub(r"[，、：（）()“”\"']", "", s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def coverage(quote, text, n=4):
    """引述的实质片段有多少比例能在条文里找到——比整句相似度稳，不怕语序与虚词差异。"""
    qu = _units(quote, n)
    if not qu:
        return 0.0
    tu = _units(text, n)
    if not tu:
        return 0.0
    return len(qu & tu) / float(len(qu))


def key_terms(quote, n=3):
    """引述里的「实词串」（3 字滑窗去重取最长的若干），用来判断是否命中同一条的独有特征。"""
    s = re.sub(r"[，、：（）()“”\"'。；]", "", norm(quote))
    if len(s) <= n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def best_window(quote, text, win=None):
    """返回 (score, cov)：score 用于排序展示，cov 用于判定是否命中本条。"""
    if not norm(quote) or not norm(text):
        return 0.0, 0.0
    if norm(quote) in norm(text):
        return 1.0, 1.0
    cov = coverage(quote, text)
    sim = 0.0
    for qs in _split_items(quote):
        for ts in _split_items(text):
            if abs(len(ts) - len(qs)) > max(len(qs), 30):
                continue
            w = max(len(qs), min(len(ts), int(len(qs) * 1.5)))
            if len(ts) <= w:
                sim = max(sim, ratio(qs, ts))
            else:
                step = max(1, len(qs) // 5)
                for i in range(0, len(ts) - w + 1, step):
                    sim = max(sim, ratio(qs, ts[i:i + w]))
    return max(cov, sim * 0.92), cov


def extract_cites(text):
    """抽引用：返回 [{law_raw, law, no, quote}]。quote 取条号后到句号/分号的一段。"""
    out, seen = [], set()
    for m in CITE_RE.finditer(text):
        raw, num = m.group(1), m.group(2)
        law = pick_law(raw)
        no = cn2int(num)
        if not law or not no:
            continue
        tail = text[m.end():m.end() + 160]
        # 引述正文：去掉紧跟的「规定/之规定/，」「：」等引导语
        tail = re.sub(r"^\s*(?:之?规定)?\s*[，,：:、]?\s*", "", tail)
        quote = re.split(r"[。；;！!？?\n]", tail)[0]
        quote = re.sub(r"^[“\"']|[”\"']$", "", quote.strip())
        key = (law, no)
        if key in seen:
            continue
        seen.add(key)
        out.append({"law_raw": raw.strip("《》 "), "law": law, "no": no,
                    "quote": quote[:120]})
    return out


def verify(cites, db, strict=0.72):
    """对每条引用给出判定。判定只有四档，不发明第五档。

    判定逻辑（双信号）：
      · 条号不在库            → 待核验
      · 没给引述正文          → 条号成立（只核到条号存在）
      · 4 字片段覆盖率 ≥ 0.62 → 通过（引述能落到本条，允许同义改写与摘引）
      · 覆盖率 0.35–0.62      → 表述存疑（像是引了本条但用词偏差大，给出原文交人裁决）
      · 覆盖率 < 0.35         → 待核验（引述与本条对不上，疑条号错位）
    """
    laws = db.get("laws") or {}
    meta = db.get("meta") or {}
    rows = []
    for c in cites:
        law, no = c["law"], c["no"]
        ents = laws.get(law) or {}
        ent = ents.get(str(no))
        m = meta.get(law) or {}
        row = {
            "law": law, "no": no, "quote": c["quote"],
            "version": m.get("version", ""), "effective": m.get("effective", ""),
            "pending": m.get("pending"),
            "status": "", "score": None, "cov": None, "anchor": "", "note": "",
        }
        if ent is None:
            row["status"] = "待核验"
            row["note"] = "本库未收录该条（库覆盖 %d 条，非全法典），须人工核现行原文" % sum(
                len(v) for v in laws.values())
        else:
            row["anchor"] = ent.get("anchor", "")
            if not c["quote"] or len(norm(c["quote"])) < 6:
                row["status"] = "条号成立"
                row["note"] = "仅核到条号存在，未提供引述正文可比对"
            else:
                sc, cov = best_window(c["quote"], ent["text"])
                row["score"] = round(sc, 3)
                row["cov"] = round(cov, 3)
                if cov >= 0.62:
                    row["status"] = "通过"
                elif cov >= 0.35:
                    row["status"] = "表述存疑"
                    row["note"] = "引述能落到本条，但用词与原文偏差较大，请对照原文补正或改为转述"
                else:
                    row["status"] = "待核验"
                    row["note"] = "引述内容在本条原文中找不到对应，疑条号错位或引述失真"
        if row["pending"]:
            p = row["pending"]
            row["note"] = (row["note"] + "；" if row["note"] else "") + \
                "《%s》已于 %s 修订、%s 施行，本库所存为 %s 版；跨该日期引用须注明所据版本" % (
                    law, p.get("version", ""), p.get("effective", ""), row["version"])
        rows.append(row)
    return rows


def render_md(rows, src=""):
    if not rows:
        return "## 法条核验表\n\n本次未检出可核验的法条引用。\n"
    ok = sum(1 for r in rows if r["status"] in ("通过", "条号成立"))
    bad = len(rows) - ok
    L = ["## 法条核验表", "",
         "> 核验对象：%s ｜ 核验方式：本地原文库逐条比对（离线，未联网）" % (src or "本报告"),
         "> 结果：共 %d 条引用，通过 %d，需人工复核 %d。" % (len(rows), ok, bad),
         "", "| # | 法律 | 条号 | 判定 | 匹配度 | 片段覆盖 | 所据版本 | 库里原文（节选） |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        L.append("| %d | 《%s》 | 第%s条 | %s | %s | %s | %s | %s |" % (
            i, r["law"], r["no"], r["status"],
            ("%.0f%%" % (r["score"] * 100)) if r["score"] is not None else "—",
            ("%.0f%%" % (r["cov"] * 100)) if r.get("cov") is not None else "—",
            r["version"] + ("（%s 施行）" % r["effective"] if r["effective"] else ""),
            (r["anchor"] or "—").replace("|", "｜"),
        ))
    notes = [r for r in rows if r["note"]]
    if notes:
        L += ["", "**逐条说明**", ""]
        for r in notes:
            L.append("- 《%s》第%s条：%s" % (r["law"], r["no"], r["note"]))
    L += ["", "> **本表只证明「与本地库一致」，不证明「现行有效」。**条文以国家法律法规数据库"
              "（flk.npc.gov.cn）与官方公报为准；标注「待核验」者不得写入正式意见。", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="法条核验（离线，比对本地原文库）")
    ap.add_argument("--file", help="待核验的文本文件（md/txt）")
    ap.add_argument("--text", help="直接给一段文本")
    ap.add_argument("--json", help="把机读结果写到该路径")
    ap.add_argument("--list", metavar="LAW", help="列出库里某部法收录的条号")
    ap.add_argument("--strict", type=float, default=0.72, help="「表述存疑」下限，默认 0.72")
    a = ap.parse_args()

    db = load_db()

    if a.list:
        law = pick_law(a.list)
        if not law:
            print("库中没有这部法：%s" % a.list)
            print("已收录：", "、".join(sorted(db.get("laws") or {})))
            return 2
        ents = db["laws"].get(law) or {}
        nos = sorted(int(k) for k in ents)
        print("《%s》收录 %d 条：%s" % (law, len(nos), "、".join(str(n) for n in nos)))
        m = (db.get("meta") or {}).get(law) or {}
        if m:
            print("版本：%s ｜ 施行：%s" % (m.get("version", ""), m.get("effective", "")))
        return 0

    text = a.text or ""
    src = ""
    if a.file:
        with io.open(a.file, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        src = os.path.basename(a.file)
    if not text.strip():
        print("没给内容：用 --file 或 --text")
        return 2

    cites = extract_cites(text)
    rows = verify(cites, db, strict=a.strict)
    md = render_md(rows, src)
    sys.stdout.write(md)

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump({"source": src, "rows": rows}, f, ensure_ascii=False, indent=1)
        print("\n机读结果：%s" % a.json)

    bad = [r for r in rows if r["status"] in ("待核验", "表述存疑")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
