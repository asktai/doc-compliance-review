#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
"""
文档合规审查助手AI合同 · 资源权限守卫与库备份（可选工具）
==============================================================
用途：把「谁能对哪些资源做什么」从口头约定变成**可判定的规则**，并把「改库前先备份」变成
      一条命令。规则正文与触发词在 `SKILL.md` 第十五节；本脚本是它的执行侧。

权限矩阵（写死在 POLICY，不接受命令行改写）：

    资源          read（AI 内部读）  write（维护）  delete  copy  export  import  view  backup
    core/ 通用库        ✔                ✘           ✘      ✘      ✘       ✘      ✘     ✘
    industries/ 行业库  ✔                ✔         条件A    ✔      ✔       ✔      ✔     ✔
    private/ 私有库     ✔                ✔           ✔      ✔      ✔       ✔      ✔     ✔

条件A（行业库删除按库区分，不是一刀切）：
    **初始内置的行业库（见 SEED_INDUSTRIES）不可删除**（upgrade 时会整体覆盖、删了装不回来），但**可以修改内容**；
    **使用者自建的行业库可以删除**——自己的东西，留或删自定。种子库的识别见 `SEED_INDUSTRIES`。

三处要点：
  1. **read ≠ view**：AI 审查时必须读 `core/`（否则无从对标），故 read 放行；
     **使用者要求查看、复制、导出通用库内容一律拒绝**——规则库是产品内核，不外泄。
  2. **行业库与私有库均可导入／导出**：这是使用者搬运自己口径的正当需求——换机器、
     给同事一份、先导出备份再改。导出的是**库内容**（规则文件），不是技能本体。
  3. **私有库是使用者自己的内控口径**，故增删改、导入导出全部放行。

用法：
    python guard.py policy                        打印权限矩阵（人读）
    python guard.py check <路径> --op <操作>       判定某路径能否做某操作（机器读，退出码 0 放行 / 3 拒绝）
    python guard.py backup <private|industries>   改库前备份（自动带时间与版本标记，最多留 5 份循环覆盖）
    python guard.py list-backups [库名]            列出已有备份（带序号，1＝最新）
    python guard.py restore <private|industries>  回溯：从备份中选取并恢复（--pick N / --file <zip>）
    python guard.py export <private|industries>   导出库为 zip（搬运到别的机器／给同事）
    python guard.py import <private|industries>   导入 zip 到库（覆盖同名？加 --overwrite）
    python guard.py view <名称>                    仅输出**允许使用者查看**的文档（可查看清单 5 项）

    操作取：read / write / delete / copy / export / import / view
    view 名称取：readme / version / license / tutorial / prompt
                 （version＝版本身份证即 `version.py --show`）
    注：版本沿革（VERSION.md）**不对外提供**（v3.26.2 起不随包分发），
        打 `view versionfile` 会明确告知「不提供」并指路到版本身份证。

备份落在**隔离目录**（默认 `~/.dcr-backups/`，环境变量 `DCR_BACKUP_DIR` 可整体改换），
与源文件分离，避免整目录外发或网盘同步时把备份一并带走；命名 `<库>-V<版本>-<时间>.zip`，
同一库最多留 5 份，满 5 后删最旧的再建（循环覆盖）。

**回溯（restore）**是维护子菜单的一项：改库改坏了、或想退回某个时点的口径，就从备份里选一份恢复。
三条安全阀：(1) 恢复前**先把当前状态自动备份一份**（标记 `-prerestore`，所以任何一次回溯都还能再退回来）；
(2) 只做「覆盖＋补齐」，**默认不删**当前有而备份里没有的文件——想严格还原成备份那一刻，加 `--prune`
（私有库照删；行业库**跳过初始内置库的文件**，只删自建部分）；(3) 权限按 POLICY 判定，通用库不可回溯。

本脚本纯本地执行，不访问任何网络。
"""
import os
import io
import re
import sys
import shutil
import zipfile
import argparse
import datetime
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 备份隔离目录：默认 ~/.dcr-backups/，与映射表同思路（不与源文件同目录散落）
BACKUP_DIR = os.environ.get("DCR_BACKUP_DIR") or os.path.join(os.path.expanduser("~"), ".dcr-backups")
MAX_BACKUPS = 5   # 每库最多保留份数，满则删最旧（循环覆盖）

