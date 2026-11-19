#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""法规检索（要件呈现）—— legal-articles.json 的第二个消费者

与 legal-verify.py 的分工
    legal-verify：**你已经在报告里引了某条**，我核这条原文对不对、是不是现行版（裁判）
    legal-search：**你还没引、只想查**，我按问题或条号把条文找出来，并把本条
                  的适用要件拆给你看（找 + 呈现）

用途：给定问题或「法名＋条号」，在本地法规库内检索条文，输出原文、出处、
      本条针对的情形、适用要件、除外情形。

设计红线（改代码前先读，越界即违规）
  · **只讲要件，不下结论**。要件是法条自身的结构（「……的，应当……」里的
    「……」就是要件），属客观内容；「你这个情况算不算」「该不该签」「能不能赢」
    一槪不答。输出结构里**根本没有**结论字段——想写也写不进去。
  · **库外不猜**。库内没有的条号，一律明说「本库未收录」，绝不凭模型记忆补条文。
  · **本脚本永不联网**（E0 档）。库外条文的联网核对由 `legal-lookup.py`（E2 档）承担，
    那个脚本只接「法名＋条号」，没有放使用者文本的入口——两件事分开，是为了让
    `--ask` 的自然语言问题（可能含案情）**永远不出域**。v3.33.0 起路由为**本地优先、
    联网补位**：本地命中即回（毫秒级、双源已验证），未命中才提示走联网。
  · **覆盖面必须报**。本库是按审查场景精选，不是法律全集。每次输出都带
    覆盖面声明，避免用户误以为是全库检索。
  · **未验证不许冒充已验证**。每条必带 verified 状态；单源/冲突要显式标出。

适用要件的抽取方式（为什么不能交给模型）
    条文里「的，应当」结构就是法律构成要件。本脚本用**句式规则**切分：
      「有下列情形之一的」「……的」「应当」「不得」「除外」「但书」
    切出来的片段直接来自原文，可指回原句。模型自由生成的「要件」无法验证，
    一旦生成错，就是把假法理当真法理卖——比不答更坏。

用法：
  python scripts/legal-search.py --ask "合同违约金能约定多少"
  python scripts/legal-search.py --ask "违约金" --law 民法典
  python scripts/legal-search.py --article 民法典 585
  python scripts/legal-search.py --coverage                    # 看本库覆盖面

库外条文（含司法解释）本脚本**抓不到也不去抓**——它标 E0、零网络库。改用：
  python scripts/legal-lookup.py --article 商标法 3            # 联网补位，只发法名＋条号

退出码：0 命中；1 未命中（库内没有；联网补位请走 legal-lookup.py）。
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
DB = os.path.join(HERE, "..", "core", "legal-articles.json")

# 复用 legal-verify 的检索原语（同一套 4 字滑窗 + 覆盖率打分，不另造一套算法）
_sys.path.insert(0, HERE)
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("lv", os.path.join(HERE, "legal-verify.py"))
lv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(lv)

CONF_LABEL = {"multi-ok": "多源一致", "single": "单源未核", "conflict": "多源冲突"}


def load_db(path=DB):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── 要件抽取（句式规则，非模型） ───────────────────────────
#
# 法条的经典结构：
#   「有下列情形之一的，……：」 → 列举式要件
#   「……的，应当……」          → 前段是构成要件，后段是法律后果
#   「……，不得……」            → 禁止性规定
#   「但……」「除外」           → 例外
#
# 抽取只做三件事：切分、归类、保留原文片段。**不生成、不改写、不解释**。

_SENT_SPLIT = re.compile(r"(?<=[。；;])")
# 「……的，」结尾的条件从句
_COND_THEN = re.compile(r"^(?P<cond>.{4,}?的)[，,]\s*(?P<then>.+)$")
# 列举引导
_ENUM_HEAD = re.compile(r"^(?P<head>.{0,60}?)(?:下列|以下)(?:情形|事项|条件|行为|方式|内容)之一")
# 除外 / 但书
_EXCEPT = re.compile(r"^(?P<except>(?:但是|但|除外|另有|法律另有规定|当事人另有约定).+)$")


