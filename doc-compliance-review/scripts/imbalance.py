#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""失衡画像：单文档内部多处问题的横向归纳（报告 3.5 节的计算器）

逐条分析是**纵向**的——一条一条看，每条都说得通。但律师真正该抓的往往不是某一条，
而是**这些条款合起来往哪边偏**。一条违约金过高是个案；付款、违约、解除、管辖五条
全都单向有利于甲方，那是**设计**，不是笔误。

本脚本只做**计数与判定**，不做法律判断：
  · 归类：一条归入哪个维度、算不算计入条款，由调用方（模型／律师）给定
  · 计算：方向占比、维度集中度、是否达到「系统性」阈值
  · 输出：可直接抄进报告的一屏结论

为什么把阈值写死在代码里：口头约定「同向 3 条以上算系统性」，写着写着就会变成
「差不多同向就算」——**结论要能复现，判断标准就必须是常量，不是感觉**。

用法
  python scripts/imbalance.py --rows rows.json --side 甲方
  python scripts/imbalance.py --file 审查意见.md          # 从报告里抓条款表（实验性）
  python scripts/imbalance.py --self-test                 # 跑内置用例，验证判定逻辑

rows.json 格式（由审查流程生成）：
  [{"no": "8.2", "level": "★★★", "dim": "违约责任", "against": true},
   {"no": "4.1", "level": "★★",  "dim": "付款与结算", "against": true},
   {"no": "9.3", "level": "★★",  "dim": "违约责任", "against": false}]
  level  : "★★★" | "★★" | "★"
  dim    : 七类维度之一（见 DIMS）
  against: true＝对我方不利；false＝对我方有利（以 --side 指定的我方立场为基准）

退出码：0 正常；2 参数或数据错误
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 判定常量（写死，改要过 review）

MIN_ROWS = 3          # 计入条款少于 3 条，一律不判 —「样本不足就说不判」
MIN_SAME = 3          # 同向至少 3 条
MIN_DIM = 2           # 「最集中维度」的条数门槛：只有 1 条的维度算不上集中
MAJORITY = 0.60       # 同向占比达到 60% 才叫「系统性」
WEIGHT = {"★★★": 2, "★★": 1}   # ★ 不计入：混进来会把结论稀释成一个什么都算的数字

DIMS = ["付款与结算", "交付与验收", "违约责任", "解除与终止",
        "责任限制与赔偿范围", "知识产权与保密", "管辖与争议解决"]

VERDICT_AGAINST = "系统性有利于对方"
VERDICT_FOR = "系统性有利于我方"
VERDICT_BALANCED = "基本均衡"
VERDICT_NA = "未发现系统性偏移"
VERDICT_NO_SIDE = "未指定我方立场，不做偏向判断"


def normalize(rows):
    """只保留计入条款（★★★ / ★★），其余原样告诉调用方被剔掉了多少。"""
    kept, dropped = [], 0
    for r in rows or []:
        lv = (r.get("level") or "").strip()
        if lv not in WEIGHT:
            dropped += 1
            continue
        dim = (r.get("dim") or "").strip()
        if dim not in DIMS:
            # 维度认不出：不猜它属于哪类，直接计入「未归类」并让结论标注
            dim = "未归类"
        kept.append({"no": str(r.get("no") or "").strip(), "level": lv,
                     "dim": dim, "against": bool(r.get("against"))})
    return kept, dropped


