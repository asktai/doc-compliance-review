#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
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
import datetime
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
    # v3.26.5 新增三部（随离线库一起入册）。刑法名短，须靠「最长匹配」压住
    # 「…刑法」以外的误配；发票管理办法与药品管理法是行政法规/法律，别号各一。
    ("中华人民共和国刑法", "刑法", ("刑法", "中华人民共和国刑法")),
    ("中华人民共和国发票管理办法", "发票管理办法",
     ("发票管理办法", "中华人民共和国发票管理办法")),
    ("中华人民共和国药品管理法", "药品管理法", ("药品管理法", "中华人民共和国药品管理法")),
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
_SUB = r"[一二三四五六七八九十]{1,3}"
# 「《民法典》第五百八十五条」「《民法典》第 585 条」「民法典585条」
# 「《刑法》第二百零五条之一」——增设条必须一起吃掉，否则 205 之一会被当成 205，
# 核验时拿 205 条的原文去比「虚开发票罪」的引述，判「引述与原文不符」——错怪用户。
CITE_RE = re.compile(r"(《?[^》，。；：、\s（）()]{2,20}?》?)\s*第\s*(" + NUM + r")\s*条"
                     r"(?:\s*之(" + _SUB + r"))?")

# 「旧第X条 → 新第Y条」映射（v3.26.11 · H-08）
# ----------------------------------------------------------------
# 库里三部法的 meta.note **早就写着**这种对照（发票办法「旧第二十二条（禁止虚开）→
# 新第二十一条」、反不正当竞争法「旧第七（商业贿赂）→新第八」等），但核验表**从不输出**它。
# 于是使用者引旧条号时只读到「疑条号错位或引述失真」，一律理解成「库里没这条」——
# 把「条号旧了」记成了「库缺条」，直接损害对库的信任。
# 本正则吃两种写法：「旧第七（商业贿赂）→新第八」（「条」字可省）与「旧第二十二条 → 新第二十一条」。
_OLDNEW_RE = re.compile(
    r"旧第\s*(" + NUM + r")\s*条?\s*(?:（[^）]{0,24}）)?\s*[→\-—>]+\s*新第\s*(" + NUM + r")\s*条?")


def art_key(no):
    """条号归一为字符串键：「205」「205.1」（＝第二百零五条之一）。

    为什么必须区分「之一」（v3.26.5）
    ------------------------------------------------------------------
    收《刑法》入离线库时撞上的硬问题：第 205 条（虚开增值税专用发票罪）与
    第 205 条之一（虚开发票罪）是**两个独立罪名、两套刑罚**，用同一个条号会互相覆盖
    （解析侧「同号取正文更长者」，205 之一 直接被 205 吞掉）。
    《刑法》里「之X」条有 53 处，不区分就全都查不到，而且看不出少了。
    故条号统一为字符串：主条 "205"，增设条 "205.1"。其余法的键本来就是 "205" 这种字符串，
    不受影响。
    """
    if isinstance(no, str):
        return no
    return str(no)


def art_base(no):
    """取主条号（"205.1" → 205），供排序、区间压缩、位移比对使用。"""
    try:
        return int(float(art_key(no)))
    except (TypeError, ValueError):
        return 0


def art_label(no):
    """条号标签（自带「条」字）：「205」→「205条」，「205.1」→「205条之一」。

    调用处一律写「第%s」而不是「第%s条」——「之一」两个字的正确位置在「条」之后，
    写成「第205 之一条」既不成话，也会让条号解析正则匹配不到。
    """
    s = art_key(no)
    if "." not in s:
        return s + "条"
    a, b = s.split(".", 1)
    cn = "一二三四五六七八九十"
    try:
        k = int(b)
    except ValueError:
        return s + "条"
    return "%s条之%s" % (a, cn[k - 1] if 1 <= k <= 10 else b)


def parse_no(num, sub=None):
    """把「条号 ＋ 可选之X」转成库键：("二百零五", None) → "205"；("205", "一") → "205.1"。"""
    n = cn2int(num)
    if not n:
        return None
    if sub:
        k = cn2int(sub)
        if k:
            return "%d.%d" % (n, k)
    return str(n)


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[\s\u3000]+", "", s)


