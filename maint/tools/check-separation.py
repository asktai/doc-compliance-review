#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发侧／技能侧分离守卫（铁律 §9）。

**为什么要有它**：分离此前只有"机制"（`pack.py` 的白名单／排除表），没有"守卫"——
机制写错、或有人往技能目录塞东西，出包五项自检照样"全过"，`check.py` 也零反应。
东西明明躺在技能目录里（看起来合法、会被镜像同步到运行实例），却没人告诉你不该在那。
本守卫把这层补上（铁律 16.1：能固化的就做成守卫）。

**管三件事**：

  (1) 白名单目录防混入。`pack.py` 的 `FULL_DIRS`（core／industries／scripts／assets）
      是**整体递归打包**的——往里塞一份"AI 参考资料""测试数据"会被**照单全收且无声**。
      故：这些目录内出现**未登记**的条目即报错。
  (2) 素材准入核验（铁律 §9.4 准入制）。技能目录 `samples/` 属"必须随包的测试素材"，
      **默认拒绝随包**：须在开发侧准入清单 `maint/samples-manifest.json` 逐条登记
      「许可随包 ＋ 理由」。未登记 → 报错；已登记但文件缺失 → 报错；
      sha256 不符（文件被换过）→ 报错。
  (3) 开发资料越界检查。AI 学习参考、临时测试数据、出题素材三类**不得出现在技能目录**，
      一律放 `maint/ai-notes/`、`maint/test-data/`、`maint/scratch/`（铁律第 9.5 条）。

用法：
  python3 maint/tools/check-separation.py            # 查（默认，报错退码 1）
  python3 maint/tools/check-separation.py --seal     # 把实测 sha256 回填准入清单
  python3 maint/tools/check-separation.py -v         # 连带打印已登记的条目