def split_requirements(text):
    """从条文原文抽取〔针对情形／适用要件／除外情形〕三组片段。

    返回值全部是**原文子串**，不改一个字——可逐句指回条文，便于人工核对。
    抽取不出来就返回空表，**绝不编造**。
    """
    t = (text or "").strip()
    if not t:
        return {"scene": "", "reqs": [], "excepts": []}

    scene, reqs, excepts = "", [], []

    # 切句：以 。； 为界，保留分隔符
    sents = [s.strip() for s in _SENT_SPLIT.split(t) if s.strip()]

    for s in sents:
        body = s.rstrip("。；;")

        # ① 列举式：「有下列情形之一的，……：」——本句只给场景，列举项在后面
        m = _ENUM_HEAD.match(body)
        if m:
            scene = scene or body
            continue

        # ② 除外／但书
        m = _EXCEPT.match(body)
        if m:
            excepts.append(m.group("except").rstrip("。；;"))
            continue

        # ③ 「……的，应当/不得/可以……」——条件从句即要件
        m = _COND_THEN.match(body)
        if m:
            cond = m.group("cond").strip()
            # 条件从句过长（>90 字）多半是把整段都包进去了，**不收入要件**
            # ——宁可少列，也不要把整句授权性规范当成构成要件（那是假法理）
            if len(cond) <= 90:
                reqs.append(cond)
            continue

        # ④ 兜底：以「应当／不得／必须」开头的独立义务句，本身不是要件而是后果，
        #    不并入要件——避免把法律后果误标成构成要件（这是最容易出错的地方）
        if re.match(r"^(应当|不得|必须|可以)", body):
            continue

        # ⑤ 授权性／定义性规范不是构成要件：「当事人可以……」「本法所称……」。
        #    这类句子描述的是「允许做什么」，不是「满足什么才适用」。
        if re.match(r"^(当事人|任何|自然|法[人定]|本法所称|本[条法]所称)\s*(可以|有权)", body):
            continue

        # ⑥ 其余短句：若是列举项（（一）（二）…）或平铺情形，收作要件
        if re.match(r"^[（(][一二三四五六七八九十\d]{1,3}[）)]", body):
            reqs.append(re.sub(r"^[（(][一二三四五六七八九十\d]{1,3}[）)]", "", body).strip())
        elif 6 <= len(body) <= 60 and re.search(r"的$|时$|情形$|条件$", body):
            # 只收「……的」「……时」「……情形」这类条件性短句；
            # 平铺陈述句（如「违约方支付违约金后」）不当作要件
            reqs.append(body)

    # 去重保序
    def _uniq(seq):
        out, seen = [], set()
        for x in seq:
            k = lv.norm(x)
            if k and k not in seen:
                seen.add(k)
                out.append(x)
        return out

    return {"scene": scene, "reqs": _uniq(reqs), "excepts": _uniq(excepts)}


# ─────────────────────────── 检索 ───────────────────────────

def search_in_db(q, db, law_filter=None, limit=8, min_score=0.28):
    """库内检索。先精确条号，再主题词加权。

    返回 [{law, no, text, anchor, verified, status, sources, score, hit}]。
    """
    laws = db.get("laws") or {}
    out = []

    # (1) 显式条号：问题里带了「第X条」
    m = re.search(r"第\s*([一二三四五六七八九十百千零〇\d]{1,8})\s*条"
                  r"(?:\s*之([一二三四五六七八九十]{1,3}))?", q)
    if m:
        # 「第205条之一」必须与「第205条」分开查：两个不同罪名，条文完全不同
        no = lv.parse_no(m.group(1), m.group(2))
        name_hint = lv.pick_law(q) or law_filter
        targets = [name_hint] if name_hint else list(laws)
        for law in targets:
            ent = (laws.get(law) or {}).get(no)
            if ent:
                out.append(_row(law, no, ent, 1.0, "条号精确"))
        if out:
            return out

    # (2) 主题词检索：长串走 4 字滑窗覆盖率，短词走整词包含
    #
    # 注意：legal-verify 的 _units 取 4 字滑窗，短于 4 字的关键词（如「违约金」
    # 三字）切不出窗口，得分恒为 0——拿它直接检索短词会全部漏检。
    # 故短词改走「整词出现次数」打分，与长串结果归一后再排序。
    qn = lv.norm(q)
    short = len(qn) < 4
    pools = [law_filter] if law_filter else list(laws)
    for law in pools:
        for no_s, ent in (laws.get(law) or {}).items():
            txt = ent.get("text", "")
            if not txt:
                continue
            anc = ent.get("anchor", "")
            if short:
                tn = lv.norm(txt)
                # 出现即给基础分；出现次数越多、越靠前，相关度越高（有上限）
                cnt = tn.count(qn) + (lv.norm(anc).count(qn) * 2)
                if cnt == 0:
                    continue
                score = min(0.30 + 0.12 * (cnt - 1), 0.78)
                out.append(_row(law, no_s, ent, score, "关键词命中"))
                continue
            cov = lv.coverage(q, txt)
            anc_cov = lv.coverage(q, anc) if anc else 0.0
            score = max(cov, anc_cov * 0.9)
            if score >= min_score:
                out.append(_row(law, no_s, ent, score,
                                "主题命中" if cov >= anc_cov else "摘要命中"))

    out.sort(key=lambda r: (-r["score"], r["law"], lv.art_base(r["no"]), lv.art_key(r["no"])))
    return out[:limit]