# 初始内置的行业库（随包分发）。**不可删除**，但可修改内容；使用者自建的库不受此限。
# 判据：行业库文件名形如 <slug>-rules.md / <slug>-meta.md，slug 在此集合内即为种子库。
# 增删本集合时，对外文案一律用 len(SEED_INDUSTRIES) 取数，不要另写死数字，避免口径漂移。
SEED_INDUSTRIES = {"food", "hr", "manufacturing", "medical",
                   "newenergy", "newmedia", "newretail", "pharma",
                   "realestate"}

# 权限矩阵（写死）。read=AI 内部读取用于审查；view=展示/输出给使用者。
# delete 对 industries 不是简单 True/False —— 种子库不可删、自建库可删，由 do_check 二次判定，
# 故此处置 True 后在 do_check 里拦；置 False 会让"自建库可删"无法通过，二者择此。
POLICY = {
    "core":       {"read": True,  "write": False, "delete": False, "copy": False, "export": False,
                   "import": False, "view": False, "backup": False},
    "industries": {"read": True,  "write": True,  "delete": True,  "copy": True,  "export": True,
                   "import": True,  "view": True,  "backup": True},
    "private":    {"read": True,  "write": True,  "delete": True,  "copy": True,  "export": True,
                   "import": True,  "view": True,  "backup": True},
}
OPS = ("read", "write", "delete", "copy", "export", "import", "view")
OP_CN = {"read": "读取（AI 内部）", "write": "维护/修改/新建/更新", "delete": "删除",
         "copy": "复制", "export": "导出", "import": "导入", "view": "查看（展示给使用者）"}
LIB_CN = {"core": "通用库 core/", "industries": "行业库 industries/", "private": "私有库 private/"}
# 使用者**可以**查看的文档可查看清单（其余一律不可查看/复制/导出）
VIEWABLE = {
    "readme":      "README.md",
    "license":     "LICENSE.md",
    "tutorial":    "安装使用教程.md",
    "prompt":      "文档合规审查助手AI合同提示词版.md",
}
VIEW_CN = {"readme": "技能手册", "version": "版本身份证（当前版本／脚本数／规则数）",
           "versionfile": "版本沿革", "license": "许可与免责", "tutorial": "安装使用教程",
           "prompt": "纯提示词版"}
DENY_HINT = {
    "view": "（规则库与技能内部结构不可外泄；可查看的只有清单内这 5 项，见 `guard.py view`）",
    "copy": "（复制会把技能内容带走，一律拒绝）",
    "export": "（导出技能内容或技能包，一律拒绝）",
    "import": "（导入会改写技能内容，一律拒绝）",
    "write": "（通用库是产品内核，只读、不可修改）",
    "delete": "（通用库不可删除）",
}


def industry_slug(rel):
    """行业库内路径 → 行业 slug；取不到返回 None。

    支持两种形态：`industries/<slug>-rules.md`（现行命名）与 `industries/<slug>/…`（早期/自定义目录形态）。
    """
    parts = str(rel).replace("\\", "/").split("/")
    if len(parts) < 2:
        return None
    head = parts[1]
    if head.startswith("_"):          # _template-* 属模板，不是某个具体行业
        return None
    for suf in ("-rules.md", "-meta.md"):
        if head.endswith(suf):
            return head[: -len(suf)]
    return head if len(parts) > 2 else None


def is_seed_industry(rel):
    """路径是否落在初始内置行业库范围内（不可删除，但可修改）。"""
    return industry_slug(rel) in SEED_INDUSTRIES


