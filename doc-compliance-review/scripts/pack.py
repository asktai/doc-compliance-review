#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys
_sys.dont_write_bytecode = True
"""
文档合规审查助手AI合同审核全能版 · 发布包打包脚本（UTF-8 文件名）
===============================================================
用 Python zipfile 生成**唯一的发布 zip** —— 以开放平台（open.workbuddy.cn）的上架规范为准。

**只有一个包**：`doc-compliance-review-<版本>.zip`，解压后**第一层是技能目录**
`doc-compliance-review/`，进去才是 `SKILL.md`、`core/`、`scripts/`…。

    doc-compliance-review-V3.7.0.zip
      └─ doc-compliance-review/        ← 第一层即技能目录（平台要求，否则无法解析）
           ├─ SKILL.md               ← 每次会话都加载的主口径（刻意瘦身，只留常驻部分）
           ├─ permissions-and-libraries.md／drafting-guide.md／template-guide.md   ← 按需加载，命中入口才读
            ├─ README.md / 安装使用教程.md / LICENSE.md / VERSION.md
            ├─ 文档合规审查助手AI合同审核提示词版.md / SECURITY.md
            ├─ core/  industries/  scripts/（含 TONE.md）  assets/  samples/
           └─ …

一份源、一次打包、一个产物，不存在两处内容漂移的可能。纯提示词版也**不单独打包**，
它是包内的单个文件「文档合规审查助手AI合同审核提示词版.md」，复制粘贴即可用（少一个包就少一处不一致）。

**平台硬约束**：技能包内**至多两级目录**（`技能目录/二级目录/文件`）。
三级（如 `industries/<slug>/rules.md`）会被判「目录层级超限」直接拒收——故行业库平铺为
`industries/<slug>-rules.md`、自检样本直接放 `samples/` 顶层；`check.py` 与本脚本的出包
自检都会守住这条。

安全要点：
  **private/ 默认不打入发布包**。私有库是企业内控口径（审批流、风控底线、商业底线条款），
  一旦随发布包外泄即无法收回，故与 README「对外发布前务必剔除 private/」的要求保持一致：
  由脚本强制排除，而非依赖人工记得删。
  确需连同私有库一起打包（如企业内部留档）时，须显式加 --include-private，脚本会打印醒目警告，
  并在打包后复查包内是否混入 private/。

用法：
  python pack.py <技能根目录> [--out <发布包目录，默认 <根>/_发布包>]
                             [--include-private] [--tag <版本标签，默认读 SKILL.md>]
"""
import os, re, sys, zipfile, argparse

# SECURITY.md 必须随包：README 目录树、SKILL 第十二节、提示词版边界条款均指向它，
# 漏掉会变成「包内文档指向包外不存在的文件」。
# 注：`scripts/TONE.md`（感谢语参考）**不在此列**——scripts/ 由 FULL_DIRS 整体递归打包，
# 再列一次会写出同名重复条目（zipfile 会告警且条目数虚增）。它随 scripts/ 进包即达目的。
FULL_FILES = ["SKILL.md", "README.md", "安装使用教程.md", "LICENSE.md", "VERSION.md",
              "文档合规审查助手AI合同审核提示词版.md", "SECURITY.md",
              # 按需加载的三份专项口径：SKILL 里只留索引段，命中对应入口时才读这几份，
              # 以此压住 SKILL 的常驻体积。必须随包，否则索引指向包外不存在的文件。
              "permissions-and-libraries.md", "drafting-guide.md", "template-guide.md"]
