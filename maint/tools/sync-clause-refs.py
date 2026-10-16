#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨文件条号引用同步：铁律条号重排后，把散落在各文件里的引用一并搬过去。

**为什么需要它**（本工具的存在理由，即本轮事故的复盘）：
  铁律条号会因**插入新条／对调次序**而重排，重排脚本（`renumber-clauses.py` 等）
  只改 `DEV-RULES.md` **正文**。但铁律条号**被别处引用着**——
  `pack.py`／`check.py`／`publish.py`／各处 README 与计划文档里都有写死的
  "（铁律第 9.4 条）""铁律 19.3"这类标注。**正文一动，这些标注全部悬空**，
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
  `--apply`    重排**之后**跑：按映射把基准原文映射为新原文并落到各文件。

**映射怎么来**（**首选映射文件，不手抄**）：
  重排脚本跑完会**自动**写出映射文件 `maint/scratch/.last-clause-map.txt`
  （见 `maint/tools/clause_map.py`），这里用 `--map-file` 读它：
      python3 maint/tools/sync-clause-refs.py --apply --map-file maint/scratch/.last-clause-map.txt
  也支持手写 `--map 旧=新,旧=新`（应急用）。
  **为什么不让脚本自己猜**：条号映射依赖"插入了哪条、对调了哪两条"这一**重排意图**，
  从结果反推不出（且 `第 7 条` 可能指"条"也可能指别的）——**猜测即幻觉**（第 3 条）。
  故映射一律由**重排脚本自己声明**，本工具只做**忠实搬运**。

用法：
  python3 maint/tools/sync-clause-refs.py --capture
  python3 maint/tools/sync-clause-refs.py --apply --map-file maint/scratch/.last-clause-map.txt
  python3 maint/tools/sync-clause-refs.py --apply --map 7=9,7.4=9.4
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
# 日志／沿革类是**流水账**，记的是"当时如何"，不回改（改了就是篡改历史）。
# **CHANGELOG 与 DEVLOG 同理**——里面的旧条号是"当时的规定"，读者看到旧号
# 想的是"那会儿"而不是"现在"，**回改反而制造假历史**。
# （教训：首次实战把这层只用在 DEVLOG 上，CHANGELOG 的两处历史引用被一起搬了，
#   已回退并补进本集合。）
SKIP_FILES |= {"DEVLOG.md", "CHANGELOG.md"}
# **本工具自己**也要跳过：它的注释里带两类编号——① 用法的**举例**（"如 `铁律 19.3`"），
# ② 事故复盘的**史料**（"`铁律 15.2` 先 `→ 19.2`"）。①随便换个数都通，②则是
# **当时现场**，一改教训就假。两者都不该被业务重排搬动（**元层面的东西不跟业务走**）。
SKIP_FILES |= {os.path.basename(__file__)}
# `VERSION.md` 是**随包的沿革表**（一行一个已发布版本），性质同 CHANGELOG：
# 里面的条号属"那一版当时的规定"，**不回改**。当前版条目在写的时候就按新号写，
# 无需工具搬。
SKIP_FILES |= {"VERSION.md"}

# 引用形态：只认**带"铁律"前缀**的标注——这是"引铁律条号"的强信号，
# 避免误伤业务条号（如"《民法典》第585条""项目第 5.2 条"）。
#
# **只许一条 pattern**。曾经写成两条（第一条 `第? ?` 可选、第二条补"无前缀"形态），
# 结果第二条是第一条的**子集**：同一段文本被两条都匹配上，于是**被替换两次**——
# `铁律 15.2` 先 `→ 19.2`，紧接着 `19.2` 又被映射成 `16.2`，**双重映射**。
# 那一次的映射表里 `15.2=19.2` 与 `19.2=16.2` 恰好都存在，错得还很像对的。
# 教训：**替换类操作凡"多 pattern 叠加"必先证明互斥**，证不了就合并成一条。
#
# **并列段**（斜杠／顿号）：`铁律 19.2／18.2` 的后半段**没有前缀**，早先版本
# 直接漏掉——`18.2` 悬空。现在把并列段纳入**同一个 pattern**（同一条正则，
# 不新增第二条，免得又踩双重映射），用 `_PARA` 把"后缀数字"单独捕获，
# 在 `_translate` 里让它**继承前段的前缀**再映射一次。
# **只认纯数字形态**（`／18.2`、`/18.2.3`、`、18.2`）：斜杠后若跟着非数字
# （如 `／见第 3 条`），`_PARA` 不匹配，自然不吃——**宁漏不误**。
# 分隔符**前后都容忍空白**（`铁律 19.2 / 15.2` 与 `铁律 19.2/15.2` 都是常见写法；
# 实测 `check.py` 就有一处 `铁律 15.3 / 13.4.5` 因空格被漏掉）。
# 前侧只吃**半角空格**（`[ ]*`，不吃换行）——免得跨行"隔空"吞掉不相干的数字。
_SEP = r"[／/、]"                                            # 全角斜杠／半角斜杠／顿号
_PARA = r"(?:[ ]*%s\s*(\d+(?:\.\d+){0,3}))" % _SEP          # 并列段（可选，可多段）
PATTERNS = [
    # **必须一次抓满 1—4 级**，否则三级引用（`铁律 19.4.5`）会被"只抓二级"的
    # 正则改掉前缀、留下尾巴——**实测踩过**：`21.1.1` 因映射里只有 `21.1`，
    # 整个漏改；而 `13.4.5` 恰好凑成 `15.4.5`，是**巧合正确**，不可依赖。
    # `第? ?` 用可选：既认 `铁律第 9.4 条`，也认 `铁律 19.4.5`／`铁律 12.3.3`。
    r"铁律 ?第? ?(\d+(?:\.\d+){0,3})(%s*)" % _PARA,
]
_RE_PARALLEL = re.compile(_PARA)