def _read(path):
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def skill_meta():
    """读 SKILL.md frontmatter 的 version / name（读不到返回空串，不阻断）。"""
    p = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(p):
        return "", ""
    t = _read(p)
    if not t.startswith("---"):
        return "", ""
    end = t.find("\n---", 3)
    if end < 0:
        return "", ""
    ver = name = ""
    for line in t[3:end].splitlines():
        m = re.match(r"^(version|name):\s*(.*)$", line.rstrip())
        if m:
            val = m.group(2).strip().strip('"').strip("'")
            if m.group(1) == "version":
                ver = val
            else:
                name = val
    return ver, name


def classify(rel):
    """路径 → 库名；不属于三个库的返回 None（视为技能其他内容）。"""
    parts = str(rel).replace("\\", "/").split("/")
    top = parts[0]
    return top if top in POLICY else None


def do_policy():
    ver, name = skill_meta()
    print("[guard] 技能：%s　版本：V%s" % (name or "doc-compliance-review", ver or "未知"))
    print("[guard] 权限矩阵（写死，不接受命令行改写）：")
    print("        %-14s %-8s %-8s %-8s %-8s %-8s %-8s %-8s %-8s"
          % ("资源", "read", "write", "delete", "copy", "export", "import", "view", "backup"))
    for lib in ("core", "industries", "private"):
        p = POLICY[lib]
        row = "        %-14s" % lib
        for op in OPS + ("backup",):
            row += " %-8s" % ("允许" if p.get(op) else "禁止")
        print(row)
    print("[guard] 注：行业库 delete 列的「允许」是**条件允许**——初始内置 %d 个行业库"
          "（%s）不可删除，其余自建库可删。"
          % (len(SEED_INDUSTRIES), "、".join(sorted(SEED_INDUSTRIES))))
    print("[guard] 说明：read=AI 内部读取（审查必需）；view=展示给使用者查看。")
    print("[guard] 可查看清单（%d 项）：%s"
          % (len(VIEWABLE) + 1, "、".join([VIEW_CN[k] for k in ("readme", "version",
                                                                "license", "tutorial", "prompt")])))
    print("[guard] 维护子菜单五项：")
    print("        1 新建规则      2 修改/更新既有规则（改前：python guard.py backup <库>）")
    print("        3 备份          4 回溯（python guard.py restore <库> --pick 1，1＝最新）")
    print("        5 查看备份列表（python guard.py list-backups）")
    print("[guard] 搬运库内容：python guard.py export <库> / import <库> <zip>（导入前自动备份，默认不覆盖同名）")
    print("[guard] 备份最多 %d 份/库，满则循环覆盖；隔离目录 %s" % (MAX_BACKUPS, BACKUP_DIR))
    return 0