def _row(law, no, ent, score, hit):
    return {
        "law": law, "no": no, "score": round(score, 3), "hit": hit,
        "text": ent.get("text", ""), "anchor": ent.get("anchor", ""),
        "verified": ent.get("verified"), "status": ent.get("status", ""),
        "sources": ent.get("sources") or [],
    }


# ─────────────────────── 条款反查（条款 → 条文） ───────────────────────
#
# 与 --ask 的分工：--ask 问「我想查什么」，反查问「我手上这条款对应哪几条」。
# 检索方向相反，判据也不同：--ask 用覆盖率（问句与条文语义近），
# 反查用**术语连续命中**（条款里的专有名词在条文原文里原样出现）。
#
# 为什么反查不能用覆盖率（实测过，不是拍脑袋）：
#   条文短，「违约金」三字切不出 4 字窗，覆盖率恒为 0；长条款又被长度稀释成普遍低分。
#   改用「3–6 字片段中能整段出现在原文里的部分」，只留最长的若干段。
#
# 为什么必须把「命中术语」摆出来：
#   词面匹配分不清「竞业限制」和「不得从事」——两者都是 4 字，分数一样。
#   把命中的术语列出来，使用者一眼能判相关性真假，这是**可核验**的做法；
#   只报一个相关度数字、把依据藏起来，等于让人凭排序相信一个查不了的东西。
#
# 红线不变：仍只给候选条文与要件，**不判断该条款是否合规、是否有效**。

# 纯句式套话——命中它们不代表主题相关，反而会淹没真术语。
# 铁则：这张表里**不许出现任何法律实体术语**（「违约金」「竞业限制」「商业秘密」
# 这类必须留着）。误收一个，该主题就再也检不出来——这是实测踩过的坑。
_STOP_PHRASES = (
    "不得从事", "范围内的", "有权解除", "应当承担", "承担赔偿", "赔偿损失",
    "依照本法", "本法规定", "本条规定", "当事人的", "约定的期", "合同约定",
    "按照约定", "可以要求", "要求对方", "向人民法", "人民法院", "提起诉讼",
    "本解释", "下列情形", "情形之一的", "的期限", "期限内", "履行期限",
    "届满", "可以解除", "解除合同", "的，应", "，应当", "有权要", "照约定",
    "超过三十", "三十日内", "分之五",
)


def _strip_punct(s):
    # 全角半角都要去：法条用全角「，」，条款原文常被输入法写成半角「,」——
    # 只去全角，半角会留在片段里（`逾期付款的,` 就是这么来的）
    return re.sub(r"[，,、：:；;（）()“”\"'‘’。.\s]", "", lv.norm(s))


def _clause_grams(s):
    """条款切成 3–6 字片段。3 字起——「违约金」三字是有效术语，2 字全是噪声。"""
    t = _strip_punct(s)
    out = set()
    for n in range(3, 7):
        for i in range(len(t) - n + 1):
            out.add(t[i:i + n])
    return out


def _is_stop(g):
    """双向包含判定：g 是某条套话的子串、或某条套话是 g 的子串，都算套话。"""
    return any(g in st or st in g for st in _STOP_PHRASES)