def old_new_map(note):
    """从 meta.note 抠出「旧第X条 → 新第Y条」对照，返回 {旧号 int: 新号 int}（v3.26.11 · H-08）。

    ## 为什么从人读的 note 里抠，不另建结构化字段

    另建 `"old_no": {"22": "21"}` 要动建库脚本、20 部法的元数据与巡检链；而 note 里这段话
    **是同一事实的另一种写法，且已经过人工核过一遍**（写它的时候就是在提醒换版）。
    从它抠出机器可用的对照，比另存一份更不容易漂——铁律 12.2「一概念一处」，两处各存必漂。

    ## 反向核对

    抠出来的 (旧→新) 在 `verify()` 里只作**提示**用，绝不改判、绝不据它补条文：
    命中只说明「你引的这个号，是这部法改版前的编号」，条文本身仍要靠库里的原文比。
    """
    out = {}
    for m in _OLDNEW_RE.finditer(note or ""):
        a, b = cn2int(m.group(1)), cn2int(m.group(2))
        if a and b and a != b:
            out[a] = b
    return out


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
        no = parse_no(num, m.group(3))
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


# 置信来源说明：库里这条有没有被多源交叉验证过。
# 交叉验证只管「多个独立来源的同一段文字是否一致」，管不了「这条法还现行有效没有」——
# 两者必须分开说，否则「已核」会被读成「绝对正确」。
CONF_NOTE = {
    "multi-ok": "",                    # 已多源一致，无需额外提示
    "single": "本条在库里为**单源收录**，未做多源交叉验证；引用前建议人工比对官方文本",
    "conflict": "本条在库里有**多源冲突未裁决**，两版原文差异较大；引用前必须人工裁定",
}
CONF_LABEL = {"multi-ok": "多源一致", "single": "单源未核", "conflict": "多源冲突"}


def _join(a, b):
    if not a:
        return b
    if not b:
        return a
    return a + "；" + b


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
        ent = ents.get(art_key(no))
        m = meta.get(law) or {}
        # 该法有没有「旧条号 → 新条号」对照，本次引的号是否正落在旧号上（v3.26.11 · H-08）
        no_int = cn2int(art_key(no))
        new_no = old_new_map(m.get("note")).get(no_int) if no_int else None
        row = {
            "law": law, "no": no, "quote": c["quote"],
            "version": m.get("version", ""), "effective": m.get("effective", ""),
            "pending": m.get("pending"),
            "status": "", "cause": "", "score": None, "cov": None, "anchor": "", "note": "",
            "verified": None, "vs": "",
        }
        if ent is None:
            row["status"] = "待核验"
            row["cause"] = "库外未收录"
            row["note"] = "本库未收录该条（库覆盖 %d 条，非全法典），须人工核现行原文" % sum(
                len(v) for v in laws.values())
        else:
            row["anchor"] = ent.get("anchor", "")
            # 置信来源：本条在库里有没有被多源交叉验证过
            row["verified"] = bool(ent.get("verified"))
            row["vs"] = ent.get("status") or ("multi-ok" if row["verified"] else "single")
            if not row["verified"]:
                row["note"] = CONF_NOTE.get(row["vs"], CONF_NOTE["single"])
            if not c["quote"] or len(norm(c["quote"])) < 6:
                row["status"] = "条号成立"
                row["note"] = _join(row["note"], "仅核到条号存在，未提供引述正文可比对")
            else:
                sc, cov = best_window(c["quote"], ent["text"])
                row["score"] = round(sc, 3)
                row["cov"] = round(cov, 3)
                if cov >= 0.62:
                    row["status"] = "通过"
                elif cov >= 0.35:
                    row["status"] = "表述存疑"
                    row["cause"] = "表述偏差"
                    row["note"] = _join(row["note"],
                                        "引述能落到本条，但用词与原文偏差较大，"
                                        "请对照原文补正或改为转述")
                else:
                    row["status"] = "待核验"
                    if new_no:
                        # 已确知是条号旧了，就别说「疑条号错位」——那仍然让人去猜
                        row["cause"] = "条号疑旧"
                        row["note"] = _join(
                            row["note"],
                            "本库第%s现为「%s」，与你这段引述对不上，很可能就是条号旧了" % (
                                art_label(no), re.sub(r"[\s|]+", "", ent.get("text") or "")[:26]))
                    else:
                        row["cause"] = "引述失真"
                        row["note"] = _join(row["note"],
                                            "引述内容在本条原文中找不到对应，"
                                            "疑引述失真，或摘引了别一条")

        # 旧条号提示：与判定档**独立**——只要该法 meta 写着「旧X→新Y」且本次引的正是 X，
        # 就把对照摆出来，不论判到哪一档。这一句是使用者最需要的那一行，不能藏在括号里。
        if new_no:
            row["note"] = _join(
                "**引的是旧条号**：第%s为《%s》改版前的编号，现行对应**第%s**（本库按现行版收录）"
                % (art_label(no), law, art_label(new_no)), row["note"])
            if row["status"] in ("待核验", "表述存疑"):
                row["cause"] = "条号疑旧"
        if row["pending"]:
            p = row["pending"]
            row["note"] = (row["note"] + "；" if row["note"] else "") + \
                "《%s》已于 %s 修订、%s 施行，本库所存为 %s 版；跨该日期引用须注明所据版本" % (
                    law, p.get("version", ""), p.get("effective", ""), row["version"])
        rows.append(row)
    return rows