def do_check(target, op):
    op = (op or "").strip().lower()
    if op not in OPS:
        print("[guard] 未知操作：%s（可取：%s）" % (op, "/".join(OPS)))
        return 2
    # 归一成相对技能根的路径。
    # 坑一：直接 abspath 会按**当前工作目录**解析，使用者写 `core` / `private` 这类相对技能根的
    #       简写时会被算成技能目录之外的路径，进而误判成"技能自带文件"而拒绝。
    # 坑二：判定「能不能删」时目标往往**尚不存在**（正要删、或还没建），纯靠 exists 探测会落空。
    # 故：相对路径一律先按技能根拼（不依赖 exists），只有绝对路径才直接用；两条都不存在时，
    #     保留技能根拼法，rel 仍能算出库归属。
    ap = target if os.path.isabs(target) else os.path.join(ROOT, target)
    if os.path.isabs(target) and not os.path.exists(ap):
        cand = os.path.join(ROOT, os.path.basename(target))
        if os.path.exists(cand):
            ap = cand
    rel = os.path.relpath(os.path.abspath(ap), ROOT).replace("\\", "/")
    lib = classify(rel)
    # ⚠ 2026-10-20 全量质检修（独立复核实测坐实）：目标不存在时原来直接给判定
    #   （"允许：../../../nonexistent/x.md"），读起来像"文件可以放读"。补一句提示。
    if not os.path.exists(ap):
        print("[guard] 提示：目标不存在（%s）——以下判定按路径归属给出，不代表文件可读" % rel)
    if lib is None:
        # 技能内其他内容：只有可查看清单文档可 view，其余 view/copy/export 一律拒绝
        base = os.path.basename(rel)
        allowed = set(VIEWABLE.values())
        if op == "view":
            if base in allowed:
                print("[guard] 允许：%s（使用者可查看，属可查看清单文档）" % base)
                return 0
            print("[guard] 拒绝：%s 不在可查看清单内 %s" % (base, DENY_HINT["view"]))
            return 3
        if op in ("copy", "export", "import"):
            print("[guard] 拒绝：技能内容不可%s / 不可向技能写入 %s" % (OP_CN[op], DENY_HINT[op]))
            return 3
        if op == "read":
            print("[guard] 允许：%s（AI 内部读取）" % rel)
            return 0
        print("[guard] 拒绝：技能自带文件不可%s" % OP_CN[op])
        return 3
    p = POLICY[lib]
    # 行业库 delete 的二次判定：初始内置行业库**不可删除**，但修改/编辑/更新照常放行；
    # 使用者自建的行业库（slug 不在 SEED_INDUSTRIES 内）可删。
    if lib == "industries" and op == "delete":
        slug = industry_slug(rel)
        if rel in ("industries", "industries/"):
            print("[guard] 拒绝：整个行业库目录不可删除（那是随包资产；要移走某个自建库请指到具体库）")
            return 3
        if slug in SEED_INDUSTRIES:
            print("[guard] 拒绝：初始内置行业库「%s」不可删除——它随安装包分发，删了连升级都补不回来。" % slug)
            print("[guard] 可做的：内容照常维护——修改、编辑、更新规则的任何部分都允许"
                  "（跑 `--op write` 判定即放行）；升级时新版也会整体覆盖这一库。")
            print("[guard] 想停用某个内置库 → 不加载它即可（加载库清单里不勾选），无需删除文件。")
            return 3
        print("[guard] 允许：对%s（自建库「%s」）执行「%s」——自建内容，留或删自定"
              % (LIB_CN[lib], slug or "自建", OP_CN[op]))
        print("[guard] 提醒：删了就找不回来，删前建议先备份：python guard.py backup industries")
        return 0
    if not p.get(op):
        print("[guard] 拒绝：对%s执行「%s」——%s %s"
              % (LIB_CN[lib], OP_CN[op], "规则写死，不可更改" if lib == "core" else "该库不允许此操作",
                 DENY_HINT.get(op, "")))
        if lib == "core" and op in ("write", "delete"):
            print("[guard] 替代：需要收紧或改写内核规则时，用私有库 `<规则ID>@private` 覆盖，不动 core。")
        return 3
    hint = ""
    if op == "write" and p.get("backup"):
        hint = "（维护前请先备份：python guard.py backup %s）" % lib
    print("[guard] 允许：对%s执行「%s」%s" % (LIB_CN[lib], OP_CN[op], hint))
    return 0


def do_backup(lib, tag=None):
    lib = (lib or "").strip().lower()
    if lib not in POLICY:
        print("[guard] 未知库：%s（可取：private / industries）" % lib)
        return 2
    p = POLICY[lib]
    if not p.get("backup"):
        print("[guard] 拒绝：%s 不允许备份（备份即复制，与该库权限冲突）" % LIB_CN[lib])
        return 3
    src = os.path.join(ROOT, lib)
    if not os.path.isdir(src):
        print("[guard] 目录不存在，无需备份：%s" % src)
        return 1
    ver, _ = skill_meta()
    outdir = os.path.join(BACKUP_DIR, lib)
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "%s-V%s-%s" % (lib, ver or "0.0.0", stamp)
    if tag:   # 回溯前的"当前状态"备份带标记，一眼看出它不是常规备份
        base = "%s-%s" % (base, tag)
    # 同一秒内重复备份会撞名，加序号区分，避免后一次静默覆盖前一次
    name, i = base + ".zip", 1
    while os.path.exists(os.path.join(outdir, name)):
        i += 1
        name = "%s-%d.zip" % (base, i)
    dst = os.path.join(outdir, name)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for r, ds, fs in os.walk(src):
            ds[:] = [d for d in ds if d != "__pycache__"]
            for f in fs:
                if f.endswith(".pyc"):
                    continue
                fp = os.path.join(r, f)
                z.write(fp, os.path.relpath(fp, src))
                n += 1
    print("[guard] 已备份 %s → %s（%d 个文件）" % (LIB_CN[lib], dst, n))
    # 循环覆盖：保留最近 MAX_BACKUPS 份，多余的删最旧
    zips = sorted([f for f in os.listdir(outdir) if f.endswith(".zip")])
    removed = []
    while len(zips) > MAX_BACKUPS:
        old = zips.pop(0)
        os.remove(os.path.join(outdir, old))
        removed.append(old)
    if removed:
        print("[guard] 备份已满 %d 份，循环覆盖删最旧：%s" % (MAX_BACKUPS, "、".join(removed)))
    print("[guard] 现有备份 %d/%d 份（隔离目录：%s）" % (len(zips), MAX_BACKUPS, outdir))
    return 0


