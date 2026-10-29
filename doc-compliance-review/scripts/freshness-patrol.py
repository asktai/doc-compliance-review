#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L2  不联网就用不成（能力依赖外部知识）；须显式调用，离线须明示降级
"""法规库失效巡检（**随包**；联网例外脚本之一，须显式调用）

回答一个问题：**我手上这份法规库，和它当初抓的那些源页面，还是不是一回事？**

为什么要有它（v3.22.2 的直接教训）
------------------------------------------------------------------------------
v3.22.2 补源时才发现《反不正当竞争法》已 2025 年第二次修订，而库内还是 2019 版——
**隔了 4 个月才发现，靠的是人工撞上**。本脚本把这件事变成可跑的动作：
把库里登记的每一个源页面重新抓回来、重新解析、与库内条文逐条比对。
谁对不上了，就说明「库与它的源之一已经分叉」——要么该法已修订（源页换新版），
要么转载页自己改了。两种都须人工复核，脚本**不猜谁对**。

诚实的能力边界（不冒充）
------------------------------------------------------------------------------
  · 本巡检回答「库与**已登记源**是否仍一致」，**不承诺发现库里没有的新法**。
    flk.npc.gov.cn 的检索接口实测需签名/验证码（HTTP 500），机器不可达，如实登记；
    「库外是不是出了新法」仍靠换库时的人工核对 + `--audit-rules` 条号对位守卫兜底。
  · 比对口径与 legal-crosscheck.py 完全一致（4 字片段双向覆盖，阈值 0.985），
    少量差异可能是转载噪声，**只有大面积不一致（≥50%）才判疑似换版**。
  · 解析链与建库**共用同一份**（legal-parse.py）。另写一套必漂移——
    首跑时龙陵县版《劳动合同法》89/94 条被判「疑似换版」，根因就是漏了
    建库那条 `strip_line_title`（该页把每条小标题混进正文）。

用法
------------------------------------------------------------------------------
    python scripts/freshness-patrol.py                 # 全部法（联网）
    python scripts/freshness-patrol.py --law 劳动法    # 只巡一部
    python scripts/freshness-patrol.py --json OUT      # 机读结果落盘
    python scripts/freshness-patrol.py --self-test     # **离线自检**（不联网，出包门禁用）
退出码：0 全一致；1 有疑似换版/分叉或须人工补巡（可直接进 cron）；2 参数/环境错误。

联网与隐私
------------------------------------------------------------------------------
本脚本**只抓公开法规页面，不接触、不读取、不上传任何使用者文档**——
它连文档路径参数都没有。**默认不会被自动调用**，只有人显式跑它才联网。
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
import datetime
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_PATH = os.path.join(ROOT, "core", "legal-articles.json")

PARSE = None
CROSS = None


def _load_modules():
    global PARSE, CROSS
    for name, fn in (("legal_parse", "legal-parse.py"),
                     ("legal_crosscheck", "legal-crosscheck.py")):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            raise SystemExit("[E] 找不到 %s（同目录），无法巡检" % fn)
        spec = importlib.util.spec_from_file_location(name, p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        if name == "legal_parse":
            PARSE = m
        else:
            CROSS = m


def self_test():
    """离线自检：不联网，只验判据本身（三组已知答案 + 阈值常量在合理区间）。

    为什么自检必须是离线的：出包门禁不能依赖网络——源站挂了就装不了包，
    而且门禁要验的是「判据对不对」，不是「源站活着没有」。
    """
    ok, bad = [], []

    def check(name, cond, detail=""):
        (ok if cond else bad).append("%s%s" % (name, ("：" + detail) if detail else ""))

    c = CROSS.compare
    a = "用人单位自用工之日起即与劳动者建立劳动关系。用人单位应当建立职工名册备查。"
    b = "劳动关系的建立用人单位自用工之日起即与劳动者建立劳动关系。用人单位应当建立职工名册备查。"
    r_ident = c(a, a)
    r_title = c(a, b)                       # 混入条目标题：应低于阈值（这正是首跑误报的型）
    r_other = c(a, "经营者不得实施下列混淆行为，引人误认为是他人商品。")
    check("同一条文必判一致", r_ident["ratio"] >= 0.985, "ratio=%.3f" % r_ident["ratio"])
    check("混入条目标题须判不一致（否则换版就漏）", r_title["ratio"] < 0.985,
          "ratio=%.3f" % r_title["ratio"])
    check("完全无关的条文须判不一致", r_other["ratio"] < 0.5, "ratio=%.3f" % r_other["ratio"])
    check("换版判定阈值 0.985 在合理区间", 0.95 <= 0.985 <= 0.999)
    check("大面积判据 ≥50% 在合理区间", 0.3 <= 0.5 <= 0.8)

    # 库内 sources 必须带 grp/enc，否则包内巡检无从定位源
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    miss = [s.get("url", "?") for s in (db.get("sources") or [])
            if "grp" not in s or "enc" not in s]
    check("库内 sources 均带 grp/enc（巡检据此定位源）", not miss,
          ("缺 %d 个，如 %s" % (len(miss), miss[0])) if miss else "")

    print("法规库失效巡检 · 离线自检")
    for x in ok:
        print("  [OK] " + x)
    for x in bad:
        print("  [FAIL] " + x)
    print("结果：%d 项通过、%d 项失败（离线，未联网）" % (len(ok), len(bad)))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="法规库失效巡检（联网；须显式调用）")
    ap.add_argument("--law", help="只巡检某部法（子串匹配）")
    ap.add_argument("--json", metavar="PATH", help="机读结果写入该路径")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="两次抓取间隔秒数（默认 1.0，对源站客气些）")
    ap.add_argument("--self-test", action="store_true",
                    help="离线自检：只验判据与库内字段，不联网（出包门禁用）")
    a = ap.parse_args()

    _load_modules()
    if a.self_test:
        return self_test()

    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    laws, meta = db["laws"], (db.get("meta") or {})

    # 源清单来自**库自身**（建库时随库下发 grp/enc），不依赖开发侧配置
    by_law = {}
    for s in (db.get("sources") or []):
        if s.get("law") in laws:
            by_law.setdefault(s["law"], []).append(s)
    targets = sorted(lw for lw in by_law if lw in laws and (not a.law or a.law in lw))
    if a.law and not targets:
        print("库里没有这部法：%s" % a.law)
        return 2

    today = datetime.date.today()
    pend = []
    for lw, m in sorted(meta.items()):
        try:
            if datetime.date.fromisoformat(str(m.get("effective") or "")) > today:
                pend.append("%s（%s 施行）" % (lw, m.get("effective")))
        except ValueError:
            pass
    if pend:
        print("[i] 已登记但尚未施行：%s" % "；".join(pend))
    print("[i] 巡检 %d 部法（库截至 %s，源 %d 个）"
          % (len(targets), str(db.get("generated"))[:10],
             sum(len(v) for v in by_law.values())))
    print()

    alerts, notes = [], []
    result = {"when": datetime.datetime.now().isoformat(timespec="seconds"),
              "lib_generated": str(db.get("generated"))[:10], "laws": {}}

    for law in targets:
        lib = laws[law]
        per = {"sources": [], "alert": False}
        for gi in sorted({s["grp"] for s in by_law[law]}):
            pages = [s for s in by_law[law] if s["grp"] == gi]
            name = pages[0].get("name") or pages[0].get("url", "?")
            try:
                text = "".join(PARSE.to_text(PARSE.fetch(s["url"], s.get("enc", "utf-8"),
                                                         tries=2)) for s in pages)
                got = {k: PARSE.strip_line_title(v, law, k)
                       for k, v in PARSE.parse_articles(text).items()}
            except Exception as ex:
                msg = "%s｜%s ｜ 抓取失败：%s" % (law, name, ex)
                notes.append(msg)
                per["sources"].append({"name": name, "state": "fetch_fail", "err": str(ex)})
                print("[WARN] " + msg)
                time.sleep(a.sleep)
                continue
            shared = sorted(set(int(k) for k in got) & set(int(k) for k in lib))
            # 库是按 WANTED 选条收录的（如食品安全法仅收第 148 条、商标法 3 条），
            # 阈值必须相对库内条数，用绝对数会让选条少的法永远报警
            if len(shared) < max(1, int(0.5 * len(lib))):
                msg = "%s｜%s ｜ 共同条号仅 %d/%d 条（页面可能已改版）" % (
                    law, name, len(shared), len(lib))
                notes.append(msg)
                per["sources"].append({"name": name, "state": "few_shared",
                                       "shared": len(shared)})
                print("[WARN] " + msg)
                time.sleep(a.sleep)
                continue
            bad = [(no, CROSS.compare(lib[str(no)]["text"], got[no])["ratio"])
                   for no in shared]
            bad = [(no, r) for no, r in bad if r < 0.985]
            frac = len(bad) / float(len(shared))
            state = "suspect" if frac >= 0.5 else ("noisy" if bad else "ok")
            per["sources"].append({"name": name, "state": state, "shared": len(shared),
                                   "bad": bad, "frac": round(frac, 3)})
            if state == "suspect":
                msg = ("%s｜%s ｜ %d/%d 条不一致（%.0f%%）——疑似该法已修订或页面已换版，须人工复核"
                       % (law, name, len(bad), len(shared), frac * 100))
                alerts.append(msg)
                per["alert"] = True
                print("[ALERT] " + msg)
            elif state == "noisy":
                msg = "%s｜%s ｜ %d/%d 条轻微不一致（多为转载噪声，低于换版线）" % (
                    law, name, len(bad), len(shared))
                notes.append(msg)
                print("[WARN] " + msg)
            else:
                print("[OK]   %s｜%s ｜ %d 条全一致" % (law, name, len(shared)))
            time.sleep(a.sleep)
        result["laws"][law] = per
        print()

    print("=" * 62)
    for m in notes:
        print("[WARN]", m)
    if alerts:
        print("结果：%d 处疑似分叉/换版，须人工复核（脚本不猜谁对）" % len(alerts))
        rc = 1
    elif notes:
        print("结果：无疑似换版，但 %d 处须人工补巡（改版/抓取失败）" % len(notes))
        rc = 1
    else:
        print("结果：库与全部已登记源一致")
        rc = 0
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"alerts": alerts, "notes": notes, "rc": rc, **result},
                      f, ensure_ascii=False, indent=1)
        print("机读结果：%s" % a.json)
    return rc


if __name__ == "__main__":
    sys.exit(main())
