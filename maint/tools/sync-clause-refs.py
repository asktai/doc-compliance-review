#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨文件条号引用同步：铁律条号重排后，把散落在各文件里的引用一并搬过去。

**为什么需要它**（本工具的存在理由，即本轮事故的复盘）：
  铁律条号会因**插入新条／对调次序**而重排，重排脚本（`renumber-clauses.py` 等）
  只改 `DEV-RULES.md` **正文**。但铁律条号**被别处引用着**——
  `pack.py`／`check.py`／`publish.py`／各处 README 与计划文档里都有写死的
  "（铁律第 9.4 条）""铁律 15.3"这类标注。**正文一动，这些标注全部悬空**，
  而自检（第 (3) 维）**只查 DEV-RULES.md 内部**，根本看不见它们。

**事故实证**：2026-10-16 全库扫出 **25 处**悬空引用（含**随包**的 `pack.py`／`check.py`
与 `VERSION.md`——会发给使用者），最久的已漂了 4 个版本号。

**设计：基准化 ＋ 差量同步**（"能算出来的就不要手写"，铁律 12）
  - **基准（baseline）**：记下"某个已知干净状态下，各引用点的**原文**"。
    基准文件 `maint/tools/ref-baseline.json`。
  - **同步**：重排后，用**同一套映射**把基准里的原文映射成新原文，
    再去各文件里**按原文查找替换**——找不到即报错（说明该处已被手工改过，
    须人工核对，**不得静默跳过**）。

**两种用法**：
  `--capture`  重排**之前**跑：把当前各引用点原文记入基准（须先确认引用都是对的）；
  `--apply`    重排**之后**跑：按给定映射把基准原文映射为新原文并落到各文件。

**映射怎么来**：由调用者以 `--map 7=9,7.4=9.4,...` 显式给出（旧号=新号）。
**为什么不让它自己猜**：条号映射依赖"插入了哪条、对调了哪两条"这一**重排意图**，
脚本从结果反推不出意图（且 `第 7 条` 可能指"条"也可能指别的）——**猜测即幻觉**（第 3 条）。
故映射**必须由人明确给出**，脚本只做**忠实搬运**。

用法：
  python3 maint/tools/sync-clause-refs.py --capture
  python3 maint/tools/sync-clause-refs.py --apply --map 7=9,7.4=9.4,7.5=9.5,20=22
"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))          # dev/
BASELINE = os.path.join(HERE, "ref-baseline.json")

# 扫描范围：开发侧 + 随包侧（不含 DEV-RULES.md 自身——它是真源，不参与"引用搬运"）
SCAN_EXTS = (".py", ".md", ".sh", ".json", ".txt")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist"}
SKIP_FILES = {"DEV-RULES.md", "ref-baseline.json"}
# 日志类是**流水账**，记的是"当时如何"，不回改（改了就是篡改历史）
SKIP_FILES |= {"DEVLOG.md"}

# 引用形态：只认**带"铁律"前缀**的标注——这是"引铁律条号"的强信号，
# 避免误伤业务条号（如"《民法典》第585条""项目第 5.2 条"）。
PATTERNS = [
    # **必须一次抓满 1—3 级**，否则三级引用（`铁律 15.4.5`）会被"只抓二级"的
    # 正则改掉前缀、留下尾巴——**实测踩过**：`21.1.1` 因映射里只有 `21.1`，
    # 整个漏改；而 `13.4.5` 恰好凑成 `15.4.5`，是**巧合正确**，不可依赖。
    r"铁律 ?第? ?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?",   # 铁律第 9.4 条 / 铁律 15.4.5
    r"铁律 ?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?",             # 铁律 12.3.3
]


def iter_files():
    for root, dirs, files in os.walk(DEV):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(SCAN_EXTS) or fn in SKIP_FILES:
                continue
            yield os.path.join(root, fn)


def find_refs(text):
    """返回 [(整段匹配文本, 旧号字符串)]——旧号写成 `7`/`7.4`/`7.4.3` 形式。"""
    out = []
    for pat in PATTERNS:
        for m in re.finditer(pat, text):
            num = ".".join(g for g in m.groups() if g)
            out.append((m.group(0), num))
    return out


def capture():
    base = {}
    for path in iter_files():
        rel = os.path.relpath(path, DEV)
        try:
            text = io.open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        refs = find_refs(text)
        if refs:
            base[rel] = sorted({r[0] for r in refs})
    io.open(BASELINE, "w", encoding="utf-8").write(
        json.dumps(base, ensure_ascii=False, indent=2) + "\n")
    total = sum(len(v) for v in base.values())
    print("[OK] 基准已记录：%d 个文件、%d 条引用 → %s"
          % (len(base), total, os.path.relpath(BASELINE, DEV)))
    for rel, items in sorted(base.items()):
        print("     %-52s %d 条" % (rel, len(items)))
    return 0