def iter_files():
    for root, dirs, files in os.walk(DEV):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(SCAN_EXTS) or fn in SKIP_FILES:
                continue
            yield os.path.join(root, fn)


def _map_num(num, mapping):
    """把一个条号串按映射改写（**前缀最长匹配**）。

    `21.1.1` 若映射里有 `21.1.1` 用它，否则退到 `21.1`，再退到 `21`。
    这样三级引用改到的**映射不齐**时不会改半截——**要么整段搬对，要么整段不动**。
    无任何前缀命中则返回 None（调用方决定"原样保留"）。
    """
    parts = num.split(".")
    for cut in range(len(parts), 0, -1):
        old_num = ".".join(parts[:cut])
        if old_num in mapping:
            tail = ".".join(parts[cut:])               # 未被映射覆盖的尾巴
            return mapping[old_num] + (("." + tail) if tail else "")
    return None


def find_refs(text):
    """返回 [(整段匹配文本, 旧号字符串)]——旧号写成 `7`/`7.4`/`7.4.3` 形式。

    **只出"整段"**（`铁律 15.2／18.2` 记成**一条**，不拆成两半）。
    由来：曾把并列半段也单列进基准，结果 apply 时整段先替换（顺带把半段也改了），
    半段条目随后**必然未命中**——凭空多一条假告警。**整段替换已含并列段处理**，
    半段无需单独入表。（铁律：**同一件事只在一个地方做**。）
    """
    out = []
    for pat in PATTERNS:
        for m in re.finditer(pat, text):
            out.append((m.group(0), m.group(1)))
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

    只改数字、不动措辞，是为了不破坏作者的表述习惯。**并列段各改各的**
    （`铁律 19.2／18.2` 的前后两段分别过映射，因为它们指的是**不同条**）。
    并列段里的分隔符与空白**原样保留**（`_PARA` 的空白在捕获组外，
    替换时只在 `pm2.group(0)` 内部改数字）。
    """
    def _sub(mm):
        matched = mm.group(0)
        # ① 主条号（第 1 组）单独映射，只替换那一段
        old_num = mm.group(1)
        new = _map_num(old_num, mapping) if old_num else None
        if new:
            matched = matched.replace(old_num, new, 1)
        # ② 并列段（第 2 组，可能有多段）**各改各的**——它们指的是不同的条
        for pm2 in _RE_PARALLEL.finditer(mm.group(2) or ""):
            new2 = _map_num(pm2.group(1), mapping)
            if new2:
                matched = matched.replace(pm2.group(0),
                                          pm2.group(0).replace(pm2.group(1), new2, 1), 1)
        return matched

    text = old_ref
    for pat in PATTERNS:
        text = re.sub(pat, _sub, text)
    return text


def apply_map(map_arg, map_file=None, dry_run=False):
    mapping = {}
    if map_file:
        # 读重排脚本自动写出的映射文件（**首选**，机器传机器、不经人手）
        try:
            import clause_map
        except ImportError:
            sys.path.insert(0, HERE)
            import clause_map
        try:
            mapping.update(clause_map.parse_map_file(map_file))
        except (OSError, ValueError) as e:
            print("[E] 读映射文件失败：%s" % e)
            return 1
        print("[i] 已从映射文件读入 %d 条：%s" % (len(mapping), map_file))
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
        print("[E] 映射为空——请用 --map-file 或 --map 提供（见用法）")
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
    ap.add_argument("--map-file", dest="map_file", default="",
                    help="读重排脚本自动写出的映射文件（**首选**，免手抄）")
    ap.add_argument("--dry-run", action="store_true",
                    help="预演：只列出将改哪些，不落盘（**改前务必先跑一次**）")
    a = ap.parse_args()

    if a.capture and a.apply:
        print("[E] --capture 与 --apply 不可同时使用")
        return 1
    if a.capture:
        return capture()
    if a.apply:
        return apply_map(a.map_arg, map_file=a.map_file, dry_run=a.dry_run)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