def lib_note(db, rows=None):
    """**v3.22.3 新增**：报告头部的「法条库截至」一行。

    为什么要有：v3.22.2 撞见的教训是「库自称唯一真值来源，却存着失效条文」。
    核验表如果只给结论、不给「依据的是哪一版库」，使用者无从判断这句话的时效。
    库龄逾 90 天时显式提醒——不是为了吓人，是把「该更新库了」从想起来才有
    变成看见了就躲不掉。库龄只按 generated 日期粗算，不作精确承诺。
    """
    laws = db.get("laws") or {}
    nlaws = len(laws)
    nart = sum(len(v) for v in laws.values() if isinstance(v, dict))
    gen = str(db.get("generated") or "")[:10] or "未知"
    note = "法条库截至 %s（%d 部 %d 条，离线比对，更新时点见生成日期）" % (gen, nlaws, nart)
    try:
        d0 = datetime.date.fromisoformat(gen)
        age = (datetime.date.today() - d0).days
        if age > 90:
            note += " ｜ **库龄 %d 天，逾 90 天：建议更新法规库后重新核验**" % age
    except ValueError:
        pass
    return note


def render_md(rows, src="", note=""):
    if not rows:
        head = "## 法条核验表\n\n本次未检出可核验的法条引用。\n"
        if note:
            head += "\n> " + note + "\n"
        return head
    ok = sum(1 for r in rows if r["status"] in ("通过", "条号成立"))
    bad = len(rows) - ok
    L = ["## 法条核验表", "",
         "> 核验对象：%s ｜ 核验方式：本地原文库逐条比对（离线，未联网）" % (src or "本报告"),
         "> 结果：共 %d 条引用，通过 %d，需人工复核 %d。" % (len(rows), ok, bad)]
    if note:
        L.insert(2, "> " + note)
    L += ["", "| # | 法律 | 条号 | 判定 | 库内置信 | 匹配度 | 片段覆盖 | 所据版本 | 库里原文（节选） |",
          "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        # 「判定」列带成因后缀（v3.26.11 · H-08）：光写「待核验」三个字，使用者分不清是
        # 「库没收这条」「条号旧了」还是「引述走样」——三件事的处置完全不同，却读成同一件。
        verdict = r["status"] + ("·" + r["cause"] if r.get("cause") else "")
        L.append("| %d | 《%s》 | 第%s | %s | %s | %s | %s | %s | %s |" % (
            i, r["law"], art_label(r["no"]), verdict,
            CONF_LABEL.get(r.get("vs") or "", "库外"),
            ("%.0f%%" % (r["score"] * 100)) if r["score"] is not None else "—",
            ("%.0f%%" % (r["cov"] * 100)) if r.get("cov") is not None else "—",
            r["version"] + ("（%s 施行）" % r["effective"] if r["effective"] else ""),
            (r["anchor"] or "—").replace("|", "｜"),
        ))
    causes = [r.get("cause") for r in rows if r.get("cause")]
    if causes:
        L += ["", "**「待核验／表述存疑」后面那个词是成因，三件事处置完全不同**", "",
              "| 成因 | 意思 | 该做什么 |",
              "|---|---|---|",
              "| **库外未收录** | 库只收高频条号，不是全法典 | 人工查现行原文；**不等于条号错，更不得据此删引** |",
              "| **条号疑旧** | 你引的号是该法**改版前**的编号，现行对应另一条 | 按上面给的「旧X→新Y」改引新号后重核 |",
              "| **引述失真** | 条号对，但这段话在本条原文里找不到 | 对照库里原文补正，或改成转述并标明「转述」 |",
              "| **表述偏差** | 条号对、大意也对，只是用词与原文差得远 | 摘引原文，或明确写「意近」 |",
              ""]
    notes = [r for r in rows if r["note"]]
    if notes:
        L += ["", "**逐条说明**", ""]
        for r in notes:
            L.append("- 《%s》第%s：%s" % (r["law"], art_label(r["no"]), r["note"]))
    n_multi = sum(1 for r in rows if (r.get("vs") == "multi-ok"))
    n_single = sum(1 for r in rows if (r.get("vs") == "single"))
    n_conf = sum(1 for r in rows if (r.get("vs") == "conflict"))
    L += ["", "**库内置信说明**（两个「置信」是不同的东西，别混）",
          "",
          "- **判定**：你引的这段话能不能在库中该条原文里找到——比的是**引述与原文**。",
          "- **库内置信**：库中该条原文自身有没有被 ≥2 个独立来源比对过——比的是**源与源**。"
          "「多源一致」 %d 条、「单源未核」 %d 条、「多源冲突」 %d 条。" % (n_multi, n_single, n_conf),
          "- 两者都过，才叫「引述准确且原文可信」；任一存疑都要人工复核后再写入正式意见。",
          ""]
    L += ["", "> **本表只证明「与本地库一致」，不证明「现行有效」。**条文以国家法律法规数据库"
              "（flk.npc.gov.cn）与官方公报为准；标注「待核验」者不得写入正式意见。", ""]
    return "\n".join(L)


def _audit_rules(db, root, update=False):
    """规则库条号引用自检：**防「换版后条号错位」这类事故再次静默通过。**

    ## 为什么要有这个模式
    2026-10-22 实测发现：`core/01-general-risk-rules.md`、`industries/*.md` 里写着
    「《反不正当竞争法》第 7 条商业贿赂」，而该法已于 2025-06-27 第二次修订、2025-10-15 施行，
    新法第七条是**混淆行为**，商业贿赂移到了第八条。也就是说，规则库引的条号指向了另一个行为。
    `--file/--text` 那条核验路径抓不到这种错：它核的是「报告里引述的那句话在不在条文里」，
    而规则库里只写了「第 7 条」，没有引述正文可比。

    ## 判据：不猜语义，只锁「引用 → 条文」的对应关系
    语义比对（拿「商业贿赂」四字去条文里找）在本例中会失灵——「商业秘密」对第 9 条也能命中
    0.50（因为条文里有「商业宣传」），判不出对错。故这里不比语义，只做**指纹锚定**：
    每条「《法》N 条」的引用，记下它当时对应的条文 sha256。日后以下两种情形任一发生，即报警：
      ① 规则改了条号（引用指纹变）     → 该引用须人工复核是否还对应当年那条
      ② 库换了版本（条文 sha256 变）   → 该条内容已变，规则里对该条的描述可能失效
    两者都不发生时跳过，不制造噪声。

    ## 用法
      python scripts/legal-verify.py --audit-rules            # 比对，有差异退出码 1
      python scripts/legal-verify.py --audit-rules --update    # 人工确认后刷新基线
    """
    base_path = os.path.join(root, "core", "_cite-baseline.json")
    laws = db.get("laws") or {}
    meta = db.get("meta") or {}

    # 「《中华人民共和国XX法》」与「《XX法》」都要认；法名以库内 key 为准
    names = sorted(laws, key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names)
    # 增设条（「第 205 条之一」）也要抓：它和主条是两个罪名，漏掉「之一」就会把
    # 虚开发票罪的引用记到虚开增值税专用发票罪名下，基线从此记错。
    pat = re.compile(r"《(?:中华人民共和国)?(" + alt + r")》\s*第?\s*(\d+)\s*条"
                     r"(?:\s*之([一二三四五六七八九十]{1,3}))?")

    cur, missing = {}, []
    for rel in ("core/01-general-risk-rules.md", "core/02-legal-verification-checklist.md"):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            continue
        _scan_file(p, rel, pat, laws, meta, cur, missing)
    ind = os.path.join(root, "industries")
    if os.path.isdir(ind):
        for fn in sorted(os.listdir(ind)):
            if fn.endswith(".md"):
                rel = "industries/" + fn
                _scan_file(os.path.join(ind, fn), rel, pat, laws, meta, cur, missing)

    if update:
        out = {
            "_说明": "规则库条号引用基线（legal-verify.py --audit-rules 生成）。"
                     "键＝「文件::法名::条号」，值＝该引用所对应条文的 sha256 与当时版本。"
                     "换版或改条号后须人工确认每条引用仍对得上，再 --update 刷新。",
            "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(cur),
            "cites": dict(sorted(cur.items())),
        }
        with io.open(base_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("已刷新条号引用基线：%d 条 → %s" % (len(cur), os.path.relpath(base_path, root)))
        return 0

    if not os.path.exists(base_path):
        print("没有基线文件，先跑 --audit-rules --update 生成。")
        return 2
    with io.open(base_path, encoding="utf-8") as f:
        base = json.load(f)
    old = base.get("cites") or {}

    # ---- 判据（2026-10-22 修正）：不能以「文件::法名::条号」为键去比对 ----
    # 首版就是那样写的，结果**反向注入验不出来**：把规则里的「第 8 条」改回「第 7 条」后，
    # 键从 `...::8` 变成 `...::7`，旧的进「引用消失」、新的进「新增」，而这两类当时的退出码
    # 都是 0——**改了条号，门禁竟然全绿**。而「改了条号」恰恰是本门禁唯一要拦的事。
    # 改为按「文件 + 法名」归组，逐组比对条号集合：集合变了就是条号位移动，直接判错。
    def group(cites):
        g = {}
        for key, ent in cites.items():
            rel, law, no = key.split("::")
            g.setdefault((rel, law), {})[art_key(no)] = ent
        return g

    og, ng = group(old), group(cur)
    shifted, changed, gone, added = [], [], [], []
    for (rel, law), omap in sorted(og.items()):
        nmap = ng.get((rel, law), {})
        if not nmap:
            gone.append((rel, law, sorted(omap, key=art_base)))
            continue
        os_, ns_ = set(omap), set(nmap)
        if os_ != ns_:
            # 条号集合变了：可能是条号位移（换版后整体后移），也可能是增删引用
            keep = os_ & ns_
            shifted.append((rel, law, sorted(os_ - ns_), sorted(ns_ - os_),
                            bool(keep), sorted(keep)))
        for no in sorted(os_ & ns_):
            if omap[no]["sha256"] != nmap[no]["sha256"]:
                changed.append((rel, law, no, omap[no], nmap[no]))
    for (rel, law) in sorted(set(ng) - set(og)):
        added.append((rel, law, sorted(ng[(rel, law)])))

    bad = bool(shifted or changed)
    print("## 规则库条号引用自检")
    print()
    print("> 引用 %d 条｜基线 %d 条｜条号位移 %d 处｜条文变动 %d 条｜整组消失 %d｜整组新增 %d｜库未收录 %d"
          % (len(cur), len(old), len(shifted), len(changed), len(gone), len(added),
             len(missing)))

    if changed:
        print()
        print("**条文内容已变**（库换了版本或该条被修正）——规则里对它的描述须逐条复核：")
        for rel, law, no, o, n in changed:
            print("- `%s` 《%s》第%d条：%s 版 → %s 版（sha256 %s → %s）"
                  % (rel, law, no, o.get("version", "?"), n.get("version", "?"),
                     o["sha256"][:8], n["sha256"][:8]))

    if shifted:
        print()
        print("**条号位移动了**——规则里引的条号与基线对不上。"
              "换版导致条号整体后移时最常见，须逐条确认规则描述的是否仍是该内容：")
        for rel, law, lost, new, overlap, keep in shifted:
            print("- `%s` 《%s》" % (rel, law))
            if lost or new:
                print("    少了：%s ｜多了：%s" % (
                    "、".join(art_label(n) for n in lost) or "—",
                    "、".join(art_label(n) for n in new) or "—"))
            if overlap and keep:
                print("    同组内另有 %s 未变，说明是**个别条号改动**，不是整组重排"
                      % "、".join(art_label(n) for n in keep))

    if missing:
        print()
        print("**库内未收录**（无从核对，须人工核现行原文）：")
        for rel, law, no in missing:
            print("- `%s` 《%s》第%s" % (rel, law, art_label(no)))

    if gone:
        print()
        print("**整组引用消失**（该文件不再引用这部法；确认是有意删除后 --update）：")
        for rel, law, nos in gone:
            print("- `%s` 《%s》原引 %s" % (rel, law, "、".join(art_label(n) for n in nos)))

    if added:
        print()
        print("**整组新增**（该文件开始引用这部法，无基线可比；确认无误后 --update）：")
        for rel, law, nos in added:
            print("- `%s` 《%s》新引 %s" % (rel, law, "、".join(art_label(n) for n in nos)))

    if not bad and not gone and not added and not missing:
        print()
        print("无差异：规则库每条「《法》N 条」引用，都与基线记录的条文对得上。")
    return 1 if bad else 0


def _scan_file(path, rel, pat, laws, meta, cur, missing):
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    for m in pat.finditer(text):
        law, no = m.group(1), parse_no(m.group(2), m.group(3))
        if not law or not no:
            continue
        ent = (laws.get(law) or {}).get(no)
        if ent is None:
            missing.append((rel, law, no))
            continue
        cur["%s::%s::%s" % (rel, law, no)] = {
            "no": no, "sha256": ent.get("sha256", ""),
            "version": (meta.get(law) or {}).get("version", ""),
        }


def main():
    ap = argparse.ArgumentParser(description="法条核验（离线，比对本地原文库）")
    ap.add_argument("--file", help="待核验的文本文件（md/txt）")
    ap.add_argument("--text", help="直接给一段文本")
    ap.add_argument("--json", help="把机读结果写到该路径")
    ap.add_argument("--audit-rules", action="store_true",
                    help="自检模式：扫 core/ 与 industries/ 规则里的「《法》N 条」引用，"
                         "核对库中该条是否真是所描述的那条（防换版后条号错位）")
    ap.add_argument("--update", action="store_true",
                    help="配合 --audit-rules：人工确认全部差异后刷新基线")
    ap.add_argument("--list", metavar="LAW", help="列出库里某部法收录的条号")
    ap.add_argument("--strict", type=float, default=0.72, help="「表述存疑」下限，默认 0.72")
    a = ap.parse_args()

    db = load_db()

    if a.audit_rules:
        root = os.path.abspath(os.path.join(HERE, ".."))
        return _audit_rules(db, root, update=a.update)

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
    md = render_md(rows, src, note=lib_note(db))
    sys.stdout.write(md)

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump({"source": src, "rows": rows}, f, ensure_ascii=False, indent=1)
        print("\n机读结果：%s" % a.json)

    bad = [r for r in rows if r["status"] in ("待核验", "表述存疑")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
