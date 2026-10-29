#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L1  在线只读公开信息（请求不含任何使用者数据）；须可关，离线静默降级
"""
版本身份证 · 更新检测 · 本地升级（scripts/version.py）
=====================================================
用途：解决"装完之后不知道自己装的是哪一版、有没有新版、新版怎么装上去"。
      三件事：**看清当前版本**（身份证）→ **比对更新源**（有没有新版）→ **本地升级**（带备份）。

用法：
    python version.py                        打印当前版本身份证
    python version.py --check <源>           与更新源比对（源＝解开的目录 或 未解开的 .zip）
    python version.py --check                省略源时，用 --watch 登记过的那个
    python version.py --changelog <源>       摘出「从当前版本到源版本」之间的沿革条目
    python version.py --upgrade <源> --target <安装目录>
                                             升级预演（默认 dry-run，列出覆盖/新增/保留）
    python version.py --upgrade <源> --target <安装目录> --apply
                                             真正升级（先整目录备份，再覆盖）
    python version.py --upgrade ... --overwrite-config
                                             连 config.json 一起覆盖（默认保留本机配置）

**更新源登记与更新提示**（对应"技能版本 / 技能更新 / 技能升级"三个入口）：
    python version.py --watch <源>           登记一个更新源（本机记录路径，以后不必每次手打）
    python version.py --source               看当前登记的是哪个源、上次查到哪一版
    python version.py --unwatch              取消登记
    python version.py --notice               静默检查有没有新版（**无新版完全不输出**，退出码 0；
                                             有新版才输出一行提示，退出码 1）
    python version.py --dismiss <版本>       忽略某个版本的提醒（使用者明确说"先不升"时用）
    python version.py --undismiss            恢复提醒

> **升级永远是使用者说了算。** `--notice` 只提示，不改任何文件；`--upgrade` 不带 `--apply` 就是
> 预演（dry-run），只列出会覆盖/新增/保留什么，一个字节都不动。发现新版就自动替使用者升级，
> 是明确排除的行为——版本换季可能改变审查口径与产出形态，必须由人判断何时切。

**联网口径（分级，2026-10-22 起默认关闭）**——本脚本把"查更新"与"拿更新"分成两件事：
  · **查有无新版**：**默认不联网**。只有两种情形才发请求——(a) 使用者命令行显式打
    `--check-online`（一次性知情同意）；(b) config.json 里 `update.check_online_by_default`
    **被显式设为 true**（长期知情同意）。发请求时只读一份公开 `version.json` 清单，
    **不上传任何使用者信息**；离线／连不上／未配置时**静默降级**，退回本地已登记的更新源，
    绝不报错、绝不卡住。这是本技能唯一会联网的脚本，默认关闭是为了让"联网"永远由人先开口。
  · **下载新版包**：**由使用者手动**——工具只给出"下载页地址"，包由使用者在浏览器里自己下。
    工具**从不自动下载、从不自动安装**。
  · **本地方式始终可用**：更新源也可以是本地目录或已下载的 zip（`--watch` 登记），
    该路径**完全不联网**，适合内网／离网环境。
  两条路径在"装"这一步完全同构：接到的都是一个本地目录或本地 zip，故走同一套校验／预演／
  备份／升级链。判定依据＝两侧 `SKILL.md` frontmatter 的 `version` 字段。

保护规则（升级时）：
- `private/` **永不覆盖**（脱敏词表、映射表属本机私有数据）；
- `scripts/config.json` **默认保留**（本机工具路径与工作目录设置），需 `--overwrite-config` 才覆盖；
- 目标里有、源里没有的文件**一律保留**并列出，不删除。
备份：升级前整目录备份到 `<安装目录>_bak-V<旧版本>-<时间戳>`，与安装目录同级。
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import re
import io
import glob
import shutil
import zipfile
import argparse
import datetime
import tempfile

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_sys.path.insert(0, HERE)
import _config as _cfgmod

SKILL_PATH = os.path.join(ROOT, "SKILL.md")
# 永不覆盖（本机私有数据）
NEVER_OVERWRITE = ("private",)
# 默认保留、需显式 --overwrite-config 才覆盖
KEEP_CONFIG = "scripts/config.json"
# 复制时排除
SKIP_PAT = ("__pycache__", "*.pyc", "_*.log.txt", ".DS_Store")

# 更新源登记：把"去哪儿找新版"记在本机隔离目录，避免每次手打长路径。
# 与映射表、备份同思路——不落在技能目录内，免得整目录外发时把使用者的更新来源一并带出去。
UPDATE_DIR = os.environ.get("DCR_UPDATE_DIR") or os.path.join(os.path.expanduser("~"), ".dcr-updates")
SOURCE_FILE = os.path.join(UPDATE_DIR, "source.json")

# 在线检查更新的网络超时（秒）。**刻意短**：这个检查是可选的锦上添花，
# 绝不能因为对方站点慢/不通就把使用者的命令卡在那里。
ONLINE_TIMEOUT = 6


def _load_update_cfg():
    """读在线更新配置（config.json 的 update 段）。

    三层叠加交给 _config.load() 处理；这里只取 update 段。
    未配置、解析失败、字段缺失一律返回空 dict——**在线检查是可选增强**，
    配置缺失时自动退回纯本地模式，不报错、不打扰。
    """
    try:
        cfg = _cfgmod.load()
        u = cfg.get("update") or {}
        if not isinstance(u, dict):
            return {}
        return u
    except Exception:
        return {}


def _online_enabled(u):
    """在线检查是否可用：须有清单地址，且开关未显式关闭。

    默认**关闭**：config.json 的 `update.check_online_by_default` 须显式为 true 才启用。
    为什么默认关：这是唯一会联网的脚本，而联网这件事一旦默认打开，
    使用者在完全不知情的情况下就产生了外连记录——即便只读、即便不带任何使用者信息。
    想用在线检查须自己显式打开一次，这一步就是「知情」本身。
    """
    url = (u.get("manifest_url") or "").strip()
    if not url or "<your-org>" in url:      # 占位地址＝尚未配置真源，等同于关闭
        return False
    if u.get("check_online_by_default") is not True:   # 缺省即关，只有显式 true 才开
        return False
    return True


def _fetch_manifest(url):
    """只读拉取在线版本清单（version.json）。**任何异常都吞掉、返回 None**。

    设计取向（与 --notice 一致）：这是"顺带查一下"，不是关键路径。
    离线、被墙、DNS 失败、超时、返回不是 JSON、字段缺失——一律静默降级，
    绝不把网络错误抛给使用者。**只做 GET 读一个公开清单，不上传任何信息。**
    """
    import json
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={
            # 只声明"谁能取"，不带任何使用者标识；UA 便于对方站点统计
            "User-Agent": "doc-compliance-review/version-check",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=ONLINE_TIMEOUT) as resp:
            raw = resp.read(200000)          # 清单很小，设上限防异常大包
        d = json.loads(raw.decode("utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _manifest_latest(m):
    """从清单里取 latest 段，规整成 (版本串, 日期, 摘要, 要点列表, 下载页, 文件直链)。"""
    if not isinstance(m, dict):
        return None
    lat = m.get("latest") or {}
    ver = str(lat.get("version") or "").strip()
    if not re.search(r"\d+\.\d+\.\d+", ver):
        return None
    ch = lat.get("changes") or []
    if not isinstance(ch, list):
        ch = []
    files = lat.get("files") or {}
    if not isinstance(files, dict):
        files = {}
    return {
        "version": ver,
        "date": str(lat.get("date") or "").strip(),
        "summary": str(lat.get("summary") or "").strip(),
        "changes": [str(x).strip() for x in ch if str(x).strip()],
        "page": str(lat.get("download_page") or m.get("download_page") or "").strip(),
        "files": {k: str(v).strip() for k, v in files.items() if str(v).strip()},
    }


def online_check(quiet=False, forced=False):
    """在线检查更新：**展示新版版本号 + 更新了哪些内容 + 下载指引**。

    返回：0＝已是最新（或在线不可用，静默）／1＝有新版本（已展示指引）／2＝未配置在线源。

    联网前置条件（两道都过才发请求）：
      · `forced=True`（使用者命令行显式打 `--check-online`）**或**
        `config.json` 的 `update.check_online_by_default` **显式为 true**；
      · `update.manifest_url` 已填真地址。
    默认配置**不发任何请求**——脚本层"零联网"是靠这条守住的，不是靠自觉。

    quiet=True 时（供 --notice 用）：
      · 已是最新 → 一个字都不输出，退 0；
      · 在线不可用 → 一个字都不输出，退 0（**静默降级，交给本地链**）；
      · 有新版 → 输出完整信息（版本号／内容／下载指引），退 1。
    quiet=False 时（供 --check-online 用）：把"已是最新""在线不可用"也说明白。
    """
    u = _load_update_cfg()
    enabled = _online_enabled(u)
    if not enabled and forced:
        # 使用者显式要求（--check-online）＝这一次的知情同意，只要地址填了就走。
        enabled = bool((u.get("manifest_url") or "").strip())
    if not enabled:
        if not quiet:
            print("[version] 在线检查已关闭（config.json 的 update.manifest_url 未填，"
                  "或 update.check_online_by_default 未显式设为 true）。")
            print("[version] 想启用：把 manifest_url / download_page 填成你自己的在线地址，"
                  "并把 check_online_by_default 设为 true；留空即纯本地模式。")
            print("[version] 只查这一次不改配置：python version.py --check-online")
        return 2
    m = _fetch_manifest(u["manifest_url"])
    if m is None:
        if not quiet:
            print("[version] 在线检查不可用（离线、连不上或清单读取失败）——已静默降级，"
                  "不影响本地使用。")
            print("[version] 可改用纯本地方式：--watch <目录或 zip>。")
        return 0
    lat = _manifest_latest(m)
    if lat is None:
        if not quiet:
            print("[version] 在线清单格式无法识别，已忽略。")
        return 0
    i = identity()
    cur, tgt = vkey(i["version"]), vkey(lat["version"])
    if tgt <= cur:
        if not quiet:
            print("[version] 已是最新版：v%s。" % i["version"])
        return 0
    if lat["version"] in (_load_src_cfg().get("dismissed") or []):
        return 0
    # 清单里的版本号可能带 v 也可能不带，统一成"小写 v + 数字"再展示（防止 vv3.12.0）
    tver = "v" + lat["version"].lstrip("vV")
    # dismissed 里存的是**裸号**（--dismiss 3.12.0），故用裸号比对，避免带不带 v 对不上
    if tver.lstrip("v") in (_load_src_cfg().get("dismissed") or []):
        return 0
    # —— 有新版本：完整展示（版本号 / 更新内容 / 下载指引）——
    print("[version] **有新版可用：当前 v%s → 最新 %s**%s"
          % (i["version"], tver, ("（%s 发布）" % lat["date"]) if lat["date"] else ""))
    if lat["summary"]:
        print("[version] 一句话：%s" % lat["summary"])
    if lat["changes"]:
        print("[version] 新版更新了哪些内容：")
        for c in lat["changes"]:
            print("           · %s" % c)
    print("[version] **要不要更新由你定**——本工具只提示，绝不自动升级，也不会替你下载。")
    print("[version] 本技能不提供历史版本沿革（沿革不随技能分发）；此处只列最新一版要点。")
    print("[version] 愿意更新的话，按三步走：")
    if lat["page"]:
        print("[version]   第一步 · 打开下载页：%s" % lat["page"])
    else:
        print("[version]   第一步 · 打开项目的下载页（见 README／版本清单）")
    for k, label in (("skill", ".skill 包"), ("zip", ".zip 包")):
        if lat["files"].get(k):
            print("[version]   　　　　（%s 直链）：%s" % (label, lat["files"][k]))
    print("[version]   第二步 · 下载到本机（浏览器里下，地址与进度都看得见），记住存到哪了")
    print("[version]   第三步 · 装上去（先预演、确认无误再执行）：")
    print("[version]   　　　python scripts/version.py --upgrade <刚下载的包> --target <安装目录>")
    print("[version]   　　　python scripts/version.py --upgrade <刚下载的包> --target <安装目录> --apply")
    print("[version]   不想再看到这个版本的提醒：--dismiss %s" % tver.lstrip("v"))
    return 1


def _read(path):
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def frontmatter(text):
    """解析 YAML frontmatter 的键值子集（只要标量，列表项忽略）。"""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line.rstrip())
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def vkey(s):
    """版本串 → 可比较元组。认不出返回 (0,0,0)。"""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def vstr(t):
    return ".".join(str(x) for x in t)


# ---------------------------------------------------------------- 更新源登记与提示
def _load_src_cfg():
    """读本机登记的更新源配置；没有或损坏都返回空 dict，不抛异常打扰使用者。"""
    try:
        if not os.path.exists(SOURCE_FILE):
            return {}
        import json
        with io.open(SOURCE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_src_cfg(d):
    import json
    os.makedirs(UPDATE_DIR, exist_ok=True)
    with io.open(SOURCE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def watch(src):
    """登记更新源：先校验它确实像一个技能版本源（能读出 SKILL.md 的版本号），再落盘。

    登记一个认不出来的路径等于自找麻烦（每次 notice 都要报错），故校验不通过就不登记。
    """
    src = os.path.abspath(src)
    kind, sver, sname = source_version(src)
    if sver is None:
        print("[version] 未登记：这里读不到 SKILL.md —— %s" % src)
        print("[version] 更新源应是：解开的技能目录、或未解开的 .zip 发布包。")
        return 2
    d = _load_src_cfg()
    d.update({"path": src, "registered_at": datetime.datetime.now().isoformat(timespec="seconds")})
    d.pop("checked_at", None)
    _save_src_cfg(d)
    print("[version] 已登记更新源：%s（源版本 v%s）" % (src, sver))
    print("[version] 以后直接跑 python scripts/version.py --check 即可比对；"
          "--notice 会静默检查只在有新版本时提示一次。")
    return 0


def unwatch():
    if not os.path.exists(SOURCE_FILE):
        print("[version] 本来就没有登记更新源。")
        return 0
    os.remove(SOURCE_FILE)
    print("[version] 已取消更新源登记，不再提示新版本。")
    return 0


def show_source():
    d = _load_src_cfg()
    if not d.get("path"):
        print("[version] 尚未登记更新源。登记方法：python scripts/version.py --watch <目录或 zip>")
        return 0
    i = identity()
    p = d["path"]
    exists = os.path.exists(p)
    print("[version] 更新源：%s%s" % (p, "" if exists else "　（**当前不可访问**）"))
    if exists:
        kind, sver, _ = source_version(p)
        cur = vkey(i["version"])
        tgt = vkey(sver) if sver else (0, 0, 0)
        if sver and tgt > cur:
            print("[version] 源版本 v%s ＞ 当前 v%s：**有更新可用**（是否升级由使用者决定）"
                  % (sver, i["version"]))
        elif sver and tgt < cur:
            print("[version] 源版本 v%s ＜ 当前 v%s：这个源比本机旧，装它会回退。" % (sver, i["version"]))
        elif sver:
            print("[version] 源版本 v%s ＝ 当前 v%s：已是最新。" % (sver, i["version"]))
    print("[version] 登记时间：%s" % d.get("registered_at", "未知"))
    if d.get("checked_at"):
        print("[version] 上次检查：%s" % d["checked_at"])
    if d.get("dismissed"):
        print("[version] 已忽略的版本：%s（--undismiss 可恢复提醒）" % "、".join(d["dismissed"]))
    return 0


def set_dismiss(ver, undo=False):
    """忽略/恢复某版本的提醒。

    注意：**不要求已登记本地更新源**——2026-10-14 起更新检查默认走在线清单，
    使用者可能从未 `--watch` 过任何本地源，但仍需要"这个版本先别提醒了"。
    故此处只校验版本号形态，不再以"有无本地源"作前置（否则在线路径下无法忽略）。
    """
    if not undo and not re.match(r"^\d+\.\d+\.\d+$", (ver or "").strip()):
        print("[version] --dismiss 需要版本号，如：--dismiss 3.7.0")
        return 2
    d = _load_src_cfg()
    arr = list(d.get("dismissed") or [])
    if undo:
        arr = []
        print("[version] 已恢复所有版本的更新提醒。")
    else:
        ver = ver.strip()
        if ver not in arr:
            arr.append(ver)
        print("[version] 已忽略 v%s 的更新提醒（本机仍可随时手动检查或升级）。" % ver)
    d["dismissed"] = arr
    _save_src_cfg(d)
    return 0


def notice(quiet=True):
    """静默检查有没有新版本：**无新版、无更新源、源不可访问，一律不输出、退 0**。

    设计取向：这个命令是给 AI 每次会话开头悄悄跑一次的，绝不能变成噪音。
    只在"确实有更高版本、且使用者没说过忽略"时才输出，退 1。

    **两条腿走路**（2026-10-14 起）：
      1. **在线优先**：若配置了在线清单（config.json 的 update 段），先联网读它——
         这是**默认**路径，使用者不必先登记任何本地源就能知道有没有新版；
      2. **本地兜底**：在线不可用（离线／被墙／未配置）时，静默降级到本地已登记的更新源。
    两条路都走不通＝一个字都不输出（退 0），使用者完全无感。
    """
    # —— 第一条腿：在线（默认）——
    if quiet:
        rc = online_check(quiet=True)
        if rc == 1:
            return 1                      # 在线明确报告有新版，已展示完整指引
        # rc == 0（已最新／在线不可用）、rc == 2（未配置）→ 继续看本地源
    # —— 第二条腿：本地已登记的源（静默兜底）——
    d = _load_src_cfg()
    p = d.get("path") or ""
    if not p or not os.path.exists(p):
        return 0
    i = identity()
    kind, sver, _ = source_version(p)
    if not sver:
        return 0
    cur, tgt = vkey(i["version"]), vkey(sver)
    if tgt <= cur:
        return 0
    if sver in (d.get("dismissed") or []):
        return 0
    try:
        d["checked_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        _save_src_cfg(d)
    except Exception:
        pass
    print("[version] 检测到新版本：当前 v%s → 可用 v%s（本地更新源：%s）"
          % (i["version"], sver, p))
    print("[version] 这只是一个提示，**不会自动升级**。要看看改了什么："
          "python scripts/version.py --changelog %s" % p)
    print("[version] 要升级（须使用者确认后才可执行）：先用 --upgrade 预演，"
          "确认无误再加 --apply 真正安装。")
    return 1


# ---------------------------------------------------------------- 更新源读取
def _zip_pick(z, tail):
    """在 zip 内挑出指定尾部文件（取路径最短的那个，兼容带顶层目录的包）。"""
    names = [n for n in z.namelist()
             if n.replace("\\", "/").endswith("/" + tail) or n == tail]
    if not names:
        return None
    return sorted(names, key=lambda x: x.count("/"))[0]


def source_text(src, tail):
    """从更新源读取某文件内容。src＝目录 或 zip。返回 (形态, 文本|None)。"""
    if os.path.isdir(src):
        p = os.path.join(src, tail.replace("/", os.sep))
        if os.path.exists(p):
            return "目录", _read(p)
        return "目录", None
    if os.path.isfile(src) and src.lower().endswith(".zip"):
        try:
            z = zipfile.ZipFile(src)
        except Exception as e:
            return "zip", None
        n = _zip_pick(z, tail)
        if not n:
            return "zip", None
        return "zip", z.read(n).decode("utf-8", "ignore")
    return None, None


def source_version(src):
    kind, txt = source_text(src, "SKILL.md")
    if txt is None:
        return kind, None, None
    fm = frontmatter(txt)
    return kind, fm.get("version") or "", fm.get("name") or ""


# ---------------------------------------------------------------- 当前版本
def _count_rules():
    """通用规则库条目数。**直接复用 rule-baseline 的口径**，不另造一套计数规则。"""
    p = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if not os.path.exists(p):
        return 0
    try:
        import importlib
        m = importlib.import_module("rule-baseline") if False else None
        spec = importlib.util.spec_from_file_location(
            "rule_baseline", os.path.join(HERE, "rule-baseline.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return len(m.scan_rules(p))
    except Exception:
        return len(re.findall(r"^\|[^|]*[A-Z]\d+", _read(p), re.M))


def identity():
    t = _read(SKILL_PATH)
    fm = frontmatter(t)
    scripts = sorted(glob.glob(os.path.join(HERE, "*.py")))
    integ = os.path.join(HERE, ".integrity.json")
    n_int, gen = 0, ""
    if os.path.exists(integ):
        try:
            import json
            d = json.loads(_read(integ))
            n_int = len(d.get("sha256") or {}) or int(d.get("count") or 0)
            gen = datetime.datetime.fromtimestamp(
                os.path.getmtime(integ)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    ind = os.path.join(ROOT, "industries")
    # 平铺结构：行业库为 industries/<slug>-rules.md（不再有子目录）
    n_ind = len([f for f in os.listdir(ind)
                 if re.match(r"^[A-Za-z0-9_]+-rules\.md$", f)
                 and not f.startswith("_template")]) if os.path.isdir(ind) else 0
    return {
        "name": fm.get("name") or "",
        "version": fm.get("version") or "",
        "license": fm.get("license") or "",
        "author": fm.get("author") or "",
        "scripts": len(scripts),
        "integrity": n_int,
        "integrity_time": gen,
        "rules": _count_rules(),
        "industries": n_ind,
        "skill_mtime": datetime.datetime.fromtimestamp(
            os.path.getmtime(SKILL_PATH)).strftime("%Y-%m-%d %H:%M") if os.path.exists(SKILL_PATH) else "",
    }


def show():
    i = identity()
    print("[version] 位置：%s" % ROOT)
    print("[version] 名称：%s" % i["name"])
    print("[version] 版本：v%s" % i["version"])
    if i["author"]:
        print("[version] 作者：%s" % i["author"])
    print("[version] 许可：%s" % i["license"])
    print("[version] 规模：脚本 %d 个（指纹已签 %d 个，%s）　通用规则 %d 条　行业库 %d 个"
          % (i["scripts"], i["integrity"], i["integrity_time"] or "未签名", i["rules"], i["industries"]))
    print("[version] 入口更新时间：%s" % i["skill_mtime"])
    print("[version] 核对更新：python scripts/version.py --check <更新源目录或 zip>")
    return 0


# ---------------------------------------------------------------- 更新检测
def check(src):
    i = identity()
    cur = vkey(i["version"])
    kind, sver, sname = source_version(src)
    if sver is None:
        print("[version] 未在更新源里找到 SKILL.md：%s（%s）" % (src, kind or "路径不存在"))
        print("[version] 更新源应是：解开的技能目录、或未解开的 .zip 发布包。")
        return 2
    tgt = vkey(sver)
    print("[version] 当前：v%s　更新源：v%s（%s）" % (i["version"], sver, kind))
    if tgt == cur:
        print("[version] 已是最新版，无需升级。")
        return 0
    if tgt > cur:
        print("[version] 有更新：v%s → v%s" % (i["version"], sver))
        print("[version] 先看改了什么：python scripts/version.py --changelog %s" % src)
        print("[version] 再预演升级：python scripts/version.py --upgrade %s --target <安装目录>" % src)
        return 0
    print("[version] 更新源版本 **低于** 当前版本（v%s < v%s）——确认是否拿错了包；"
          "继续安装会**回退**功能。" % (sver, i["version"]))
    return 3


def changelog(src, limit=40):
    i = identity()
    cur = vkey(i["version"])
    kind, sver, _ = source_version(src)
    if sver is None:
        print("[version] 更新源里没有 SKILL.md：%s" % src)
        return 2
    tgt = vkey(sver)
    # 沿革明细**不随发布包**（v3.26.2 起 VERSION.md 也移出包）：发布包源通常两样都没有。
    # 仍先看项目侧 CHANGELOG.md，再回退 VERSION.md——只在「源是开发目录」时才有内容，
    # 供维护侧升级时自查；对普通使用者，这里会明确告知「不提供」，而不是报错。
    _, txt = source_text(src, "CHANGELOG.md")
    src_of_rows = "CHANGELOG.md（项目侧明细）"
    if not txt:
        _, txt = source_text(src, "VERSION.md")
        src_of_rows = "VERSION.md（维护侧沿革）"
    if not txt:
        print("[version] 该更新源不含沿革明细（%s）——发布包按设计不带历史版本信息。" % (kind or src))
        print("[version] 只能确认版本号新旧：当前 v%s，源 %s。" % (i["version"], sver))
        print("[version] 升级前想看「这版改了什么」，以源包内 version.json 的 latest.changes 为准。")
        return 0
    rows = []
    for line in txt.splitlines():
        st = line.strip()
        m = re.match(r"^(#{2,6})\s*V?(\d+\.\d+\.\d+)\s*(.*)$", st)
        if not m:                      # 回退：VERSION.md 的表格行「| **V3.8.5** | 日期 | 摘要 |」
            m = re.match(r"^\|\s*\**\s*V?(\d+(?:\.\d+){1,2})\s*\**\s*\|(.*)$", st)
            if m:
                ver = m.group(1)
                if ver.count(".") == 1:      # 「V3.1」这类两位号补齐成三位，便于比较
                    ver += ".0"
                cells = [c.strip() for c in m.group(2).split("|")]
                # 行尾的「|」会切出一个空串，摘要要取**最后一个非空单元格**
                tail = next((c for c in reversed(cells) if c), "")
                rows.append((vkey(ver), ver, tail.strip().strip("*")))
            continue
        rows.append((vkey(m.group(2)), m.group(2), m.group(3).strip()))
    lo, hi = (cur, tgt) if tgt >= cur else (tgt, cur)
    hit = [r for r in rows if lo < r[0] <= hi]
    if not hit and tgt == cur:
        print("[version] 当前 v%s 与源版本相同，无区间沿革。" % i["version"])
        return 0
    print("[version] 区间沿革 v%s → v%s（%d 个版本条目，取自 %s）："
          % (vstr(lo), vstr(hi), len(hit), src_of_rows))
    if not hit:
        print("    （CHANGELOG 中未找到该区间的版本标题，可能两侧版本同属于一个大版本块）")
    for _, v, tail in hit[:limit]:
        print("    V%-8s %s" % (v, tail[:96]))
    return 0


# ---------------------------------------------------------------- 升级
def _walk_files(root):
    out = []
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d not in ("__pycache__", ".git")]
        for f in fs:
            if f.endswith((".pyc", ".DS_Store")):
                continue
            if f.startswith("_") and f.endswith(".log.txt"):
                continue
            p = os.path.join(r, f)
            out.append(os.path.relpath(p, root).replace("\\", "/"))
    return sorted(out)


def _prepare_src(src):
    """把更新源整理成一个目录；zip 则解到临时目录。返回 (目录, 是否临时)。"""
    if os.path.isdir(src):
        return src, False
    if os.path.isfile(src) and src.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="dcr-up-")
        zipfile.ZipFile(src).extractall(tmp)
        # zip 可能带一层顶层目录：若只有一个子目录且其中有 SKILL.md，则下沉
        subs = [d for d in os.listdir(tmp)
                if os.path.isdir(os.path.join(tmp, d))]
        if len(subs) == 1 and not os.path.exists(os.path.join(tmp, "SKILL.md")):
            inner = os.path.join(tmp, subs[0])
            if os.path.exists(os.path.join(inner, "SKILL.md")):
                return inner, True
        return tmp, True
    return None, False


def _protected(rel, overwrite_cfg):
    parts = rel.split("/")
    if parts[0] in NEVER_OVERWRITE:
        return "private（永不覆盖）"
    if rel == KEEP_CONFIG and not overwrite_cfg:
        return "config.json（本机配置，需 --overwrite-config 才覆盖）"
    return ""


def upgrade(src_dir, target, apply=False, overwrite_cfg=False):
    if not os.path.isdir(target):
        print("[version] 安装目录不存在：%s" % target)
        return 2
    src, tmp = _prepare_src(src_dir)
    if src is None:
        print("[version] 更新源不可用：%s（应为目录或 .zip）" % src_dir)
        return 2

    s_files = _walk_files(src)
    t_files = _walk_files(target)
    s_set = set(s_files)
    over = [f for f in s_files if f in set(t_files)]
    add = [f for f in s_files if f not in set(t_files)]
    keep = [f for f in t_files if f not in s_set]
    prot = [(f, _protected(f, overwrite_cfg)) for f in over + add if _protected(f, overwrite_cfg)]

    cur_ver = identity()["version"]
    print("[version] 源：%s" % src_dir)
    print("[version] 目标：%s" % target)
    print("[version] 变更：覆盖 %d　新增 %d　目标独有（保留）%d" % (len(over), len(add), len(keep)))
    if prot:
        print("[version] 受保护（不覆盖）：")
        for f, why in prot[:12]:
            print("    %-46s %s" % (f[:46], why))
    for f in add[:12]:
        print("    [新增] %s" % f)
    for f in keep[:12]:
        print("    [保留] %s" % f)
    if len(keep) > 12:
        print("    …… 其余保留项 %d 个（目标独有，不会删除）" % (len(keep) - 12))

    if not apply:
        print("[version] 以上是预演（dry-run），未改动任何文件。")
        print("[version] 确认无误后加 --apply 执行；备份会写在安装目录同级。")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    bak = "%s_bak-v%s-%s" % (target.rstrip("\\/"), cur_ver.replace(".", ""), stamp)
    print("[version] 备份中：%s" % bak)
    n = 0
    for r, ds, fs in os.walk(target):
        ds[:] = [d for d in ds if d not in ("__pycache__",)]
        rel = os.path.relpath(r, target)
        dst = os.path.join(bak, rel) if rel != "." else bak
        os.makedirs(dst, exist_ok=True)
        for f in fs:
            shutil.copy2(os.path.join(r, f), os.path.join(dst, f))
            n += 1
    print("[version] 已备份 %d 个文件。" % n)

    done, skipped = 0, 0
    for rel in over + add:
        if _protected(rel, overwrite_cfg):
            skipped += 1
            continue
        sp = os.path.join(src, rel.replace("/", os.sep))
        tp = os.path.join(target, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        shutil.copy2(sp, tp)
        done += 1
    print("[version] 已写入 %d 个文件（受保护跳过 %d 个）。" % (done, skipped))
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    print("[version] 升级完成。接下来跑：python scripts/check.py && python scripts/smoke-test.py --fast")
    print("[version] 若需重新签名（脚本有改动时）：python scripts/check.py --sign")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="版本身份证 · 更新检测 · 升级（检查可联网、下载升级包由使用者手动）")
    ap.add_argument("--check", metavar="源", nargs="?", const="__registered__", default=None,
                    help="与更新源比对版本（目录或 zip；省略源时用已登记的更新源）")
    ap.add_argument("--changelog", metavar="源", nargs="?", const="__registered__", default=None,
                    help="摘出当前版本到源版本之间的沿革条目")
    ap.add_argument("--upgrade", metavar="源", help="升级（配合 --target；默认预演，加 --apply 执行）")
    ap.add_argument("--target", metavar="目录", help="待升级的安装目录")
    ap.add_argument("--apply", action="store_true", help="真正执行升级（先备份）")
    ap.add_argument("--overwrite-config", action="store_true", help="连 config.json 一起覆盖（默认保留）")
    ap.add_argument("--watch", metavar="源", help="登记一个更新源（本机记住路径，供以后 --check/--notice 使用）")
    ap.add_argument("--unwatch", action="store_true", help="取消更新源登记")
    ap.add_argument("--source", action="store_true", help="显示当前登记的更新源与版本关系")
    ap.add_argument("--notice", action="store_true",
                    help="静默检查是否有新版本（无新版不输出、退 0；有新版输出一行、退 1）")
    ap.add_argument("--check-online", action="store_true",
                    help="显式在线检查更新（显示最新版本号、更新内容与下载指引；只读公开清单）")
    ap.add_argument("--dismiss", metavar="版本", help="忽略某版本的更新提醒（如 --dismiss 3.7.0）")
    ap.add_argument("--undismiss", action="store_true", help="恢复所有版本的更新提醒")
    a = ap.parse_args()

    def _resolve(v):
        """省略源时取已登记的那个；取不到给出可执行的下一步。"""
        if v != "__registered__":
            return v
        d = _load_src_cfg()
        p = d.get("path")
        if not p:
            print("[version] 尚未登记更新源。先登记：python scripts/version.py --watch <目录或 zip>")
            return None
        if not os.path.exists(p):
            print("[version] 已登记的更新源当前不可访问：%s" % p)
            print("[version] 换一个：--watch <新源>；或取消登记：--unwatch")
            return None
        return p

    if a.watch:
        return watch(a.watch)
    if a.unwatch:
        return unwatch()
    if a.source:
        return show_source()
    if a.notice:
        return notice()
    if a.check_online:
        return online_check(quiet=False, forced=True)
    if a.dismiss:
        return set_dismiss(a.dismiss)
    if a.undismiss:
        return set_dismiss(None, undo=True)
    if a.check:
        src = _resolve(a.check)
        return check(src) if src else 2
    if a.changelog:
        src = _resolve(a.changelog)
        return changelog(src) if src else 2
    if a.upgrade:
        if not a.target:
            print("[version] --upgrade 需要同时给 --target <安装目录>。")
            return 2
        src = _resolve(a.upgrade)
        return upgrade(src, a.target, a.apply, a.overwrite_config) if src else 2
    return show()


if __name__ == "__main__":
    _sys.exit(main())
