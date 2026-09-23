#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
样例级人工基线（scripts/sample-baseline.py）
============================================
用途：自动基线（`rule-baseline.py`）只验"规则条目改没改"，验不出"改完之后审查结论
      还对不对"。本脚本补上这一层——把"这份样例文档该报出哪几条风险"固化成**台账**，
      之后每次规则大改 / 换模型 / 升版，跑一次比对，看**漏报、评级漂移、多报**。

      审查结论由模型作出，脚本**不能自动生成预期**——预期只能人工（或人驱动模型）
      填写，本脚本负责**存得住、比得动、跑得出差异**。

用法：
    python sample-baseline.py --list                 列出台账全部用例与预期
    python sample-baseline.py --check <报告.md|目录>   拿实际报告与台账比对（漏报/漂移/多报）
    python sample-baseline.py --check <目录> --case S1 只比对 S1（报告名含样例名即自动配对）
    python sample-baseline.py --verify               只校验台账自身（供 check.py 调用）
    python sample-baseline.py --record --id S1 \
           --sample samples/敏感信息示例.docx \
           --findings "第六条 付款|付款与验收脱钩|2|P4/第六条/付款" \
           --status confirmed --by 胡皓              写入/覆盖一个用例
    python sample-baseline.py --json                 机器可读输出（供 CI）

--findings 每项格式：「条款定位|风险点关键词|预期★数[|规则ID][/备选定位…]」，可重复传多个，
或用分号分隔。**备选定位**用 `/` 分隔：报告标题写法不固定（有人写「第六条 违约责任」，有人
写「违约金」），任一定位命中即算该项报出——没有备选时，标题写法一变就是假漏报。
--status：draft＝初拟（比对只提示、不计失败）；confirmed＝已人工确认（比对计失败）。

台账文件：`core/_sample-baseline.json`（随包，可读可改）。
报告解析：按审查意见报告的章节标题「## N. <条款定位>  ★★★ 高风险」取定位与评级；
若报告里写了规则 ID（如 `（P1）`），也一并抽出用于对账。
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import re
import json
import argparse
import datetime

try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, "core", "_sample-baseline.json")
CORE = os.path.join(ROOT, "core", "01-general-risk-rules.md")

CORE_ID_RE = re.compile(r"\|\s*([PVLGICDHEQWMNKJSTFXB]\d+)\s*\|")
# 报告章节标题：「## 1. 第一条 标的  ★★★ 高风险」
RE_HEAD = re.compile(r"^##\s+\d+\.\s*(.+?)\s+(★+)\s*(\S*)", re.M)
# 报告里可能标注的规则 ID：「（P1）」「[P1]」「规则 P1」
RE_RULE = re.compile(r"[（(\[]\s*([PVLGICDHEQWMNJSTFXB]\d+)\s*[)）\]]|规则\s*([PVLGICDHEQWMNJSTFXB]\d+)")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def load():
    if not os.path.exists(LEDGER):
        return None
    try:
        return json.loads(_read(LEDGER))
    except Exception as e:
        print("[sample-baseline] 台账解析失败：%s" % e)
        return None


def core_ids():
    """core/01 现有规则 ID 集合（校验台账里写的 ID 是否真实存在）。"""
    if not os.path.exists(CORE):
        return set()
    return set(CORE_ID_RE.findall(_read(CORE)))


def parse_findings(items):
    """把 --findings 的每项「定位|关键词|★数[|规则ID][/备选…]」解析为 dict。"""
    out = []
    for raw in items:
        for seg in re.split(r"[;；]", raw):
            seg = seg.strip()
            if not seg:
                continue
            parts = [x.strip() for x in seg.split("|")]
            if len(parts) < 2:
                raise ValueError("--findings 每项须为「条款定位|风险点|★数」，收到：%s" % seg)
            lvl = 0
            if len(parts) > 2:
                m = re.search(r"(\d)", parts[2])
                if m:
                    lvl = int(m.group(1))
            rid = parts[3] if len(parts) > 3 else ""
            alt = []
            if "/" in rid:
                rid, alt_raw = rid.split("/", 1)
                alt = [x.strip() for x in alt_raw.split("/") if x.strip()]
            out.append({"locate": parts[0], "issue": parts[1], "level": lvl,
                        "rule": rid.strip(), "alt": alt})
    return out