# assets/ 必须随包（README/SKILL 顶部引用了头标，缺了就是裂图）；private/ 仍默认排除
# samples/ 下**只带顶层文件**（即自检样本）；samples/输出样例、公开范本、通用样例属
# 开发侧素材，一律不随包。
# **平台约束（V3.3.0 实测）**：开放平台解析技能包时只接受「根目录/二级目录/文件」两级，
# 三级（如 industries/<slug>/rules.md）直接报「目录层级超限」而拒收——故自检样本也**不再
# 放子目录**，行业库改平铺（industries/<slug>-rules.md），scripts/ 校验会守住这条。
# smoke-test 的「真实文件链路」与「比对链路」用它们验证 Word 提取、扫描型 PDF 与图片
# 合同的 OCR、真实敏感信息脱敏、以及 A/B 两版比对。
# 若使用者自行删掉这些样本（例如只留提示词版），smoke-test 相关项一律 SKIP 而非 FAIL。
SELFTEST_DIR = "samples"
FULL_DIRS = ["assets", "core", "industries", "scripts", SELFTEST_DIR]
NONREC_DIRS = {"samples"}   # 只带该目录下的文件，不递归其子目录（子目录为开发侧素材）
PRIVATE_DIR = "private"
EXCLUDE_DIRS = {"_归档", "_分发包", "_发布包", "测试合同", "__pycache__"}
EXCLUDE_FILES = {"regression-report-V2.0.0.md"}

# 技能目录名 —— 必须与 SKILL.md frontmatter 的 name 一致，平台据此识别技能；
# 上架版要求解压后第一层就是它。
SKILL_DIR = "doc-compliance-review"
# 平台上限（2026-09-20 实测口径）；超出会被拒收，故打包后自检会拦
PLATFORM_MAX_MB = 3
# 平台只解析两级（技能目录/二级目录/文件）
PLATFORM_MAX_DEPTH = 2

def add_tree(zf, base, relpath, recurse=True, prefix=""):
    src = os.path.join(base, relpath)
    for root, dirs, files in os.walk(src):
        if recurse:
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        else:
            dirs[:] = []   # 不进入子目录：非随包目录（如 samples/公开范本）不得混入
        for f in sorted(files):
            if f in EXCLUDE_FILES:
                continue
            if f.startswith("_") and f.endswith(".log.txt"):
                continue   # 本地测试日志（如 _testrb.log.txt）不得混入发布包
            fp = os.path.join(root, f)
            arc = os.path.relpath(fp, base).replace("\\", "/")
            zf.write(fp, prefix + arc if prefix else arc)

def verify_zip(zp):
    """出包自检：把上次被平台拒收的硬伤，做成**出包即拦**的守门（退码非 0 即视为打包失败）。

    校验项均来自开放平台的实测口径：
      1. 顶层只有技能目录一个条目（第一层须是 SKILL_DIR）→ 否则平台解析不到技能
      2. SKILL.md 恰 1 份且在技能目录下          → 多份或缺份都会 400
      3. 目录层级 ≤ 2（技能目录/二级目录/文件）    → 三级直接判「目录层级超限」拒收
      4. 体积 ≤ 3 MB                              → 平台上传上限
      5. private/ 未混入                          → 企业内控口径不得外泄
    """
    bad = []
    with zipfile.ZipFile(zp) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = sorted(set(n.split("/")[0] for n in names))
    if tops != [SKILL_DIR]:
        bad.append("顶层条目 %s —— 第一层须是技能目录 %s，且只有它" % (tops, SKILL_DIR))
    n_skill = sum(1 for n in names if n == SKILL_DIR + "/SKILL.md")
    if n_skill != 1:
        bad.append("SKILL.md 计数 %d（须恰为 1，且在技能目录下）" % n_skill)
    # 两级目录 ＝ 技能目录/二级目录/文件 ⇒ 相对 zip 根最多 2 个斜杠
    deep = sorted(set(n for n in names if n.count("/") > PLATFORM_MAX_DEPTH))
    if deep:
        bad.append("目录层级超限（>%d 级）共 %d 条，例如：%s"
                   % (PLATFORM_MAX_DEPTH, len(deep), deep[0]))
    mb = os.path.getsize(zp) / 1048576.0
    if mb > PLATFORM_MAX_MB:
        bad.append("体积 %.2f MB > 平台上限 %d MB" % (mb, PLATFORM_MAX_MB))
    leaked = [n for n in names if n.startswith(SKILL_DIR + "/" + PRIVATE_DIR + "/")]
    if leaked:
        bad.append("private/ 混入了 %d 个文件（企业内控口径，不得外发）" % len(leaked))
    return bad


