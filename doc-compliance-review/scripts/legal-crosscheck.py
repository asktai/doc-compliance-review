#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
"""条文一致性比对（交叉验证的核心算法）

为什么要它：法条库是「核验真值源」。真值源自己错了，核验会把错的判成对的，
比没有库更危险。单源抓取的文件一旦网页本身有错字、漏字、串行，谁都发现不了。
故同一部法须从 ≥2 个彼此独立的来源抓同一批条号，逐条正文比对：
  一致 → 该条可信（verified: true）
  不一致 → 不猜谁对，原文照存并标冲突（conflict 记录两版差异），交人工裁决
  只有一源 → 显式标 verified: false，绝不伪装成「已核」

比对口径（刻意的宽松）：
  只比「中文字＋数字」字串，剔除标点、空白、书名号、括号；
  用 4 字片段覆盖率衡量——同义转载页常有全半角、「的」字增删、
  「条/款」表述差异，这些不应判成冲突。阈值 0.985：
  允许极少量噪声，但漏一句（十几字）必然跌破。
"""

import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
import re

STRIP_RE = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]")


def norm(s):
    """归一：只留中文、字母、数字。"""
    return STRIP_RE.sub("", s or "")


def grams(s, n=4):
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


def compare(a, b):
    """返回 dict(ratio, len_a, len_b, diff)。

    ratio 取「双向 4 字片段覆盖」中的较小值——只要一版多出一段或漏掉一段，
    这个值就会明显下降，比单纯的长度比或单向覆盖率更敏感。
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return {"ratio": 0.0, "len_a": len(na), "len_b": len(nb), "diff": ""}
    if na == nb:
        return {"ratio": 1.0, "len_a": len(na), "len_b": len(nb), "diff": ""}
    ga, gb = grams(na), grams(nb)
    if not ga or not gb:
        return {"ratio": 0.0, "len_a": len(na), "len_b": len(nb), "diff": ""}
    inter = len(ga & gb)
    cov_a = inter / float(len(ga))
    cov_b = inter / float(len(gb))
    ratio = min(cov_a, cov_b)
    diff = "" if ratio >= 0.985 else _only_run(na, gb)
    return {"ratio": round(ratio, 4), "len_a": len(na), "len_b": len(nb), "diff": diff}


def _only_run(na, gb, n=4):
    """在 a 中找第一段「连续 4 字片段都不在 b 里」的原文（带少量上下文，便于人读）。"""
    run, best = [], []
    for i in range(max(0, len(na) - n + 1)):
        if na[i:i + n] in gb:
            run = []
        else:
            run.append(i)
            if len(run) > len(best):
                best = list(run)
    if len(best) < 2:
        return ""
    s, e = best[0], best[-1] + n
    return na[max(0, s - 6):min(len(na), e + 6)]


def verdict(results, threshold=0.985):
    """给一组同条号的比对结果下判决。

    results: [(源标识, 正文), ...]，至少一条。
    返回 dict(status, verified, ratio, conflict)
      status: "multi-ok" 多源一致 / "single" 单源未交叉 / "conflict" 多源冲突
    """
    results = [(s, t) for s, t in results if t]
    if not results:
        return {"status": "missing", "verified": False, "ratio": None, "conflict": None}
    if len(results) == 1:
        return {"status": "single", "verified": False, "ratio": None, "conflict": None}
    base_src, base = results[0]
    worst = None
    for src, txt in results[1:]:
        c = compare(base, txt)
        if worst is None or c["ratio"] < worst[0]["ratio"]:
            worst = (c, src, txt)
    c, src, txt = worst
    if c["ratio"] >= threshold:
        return {"status": "multi-ok", "verified": True, "ratio": c["ratio"], "conflict": None}
    gb, ga = grams(norm(txt)), grams(norm(base))
    return {
        "status": "conflict", "verified": False, "ratio": c["ratio"],
        "conflict": {
            "with": src,
            "ratio": c["ratio"],
            "len_base": c["len_a"],
            "len_other": c["len_b"],
            "only_base": _only_run(norm(base), gb),
            "only_other": _only_run(norm(txt), ga),
            "base_text": base[:400],
            "other_text": txt[:400],
        },
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        print(compare(sys.argv[1], sys.argv[2]))
