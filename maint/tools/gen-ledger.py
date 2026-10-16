#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出物台账生成器 —— 扫描 dist/ 与开发侧关键文件，生成《产出物台账.md》。

用法：
    python3 gen-ledger.py                 # 写入 /workspace/产出物台账.md
    python3 gen-ledger.py --print         # 只打印到 stdout，不落盘
    python3 gen-ledger.py --no-files      # 只出总表，不出「技能本体文件清单」大表

维护约定（见 DEV-RULES 第 12 条）：每次交付产出物后，同步跑一次本脚本刷新台账。
生成物是**可重建的派生文件**，真源是 dist/ 与 dev/ 下的实际文件。
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

ROOT = "/workspace"
DIST = os.path.join(ROOT, "dist")
DEV = os.path.join(ROOT, "dev")
SKILL = os.path.join(DEV, "doc-compliance-review")
OUT = os.path.join(ROOT, "产出物台账.md")

CST = timezone(timedelta(hours=8))

# 分发包四段式：中文产品名_版本号_日期_(技能ID).扩展名
PKG_RE = re.compile(r"^(?P<name>.+?)_(?P<ver>v\d+\.\d+\.\d+)_(?P<date>\d{8})_\((?P<slug>[^)]+)\)\.(?P<ext>skill|zip)$")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ver_key(v):
    return tuple(int(x) for x in v.lstrip("Vv").split("."))


def scan_dist():
    """扫分发包，按 版本→扩展名(.skill 在前) 排序。"""
    rows = []
    if not os.path.isdir(DIST):
        return rows
    for fn in os.listdir(DIST):
        m = PKG_RE.match(fn)
        if not m:
            continue
        p = os.path.join(DIST, fn)
        st = os.stat(p)
        rows.append({
            "file": fn,
            "ver": m.group("ver"),
            "date": m.group("date"),
            "ext": m.group("ext"),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, CST).strftime("%Y-%m-%d"),
            "sha256": sha256(p),
            "version_in_name": (m.group("ver") == m.group("ver")),  # 占位，正文另校验
        })
    rows.sort(key=lambda r: (ver_key(r["ver"]), 0 if r["ext"] == "skill" else 1))
    return rows


def get_version_of_pkg(row):
    """从包名取版本，不含 V 前缀。"""
    return row["ver"].lstrip("V")


def read_dev_rules_version():
    p = os.path.join(DEV, "DEV-RULES.md")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"\*\*版本 (v\d+\.\d+\.\d+)\*\*", line)
            if m:
                return m.group(1)
    return None


def read_skill_version():
    p = os.path.join(SKILL, "SKILL.md")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        head = f.read(4000)
    m = re.search(r"^version:\s*(\d+\.\d+\.\d+)", head, re.M)
    return ("v" + m.group(1)) if m else None


def scan_skill_files():
    """列技能本体全部文件（以 git 跟踪为准，无 git 则全盘扫）。"""
    names = []
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "doc-compliance-review/"],
            cwd=DEV, capture_output=True, check=True,
        ).stdout.decode("utf-8").split("\0")
        names = [x for x in out if x]
        if not names:
            raise RuntimeError("git ls-files 返回空，回退全盘扫描")
    except Exception:
        for dp, _, fns in os.walk(SKILL):
            for fn in fns:
                full = os.path.join(dp, fn)
                names.append(os.path.relpath(full, DEV))
    rows = []
    for n in names:
        full = os.path.join(DEV, n)
        if not os.path.isfile(full):
            continue
        rows.append({
            "path": n[len("doc-compliance-review/"):],
            "size": os.path.getsize(full),
            "sha256": sha256(full),
        })
    rows.sort(key=lambda r: r["path"])
    return rows


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/1024/1024:.2f} MB"