def _hit_terms(grams_, target):
    """条款片段里，能整段出现在 target 中的最长若干段（剔掉被更长段包含的碎渣）。

    **以「的」结尾的一律丢弃**：那是定语残片不是术语——「期付款的」「范围内的」
    「约定的期」都是半截话。实测这条过滤最管用：不加它，「分期付款的」会排在
    「违约金」前面（4 字比 3 字分高），律师一眼就看出排错了。
    """
    tn = _strip_punct(target)
    hit = [g for g in grams_
           if g in tn and not _is_stop(g)
           and not g.endswith("的") and g[0] not in "的了在与和或"]
    if not hit:
        return []
    hit.sort(key=len, reverse=True)
    keep = []
    for x in hit:
        if not any(x != y and x in y for y in hit):
            keep.append(x)
    return keep[:3]


def search_from_clause(clause, db, law_filter=None, limit=6):
    """条款 → 候选条文。返回结构与 search_in_db 一致，另带 terms／score_kind。"""
    cg = _clause_grams(clause)
    if not cg:
        return []
    laws = db.get("laws") or {}
    pools = [law_filter] if law_filter else list(laws)
    out = []
    for law in pools:
        for no_s, ent in (laws.get(law) or {}).items():
            txt = ent.get("text", "")
            if not txt:
                continue
            anc = ent.get("anchor", "")
            ht = _hit_terms(cg, txt)
            if not ht:
                continue
            ha = _hit_terms(cg, anc) if anc else []
            # 最长命中不足 4 字、条旨也没对上——多半是句式套话漏网，不当作候选。
            # 宁可少给几条，也不拿噪声充数（噪声会让人以为检出了，实际没对上）。
            if len(ht[0]) < 4 and not ha:
                continue
            score = sum(len(x) ** 2 for x in ht) + sum(len(x) ** 2 * 1.5 for x in ha)
            row = _row(law, no_s, ent, 0.0, "术语命中")
            row["score"] = round(score, 1)
            row["score_kind"] = "术语分"
            row["terms"] = ha or ht
            out.append(row)
    # 同分时条号靠前者优先——只是给一个稳定次序，不代表更相关
    out.sort(key=lambda r: (-r["score"], r["law"], lv.art_base(r["no"]), lv.art_key(r["no"])))
    return out[:limit]


def _external_query_sheet(q, db, kind):
    """库外检索单：本库没有的东西，写成一份可复制的单子交出去。

    **不调用任何外部服务**（本脚本 E0）。两个技能之间靠这份单子衔接，不靠代码耦合——
    审查技能只负责「说清缺什么」，查什么、怎么查由使用者拿到检索侧去做。
    """
    total = sum(len(v) for v in (db.get("laws") or {}).values())
    L = []
    L.append("### 库外检索单（可整段复制）")
    L.append("")
    L.append("| 项 | 内容 |")
    L.append("|---|---|")
    L.append("| 检索对象 | %s |" % q.strip().replace("|", "\\|"))
    L.append("| 检索类型 | %s |" % ("法条原文核对（法名＋条号）" if kind == "article"
                                     else "按事项反查法条／司法解释／案例"))
    L.append("| 为什么在本库查不到 | 本库 %d 条按审查场景精选，非法律全集 |" % total)
    L.append("| 建议去处 | 「法律与案例检索助手」技能；或国家法律法规数据库 flk.npc.gov.cn |")
    L.append("| 本技能的立场 | **不代查、不猜测、不凭记忆补条文**——查不到就说查不到 |")
    L.append("")
    return L


def coverage_report(db):
    laws = db.get("laws") or {}
    total = sum(len(v) for v in laws.values())
    rows = sorted(((k, len(v)) for k, v in laws.items()), key=lambda x: -x[1])
    lines = ["## 本库覆盖面", "",
             "> **本库是按审查场景精选的条文子集，不是法律全集。**"
             "问到的条若不在库内，本脚本会明说「未收录」，不会凭记忆补。", "",
             "| 法名 | 收录条数 |", "|---|---|"]
    for k, n in rows:
        lines.append("| %s | %d |" % (k, n))
    lines.append("| **合计** | **%d** |" % total)
    return "\n".join(lines), total