退出码：0＝通过；1＝有违规（未登记条目／清单不符／越界资料）。
"""

import os
import sys
import json
import ast
import copy
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
DEV = os.path.dirname(os.path.dirname(HERE))                 # /workspace/dev
SKILL = os.path.join(DEV, "doc-compliance-review")
MANIFEST = os.path.join(DEV, "maint", "samples-manifest.json")
PACK = os.path.join(SKILL, "scripts", "pack.py")

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
SEAL = "--seal" in sys.argv

ERRS, WARNS, INFOS = [], [], []


def err(m):
    ERRS.append(m)


def warn(m):
    WARNS.append(m)


def info(m):
    INFOS.append(m)


def digest(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ────────────────── 从 pack.py 读真源，避免两处硬编码漂移 ──────────────────
# **不复制常量**：FULL_FILES／FULL_DIRS／EXCLUDE_* 的真源在 pack.py，
# 本守卫读取它——若守卫另写一份，改了 pack.py 忘记同步守卫，就又是漂移源（铁律 12.3）。
#
# **也不维护"要读哪些常量"的手写名单**（2026-11-11 根治）：
# 早期本函数带一份 `want = {...}` 白名单，只收名单里的 7 个常量名。于是 pack.py
# 每新增一个 XXX_DIR（本次是 TPL_DIR），名单漏补一次，FULL_DIRS 里的名字就代入不了
# → 整条解析失败 → 第 (1) 项形同虚设。那份手写名单本身就是第二处真源，是漂移的根。
# 现改为：**自动收 pack.py 全部模块级赋值**（不筛选名字）→ 先收能字面量求值的进
# 解析环境 → 再把含名字引用的常量代入环境求值。pack.py 以后无论加多少常量，
# 守卫都自动认识，无需同步、永不漂移。
# 历史教训仍在（DEVLOG 2026-10-14 Bug1）：解析失败**必须报错**，绝不 `except: pass`
# 静默降级——那会让守卫表现为"永远绿"，比没有守卫更危险。

# 第 (1) 项真正会用到的常量。前两个缺了＝整项没查，必须报错；
# 后两个缺了＝少排除开发资料，可能误报，给警告。除此之外不设任何名单。
_MUST = ("FULL_DIRS", "FULL_FILES")
_SHOULD = ("EXCLUDE_DIRS", "EXCLUDE_FILES")


class _InlineNames(ast.NodeTransformer):
    """把表达式里的 Name 换成它字面量值的 Constant，再交给 literal_eval 求值。

    只负责"名字 → 值"这一步；列表／集合／字典／字符串拼接等语义一概交给 Python
    自己的 literal_eval，不自己重写表达式求值（少一处可漂移的实现）。遇到环境里
    没有的名字，记进 unresolved，由调用方显式报错，绝不静默。
    """

    def __init__(self, env):
        self.env = env
        self.unresolved = []

    def visit_Name(self, node):
        if node.id in self.env:
            return ast.copy_location(ast.Constant(value=self.env[node.id]), node)
        self.unresolved.append(node.id)
        return node


def read_pack_consts(pack_path=None):
    """读 pack.py 全部模块级常量（含名字引用代入），返回 {名: 值}。

    pack_path 可选：默认读正式 pack.py；传副本路径供冒烟验证"新增常量自动解析"
    （铁律 16.2 副本操作，不碰正式文件）。
    """
    src = open(pack_path or PACK, encoding="utf-8").read()
    tree = ast.parse(src)
    # 第一遍：收全部模块级赋值，能直接字面量求值的进解析环境 env
    env, assigns = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigns[t.id] = node.value
                    try:
                        env[t.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
    # 第二遍：对含名字引用的常量，代入 env 后再求值（FULL_DIRS 走这里）
    got = dict(env)
    unresolved = []
    for name, node in assigns.items():
        if name in got:
            continue
        inl = _InlineNames(env)
        val_node = inl.visit(copy.deepcopy(node))
        ast.fix_missing_locations(val_node)
        if inl.unresolved:
            # 只诊断守卫真正要用的常量。INTEGRITY_REL=os.path.join(...)、
            # STEM_RE=re.compile(...) 里的 os／re 是模块名，属设计内跳过的非字面量
            # 表达式，不该混进"未解析引用"里稀释报错（否则点不准到底哪个名字没定义）。
            if name in _MUST or name in _SHOULD:
                unresolved.append("%s→%s" % (name, "/".join(sorted(set(inl.unresolved)))))
            continue
        try:
            got[name] = ast.literal_eval(val_node)
        except Exception:
            # os.path.join(...)、re.compile(...) 等非字面量表达式：守卫本就不用，
            # 跳过即可（pack.py 自己会正常执行它们）。
            pass

    # 命脉常量：缺了第 (1) 项等于没查，必须报错，并点名是哪几个引用没定义
    hint = ("；未解析的名字引用：%s" % "，".join(unresolved)) if unresolved else ""
    for key in _MUST:
        if key not in got:
            err("无法从 pack.py 解析 %s（第 (1) 项白名单防混入将形同虚设）"
                "——请检查 pack.py 的写法%s" % (key, hint))
    for key in _SHOULD:
        if key not in got:
            warn("%s 未能解析（按空集处理，可能少排除开发资料）" % key)
    return got


# ────────────────── (1) 白名单目录防混入 ──────────────────

def check_whitelist_dirs(c):
    """`FULL_DIRS` 内的条目须「在包内应存在」——即不是明显的开发资料。

    判据不靠"猜内容"，靠**名字形态 ＋ 排除表**：
      · 名字以 `_` 开头且不是已知随包的 `_*.json` 台账 → 可疑（本机临时物常用 `_` 前缀）
      · 名字含开发资料特征词（参考／学习／素材／草稿／备份／tmp／测试数据…）→ 报错
      · `EXCLUDE_*` 里登记过的 → 已在 pack.py 排除，提示而非报错
    这样既不误伤（不猜语义），又能拦住"往白名单目录塞资料"这一实际风险。
    """
    dirs = c.get("FULL_DIRS") or []
    ex_dirs = set(c.get("EXCLUDE_DIRS") or [])
    ex_files = set(c.get("EXCLUDE_FILES") or [])

    # 开发资料特征词（命中即报——这些词出现在随包目录里，几乎必是误放）
    SUSPECT = ("参考", "学习", "AI对话", "对话记录", "草稿", "备份", "临时",
               "测试数据", "出题", "素材", "笔记", "notes", "draft", "bak", "tmp")

    for d in dirs:
        base = os.path.join(SKILL, d)
        if not os.path.isdir(base):
            continue
        for root, subdirs, files in os.walk(base):
            subdirs[:] = [x for x in subdirs
                          if x not in {"__pycache__"} and x not in ex_dirs]
            for f in sorted(files):
                if f in ex_files or f.endswith(".pyc"):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, SKILL)
                hit = next((w for w in SUSPECT if w in f), None)
                if hit:
                    err("随包目录内出现疑似开发资料：%s（命中「%s」）——"
                        "请移到 maint/ai-notes、maint/test-data 或 maint/scratch" % (rel, hit))
                elif f.startswith("_") and not f.endswith(".json"):
                    warn("随包目录内有下划线开头文件：%s —— 确认是有意随包（台账类），"
                         "否则请移出技能目录" % rel)


# ────────────────── (2) 素材准入核验 ──────────────────

def load_manifest():
    if not os.path.exists(MANIFEST):
        err("未找到素材准入清单：%s" % MANIFEST)
        return None
    try:
        return json.load(open(MANIFEST, encoding="utf-8"))
    except Exception as e:
        err("准入清单 JSON 解析失败：%s" % e)
        return None


def check_admission(man, seal=False):
    """准入核验：册上有的包内须有、包内有的册上须有、sha256 须符。"""
    if man is None:
        return
    d = man.get("directory") or ""
    base = os.path.join(DEV, d)
    if not os.path.isdir(base):
        err("准入清单指向的目录不存在：%s" % d)
        return

    reg = {e["file"]: e for e in (man.get("entries") or [])}
    actual = {f for f in os.listdir(base)
              if os.path.isfile(os.path.join(base, f))}

    # 册上有、包内无 → 使用者会缺样本
    for fn in sorted(set(reg) - actual):
        err("准入清单登记了「%s」，但技能目录 samples/ 内没有此文件"
            "——使用者将缺该样本（冒烟相关项会 SKIP）" % fn)
    # 包内有、册上无 → 未许可即随包（准入制的核心：默认拒绝）
    for fn in sorted(actual - set(reg)):
        err("技能目录 samples/ 内有未登记素材「%s」——准入制为默认拒绝，"
            "须在 maint/samples-manifest.json 登记「许可随包 ＋ 理由」" % fn)

    # sha256 核对（被替换过的文件会在此暴露）
    changed = []
    for fn, e in sorted(reg.items()):
        p = os.path.join(base, fn)
        if not os.path.isfile(p):
            continue
        now = digest(p)
        old = (e.get("sha256") or "").strip()
        if seal:
            e["sha256"] = now
            continue
        if not old:
            warn("准入清单「%s」的 sha256 为空——请跑 --seal 回填" % fn)
        elif old != now:
            changed.append(fn)
    if seal:
        json.dump(man, open(MANIFEST, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        open(MANIFEST, "a", encoding="utf-8").write("\n")
        info("已回填 %d 条 sha256 至准入清单" % len(reg))
        return
    for fn in changed:
        err("准入素材「%s」的 sha256 与清单不符——文件已被替换／改动，"
            "确认无误后跑 --seal 更新（或查明是谁改的）" % fn)

    if not ERRS:
        info("素材准入核验通过：册上 %d 条与包内 %d 件一致，sha256 全符"
             % (len(reg), len(actual)))
        if VERBOSE:
            for fn, e in sorted(reg.items()):
                print("      · %s — %s" % (fn, (e.get("purpose") or "")[:52]))


# ────────────────── (3) 开发资料越界检查 ──────────────────

def check_dev_material_out_of_skill():
    """三类开发资料不得出现在技能目录（铁律第 9.5 条给的"家"在 maint/ 下）。"""
    HOMES = {
        "ai-notes": ("AI 对话记录", "学习参考", "与AI对话"),
        "test-data": ("测试数据", "临时测试"),
        "scratch": ("出题素材", "草稿"),
    }
    for d in ("ai-notes", "test-data", "scratch"):
        # 技能目录内若出现同名目录，几乎必是放错了位置
        p = os.path.join(SKILL, d)
        if os.path.isdir(p):
            err("技能目录内出现开发资料目录「%s」——应放 maint/%s/（铁律第 9.5 条）"
                % (d, d))
    # 技能目录内不得出现任何"开发侧资料"痕迹
    for root, dirs, files in os.walk(SKILL):
        dirs[:] = [x for x in dirs if x not in {"__pycache__"}]
        for f in files:
            if f.endswith((".pyc",)):
                continue
            for home, words in HOMES.items():
                if any(w in f for w in words):
                    rel = os.path.relpath(os.path.join(root, f), SKILL)
                    err("技能目录内出现开发资料：%s —— 应放 maint/%s/" % (rel, home))


# ────────────────── 主流程 ──────────────────

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    print("开发侧／技能侧分离守卫（铁律 §9）")
    print("=" * 62)

    if not os.path.isdir(SKILL):
        err("技能目录不存在：%s" % SKILL)
    elif not os.path.exists(PACK):
        err("未找到打包脚本（真源）：%s" % PACK)
    else:
        c = read_pack_consts()
        print("真源：%s（读到 %d 个常量）" % (os.path.relpath(PACK, DEV), len(c)))
        print()
        print("(1) 白名单目录防混入（FULL_DIRS 内不得放开发资料）")
        check_whitelist_dirs(c)
        print("(2) 素材准入核验（samples/ 默认拒绝，须逐条许可登记）")
        man = load_manifest()
        check_admission(man, seal=SEAL)
        print("(3) 开发资料越界检查（三类资料须在 maint/ 下的家）")
        check_dev_material_out_of_skill()

    for w in WARNS:
        print("  [W] %s" % w)
    for i in INFOS:
        print("  [i] %s" % i)
    print("=" * 62)
    if ERRS:
        print("结果：错误 %d 项，警告 %d 项 —— **未通过**" % (len(ERRS), len(WARNS)))
        for e in ERRS:
            print("  · %s" % e)
        return 1
    print("结果：无错误（警告 %d 项，提示 %d 项）—— 通过" % (len(WARNS), len(INFOS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