def locs_of(f):
    """一项预期的全部可接受定位：主定位 ＋ 备选定位。"""
    out = [f.get("locate") or ""]
    out += [x for x in (f.get("alt") or []) if x]
    return [x for x in out if x]


def verify(data=None):
    """校验台账自身：结构、样例路径、规则 ID 是否存在、评级范围。返回问题列表。"""
    data = data if data is not None else load()
    problems = []
    if not data:
        return ["台账不存在或解析失败：%s" % LEDGER]
    ids = core_ids()
    for c in data.get("cases") or []:
        cid = c.get("id") or "?"
        sp = c.get("sample") or ""
        if not sp:
            problems.append("%s：缺 sample 路径" % cid)
        elif not os.path.exists(os.path.join(ROOT, sp)):
            problems.append("%s：样例文件不存在 %s" % (cid, sp))
        if c.get("status") not in ("draft", "confirmed"):
            problems.append("%s：status 须为 draft 或 confirmed（现为 %r）" % (cid, c.get("status")))
        fs = c.get("expect") or {}
        for f in fs.get("findings") or []:
            if not f.get("locate"):
                problems.append("%s：预期项缺 locate" % cid)
            lv = f.get("level")
            if lv not in (1, 2, 3):
                problems.append("%s：预期项 %s 的 level 须为 1/2/3（现为 %r）"
                                % (cid, f.get("locate"), lv))
            rid = (f.get("rule") or "").strip()
            if rid and ids and rid not in ids:
                problems.append("%s：预期项写了规则 ID %s，但 core/01 中不存在" % (cid, rid))
        for rid in (fs.get("must_not") or []):
            if ids and rid not in ids:
                problems.append("%s：must_not 中的规则 ID %s 在 core/01 中不存在" % (cid, rid))
        # 定位冲突：不同预期项之间，任一候选定位互为子串 ⇒ 比对时互相抢，必出假漏报
        cands = []
        for f in fs.get("findings") or []:
            cands.append((f.get("locate") or "", locs_of(f)))
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                for x in cands[i][1]:
                    for y in cands[j][1]:
                        if x and y and (x in y or y in x):
                            problems.append(
                                "%s：两项预期的定位「%s」与「%s」互为子串，配对时会互相抢，"
                                "须改成互不包含的写法（或并入同一项）" % (cid, x, y))
    return problems


def parse_report(path):
    """从审查意见报告抽出 [(定位, ★数, 标题原文)] 与出现的规则 ID。"""
    txt = _read(path)
    items = []
    for m in RE_HEAD.finditer(txt):
        items.append({"locate": m.group(1).strip(), "level": len(m.group(2)),
                      "raw": m.group(0).strip()})
    rules = set()
    for m in RE_RULE.finditer(txt):
        rules.add(m.group(1) or m.group(2))
    return items, rules


def match(exp, act):
    """预期项与实际报告项配对：主定位或任一备选定位与实际定位互为子串即算命中。"""
    used, pairs = set(), []
    for e in exp:
        hit = -1
        cands = locs_of(e)
        for i, a in enumerate(act):
            if i in used:
                continue
            al = a["locate"]
            if al and any(c and (c in al or al in c) for c in cands):
                hit = i
                break
        if hit < 0:
            pairs.append({"exp": e, "act": None})
        else:
            used.add(hit)
            pairs.append({"exp": e, "act": act[hit]})
    extra = [a for i, a in enumerate(act) if i not in used]
    return pairs, extra


