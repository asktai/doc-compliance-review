#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""圆圈编号 → 半角括号编号 批量转换（开发侧工具，不随包分发）。

规则（依铁律 §22 第 8 行「编号用可键入字符」）：
  (1) **按连续段落归并**：圆圈之间若只有普通换行，且中间行不以"新条目起始"
      （空行／`N. `／`## `／`- `／`|`／`> ` 等）开头，则归入**同一序列**递增；
      否则各自起算（避免跨条目错位）。
  (2) **并列前缀**：形如"XX①……XX②……"（圆桌前同有相同前缀文本）的，按同前缀
      连续编号，不因换行重置。
  (3) DEV-RULES.md 中的反例行**不转换**——那是纪律举的反例，现行落点 `§22 第 8 行`。
      此处保留旧号以存史：〔述史〕`第 20 条 第 8 行` 是 V1.29.1（`c63daa4`，本工具创建时）
      的表述纪律条号；v1.37.0（`39aad9d`）重排后改为第 22 条、案乙换号后为 §22，
      而「第 20 条」今已改指分发包命名，**勿按现行号索骥**。

用法：
  python3 convert-circles.py --dry     # 只打印对照表（默认）
  python3 convert-circles.py --apply   # 实际写盘
"""
import glob
import os
import re
import sys

CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))

TARGETS = []
for pat in ["doc-compliance-review/**/*.md", "doc-compliance-review/**/*.py",
            "maint/*.md", "maint/tools/*.py", "CHANGELOG.md", "publish.py"]:
    TARGETS += glob.glob(os.path.join(DEV, pat), recursive=True)
# 排除：缓存、本转换器自身、铁律（含反例行）
TARGETS = sorted({t for t in TARGETS
                  if "__pycache__" not in t
                  and not t.endswith("convert-circles.py")
                  and not t.endswith("DEV-RULES.md")
                  and not t.endswith("check-dev-rules.py")})

# 「新条目起始」判据：这些开头的行不与上一行共享序列
NEW_ITEM_RE = re.compile(r"^(?:\s*$|\s*\d+\.\s|\s*#{1,6}\s|\s*[-*]\s|\s*\||\s*>\s|\s*```)")


def is_item_start(line):
    return bool(NEW_ITEM_RE.match(line))


def prefix_before_circ(line, ch):
    """取该圆圈**之前**、去掉行首编号后的文本，作为"并列前缀"比较依据。"""
    i = line.index(ch)
    pre = line[:i]
    pre = re.sub(r"^\s*\d+\.\s*", "", pre)      # 去行首 "2. "
    pre = re.sub(r"^\s*[-*>]\s*", "", pre)      # 去行首列表符／引用符
    return pre.strip()


def convert(text):
    """返回 (新文本, [(行号, 旧行, 新行), ...])"""
    lines = text.split("\n")
    out = list(lines)
    log = []
    # 序列状态：seq = 当前序列已用个数；last_prefix = 上一圆圈行的前缀
    seq = 0
    prev_was_circ = False
    last_prefix = None
    for i, line in enumerate(lines):
        if not any(c in line for c in CIRC):
            # 非圆圈行：若为空行或新条目起始，则重置序列
            if is_item_start(line):
                seq = 0
                last_prefix = None
                prev_was_circ = False
            else:
                # 普通换行 → 保持序列延续
                prev_was_circ = False
            continue
        # 本行含圆圈
        if not prev_was_circ and seq == 0:
            # 检查是否与上一圆圈行构成"并列前缀"（同前缀，跨新条目）
            pass
        new_line = []
        n = seq
        # 行内的正则字符类区间 `[...]`：其中的圆圈是范围端点，不转换
        cls_spans = [(m.start(), m.end()) for m in re.finditer(r"\[[^\]\n]*\]", line)]
        for j, ch in enumerate(line):
            if ch in CIRC:
                # **反引号包裹的字面引用（如 `①`→`(1)` 说明文字）不改**
                prev_c = line[j - 1] if j > 0 else ""
                next_c = line[j + 1] if j + 1 < len(line) else ""
                if prev_c == "`" or next_c == "`":
                    new_line.append(ch)
                    continue
                # **正则字符类内（如 [①-⑩]）不改**：那是范围端点，改了正则即坏
                if any(a <= j < b for a, b in cls_spans):
                    new_line.append(ch)
                    continue
                pre = prefix_before_circ(line, ch)
                if seq > 0 and last_prefix is not None and pre == last_prefix:
                    n += 1                      # 并列前缀 → 继续递增
                elif seq > 0 and not is_item_start(line):
                    n += 1                      # 段落内延续
                else:
                    n = seq + 1                 # 新序列起算
                    seq = 0
                new_line.append("(%d)" % n)
                seq = n
                last_prefix = pre
            else:
                new_line.append(ch)
        new_line = "".join(new_line)
        out[i] = new_line
        log.append((i + 1, line, new_line))
        prev_was_circ = True
    return "\n".join(out), log


def main():
    apply = "--apply" in sys.argv
    total = 0
    for p in TARGETS:
        with open(p, encoding="utf-8") as f:
            s = f.read()
        if not any(c in s for c in CIRC):
            continue
        new, log = convert(s)
        # 剔除"新行==旧行"（未变）的记录
        log = [x for x in log if x[1] != x[2]]
        total += len(log)
        rel = os.path.relpath(p, DEV)
        print("=== %s（%d 行）===" % (rel, len(log)))
        for ln, a, b in log:
            print("  L%-5d 旧: %s" % (ln, a.strip()[:110]))
            print("         新: %s" % b.strip()[:110])
        if apply:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
    print("\n合计触发行：%d  %s" % (total, "(已写盘)" if apply else "(未写盘，加 --apply 落盘)"))


if __name__ == "__main__":
    main()
