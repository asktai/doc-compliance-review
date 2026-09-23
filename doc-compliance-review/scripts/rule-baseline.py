#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则库回归基线（scripts/rule-baseline.py）
==========================================
用途：冒烟验的是"链路通不通"，验不出"规则改没改"。改一条规则（如调整违约金口径、
      给某条降级）不会让任何冒烟项变红，但审查结论会漂移。本脚本给规则库拍一张
      **基线快照**——通用库按条目记（规则 ID / 名称 / 评级★数 / 所属节），行业库按
      文件记（行数 / 节数 / sha256）——之后每次改动跑一次比对，把**新增、删除、评级变化、
      名称变化、文件内容变化**列出来交人工确认。这是"规则库长期可信"的地基。

用法：
    python rule-baseline.py              与基线比对（无变化退 0；有变化列清单并退 1）
    python rule-baseline.py --update     以当前规则库刷新基线（改动经人工确认后再执行）
    python rule-baseline.py --show       打印基线摘要（各文件规则数、评级分布、元数据、文件指纹）
    python rule-baseline.py --json       机器可读输出（差异清单 JSON）

覆盖三层：
    1. `core/01-general-risk-rules.md`（通用库，**条目级**：ID／名称／评级★数／所属节）
    2. `industries/<slug>-rules.md`（行业库，**文件级**：行数／节数／sha256——行业库是
       "增量要点＋引用 core 规则 ID"，没有自己的 ID 体系）
    3. **生效日与最近修订元数据**（`core/0*.md` 头部元数据行 ＋ `industries/<slug>-meta.md`
       的 `effective_date` / `last_revised` / `revision`）

**行业库为平铺结构**（`<slug>-rules.md` / `<slug>-meta.md`，V3.3.0 起）：平台解析技能包
只接受「根目录/二级目录/文件」两级，原来的 `industries/<slug>/rules.md` 是三级、会被拒收，
故行业库不再是子目录。

第3层除记录外还多守一道：**内容指纹变了、「最近修订」却没变** → 记为 `stale`（陈旧）
并告警。规则改了却不动「最近修订」，便无从判断这版从哪天起算、是否被改过——这正是
"生效日／最近修订"要防的事。

基线文件：`core/_rules-baseline.json`（随包，可读可改）。

**人工基线（样例级）**：审查结论由模型作出，脚本无法自动生成"预期风险项"。
样例级基线用 `scripts/sample-baseline.py` 维护（台账 `core/_sample-baseline.json`
＋ 比对器），用法见该脚本 `--help` 与 `04-交付报告\规则回归基线-V3.4.0.md` 第三节。
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import re
import json
import hashlib
import argparse
import datetime

try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 与 check.py 一致的通用库规则 ID 形态
CORE_ID_RE = re.compile(r"\|\s*([PVLGICDHEQWMNJSTF]\d+)\s*\|")
BASELINE = os.path.join(ROOT, "core", "_rules-baseline.json")


def _read(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _industry_slugs():
    """行业库 slug：由平铺文件 `industries/<slug>-rules.md` 反推（`_template` 除外）。"""
    ind = os.path.join(ROOT, "industries")
    if not os.path.isdir(ind):
        return []
    out = []
    for f in sorted(os.listdir(ind)):
        m = re.match(r"^([A-Za-z0-9_]+)-rules\.md$", f)
        if m and m.group(1) != "_template":
            out.append(m.group(1))
    return out


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def scan_rules(path):
    """通用库条目级扫描：[(id, 名称, 评级★数, 所属节)]。"""
    out, section = [], ""
    for line in _read(path).splitlines():
        if line.startswith("## "):
            section = line.lstrip("#").strip()
            continue
        if not line.strip().startswith("|"):
            continue
        m = CORE_ID_RE.search(line)
        if not m:
            continue
        cells = _cells(line)
        stars = len(re.findall(r"★", line))
        if not stars:
            lvl = re.search(r"(高风险|中风险|低风险)", line)
            stars = {"高风险": 3, "中风险": 2, "低风险": 1}.get(lvl.group(1), 0) if lvl else 0
        out.append({"id": m.group(1), "name": cells[1] if len(cells) > 1 else "",
                    "level": stars, "section": section})
    return out


def fingerprint(path):
    """行业库文件级指纹：行数 / 节数 / sha256。"""
    txt = _read(path)
    return {"lines": len(txt.splitlines()),
            "sections": len(re.findall(r"^## ", txt, re.M)),
            "sha256": hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]}


def sha16(path):
    return hashlib.sha256(_read(path).encode("utf-8")).hexdigest()[:16]


# ---- 生效日 / 最近修订元数据 ------------------------------------------------
RE_VER = re.compile(r"版本\s*\**\s*(V?\d+\.\d+\.\d+)")
RE_EFF = re.compile(r"生效日\s*\**\s*(\d{4}-\d{2}-\d{2})")
RE_REV = re.compile(r"最近修订\s*\**\s*(\d{4}-\d{2}-\d{2})")
RE_YAML = re.compile(r"^([a-z_]+):\s*(.+)$")