def do_list_backups(lib=None):
    libs = [lib] if lib else ["private", "industries"]
    total = 0
    for lb in libs:
        d = os.path.join(BACKUP_DIR, lb)
        if not os.path.isdir(d):
            print("[guard] %s：尚无备份" % LIB_CN.get(lb, lb))
            continue
        zs = _backup_names(lb)
        print("[guard] %s：%d/%d 份（序号 1＝最新，restore --pick N 即取第 N 份）"
              % (LIB_CN.get(lb, lb), len(zs), MAX_BACKUPS))
        for i, f in enumerate(zs, 1):
            fp = os.path.join(d, f)
            sz = os.path.getsize(fp)
            tm = datetime.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S")
            print("        %2d. %-46s %8d 字节  %s" % (i, f, sz, tm))
        total += len(zs)
    print("[guard] 隔离目录：%s" % BACKUP_DIR)
    return 0


def _backup_names(lib):
    """备份文件名列表，按时间**由新到旧**排（序号 1＝最新，与 restore --pick 的编号一致）。"""
    d = os.path.join(BACKUP_DIR, lib)
    if not os.path.isdir(d):
        return []
    zs = sorted([f for f in os.listdir(d) if f.endswith(".zip")])
    zs.reverse()
    return zs


def do_restore(lib, pick=None, zipfile_path=None, prune=False):
    """回溯：把某份备份恢复回库目录。恢复前先备份当前状态，任何一次回溯都还能再退回来。"""
    lib = (lib or "").strip().lower()
    if lib not in POLICY:
        print("[guard] 未知库：%s（可取：private / industries）" % lib)
        return 2
    p = POLICY[lib]
    if not p.get("write"):
        print("[guard] 拒绝：%s 不允许回溯（回溯＝写入，与该库权限冲突）" % LIB_CN[lib])
        print("[guard] 替代：通用库想收紧规则，用私有库 `<规则ID>@private` 覆盖，不动 core。")
        return 3
    if prune and not p.get("delete"):
        print("[guard] 拒绝：%s 不允许删除，故不支持 `--prune` 严格还原（只做覆盖＋补齐）" % LIB_CN[lib])
        return 3
    if lib == "industries" and prune:
        print("[guard] 提示：行业库 `--prune` 只删自建库文件，初始内置 %d 个行业库一律保留。"
              % len(SEED_INDUSTRIES))
    names = _backup_names(lib)
    if not names:
        print("[guard] %s 尚无备份，无回溯点可退（先跑：python guard.py backup %s）" % (LIB_CN[lib], lib))
        return 1
    if zipfile_path:
        zp = os.path.abspath(zipfile_path)
        if not os.path.exists(zp):
            cand = os.path.join(BACKUP_DIR, lib, zipfile_path)
            zp = cand if os.path.exists(cand) else zp
    elif pick:
        try:
            i = int(pick)
        except Exception:
            print("[guard] --pick 需为数字序号（list-backups 可见，1＝最新）")
            return 2
        if i < 1 or i > len(names):
            print("[guard] 序号越界：%d（可用 1–%d）" % (i, len(names)))
            return 2
        zp = os.path.join(BACKUP_DIR, lib, names[i - 1])
    else:
        print("[guard] 请指定回溯点：`--pick N`（N 见 list-backups，1＝最新）或 `--file <备份.zip>`")
        for i, f in enumerate(names, 1):
            print("        %2d. %s" % (i, f))
        return 1
    if not os.path.exists(zp):
        print("[guard] 备份不存在：%s" % zp)
        return 1
    if not zipfile.is_zipfile(zp):
        print("[guard] 不是有效的备份包：%s" % zp)
        return 2
    dest = os.path.join(ROOT, lib)
    os.makedirs(dest, exist_ok=True)
    # 安全阀一：先把当前状态存一份（带 -prerestore 标记），回溯错了还能再退回来
    print("[guard] 回溯前先备份当前状态：")
    do_backup(lib, tag="prerestore")
    tmp = tempfile.mkdtemp(prefix="dcr-restore-")
    try:
        with zipfile.ZipFile(zp) as z:
            z.extractall(tmp)
        covered, added, kept = 0, 0, []
        have = set()
        for r, ds, fs in os.walk(tmp):
            ds[:] = [d for d in ds if d != "__pycache__"]
            for f in fs:
                if f.endswith(".pyc"):
                    continue
                rel = os.path.relpath(os.path.join(r, f), tmp).replace("\\", "/")
                have.add(rel)
                tgt = os.path.join(dest, rel.replace("/", os.sep))
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                if os.path.exists(tgt):
                    covered += 1
                else:
                    added += 1
                shutil.copyfile(os.path.join(r, f), tgt)
        # 安全阀二：默认只覆盖＋补齐，不删；--prune 才严格还原。
        # 私有库照删；行业库**跳过初始内置库的文件**——那些是随包资产，删了升级也回不来。
        if prune:
            for r, ds, fs in os.walk(dest):
                ds[:] = [d for d in ds if d != "__pycache__"]
                for f in fs:
                    rel = os.path.relpath(os.path.join(r, f), dest).replace("\\", "/")
                    if rel in have:
                        continue
                    if lib == "industries" and is_seed_industry(rel):
                        kept.append(rel + "（内置库，保留）")
                        continue
                    os.remove(os.path.join(r, f))
                    kept.append(rel)
        else:
            for r, ds, fs in os.walk(dest):
                ds[:] = [d for d in ds if d != "__pycache__"]
                for f in fs:
                    rel = os.path.relpath(os.path.join(r, f), dest).replace("\\", "/")
                    if rel not in have:
                        kept.append(rel)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[guard] 已回溯 %s ← %s（覆盖 %d 个、补齐 %d 个）" % (LIB_CN[lib], os.path.basename(zp), covered, added))
    if kept:
        print("[guard] 备份中没有、本次保留的现有文件 %d 个%s："
              % (len(kept), "（--prune 已删除）" if prune else "（默认不删；确需严格还原请用 --prune）"))
        for k in kept[:20]:
            print("        -", k)
        if len(kept) > 20:
            print("        …… 其余 %d 个未列" % (len(kept) - 20))
    print("[guard] 提示：回溯只改库内容，不影响技能本体；如需退回本次回溯，用 list-backups 里带 "
          "-prerestore 标记的那一份再 restore 一次。")
    return 0