def build(base, outdir, include_private=False, tag="V3.0.0"):
    os.makedirs(outdir, exist_ok=True)
    priv_path = os.path.join(base, PRIVATE_DIR)
    prefix = SKILL_DIR + "/"   # 上架版结构：所有条目都套一层技能目录
    for files, dirs, name in [
        (FULL_FILES, list(FULL_DIRS), f"{SKILL_DIR}-{tag}.zip"),
    ]:
        dirs = list(dirs)
        with_private = include_private and os.path.isdir(priv_path)
        if with_private:
            dirs.append(PRIVATE_DIR)
        zp = os.path.join(outdir, name)
        if os.path.exists(zp):
            os.remove(zp)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                fp = os.path.join(base, f)
                if os.path.exists(fp):
                    zf.write(fp, prefix + f)
            for d in dirs:
                if os.path.isdir(os.path.join(base, d)):
                    add_tree(zf, base, d, recurse=(d not in NONREC_DIRS), prefix=prefix)
        with zipfile.ZipFile(zp) as zf:
            entries = zf.namelist()
        n_entry = len([n for n in entries if not n.endswith("/")])
        print("built", zp, "entries", len(entries))
        print("  [i] 结构：第一层 %s/（上架版规范），共 %d 个文件条目" % (SKILL_DIR, n_entry))
        leaked_hit = [n for n in entries if n.startswith(SKILL_DIR + "/" + PRIVATE_DIR + "/")]
        if leaked_hit:
            print("  [警告] 本包内含 private/ 共 %d 个文件（企业内控口径）——请确认发布对象，勿对外发布！"
                  % len(leaked_hit))
        else:
            print("  [OK] 已排除 private/（企业内控口径未入包）")
        bad = verify_zip(zp)
        if bad:
            for b in bad:
                print("  [FAIL] " + b)
            print("  [x] 出包自检未通过：请勿发布，修正后重打。")
            return False
        print("  [OK] 出包自检通过：顶层／SKILL.md 计数／层级（≤%d 级）／体积（≤%d MB）／private 五项全过"
              % (PLATFORM_MAX_DEPTH, PLATFORM_MAX_MB))
    return True

def read_skill_version(base):
    """从 SKILL.md frontmatter 读取版本串作为发布包标签（同时也是 zip 文件名的一部分）。

    不用写死的默认值：否则版本升级后忘记传 --tag，会静默打出旧版本标签的包。
    """
    try:
        with open(os.path.join(base, "SKILL.md"), encoding="utf-8-sig") as f:
            # 注意：frontmatter 的 description 会随版本变长（曾出现 1200 字符读不到 version 行、
            # 静默退化成 V0.0.0 包的事故），故取足 4000 字符，并只从 frontmatter 段内匹配。
            head = f.read(4000)
        m = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", head)
        if m:
            v = m.group(1).strip()
            return v if v.upper().startswith("V") else "V" + v
    except OSError:
        pass
    return "V0.0.0"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="生成唯一的发布 zip（上架版结构：第一层为技能目录 %s）" % SKILL_DIR)
    ap.add_argument("base", help="技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="输出目录，默认 <根>/_发布包")
    ap.add_argument("--include-private", action="store_true",
                    help="将 private/ 一并打入包内（默认排除；内含企业内控口径，慎用）")
    ap.add_argument("--tag", default=None, help="版本标签（默认自动读 SKILL.md frontmatter）")
    a = ap.parse_args()
    if a.include_private:
        print("[警告] --include-private 已启用，private/（企业内控口径）将被打入发布包，"
              "请确认发布对象，勿对外发布。")
    ok = build(a.base, a.out or os.path.join(a.base, "_发布包"), a.include_private,
               a.tag or read_skill_version(a.base))
    sys.exit(0 if ok else 1)
