#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L3  门禁自检类：文件内出现网络关键字，但自身不发起联网
"""
文档合规审查助手AI合同 · 结构校验与环境自检（Python 版）
==================================================================
替代原 `check.ps1`：**纯 Python 实现，无需 PowerShell、不绕过任何执行策略**，
跨平台（Windows / macOS / Linux）一致运行，消除「依赖执行策略绕过参数运行脚本」带来的绕过面。

用法：
  python check.py                    结构 + 字段 + 头标 + 去企业化 + 规则ID + 配置 + 安全项 自检
  python check.py --sign             生成/刷新脚本完整性指纹（scripts/.integrity.json）
  python check.py --verify           仅校验脚本指纹是否与记录一致（防篡改）
  python check.py --strict           指纹不一致时视为错误（默认仅告警）
  python check.py --clean            清理 __pycache__ / *.pyc（缓存残留）
  python check.py --quiet            只输出结论行

退出码：0=通过（可能有告警）；1=存在错误。
"""
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
import os
import re
import json
import glob
import subprocess
import sys
import hashlib
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INTEGRITY = os.path.join(HERE, ".integrity.json")

ERRS = []
WARNS = []
INFOS = []


def err(m):
    ERRS.append(m)


def warn(m):
    WARNS.append(m)


def info(m):
    INFOS.append(m)


def _load_forbidden():
    """从外部文件加载"企业专属词"表。

    设计要点：**词表不进脚本源码、不进发布包**——避免检查器自身泄露企业名
    （检查器若把企业名写死，"去企业化"检查本身就制造了泄露）。
    路径：`private/deidentify-words.txt`（每行一个词，`#` 开头为注释）；
    该目录默认被 `pack.py` 排除，故不会随发布包外流。文件不存在时返回空表（跳过该项检查）。
    """
    p = os.path.join(ROOT, "private", "deidentify-words.txt")
    if not os.path.exists(p):
        return []
    words = []
    for line in _read(p).splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            words.append(s)
    return words

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "安装使用教程.md",
    "LICENSE.md",
    "VERSION.md",
    os.path.join("scripts", "TONE.md"),   # 感谢语参考：藏于脚本目录，不入使用者的视线
    "文档合规审查助手AI合同提示词版.md",
    os.path.join("core", "01-general-risk-rules.md"),
    # 按需加载的三份专项口径（SKILL.md 只留索引段指向它们，缺哪一个都是断链）
    "permissions-and-libraries.md", "drafting-guide.md", "template-guide.md",
]

INDUSTRY_KEYS = ["industry", "slug", "display_name", "common_roles", "inherits", "core_version"]
# 通用库规则 ID 形态。组字母须覆盖 core/01 当前全部 21 个组：
# A(标的与定义) B(通用条款完备性) C D E F G H I J K(发票税务付款) L M N P Q S T V W X(逻辑一致性)
# 口径必须与 rule-baseline.py、sample-baseline.py 完全一致（check.py 的
# 「三脚本白名单一致性」项会常驻校验，防止新增组后某一处漏改导致计数漂移）。
CORE_ID_GROUPS = "PVLGICDHEQWMNKJSTFXBA"
CORE_ID_RE = re.compile(r"\|\s*([%s]\d+)\s*\|" % CORE_ID_GROUPS)
ASSET_REF_RE = re.compile(r"!\[[^\]]*\]\((?:\./)?(assets/[^)\s\"']+)\)")


# ---------------------------------------------------------------- 校验项
def check_required_files():
    for f in REQUIRED_FILES:
        if not os.path.exists(os.path.join(ROOT, f)):
            err("缺少文件: %s" % f)


def _industry_slugs():
    """行业库 slug 列表。

    **扁平化结构（V3.3.0 起）**：行业库为 `industries/<slug>-rules.md` 与
    `industries/<slug>-meta.md` 两个平铺文件，不再有 `industries/<slug>/` 子目录
    ——平台解析技能包时只接受「根目录/二级目录/文件」两级，三级目录直接拒绝。
    """
    ind = os.path.join(ROOT, "industries")
    if not os.path.isdir(ind):
        return []
    out = []
    for f in sorted(os.listdir(ind)):
        m = re.match(r"^([A-Za-z0-9_]+)-rules\.md$", f)
        if m and m.group(1) != "_template":
            out.append(m.group(1))
    return out


def check_industries():
    ind = os.path.join(ROOT, "industries")
    if not os.path.isdir(ind):
        warn("未发现 industries/ 行业库目录")
        return
    # 平台硬约束：包内至多两级目录，三级（如 industries/<slug>/rules.md）会被拒收
    stray = [d for d in sorted(os.listdir(ind)) if os.path.isdir(os.path.join(ind, d))]
    if stray:
        err("industries/ 下仍有子目录（包内须「根/二级目录/文件」，三级会致平台解析失败）：%s"
            % ", ".join(stray))
    pkgs = _industry_slugs()
    for slug in pkgs:
        for rf in ("%s-meta.md" % slug, "%s-rules.md" % slug):
            if not os.path.exists(os.path.join(ind, rf)):
                err("[%s] 缺少 %s" % (slug, rf))
        meta = os.path.join(ind, "%s-meta.md" % slug)
        if os.path.exists(meta):
            txt = _read(meta)
            for k in INDUSTRY_KEYS:
                if not re.search(r"(?m)^\s*%s\s*:" % k, txt):
                    err("[%s] meta 缺少字段: %s" % (slug, k))
    info("行业包数: %d（%s）" % (len(pkgs), ", ".join(pkgs) if pkgs else "无"))


def check_assets():
    """头标资源：文档中引用的 assets/ 文件必须真实存在。

    动机：`assets/` 是「发布用头标」，README/SKILL 顶部直接引用它；
    一旦资源缺失（漏打包、改名、删图），发布包里就是一张裂图——
    而 .md 渲染不会报错，肉眼也未必在打包环节发现，故在此机器校验。
    """
    adir = os.path.join(ROOT, "assets")
    refs = {}
    for fn in ("SKILL.md", "README.md", "安装使用教程.md", "LICENSE.md", "VERSION.md",
               os.path.join("scripts", "TONE.md"), "文档合规审查助手AI合同提示词版.md", "SECURITY.md"):
        p = os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        for m in ASSET_REF_RE.finditer(_read(p)):
            refs.setdefault(m.group(1), []).append(fn)
    missing = [a for a in refs if not os.path.exists(os.path.join(ROOT, a.replace("/", os.sep)))]
    for a in missing:
        err("文档引用了不存在的资源 %s（引用自 %s）" % (a, ", ".join(refs[a])))
    if refs and not missing:
        info("头标: 文档引用 %d 个 assets 资源，均存在" % len(refs))
    elif not refs:
        info("头标: 文档未引用 assets/ 资源")
    if os.path.isdir(adir):
        n = len([f for f in os.listdir(adir) if os.path.isfile(os.path.join(adir, f))])
        info("assets/: %d 个文件" % n)
    else:
        warn("未发现 assets/ 目录（发布用头标缺失）")


def check_deenterprise():
    """去企业化：.md 文件中不得残留企业专属词（样例/归档/发布包除外）。

    词表来自 `private/deidentify-words.txt`（外部文件，默认不随包分发）。
    未配置词表时跳过本项检查——这是正常状态，不视为缺陷。
    """
    words = _load_forbidden()
    if not words:
        info("去企业化: 未配置专属词表（private/deidentify-words.txt 缺失或为空），已跳过")
        return
    hits = 0
    for p in _walk(ROOT, exts=(".md",)):
        rel = os.path.relpath(p, ROOT)
        if re.search(r"[\\/](samples|_归档|_分发包|测试合同)[\\/]", rel) or rel.startswith("_归档"):
            continue
        txt = _read(p)
        for w in words:
            if w in txt:
                err("发现企业专属词 %r 于 %s（词表：private/deidentify-words.txt）" % (w, rel))
                hits += 1
    if not hits:
        info("去企业化: 未发现企业专属词（词表 %d 条）" % len(words))


def check_rule_ids():
    core = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if not os.path.exists(core):
        return
    ids = CORE_ID_RE.findall(_read(core))
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        warn("core 规则ID重复: %s" % ",".join(dup))
    info("core 规则数: %d" % len(ids))
    ind = os.path.join(ROOT, "industries")
    if os.path.isdir(ind):
        total = 0
        for slug in _industry_slugs():
            rf = os.path.join(ind, "%s-rules.md" % slug)
            if os.path.exists(rf):
                n = len(re.findall(r"[A-Z]{2}-\d+", _read(rf)))
                total += n
        if total:
            info("行业规则条目: %d" % total)


def check_id_group_whitelist():
    """规则ID组字母白名单：(1)三脚本彼此一致 (2)覆盖 core/01 实际用到的全部组。
    背景：新增规则组（如 V3.8.0 的 K 组、既有但漏管的 A/B/X 组）若某脚本漏改，
    会导致规则计数与基线条账静默缺项。此处常驻校验，堵住该漂移面。"""
    scripts = ["check.py", "rule-baseline.py", "sample-baseline.py"]
    found = {}
    for s in scripts:
        p = os.path.join(ROOT, "scripts", s)
        if not os.path.exists(p):
            continue
        m = re.search(r'^CORE_ID_GROUPS\s*=\s*"([A-Z]+)"', _read(p), re.M)
        if not m:
            err("%s 未定义 CORE_ID_GROUPS（三脚本须统一同一口径）" % s)
            continue
        found[s] = "".join(sorted(m.group(1)))
    if not found:
        return
    if len(set(found.values())) > 1:
        for s in sorted(found):
            err("规则ID组字母白名单不一致：%s = %s" % (s, found[s]))
        return
    wl = set(next(iter(found.values())))
    core = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if not os.path.exists(core):
        return
    real = set(re.findall(r"\|\s*([A-Z])\d+\s*\|", _read(core)))
    if real - wl:
        err("core/01 使用了白名单外的组字母：%s（须补进 CORE_ID_GROUPS）"
            % ",".join(sorted(real - wl)))
    elif wl - real:
        info("规则ID组字母白名单：三脚本一致（%d 组），预留未用组 %s"
             % (len(wl), ",".join(sorted(wl - real))))
    else:
        info("规则ID组字母白名单：三脚本一致，%d 组覆盖完整" % len(wl))