def do_export(lib, out=None):
    """导出库为 zip：换机器、给同事、或导出后再放心改。

    导出的是**库内容**（规则文件），不是技能本体；skill 结构与脚本不在导出范围内。
    """
    lib = (lib or "").strip().lower()
    if lib not in POLICY:
        print("[guard] 未知库：%s（可取：private / industries）" % lib)
        return 2
    if not POLICY[lib].get("export"):
        print("[guard] 拒绝：%s 不允许导出 %s" % (LIB_CN[lib], DENY_HINT["export"]))
        return 3
    src = os.path.join(ROOT, lib)
    if not os.path.isdir(src):
        print("[guard] 目录不存在：%s" % src)
        return 1
    ver, _ = skill_meta()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.abspath(out or os.path.join(os.getcwd(), "%s-V%s-%s.zip" % (lib, ver or "0.0.0", stamp)))
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for r, ds, fs in os.walk(src):
            ds[:] = [d for d in ds if d != "__pycache__"]
            for f in fs:
                if f.endswith(".pyc"):
                    continue
                fp = os.path.join(r, f)
                z.write(fp, os.path.join(lib, os.path.relpath(fp, src)))
                n += 1
    print("[guard] 已导出 %s → %s（%d 个文件）" % (LIB_CN[lib], dst, n))
    print("[guard] 说明：导出的只是%s的规则文件，不含技能本体与脚本；它现在是你的数据，可自由搬运。"
          % ("企业内控口径" if lib == "private" else "行业要点"))
    if lib == "private":
        print("[guard] 注意：私有库可能含企业内控红线，导出后按涉密级别自行保管。")
    return 0