def _translate(old_ref, mapping):
    """按映射改写一处引用的**文本**，保留原形态（"铁律第 X 条"仍作"铁律第 Y 条"）。

    **映射按"前缀最长匹配"生效**：`21.1.1` 若映射里有 `21.1.1` 用它，否则退到 `21.1`，
    再退到 `21`。这样三级引用改到的**映射不齐**时不会改半截——**要么整段搬对，要么整段不动**。
    只改数字、不动措辞，同样是为了不破坏作者的表述习惯。
    """
    def _sub(mm):
        groups = [g for g in mm.groups() if g]
        if not groups:
            return mm.group(0)
        # 前缀最长匹配：从最长路径往短退
        for cut in range(len(groups), 0, -1):
            old_num = ".".join(groups[:cut])
            if old_num in mapping:
                new_num = mapping[old_num]
                tail = ".".join(groups[cut:])          # 未被映射覆盖的尾巴
                repl = new_num + (("." + tail) if tail else "")
                return mm.group(0).replace(old_num, repl)
        return mm.group(0)                             # 无任何前缀命中：原样保留

    text = old_ref
    for pat in PATTERNS:
        text = re.sub(pat, _sub, text)
    return text


def apply_map(map_arg, dry_run=False):
    mapping = {}
    for pair in map_arg.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            print("[E] --map 项须形如 旧号=新号：%r" % pair)
            return 1
        a, b = pair.split("=", 1)
        mapping[a.strip()] = b.strip()
    if not mapping:
        print("[E] --map 为空")
        return 1

    if not os.path.exists(BASELINE):
        print("[E] 未找到基准文件 %s——请先在**干净状态**下跑 --capture"
              % os.path.relpath(BASELINE, DEV))
        return 1

    base = json.loads(io.open(BASELINE, encoding="utf-8").read())
    n_files, n_hits, miss = 0, 0, []
    preview = []

    for rel, refs in sorted(base.items()):
        path = os.path.join(DEV, rel)
        if not os.path.exists(path):
            miss.append((rel, "文件不存在"))
            continue
        text = io.open(path, encoding="utf-8").read()
        changed = False
        # **按引用长度降序处理**——否则短引用先替换会"吃掉"长引用的前缀：
        # 先把 `铁律 12.5` 换成 `铁律 12.5`，`铁律 12.5.1` 就变成 `铁律 12.5.1`
        # （结果虽对，但下一轮再找 `铁律 12.5.1` 必然落空 → **误报未命中**）。
        # 长引用先走，短引用后走，各归各位。
        for old_ref in sorted(refs, key=len, reverse=True):
            new_ref = _translate(old_ref, mapping)
            if new_ref == old_ref:
                continue
            if old_ref not in text:
                # **找不到即报错，不静默跳过**——该处可能已被手工改过，
                # 或基准过期，两种都必须人看一眼（第 3 条：不确定就问）
                miss.append((rel, old_ref))
                continue
            preview.append((rel, old_ref, new_ref))
            text = text.replace(old_ref, new_ref)
            n_hits += 1
            changed = True
        if changed and not dry_run:
            io.open(path, "w", encoding="utf-8").write(text)
            n_files += 1

    if dry_run:
        print("[DRY-RUN] 预演：将改写 %d 处引用（未落盘）：" % n_hits)
        for rel, old_ref, new_ref in preview:
            print("     %-48s %s  →  %s" % (rel, old_ref, new_ref))
    else:
        print("[OK] 同步完成：%d 个文件、%d 处引用已按映射改写" % (n_files, n_hits))

    if miss:
        print("[!] %d 处**未命中**（须人工核对，未作改动）：" % len(miss))
        for rel, ref in miss:
            print("     %s  ←  %s" % (rel, ref))
        return 2
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="跨文件条号引用同步（重排铁律条号后，搬运别处的引用）")
    ap.add_argument("--capture", action="store_true",
                    help="重排**前**跑：把当前引用记入基准")
    ap.add_argument("--apply", action="store_true",
                    help="重排**后**跑：按 --map 改写各文件引用")
    ap.add_argument("--map", dest="map_arg", default="",
                    help="旧号=新号，逗号分隔，如 7=9,7.4=9.4,20=22")
    ap.add_argument("--dry-run", action="store_true",
                    help="预演：只列出将改哪些，不落盘（**改前务必先跑一次**）")
    a = ap.parse_args()

    if a.capture and a.apply:
        print("[E] --capture 与 --apply 不可同时使用")
        return 1
    if a.capture:
        return capture()
    if a.apply:
        return apply_map(a.map_arg, dry_run=a.dry_run)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
