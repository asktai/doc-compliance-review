#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法规库时效巡检（开发侧，联网，不随包分发）
==============================================================================
为什么要有它（v3.22.2 的直接教训）
------------------------------------------------------------------------------
v3.22.2 补源时才发现《反不正当竞争法》已 2025 年第二次修订，而库内还是 2019 版——
**隔了 4 个月才被发现，靠的是人工撞上**。「域名权威 ≠ 版本现行」：
中国政府网那页广告法至今还是 2015 版；三个标「2018 修正」的劳动法页正文是 1994 原版。
所以巡检**不看页面标题、不看域名**，只做一件可机械判定的事：

    把库里登记的每一个源页面重新抓回来、重新解析、与库内条文逐条比对。
    谁对不上了，就说明「库与它的源之一已经分叉」——要么该法已修订（源页换新版），
    要么转载页自己改了。两种都须人工复核，脚本不猜谁对。

诚实的能力边界（不冒充）：
  · 本巡检回答「库与已登记源是否仍一致」，**不承诺发现库里没有的新法**——
    flk.npc.gov.cn 的搜索接口实测需签名/验证码（HTTP 500），机器不可达，如实登记；
    发现「库外新法」仍靠换库时的人工核对 + check.py 的条号对位守卫兜底。
  · 比对口径与 legal-crosscheck.py 完全一致（4 字片段双向覆盖，阈值 0.985），
    少量差异可能是转载噪声，**大面积不一致（≥50%）才判疑似换版**。

用法
------------------------------------------------------------------------------
    python3 freshness-patrol.py                 # 全部 17 部法
    python3 freshness-patrol.py --law 劳动法    # 只巡一部
    python3 freshness-patrol.py --json OUT      # 机读结果落盘
退出码：0 全一致；1 有疑似换版/分叉（可直接进 cron）；2 参数/环境错误。

归属：维护侧工具（/workspace/dev/maint/tools/），联网、不进技能包、不进发布链。
"""

import sys
sys.dont_write_bytecode = True
import argparse
import datetime
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "..", "doc-compliance-review")
DB_PATH = os.path.join(SKILL, "core", "legal-articles.json")


def _load_builder():
    """复用 build-legal-db.py 的抓取与解析（同一套判据，避免两套实现漂移）。"""
    p = os.path.join(HERE, "build-legal-db.py")
    spec = importlib.util.spec_from_file_location("build_legal_db", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._load_crosscheck(HERE)
    return m


def main():
    ap = argparse.ArgumentParser(description="法规库时效巡检：重抓源页面与库内条文比对")
    ap.add_argument("--law", help="只巡检某部法（子串匹配）")
    ap.add_argument("--json", metavar="PATH", help="机读结果写入该路径")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="两次抓取间隔秒数（默认 1.0，对源站客气些）")
    a = ap.parse_args()

    B = _load_builder()
    fetch, parse_articles, compare = B.fetch, B.parse_articles, B.CROSS.compare
    to_text, SOURCES, GROUPS = B.to_text, B.SOURCES, B.GROUPS
    # 与 builder main 同一链：抽条后须再做一次条目标题剥离，否则混进标题的
    # 源页（如龙陵县版劳动合同法）会被误判成「大面积不一致」
    strip_line_title = B.strip_line_title

    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    laws = db["laws"]
    meta = db.get("meta") or {}

    targets = [lw for lw in SOURCES
               if lw in laws and (not a.law or a.law in lw)]
    if a.law and not targets:
        print("配置与库里都找不到这部法：%s" % a.law)
        return 2

    today = datetime.date.today()
    # 先报一遍「尚未施行」的 pending 条目（如商标法 2027-01-01）
    pend = []
    for lw, m in sorted(meta.items()):
        eff = str(m.get("effective") or "")
        try:
            if datetime.date.fromisoformat(eff) > today:
                pend.append("%s（%s 施行）" % (lw, eff))
        except ValueError:
            pass
    if pend:
        print("[i] 已登记但尚未施行：%s" % "；".join(pend))
    print("[i] 巡检 %d 部法（库截至 %s）" % (len(targets), str(db.get("generated"))[:10]))
    print()

    alerts, notes = [], []
    result = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
              "lib_generated": str(db.get("generated"))[:10], "laws": {}}

    for law in targets:
        urls = [u for u, _ in SOURCES[law]]
        encs = [e for _, e in SOURCES[law]]
        grps = GROUPS.get(law, list(range(len(urls))))
        lib = laws[law]
        per_law = {"sources": [], "alert": False}
        for gi in sorted(set(grps)):
            pages = [i for i, g in enumerate(grps) if g == gi]
            name = B.src_name(urls[pages[0]])
            try:
                text = "".join(to_text(fetch(urls[i], encs[i], tries=2)) for i in pages)
                got = {k: strip_line_title(v, law, k)
                       for k, v in parse_articles(text).items()}
            except Exception as ex:
                msg = "%s｜%s ｜ 抓取失败：%s" % (law, name, ex)
                notes.append(msg); per_law["sources"].append(
                    {"name": name, "state": "fetch_fail", "err": str(ex)})
                print("[WARN] " + msg)
                time.sleep(a.sleep)
                continue
            shared = sorted(set(int(k) for k in got) & set(int(k) for k in lib))
            # 库是按 WANTED 选条收录的（如食品安全法仅收第 148 条、商标法仅 3 条），
            # 阈值必须相对库内条数，不能用绝对数——否则选条少的法永远报警
            if len(shared) < max(1, int(0.5 * len(lib))):
                msg = "%s｜%s ｜ 共同条号仅 %d/%d 条（页面可能已改版）" % (
                    law, name, len(shared), len(lib))
                notes.append(msg); per_law["sources"].append(
                    {"name": name, "state": "few_shared", "shared": len(shared)})
                print("[WARN] " + msg)
                time.sleep(a.sleep)
                continue
            bad = []
            for no in shared:
                r = compare(lib[str(no)]["text"], got[no])
                if r["ratio"] < 0.985:
                    bad.append((no, r["ratio"]))
            frac = len(bad) / float(len(shared))
            state = ("suspect" if frac >= 0.5 else
                     "noisy" if bad else "ok")
            per_law["sources"].append(
                {"name": name, "state": state, "shared": len(shared),
                 "bad": [[n, rt] for n, rt in bad], "frac": round(frac, 3)})
            if state == "suspect":
                msg = ("%s｜%s ｜ %d/%d 条不一致（%.0f%%）——疑似该法已修订或页面已换版，须人工复核"
                       % (law, name, len(bad), len(shared), frac * 100))
                alerts.append(msg); per_law["alert"] = True
                print("[ALERT] " + msg)
            elif state == "noisy":
                msg = "%s｜%s ｜ %d/%d 条轻微不一致（多为转载噪声，低于换版线）" % (
                    law, name, len(bad), len(shared))
                notes.append(msg)
                print("[WARN] " + msg)
            else:
                print("[OK]   %s｜%s ｜ %d 条全一致" % (law, name, len(shared)))
            time.sleep(a.sleep)
        result["laws"][law] = per_law
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
