#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E2  不联网就用不成（能力依赖外部知识）；须显式调用，离线须明示降级
"""库外条文联网核对 —— 本地库的**补位**，不是替代

与 legal-search.py 的分工
    legal-search：**本地优先**（E0 绝对离线）。日常查条文、`--ask` 的自然语言问题，
                  一律在随包库内解决，零出域。
    legal-lookup：**库外补位**（E2 联网）。只接「法名＋条号」这种结构化检索键，
                  去已登记的公开源把条文抓回来，双源一致才认。

为什么必须拆成两个脚本（不是为了好看）
    legal-search 的 `--ask` 接自然语言——「我们公司这个竞业限制条款能不能签」，
    这里面有案情。一旦让它自动联网，就等于把案情发出去。
    本脚本**没有 `--ask`、没有 `--file`、没有 `--dir`**：参数里只有法名、条号，
    可选一个公开页地址。**没有可以放使用者文本的地方**——不是「承诺不发」，是「没这个入口」。

为什么本地优先、联网只补位（v3.33.0 定）
    维度        本地库                              联网抓取
    速度        读 JSON，毫秒级                     45 秒超时 × 重试，每源一次
    可信度      725 条全部 ≥2 独立来源交叉验证       转载页，单源
    稳定        零依赖                              部分官方站有验证码／签名，机器不可达
    安全        零出域                              必有出域动作
    **联网优先＝用单源转载页覆盖双源验证过的真值源**，精准度是降不是升。
    它真正的价值在**库外条文与司法解释**——库里 20 部法只有 1 部司法解释（69 条）。

诚实的边界（不冒充）
  · 只能查**库里已登记源的法**。库里没有的法（含绝大多数司法解释）没有源可抓，
    跑本脚本会明说「未登记源」；确实要查，用 `--url` 指定一个公开页。
  · 只回答「这一条在源页上长什么样」，**不判断是否现行有效**、**不解释如何适用**。
  · **抓到的条文一律不写回** `core/legal-articles.json`。入库是人工动作
    （核对 → 重跑 legal-crosscheck → 刷新基线），脚本不替人做决定。
  · 抓不到就说抓不到。**没有「大概是这样」这一档。**

用法
    python scripts/legal-lookup.py --article 民法典 585
    python scripts/legal-lookup.py --article 合同编通则解释 3 --max-src 3
    python scripts/legal-lookup.py --article 民法典 585 --offline        # 明示降级（安全要求）
    python scripts/legal-lookup.py --article 某某解释 5 --url https://...  # 库内未登记源时
    python scripts/legal-lookup.py --list-laws

退出码：0 多源一致（可引用）｜1 未完成（离线／未登记源／抓不到）｜2 参数错｜3 单源或冲突（须人工）
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
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "core", "legal-articles.json")
CFG = os.path.join(HERE, "config.json")
THRESHOLD = 0.985          # 与 legal-crosscheck.py 同一口径，不另立阈值

sys.path.insert(0, HERE)
import importlib.util as _ilu


def _load(mod_name, filename):
    """按文件路径加载同目录脚本（不写 .pyc、不污染 sys.path 的模块名）。"""
    spec = _ilu.spec_from_file_location(mod_name, os.path.join(HERE, filename))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 解析链与比对口径**一律复用**，不另写一套。
# 首跑时另写一套的教训（v3.22.x）：巡检漏了建库那条 strip_line_title，
# 《劳动合同法》89/94 条被误判「疑似换版」，白排查一轮。
PARSE = _load("_lp", "legal-parse.py")    # E2：抓取 ＋ 解析（模块名取 PARSE，与门禁的联网路径判据同名——
                                          # 让 `check.py` 的 NET_CALL_RE 一眼认得出「这里真的会出网」）
CC = _load("_lc", "legal-crosscheck.py")  # E0：比对算法（纯函数，不联网）
LV = _load("_lv", "legal-verify.py")      # E0：条号表示法（"205" / "205.1"）

VERDICT_LABEL = {
    "multi-ok": "多源一致",
    "single": "单源未交叉",
    "conflict": "多源冲突",
    "missing": "源页未找到该条",
}


# ────────────────────────────── 环境判断 ──────────────────────────────

def load_db(path=DB):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def online_allowed():
    """config 里 `legal.allow_online` 为 false 时一律不许出网（安全要求）。

    返回 (允许?, 原因)。**默认允许**——本脚本被显式调用本身就是一次知情同意，
    与 version.py 的 `--check-online` 同口径；但机构可以一处关掉全公司。
    """
    try:
        with io.open(CFG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return True, "config.json 未读到，按默认允许"
    legal = cfg.get("legal") or {}
    if legal.get("allow_online") is False:
        return False, "config.json 里 legal.allow_online = false（机构安全策略）"
    return True, "config.json 未禁止联网"


def _guard_url(u):
    """只读公开页：拒绝非 http(s)、拒绝本机与内网字面量。

    不是什么严密的 SSRF 防护（本地 CLI 工具，使用者跑在自己机器上），
    而是把「手滑把内网地址填进来」这类事故挡在出网之前。
    """
    if not re.match(r"^https?://", u, re.I):
        raise SystemExit("[参数错误] --url 只接受 http/https 公开页地址：%s" % u)
    host = re.sub(r"^https?://", "", u, flags=re.I).split("/")[0].split(":")[0].lower()
    if (host in ("localhost", "0.0.0.0", "::1") or host.startswith("127.")
            or host.startswith("10.") or host.startswith("192.168.")
            or host.startswith("169.254.")
            or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host)):
        raise SystemExit("[参数错误] 拒绝本机／内网地址（本脚本只读公开页）：%s" % host)
    return u


def sources_for(db, law):
    """该法已登记的源，**按 grp 分组、每组取一条**。

    分组的道理与建库时一致：同一份文本拆成几页的 URL 会被归到同一 grp，
    必须拼起来算**一个**源，否则会把「同一页」误判成「两源一致」。
    """
    groups = {}
    for s in db.get("sources") or []:
        if s.get("law") != law or not s.get("url"):
            continue
        groups.setdefault(s.get("grp", 0), []).append(s)
    out = []
    for _g, items in sorted(groups.items()):
        items.sort(key=lambda x: -(x.get("articles") or 0))
        out.append(items[0])
    return out


# ────────────────────────────── 抓取与核对 ──────────────────────────────

def grab_one(src, want_key, verify=True):
    """抓一个源 → 解析全页 → 取出该条。返回 (正文或None, 该页解析条数, 错误摘要或None)。

    **默认严格校验证书**（`verify=True`）。理由：这里抓回来的条文是要被当原文引用的，
    中间人替换比"抓不到"危险得多——抓不到可以如实说抓不到，抓到一份被改过的"原文"
    却无从察觉。建库那条链（legal-parse 的默认 None）仍沿用宽松策略，
    因为地方政府站证书链不完整会让源整片消失，而"每部法至少两源"是建库的硬前提。
    """
    try:
        html = PARSE.fetch(src["url"], src.get("enc") or "utf-8", tries=1,
                           verify_tls=True if verify else False)
    except Exception as ex:
        return None, 0, _classify_err(ex)
    try:
        text = PARSE.to_text(html)
    except Exception as ex:
        return None, 0, "页面解码失败：%s" % ex
    try:
        arts = PARSE.parse_articles(text)
    except Exception as ex:
        return None, 0, "条文切分失败：%s" % ex
    body = arts.get(want_key)
    if not body:
        return None, len(arts), None
    try:
        body = PARSE.strip_line_title(body, src.get("law"), want_key)
    except Exception:
        pass
    return body, len(arts), None


def _classify_err(ex):
    """把抓取异常翻成一句人话——「没网」和「源站挂了」是两回事，别混为一谈。"""
    s = "%s" % ex
    low = s.lower()
    if "name or service not known" in low or "getaddrinfo" in low or "nodename" in low:
        return "DNS 解析失败（本机可能无出网，或该域名不可达）"
    if "timed out" in low or "timeout" in low:
        return "连接超时"
    if "certificate" in low or "ssl" in low:
        return "证书校验失败（该站证书链不完整／已过期）——确需抓该站可加 `--insecure`，" \
               "但抓回内容未经校验，引用前须以官方文本复核"
    if "connection refused" in low:
        return "连接被拒"
    return s[:120]


def compare_with_db(db, law, key, fetched):
    """拿抓到的原文与本地库比。返回 (状态码, 说明)。本地无此条也照实说。"""
    ent = ((db.get("laws") or {}).get(law) or {}).get(key)
    if not ent:
        return "db-absent", "本地库未收录此条"
    ratio = CC.compare(ent.get("text", ""), fetched)["ratio"]
    if ratio >= THRESHOLD:
        return "db-same", "一致（%.3f）" % ratio
    return "db-diff", "**不一致（%.3f）**——须人工判断谁对，脚本不猜" % ratio


# ────────────────────────────── 输出 ──────────────────────────────

def _head(law, key):
    return ["## 联网核对：《%s》第%s" % (law, LV.art_label(key)), ""]


def _net_notice(urls, insecure=False):
    out = ["| 项 | 内容 |", "|---|---|",
           "| **检索路径** | **联网补位**（E2 档）。本地优先，联网只在库外或显式要求时发生 |",
           "| **本次出网内容** | 法名 ＋ 条号 ＋ 页面地址请求——**不含任何文档内容、问题原文或使用者信息** |",
           "| **出网站点** | %s |" % ("、".join(urls) if urls else "（无）"),
           "| **证书校验** | %s |" % ("**未校验**（`--insecure`）—— 抓回内容可能被中间人替换，"
                                      "引用前请以官方文本复核" if insecure
                                      else "严格校验（默认）")]
    return out + [""]


def main():
    ap = argparse.ArgumentParser(description="库外条文联网核对（本地库的补位）")
    ap.add_argument("--article", nargs=2, metavar=("LAW", "NO"), help="法名 ＋ 条号，如 民法典 585")
    ap.add_argument("--url", help="库内未登记源时，指定一个公开页地址")
    ap.add_argument("--max-src", type=int, default=2, help="最多抓几个独立源（默认 2，双源阈值）")
    ap.add_argument("--offline", action="store_true", help="强制离线：不做任何网络请求，明示降级")
    ap.add_argument("--insecure", action="store_true",
                    help="不校验证书（默认严格校验；仅当源站证书链不完整导致抓不到时才用，"
                         "用了会在输出里标注，引用的可靠性随之下降）")
    ap.add_argument("--list-laws", action="store_true", help="列出库内哪些法登记了可核对的源")
    ap.add_argument("--json", help="机读结果输出到文件")
    a = ap.parse_args()

    db = load_db()

    if a.list_laws:
        laws = sorted((k for k in (db.get("laws") or {}) if sources_for(db, k)),
                      key=lambda x: -len(db["laws"][x]))
        print("## 可联网核对的法（库内已登记源）\n")
        print("| 法名 | 库内条数 | 源组数（≥2 才可双源交叉） |")
        print("|---|---|---|")
        for k in laws:
            print("| %s | %d | %d |" % (k, len(db["laws"][k]), len(sources_for(db, k))))
        print("\n> 不在上表的法**没有登记源**，本脚本抓不了；要用 `--url` 指定一个公开页。")
        return 0

    if not a.article:
        ap.print_help()
        return 2

    law_raw, no_raw = a.article
    law = LV.pick_law(law_raw) or law_raw
    m = re.match(r"^\s*([一二三四五六七八九十百千零〇\d]{1,8})\s*"
                 r"(?:条)?(?:\s*之([一二三四五六七八九十]{1,3}))?\s*$", no_raw or "")
    key = LV.parse_no(m.group(1), m.group(2)) if m else None
    if not key:
        print("[参数错误] 条号无法解析：%s（可写 585 或 585之一）" % no_raw, file=sys.stderr)
        return 2

    out = _head(law, key)

    # ① 闸门一：使用者显式要求离线
    if a.offline:
        ok, why = False, "命令行加了 `--offline`"
    else:
        ok, why = online_allowed()

    # ② 找源
    srcs = sources_for(db, law)
    if a.url:
        srcs = [{"law": law, "url": _guard_url(a.url), "enc": "utf-8", "grp": 9,
                 "name": PARSE.src_name(a.url)}]

    if not ok or not srcs:
        out += ["### 未完成：没有发出任何网络请求", "",
                "| 项 | 内容 |", "|---|---|"]
        if not ok:
            out.append("| **原因** | 当前不允许联网（%s） |" % why)
            out.append("| **降级到哪** | 本地库检索：`python scripts/legal-search.py --article %s %s` |"
                       % (law, key))
        else:
            out.append("| **原因** | 库内未登记《%s》的源，无从抓取 |" % law)
            out.append("| **怎么办** | ① 用 `--url` 指定一个公开页；② 直接查官方文本后人工核对 |")
            out.append("| **不要做什么** | 不要凭记忆补条文，也不要把「没查到」写成「没问题」 |")
        out += ["",
                "> **本脚本不会在没联网的情况下假装核过。** 本地库能查到的，去 `legal-search.py` 查；",
                "> 本地库查不到的，就是「未收录」，如实标「待核验」。"]
        print("\n".join(out))
        if a.json:
            _dump(a.json, {"law": law, "article": key, "done": False,
                           "reason": why if not ok else "未登记源"})
        return 1

    srcs = srcs[:max(1, a.max_src)]

    # ③ 抓
    got, rows, errs = [], [], []
    for i, s in enumerate(srcs, 1):
        name = s.get("name") or PARSE.src_name(s["url"])
        body, n_arts, err = grab_one(s, key, verify=not a.insecure)
        if err:
            rows.append("| %d | %s | **失败**：%s | — |" % (i, name, err))
            errs.append(err)
        elif not body:
            rows.append("| %d | %s | 抓到，但**未找到该条**（该页解析出 %d 条） | %d |"
                        % (i, name, n_arts, n_arts))
        else:
            rows.append("| %d | %s | 成功 | %d |" % (i, name, n_arts))
            got.append((name, body))

    out += _net_notice([s.get("name") or PARSE.src_name(s["url"]) for s in srcs], a.insecure)
    out += ["### 来源与获取", "",
            "| # | 站点 | 结果 | 该页解析出条数 |", "|---|---|---|---|"] + rows + [""]

    if not got:
        out += ["### 未完成：所有源都没拿到这条", "",
                "> **不凭记忆补条文。** 可能的原因：源页改版、该条不在该页、或本机无出网。",
                "",
                "| 下一步 | 做法 |", "|---|---|",
                "| 换源 | `--max-src 3` 多试一个源 |",
                "| 指定页 | `--url <公开页地址>` 自己给一页 |",
                "| 查本地 | `python scripts/legal-search.py --article %s %s` |" % (law, key)]
        print("\n".join(out))
        if a.json:
            _dump(a.json, {"law": law, "article": key, "done": False,
                           "reason": "所有源均未取到", "errors": errs})
        return 1

    # ④ 判决
    v = CC.verdict(got, THRESHOLD)
    status = v["status"]
    out += ["### 验证判决", ""]
    if status == "multi-ok":
        out += ["**%s**（最差相似度 %.3f ≥ 阈值 %s）→ **可作为条文原文引用**。"
                % (VERDICT_LABEL[status], v["ratio"], THRESHOLD), ""]
        out += ["> 口径：一致只证明「两个独立转载页在这一条上写的一样」，"
                "**不证明它是最新版本、也不证明它适用于你的情形**。"]
    elif status == "single":
        out += ["**%s**（只取到 1 个源）→ **不得说成「已核」**。" % VERDICT_LABEL[status], "",
                "> 正确说法：「某站登载的该条如下，单源，未做交叉验证」。"
                "加大 `--max-src` 可能取到第二个源。"]
    else:
        out += ["**%s**（相似度 %.3f < 阈值 %s）→ **不猜谁对，交人工**。"
                % (VERDICT_LABEL[status], v["ratio"] or 0, THRESHOLD), "",
                "> 常见原因：两个源抓的是**不同版本**的同一部法（条号后移、修正前后），"
                "或其中一页有漏字／串行。**跨版本不能互证**，须先确认两源的版本一致。"]
    out.append("")

    # ⑤ 原文
    out += ["### 原文（取第一源）", "", "> " + got[0][1].replace("\n", " "), ""]
    if status == "conflict":
        c = v["conflict"] or {}
        out += ["**差异（第一源 vs %s）**" % (c.get("with") or "另一源"), "",
                "| 只在第一源出现 | 只在另一源出现 |", "|---|---|",
                "| %s | %s |" % ((c.get("only_base") or "—")[:120], (c.get("only_other") or "—")[:120]),
                ""]

    # ⑥ 与本地库比对
    db_state, db_note = compare_with_db(db, law, key, got[0][1])
    out += ["### 与本地库比对", "",
            "| 项 | 结果 |", "|---|---|",
            "| 本地库是否收录 | %s |" % ("收录" if db_state != "db-absent" else "**未收录**"),
            "| 库内原文 vs 本次抓取 | %s |" % db_note, ""]
    if db_state == "db-same":
        out += ["> **本地库这条是对的，以后用 `legal-search.py` 查即可**，不必再联网——"
                "本地是双源验证过的，快且不出域。"]
    elif db_state == "db-diff":
        out += ["> **库内与源页不一致，先别信任何一个。** 三步：① 确认两源版本是否同一版；"
                "② 若确系库内过期，走换库流程重跑 `legal-crosscheck.py`；③ 期间引用一律标「待核验」。"]
    else:
        out += ["> 这条属**库外条文**。要入库须人工核对后走建库流程，"
                "**脚本不会自动写回** `core/legal-articles.json`。"]
    out += ["",
            "> 本脚本只搬运条文：**不判断现行有效、不解释如何适用、不预测案件结果**。"
            "具体适用须执业律师结合事实认定。"]

    print("\n".join(out))
    if a.json:
        _dump(a.json, {"law": law, "article": key, "done": True, "status": status,
                       "verified": v["verified"], "ratio": v["ratio"],
                       "text": got[0][1], "db_state": db_state,
                       "sources": [n for n, _ in got]})
    return 0 if status == "multi-ok" else 3


def _dump(path, obj):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("\n[已写出机读结果] %s" % path, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