def check_rule_baseline():
    """规则库回归基线：与 core/_rules-baseline.json 比对（检出规则增删改与评级变化）。"""
    p = os.path.join(ROOT, "core", "_rules-baseline.json")
    if not os.path.exists(p):
        info("规则基线：未生成（python scripts/rule-baseline.py --update 建立）")
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_rule_baseline",
                                                      os.path.join(HERE, "rule-baseline.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        meta = json.loads(_read(p))
        # 三层都要传：规则条目 / 行业库文件 / 生效日与最近修订元数据
        d = m.diff((meta.get("rules") or {}, meta.get("files") or {}, meta.get("meta") or {}),
                   m.collect())
        n = sum(len(v) for v in d.values())
        if n:
            warn("规则基线与当前规则库有 %d 处差异（须人工确认是否预期内）："
                 "python scripts/rule-baseline.py" % n)
        else:
            info("规则基线一致（通用库 %d 条）" % meta.get("total", 0))
    except Exception as e:
        warn("规则基线比对失败：%s" % e)


def check_config():
    """config.json 合法性与可移植性。"""
    cfg = os.path.join(HERE, "config.json")
    if not os.path.exists(cfg):
        info("config.json 不存在（将全用内置默认值）")
        return
    try:
        data = json.loads(_read(cfg))
    except Exception as e:
        err("config.json 解析失败: %s" % e)
        return
    try:
        import _config as _cm
    except Exception:
        _cm = None
    # 工具路径：留空＝按 PATH 探测（不是问题）；填了不在本机但 PATH 能兜住＝只提示；
    # 两者都没有＝才算缺失。这里反映 config.json ＋ config.local.json 叠加后的结果。
    tools = ((_cm.load() if _cm else {}) or {}).get("tools") or {}
    custom, via_path, absent = [], [], []
    for k, v in tools.items():
        v = (v or "").strip()
        if not v:
            continue
        if os.path.exists(v):
            custom.append(k)
        elif _cm and _cm.tool_available(_cm.load(), k):
            via_path.append(k)
        else:
            absent.append("%s=%s" % (k, v))
    if custom:
        info("工具路径: %d 项按自定义路径生效（%s）" % (len(custom), "、".join(sorted(custom))))
    if via_path:
        info("工具路径: %d 项配置路径在本机不存在，已按 PATH 自动探测（%s）——功能不受影响"
             % (len(via_path), "、".join(sorted(via_path))))
    if absent:
        warn("以下工具既无有效路径、PATH 中也找不到（相应文档类型将无法解析）: %s —— 跑"
             " detect-tools.py --install-guide 查看安装命令" % "; ".join(sorted(absent)))
    if not (custom or via_path or absent):
        info("工具路径: 全部留空，按 PATH 自动探测（自定义可选，不作强制）")
    base = ((data.get("workdir") or {}).get("base_dir") or "").strip()
    if base and base.lower() not in ("auto", "autodetect", "自动"):
        parent = os.path.dirname(base)
        if parent and not os.path.exists(parent):
            warn("base_dir 的上级目录/盘符不存在（运行时自动顺延到下一候选）: %s" % base)
    else:
        info("base_dir=auto：工作根目录按候选链自动探测，无 D 盘也能落地")
    try:
        import _config as _cm
        _b, _src = _cm.resolve_base(_cm.load(), create=False)
        info("工作根目录解析结果：%s [来源：%s]" % (_b, _src))
    except Exception as e:
        warn("工作根目录解析失败：%s" % e)
    _check_online_gate(data)


# ── 安全引擎：联网分四档（DEV-RULES.md 第 26 条）──────────────────────────
# 口径：**按「数据出域」分档，不按「有没有 urllib」一刀切**。
# 真源是**每个脚本文件头那行 `# net-tier: Ln`**——不在本文件另立登记表。
# 同一事实两处写必漂（第 12 条）：中央登记表一定与代码分家，写在代码里则改档必须动那个文件。
# 本检查器只做三件事：**读标记 → 与实测比对 → 与 SECURITY.md 双向咬合**。
NET_TIER_RE = re.compile(r"^#[ \t]*net-tier:[ \t]*(L[0-3])\b", re.M)
# 行首匹配真正的 import 语句；检查器自己持有的"关键字清单"是行中间的字符串，不会自指命中。
NET_IMPORT_RE = re.compile(
    r"^[ \t]*(?:import|from)[ \t]+(?:urllib|requests|socket|http\.client|aiohttp|httpx"
    r"|smtplib|ftplib|xmlrpc)\b", re.M)
# 联网动作（含间接）：自己不 import 网络库、但调用在线档模块的网络函数，同样算联网路径。
NET_CALL_RE = re.compile(
    r"urlopen\(|requests\.(?:get|post|put)\(|socket\.(?:socket|create_connection)\("
    r"|(?:PARSE|_PARSE|parse)\.fetch\(", re.M)
TIER_MEANING = {
    "L0": "接触文档内容 → 绝对离线（零网络库）",
    "L1": "在线只读公开信息 → 须可关、离线静默降级",
    "L2": "不联网就用不成 → 须显式调用、离线明示降级",
    "L3": "门禁自检类 → 自身不发起联网",
}


def _net_tiers():
    """读全部脚本的档位自标 → {文件名: 档位}（缺失为 None）。

    **这里必须扫全目录，不能用 `_script_files()`**——后者为算指纹而把 `check.py` 自身排除在外，
    结果守门人自己成了唯一没定档的脚本（v3.23.2 首次跑门禁即被本函数当场抓出）。
    **检查器最容易被自己漏掉**，故凡"全量清点"类检查，一律直接列举目录，不复用带豁免的辅助函数。
    """
    out = {}
    for p in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        m = NET_TIER_RE.search(_read(p))
        out[os.path.basename(p)] = m.group(1) if m else None
    return out


def _doc_net_tiers():
    """读 SECURITY.md 里**可见的**档位名单 → {档位: [文件名]}；缺行返回 None。

    为什么用"可见代码块"而不藏进 HTML 注释：给客户看的名单必须看得见，
    而藏起来的机读块一旦与可见文字分家就无人发现（第 12 条的典型形态）。
    故**一处写、两边用**——代码块既给人看，也给本函数解析。
    """
    p = os.path.join(os.path.dirname(HERE), "SECURITY.md")
    if not os.path.exists(p):
        return None
    out = {}
    for line in _read(p).splitlines():
        mm = re.match(r"[ \t]*(L[0-3])[ \t]*:[ \t]*([A-Za-z0-9_.\- ]+)$", line)
        if mm and all(x.endswith(".py") for x in mm.group(2).split()):
            out[mm.group(1)] = mm.group(2).split()
    return out or None


def check_net_tiers():
    """安全引擎门禁：联网按档，档位在代码里、机读、与文档咬合。

    为什么不再写「脚本全部不联网」（这是 v3.23.2 修正的一刀切）：
    那句话把**手段当成了目的**。红线是「使用者的文档不出域」，不是「有没有 urllib」——
    一刀切禁联网会连「法规库失效巡检」一起废掉，而它不联网根本做不成，
    恰是产品最值钱的部分。故分四档，并且：
      · **L0 仍然一刀切**，但切在「**接触文档**」上，不切在「联网」上——这是唯一该切的地方；
      · **L2 承认「不联网就用不成」**，代价换到别处补：须显式调用、离线须明示降级；
      · 分档若只写在文档里就成了漂亮话，故**档位写在代码里**，且文档名单与代码**双向比对**——
        任一侧偷改当场报错（25.2 的事故形态：文档写一套、代码做一套，无人比对）。
    """
    tiers = _net_tiers()
    if not tiers:
        err("未读到任何脚本——安全引擎无从定档")
        return
    no_tag = sorted(n for n, t in tiers.items() if t is None)
    if no_tag:
        err("以下脚本缺 `# net-tier:` 档位自标：%s；新增脚本须**先定档再入库**（第 26 条）"
            % "、".join(no_tag))
        tiers = {n: t for n, t in tiers.items() if t}
    bad = sorted("%s=%s" % (n, t) for n, t in tiers.items() if t not in TIER_MEANING)
    if bad:
        err("档位取值非法（只许 L0—L3）：%s" % "、".join(bad))
        return

    imp_hit, call_hit = set(), set()
    for n in tiers:
        txt = _read(os.path.join(HERE, n))
        if NET_IMPORT_RE.search(txt):
            imp_hit.add(n)
        if NET_CALL_RE.search(txt):
            call_hit.add(n)
    by = lambda t: sorted(n for n, v in tiers.items() if v == t)  # noqa: E731

    # ① L0（接触文档）：**唯一保留的一刀切**——零网络库
    bad_l0 = [n for n in by("L0") if n in imp_hit]
    if bad_l0:
        err("L0 档（接触文档内容）脚本含网络库 import：%s。文档一经手就不得有任何出网路径——"
            "要么删掉，要么先改档并在 SECURITY.md 写明理由（第 26 条）" % "、".join(bad_l0))
        return
    # ② L1/L2：标了"会联网"就得真有联网路径——**档位不许是空头标签**
    online = by("L1") + by("L2")
    dead = [n for n in online if n not in (imp_hit | call_hit)]
    if dead:
        err("标为在线档却找不到任何联网路径：%s——档位不能是空头标签，要么接上实现，要么改回 L0"
            % "、".join(dead))
        return
    # ③ L3：门禁自检类只许持有"网络关键字清单"，不许真 import
    bad_l3 = [n for n in by("L3") if n in imp_hit]
    if bad_l3:
        err("L3 档（门禁自检类）不该真 import 网络库：%s；它只应持有用于检查别人的关键字清单"
            % "、".join(bad_l3))
        return
    # ④ 与 SECURITY.md 双向咬合（文档一套代码一套，正是 25.2 的事故形态）
    doc = _doc_net_tiers()
    if doc is None:
        err("SECURITY.md 缺机读档位块（NET-TIERS）——名单无法与代码比对，改一处就分家（25.2）")
        return
    for t in ("L0", "L1", "L2", "L3"):
        a, b = by(t), sorted(doc.get(t) or [])
        if a != b:
            err("SECURITY.md 的 %s 档名单与脚本自标不一致：文档 %s／代码 %s；两处须同步"
                % (t, b, a))
            return
    info("安全引擎：联网分四档——L0 %d 个（接触文档，零网络库）／L1 %d 个（在线只读公开信息，可关）"
         "／L2 %d 个（不联网就用不成，须显式调用）／L3 %d 个（门禁自检，自身不联网）；"
         "名单与 SECURITY.md 双向一致" % (len(by("L0")), len(by("L1")), len(by("L2")), len(by("L3"))))


# 真正的"带 shell 的调用"，而非 `shell=True` 这个子串（后者会让检查器自指命中）。
SHELL_TRUE_RE = re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True")

# ── 安全机制登记表（铁律第 27 条）────────────────────────────────────────
# 为什么要有这张表：安全承诺原先散落在 SECURITY.md 的七条承诺／八不／九项措施里，
# 而 `check_security()` 实际只查了三项（私有库／映射表目录／缓存）——
# **多数承诺是"写在文档里"，没有一行代码在盯**。文档写一套、代码做一套且无人比对，
# 正是 25.2 的事故形态；安全承诺尤其经不起这个，因为它是客户据以决定"敢不敢把涉密合同交给你"的依据。
#
# 本表的口径只有一条：**登记表不复制实现，只登记"机制 → 判据 → 落点"**（第 12 条）。
#   · 判据一律**指向已经在跑的那段代码**（同一常量、同一函数），故实现删了判据当场红；
#   · 已有独立段落盯着的（缓存／防篡改／去企业化）不重复跑，只登记**锚点**并验锚点还在位；
#   · 行为类判据（如"不改原件"）落在冒烟，本表同样只记落点并验在位——
#     改名不同步会当场报错，这正是 26.5.5 那条"按字符串匹配的用例视同引用了实现"的用法。


def _sec_doc_no_net():
    """数据层：文档不出网——接触文档的 L0 档零网络库（与 26.5.2 同一判据，不另写一套）"""
    tiers = _net_tiers()
    l0 = [n for n, v in tiers.items() if v == "L0"]
    bad = [n for n in l0 if NET_IMPORT_RE.search(_read(os.path.join(HERE, n)))]
    return (not bad,
            "L0 档 %d 个脚本零网络库" % len(l0) if not bad else "越界 %s" % ", ".join(bad))


def _sec_map_isolated():
    """数据层：映射表落**本机隔离目录**，且不落在技能目录里（否则会被整目录打包带走）"""
    t = _read(os.path.join(HERE, "desensitize.py"))
    m = re.search(r"^MAP_DIR\s*=.*$", t, re.M)
    if not m:
        return (False, "desensitize.py 里找不到 MAP_DIR 常量（隔离目录的实现被删）")
    expr = m.group(0)
    ok = ("expanduser" in expr) and ("HERE" not in expr)
    return (ok, "默认落本机隔离目录 %s" % expr.strip() if ok
            else "MAP_DIR 未走 expanduser 或落在技能目录内：%s" % expr.strip())


def _sec_private_not_packed():
    """数据层：私有库默认不打进发布包"""
    t = _read(os.path.join(HERE, "pack.py"))
    ok = bool(re.search(r"def build\([^)]*include_private\s*=\s*False", t))
    return (ok, "pack.py 的 build() 默认 include_private=False"
            if ok else "build() 的默认参数变了——私有库可能被默认打包")


def _sec_online_off():
    """数据层：查更新默认不发请求（可联网 ≠ 会自动联网）"""
    try:
        u = (json.loads(_read(os.path.join(HERE, "config.json"))).get("update") or {})
    except Exception as e:
        return (False, "config.json 读不出来：%r" % (e,))
    ok = u.get("check_online_by_default") is False
    return (ok, "出厂 check_online_by_default=false" if ok
            else "实为 %r——默认会自己发请求" % u.get("check_online_by_default"))


def _sec_original_intact():
    """产物层：原件不改——行为判据落在冒烟（跑完比 sha256），本表只验落点还在位"""
    t = _read(os.path.join(HERE, "smoke-test.py"))
    ok = ("处理前后源文档 sha256 不变" in t) and ("hashlib.sha256" in t)
    return (ok, "冒烟行为判据在位（跑完比一次 sha256）"
            if ok else "冒烟里的原件判据被删或改名——「不改原件」退回成一句无人验的话")


def _sec_output_isolated():
    """产物层：交付物按文档名分目录（多客户不平铺混放）"""
    try:
        o = (json.loads(_read(os.path.join(HERE, "config.json"))).get("output") or {})
    except Exception as e:
        return (False, "config.json 读不出来：%r" % (e,))
    ok = o.get("per_source_subdir") is True
    return (ok, "出厂 per_source_subdir=true" if ok
            else "实为 %r——多客户文档会平铺混放" % o.get("per_source_subdir"))


def _sec_no_shell():
    """代码层：调用本机工具无 shell 拼接（注入面）。

    判据**必须正则到 `subprocess.…(…shell=True` 这一整段**，不能只搜 `shell=True` 子串：
    检查器自己就要写这个字符串来搜别人，子串判据会让 `check.py` 自指命中
    （与 26.5.3 的"行首正则"同一教训：判据要落到**调用形态**，不是关键字）。
    """
    bad = [os.path.basename(p) for p in glob.glob(os.path.join(HERE, "*.py"))
           if SHELL_TRUE_RE.search(_read(p))]
    return (not bad, "全部脚本零 shell=True 调用" if not bad else "存在注入面 %s" % ", ".join(bad))


def _sec_no_auto_install():
    """代码层：不代装依赖——只给命令，不替使用者执行"""
    t = _read(os.path.join(HERE, "detect-tools.py"))
    ok = ("subprocess" not in t) and ("os.system" not in t)
    return (ok, "detect-tools.py 只打印命令、无执行调用"
            if ok else "detect-tools.py 出现了执行调用——「不代装」被打破")


def _sec_fingerprint():
    """代码层：脚本防篡改——指纹基线须覆盖全部脚本，缺一个即等于该脚本无人看管"""
    p = os.path.join(HERE, ".integrity.json")
    if not os.path.exists(p):
        return (False, "缺 .integrity.json（指纹基线）")
    try:
        d = json.loads(_read(p))
    except Exception as e:
        return (False, ".integrity.json 解析失败：%r" % (e,))
    signed = set((d.get("sha256") or {}).keys())   # 实测结构：{note, root, count, sha256{文件名: 指纹}}
    have = {os.path.basename(f) for f in glob.glob(os.path.join(HERE, "*.py"))}
    miss = sorted(have - signed - {"check.py"})   # check.py 自己不算自己的指纹
    return (not miss, "指纹基线覆盖 %d 个脚本" % len(signed) if not miss
            else "未纳入指纹 %s" % ", ".join(miss))


# (编号, 机制, 层, SECURITY.md 里的对应承诺关键词, 判据函数 or None（None＝由既有段落负责，见 anchor）, 锚点)
SEC_MATRIX = (
    ("M1", "文档不出网（接触文档的脚本零出网路径）", "数据层", "不出域", _sec_doc_no_net, None),
    ("M2", "映射表隔离（默认落本机隔离目录）", "数据层", "映射表", _sec_map_isolated, None),
    ("M3", "私有库默认不打进发布包", "数据层", "private", _sec_private_not_packed, None),
    ("M4", "查更新默认不发请求（可联网 ≠ 会自动联网）", "数据层", "默认", _sec_online_off, None),
    ("M5", "原件不改（产物一律新建）", "产物层", "不改动原始文件", _sec_original_intact, None),
    ("M6", "输出隔离（按文档名分目录，多客户不混放）", "产物层", "隔离", _sec_output_isolated, None),
    ("M7", "私有库默认空（不参与审查）", "数据层", "私有库默认空", None, "check_security"),
    ("M8", "不留缓存（脚本禁止生成 __pycache__）", "代码层", "无缓存留痕", None, "_check_no_bytecode"),
    ("M9", "脚本防篡改（指纹基线覆盖全部脚本）", "代码层", "脚本防篡改", _sec_fingerprint, None),
    ("M10", "无 shell 注入面（本机工具按参数列表调用）", "代码层", "shell", _sec_no_shell, None),
    ("M11", "不代装依赖（只给命令，不替人执行）", "代码层", "不代装", _sec_no_auto_install, None),
    ("M12", "企业词表外置（脚本内不含任何企业名）", "代码层", "企业词表外置", None, "check_deenterprise"),
)


def check_security_matrix():
    """安全机制逐条自检：登记在册的 12 条，逐条跑判据并公布结论。

    与 `check_net_tiers()` 的分工：那条管"**谁可以联网**"，本条管"**承诺过的安全机制是不是真装上了**"。
    两条都不复制实现，只钉落点——**登记表与实现分家是 25.2 的事故形态，安全承诺尤其经不起**。
    """
    sec_p = os.path.join(os.path.dirname(HERE), "SECURITY.md")
    sec = _read(sec_p) if os.path.exists(sec_p) else ""
    bad_all, layers = [], {}
    for mid, name, layer, doc_kw, probe, anchor in SEC_MATRIX:
        layers.setdefault(layer, []).append(mid)
        if probe is not None:
            try:
                ok, detail = probe()
            except Exception as e:      # 判据跑不起来＝落点被删，与"判据失败"同罪
                ok, detail = False, "判据跑不起来：%r（落点可能被删）" % (e,)
        else:
            # 由既有段落负责：只验锚点还在位（改名不同步当场报错，不重复执行以免重复输出）
            ok = bool(anchor) and callable(globals().get(anchor))
            detail = ("由 %s() 负责" % anchor) if ok else "锚点 %s 不存在或不可调用" % anchor
        if not ok:
            bad_all.append("%s %s：%s" % (mid, name, detail))
        if doc_kw and doc_kw not in sec:
            bad_all.append("%s %s：SECURITY.md 里查不到对应承诺（关键词「%s」）——"
                           "代码有、文档没说，或文档改了名，两处须对上" % (mid, name, doc_kw))
    if bad_all:
        for b in bad_all:
            err("安全机制未落实 —— %s" % b)
        return
    info("安全机制：12 条在册逐条落实（数据层 %d／产物层 %d／代码层 %d；"
         "判据均指向已在跑的实现，登记表不复制实现）"
         % (len(layers.get("数据层", [])), len(layers.get("产物层", [])),
            len(layers.get("代码层", []))))


def _check_online_gate(data=None):
    """只守一件事：出厂配置**不得默认联网**。

    分档由 `check_net_tiers()` 管（谁可以联网、谁绝不能），这里只管"默认行为"——
    **可联网 ≠ 会自动联网**。L1 的 `version.py` 允许联网查更新，但出厂必须关着，
    要人显式开口（`--check-online`）才发请求（19.4.5 与 25.4.3）。
    """
    if data is None:
        try:
            data = json.loads(_read(os.path.join(HERE, "config.json")))
        except Exception:
            data = {}
    u = (data.get("update") or {}) if isinstance(data, dict) else {}
    if u.get("check_online_by_default") is True:
        warn("config.json 把 update.check_online_by_default 设为 true：查更新会自动联网。"
             "对外分发前请确认这是有意为之（SECURITY.md 声称默认不发请求）")


def check_freshness_engine():
    """法规库失效巡检门禁：判据必须真的能分辨「一致／换版」，且库内源可定位。

    为什么要门禁：v3.22.2 的教训是「库里存着失效条文，隔 4 个月才发现」。
    巡检脚本建起来之后，真正需要防的是它**悄悄变成摆设**——判据一松，
    换版就漏；库内 sources 缺 grp/enc，巡检就找不到源。故跑一次**离线自检**
    （不联网：出包不能依赖源站活着，且要验的是判据不是源站），非 0 即拦下。
    """
    p = os.path.join(HERE, "freshness-patrol.py")
    if not os.path.exists(p):
        err("缺少 scripts/freshness-patrol.py（法规库失效巡检）——库的时效无从核验")
        return
    try:
        r = subprocess.run([sys.executable, p, "--self-test"],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        err("巡检自检跑不起来：%s" % e)
        return
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        err("法规库失效巡检自检未通过（退出 %d）：%s"
            % (r.returncode, out.strip().splitlines()[-1] if out.strip() else "无输出"))
        return
    for must in ("同一条文必判一致", "混入条目标题须判不一致", "库内 sources 均带 grp/enc"):
        if must not in out:
            err("巡检自检缺少关键判据项「%s」——判据被删或改名，门禁等于失效" % must)
            return
    n_ok = len(re.findall(r"\[OK\]", out))
    info("法规库失效巡检：离线自检 %d 项全过（判据可分辨一致/换版，库内源可定位）" % n_ok)


def check_hardcoded_paths():
    """回归检查：脚本内是否残留盘符字面量。

    V3.9.0 起不再豁免 `_config.py`——其 DEFAULTS 的 tools 已全部留空（改为按 PATH 探测），
    本机路径只允许出现在 `config.local.json`（不进 git、不随包），故任何 .py 里都不该有盘符字面量。
    `check.py` 自身仍豁免：本函数的检测正则自指，无法自检。
    """
    bad = []
    for p in _walk(HERE, exts=(".py",)):
        if os.path.basename(p) == "check.py":
            continue
        txt = _read(p)
        # 统计盘符字面量；排除系统字体目录（跨平台字体候选，属正常硬编码）
        lits = re.findall(r'r?"[A-Z]:\\[^"]*"', txt)
        lits = [s for s in lits if "Windows\\Fonts" not in s and "Windows/Fonts" not in s]
        n = len(lits)
        if n:
            bad.append("%s(%d处)" % (os.path.basename(p), n))
    if bad:
        warn("脚本内仍有盘符字面量（宜改为读 config.json）: " + ", ".join(bad))
    else:
        info("路径外置: 无残留盘符硬编码")


def check_security():
    """安全项：私有库空态、映射表隔离目录、缓存残留。"""
    rules = []
    for fn in ("rules.md", "meta.md"):
        p = os.path.join(ROOT, "private", fn)
        if not os.path.exists(p):
            continue
        txt = re.sub(r"<!--.*?-->", "", _read(p), flags=re.S)   # 注释内示例不计入生效规则
        rules += [l for l in txt.splitlines()
                  if l.strip().startswith("|") and re.search(r"PR-\d+", l)]
    if rules:
        info("私有库: 含 %d 条内控规则（打包分发请用 --include-private 显式确认）" % len(rules))
    else:
        info("私有库: 空库（默认，不参与审查）")
    mapdir = os.environ.get("DCR_MAP_DIR") or os.path.join(os.path.expanduser("~"), ".dcr-maps")
    info("脱敏映射表隔离目录: %s（%s）" % (mapdir, "存在" if os.path.isdir(mapdir) else "尚未创建"))
    caches = _pycache_dirs()
    if caches:
        warn("发现 %d 个 __pycache__ 缓存目录（可用 python check.py --clean 清理）: %s"
             % (len(caches), ", ".join(os.path.relpath(c, ROOT) for c in caches)))
    else:
        info("缓存残留: 无 __pycache__")
    _check_no_bytecode()


def _check_no_bytecode():
    """每个脚本都必须在 import 之前关掉字节码写入——文档承诺「脚本禁止生成 __pycache__」。

    为什么要逐个查：`sys.dont_write_bytecode = True` 只有写在**模块被 import 之前**才管用，
    写在文件中间或漏写，被别的脚本 import 一次就会在技能目录里留下 .pyc。
    实测漏写是静默的——CLI 直跑不报错，只有被 import 时才留痕，肉眼看不出来。
    这既是「无缓存留痕」的技术措施，也影响 `pack.py` 出包的确定性（包里会混进 .pyc）。
    """
    bad = []
    for p in _script_files():
        if not p.endswith(".py") or os.path.basename(p) == "_config.py":
            continue   # _config.py 自身就是这个开关的实现方，也是被 import 的第一站
        src = _read(p)
        head = src[:4000]            # 只看文件头，开关必须在真正的业务 import 之前
        if "_sys.dont_write_bytecode" not in head and "sys.dont_write_bytecode" not in head:
            bad.append(os.path.basename(p))
    if bad:
        err("以下脚本未在文件头关闭字节码写入（被 import 时会在技能目录留下 __pycache__）："
            "%s；应在首个 import 前加 `import sys as _sys` ＋ `_sys.dont_write_bytecode = True`"
            % ", ".join(bad))
        return
    info("缓存防护: %d 个脚本均在 import 前关闭字节码写入（被 import 也不留 .pyc）"
         % len([p for p in _script_files() if p.endswith(".py")]))


# ---------------------------------------------------------------- 指纹
def _script_files():
    out = []
    for p in _walk(HERE, exts=(".py", ".ps1")):
        b = os.path.basename(p)
        if b == "check.py":
            continue
        out.append(p)
    return sorted(out)


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def sign():
    files = {os.path.relpath(p, HERE).replace("\\", "/"): _sha(p) for p in _script_files()}
    payload = {"note": "脚本完整性指纹；校验用 python check.py --verify，刷新用 --sign",
               "root": "scripts", "count": len(files), "sha256": files}
    with open(INTEGRITY, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    info("已写入指纹文件: %s（%d 个脚本）" % (INTEGRITY, len(files)))


def verify(strict=False):
    if not os.path.exists(INTEGRITY):
        warn("未发现指纹文件，跳过校验（可先运行 python check.py --sign 建立基线）")
        return
    try:
        rec = json.loads(_read(INTEGRITY)).get("sha256") or {}
    except Exception as e:
        err("指纹文件解析失败: %s" % e)
        return
    cur = {os.path.relpath(p, HERE).replace("\\", "/"): _sha(p) for p in _script_files()}
    changed = [k for k in rec if k in cur and cur[k] != rec[k]]
    missing = [k for k in rec if k not in cur]
    added = [k for k in cur if k not in rec]
    if changed:
        (err if strict else warn)("脚本已被修改，指纹不一致: %s" % ", ".join(changed))
    if missing:
        warn("指纹记录中的脚本已缺失: %s" % ", ".join(missing))
    if added:
        warn("新增脚本未纳入指纹（建议 --sign 刷新）: %s" % ", ".join(added))
    if not (changed or missing or added):
        info("脚本完整性: %d 个脚本指纹一致" % len(rec))


# ---------------------------------------------------------- 免责声明口径
DISC_VERBATIM = ("AI不能替代人工，人工不能依赖AI，个人仅限研究、学习、交流、体验自用，商业使用须获作者书面授权"
                 "；本技能仅作为辅助法律工作，不构成法律意见，不可直接作为决策依据；输出内容须经执业律师复核"
                 "后方可使用；使用风险与后果由使用者自行承担。使用即为已知晓后果并免责作者，否则，请勿使用！")
DISC_KEYS = ["AI不能替代人工", "人工不能依赖AI", "商业使用须获作者书面授权",
             "不构成法律意见", "执业律师复核", "免责作者"]
DISC_FULL_DOCS = ["SKILL.md", "LICENSE.md", "安装使用教程.md", "文档合规审查助手AI合同提示词版.md"]
DISC_KEY_DOCS = ["README.md", "scripts/make-docx.py", "SECURITY.md", "core/01-general-risk-rules.md"]


def _norm(t):
    """去掉 Markdown 强调符与全部空白，便于跨排版比对同一句话。"""
    return re.sub(r"[*_\s]", "", t or "")


def check_disclaimer():
    """《免责声明》口径一致：每次使用先输出的那段，入口文档须逐字一致。

    入口文档（SKILL.md / LICENSE.md / 安装使用教程.md / 文档合规审查助手AI合同提示词版.md）要求**逐字全文**；
    生成端与摘要处（README.md / make-docx.py / SECURITY.md / core 库）只查**关键句**，
    允许节选改写——README 页首与「三、快速上手」各保留一句概要，全文在 `LICENSE.md`。
    """
    bad = []
    for rel in DISC_FULL_DOCS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            bad.append(rel + "(缺失)")
        elif _norm(DISC_VERBATIM) not in _norm(_read(p)):
            bad.append(rel)
    if bad:
        err("免责声明未含逐字全文：%s" % "、".join(bad))
    for rel in DISC_KEY_DOCS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            warn("免责声明关键句未检查（文件缺失）: %s" % rel)
            continue
        lack = [k for k in DISC_KEYS if k not in _read(p)]
        if lack:
            err("%s 免责声明缺关键句: %s" % (rel, "／".join(lack)))
    if not bad:
        info("免责声明: %d 处入口文档含逐字全文，生成端与摘要处关键句齐全" % len(DISC_FULL_DOCS))
    sk = _read(os.path.join(ROOT, "SKILL.md"))
    if "步骤 0.0 免责声明" not in sk:
        err("SKILL.md 启动流程缺「步骤 0.0 免责声明」（同一对话内首次使用先输出）")


# ---------------------------------------------------------------- 长文档分批口径
BATCH_DOCS = ["SKILL.md", "文档合规审查助手AI合同提示词版.md"]
BATCH_KEYS = ["共 N 批", "按条款分批", "一次性"]


def check_batch_guidance():
    """《长文档分批》口径：主档与纯提示词版须同时具备，避免一处改一处漏（超长全文会静默漏条）。"""
    bad = []
    for rel in BATCH_DOCS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            bad.append(rel + "(缺失)")
            continue
        t = _read(p)
        lack = [k for k in BATCH_KEYS if k not in t]
        if lack:
            bad.append("%s(缺:%s)" % (rel, "／".join(lack)))
    if bad:
        err("长文档分批口径不一致/缺失：%s" % "、".join(bad))
    else:
        info("长文档分批: %d 处入口文档口径齐全（共 N 批 / 按条款分批 / 禁止一次性）" % len(BATCH_DOCS))


def check_md_fences():
    """代码围栏配对：漏一个闭合会把后续标题整段吞进代码块，阅读器大纲里直接消失。

    只对 `## ` 级标题报警——代码块内的 `# 注释`（如 PowerShell 示例）是合法的，
    若一并当标题会误报。
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = 0
    for p in _walk(base, (".md",)):
        rel = os.path.relpath(p, base).replace("\\", "/")
        if rel.startswith("samples/") or rel.startswith("private/"):
            continue
        lines = _read(p).split("\n")
        idx = [i for i, ln in enumerate(lines, 1) if ln.strip().startswith("```")]
        if not idx:
            continue
        if len(idx) % 2:
            err("Markdown 代码围栏未闭合：%s（围栏 %d 个，应为偶数）" % (rel, len(idx)))
            bad += 1
            continue
        for k in range(0, len(idx), 2):
            a, b = idx[k], idx[k + 1]
            for j in range(a + 1, b):
                t = lines[j - 1]
                if t.lstrip().startswith("## "):
                    err("Markdown 代码围栏吞掉标题：%s 第 %d 行「%s」落在代码块内（L%d~L%d）"
                        % (rel, j, t.strip()[:40], a, b))
                    bad += 1
    if not bad:
        info("Markdown 代码围栏：全部成对，无章节标题被吞")


def _png_text(path):
    """读取 PNG 的 tEXt 文本块（纯标准库实现，不给 check 引入 Pillow 依赖）。"""
    out = {}
    try:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return out
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                ln = int.from_bytes(hdr[:4], "big")
                ctype = hdr[4:8]
                data = f.read(ln)
                f.read(4)
                if ctype == b"tEXt":
                    k, _, v = data.partition(b"\x00")
                    out[k.decode("latin-1", "ignore")] = v.decode("latin-1", "ignore")
                if ctype == b"IEND":
                    break
    except OSError:
        pass
    return out


def check_header_version():
    """头标 PNG 内嵌的 Skill-Version 是否与 SKILL.md 版本一致。

    头图上的版本串是**烧进像素**的，升版时若忘了重绘，图片看起来正常、
    脚本也全绿，只有肉眼能发现。故由 make-header.py 在出图时把版本写进 PNG
    的 tEXt 元数据，这里比对即可当场发现「图片版本过期」。
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = re.search(r"(?m)^version:\s*([0-9][0-9.]*)\s*$", _read(os.path.join(base, "SKILL.md")))
    cur = ("v" + m.group(1)) if m else None
    adir = os.path.join(base, "assets")
    if not cur or not os.path.isdir(adir):
        return
    seen, stale, unstamped = 0, [], []
    for x in sorted(os.listdir(adir)):
        if not x.lower().endswith(".png"):
            continue
        seen += 1
        v = _png_text(os.path.join(adir, x)).get("Skill-Version")
        if v is None:
            unstamped.append(x)
        elif v != cur:
            stale.append("%s（内嵌 %s）" % (x, v))
    if stale:
        err("头标版本串过期：%s —— SKILL.md 现为 %s，请重跑 `python scripts/make-header.py` 刷新头图"
            % ("、".join(stale), cur))
    elif unstamped:
        warn("头标缺版本戳（%s）：建议用 make-header.py 重绘一次；此后升版漏重绘会被本项检出"
             % "、".join(unstamped))
    if seen and not stale and not unstamped:
        info("头标版本戳：%d 张图的 Skill-Version 均为 %s" % (seen, cur))


def check_rule_metadata():
    """《生效日／最近修订》元数据：核心库与每个行业包都要有，且不得缺项、不得晚于今天。

    只查"有没有、对不对格式"，**内容变了没更新「最近修订」**由 `rule-baseline.py` 的 stale 判据
    负责（已挂 `check_rule_baseline()`），此处不重复比对。
    """
    import datetime
    today = datetime.date.today().isoformat()
    bad, ok = [], 0
    # 核心库：头部须有 版本 / 生效日 / 最近修订（沿革表已移除，修订史随项目维护、不随包）
    for name in ("01-general-risk-rules.md", "02-legal-verification-checklist.md"):
        p = os.path.join(ROOT, "core", name)
        if not os.path.exists(p):
            continue
        head = "\n".join(_read(p).splitlines()[:40])
        lack = []
        if not re.search(r"生效日\s*\**\s*\d{4}-\d{2}-\d{2}", head):
            lack.append("生效日")
        if not re.search(r"最近修订\s*\**\s*\d{4}-\d{2}-\d{2}", head):
            lack.append("最近修订")
        # 01 声明的「规则数」须与实际扫描一致（历史教训：写 140 而实为 159，
        # 因 A/B/X 组长期漏出正则白名单且无人校验，对外口径一路失真）
        if name == "01-general-risk-rules.md":
            real = len(CORE_ID_RE.findall(_read(p)))
            mn = re.search(r"规则数\s*\**\s*(\d+)\s*\**", head)
            if not mn:
                lack.append("规则数")
            elif int(mn.group(1)) != real:
                lack.append("规则数写%s实为%d" % (mn.group(1), real))
        for m in re.finditer(r"(?:生效日|最近修订)\s*\**\s*(\d{4}-\d{2}-\d{2})", head):
            if m.group(1) > today:
                lack.append("日期晚于今天(%s)" % m.group(1))
        if lack:
            bad.append("core/%s(缺:%s)" % (name, "／".join(lack)))
        else:
            ok += 1
    # 行业包 <slug>-meta.md：生效日 / 最近修订 / revision
    ind = os.path.join(ROOT, "industries")
    if os.path.isdir(ind):
        for slug in _industry_slugs():
            p = os.path.join(ind, "%s-meta.md" % slug)
            if not os.path.exists(p):
                continue
            t = _read(p)
            lack = []
            if not re.search(r"^effective_date:\s*\d{4}-\d{2}-\d{2}\s*$", t, re.M):
                lack.append("effective_date")
            if not re.search(r"^last_revised:\s*\d{4}-\d{2}-\d{2}\s*$", t, re.M):
                lack.append("last_revised")
            if not re.search(r"^\s*-\s*version:", t, re.M):
                lack.append("revision")
            for m in re.finditer(r"^(?:effective_date|last_revised):\s*(\d{4}-\d{2}-\d{2})\s*$",
                                 t, re.M):
                if m.group(1) > today:
                    lack.append("日期晚于今天(%s)" % m.group(1))
            if lack:
                bad.append("industries/%s-meta.md(缺:%s)" % (slug, "／".join(lack)))
            else:
                ok += 1
    if bad:
        err("规则元数据（生效日/最近修订/规则数）缺失或失准：%s" % "、".join(bad))
    else:
        info("规则元数据: %d 处齐全（生效日 / 最近修订 / 规则数）" % ok)
    # README 对外宣称的通用库条数，须与 core/01 同一口径
    rp = os.path.join(ROOT, "README.md")
    core01 = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if os.path.exists(rp) and os.path.exists(core01):
        real = len(CORE_ID_RE.findall(_read(core01)))
        hits = set(re.findall(r"通用库[^0-9]{0,24}?(\d{2,4})\s*\**\s*条", _read(rp)))
        if hits and str(real) not in hits:
            err("README 宣称通用库 %s 条，实际 %d 条（两处口径须一致）"
                % ("/".join(sorted(hits)), real))


def check_smoke_count():
    """冒烟项数：文档所写的「N 项」须等于实测总数。

    实测值来自 `core/_smoke-baseline.json`（`smoke-test.py` 跑完自动记账，运行侧生成物）。
    背景：冒烟项数会随链路扩充而增加，手写在文档里的数字极易漂（本次即发现文档写 66、
    实为 89）。跑过一次冒烟后此项即生效，未跑过时只提示不报错。
    两档项数守恒（全量拆分 OCR 两步、快档合并，总数一致），故只比 total。
    """
    led = os.path.join(ROOT, "core", "_smoke-baseline.json")
    if not os.path.exists(led):
        info("冒烟项数：未跑过 smoke-test，跳过校验（跑一次后此项自动生效）")
        return
    try:
        d = json.load(open(led, encoding="utf-8"))
    except Exception as e:
        warn("冒烟台账解析失败：%s" % e)
        return
    # 只有在冒烟全通过时，total 才是「完整项数」：依赖不全的机器上会有若干项根本跑不到
    # （实测：OCR 不可用时总数由 89 掉到 87），此时拿它当基准会误判文档，故跳过校验。
    if d.get("failed"):
        info("冒烟项数：上次冒烟有 %d 项失败，项数不作基准（请先排除失败再校验文档口径）"
             % d["failed"])
        return
    real = d.get("total")
    if not isinstance(real, int) or not real:
        return
    # 只扫与冒烟/自检同一行的数字。须排除两类干扰，否则会把别的脚本的项数当成冒烟项数：
    # (1) 其他脚本所在行（check.py 的 12 项、pack.py 的 5 项都不是冒烟项数）
    # (2) 列表式表述「N 项：结构／字段／…」——那是分项的枚举，不是总数
    kw = ("smoke-test", "冒烟", "自检")
    other_scripts = ("check.py", "pack.py", "sample-baseline", "guard.py", "rule-baseline")
    bad, seen = [], 0
    for rel in ("README.md", "安装使用教程.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        for ln, line in enumerate(_read(p).splitlines(), 1):
            if not any(k in line for k in kw):
                continue
            if any(k in line for k in other_scripts):
                continue
            for m in re.finditer(r"(\d{2,3})\s*\**\s*项(?!\s*[:：])", line):
                seg = line[max(0, m.start() - 8):m.end() + 14]
                if "SKIP" in seg or "跳过" in seg or "预期" in seg:
                    continue
                n = int(m.group(1))
                seen += 1
                if n != real:
                    bad.append("%s:%d 写 %d 项" % (rel, ln, n))
    if bad:
        err("冒烟项数失准（文档所写 ≠ 实测总数 %d 项）：%s" % (real, "；".join(bad)))
    elif seen:
        info("冒烟项数：文档 %d 处口径与实测一致（%d 项）" % (seen, real))


def _doc_lines(rel):
    p = os.path.join(ROOT, rel)
    return _read(p).splitlines() if os.path.exists(p) else []


def check_doc_number_caliber():
    """文档数字口径守卫（格式数 / 菜单项数 / 内置库数）。

    背景（V3.11.1）：新增 HTML 格式时，SKILL 与教程的个别位置改了、README 与教程另一处没改，
    文档里同时存在「4 种格式」与「5 种格式」，而既有守卫只查冒烟项数与规则条数，**不查格式数**，
    于是漏改 5 处一路带到出包。同类风险还有两处这次一并堵上：功能菜单项数（曾写 11 项、
    实际 0–11 共 12 项）、初始内置行业库数（曾写 8 库、真源 9 个）。

    做法与冒烟项数守卫同源：**真源一律可实算，不写死数字**——
      · 格式数 ← `make-docx.py` 的 `--formats` 帮助串里列出的合法值；
      · 菜单项数 ← `SKILL.md` 功能菜单代码块里「N. 」开头的实际行数；
      · 内置库数 ← `guard.py` 的 `SEED_INDUSTRIES` 实读。
    只扫明确写「N 种格式 / N 格式 / N 项功能 / N 个行业库」这类总量表述，
    `VERSION.md` 为沿革表（旧数字属历史记录）跳过。
    """
    DOCS = ("SKILL.md", "README.md", "安装使用教程.md",
            "文档合规审查助手AI合同提示词版.md")

    # ---- 真源 1：格式数 ----
    real_fmt = None
    mk = os.path.join(HERE, "make-docx.py")
    if os.path.exists(mk):
        m = re.search(r'"--formats"[^\n]*?help="逗号分隔：([a-z,]+)', _read(mk))
        if m:
            real_fmt = len([x for x in m.group(1).split(",") if x])
    # ---- 真源 2：菜单项数 ----
    real_menu = None
    sk = _read(os.path.join(ROOT, "SKILL.md")) if os.path.exists(os.path.join(ROOT, "SKILL.md")) else ""
    m = re.search(r"【本技能功能 · 请单选】\n(.*?)```", sk, re.S)
    if m:
        real_menu = len(re.findall(r"^\s*(\d+)\.\s", m.group(1), re.M))
    # ---- 真源 3：内置库数 ----
    real_seed = None
    gd = os.path.join(HERE, "guard.py")
    if os.path.exists(gd):
        m = re.search(r"SEED_INDUSTRIES\s*=\s*[\[\{](.*?)[\]\}]", _read(gd), re.S)
        if m:
            real_seed = len(re.findall(r"['\"]([a-z][a-z0-9]*)['\"]", m.group(1)))

    src_note = []
    if real_fmt:  src_note.append("格式 %d" % real_fmt)
    if real_menu: src_note.append("菜单 %d 项" % real_menu)
    if real_seed: src_note.append("内置库 %d 个" % real_seed)
    if not src_note:
        info("数字口径：真源未能解析，跳过")
        return

    fmt_bad, menu_bad, seed_bad = [], [], []
    for rel in DOCS:
        for ln, line in enumerate(_doc_lines(rel), 1):
            # 格式数：「N 种格式」／「N 格式」／「N 种封装」不算（那是发布包封装格式）
            if real_fmt:
                for m in re.finditer(r"(\d+)\s*种?\s*格式", line):
                    if "封装" in line or ".skill" in line or ".zip" in line:
                        continue
                    n = int(m.group(1))
                    if n != real_fmt:
                        fmt_bad.append("%s:%d 写 %d 种" % (rel, ln, n))
            # 菜单项数：只认「列出 N 项」「N 项功能」「N 项全列」这类总量表述，
            # 且同行须出现菜单/向导语境——否则「第 5／6 项」「13 项要素」都会被误抓。
            if real_menu:
                if not any(k in line for k in ("向导", "菜单", "功能总菜单")):
                    pass
                else:
                    hits = [int(x) for x in re.findall(r"列出\s*\**(\d+)\s*\**\s*项", line)]
                    hits += [int(x) for x in
                             re.findall(r"(\d+)\s*\**\s*项(?:功能|全列)", line)]
                    for n in hits:
                        if n != real_menu:
                            menu_bad.append("%s:%d 写 %d 项" % (rel, ln, n))
            # 内置库数：「N 个行业库」／「初始 N 库」
            if real_seed:
                for m in re.finditer(r"(\d+)\s*个(?:内置)?行业库|初始\s*(\d+)\s*库", line):
                    n = int(m.group(1) or m.group(2))
                    if n != real_seed:
                        seed_bad.append("%s:%d 写 %d 个" % (rel, ln, n))

    msg = []
    if fmt_bad:
        err("交付物格式数失准（真源 `--formats` 共 %d 种）：%s"
            % (real_fmt, "；".join(fmt_bad)))
    if menu_bad:
        err("功能菜单项数失准（真源菜单代码块共 %d 项）：%s"
            % (real_menu, "；".join(menu_bad)))
    if seed_bad:
        err("内置行业库数失准（真源 `SEED_INDUSTRIES` 共 %d 个）：%s"
            % (real_seed, "；".join(seed_bad)))

    # ---- 真源 4：法规库规模（「17 部法 704 条」这类表述）----
    # 背景（v3.15.0/v3.16.0）：法条库从 85 条扩到 704 条，文档里「N 部法 M 条」出现在
    # SKILL／README 多处，扩一次要同步 5 处以上。凡写死数字迟早失真，故纳入常驻校验。
    real_laws = real_arts = None
    lp = os.path.join(ROOT, "core", "legal-articles.json")
    if os.path.exists(lp):
        try:
            _db = json.loads(_read(lp))
            _laws = _db.get("laws") or {}
            real_laws = len(_laws)
            real_arts = sum(len(v) for v in _laws.values())
        except Exception:
            pass
    law_bad = []
    if real_laws and real_arts:
        for rel in DOCS:
            for ln, line in enumerate(_doc_lines(rel), 1):
                for m in re.finditer(r"(\d+)\s*部法[^0-9]{0,10}?(\d+)\s*条", line):
                    if int(m.group(1)) != real_laws or int(m.group(2)) != real_arts:
                        law_bad.append("%s:%d 写 %s 部 %s 条" % (rel, ln, m.group(1), m.group(2)))
        if law_bad:
            err("法规库规模失准（真源 core/legal-articles.json 实为 %d 部法 %d 条）：%s"
                % (real_laws, real_arts, "；".join(law_bad)))

    if not (fmt_bad or menu_bad or seed_bad or law_bad):
        note = src_note + (["法条 %d 部 %d 条" % (real_laws, real_arts)] if real_laws else [])
        info("数字口径：格式／菜单项数／内置库数／法规库规模与真源一致（%s）" % "、".join(note))


def check_package_fields():
    """出包必填字段守卫：`pack.py` 组装文件名所依赖的 frontmatter 字段，必须齐且非空。

    真源不写死在 check.py——从 `pack.py` 里实际调用的 `_fm_field(base, "X")` 抽出来，
    以后 pack.py 新增依赖字段，本守卫自动跟上，不需要人回来改两张表。

    **为什么非有这条不可**：`package_stem` 对每个字段都写了 `or` 兜底，字段丢了**不报错**，
    只会静默降级——四段式看着仍合规，`verify_filename` 也照样放行。V3.11.2 把它列为遗留，
    本条即其落地：**不再允许静默**。
    （V3.11.6 起文件名第四段改用 slug `name`，丢了会退化成技能目录名；`display_name_en`
    仍读取、仍属必填，只是不进文件名——本守卫照旧看 `pack.py` 的真实调用，自动跟上。）

    **第二道**：直接调用 pack.py 自己的 `package_stem` 实算文件名、再交给 `verify_filename`
    校验，这样"字段齐全但拼出来仍不合规"（例如产品名被非法字符洗空）也能当场抓住——
    生产与校验分离，任一边改坏都会被另一边查出。

    **第三道**：文档里凡以本技能产品名开头的四段式文件名（教程第一节放的就是实际产名），
    其**版本段必须等于当前版本**。示例串写死一次很容易在升版后被忘在旧号上——那正好是
    文件名规范刚埋下的新漂移点，此处一并堵上。
    """
    skill = os.path.join(ROOT, "SKILL.md")
    pack = os.path.join(HERE, "pack.py")
    if not os.path.exists(skill) or not os.path.exists(pack):
        return
    keys = []
    for k in re.findall(r'_fm_field\s*\(\s*base\s*,\s*"([^"]+)"', _read(pack)):
        if k not in keys:
            keys.append(k)
    if not keys:
        warn("pack.py 里未定位到 _fm_field 调用，出包字段校验未执行（改过 pack.py 请复核本守卫）")
        return
    fm = re.search(r"^---\n(.*?)\n---", _read(skill), re.S)
    fmtext = fm.group(1) if fm else ""
    missing = []
    for k in keys:
        m = re.search(r"(?m)^%s:[ \t]*(.*)$" % re.escape(k), fmtext)
        val = (m.group(1) if m else "").strip().strip('"').strip("'").strip()
        if not val:
            missing.append(k)
    if missing:
        err("SKILL.md frontmatter 缺出包必填字段（缺了该字段会**静默降级**，"
            "文件名看着仍合规）：%s" % "、".join(missing))
    else:
        info("出包必填字段：%s 齐全（真源＝pack.py 的 _fm_field 调用）" % "、".join(keys))

    # 第二道：加载 pack.py 实算文件名（这里是真跑它的代码，不是照抄一份正则来比对）
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_pack_probe", pack)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # pack.py 的 main 在 __main__ 保护下，导入无副作用
        tag = mod.read_skill_version(ROOT)
        stem, product, _sid, _d, _en = mod.package_stem(ROOT, tag)
        bad = mod.verify_filename(stem)
        if bad:
            err("实算出的出包文件名不合四段式：%s" % "；".join(bad))
        else:
            info("出包文件名实算合规：%s.%s" % (stem, mod.FMT_EXT["skill"]))
    except Exception as e:
        warn("出包文件名实算未执行：%s" % e)
        return

    # 第三道：文档里本技能的四段式示例，版本段必须与当前版本一致、形态必须符合新规范
    # 括号段这里**故意放宽**成 `[^()]+`：若写成只认 slug，旧形态示例会直接匹配不到而漏检，
    # 反倒失去"抓住滞后示例"的作用——形态问题另由下面的校验单列报错。
    pat = re.escape(product) + r"_([Vv]?\d+(?:\.\d+)+)_\d{8}_(\([^()]+\))"
    stale = []
    for rel in ("安装使用教程.md", "README.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        for ver, seg in re.findall(pat, _read(p)):
            if ver.lstrip("Vv") != tag.lstrip("Vv"):
                stale.append("%s 里的示例仍是 %s（当前 %s）" % (rel, ver, tag))
            if not ver.startswith("v"):
                stale.append("%s 里的示例版本号未带小写 v：%s" % (rel, ver))
            if " " in seg or "（" in seg or "）" in seg:
                stale.append("%s 里的示例技能ID 段仍是旧形态（应为 slug + 半角括号）：%s"
                             % (rel, seg))
    if stale:
        err("文档里的出包文件名示例不合新四段式：%s" % "；".join(stale))
    else:
        info("出包文件名示例：文档中的版本段与当前版本一致、形态合规（%s）" % tag)


def check_version_consistency():
    """版本号一致性：SKILL.md frontmatter 为准，正文标题与各文档里的版本串都要跟上。

    升版要改 10 处，最容易漏的就是"frontmatter 改了、正文没改"、"README 还是旧版"
    与"漏了重绘头标（图片里的版本串是烧进像素的，只有肉眼看得出来，见
    check_header_version）"。
    这里让脚本守着，漏一处即报错（error，不是警告）。
    """
    skill = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(skill):
        return
    t = _read(skill)
    m = re.search(r"(?m)^version:\s*([\d.]+)\s*$", t)
    if not m:
        err("SKILL.md frontmatter 缺 version 字段")
        return
    ver = m.group(1)
    v = "v" + ver
    bad = []
    # SKILL 正文标题里的版本串
    if not re.search(r"\*\*%s\*\*" % re.escape(v), t):
        bad.append("SKILL.md 正文标题")
    # 各文档里应出现该版本串
    for rel in ("README.md", "SECURITY.md", "文档合规审查助手AI合同提示词版.md"):
        p = os.path.join(ROOT, rel)
        if os.path.exists(p) and v not in _read(p):
            bad.append(rel)
    # 脚本数口径（新增脚本时常漏改文档）
    n_py = len([f for f in os.listdir(os.path.join(ROOT, "scripts")) if f.endswith(".py")])
    for rel in ("SKILL.md", "README.md", "SECURITY.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        hits = set(re.findall(r"(\d+)\s*个脚本", _read(p)))
        # 允许文档同时写「21 个脚本」与「处理文档的 20 个脚本」——后者是上一句的细分，
        # 不是口径冲突；只要「21」这个全量数在，就不算漂。
        if hits and str(n_py) not in hits:
            bad.append("%s(脚本数=%d，文档写%s)" % (rel, n_py, "/".join(sorted(hits))))
    if bad:
        err("版本号 %s 未同步：%s" % (v, "、".join(bad)))
    else:
        info("版本一致性: %s（frontmatter / 正文 / README / SECURITY / 提示词版）一致；脚本数 %d 口径同步" % (v, n_py))


def check_manifest_version():
    """对外版本清单（version.json）的版本号须与 SKILL.md 一致。

    为什么这条重要：`version.json` 是**对外公布**的清单——在线检查更新时，
    使用者看到的就是它。**它错一位，所有使用者都会被引向旧版**（铁律 19.3 / 19.4.5）。
    故把它纳入同一套版本一致性守卫：清单里的 latest.version 必须等于 frontmatter 的 version。

    真源仍是 `SKILL.md` frontmatter；清单是**派生公布物**，不是真源（铁律 23.1.1）。
    文件不存在时跳过（未启用在线分发的项目不受此约束）。
    """
    skill = os.path.join(ROOT, "SKILL.md")
    man = os.path.join(ROOT, "version.json")
    if not (os.path.exists(skill) and os.path.exists(man)):
        return
    m = re.search(r"(?m)^version:\s*([\d.]+)\s*$", _read(skill))
    if not m:
        return
    truth = m.group(1)
    try:
        import json
        d = json.loads(_read(man))
    except Exception as e:
        err("version.json 无法解析为 JSON：%s" % e)
        return
    lat = (d or {}).get("latest") or {}
    got = str(lat.get("version") or "").strip().lstrip("vV")
    if got != truth:
        err("version.json 的 latest.version=%r 与 SKILL.md 版本 %s 不一致——"
            "对外清单错一位，使用者会被引向旧版（铁律 19.3）" % (lat.get("version"), truth))
        return
    # 顺带核：下载页与文件直链不能留占位（占位＝尚未配置真源）
    page = str(lat.get("download_page") or "")
    if "<your-org>" in page:
        warn("version.json 的 download_page 仍是占位地址（<your-org>）——"
             "正式发布前须替换为真实仓库地址")
    else:
        info("对外版本清单 version.json：latest=%s 与 SKILL.md 一致；下载页已配置" % truth)


def check_platform_limit():
    """平台上限口径：文档里写的 zip 体积上限，必须等于 `pack.py` 的 `PLATFORM_MAX_MB`。

    真源是**常量**，不写死在 check.py——平台口径一变，改常量的那次就会被这里要求同步文档。

    为什么挑这一条做守卫：包体积**每次出包都不同**，写进文档的具体数字必然漂（V3.11.5 校准
    「不足 1 MB」时实测已是 1.5 MB）。所以对体积本身**不写死、写明"以实测为准"**；
    真正该守住的是**上限**——它是常量、不会漂，且超限会直接导致上传失败。
    超限由 `pack.py` 出包自检兜住，本条只管"文档与代码说的是不是同一个上限"。
    """
    pack = os.path.join(HERE, "pack.py")
    if not os.path.exists(pack):
        return
    m = re.search(r"(?m)^PLATFORM_MAX_MB\s*=\s*(\d+)", _read(pack))
    if not m:
        warn("pack.py 里未定位到 PLATFORM_MAX_MB，平台上限校验未执行")
        return
    lim = m.group(1)
    # 两处：教程的开放平台口径、README 的出包自检项
    pats = [("安装使用教程.md", r"open\.workbuddy\.cn[^\n]{0,80}?≤\s*(\d+)\s*MB"),
            ("README.md", r"体积\s*≤\s*(\d+)\s*MB")]
    bad = []
    for rel, pat in pats:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        hits = re.findall(pat, _read(p))
        if not hits:
            bad.append("%s 未找到平台上限表述" % rel)
        for h in dict.fromkeys(hits):   # 去重：同一文件里同样的错只报一次
            if h != lim:
                bad.append("%s 写 %s MB ≠ 代码常量 %s MB" % (rel, h, lim))
    if bad:
        err("平台上限口径不一致：%s" % "；".join(bad))
    else:
        info("平台上限口径：文档与 pack.py 常量一致（≤%s MB）" % lim)


def check_imbalance_engine():
    """失衡画像判定逻辑自洽：脚本在、能加载、内置用例全过。

    为什么要在 check 里跑：失衡画像会写出「**系统性偏移**」这样的强结论，
    一旦阈值被悄悄调松（比如把「同向 3 条」改成 2 条、把 60% 改成 40%），
    两份只沾一点边的条款就会被说成「整份合同系统性偏向对方」——
    **这种结论错了比不写更糟**，律师拿去谈判会被对方一句话问穿。
    所以阈值是常量、自检是硬闸。
    """
    p = os.path.join(ROOT, "scripts", "imbalance.py")
    if not os.path.exists(p):
        err("失衡画像脚本缺失：scripts/imbalance.py")
        return
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_ck_imb", p)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
    except Exception as e:
        err("失衡画像脚本无法加载：%s" % e)
        return

    fails = m.self_test()
    for f in fails:
        err("失衡画像判定错误：%s" % f)

    # 阈值必须是常量且在合理区间——松到随便就判「系统性」，结论就没有意义
    if not (2 <= m.MIN_ROWS <= 5):
        err("失衡画像计入门槛异常：MIN_ROWS=%s（应在 2–5）" % m.MIN_ROWS)
    if not (0.5 <= m.MAJORITY <= 0.8):
        err("失衡画像占比阈值异常：MAJORITY=%s（应在 0.5–0.8）" % m.MAJORITY)
    if "★" in m.WEIGHT:
        err("失衡画像把 ★ 提示项计入了统计（会把结论稀释成没结论）")

    info("失衡画像：%d 组判定用例全过，阈值常量在合理区间（计入≥%d 条、同向≥%d 条且占≥%d%%），"
         "★ 提示项不参与统计，无立场时不输出偏向结论"
         % (len(m.CASES), m.MIN_ROWS, m.MIN_SAME, int(m.MAJORITY * 100)))


def check_verify_engine():
    """核验引擎（第 11 引擎）自洽：在、能加载、正例放行、负例拦得住、出口分级正确。

    为什么要在 check 里实跑：核验引擎是**产物出不出得去的裁判**。裁判死了不比错判好——
    它只会静默放行，带病文件照出。所以每次改动都实跑正负例，确认三档出口还通着电。

    特别要守住的一条：**「需人工复核」必须带定位**。没有行号/条号的复核项等于没说，
    使用者根本不知道去哪儿改。
    """
    p = os.path.join(ROOT, "scripts", "verify.py")
    if not os.path.exists(p):
        err("核验引擎缺失：scripts/verify.py")
        return
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_ck_verify", p)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
    except Exception as e:
        err("核验引擎无法加载（语法错误或依赖越界）：%s" % e)
        return

    # ① 正例：干净文本必须判「通过」，不许误伤
    clean = ("甲方：某公司。乙方：某公司。\n"
             "第一条 甲方应于2025年3月1日前交货。\n"
             "第二条 货款人民币12,000元（大写：壹万贰仟元整）。\n"
             "第三条 未尽事宜依照第一条办理。\n")
    r = m.run(clean, only=["caliber"])
    if r["level"] != m.PASS:
        err("核验引擎误伤干净文本（正例被判 %s）：%s"
            % (r["level"], "；".join(f.title for f in m.run(clean, only=["caliber"])["findings"])))
    # 补一条：条款总数与条号对得上，也不能报断号
    ok_cnt = "本协议共三条。\n第一条 甲。\n第二条 乙。\n第三条 丙。\n"
    if m.run(ok_cnt, only=["caliber"])["level"] != m.PASS:
        err("核验引擎把「共三条／一至三条」误判为口径错误")

    # ② 负例：每一类都必须拦得住，且必须给定位
    cases = [
        ("占位符残留", "第一条 甲方：{{甲方全称}}。\n第二条 乙方：某公司。\n",
         "占位符", m.BLOCK),
        ("日期区间倒置", "第一条 自2025年3月1日至2025年1月1日止。\n",
         "日期区间倒置", m.BLOCK),
        ("金额大小写不一致", "第一条 货款人民币12,000元（大写：壹拾贰万元整）。\n",
         "金额大小写", m.BLOCK),
        ("交叉引用悬空", "第一条 甲。\n第二条 乙。\n第三条 依照第九条办理。\n",
         "交叉引用", m.MANUAL),
        ("条款总数不符", "本协议共五条。\n第一条 甲。\n第二条 乙。\n第三条 丙。\n",
         "共 5 条", m.MANUAL),
    ]
    for label, text, kw, want in cases:
        rr = m.run(text, only=["caliber"])
        hits = [f for f in rr["findings"] if kw in f.title]
        if not hits:
            err("核验引擎对「%s」没拦住（负例未命中「%s」）：%s"
                % (label, kw, "；".join(f.title for f in rr["findings"]) or "无发现"))
            continue
        if hits[0].level != want:
            err("核验引擎对「%s」分级不对：应为「%s」，实为「%s」" % (label, want, hits[0].level))
        if not hits[0].loc:
            err("核验引擎对「%s」只报问题不给定位（无行号/条号），使用者无从下手" % label)

    # ③ 出口分级：BLOCK 必须压过 MANUAL，PASS 不得抬高整体结论
    t = "第一条 自2025年3月1日至2025年1月1日止。\n第二条 依照第九条办理。\n"
    rr = m.run(t, only=["caliber"])
    if rr["level"] != m.BLOCK:
        err("核验引擎出口分级错误：同类内同时有拦下与复核项时应判「拦下」，实判「%s」" % rr["level"])

    # ④ 金额解析：合法写法不得误报（这是最容易出错的地方，写死几组已知答案）
    same = [("12000", "壹万贰仟元整"), ("12000", "壹万贰仟圆整"), ("100000", "拾万元整"),
            ("12000.50", "壹万贰仟元伍角"), ("12000.05", "壹万贰仟元零伍分"),
            ("10001", "壹万零壹元整"), ("100000000", "壹亿元整")]
    for small, big in same:
        if abs(m._parse_small(small) - (m._parse_big(big) or -1)) >= 0.005:
            err("核验引擎大写金额解析错误：%s 元 与「%s」本应一致，解析为 %s"
                % (small, big, m._parse_big(big)))
    for junk in ("见附件", "壹万贰仟元整及利息", ""):
        if m._parse_big(junk) is not None:
            err("核验引擎把认不出的金额「%s」硬解析出了数（应当返回 None 不猜）" % junk)

    info("核验引擎：正例通过、5 类负例全部拦下且均带定位（占位符／日期倒置／金额大小写／"
         "交叉引用悬空／条款总数不符），出口分级与金额解析正确")


def check_reproducible_build():
    """可复现构建守卫：出包链不得引入随"生成时刻"变化的字节。

    为什么守这条：分发包随包带两份**生成型台账**（`core/_rules-baseline.json`、
    `scripts/.integrity.json`）。若其中写入生成时刻、或 zip 条目时间戳取自源文件 mtime，
    则同一版本每次重跑发布链——包内容一字未改、**字节却全变**，包哈希不可复现，
    无法用于校验、缓存与分发对账。

    （`sync()` 是 rmtree＋copytree 全量重建，重建后全部文件 mtime 都变成同步时刻，
    故"zip 条目用 mtime"这条尤其隐蔽：单看打包脚本没问题，跑完整发布链才暴露。）

    本守卫逐条断言：
      (1) rule-baseline.py 的 `generated` 由内容派生（`content-` 前缀），非当前时刻
      (2) rule-baseline.py 不写入 `generated_at`（含时刻字段即破坏复现）
      (3) rule-baseline.py 不含 `datetime.now()` 写入基线的路径
      (4) pack.py 定义并统一使用固定 zip 条目时间戳（ZIP_EPOCH），不裸用 `zf.write(`
    """
    problems = []

    rb = os.path.join(HERE, "rule-baseline.py")
    if os.path.exists(rb):
        src = _read(rb)
        if "baseline_stamp(" not in src:
            problems.append("rule-baseline.py 未见 baseline_stamp()：基线标识须由内容派生")
        if '"content-"' not in src:
            problems.append("rule-baseline.py 基线标识未用 content- 前缀（非内容派生）")
        if "generated_at" in src:
            problems.append("rule-baseline.py 写入了 generated_at：含生成时刻即破坏可复现")
        if re.search(r'"generated":\s*datetime', src):
            problems.append("rule-baseline.py 的 generated 仍取自 datetime（应为内容标识）")
    else:
        info("可复现构建：rule-baseline.py 不存在，跳过 (1)-(3)")

    pk = os.path.join(HERE, "pack.py")
    if os.path.exists(pk):
        src = _read(pk)
        # 不能用 "ZIP_EPOCH" in src —— 改名成 ZIP_EPOCH_UNUSED 仍会命中子串。
        # 须精确断言：定义是一条赋值语句，且值为合法的 zip 时间戳元组（6 个整数）。
        if not re.search(r"(?m)^ZIP_EPOCH\s*=\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,"
                         r"\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)\s*$", src):
            problems.append("pack.py 未定义 ZIP_EPOCH（须为模块级 6 元组常量，"
                            "形如 ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)）")
        # 裸 zf.write( 会把源文件 mtime 写进条目 —— 发布链重建 mtime 后包字节即变
        # 判定范围须排除"非可执行文本"：注释行与 docstring 里都会以 zf.write() 举例
        # （本守卫的说明文字自身即含此串）。用 AST 只取**真实调用**，最稳。
        try:
            import ast as _ast
            tree = _ast.parse(src)
            calls = []
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Call):
                    fn = node.func
                    if (isinstance(fn, _ast.Attribute) and fn.attr == "write"
                            and isinstance(fn.value, _ast.Name) and fn.value.id == "zf"):
                        calls.append(getattr(node, "lineno", 0))
            if calls:
                problems.append("pack.py 第 %s 行仍有裸 zf.write()：会写入源文件 mtime，破坏可复现"
                                % "、".join(str(n) for n in calls))
        except SyntaxError as e:
            problems.append("pack.py 语法错误，无法做可复现性静态检查：%s" % e)
    else:
        info("可复现构建：pack.py 不存在，跳过 (4)")

    if problems:
        err("可复现构建契约被破坏 %d 处：%s" % (len(problems), "；".join(problems)))
    else:
        info("可复现构建：基线标识内容派生、zip 条目时间戳固定（同版本重跑出包字节一致）")


def check_gitignore():
    """`.gitignore` 有效性守卫：防"行尾注释"写法让规则**静默失效**。

    gitignore **不支持行尾注释**——`#` 只有位于**行首**才是注释；写在路径后面会被
    当作路径的一部分（如 `core/x.json    # 说明` 匹配的是名为
    `core/x.json    # 说明` 的文件）。规则于是形同虚设，**且不报任何错**。
    V3.11.8 实测踩到：三条生成物规则（`.integrity.json` / `_rules-baseline.json` /
    `_smoke-baseline.json`）因此长期失效，直到有人 `git add -A` 才发现。

    本守卫断言：.gitignore 中每条**非注释、非空**行都不得含 `#`。
    """
    p = os.path.join(os.path.dirname(ROOT), ".gitignore")
    if not os.path.exists(p):
        info("gitignore：仓库根无 .gitignore，跳过")
        return
    bad = []
    for i, line in enumerate(_read(p).splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "#" in s:
            bad.append("第 %d 行含行尾注释（# 后被当路径一部分，规则会静默失效）：%s"
                       % (i, s[:56]))
    if bad:
        err("gitignore 写法有误 %d 处：%s" % (len(bad), "；".join(bad[:3])))
    else:
        info("gitignore：无行尾注释写法（规则不会静默失效）")


def check_skill_ext_lowercase():
    """封装扩展名小写守卫：`.skill` 必须全小写，防止回流成 `.Skill`。

    V3.11.9 起，分发包主格式扩展名由 `.Skill` 统一改为全小写 `.skill`——部分系统
    做扩展名匹配时**大小写敏感**，统一小写更稳妥。为防日后有人照旧例写回大写，
    本守卫断言两件事：

    1. `pack.py` 的 `FMT_EXT["skill"]` 值全小写（真源本身不能是大写）；
    2. 入口文档与脚本中不出现作为**格式引用**的大写 `.Skill`（解释性提及除外，
       由 `ALLOW` 白名单显式放行，如变更说明里"此前为大写 `.Skill`"这类记载）。
    """
    # 1) 真源：FMT_EXT 的 skill 值须全小写
    pack = os.path.join(HERE, "pack.py")
    if not os.path.exists(pack):
        info("封装扩展名：未找到 pack.py，跳过")
        return
    src = _read(pack)
    m = re.search(r'FMT_EXT\s*=\s*\{[^}]*"skill"\s*:\s*"([^"]*)"', src)
    if not m:
        warn("封装扩展名：未能解析 pack.py 的 FMT_EXT，跳过")
        return
    if m.group(1) != m.group(1).lower():
        err("pack.py 的 FMT_EXT[\"skill\"] 应为全小写：当前 %r" % m.group(1))
        return

    # 2) 文档与脚本中不得出现作为格式引用的大写 .Skill
    # 放行清单：变更说明里需保留"此前为大写 `.Skill`"的历史记载。
    allow_docs = {"VERSION.md"}        # 版本沿革，须保留历史版本当时的写法
    allow_scripts = {"pack.py", "check.py"}   # 变更说明与守卫本身需引用"错误形态"
    bad = []
    for rel in ("SKILL.md", "README.md", "VERSION.md", "SECURITY.md",
                "安装使用教程.md", "文档合规审查助手AI合同提示词版.md"):
        if rel in allow_docs:
            continue
        for ln, line in enumerate(_doc_lines(rel), 1):
            if ".Skill" in line:
                bad.append("%s:%d" % (rel, ln))
    for p in _walk(HERE, exts=(".py", ".ps1")):
        if os.path.basename(p) in allow_scripts:
            continue
        for ln, line in enumerate(_read(p).splitlines(), 1):
            if ".Skill" in line:
                bad.append("%s:%d" % (os.path.relpath(p, ROOT), ln))
    if bad:
        err("发现大写 .Skill 格式引用 %d 处（应为小写 .skill）：%s"
            % (len(bad), "、".join(bad[:5])))
    else:
        info("封装扩展名：FMT_EXT 全小写，文档/脚本无大写 .Skill 回流")


def check_sample_baseline():
    """样例级人工基线台账：结构、样例路径、规则 ID 是否真实存在（防台账写错而不自知）。"""
    p = os.path.join(ROOT, "core", "_sample-baseline.json")
    if not os.path.exists(p):
        info("样例基线：未建立（python scripts/sample-baseline.py --record 登记）")
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_sample_baseline", os.path.join(HERE, "sample-baseline.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        problems = m.verify()
    except Exception as e:
        warn("样例基线校验失败：%s" % e)
        return
    if problems:
        err("样例基线台账有问题 %d 处：%s" % (len(problems), "；".join(problems[:4])))
        return
    try:
        data = json.loads(_read(p))
        cases = data.get("cases") or []
        n_c = sum(1 for c in cases if c.get("status") == "confirmed")
        n_d = len(cases) - n_c
        info("样例基线: %d 个用例（已确认 %d / 初拟 %d）" % (len(cases), n_c, n_d))
        if n_c == 0 and cases:
            info("样例基线：尚无 confirmed 用例，比对只提示不计失败——人工确认后改 status 为 confirmed")
    except Exception:
        pass


def check_tpl_engine():
    """模板引擎自洽：引擎在、能加载、正例过、负例拦得住。

    为什么要在 check 里跑一遍：模板引擎是「出件前的硬闸」，闸门坏了不会报错、
    只会**静默放行**——带病模板照出，使用者拿去签合同。所以每次改动都实跑一次
    正负例，确认闸门仍然通电。
    """
    p = os.path.join(ROOT, "scripts", "tpl-engine.py")
    if not os.path.exists(p):
        err("模板引擎缺失：scripts/tpl-engine.py")
        return
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_ck_tpl", p)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
    except Exception as e:
        err("模板引擎无法加载（语法错误或依赖越界）：%s" % e)
        return

    base = {
        "name": "T",
        "template": {
            "name": "T（模板）",
            "body": ("<!-- tpl: T | ver: 1.0.0 | date: 2026-01-01 | 变更: 初版 -->\n"
                     "甲方：{{甲方全称}}\n{{#有担保}}\n担保条款。\n{{/有担保}}\n"
                     "{{^有担保}}\n无担保。\n{{/有担保}}"),
            "placeholders": [{"name": "{{甲方全称}}", "meaning": "x", "required": True}],
            "values": {"甲方全称": "某公司"},
            "switches": {"有担保": True},
        },
    }
    # 正例：应零错误
    r = m.check(base, {"有担保": True}, filling=True)
    if r["errors"]:
        err("模板引擎正例被判错（不该拦的拦了）：%s" % "；".join(r["errors"]))
    # 负例四条：载不载得住
    import copy as _copy
    cases = [
        ("必填未填", lambda d: d["template"].update(values={}), "必填占位符未填实"),
        ("说明表漏登记", lambda d: d["template"].update(
            body="<!-- tpl: T | ver: 1.0.0 | date: 2026-01-01 | 变更: x -->\n{{未登记项}}"), "没登记"),
        ("条件段未闭合", lambda d: d["template"].update(
            body="<!-- tpl: T | ver: 1.0.0 | date: 2026-01-01 | 变更: x -->\n{{#有担保}}\n正文"), "未闭合"),
        ("无版本留痕", lambda d: d["template"].update(
            body="甲方：{{甲方全称}}", meta={}), "版本留痕"),
    ]
    for label, mut, kw in cases:
        d = _copy.deepcopy(base)
        mut(d)
        rr = m.check(d, {}, filling=True)
        if not any(kw in e for e in rr["errors"]):
            err("模板引擎对「%s」没拦住（负例未命中「%s」）：%s"
                % (label, kw, "；".join(rr["errors"]) or "无错误"))
    info("模板引擎：正例通过、4 类负例全部拦下（占位符必填／漏登记／条件段未闭合／无版本留痕）")


def check_legal_crosscheck():
    """法规库交叉验证（出包硬闸）：比对算法可用、库内置信字段齐全、一致率不低于下限且不回退。

    为什么必须拦而不是只报：单源抓取的条文一旦网页本身有错字、漏字、串行，
    核验会把错的判成对的——比没有库更危险。交叉验证是唯一能自动发现这类错误的手段，
    它一旦静默失效（字段丢了、比对恒真、源集体失效），整个法条库就退化成「看起来有校验」。

    三道关：
      ① 算法关：给 legal-crosscheck.py 灌三组已知答案（全等/标点差异/漏一句），
         结果不对说明比对失效——比「率低了」更严重，直接报错。
      ② 字段关：每条必须带 verified(bool) 与 status(枚举)，且 verified 与 status 自洽；
         带 verified=true 的必须同时在 sources 里给出 ≥2 个来源标识。
      ③ 水位关：多源一致率不得低于 FLOOR（历史最低水位）——防回退。
         回退通常意味着「某个源失效了却没人发现」，这正是要拦的。
    """
    dbp = os.path.join(ROOT, "core", "legal-articles.json")
    modp = os.path.join(HERE, "legal-crosscheck.py")
    if not os.path.exists(modp):
        err("交叉验证模块缺失：scripts/legal-crosscheck.py（法规库失去多源比对能力）")
        return
    try:
        import importlib.util as _ilu
        s = _ilu.spec_from_file_location("_ck_cross", modp)
        m = _ilu.module_from_spec(s)
        s.loader.exec_module(m)
    except Exception as e:
        err("交叉验证模块无法加载：%s" % e)
        return

    # ① 算法关：三组已知答案
    a = "用人单位应当建立职工名册备查"
    cases = [
        ("全等", a, a, 1.0),
        ("标点差异", a + "。", a + "，", 1.0),
        ("漏一句", a + "用人单位自用工之日起即与劳动者建立劳动关系", a, None),
    ]
    for label, x, y, want in cases:
        c = m.compare(x, y)
        if want is not None:
            if abs(c["ratio"] - want) > 1e-6:
                err("交叉验证算法失灵（%s 场景应得 %.2f，实得 %s）——比对已不可信"
                    % (label, want, c["ratio"]))
        else:
            if c["ratio"] >= 0.985:
                err("交叉验证算法失灵（漏一句仍判一致，ratio=%s）——阈值形同虚设"
                    % c["ratio"])
    v = m.verdict([("A", a), ("B", a)])
    if not v.get("verified"):
        err("交叉验证判决失灵（两源全等却判未核）")
    v = m.verdict([("A", a)])
    if v.get("verified"):
        err("交叉验证判决失灵（单源却判已核）——这是最危险的错误，会把未核伪装成已核")

    # ② 字段关 + ③ 水位关
    if not os.path.exists(dbp):
        return          # 缺失由 check_legal_db 报，不重复
    try:
        db = json.loads(_read(dbp))
    except Exception:
        return
    laws = db.get("laws") or {}
    total = verified = 0
    bad = []
    for law, ents in laws.items():
        for no, e in ents.items():
            total += 1
            st = e.get("status")
            vf = e.get("verified")
            if not isinstance(vf, bool):
                bad.append("%s第%s条 缺 verified 字段" % (law, no))
                continue
            if st not in ("multi-ok", "single", "conflict"):
                bad.append("%s第%s条 status 非法（%r）" % (law, no, st))
                continue
            if vf != (st == "multi-ok"):
                bad.append("%s第%s条 verified 与 status 不自洽（%s/%s）" % (law, no, vf, st))
            if vf:
                verified += 1
                srcs = e.get("sources") or []
                if len(srcs) < 2:
                    bad.append("%s第%s条 标了已核却不足 2 个来源" % (law, no))
    if bad:
        err("法规库交叉验证字段有问题 %d 处：%s" % (len(bad), "；".join(bad[:5])))
        return
    if not total:
        return

    rate = verified / float(total)
    mc = db.get("_交叉验证") or {}
    claimed = (mc.get("统计") or {}).get("多源一致")
    if claimed is not None and claimed != verified:
        err("法规库口径失准：_交叉验证 记「多源一致 %d」，实测 %d" % (claimed, verified))

    # 水位线：写在本文件里，改它需要过 code review，避免「悄悄调低标准」
    # 2026-10-22 由 0.36 上调至 0.95：当日补完最后一批独立源后实测 712/712＝100%，
    # 原 0.36 是「450 条单源」时期留下的低位线，继续用它等于对回退睁一眼闭一眼。
    # 留 5 个百分点余量，容许新增某法时短暂未配第二源，但不容许大面积退化。
    FLOOR = 0.95
    if rate < FLOOR:
        err("法规库交叉验证覆盖率回退：多源一致 %d/%d＝%.1f%%，低于水位线 %.0f%%。"
            "通常是某个独立来源失效了——补源或查明原因后再出包，别调低水位线。"
            % (verified, total, rate * 100, FLOOR * 100))
    n_conf = sum(1 for ents in laws.values() for e in ents.values()
                 if e.get("status") == "conflict")
    if n_conf:
        err("法规库存在 %d 条多源冲突未裁决：引用前必须人工比对官方文本"
            "（明细见 report/legal-crosscheck.json）" % n_conf)
    info("法规库交叉验证：%d/%d 条多源一致（%.1f%%），单源 %d 条，冲突 %d 条"
         % (verified, total, rate * 100, total - verified - n_conf, n_conf))


def check_cite_alignment():
    """规则库条号引用与法条库对位（出包硬闸）。

    **为什么单列一道关**：交叉验证管的是「库里条文本身可不可信」，管**不**了
    「规则里引的条号是不是那一条」。2026-10-22 实测就栽在这上面——《反不正当竞争法》
    2025-06-27 第二次修订、2025-10-15 施行后条号整体后移，而规则库仍在引「第 7 条商业贿赂」
    （新法第 7 条已是混淆行为）。此时交叉验证可以 100% 全绿：库是对的，规则是错的，
    没有任何一道关在看两者的**对位关系**。

    判据见 legal-verify.py --audit-rules：按「文件＋法名」归组比条号集合与条文 sha256，
    条号位移或条文变动即判错。此处只做调用与结果转述，不重复实现。
    """
    modp = os.path.join(HERE, "legal-verify.py")
    if not os.path.exists(modp):
        err("法条核验模块缺失：scripts/legal-verify.py（规则库条号对位无从校验）")
        return
    basep = os.path.join(ROOT, "core", "_cite-baseline.json")
    if not os.path.exists(basep):
        err("条号引用基线缺失：core/_cite-baseline.json（跑 "
            "python scripts/legal-verify.py --audit-rules --update 生成）")
        return
    try:
        r = subprocess.run([sys.executable, modp, "--audit-rules"],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        err("条号对位自检跑不起来：%s" % e)
        return
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"引用 (\d+) 条｜基线 (\d+) 条｜条号位移 (\d+) 处｜条文变动 (\d+) 条",
                  out)
    if not m:
        err("条号对位自检输出无法解析（脚本可能崩了）：%s" % out.strip()[:200])
        return
    n_cur, n_base, n_shift, n_chg = (int(x) for x in m.groups())
    if r.returncode != 0 or n_shift or n_chg:
        # 把脚本给的明细原样带出来，别让读的人再去翻日志
        detail = "\n".join(l for l in out.splitlines()
                           if l.startswith("- `") or l.startswith("    "))
        err("规则库条号引用与法条库对不上：条号位移 %d 处、条文变动 %d 条。"
            "改了条号须确认对应的是同一规范内容；库换了版本须复核规则里对该条的描述。"
            "确认无误后跑 --audit-rules --update 刷基线。\n%s"
            % (n_shift, n_chg, detail[:1200]))
        return
    info("规则库条号对位：%d 条引用与基线逐条一致（对照 %d 条基线）" % (n_cur, n_base))


def check_legal_db():
    """法条核验库自洽：结构完整、条文非空、sha256 与正文对得上、文档口径与实收条数一致。
    背景：库是「核验真值源」，一旦混入残缺/错位条文，核验会把错的判成对的——
    比没有库更危险。故此处常驻校验，随每次改动必跑。"""
    p = os.path.join(ROOT, "core", "legal-articles.json")
    if not os.path.exists(p):
        err("法条核验库缺失：core/legal-articles.json（python maint/tools/build-legal-db.py 生成）")
        return
    try:
        db = json.loads(_read(p))
    except Exception as e:
        err("法条核验库解析失败：%s" % e)
        return
    laws = db.get("laws") or {}
    if not laws:
        err("法条核验库为空：laws 段无内容")
        return
    import hashlib
    bad = []
    total = 0
    for law, ents in laws.items():
        for no, e in ents.items():
            total += 1
            txt = (e or {}).get("text") or ""
            if len(txt) < 6:
                bad.append("%s第%s条正文过短" % (law, no))
                continue
            want = hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]
            if e.get("sha256") != want:
                bad.append("%s第%s条 sha256 不符" % (law, no))
            if not e.get("anchor"):
                bad.append("%s第%s条缺特征句" % (law, no))
            # 条文里混进页眉页脚/导航，说明抓取解析出错位
            if re.search(r"(版权所有|ICP备|责任编辑|上一篇|相关链接|扫一扫)", txt):
                bad.append("%s第%s条含页面噪声" % (law, no))
    if bad:
        err("法条核验库有问题 %d 处：%s" % (len(bad), "；".join(bad[:5])))
        return
    # 文档口径
    sm = re.search(r"现收录\s*(\d+)\s*部法、(\d+)\s*条", _read(os.path.join(ROOT, "SKILL.md")))
    if sm:
        dl, dn = int(sm.group(1)), int(sm.group(2))
        if dl != len(laws) or dn != total:
            err("SKILL.md 法条库口径失准：写「%d 部法、%d 条」，实测 %d 部、%d 条"
                % (dl, dn, len(laws), total))
            return
    miss = db.get("missing") or {}
    info("法条核验库: %d 部法 / %d 条（未收录待人工核：%s）"
         % (len(laws), total,
            "、".join("%s%s" % (k, v) for k, v in miss.items()) or "无"))


# ---------------------------------------------------------------- 清理
def _pycache_dirs():
    out = []
    for r, d, _f in os.walk(ROOT):
        if "__pycache__" in d:
            out.append(os.path.join(r, "__pycache__"))
    return out


def clean():
    import shutil
    n_dir = n_pyc = 0
    for c in _pycache_dirs():
        shutil.rmtree(c, ignore_errors=True)
        n_dir += 1
    for p in glob.glob(os.path.join(ROOT, "**", "*.pyc"), recursive=True):
        try:
            os.remove(p)
            n_pyc += 1
        except OSError:
            pass
    info("已清理 __pycache__ 目录 %d 个、.pyc 文件 %d 个" % (n_dir, n_pyc))


# ---------------------------------------------------------------- 工具
def _read(p):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(p, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _walk(base, exts):
    for r, d, fs in os.walk(base):
        d[:] = [x for x in d if x != "__pycache__"]
        for x in fs:
            if x.lower().endswith(exts):
                yield os.path.join(r, x)


def main():
    ap = argparse.ArgumentParser(description="文档合规审查助手AI合同 · 结构与环境自检（Python 版，替代 check.ps1）")
    ap.add_argument("--sign", action="store_true", help="生成/刷新脚本完整性指纹")
    ap.add_argument("--verify", action="store_true", help="仅校验脚本指纹")
    ap.add_argument("--strict", action="store_true", help="指纹不一致时视为错误")
    ap.add_argument("--clean", action="store_true", help="清理 __pycache__ / *.pyc 后继续自检")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    a = ap.parse_args()

    if a.clean:
        clean()

    if a.sign:
        sign()
        _report(a.quiet)
        return 0

    if not a.verify:
        check_required_files()
        check_assets()
        check_industries()
        check_deenterprise()
        check_rule_ids()
        check_id_group_whitelist()
        check_rule_baseline()
        check_disclaimer()
        check_batch_guidance()
        check_md_fences()
        check_header_version()
        check_rule_metadata()
        check_smoke_count()
        check_doc_number_caliber()
        check_package_fields()
        check_platform_limit()
        check_sample_baseline()
        check_legal_db()
        check_legal_crosscheck()
        check_cite_alignment()
        check_freshness_engine()
        check_net_tiers()
        check_security_matrix()
        check_tpl_engine()
        check_verify_engine()
        check_imbalance_engine()
        check_reproducible_build()
        check_gitignore()
        check_skill_ext_lowercase()
        check_version_consistency()
        check_manifest_version()
        check_config()
        check_hardcoded_paths()
        check_security()
    verify(strict=a.strict)
    return _report(a.quiet)


def _report(quiet):
    if not quiet:
        if INFOS:
            for m in INFOS:
                print("[i] " + m)
        if WARNS:
            for m in WARNS:
                print("[W] " + m)
    print("==== 校验结果 ====")
    if ERRS:
        for m in ERRS:
            print("[E] " + m)
        print("错误 %d 项，警告 %d 项 —— 未通过。" % (len(ERRS), len(WARNS)))
        return 1
    print("通过：结构 / 字段 / 头标 / 去企业化 / 规则ID / 免责声明 / 长文档分批 / 规则元数据 / 样例基线 / 版本一致性 / 出包字段 / 平台上限 / 配置 / 安全项 无错误（警告 %d 项，提示 %d 项）。"
          % (len(WARNS), len(INFOS)))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