def check(paths, only=None):
    """拿报告与台账比对。返回 (结果列表, 失败数)。

    报告与用例的配对：报告文件名含样例文件名主干（如 `…_合同比对A版_审查意见报告_….md`）
    即算该用例的专属报告；配不到就用全部报告比对并提示——因为一个目录里常混着多份
    不同文档的报告，不配对会把 A 合同的结论拿去比对 B 合同的预期，全是假漏报。
    """
    data = load()
    if not data:
        return [], 0
    files = []
    for p in paths:
        if os.path.isdir(p):
            for r, _d, fs in os.walk(p):
                for f in fs:
                    if f.lower().endswith((".md", ".txt")):
                        files.append(os.path.join(r, f))
        elif os.path.exists(p):
            files.append(p)
    if not files:
        print("[sample-baseline] 未找到报告文件：%s" % ",".join(paths))
        return [], 0

    per = []  # [(文件, [条目], {规则ID})]
    for f in files:
        a, r = parse_report(f)
        per.append((f, a, r))
    all_act = [x for _f, a, _r in per for x in a]
    all_rules = set()
    for _f, _a, r in per:
        all_rules |= r

    results, fails = [], 0
    for c in data.get("cases") or []:
        cid = c.get("id")
        if only and cid != only:
            continue
        st = c.get("status", "draft")
        exp = (c.get("expect") or {}).get("findings") or []
        if not exp:
            continue
        stem = os.path.splitext(os.path.basename(c.get("sample") or ""))[0]
        owned = [x for f, a, _r in per if stem and stem in os.path.basename(f) for x in a]
        used_act = owned if owned else all_act
        rules = set()
        for f, _a, r in per:
            if (owned and stem and stem in os.path.basename(f)) or not owned:
                rules |= r
        pairs, _extra = match(exp, used_act)
        miss = [p["exp"] for p in pairs if p["act"] is None]
        drift = [p for p in pairs
                 if p["act"] and p["exp"].get("level") and p["act"]["level"] != p["exp"]["level"]]
        must_not = (c.get("expect") or {}).get("must_not") or []
        wrong = sorted(r for r in must_not if r in rules)
        bad = len(miss) + len(drift) + len(wrong)
        if st == "confirmed" and bad:
            fails += bad
        results.append({"id": cid, "status": st, "sample": c.get("sample"),
                        "expected": len(exp), "actual": len(used_act),
                        "matched_report": bool(owned),
                        "missing": miss, "drift": drift, "must_not_hit": wrong,
                        "counted": st == "confirmed"})
    return results, fails