def judge(rows, side=""):
    """算失衡画像。只做计数与判定，不做法律判断。"""
    kept, dropped = normalize(rows)
    n = len(kept)

    res = {"side": side, "count": n, "dropped": dropped,
           "count_against": 0, "count_for": 0, "weight_against": 0, "weight_for": 0,
           "count_star3": 0, "count_star2": 0,
           "ratio_against": 0.0, "ratio_for": 0.0,
           "verdict": "", "systemic": False, "dims": [], "top_dims": [],
           "unclassified": 0, "notes": []}

    for r in kept:
        if r["level"] == "★★★":
            res["count_star3"] += 1
        elif r["level"] == "★★":
            res["count_star2"] += 1
        if r["against"]:
            res["count_against"] += 1
            res["weight_against"] += WEIGHT[r["level"]]
        else:
            res["count_for"] += 1
            res["weight_for"] += WEIGHT[r["level"]]

    # 占比按「条数」算，不按权重——权重只用于排序与描述，避免权重放大少数条
    if n:
        res["ratio_against"] = res["count_against"] / float(n)
        res["ratio_for"] = res["count_for"] / float(n)

    # 维度分布
    agg = {}
    for r in kept:
        d = agg.setdefault(r["dim"], {"dim": r["dim"], "count": 0,
                                      "against": 0, "for": 0, "max_level": "★",
                                      "nos": []})
        d["count"] += 1
        d["against" if r["against"] else "for"] += 1
        if WEIGHT[r["level"]] > WEIGHT.get(d["max_level"], 0):
            d["max_level"] = r["level"]
        if r["no"]:
            d["nos"].append(r["no"])
    dims = sorted(agg.values(), key=lambda x: (-x["count"], -x["against"]))
    res["dims"] = dims
    res["unclassified"] = agg.get("未归类", {}).get("count", 0)

    # ---- 判定 ----
    if n < MIN_ROWS:
        res["verdict"] = VERDICT_NA
        res["systemic"] = False
        res["notes"].append("计入条款不足 %d 条，未作偏移判断" % MIN_ROWS)
    elif res["count_against"] >= MIN_SAME and res["ratio_against"] >= MAJORITY:
        res["verdict"] = VERDICT_AGAINST
        res["systemic"] = True
        res["top_dims"] = [d["dim"] for d in dims if d["against"] and d["count"] >= MIN_DIM][:3]
    elif res["count_for"] >= MIN_SAME and res["ratio_for"] >= MAJORITY:
        res["verdict"] = VERDICT_FOR
        res["systemic"] = True
        res["top_dims"] = [d["dim"] for d in dims if d["for"] and d["count"] >= MIN_DIM][:3]
    elif res["count_against"] >= MIN_SAME and res["count_for"] >= MIN_SAME:
        res["verdict"] = VERDICT_BALANCED
        res["systemic"] = False
    else:
        res["verdict"] = VERDICT_NA
        res["systemic"] = False
        res["notes"].append("未达「同向 %d 条且占比 ≥%d%%」，不判为系统性偏移"
                            % (MIN_SAME, int(MAJORITY * 100)))

    if res["unclassified"]:
        res["notes"].append("有 %d 条维度未归类，未计入集中度排序，请人工确认归属"
                            % res["unclassified"])
    if dropped:
        res["notes"].append("已剔除 %d 条 ★ 提示项（不参与统计）" % dropped)

    # 没立场就不给偏向结论——同一份合同，我方是甲方还是乙方结论完全相反。
    # 这里必须把结论整体作废，而不是「照常给结论再加一句备注」：
    # 备注没人看，结论会被直接抄进报告。
    if not side:
        res["verdict"] = VERDICT_NO_SIDE
        res["systemic"] = False
        res["top_dims"] = []
        res["notes"].append("未指定我方立场，不做偏向判断——"
                            "同一份合同换个立场结论相反，无立场的偏向结论是错的")
    return res


def _level_bar(r):
    return "·" * r