def _article_block(r):
    """单条条文的渲染块（原文 ＋ 要件 ＋ 不作判断声明）。

    抽成函数，供三种渲染路径共用：列表式（`render`）、按法分组式（`render_cross`）、
    条款反查式（`render_clause`）。**三条路径共用同一块**，是为了让「只讲要件不下结论」
    这条红线只有一处实现——分散成三份，改一处漏两处，迟早有一条路径把结论说出来。
    """
    b = []
    conf = CONF_LABEL.get(r["status"], r["status"] or "未标")
    flag = "" if r["verified"] else "　⚠ 未通过多源验证"
    b.append("### 《%s》第%s" % (r["law"], lv.art_label(r["no"])))
    b.append("")
    if r.get("score_kind") == "术语分":
        b.append("`%s` ｜ 相关度 %s（%s）%s" % (conf, r["score"], r["hit"], flag))
        b.append("")
        b.append("**命中的术语**：%s（术语在该条原文或条旨中整段出现，可自行核验）"
                 % "、".join("`%s`" % t for t in (r.get("terms") or [])))
    else:
        b.append("`%s` ｜ %s ｜ 匹配度 %.2f（%s）%s" % (conf, r["hit"], r["score"], r["hit"], flag))
    b.append("")
    b.append("**原文**")
    b.append("")
    b.append("> " + r["text"])
    b.append("")

    req = split_requirements(r["text"])
    if req["scene"]:
        b.append("**本条针对的情形**")
        b.append("")
        b.append("- " + req["scene"])
        b.append("")
    if req["reqs"]:
        b.append("**适用要件**（摘自本条原文结构，未作改写）")
        b.append("")
        for i, x in enumerate(req["reqs"], 1):
            b.append("%d. %s" % (i, x))
        b.append("")
    if req["excepts"]:
        b.append("**除外／但书**")
        b.append("")
        for x in req["excepts"]:
            b.append("- " + x)
        b.append("")
    if not (req["reqs"] or req["excepts"]):
        b.append("> 本条无可机械拆解的构成要件句式（多为定义性／原则性条文），"
                 "请直接依据上引原文判断。")
        b.append("")

    b.append("> **你的具体情形是否满足上述要件，本技能不作判断**——"
             "需由执业律师结合事实认定。")
    b.append("")
    return b


def render(results, q, db):
    """渲染检索结果。**只讲要件，不下结论**。"""
    if not results:
        return None
    total = sum(len(v) for v in (db.get("laws") or {}).values())
    out = []
    out.append("## 法规检索：%s" % q)
    out.append("")
    out.append("> **检索路径：本地库**（E0 档，全程未联网）。覆盖 %d 部法 %d 条，"
               "全部经 ≥2 个独立来源交叉验证；是本库按审查场景精选的子集，**不是法律全集**。"
               "以下为条文原文与要件拆解，**不构成法律意见**。"
               % (len(db.get("laws") or {}), total))
    out.append("")

    for r in results:
        out.extend(_article_block(r))

    out.append("---")
    out.append("")
    out.append("*本技能提供条文检索与要件呈现，不构成法律意见、不预测案件结果；"
               "具体适用须经执业律师结合事实判断后方可据此决策。*")
    return "\n".join(out)


def render_clause(results, clause, db):
    """条款 → 候选条文。**给候选，不给结论**，并把命中术语摆出来供人核验。"""
    if not results:
        return None
    total = sum(len(v) for v in (db.get("laws") or {}).values())
    brief = re.sub(r"\s+", " ", clause).strip()
    if len(brief) > 40:
        brief = brief[:40] + "…"
    out = []
    out.append("## 条款反查：%s" % brief)
    out.append("")
    out.append("> **检索路径：本地库**（E0 档，全程未联网）。覆盖 %d 部法 %d 条，"
               "全部经 ≥2 个独立来源交叉验证；按审查场景精选，**不是法律全集**。"
               % (len(db.get("laws") or {}), total))
    out.append("")
    out.append("> **这是按「术语重合」排出的候选条文，不是法律适用结论。**"
               "判据只有一条：你条款里的词，在该条原文或条旨里**原样整段出现**——"
               "每条的命中术语都列在表里，可以自己核。"
               "**相关度只说明用词接近，不说明该条就管这件事**；"
               "本库未收录真正对应的条文也是常事，候选之外请另行检索。")
    out.append("")
    out.append("| # | 法名 | 条号 | 条旨 | 相关度 | 命中术语 |")
    out.append("|---|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        out.append("| %d | %s | %s | %s | %s | %s |" % (
            i, r["law"], lv.art_label(r["no"]),
            (r["anchor"] or "—").replace("|", "\\|")[:24],
            r["score"],
            "、".join(r.get("terms") or []) or "—"))
    out.append("")
    for r in results:
        out.extend(_article_block(r))
    out.append("---")
    out.append("")
    out.append("*本技能提供条文检索与要件呈现，不构成法律意见、不预测案件结果；"
               "具体适用须经执业律师结合事实判断后方可据此决策。*")
    return "\n".join(out)


