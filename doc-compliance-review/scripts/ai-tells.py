#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  纯本地文本检测 → 绝对离线，不得引入任何网络库
"""
去AI味引擎 · ai-tells（v3.32.0 新增 · 第 20 号引擎）
===============================================================================
**检测一段文本有多少「机器套路」，并给出改写方向——但绝不代改、绝不打分。**

红线（SKILL.md 同一口径）
-------------------------------------------------------------------------------
机器只报**可数字面特征＋位置**，不报「像 AI 的程度」分数：
  · 分数给用户一个假客观——「AI 味 72 分」没有任何可验证依据，用户却会拿它做决策；
  · 列出哪一页哪一段有什么字面特征，用户自己判断，才是可核验的。
同理**不代改文本**：擅自改写对方合同文本是法律红线（改动即意思表示），
只给位置＋改写方向，由人定夺。

规则库
-------------------------------------------------------------------------------
真源＝`core/ai-tells.json`（机器可读）＋`core/03-ai-tells.md`（人读解释）。
五组 33 条：A 空洞套话（high）/ B AI 高频词汇（mid）/ C 模板化句式（mid）/
D 法律文书专用降智表达（high）/ X 格式特征（low）。组 ID 与风险库同构。

用法
-------------------------------------------------------------------------------
  python ai-tells.py <文本文件> [--json]      检测一个文件
  python ai-tells.py <文本文件> --context 400 检测（带上下文定位）
  （供 make-docx.py 等调用方 import：ai_tells_scan(text) → list[hit]）
"""
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）

import os
import re
import sys
import json
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(_HERE, "..", "core", "ai-tells.json")

# severity → 处置口径（不打分，只分级）
SEVERITY_LABEL = {"high": "高", "mid": "中", "low": "低"}
_VALID_SEVERITY = ("high", "mid", "low")


def load_rules():
    """读规则库真源；损坏即抛异常——静默返回空表会让检测变假绿。"""
    with open(RULES_PATH, encoding="utf-8") as f:
        d = json.load(f)
    groups = d.get("groups") or []
    for g in groups:
        if g.get("id") not in ("A", "B", "C", "D", "X"):
            raise ValueError("ai-tells.json 规则组 ID 越界：%r" % g.get("id"))
        if g.get("severity") not in _VALID_SEVERITY:
            raise ValueError("规则组 %s 的 severity 非法：%r" % (g.get("id"), g.get("severity")))
        for p in g.get("patterns", []):
            re.compile(p["pattern"])   # 编译不过＝规则写坏了，当场抛
    return groups


def ai_tells_scan(text, window=120):
    """扫描一段文本。返回命中列表，每项：

      {"group": "A", "group_name": "空洞套话", "severity": "high",
       "rule": "综上所述", "note": "总结式套话开头",
       "pos": 1234, "line": 12, "context": "……综上所述，双方应……"}

    window 为 context 前后各取的字符数（定位用，不影响命中判定）。
    """
    groups = load_rules()
    text = text or ""
    line_starts = [0]
    for m in re.finditer(r"\n", text):
        line_starts.append(m.end())
    hits = []
    for g in groups:
        for p in g.get("patterns", []):
            for m in re.finditer(p["pattern"], text):
                ln = sum(1 for s in line_starts if s <= m.start())
                ctx_l = max(0, m.start() - window)
                ctx_r = min(len(text), m.end() + window)
                hits.append({
                    "group": g["id"], "group_name": g.get("name", ""),
                    "severity": g.get("severity", "low"),
                    "rule": p["pattern"], "note": p.get("note", ""),
                    "pos": m.start(), "line": ln,
                    "context": text[ctx_l:ctx_r].replace("\n", "⏎"),
                })
    # 按位置排序（同一处的多组命中相邻），再按组内严重度稳定排序
    hits.sort(key=lambda h: (h["pos"], {"high": 0, "mid": 1, "low": 2}[h["severity"]]))
    return hits


def _fmt_report(text, hits):
    if not hits:
        return "未检出 AI 味特征（规则库 5 组 33 条，0 命中）。"
    by_sev = {}
    for h in hits:
        by_sev.setdefault(h["severity"], []).append(h)
    lines = ["检出 %d 处 AI 味特征（高 %d ／ 中 %d ／ 低 %d）：" % (
        len(hits), len(by_sev.get("high", [])),
        len(by_sev.get("mid", [])), len(by_sev.get("low", [])))]
    for h in hits:
        lines.append("  [第 %d 行] %s（%s｜%s 组）%s" % (
            h["line"], h["rule"] if len(h["rule"]) <= 24 else h["rule"][:24] + "…",
            SEVERITY_LABEL[h["severity"]], h["group"], h["note"]))
    lines.append("——以上为字面特征与位置，是否确属机器生成请人工判断；"
                 "本引擎不打分、不代改文本。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="去AI味检测（规则库驱动；只报字面特征＋位置，不打分不代改）")
    ap.add_argument("file", help="待检测的文本文件（.txt/.md）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（供调用方消费）")
    ap.add_argument("--max", type=int, default=200, help="最多显示的命中条数（默认 200）")
    a = ap.parse_args()
    try:
        text = open(a.file, encoding="utf-8-sig", errors="replace").read()
    except OSError as e:
        print("[ai-tells] 读文件失败：%s" % e, file=sys.stderr)
        return 2
    hits = ai_tells_scan(text)
    if a.json:
        print(json.dumps({"file": a.file, "total": len(hits), "hits": hits[:a.max]},
                         ensure_ascii=False, indent=2))
    else:
        print(_fmt_report(text, hits))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print("[ai-tells] 输入错误：%s" % e, file=sys.stderr)
        sys.exit(2)