def render(res, fmt="md"):
    """输出一屏结论，可直接抄进报告「失衡画像」一节。"""
    L = []
    side = res.get("side") or "（未指定）"
    L.append("【失衡画像】本件整体偏向：%s" % res["verdict"])
    L.append("")
    L.append("· 我方立场：%s" % side)

    # 无立场：整体作废，不印任何百分比与维度分布，免得被当成结论抄走
    if res["verdict"] == VERDICT_NO_SIDE:
        L.append("")
        L.append("· 本节不作偏向判断。**同一份合同，我方是甲方还是乙方，结论完全相反**——")
        L.append("  在立场未定的情况下谈「偏向谁」，得到的数字是错的，抄进报告会误导谈判。")
        L.append("· 请先在谈判地位档位（1.6）选定我方立场，再重新生成本节。")
        for n in res.get("notes", []):
            if "未指定我方立场" not in n:
                L.append("· 注：%s" % n)
        return "\n".join(L)

    if res["count"] == 0:
        L.append("· 无计入条款（★★★／★★），未作偏移判断。")
        for n in res["notes"]:
            L.append("· 注：%s" % n)
        return "\n".join(L)

    L.append("· 证据：计入 %d 条（★★★ %d、★★ %d），对我方不利 %d 条（占 %d%%）、"
             "有利 %d 条（占 %d%%）。"
             % (res["count"], res["count_star3"], res["count_star2"],
                res["count_against"], round(res["ratio_against"] * 100),
                res["count_for"], round(res["ratio_for"] * 100)))

    if res["dims"]:
        L.append("· 维度分布（按集中度排序）：")
        for d in res["dims"]:
            arrow = "对我方不利 %d 条" % d["against"] if d["against"] >= d["for"] \
                else "对我方有利 %d 条" % d["for"]
            nos = "、".join("第 %s 条" % x for x in d["nos"][:6])
            L.append("  - %s：%d 条（%s，最高 %s）%s"
                     % (d["dim"], d["count"], arrow, d["max_level"],
                        ("｜" + nos) if nos else ""))
        if res["top_dims"]:
            L.append("· 最集中维度：%s" % "、".join(res["top_dims"]))

    if res["systemic"]:
        L.append("· 性质判断：多处同向，属**系统性偏移**而非个别失误——"
                 "单条谈判收益有限，建议整体重谈。")
    elif res["verdict"] == VERDICT_BALANCED:
        L.append("· 性质判断：双方均有相当数量条款偏己方，**基本均衡**，"
                 "按逐条分析修改即可，无需整体重谈。")
    else:
        L.append("· 性质判断：**未发现系统性偏移**——本次样本不足以支撑"
                 "「整体偏向某方」的结论，按逐条分析处理。")
        if res["count"] < MIN_ROWS:
            L.append("  （对照看：占比看似很高，但计入仅 %d 条，"
                     "低于 %d 条门槛。**少数几条同向说明不了整体偏向**，"
                     "硬说成「系统性」会误导谈判策略。）" % (res["count"], MIN_ROWS))

    for n in res["notes"]:
        L.append("· 注：%s" % n)

    L.append("· 本节只作归纳，不新增风险点；具体修改见逐条分析与修订件。")
    return "\n".join(L)


# ---------------------------------------------------------------- 自检

CASES = ["系统性有利于对方", "样本不足", "占比不足60%", "系统性有利于我方",
         "空数据", "维度未归类", "最集中维度门槛",
         "无立场不给偏向结论", "无立场时不印百分比"]