def main():
    ap = argparse.ArgumentParser(description="样例级人工基线：台账 / 比对 / 校验")
    ap.add_argument("--list", action="store_true", help="列出台账")
    ap.add_argument("--check", nargs="*", metavar="路径", help="报告文件或目录")
    ap.add_argument("--case", help="只比对指定用例 ID（配合 --check）")
    ap.add_argument("--verify", action="store_true", help="只校验台账自身")
    ap.add_argument("--record", action="store_true", help="写入/覆盖一个用例")
    ap.add_argument("--id", help="用例 ID（如 S1）")
    ap.add_argument("--sample", help="样例文档相对路径")
    ap.add_argument("--nature", default="", help="文件性质（合同类/非合同类/混合型）")
    ap.add_argument("--industry", default="", help="行业 slug（可空）")
    ap.add_argument("--findings", nargs="*", default=[], help="「定位|风险点|★数[|规则ID]」")
    ap.add_argument("--must-not", nargs="*", default=[], help="不得报出的规则 ID")
    ap.add_argument("--status", choices=["draft", "confirmed"], default="draft")
    ap.add_argument("--by", default="", help="登记人")
    ap.add_argument("--note", default="", help="备注")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()

    if a.record:
        if not a.id or not a.sample:
            print("[sample-baseline] --record 须同时给 --id 与 --sample")
            return 2
        try:
            findings = parse_findings(a.findings)
        except ValueError as e:
            print("[sample-baseline] %s" % e)
            return 2
        data = load() or {"_说明": "", "cases": []}
        case = {"id": a.id, "sample": a.sample, "nature": a.nature, "industry": a.industry,
                "expect": {"findings": findings, "must_not": list(a.must_not)},
                "status": a.status, "confirmed_by": a.by,
                "confirmed_at": datetime.date.today().isoformat(), "note": a.note}
        cases = data.get("cases") or []
        cases = [c for c in cases if c.get("id") != a.id]
        cases.append(case)
        cases.sort(key=lambda c: c.get("id", ""))
        data["cases"] = cases
        data["_说明"] = ("样例级人工基线（sample-baseline.py 维护）。审查结论由模型作出，"
                        "预期风险项须人工（或人驱动模型）填写；本台账负责存得住、比得动。"
                        "status＝draft 只提示、confirmed 计入失败。用法见脚本 --help。")
        data["generated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LEDGER, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("[sample-baseline] 已登记 %s（%s，%d 项预期，status=%s）→ %s"
              % (a.id, a.sample, len(findings), a.status, LEDGER))
        return 0

    if a.verify:
        ps = verify()
        if a.json:
            print(json.dumps({"ok": not ps, "problems": ps}, ensure_ascii=False, indent=2))
        elif ps:
            print("[sample-baseline] 台账有问题 %d 处：" % len(ps))
            for p in ps:
                print("    - %s" % p)
        else:
            print("[sample-baseline] 台账校验通过（%d 个用例）"
                  % len((load() or {}).get("cases") or []))
        return 1 if ps else 0

    data = load()
    if not data:
        print("[sample-baseline] 尚无台账。先用 --record 登记，或手动编辑 %s" % LEDGER)
        return 1

    if a.list:
        if a.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        print("[sample-baseline] 台账 %s（%s）　用例 %d 个"
              % (LEDGER, data.get("generated", "?"), len(data.get("cases") or [])))
        for c in data.get("cases") or []:
            exp = (c.get("expect") or {}).get("findings") or []
            print("  %s [%s] %s　%s" % (c.get("id"), c.get("status"), c.get("sample"),
                                        c.get("nature") or ""))
            for f in exp:
                rid = ("（%s）" % f["rule"]) if f.get("rule") else ""
                alt = "".join(f.get("alt") or [])
                if alt:
                    rid += "　备选定位：" + "、".join(f.get("alt") or [])
                print("      预期：%s ｜ %s ｜ ★%d %s"
                      % (f.get("locate"), f.get("issue"), f.get("level", 0), rid))
            if (c.get("expect") or {}).get("must_not"):
                print("      不得报出：%s" % ",".join((c.get("expect") or {}).get("must_not")))
            if c.get("note"):
                print("      备注：%s" % c["note"])
        return 0

    if a.check is not None:
        if not a.check:
            print("[sample-baseline] --check 须给报告文件或目录")
            return 2
        res, fails = check(a.check, only=a.case)
        if not res:
            print("[sample-baseline] 没有可比的用例（用例为空或 --case 未命中）")
            return 0
        if a.json:
            print(json.dumps({"cases": res, "fails": fails}, ensure_ascii=False, indent=2))
            return 1 if fails else 0
        print("[sample-baseline] 比对 %d 个用例（confirmed 计入失败，draft 仅提示）："
              % len(res))
        for r in res:
            flag = "FAIL" if (r["counted"] and (r["missing"] or r["drift"] or r["must_not_hit"])) \
                else ("注意" if (r["missing"] or r["drift"]) else "OK")
            print("  [%s] %s %s（预期 %d 项 / 报告 %d 项%s）"
                  % (flag, r["id"], os.path.basename(r["sample"] or ""),
                     r["expected"], r["actual"],
                     "" if r["matched_report"] else "，未匹配到专属报告·按全部报告比"))
            for m in r["missing"]:
                print("      漏报：%s ｜ %s" % (m.get("locate"), m.get("issue")))
            for dd in r["drift"]:
                print("      评级漂移：%s 预期 ★%d，实际 ★%d"
                      % (dd["exp"].get("locate"), dd["exp"].get("level", 0), dd["act"]["level"]))
            for w in r["must_not_hit"]:
                print("      不应报出的规则被报出：%s" % w)
        print("[sample-baseline] 失败项 %d（未确认的 draft 用例不计）" % fails)
        return 1 if fails else 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    _sys.exit(main())