def build(no_files=False):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    pkgs = scan_dist()
    versions = sorted({p["ver"] for p in pkgs}, key=ver_key)
    latest = versions[-1] if versions else None
    dev_ver = read_dev_rules_version()
    skill_ver = read_skill_version()

    L = []
    A = L.append

    A("# 产出物台账 ｜ Artifact Ledger")
    A("")
    A(f"**最近刷新：{now}（北京时间）** ｜ 台账文件：`/workspace/产出物台账.md`")
    A("")
    A("> 本台账登记工作目录内**全部可交付产出物**，含文件指纹（SHA256），供核对完整性、"
      "追溯版本、批量交付使用。")
    A("> **本文件是可重建的派生文件**：真源为 `dist/` 与 `dev/` 下的实际文件；"
      "刷新方式见文末「维护方式」。")
    A("")
    A("---")
    A("")

    # ── 一、当前在役版本 ──
    A("## 一、当前在役版本")
    A("")
    A("| 产出物 | 版本 | 状态 | 文件 |")
    A("|---|---|---|---|")
    if latest:
        sk = [p for p in pkgs if p["ver"] == latest and p["ext"] == "skill"]
        zp = [p for p in pkgs if p["ver"] == latest and p["ext"] == "zip"]
        f1 = f"`dist/{sk[0]['file']}`" if sk else "—"
        f2 = f"`dist/{zp[0]['file']}`" if zp else "—"
        A(f"| 文档合规审查技能（分发包） | {latest} | **在役** | {f1}（.skill）<br>{f2}（.zip） |")
    A(f"| 开发工程规范（铁律） | {dev_ver or '—'} | **在役**（开发侧，不外流） | `dev/DEV-RULES.md` |")
    if skill_ver and latest and skill_ver != latest:
        A(f"| 技能本体（工作副本） | {skill_ver} | 注意：与最新包 {latest} 不一致 | `dev/doc-compliance-review/` |")
    elif skill_ver:
        A(f"| 技能本体（工作副本） | {skill_ver} | 与最新包一致 | `dev/doc-compliance-review/` |")
    A("")
    A(f"- 分发包总数：**{len(pkgs)}** 个（覆盖 **{len(versions)}** 个版本：{versions[0]} — {latest}）")
    A(f"- 统计口径：`dist/` 目录实时扫描；只认四段式命名的包。")
    A("")
    A("---")
    A("")

    # ── 二、分发包总表 ──
    A("## 二、分发包总表")
    A("")
    A("> 命名四段式：`中文产品名_版本号_日期_(技能ID).扩展名`。"
      "同一版本成对出包：`.skill`（自定义头部 + zip 负载）与 `.zip`（纯 ZIP）。")
    A("")
    A("| # | 版本 | 日期 | 格式 | 大小 | 文件 | SHA256（前 16 位） |")
    A("|---:|---|---|---|---|---|---|")
    for i, p in enumerate(pkgs, 1):
        mark = " **←最新**" if p["ver"] == latest else ""
        A(f"| {i} | {p['ver']}{mark} | {p['date']} | `.{p['ext']}` | "
          f"{fmt_size(p['size'])} | `{p['file']}` | `{p['sha256'][:16]}` |")
    A("")
    A("**完整性核验**（在 `/workspace` 下执行）：")
    A("")
    A("```bash")
    A("sha256sum dist/*.skill dist/*.zip")
    A("```")
    A("")
    A("---")
    A("")

    # ── 二·补、腾讯文档交付（在线入口；按铁律 23.2／23.3 分链接可信度） ──
    A("## 二·补、腾讯文档交付（在线入口）")
    A("")
    A("> 无需本地取件即可查看/下载的在线交付。**本节按链接可信度分两级**"
      "（铁律 23.3）：**稳定**＝文件本体链接，可长期引用、直达固定那一份；"
      "**不稳定**＝文档派生的在线版链接，随每次导入滚动，**只作溯源自录**。")
    A("")
    # ⚠ 在线链接与 file_id 来自外部上传，无法自动派生：每次重传后须同步更新以下两端。
    _online_ver = latest or "—"
    A("### 稳定链接（文件本体，可长期引用）")
    A("")
    A("| 内容 | 类型 | 在线地址 |")
    A("|---|---|---|")
    A(f"| 技能包 {_online_ver}（`.skill`） | 腾讯文档 · 文件 | https://docs.qq.com/document/DRFF6eVZ1enpxWk1q |")
    A(f"| 技能包 {_online_ver}（`.zip`） | 腾讯文档 · 文件 | https://docs.qq.com/document/DREFRUElaTFFySE14 |")
    A("")
    A("### 不稳定链接（文档派生，只作溯源自录）")
    A("")
    A("| 内容 | 类型 | 在线地址 | 说明 |")
    A("|---|---|---|---|")
    A("| 产出物台账（本文档的在线版） | 腾讯文档 | "
      "https://docs.qq.com/markdown/DRHdRdXZLRFJYd0hq | **以最新一次导入为准**，勿作长期引用目标 |")
    A("")
    A("**导入溯源**（腾讯文档侧 `file_id`，便于核对）："
      "台账 `DwQuvKDRXwHj`／`.skill` `DQzyVuzzqZMj`／`.zip` `DAQPIZLQrHMx`。")
    A("")
    A("> **维护提示**（铁律 23.2.3）：腾讯文档导入**只新建、不覆盖**，故台账自指的"
      "「在线版」链接天然**差一代**——该链接与 `file_id` 仅供溯源，**以最新导入的那一份为准**。"
      "技能包为文件本体，链接**反之稳定**，可长期引用。")
    A("")
    A("> **受限项与整改待办**（铁律 23.4：通道不可用**不得假装已分发**——"
      "「暂时做不到」要写清楚，不得留白）：")
    A(">")
    A("> **受限一 · 通道为临时**：本节在线入口均为**临时**交付（腾讯文档导入侧限制所致）。"
      "正式发布后应改为「文件本体直链」（如 releases 附件），"
      "届时把不稳定链接整体降级为溯源备注。")
    A(">")
    A("> **受限二 · 仓库已定、清单未推**（2026-10-16 更新）：正式仓库已确定为 "
      "`https://github.com/asktai/doc-compliance-review`，技能侧 `version.json`／`config.json` "
      "的地址**已由占位 `<your-org>` 填为真值**（随 v3.11.12 出包）。"
      "**但本机 `gh` 未登录、GitHub API 对本环境返回 403**，故**清单文件尚未推送、releases 未建**"
      "——此刻「在线检查更新」仍**读不到清单**，按 15.4.5.1 **静默降级纯本地**（不报错、不卡住、不打扰）。")
    A(">")
    A("> **当前可用取件通道**＝本节上表的腾讯文档链接（技能包为文件本体，**稳定级**）。"
      "**解除受限二的操作**（须开发者提供 GitHub 凭据后执行）："
      "① `gh auth login` 授权 → ② 把 `version.json` 推到仓库默认分支 → "
      "③ 建 v3.11.12 release 并上传 `dist/` 下 `.skill`／`.zip` 作附件 → "
      "④ 把本节「稳定链接」改为 releases 附件直链，并把不稳定链接降级为溯源备注。")
    A("")
    A("---")
    A("")

    # ── 三、开发侧文件（不外流） ──
    A("## 三、开发侧文件（维护侧，不进技能包、不随分发包外流）")
    A("")
    A("| 文件 | 说明 | 大小 | SHA256（前 16 位） |")
    A("|---|---|---|---|")
    dev_files = [
        ("dev/DEV-RULES.md", "开发工程规范（铁律）——AI 开发行为红线与流程"),
        ("dev/CHANGELOG.md", "技能版本沿革（面向交付）"),
        ("dev/maint/DEVLOG.md", "开发日志（开发侧，含事故复盘）"),
        ("dev/publish.py", "发布链脚本（sync → 分离守卫 → 校验 → 打包）"),
        ("dev/maint/tools/check-dev-rules.py", "铁律自检守卫（十二维）"),
        ("dev/maint/tools/smoke-dev-rules.py", "铁律全量冒烟（注入测试，证明守卫拦得住）"),
        ("dev/maint/tools/check-separation.py", "分离守卫（开发侧／技能侧分离，铁律第 9 条）"),
        ("dev/maint/samples-manifest.json", "素材准入清单（samples/ 逐条许可登记）"),
    ]
    for rel, desc in dev_files:
        full = os.path.join(ROOT, rel)
        if os.path.isfile(full):
            A(f"| `{rel}` | {desc} | {fmt_size(os.path.getsize(full))} | `{sha256(full)[:16]}` |")
    A("")
    A("---")
    A("")

    # ── 四、技能本体文件清单 ──
    if not no_files:
        files = scan_skill_files()
        A("## 四、技能本体文件清单")
        A("")
        A(f"> 路径相对 `dev/doc-compliance-review/`，共 **{len(files)}** 个文件，"
          f"合计 {fmt_size(sum(f['size'] for f in files))}。")
        A("> 本清单用于核对工作副本与分发包内容是否一致。")
        A("")
        A("| 文件 | 大小 | SHA256 |")
        A("|---|---|---|")
        for f in files:
            A(f"| `{f['path']}` | {fmt_size(f['size'])} | `{f['sha256']}` |")
        A("")
        A("---")
        A("")

    # ── 五、维护方式 ──
    A("## 五、维护方式")
    A("")
    A("**例行流程**：每次产出新文件后，刷新本台账。")
    A("")
    A("```bash")
    A("# 全量重建台账")
    A("python3 /workspace/dev/maint/tools/gen-ledger.py")
    A("")
    A("# 只预览不落盘")
    A("python3 /workspace/dev/maint/tools/gen-ledger.py --print")
    A("```")
    A("")
    A("**设计约定**：")
    A("")
    A("- 本台账由脚本**全量重建**，不做增量追加——避免手工追加导致的漏登、重登、指纹过期。")
    A("- 真源是 `dist/` 与 `dev/` 下的实际文件；本台账随时可丢弃重建。")
    A("- 脚本只读扫描，**不修改任何产出物**；哈希基于文件当前字节，文件一改台账即过期，须重跑。")
    A("")
    A("**资料库同步（待开通）**：当前沙箱对资料库只有读权限（网关仅挂 `library_search` 工具），"
      "写入通道不可用。资料库写入权限开通后，可用本台账「分发包总表」的版本与文件列作为"
      "**批量上传清单**，逐条上传并回填状态。")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="to_stdout", action="store_true", help="只打印，不写文件")
    ap.add_argument("--no-files", action="store_true", help="不出「技能本体文件清单」大表")
    args = ap.parse_args()

    text = build(no_files=args.no_files)
    if args.to_stdout:
        sys.stdout.write(text)
    else:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
        n_lines = text.count("\n")
        print(f"[OK] 已写出 {OUT}（{n_lines} 行）")


if __name__ == "__main__":
    main()