def self_test():
    """内置用例：判定逻辑必须能过这几组。任何一组不过，脚本不许用。"""
    fails = []

    def case(label, rows, side, want_verdict, want_sys):
        r = judge(rows, side)
        if r["verdict"] != want_verdict or r["systemic"] != want_sys:
            fails.append("%s：期望 %s/%s，实为 %s/%s"
                         % (label, want_verdict, want_sys, r["verdict"], r["systemic"]))
        return r

    # ① 系统性有利于对方：9/11 不利
    rows = [{"no": str(i), "level": "★★", "dim": "违约责任", "against": True} for i in range(9)]
    rows += [{"no": "10", "level": "★★", "dim": "交付与验收", "against": False},
             {"no": "11", "level": "★", "dim": "付款与结算", "against": False}]
    r = case("系统性有利于对方", rows, "甲方", VERDICT_AGAINST, True)
    if r["count"] != 10:
        fails.append("★ 提示项应被剔除，计入应为 10，实为 %d" % r["count"])
    if (r["count_star3"], r["count_star2"]) != (0, 10):
        fails.append("★★★/★★ 计数错：期望 (0,10)，实为 (%d,%d)"
                     % (r["count_star3"], r["count_star2"]))
    if "★★★ 0、★★ 10" not in render(r):
        fails.append("证据行未如实输出 ★★★/★★ 条数")

    # ② 样本不足：2 条同向也不能叫系统性
    case("样本不足", [{"no": "1", "level": "★★★", "dim": "违约责任", "against": True},
                    {"no": "2", "level": "★★", "dim": "违约责任", "against": True}],
         "甲方", VERDICT_NA, False)

    # ③ 同向 4 条但只占 4/8＝50%，不到 60%，不判系统性
    rows = [{"no": str(i), "level": "★★", "dim": "违约责任", "against": True} for i in range(4)]
    rows += [{"no": str(10 + i), "level": "★★", "dim": "付款与结算", "against": False}
             for i in range(4)]
    case("占比不足60%", rows, "甲方", VERDICT_BALANCED, False)

    # ④ 系统性有利于我方（同一批数据，换成对方立场）
    rows = [{"no": str(i), "level": "★★★", "dim": "违约责任", "against": False} for i in range(4)]
    case("系统性有利于我方", rows, "乙方", VERDICT_FOR, True)

    # ⑤ 全空
    case("空数据", [], "甲方", VERDICT_NA, False)

    # ⑥ 维度认不出 → 计入未归类，但不能因此改变方向判定
    rows = [{"no": str(i), "level": "★★", "dim": "某个没听说过的维度", "against": True}
            for i in range(3)]
    r = case("维度未归类", rows, "甲方", VERDICT_AGAINST, True)
    if r["unclassified"] != 3:
        fails.append("维度认不出应计入未归类 3 条，实为 %d" % r["unclassified"])

    # ⑧ 没立场 → 结论整体作废，不许照常给出偏向
    rows = [{"no": str(i), "level": "★★", "dim": "违约责任", "against": True} for i in range(9)]
    r = judge(rows, "")
    if r["verdict"] != VERDICT_NO_SIDE or r["systemic"]:
        fails.append("未指定立场时仍给出了偏向结论：%s/%s" % (r["verdict"], r["systemic"]))
    # ⑨ 无立场的输出里不得出现百分比与维度分布——数字会被当成结论抄走
    out = render(r)
    if "占 100%" in out or "维度分布" in out:
        fails.append("未指定立场时输出里仍印了百分比/维度分布，会被当成结论抄走")
    if "选定我方立场" not in out:
        fails.append("未指定立场时没告诉使用者该怎么办")

    # ⑦ 「最集中维度」不得把只有 1 条的维度算进去（否则谈判重点被稀释）
    rows = [{"no": "8.%d" % i, "level": "★★", "dim": "违约责任", "against": True}
            for i in range(1, 5)]
    rows += [{"no": "4.1", "level": "★★", "dim": "付款与结算", "against": True},
             {"no": "4.2", "level": "★★", "dim": "付款与结算", "against": True},
             {"no": "12.1", "level": "★★", "dim": "管辖与争议解决", "against": True}]
    r = case("最集中维度门槛", rows, "甲方", VERDICT_AGAINST, True)
    if "管辖与争议解决" in r["top_dims"]:
        fails.append("只有 1 条的维度不该进「最集中维度」：%s" % r["top_dims"])
    if r["top_dims"] != ["违约责任", "付款与结算"]:
        fails.append("最集中维度应为 违约责任、付款与结算，实为 %s" % r["top_dims"])

    return fails


def main():
    ap = argparse.ArgumentParser(description="失衡画像：单文档多处问题的横向归纳")
    ap.add_argument("--rows", help="条款行 JSON 文件")
    ap.add_argument("--side", default="", help="我方立场（甲方／乙方／某方），必填才有意义")
    ap.add_argument("--json", help="把结果另存为 JSON")
    ap.add_argument("--self-test", action="store_true", help="跑内置用例验证判定逻辑")
    a = ap.parse_args()

    if a.self_test:
        fails = self_test()
        if fails:
            for f in fails:
                print("[FAIL] " + f)
            print("自检失败 %d 项" % len(fails))
            return 1
        print("[OK] 失衡画像判定逻辑自检通过（%d 组用例）" % len(CASES))
        return 0

    if not a.rows:
        ap.error("需要 --rows 或 --self-test")

    try:
        rows = json.load(open(a.rows, encoding="utf-8"))
    except Exception as e:
        print("[E] 读不了 %s：%s" % (a.rows, e))
        return 2
    if isinstance(rows, dict):
        # 只认 {"rows": [...]} 这一种包法；其余 dict 一律当错误，不静默当空数据
        if "rows" not in rows:
            print("[E] %s 是对象但没有 rows 字段；请传数组或 {\"rows\": [...]}" % a.rows)
            return 2
        rows = rows.get("rows") or []
    if not isinstance(rows, list):
        print("[E] rows 应为数组，实为 %s" % type(rows).__name__)
        return 2
    if not rows:
        print("[E] rows 为空，无从判断；拒绝输出一份「未发现偏移」的假结论")
        return 2

    res = judge(rows, a.side)
    print(render(res))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print("\n[已写出 %s]" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
