#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
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
    联网扩充须显式开 --online，且扩充结果只进临时集、不写回随包真值。
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
  python scripts/legal-search.py --ask "竞业限制" --online     # 库外联网扩充（显式）
  python scripts/legal-search.py --coverage                    # 看本库覆盖面

退出码：0 命中；1 未命中（库内没有，且未开 --online 或扩充也失败）。
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


def render(results, q, db):
    """渲染检索结果。**只讲要件，不下结论**。"""
    if not results:
        return None
    total = sum(len(v) for v in (db.get("laws") or {}).values())
    out = []
    out.append("## 法规检索：%s" % q)
    out.append("")
    out.append("> 库内检索，覆盖 %d 部法 %d 条（审查场景精选，非法律全集）。"
               "以下为条文原文与要件拆解，**不构成法律意见**。" % (len(db.get("laws") or {}), total))
    out.append("")

    for r in results:
        conf = CONF_LABEL.get(r["status"], r["status"] or "未标")
        flag = "" if r["verified"] else "　⚠ 未通过多源验证"
        out.append("### 《%s》第%s" % (r["law"], lv.art_label(r["no"])))
        out.append("")
        out.append("`%s` ｜ %s ｜ 匹配度 %.2f（%s）%s" % (conf, r["hit"], r["score"], r["hit"], flag))
        out.append("")
        out.append("**原文**")
        out.append("")
        out.append("> " + r["text"])
        out.append("")

        req = split_requirements(r["text"])
        if req["scene"]:
            out.append("**本条针对的情形**")
            out.append("")
            out.append("- " + req["scene"])
            out.append("")
        if req["reqs"]:
            out.append("**适用要件**（摘自本条原文结构，未作改写）")
            out.append("")
            for i, x in enumerate(req["reqs"], 1):
                out.append("%d. %s" % (i, x))
            out.append("")
        if req["excepts"]:
            out.append("**除外／但书**")
            out.append("")
            for x in req["excepts"]:
                out.append("- " + x)
            out.append("")
        if not (req["reqs"] or req["excepts"]):
            out.append("> 本条无可机械拆解的构成要件句式（多为定义性／原则性条文），"
                       "请直接依据上引原文判断。")
            out.append("")

        out.append("> **你的具体情形是否满足上述要件，本技能不作判断**——"
                   "需由执业律师结合事实认定。")
        out.append("")

    out.append("---")
    out.append("")
    out.append("*本技能提供条文检索与要件呈现，不构成法律意见、不预测案件结果；"
               "具体适用须经执业律师结合事实判断后方可据此决策。*")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="法规检索（要件呈现）")
    ap.add_argument("--ask", help="自然语言问题或关键词")
    ap.add_argument("--article", nargs=2, metavar=("LAW", "NO"), help="按「法名 条号」精确查")
    ap.add_argument("--law", help="限定法名")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--coverage", action="store_true", help="只看本库覆盖面")
    ap.add_argument("--json", help="机读结果输出到文件")
    ap.add_argument("--online", action="store_true",
                    help="库外联网扩充（显式开启；默认严格离线）")
    a = ap.parse_args()

    db = load_db()

    if a.coverage:
        txt, _n = coverage_report(db)
        print(txt)
        return 0

    if a.article:
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
    elif a.ask:
        q = a.ask
        results = search_in_db(q, db, law_filter=a.law, limit=a.limit)
    else:
        ap.print_help()
        return 2

    if not results:
        total = sum(len(v) for v in (db.get("laws") or {}).values())
        print("## 未命中：%s" % q)
        print()
        print("> 本库（%d 条）内没有可匹配的条文。" % total)
        print()
        if a.online:
            print("联网扩充需经「抓取 → 解析 → 双源交叉验证」三步，"
                  "由 `freshness-patrol.py` ＋ `legal-crosscheck.py` 完成；"
                  "本次未开启扩充链路。")
            print()
            print("**扩充前的口径**：即便联网抓到，未通过双源验证的条文也不得引用。")
        else:
            print("**本库未收录此条，且当前为严格离线模式（未开 --online）**——"
                  "不凭记忆补条文，也不猜测。")
            print()
            print("可选：①加 `--online` 走联网扩充（须联网）；"
                  "②直接查阅官方文本后人工核对。")
        return 1

    md = render(results, q, db)
    print(md)

    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            json.dump({"query": q, "results": results}, f, ensure_ascii=False, indent=2)
        print("\n[已写出机读结果] %s" % a.json, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