def scan_core_meta(path):
    """核心库头部元数据：版本 / 生效日 / 最近修订 / 内容 sha256。"""
    txt = _read(path)
    head = "\n".join(txt.splitlines()[:40])
    return {"version": (RE_VER.search(head).group(1) if RE_VER.search(head) else ""),
            "effective_date": (RE_EFF.search(head).group(1) if RE_EFF.search(head) else ""),
            "last_revised": (RE_REV.search(head).group(1) if RE_REV.search(head) else ""),
            "sha256": hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]}


def scan_meta_md(path):
    """行业 meta.md 的 YAML 元数据：生效日 / 最近修订 / 沿革末条。"""
    txt = _read(path)
    kv = {}
    for line in txt.splitlines():
        m = RE_YAML.match(line.strip())
        if m:
            kv[m.group(1)] = m.group(2).strip().strip('"')
    last = ""
    for line in txt.splitlines():
        if line.strip().startswith("- version:"):
            last = line.split(":", 1)[1].strip().strip('"')
    return {"version": kv.get("core_version", ""),
            "effective_date": kv.get("effective_date", ""),
            "last_revised": kv.get("last_revised", ""),
            "history_rows": len(re.findall(r"^\s*-\s*version:", txt, re.M)),
            "sha256": hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]}


def collect():
    """返回 (rules, files, meta, sha)。meta＝生效日/最近修订；sha＝核心库内容指纹。"""
    rules, files, meta, sha = {}, {}, {}, {}
    core = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if os.path.exists(core):
        rules["core/01-general-risk-rules.md"] = scan_rules(core)
    for name in ("01-general-risk-rules.md", "02-legal-verification-checklist.md"):
        p = os.path.join(ROOT, "core", name)
        if not os.path.exists(p):
            continue
        key = "core/" + name
        meta[key] = scan_core_meta(p)
        sha[key] = meta[key]["sha256"]
    ind = os.path.join(ROOT, "industries")
    if os.path.isdir(ind):
        for slug in _industry_slugs():
            rf = os.path.join(ind, "%s-rules.md" % slug)
            if os.path.exists(rf):
                files["industries/%s-rules.md" % slug] = fingerprint(rf)
            mf = os.path.join(ind, "%s-meta.md" % slug)
            if os.path.exists(mf):
                meta["industries/%s-meta.md" % slug] = scan_meta_md(mf)
    return rules, files, meta, sha


def diff(base, cur):
    """base/cur = (rules, files, meta[, sha])。返回差异字典。

    差异六类：added / removed / level / name / file / **meta**（生效日与最近修订）。
    meta 中含 `stale`：内容已变但「最近修订」未动 —— 改了规则却没同步修订日期。
    """
    br, bf = base[0], base[1]
    cr, cf = cur[0], cur[1]
    bm = base[2] if len(base) > 2 else {}
    cm = cur[2] if len(cur) > 2 else {}
    d = {"added": [], "removed": [], "level": [], "name": [], "file": [], "meta": []}
    for f in sorted(set(br) | set(cr)):
        b = {r["id"]: r for r in br.get(f, [])}
        c = {r["id"]: r for r in cr.get(f, [])}
        for rid in sorted(set(c) - set(b)):
            d["added"].append({"file": f, "id": rid, "name": c[rid]["name"], "level": c[rid]["level"]})
        for rid in sorted(set(b) - set(c)):
            d["removed"].append({"file": f, "id": rid, "name": b[rid]["name"], "level": b[rid]["level"]})
        for rid in sorted(set(b) & set(c)):
            if b[rid]["level"] != c[rid]["level"]:
                d["level"].append({"file": f, "id": rid, "name": c[rid]["name"],
                                   "from": b[rid]["level"], "to": c[rid]["level"]})
            if b[rid]["name"] != c[rid]["name"]:
                d["name"].append({"file": f, "id": rid, "from": b[rid]["name"], "to": c[rid]["name"]})
    for f in sorted(set(bf) | set(cf)):
        if f not in bf:
            d["file"].append({"file": f, "change": "新增文件", "detail": cf[f]})
        elif f not in cf:
            d["file"].append({"file": f, "change": "文件缺失", "detail": bf[f]})
        elif bf[f] != cf[f]:
            d["file"].append({"file": f, "change": "内容变化",
                              "detail": "%s → %s" % (bf[f], cf[f])})
    # ---- 生效日 / 最近修订 ----
    for f in sorted(set(bm) | set(cm)):
        b, c = bm.get(f), cm.get(f)
        if b is None:
            d["meta"].append({"file": f, "change": "新增元数据", "detail": c})
            continue
        if c is None:
            d["meta"].append({"file": f, "change": "元数据缺失", "detail": b})
            continue
        if b.get("sha256") != c.get("sha256"):
            if b.get("last_revised") == c.get("last_revised"):
                d["meta"].append({"file": f, "change": "stale（内容已变但未更新「最近修订」）",
                                  "detail": "last_revised 仍为 %s，请更新「最近修订」日期"
                                            % (c.get("last_revised") or "空")})
            else:
                d["meta"].append({"file": f, "change": "修订（已同步最近修订）",
                                  "detail": "last_revised %s → %s"
                                            % (b.get("last_revised") or "空",
                                               c.get("last_revised") or "空")})
        elif b.get("effective_date") != c.get("effective_date"):
            d["meta"].append({"file": f, "change": "生效日变化",
                              "detail": "%s → %s" % (b.get("effective_date") or "空",
                                                     c.get("effective_date") or "空")})
    return d


