#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 DEV-RULES.md 中的编号错乱（".." 重复段）。

成因：swap-ch5-ch6.py 的 RE_NUM 正则第 3 组带前导点，与"重拼"叠加，产出
  `16.4..1.1` / `16.4..3.1.3.1` 这类编号——`..` 右侧是**真值重复两遍**。

修法：`A..R` → `A.R的真半段`。用确定性规则 + 逐一断言，避免误伤。

用法：
  python3 maint/scratch/fix-double-dot.py            # 预演（只打印）
  python3 maint/scratch/fix-double-dot.py --apply     # 落盘（先备份）
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.abspath(os.path.join(HERE, "..", ".."))
TARGET = os.path.join(DEV, "DEV-RULES.md")

# A..R，A 为 1—2 位数起点，R 为点分数字串
RE_DD = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)*)\.\.(\d+(?:\.\d+)*)(?![\d.])")


def true_tail(right: str):
    """`..` 右侧是"真值重复两遍"，返回真值；不是则返回 None（不猜）。"""
    rp = right.split(".")
    n = len(rp)
    if n % 2 != 0:
        return None
    half = n // 2
    if rp[:half] == rp[half:]:
        return ".".join(rp[:half])
    return None


def fix_one(left: str, right: str):
    tail = true_tail(right)
    if tail is None:
        return None
    return left + "." + tail


def main():
    apply = "--apply" in sys.argv
    txt = open(TARGET, encoding="utf-8").read()

    hits = []
    for m in RE_DD.finditer(txt):
        left, right = m.group(1), m.group(2)
        new = fix_one(left, right)
        hits.append((m.start(), m.end(), m.group(0), new))

    print("发现 %d 处 `..` 编号错乱" % len(hits))
    bad = [(o, t) for (_, _, o, t) in hits if t is None]
    if bad:
        print("!! 有 %d 处不符合「重复两遍」规律，**不自动改**，须人工判定：" % len(bad))
        for o, _ in bad:
            print("   ", o)
        return 1

    # 逐处打印
    for _, _, old, new in hits:
        print("  %-22s -> %s" % (old, new))

    # 组装结果（逆向替换，避免位移）
    out = txt
    for start, end, old, new in reversed(hits):
        out = out[:start] + new + out[end:]

    # 落盘前断言：结果里不得再出现 `..`
    resid = RE_DD.findall(out)
    if resid:
        print("!! 替换后仍残留 %d 处，中止" % len(resid))
        for a, b in resid[:10]:
            print("   ", a + ".." + b)
        return 1

    # 追加断言：每处新编号须形如 N.M（含更深层级），不得是裸数字或超长
    for _, _, old, new in hits:
        if not re.match(r"^\d{1,2}(?:\.\d+){1,3}$", new):
            print("!! 异常新编号：%s" % new)
            return 1

    if not apply:
        print("\n[预演] 未落盘（加 --apply 生效）")
        return 0

    bak = TARGET + ".bak-doubledot"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(out)
    print("\n[已落盘] %s（备份 %s）" % (TARGET, os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