def render_cross(results, q, db):
    """同一主题在各法中的规定，按法横向排开。

    「违约金」在民法典怎么写、在合同编通则解释里怎么调、在劳动合同法里又怎么受限——
    分法看是一屏，混在八条里看是八条不相干的条文。分组只是渲染层的组织方式，
    判据与红线跟列表式完全一致（共用 _article_block，红线不另写一份）。
    """
    if not results:
        return None
    total = sum(len(v) for v in (db.get("laws") or {}).values())
    groups = {}
    for r in results:
        groups.setdefault(r["law"], []).append(r)
    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    out = []
    out.append("## 多法对照：%s" % q)
    out.append("")
    out.append("> **检索路径：本地库**（E0 档，全程未联网）。覆盖 %d 部法 %d 条，"
               "按审查场景精选，**不是法律全集**。" % (len(db.get("laws") or {}), total))
    out.append("")
    out.append("> **只并列规定，不比较优劣、不判断该适用哪一部。**"
               "适用顺序（特别法优于一般法、上位法优于下位法、新法优于旧法）属于法律适用判断，"
               "本技能**不作**——同一件事在不同法里规定不一致时，以现行有效文本与有权机关解释为准，"
               "由执业律师认定。")
    out.append("")
    out.append("| 法名 | 命中条数 | 条号 |")
    out.append("|---|---|---|")
    for law, rows in order:
        nos = "、".join(lv.art_label(r["no"]) for r in rows)
        out.append("| %s | %d | %s |" % (law, len(rows), nos))
    out.append("")
    for law, rows in order:
        out.append("---")
        out.append("")
        out.append("## 《%s》（%d 条）" % (law, len(rows)))
        out.append("")
        for r in rows:
            out.extend(_article_block(r))
    out.append("---")
    out.append("")
    out.append("*本技能提供条文检索与要件呈现，不构成法律意见、不预测案件结果；"
               "具体适用须经执业律师结合事实判断后方可据此决策。*")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="法规检索（要件呈现）")
    ap.add_argument("--ask", help="自然语言问题或关键词")
    ap.add_argument("--from-clause", dest="from_clause",
                    help="条款原文 → 反查候选条文（按术语重合排序，给候选不给结论）")
    ap.add_argument("--article", nargs=2, metavar=("LAW", "NO"), help="按「法名 条号」精确查")
    ap.add_argument("--law", help="限定法名")
    ap.add_argument("--limit", type=int, default=None,
                    help="返回条数（默认：列表 8、反查 6、对照 40）")
    ap.add_argument("--cross", action="store_true",
                    help="按法分组横向对照（配 --ask 用：同一主题各部法分别怎么规定）")
    ap.add_argument("--coverage", action="store_true", help="只看本库覆盖面")
    ap.add_argument("--json", help="机读结果输出到文件")
    # 2026-11-06：这里原本注册着 `--online`，是个**假开关**——本脚本自标 E0、全文无网络库，
    # 该参数只在未命中分支打印一段说明，命中路径上被完全忽略。使用者打了它以为在联网，
    # 实际什么也没发生（25.3「承诺大于实际」）。现**不再注册进 argparse**（注册了就等于
    # 宣称本脚本有在线能力），改为在 main() 开头手动拦截并明确拒绝——见下方 ONLINE_GONE。
    # 已停用的开关：手动拦截，**明确拒绝并指路**（不注册进 argparse——不宣称本脚本有在线能力）
    ONLINE_GONE = ("--online", "--net", "--remote")
    _hit = [x for x in ONLINE_GONE if x in sys.argv[1:]]
    if _hit:
        print("`%s` 已停用。本脚本自标 **E0 档**（接触文档内容，绝对离线），全文无网络库——"
              "它**从来没有真的联过网**，此前那个开关只打印一段说明。\n"
              "联网核对请改用：python scripts/legal-lookup.py --article <法名> <条号>\n"
              "（那条命令只发送法名与条号，不发送文档内容与问题原文。）" % _hit[0],
              file=sys.stderr)
        return 2

    a = ap.parse_args()

    db = load_db()

    if a.coverage:
        txt, _n = coverage_report(db)
        print(txt)
        return 0

    if a.article:
        mode = "article"
        law_raw, no_raw = a.article
        law = lv.pick_law(law_raw) or law_raw
        _m = re.match(r"^\s*([一二三四五六七八九十百千零〇\d]{1,8})\s*"
                      r"(?:条)?(?:\s*之([一二三四五六七八九十]{1,3}))?\s*$", no_raw or "")
        no = lv.parse_no(_m.group(1), _m.group(2)) if _m else None
        if not no:
            print("条号无法解析：%s（可写 205 或 205之一）" % no_raw, file=sys.stderr)
            return 2
        q = "《%s》第%s" % (law, lv.art_label(no))
        results = search_in_db(q, db, law_filter=law, limit=1)
    elif a.from_clause:
        mode = "clause"
        q = a.from_clause
        results = search_from_clause(
            q, db, law_filter=a.law,
            limit=a.limit if a.limit is not None else 6)
    elif a.ask:
        mode = "ask"
        q = a.ask
        results = search_in_db(
            q, db, law_filter=a.law,
            limit=a.limit if a.limit is not None else (40 if a.cross else 8))
    else:
        ap.print_help()
        return 2

    if not results:
        total = sum(len(v) for v in (db.get("laws") or {}).values())
        print("## 未命中：%s" % q)
        print()
        print("> **检索路径：本地库**（E0 档，全程未联网）。本库 %d 条，是按审查场景精选的子集，"
              "**不是法律全集**——未命中不等于条号错。" % total)
        print()
        if a.article:
            print("### 本地未收录此条，可联网补位")
            print()
            print("| 下一步 | 怎么做 |")
            print("|---|---|")
            print("| **联网核对原文** | `python scripts/legal-lookup.py --article %s %s` |"
                  % (law, no_raw))
            print("| 查官方文本后人工核对 | 国家法律法规数据库 flk.npc.gov.cn |")
            print()
            print("> 那条命令**只发送法名与条号**——不发送文档内容、问题原文或任何使用者信息；"
                  "它把该法已登记的两个独立源各抓一遍，**双源一致才认**，单源会标「未核」而不冒充已核。")
            print("> 不允许联网（涉密件／内网）时**别跑它**：直接按「未收录」处理，报告里标「待核验」。")
        else:
            if a.from_clause:
                print("### 这条款没有与库内条文对上的术语")
                print()
                print("> 一个术语都对不上，通常是两种情况：")
                print("> ① **本库没收这件事**（如仲裁程序、票据、海事海商、税收征管）——本库是审查场景精选的子集；")
                print("> ② **用词与法条差得太远**（如「罚息」对「逾期利息」、「竞业禁止」对「竞业限制」）。")
                print()
                print("> 换个更贴近法条的词再试（`--from-clause \"逾期利息\"`），"
                      "或改用 `--ask` 按主题检索。")
            else:
                print("### 本地没搜到可匹配的条文")
                print()
                print("> `--ask` 的自然语言问题**永不联网**——问题里可能带案情，出网就等于外发。")
                print("> 若已知法名与条号，改用 `--article`：`python scripts/legal-search.py --article 民法典 585`；")
                print("> 那时再走 `legal-lookup.py` 联网核对才有意义（它只发法名与条号，不带问题原文）。")
        print()
        print("> **不凭记忆补条文，也不猜测。** 查不到就说查不到——把「没查到」写成「没问题」是最坏的一种错。")
        print()
        for _ln in _external_query_sheet(q, db, "article" if a.article else "matter"):
            print(_ln)
        return 1

    if mode == "clause":
        md = render_clause(results, q, db)
    elif a.cross and mode == "ask":
        md = render_cross(results, q, db)
    else:
        md = render(results, q, db)
    print(md)

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump({"query": q, "results": results}, f, ensure_ascii=False, indent=2)
        print("\n[已写出机读结果] %s" % a.json, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