def do_import(lib, src_zip, overwrite=False):
    """导入 zip 到库：别人给的一份口径、或本机导出后再搬回来。

    安全考虑：(1) 导入＝写库，导入前自动备份当前状态；(2) 默认**不覆盖同名文件**（怕误冲自己的口径），
    要覆盖显式加 --overwrite；(3) 只接受 zip，且 zip 内路径必须落在该库范围内（防越界写）。
    """
    lib = (lib or "").strip().lower()
    if lib not in POLICY:
        print("[guard] 未知库：%s（可取：private / industries）" % lib)
        return 2
    if not POLICY[lib].get("import"):
        print("[guard] 拒绝：%s 不允许导入 %s" % (LIB_CN[lib], DENY_HINT["import"]))
        return 3
    zp = os.path.abspath(src_zip)
    if not os.path.exists(zp):
        print("[guard] 文件不存在：%s" % zp)
        return 1
    if not zipfile.is_zipfile(zp):
        print("[guard] 不是有效的 zip：%s" % zp)
        return 2
    dest = os.path.join(ROOT, lib)
    os.makedirs(dest, exist_ok=True)
    added, skipped, bad = [], [], []
    print("[guard] 导入前先备份当前状态：")
    do_backup(lib, tag="preimport")
    seed_blocked = []
    with zipfile.ZipFile(zp) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename.endswith("/"):
                continue
            rel = info.filename.replace("\\", "/")
            # 去掉包前缀（导出时第一层是库名），只留库内相对路径
            parts = rel.split("/")
            if parts[0] == lib:
                rel = "/".join(parts[1:])
            if not rel or rel.startswith("/") or ".." in parts:
                bad.append(info.filename)
                continue
            tgt = os.path.join(dest, rel.replace("/", os.sep))
            # 初始内置行业库不可删除，同理也不允许被外来文件覆盖（实质是改写/顶替其内容）
            if lib == "industries" and is_seed_industry(rel) and os.path.exists(tgt):
                seed_blocked.append(rel)
                continue
            if os.path.exists(tgt) and not overwrite:
                skipped.append(rel)
                continue
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            os.makedirs(os.path.dirname(tgt) or ".", exist_ok=True)
            with z.open(info) as fin, open(tgt, "wb") as fout:
                fout.write(fin.read())
            added.append(rel)
    print("[guard] 导入 %s ← %s：新增/覆盖 %d 个" % (LIB_CN[lib], os.path.basename(zp), len(added)))
    if skipped:
        print("[guard] 同名存在、未覆盖 %d 个（要覆盖加 --overwrite）：" % len(skipped))
        for s in skipped[:20]:
            print("        -", s)
    if seed_blocked:
        print("[guard] 初始内置行业库已存在同名档 %d 个，未导入（内置库只可在技能内修改，不可被外来文件顶替）："
              % len(seed_blocked))
        for s in seed_blocked[:20]:
            print("        -", s)
    if bad:
        print("[guard] 跳过 %d 个越界/非法路径条目（zip 内路径须落在 %s 内）" % (len(bad), lib))
    print("[guard] 下一步：跑 python guard.py policy 复查权限，或直接开始审查验证新规则是否生效。")
    return 0