def main():
    ap = argparse.ArgumentParser(description="规则库回归基线：比对 / 刷新 / 查看")
    ap.add_argument("--update", action="store_true", help="以当前规则库刷新基线")
    ap.add_argument("--show", action="store_true", help="打印基线摘要")
    ap.add_argument("--json", action="store_true", help="机器可读输出（差异 JSON）")
    a = ap.parse_args()

    cr, cf, cm, _cs = collect()
    total = sum(len(v) for v in cr.values())

    if a.update:
        data = {"_说明": "规则库回归基线（rule-baseline.py 生成）。rules＝通用库条目（ID/名称/评级★数/所属节）；"
                        "files＝行业库文件指纹（行数/节数/sha256）；meta＝生效日与最近修订（版本/生效日/"
                        "最近修订/内容sha256）。改动后跑 python scripts/rule-baseline.py 比对，差异交人工确认后再 --update。",
                "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total": total, "rules": cr, "files": cf, "meta": cm}
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("[baseline] 已刷新基线：%s（通用库 %d 条，行业库 %d 个文件，元数据 %d 处）"
              % (BASELINE, total, len(cf), len(cm)))
        return 0

    if not os.path.exists(BASELINE):
        print("[baseline] 尚无基线，请先执行：python scripts/rule-baseline.py --update")
        return 1

    meta = json.load(open(BASELINE, encoding="utf-8"))
    base = (meta.get("rules") or {}, meta.get("files") or {}, meta.get("meta") or {})
    if a.show:
        print("[baseline] 生成时间：%s　通用库 %d 条　行业库 %d 个文件"
              % (meta.get("generated", "?"), meta.get("total", 0), len(base[1])))
        for f in sorted(base[0]):
            lv = {}
            for r in base[0][f]:
                lv[r["level"]] = lv.get(r["level"], 0) + 1
            print("    %-38s %3d 条　评级分布(★数:条数) %s" % (f, len(base[0][f]), lv))
        for f in sorted(base[1]):
            print("    %-38s 指纹 %s" % (f, base[1][f]))
        if base[2]:
            print("    ---- 生效日 / 最近修订 ----")
            for f in sorted(base[2]):
                m = base[2][f]
                hist = ("　沿革 %d 条" % m["history_rows"]) if m.get("history_rows") else ""
                print("    %-38s 版本 %-7s 生效日 %s　最近修订 %s%s"
                      % (f, m.get("version") or "?", m.get("effective_date") or "缺失",
                         m.get("last_revised") or "缺失", hist))
        else:
            print("    （基线无元数据层，请 --update 重建）")
        return 0

    d = diff(base, (cr, cf, cm))
    n = sum(len(v) for v in d.values())
    if a.json:
        print(json.dumps({"total": total, "baseline_total": meta.get("total"), "diff": d},
                         ensure_ascii=False, indent=2))
        return 1 if n else 0

    print("[baseline] 基线 %s：通用库 %d 条；当前 %d 条" % (meta.get("generated", "?"), meta.get("total", 0), total))
    if not n:
        print("[baseline] 无差异：规则条目（ID/名称/评级）与行业库文件指纹均与基线一致。")
        return 0
    print("[baseline] 检出 %d 处差异（**须人工确认是否预期内**）：" % n)
    for k, label in (("added", "新增规则"), ("removed", "删除规则"), ("level", "评级变化"),
                     ("name", "名称变化"), ("file", "行业库文件"), ("meta", "生效日与最近修订")):
        for it in d[k]:
            if k == "level":
                print("    [%s] %s %s %s：★%d → ★%d" % (label, it["file"], it["id"], it["name"][:22], it["from"], it["to"]))
            elif k == "name":
                print("    [%s] %s %s：%s → %s" % (label, it["file"], it["id"], it["from"][:22], it["to"][:22]))
            elif k in ("file", "meta"):
                print("    [%s] %s %s：%s" % (label, it["file"], it["change"], it["detail"]))
            else:
                print("    [%s] %s %s %s（★%d）" % (label, it["file"], it["id"], it["name"][:26], it["level"]))
    print("[baseline] 确认无误后执行：python scripts/rule-baseline.py --update")
    return 1


if __name__ == "__main__":
    _sys.exit(main())