def do_view(name):
    key = (name or "").strip().lower()
    if key == "version":
        # 版本身份证＝version.py 的输出；此处直接复用其逻辑，避免两处各算一套
        vp = os.path.join(HERE, "version.py")
        if not os.path.exists(vp):
            print("[guard] 未找到 version.py")
            return 1
        import importlib.util
        spec = importlib.util.spec_from_file_location("_dcr_version", vp)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.show()
    if key == "versionfile":
        # v3.26.2：沿革（VERSION.md）不随技能分发，历史版本信息不对外提供。
        # 命令保留但明确告知，避免使用者以为是文件丢失或权限被收紧。
        print("[guard] 本版本不提供版本沿革（历史版本信息不对外提供）。")
        print("[guard] 想确认「当前是哪一版」：python scripts/version.py  （版本身份证，离线可用）")
        return 0
    if key not in VIEWABLE:
        print("[guard] 不可查看：%s" % name)
        print("[guard] 可查看清单（%d 项）：%s"
              % (len(VIEWABLE) + 1, "、".join(sorted(list(VIEWABLE) + ["version"]))))
        return 3
    p = os.path.join(ROOT, VIEWABLE[key])
    if not os.path.exists(p):
        print("[guard] 文件缺失：%s" % p)
        return 1
    print(_read(p))
    return 0


def main():
    ap = argparse.ArgumentParser(description="资源权限守卫与库备份（规则正文见 SKILL.md 第十五节）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("policy", help="打印权限矩阵")
    c = sub.add_parser("check", help="判定某路径能否做某操作")
    c.add_argument("target")
    c.add_argument("--op", required=True, help="read/write/delete/copy/export/import/view")
    b = sub.add_parser("backup", help="改库前备份（最多 %d 份，循环覆盖）" % MAX_BACKUPS)
    b.add_argument("lib", help="private 或 industries")
    lb = sub.add_parser("list-backups", help="列出已有备份（序号 1＝最新）")
    lb.add_argument("lib", nargs="?", default=None)
    rs = sub.add_parser("restore", help="回溯：从备份中选取一份恢复（恢复前先自动备份当前状态）")
    rs.add_argument("lib", help="private 或 industries")
    rs.add_argument("--pick", default=None, help="备份序号（见 list-backups，1＝最新）")
    rs.add_argument("--file", dest="zipfile", default=None, help="直接指定备份 zip 路径或文件名")
    rs.add_argument("--prune", action="store_true",
                    help="严格还原：删除备份中没有的现有文件（行业库跳过初始内置库）")
    ex = sub.add_parser("export", help="导出库为 zip（换机器/给同事；导出的是库内容，不是技能本体）")
    ex.add_argument("lib", help="private 或 industries")
    ex.add_argument("--out", default=None, help="输出 zip 路径（默认当前目录 <库>-V<版本>-<时间>.zip）")
    im = sub.add_parser("import", help="导入 zip 到库（导入前自动备份；默认不覆盖同名）")
    im.add_argument("lib", help="private 或 industries")
    im.add_argument("zipfile", help="待导入的 zip（guard.py export 产出的格式）")
    im.add_argument("--overwrite", action="store_true", help="允许覆盖同名文件")
    v = sub.add_parser("view", help="输出可查看清单内文档")
    v.add_argument("name", help="readme/version/versionfile/license/tutorial/prompt")
    a = ap.parse_args()

    if a.cmd == "policy":
        return do_policy()
    if a.cmd == "check":
        return do_check(a.target, a.op)
    if a.cmd == "backup":
        return do_backup(a.lib)
    if a.cmd == "list-backups":
        return do_list_backups(a.lib)
    if a.cmd == "restore":
        return do_restore(a.lib, pick=a.pick, zipfile_path=a.zipfile, prune=a.prune)
    if a.cmd == "export":
        return do_export(a.lib, out=a.out)
    if a.cmd == "import":
        return do_import(a.lib, a.zipfile, overwrite=a.overwrite)
    return do_view(a.name)


if __name__ == "__main__":
    _sys.exit(main())
