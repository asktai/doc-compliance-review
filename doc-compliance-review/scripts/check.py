#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E3  门禁自检类：文件内出现网络关键字，但自身不发起联网
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
import inspect

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INTEGRITY = os.path.join(HERE, ".integrity.json")

# 脱敏类数的真源：直接取 desensitize.py 的两个常量，不在本文件另写一份
# （12.2 同一事实只许一个真源；此处一旦抄成字面量，改口径时必漂）。
_sys.path.insert(0, HERE)
try:
    import desensitize as _ds
except Exception:
    _ds = None

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
def _is_distribution():
    """本副本是否**分发包**（`pack.py` 出包时在 version.json 写入 `_分发副本: true`）。

    分发包与开发源在「沿革」这件事上判据正好相反：分发包里**没有** history、**没有**
    VERSION.md（历史不给看）；开发源里**必须有**这两样（否则版本链校验全成空转）。
    只看包内自带标记，不靠 `.git`／`_发布包` 之类的路径特征——那些在别人机器上不成立。
    """
    try:
        with open(os.path.join(ROOT, "version.json"), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return False
    return isinstance(d, dict) and d.get("_分发副本") is True


def check_required_files():
    dist = _is_distribution()
    for f in REQUIRED_FILES:
        if f == "VERSION.md" and dist:
            continue          # 分发包按设计不带版本沿革（v3.26.2）
        if not os.path.exists(os.path.join(ROOT, f)):
            err("缺少文件: %s" % f)
    # 反向：分发包里**不得**出现 VERSION.md——130 行历史版本表，正是「历史不给看」
    # 要挡的那一份。只裁 JSON 的 history 不够，文档侧也得挡（两处同一口径）。
    if dist and os.path.exists(os.path.join(ROOT, "VERSION.md")):
        err("分发包内出现 VERSION.md（版本沿革）——沿革不随技能分发，对外只提供最新一版信息；"
            "出包漏排或手工塞入")


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


def check_ai_tells_rules():
    """去AI味规则库咬合（v3.32.0）：core/ai-tells.json（机器真源）↔ core/03-ai-tells.md（人读版）。

    两份文件各写一遍必然分家（铁律第 12 条同型风险），故四条断言：
      ① json 可解析、规则组 ID ⊆ {A,B,C,D,X}、severity ∈ {high,mid,low}、正则全部可编译；
      ② md 的「规则组数／条数」与 json 实算一致（md 写死数字须与真源同步）;
      ③ md 五个组标题（### A · …）与 json 组 ID/名称咬合；
      ④ json 里的规则条数与「条数：N 条」声明一致。
    另与 scripts/ai-tells.py 的白名单常量咬合（引擎端 load_rules 的 ID 集须一致）。
    """
    jp = os.path.join(ROOT, "core", "ai-tells.json")
    mp = os.path.join(ROOT, "core", "03-ai-tells.md")
    if not (os.path.exists(jp) and os.path.exists(mp)):
        err("去AI味规则库：core/ai-tells.json 与 core/03-ai-tells.md 须同时存在（机器真源＋人读版）")
        return
    try:
        d = json.loads(_read(jp))
        groups = d.get("groups") or []
        n_rules = sum(len(g.get("patterns", [])) for g in groups)
        for g in groups:
            if g.get("id") not in ("A", "B", "C", "D", "X"):
                err("去AI味规则库：组 ID %r 越界（白名单 A/B/C/D/X）" % g.get("id"))
            if g.get("severity") not in ("high", "mid", "low"):
                err("去AI味规则库：组 %s severity 非法" % g.get("id"))
            for pat in g.get("patterns", []):
                try:
                    re.compile(pat["pattern"])
                except re.error as e:
                    err("去AI味规则库：组 %s 正则编译失败 %r（%s）" % (g.get("id"), pat["pattern"], e))
    except Exception as e:  # noqa: BLE001
        err("去AI味规则库：ai-tells.json 解析失败（%s）" % e)
        return
    mdsrc = _read(mp)
    m = re.search(r"规则组数[：:]\s*(\d+)\s*组\s*[／/]\s*\*\*?规则条数\*?\*?[：:]\s*(\d+)\s*条", mdsrc)
    if not m:
        err("去AI味规则库：03-ai-tells.md 缺「规则组数：N 组／规则条数：N 条」声明（守卫无从咬合）")
    else:
        if int(m.group(1)) != len(groups):
            err("去AI味规则库：md 写 %s 组，json 实算 %d 组" % (m.group(1), len(groups)))
        if int(m.group(2)) != n_rules:
            err("去AI味规则库：md 写 %s 条，json 实算 %d 条" % (m.group(2), n_rules))
    # 组标题咬合：md 的 "### A · 空洞套话" 与 json 的 (id, name)
    md_heads = dict(re.findall(r"^###\s*([A-Z])\s*·\s*(\S+)", mdsrc, re.M))
    for g in groups:
        if md_heads.get(g["id"]) not in (None, g.get("name")):
            err("去AI味规则库：md 组标题 %s·%s 与 json 组名 %s 不一致"
                % (g["id"], md_heads.get(g["id"]), g.get("name")))
    # 引擎端咬合：ai-tells.py 的 load_rules 白名单
    ep = os.path.join(HERE, "ai-tells.py")
    if os.path.exists(ep):
        esrc = _read(ep)
        m3 = re.search(r'not in \("A", "B", "C", "D", "X"\)', esrc)
        if not m3:
            err("去AI味规则库：ai-tells.py 的组 ID 白名单与守卫口径不一致（须同为 A/B/C/D/X）")
    if not ERRS or not any("去AI味规则库" in x for x in ERRS):
        info("去AI味规则库：%d 组 %d 条，json↔md↔引擎三方咬合通过" % (len(groups), n_rules))


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
# 真源是**每个脚本文件头那行 `# net-tier: En`**——不在本文件另立登记表。
# 同一事实两处写必漂（第 12 条）：中央登记表一定与代码分家，写在代码里则改档必须动那个文件。
# 本检查器只做三件事：**读标记 → 与实测比对 → 与 SECURITY.md 双向咬合**。
NET_TIER_RE = re.compile(r"^#[ \t]*net-tier:[ \t]*(E[0-3])\b", re.M)
# 行首匹配真正的 import 语句；检查器自己持有的"关键字清单"是行中间的字符串，不会自指命中。
NET_IMPORT_RE = re.compile(
    r"^[ \t]*(?:import|from)[ \t]+(?:urllib|requests|socket|http\.client|aiohttp|httpx"
    r"|smtplib|ftplib|xmlrpc)\b", re.M)
# 联网动作（含间接）：自己不 import 网络库、但调用在线档模块的网络函数，同样算联网路径。
NET_CALL_RE = re.compile(
    r"urlopen\(|requests\.(?:get|post|put)\(|socket\.(?:socket|create_connection)\("
    r"|(?:PARSE|_PARSE|parse)\.fetch\(", re.M)
TIER_MEANING = {
    "E0": "接触文档内容 → 绝对离线（零网络库）",
    "E1": "在线只读公开信息 → 须可关、离线静默降级",
    "E2": "不联网就用不成 → 须显式调用、离线明示降级",
    "E3": "门禁自检类 → 自身不发起联网",
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
        mm = re.match(r"[ \t]*(E[0-3])[ \t]*:[ \t]*([A-Za-z0-9_.\- ]+)$", line)
        if mm and all(x.endswith(".py") for x in mm.group(2).split()):
            out[mm.group(1)] = mm.group(2).split()
    return out or None


def check_net_tiers():
    """安全引擎门禁：联网按档，档位在代码里、机读、与文档咬合。

    为什么不再写「脚本全部不联网」（这是 v3.23.2 修正的一刀切）：
    那句话把**手段当成了目的**。红线是「使用者的文档不出域」，不是「有没有 urllib」——
    一刀切禁联网会连「法规库失效巡检」一起废掉，而它不联网根本做不成，
    恰是产品最值钱的部分。故分四档，并且：
      · **E0 仍然一刀切**，但切在「**接触文档**」上，不切在「联网」上——这是唯一该切的地方；
      · **E2 承认「不联网就用不成」**，代价换到别处补：须显式调用、离线须明示降级；
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
        err("档位取值非法（只许 E0—E3）：%s" % "、".join(bad))
        return

    imp_hit, call_hit = set(), set()
    for n in tiers:
        txt = _read(os.path.join(HERE, n))
        if NET_IMPORT_RE.search(txt):
            imp_hit.add(n)
        if NET_CALL_RE.search(txt):
            call_hit.add(n)
    by = lambda t: sorted(n for n, v in tiers.items() if v == t)  # noqa: E731

    # ① E0（接触文档）：**唯一保留的一刀切**——零网络库
    bad_l0 = [n for n in by("E0") if n in imp_hit]
    if bad_l0:
        err("E0 档（接触文档内容）脚本含网络库 import：%s。文档一经手就不得有任何出网路径——"
            "要么删掉，要么先改档并在 SECURITY.md 写明理由（第 26 条）" % "、".join(bad_l0))
        return
    # ② E1/E2：标了"会联网"就得真有联网路径——**档位不许是空头标签**
    online = by("E1") + by("E2")
    dead = [n for n in online if n not in (imp_hit | call_hit)]
    if dead:
        err("标为在线档却找不到任何联网路径：%s——档位不能是空头标签，要么接上实现，要么改回 E0"
            % "、".join(dead))
        return
    # ③ E3：门禁自检类只许持有"网络关键字清单"，不许真 import
    bad_l3 = [n for n in by("E3") if n in imp_hit]
    if bad_l3:
        err("E3 档（门禁自检类）不该真 import 网络库：%s；它只应持有用于检查别人的关键字清单"
            % "、".join(bad_l3))
        return
    # ④ E0 档不得注册「在线类」开关——假开关的温床（2026-11-06 新补，此前是盲区）
    #
    # 抓到的事：`legal-search.py` 自标 E0、全文无网络库，却注册着 `--online`；
    # 该参数**只在未命中分支打印一段说明**，命中路径上被完全忽略。使用者打了它以为在联网，
    # 实际什么也没发生——25.3「承诺大于实际」。而原作的三条判据都在查 E1/E2 的**空头标签**
    # （标了在线却没有联网路径），反方向（标了离线却挂着在线开关）**一条都没看**。
    # 判据只认 argparse 注册这一形态：要保留兼容写法，就该自己拦 sys.argv 并拒绝，不注册。
    # 判据须容得下 argparse 的**惯用写法** `add_argument("-o", "--online")`——
    # 第一版只认「紧跟在左括号后的长旗」，独立复核当场指出现实中最常见的
    # 「短旗＋长旗」形态反而漏掉（那不算刻意规避，是标准写法）。
    # 刻意混淆（`"--" + "online"`、`*["--online"]`）仍可绕过，**如实记在这里**：
    # 但 E0 的结构性底座是「禁网络库」（NET_IMPORT_RE），伪造一个开关骗到的是提示语，
    # 不是数据——真要出网还得 import，那一关绕不过去。
    ONLINE_FLAG_RE = re.compile(
        r"""add_argument\([^)\n]{0,120}?["']--(?:online|net|remote|fetch|download)\b""")
    fake = [n for n in by("E0") if ONLINE_FLAG_RE.search(_read(os.path.join(HERE, n)))]
    if fake:
        err("E0 档脚本注册了在线类开关：%s——E0 承诺零出网路径，注册这类开关只会让使用者"
            "以为本脚本会联网（legal-search.py 的 `--online` 就是这么假的：只打印说明，"
            "命中路径上被完全忽略）。要保留兼容写法，请在 main() 开头自己拦 sys.argv 并"
            "**明确拒绝＋指路**，不要注册进 argparse（第 26 条）。"
            "注意：这条判据看不见手动读 sys.argv 的通道——故那种写法**只许用于拒绝，"
            "不得据 argv 分支执行任何动作**，否则就成了绕过本判据的后门" % "、".join(fake))
        return
    # ⑤ 与 SECURITY.md 双向咬合（文档一套代码一套，正是 25.2 的事故形态）
    doc = _doc_net_tiers()
    if doc is None:
        err("SECURITY.md 缺机读档位块（NET-TIERS）——名单无法与代码比对，改一处就分家（25.2）")
        return
    for t in ("E0", "E1", "E2", "E3"):
        a, b = by(t), sorted(doc.get(t) or [])
        if a != b:
            err("SECURITY.md 的 %s 档名单与脚本自标不一致：文档 %s／代码 %s；两处须同步"
                % (t, b, a))
            return
    info("安全引擎：联网分四档——E0 %d 个（接触文档，零网络库）／E1 %d 个（在线只读公开信息，可关）"
         "／E2 %d 个（不联网就用不成，须显式调用）／E3 %d 个（门禁自检，自身不联网）；"
         "名单与 SECURITY.md 双向一致" % (len(by("E0")), len(by("E1")), len(by("E2")), len(by("E3"))))


# 真正的"带 shell 的调用"，而非 `shell=True` 这个子串（后者会让检查器自指命中）。
SHELL_TRUE_RE = re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True")
# 同理：只认「策略值紧跟 ExecutionPolicy」这一形态，不搜裸关键字（否则检查器自指命中）
EXEC_BYPASS_RE = re.compile(r"ExecutionPolicy\s+(Bypass|Unrestricted|RemoteSigned|AllSigned)", re.I)

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
    """数据层：文档不出网——接触文档的 E0 档零网络库（与 26.5.2 同一判据，不另写一套）"""
    tiers = _net_tiers()
    l0 = [n for n, v in tiers.items() if v == "E0"]
    bad = [n for n in l0 if NET_IMPORT_RE.search(_read(os.path.join(HERE, n)))]
    return (not bad,
            "E0 档 %d 个脚本零网络库" % len(l0) if not bad else "越界 %s" % ", ".join(bad))


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


def _sec_mask_defaults():
    """数据层：脱敏口径默认值——对外出域须 10 类全脱，且纯本地链路必须取这个口径。

    为什么要单列：`ALL_TYPES`（10 类）与 `REVIEW_TYPES`（6 类）是两个常量，
    而"涉密走纯本地链路"这条承诺全靠 `local-only.py` 的默认值取前者撑着。
    有人把它改成后者，**涉密文档就只脱 6 类就出去了，而门禁此前全绿**
    （本条是 v3.23.4 复盘「登记表守不住完备性」时补的，此前漏登记）。
    """
    d = _read(os.path.join(HERE, "desensitize.py"))
    m = re.search(r"^ALL_TYPES\s*=\s*\((.*?)\)\s*(?:#.*)?$", d, re.M | re.S)
    if not m:
        return (False, "desensitize.py 里找不到 ALL_TYPES（对外出域口径的实现被删）")
    n = len([x for x in m.group(1).replace("\n", "").split(",") if x.strip()])
    if n != 10:
        return (False, "ALL_TYPES 实为 %d 类——对外出域口径被改少（应为 10 类全脱）" % n)
    lo = _read(os.path.join(HERE, "local-only.py"))
    if "_d.ALL_TYPES" not in lo:
        return (False, "local-only.py 的默认口径不再取 desensitize.ALL_TYPES——"
                       "纯本地链路可能偷偷降成审查用的 6 类")
    return (True, "对外出域 10 类全脱，纯本地链路默认取该口径")


def _sec_no_exec_bypass():
    """代码层：无执行策略绕过——不得要求使用者以绕过 PowerShell 执行策略的方式运行。

    判据同 27.3.2：只认**策略值跟在 ExecutionPolicy 之后**这一形态，
    不搜裸关键字（检查器自己要写这些词来扫别人，裸搜必自指命中）。
    """
    bad = [os.path.basename(p) for p in glob.glob(os.path.join(HERE, "*.py"))
           if EXEC_BYPASS_RE.search(_read(p))]
    bad += [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.ps1")) + glob.glob(os.path.join(ROOT, "*.bat"))
            if EXEC_BYPASS_RE.search(_read(p))]
    return (not bad, "无执行策略绕过参数" if not bad else "存在绕过面 %s" % ", ".join(sorted(set(bad))))


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


# 登记表字段（27.3）：
#   编号／机制／层／**承诺词组**／判据函数 or None／锚点 or None／强度
#
# 两处都是 v3.23.4 复盘后的加固，别再退回旧写法：
#   · 承诺词组：必须**同一行**里全部出现才算咬合（旧写法是单个关键词 `in` 全文，
#     实测把「默认关」改成「可关」仍全绿——拿"词在别处"冒充"承诺还在"）。
#   · 锚点：写成 (函数名, 判据行特征)，**只验名字在是不够的**——
#     实测删光 `check_security()` 里的私有库整段，登记表照样报"逐条落实"。
SEC_MATRIX = (
    ("M1", "文档不出网（接触文档的脚本零出网路径）", "数据层",
     ("数据出域", "E0"), _sec_doc_no_net, None, "机械"),
    ("M2", "映射表隔离（默认落本机隔离目录）", "数据层",
     ("映射表", "隔离目录"), _sec_map_isolated, None, "机械"),
    ("M3", "私有库默认不打进发布包", "数据层",
     ("private/", "排除"), _sec_private_not_packed, None, "机械"),
    ("M4", "查更新默认不发请求（可联网 ≠ 会自动联网）", "数据层",
     ("查更新", "默认关"), _sec_online_off, None, "机械"),
    ("M5", "原件不改（产物一律新建）", "产物层",
     ("不改动原始文件", "原件只读"), _sec_original_intact, None, "行为"),
    ("M6", "输出隔离（按文档名分目录，多客户不混放）", "产物层",
     ("输出隔离", "限权"), _sec_output_isolated, None, "机械"),
    ("M7", "私有库默认空（不参与审查）", "数据层",
     ("私有库默认空", "空库"), None, ("check_security", r"PR-\\d+"), "弱"),
    ("M8", "不留缓存（脚本禁止生成 __pycache__）", "代码层",
     ("无缓存留痕", "__pycache__"), None, ("_check_no_bytecode", "dont_write_bytecode"), "弱"),
    ("M9", "脚本防篡改（指纹基线覆盖全部脚本）", "代码层",
     ("脚本防篡改", "--verify"), _sec_fingerprint, None, "机械"),
    ("M10", "无 shell 注入面（本机工具按参数列表调用）", "代码层",
     ("参数列表", "shell"), _sec_no_shell, None, "机械"),
    ("M11", "不代装依赖（只给命令，不替人执行）", "代码层",
     ("不代装依赖", "安装命令"), _sec_no_auto_install, None, "机械"),
    ("M12", "企业词表外置（脚本内不含任何企业名）", "代码层",
     ("企业词表外置", "deidentify-words"), None, ("check_deenterprise", "deidentify-words"), "弱"),
    ("M13", "脱敏口径默认值（对外出域 10 类全脱，纯本地链路取该口径）", "数据层",
     ("10 类全脱", "对外出域"), _sec_mask_defaults, None, "机械"),
    ("M14", "无执行策略绕过（纯 Python 校验，不要求绕过 PowerShell）", "代码层",
     ("无执行策略绕过", "PowerShell"), _sec_no_exec_bypass, None, "机械"),
)


def _sec_claims(sec):
    """完备性反查：对外文档里**每一条承诺**都必须认领一个机制编号（或明示「人工」）。

    为什么需要这一段：登记表能保证"登记了的都有判据"，**保证不了有没有漏登记**——
    12 条最初是人工读文档归纳的，而"无执行策略绕过""脱敏口径默认值"两条就漏了
    （v3.23.4 复盘实测）。故改为**从文档反查**：先数出文档到底承诺了哪些
    （七条 C／八不 B／九项措施 T，编号由文档自己给出），再看认领表是否逐条认领。
    **多一条承诺没人认领即报错，多一条机制没人认领也报错**。

    "人工"是合法归属：有些承诺守的是使用者的动作，机器判不了；
    **写明"人工"不算漏，闷着不写才算漏**。
    """
    if not sec:
        return (False, "读不到 SECURITY.md")
    # ① 文档实际承诺了哪些（编号由文档给出，门禁不推算，避免"数行数"式隐式编号漂移）
    cs = re.findall(r"^\|\s*\*\*(C\d+)\*\*", sec, re.M)
    ts = re.findall(r"^\|\s*\*\*(T\d+)\*\*", sec, re.M)
    b_sec = re.search(r"## 四、操作红线.*?(?=\n## )", sec, re.S)
    bs = ["B%d" % i for i in range(1, len(re.findall(r"^\d+\.\s", b_sec.group(0), re.M)) + 1)] if b_sec else []
    promised = set(cs) | set(bs) | set(ts)
    if not promised:
        return (False, "SECURITY.md 里解析不出承诺编号（C／B／T 三族都没了）")
    # ② 认领表：| C1 文档不出域 | M1 | 机械 |
    rows = re.findall(r"^\|\s*((?:C|B|T)\d+)\b[^\|]*\|\s*([^\|]+?)\s*\|", sec, re.M)
    claimed = {}
    for cid, val in rows:
        claimed.setdefault(cid, []).extend(
            [v.strip() for v in re.split(r"[、,]", val) if v.strip()])
    bad = []
    miss = sorted(promised - set(claimed))
    if miss:
        bad.append("无人认领的承诺 %s（新增承诺必须来认领表登记）" % ", ".join(miss))
    ghost = sorted(set(claimed) - promised)
    if ghost:
        bad.append("认领表里有不存在的承诺 %s（承诺已删，认领未清）" % ", ".join(ghost))
    mids = {m[0] for m in SEC_MATRIX}
    illegal = sorted({v for vs in claimed.values() for v in vs if v not in mids and v != "人工"})
    if illegal:
        bad.append("认领了不存在的机制 %s" % ", ".join(illegal))
    orphan = sorted(mids - {v for vs in claimed.values() for v in vs})
    if orphan:
        bad.append("无人认领的机制 %s（没有对外承诺认领它——要么补承诺，要么删机制）" % ", ".join(orphan))
    return (not bad, "；".join(bad)) if bad else (
        True, "承诺 %d 条全部认领（C%d／B%d／T%d），无孤儿机制" % (len(promised), len(cs), len(bs), len(ts)))


def check_security_matrix():
    """安全机制逐条自检：登记在册的每条机制，逐条跑判据并**如实公布强度**。

    与 `check_net_tiers()` 的分工：那条管"**谁可以联网**"，本条管"**承诺过的安全机制是不是真装上了**"。
    两条都不复制实现，只钉落点——**登记表与实现分家是 25.2 的事故形态，安全承诺尤其经不起**。

    强度必须公布：把"弱（锚点）"混在"机械"里报"逐条落实"，
    **这句汇总自己就成了新的空头承诺**（第 25 条形态，v3.23.4 复盘实测）。
    """
    sec_p = os.path.join(os.path.dirname(HERE), "SECURITY.md")
    sec = _read(sec_p) if os.path.exists(sec_p) else ""
    lines = sec.splitlines()
    bad_all, layers, strengths = [], {}, {}
    for mid, name, layer, doc_words, probe, anchor, strength in SEC_MATRIX:
        layers.setdefault(layer, []).append(mid)
        strengths.setdefault(strength, []).append(mid)
        if probe is not None:
            try:
                ok, detail = probe()
            except Exception as e:      # 判据跑不起来＝落点被删，与"判据失败"同罪
                ok, detail = False, "判据跑不起来：%r（落点可能被删）" % (e,)
        else:
            # 锚点型（27.3.3）：不仅验函数还在，**还要验判据行还在**——
            # 只验名字在的话，把函数里的检查内容删光也照样绿（v3.23.4 复盘实测）。
            fn_name, needle = anchor
            fn = globals().get(fn_name)
            if not callable(fn):
                ok, detail = False, "锚点 %s 不存在或不可调用" % fn_name
            else:
                body = inspect.getsource(fn)
                ok = re.search(needle, body) is not None
                detail = ("由 %s() 负责，判据行在位（%s）" % (fn_name, needle) if ok
                          else "%s() 里找不到判据行 %s——那段检查可能被删了" % (fn_name, needle))
        if not ok:
            bad_all.append("%s %s：%s" % (mid, name, detail))
        # 咬合：词组须在**同一行**全部出现（单个关键词 `in` 全文会被"词在别处"骗过）
        if doc_words and not any(all(w in ln for w in doc_words) for ln in lines):
            bad_all.append("%s %s：SECURITY.md 里找不到同时含 %s 的承诺句——"
                           "代码有、文档没说，或文档把承诺改弱了"
                           % (mid, name, "、".join("「%s」" % w for w in doc_words)))
    ok_claim, claim_detail = _sec_claims(sec)
    if not ok_claim:
        bad_all.append("完备性反查未过 —— %s" % claim_detail)
    if bad_all:
        for b in bad_all:
            err("安全机制未落实 —— %s" % b)
        return
    weak = strengths.get("弱", [])
    info("安全机制：%d 条在册逐条落实（数据层 %d／产物层 %d／代码层 %d）"
         % (len(SEC_MATRIX), len(layers.get("数据层", [])), len(layers.get("产物层", [])),
            len(layers.get("代码层", []))))
    info("安全机制强度：机械 %d／行为 %d／弱（锚点）%d＝%s；%s"
         % (len(strengths.get("机械", [])), len(strengths.get("行为", [])), len(weak),
            ", ".join(weak) if weak else "无", claim_detail))


def _check_online_gate(data=None):
    """只守一件事：出厂配置**不得默认联网**。

    分档由 `check_net_tiers()` 管（谁可以联网、谁绝不能），这里只管"默认行为"——
    **可联网 ≠ 会自动联网**。E1 的 `version.py` 允许联网查更新，但出厂必须关着，
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
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=_utf8_env(), timeout=120)
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
            # 顺序很重要：先说清「是不是输出本身不可信」，再谈判据。
            # v3.26.2 之前这里直接报「判据被删或改名」，把 GBK 乱码误诊成红线失效。
            hint = _garbled_hint(out)
            if hint:
                err(hint + "\n原始输出（乱码）：" + out.strip()[:160])
                return
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


def bytecode_leaks():
    """返回「未在首个业务 import 之前关闭字节码写入」的脚本名（空表＝合规）。

    **判据只有这一份**：门禁与冒烟都调它。此前冒烟里另抄了一份同样的 `src[:4000]` 查法，
    两处各写一遍必然分家——本文件 docstring 一加长就出现过「门禁误报漏写、冒烟也误报」，
    而它们本来就是同一条判据的两个副本。

    为什么按「首个业务 import 之前」定位而不按固定字数：开关只有写在**任何 import 之前**
    才管用，与文件头多长无关；取固定字数只是一种近似，文档一长就把开关挤出窗口，
    报出来是「明明写了却判漏写」——量的位置不对，结论就与事实相反。
    """
    bad = []
    for p in _script_files():
        if not p.endswith(".py") or os.path.basename(p) == "_config.py":
            continue   # _config.py 自身就是这个开关的实现方，也是被 import 的第一站
        lines = _read(p).splitlines()
        stop = len(lines)
        for i, ln in enumerate(lines):
            _s = ln.strip()
            if _s.startswith(("import ", "from ")) and _s not in ("import sys", "import sys as _sys"):
                stop = i
                break
        head = "\n".join(lines[:stop])
        if "_sys.dont_write_bytecode" not in head and "sys.dont_write_bytecode" not in head:
            bad.append(os.path.basename(p))
    return bad


def _check_no_bytecode():
    """每个脚本都必须在 import 之前关掉字节码写入——文档承诺「脚本禁止生成 __pycache__」。

    为什么要逐个查：`sys.dont_write_bytecode = True` 只有写在**模块被 import 之前**才管用，
    写在文件中间或漏写，被别的脚本 import 一次就会在技能目录里留下 .pyc。
    实测漏写是静默的——CLI 直跑不报错，只有被 import 时才留痕，肉眼看不出来。
    这既是「无缓存留痕」的技术措施，也影响 `pack.py` 出包的确定性（包里会混进 .pyc）。
    """
    bad = bytecode_leaks()
    if bad:
        err("以下脚本未在文件头关闭字节码写入（被 import 时会在技能目录留下 __pycache__）："
            "%s；应在首个 import 前加 `import sys as _sys` ＋ `_sys.dont_write_bytecode = True`"
            % ", ".join(bad))
        return
    info("缓存防护: %d 个脚本均在 import 前关闭字节码写入（被 import 也不留 .pyc；"
         "计数不含门禁自身 check.py）"
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
                 "；本技能仅作为辅助法律工作，不构成法律意见，不可直接作为决策依据；条文检索与适用要件呈现"
                 "仅为法律信息提供，不预测案件结果、不判断具体情形是否成立，具体适用须经执业律师结合事实认定；"
                 "输出内容须经执业律师复核后方可使用；使用风险与后果由使用者自行承担。"
                 "使用即为已知晓后果并免责作者，否则，请勿使用！")
DISC_KEYS = ["AI不能替代人工", "人工不能依赖AI", "商业使用须获作者书面授权",
             "不构成法律意见", "执业律师复核", "免责作者",
             "不预测案件结果", "不判断具体情形是否成立"]
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
            _src = _read(p)
            real = len(CORE_ID_RE.findall(_src))
            mn = re.search(r"规则数\s*\**\s*(\d+)\s*\**", head)
            if not mn:
                lack.append("规则数")
            elif int(mn.group(1)) != real:
                lack.append("规则数写%s实为%d" % (mn.group(1), real))
            # 紧邻下一行的「计数口径：159 条 ＝ 21 个组全覆盖（A3·B11·…）」是同一事实的
            # **第二处声明**。只查头部那一处不够：改总数忘改明细、或改明细忘改总数，
            # 都会让「明细加总 ≠ 总数」静默漂——而两处各自的数看着都对（12.2 两处写必漂）。
            # 判据四层，任一层不等即报：明细加总＝声明总数、声明总数＝实扫条数、
            # 声明组数＝明细项数、每组数＝实扫该组条数。四层都查才抓得住「总数对、分组错」。
            _grp = re.search(r"计数口径[^\n]*?(\d+)\s*条[^\n]*?[（(]([A-Z]\d+[^）)]*)[）)]", _src)
            if not _grp:
                lack.append("计数口径")
            else:
                _total = int(_grp.group(1))
                _pairs = re.findall(r"([A-Z])(\d+)", _grp.group(2))
                _sum = sum(int(n) for _, n in _pairs)
                _ng = re.search(r"计数口径[^\n]*?(\d+)\s*个组", _src)
                if not _pairs:
                    lack.append("计数口径明细")
                else:
                    if _sum != _total:
                        lack.append("计数口径明细加总%d≠总数%d" % (_sum, _total))
                    if _total != real:
                        lack.append("计数口径%d≠实扫%d" % (_total, real))
                    if _ng and int(_ng.group(1)) != len(_pairs):
                        lack.append("计数口径称%d组实列%d组" % (int(_ng.group(1)), len(_pairs)))
                    for _g, _n in _pairs:
                        _real_g = len(re.findall(r"\|\s*%s\d+\s*\|" % _g, _src))
                        if int(_n) != _real_g:
                            lack.append("组%s写%s实为%d" % (_g, _n, _real_g))
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
    # 两档守恒断言（v3.30.0）：快速档与全量档的项数必须相等——快档是把耗时项记 SKIP 保留占位，
    # 不是删掉条目。曾经 fast 用一条 skip 顶掉四条 check，fast=265／full=270，
    # 于是 check_smoke_count 拿 fast 的 total 去比文档就报错，表现为「装完即红」。
    # 两个键都在时才判（只跑过一档时不误报）。
    _tf, _tk = d.get("total_full"), d.get("total_fast")
    if isinstance(_tf, int) and isinstance(_tk, int) and _tf != _tk:
        err("冒烟两档项数不守恒（全量 %d 项 ／ 快速 %d 项）——快速档须用 skip 保留占位，"
            "不得删减条目；请对齐 fast 分支的 skip 与 else 分支的 check 后再跑两档"
            % (_tf, _tk))    # 只扫与冒烟/自检同一行的数字。须排除两类干扰，否则会把别的脚本的项数当成冒烟项数：
    # (1) 其他脚本所在行（check.py 的 12 项、pack.py 的 5 项都不是冒烟项数）
    # (2) 列表式表述「N 项：结构／字段／…」——那是分项的枚举，不是总数
    kw = ("smoke-test", "冒烟", "自检")
    other_scripts = ("check.py", "pack.py", "sample-baseline", "guard.py", "rule-baseline")
    bad, seen = [], 0
    for rel in ("README.md", "安装使用教程.md", "SKILL.md",
                "文档合规审查助手AI合同提示词版.md"):
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
    # v3.31.0 引擎拆分后，**格式家族清单的声明仍在 make-docx.py 的 --formats 帮助串**
    # （CLI 入口在那里），而家族的覆盖矩阵/白名单/生成器字典搬到了 format-engine.py。
    # 这里读法不变，只把路径写成「CLI 入口」，并额外与 format-engine 的 FORMAT_ALL 咬合
    # ——两处任一处漏改都会被下面这条断言抓出来。
    real_fmt = None
    mk = os.path.join(HERE, "make-docx.py")
    if os.path.exists(mk):
        m = re.search(r'"--formats".*?help="逗号分隔：([a-z,]+)', _read(mk), re.S)
        if m:
            real_fmt = len([x for x in m.group(1).split(",") if x])
    # ---- 真源 2：菜单项数（步骤 0.5 向导入口后的代码块，数「N. 」行；标题改名也不致失明）----
    real_menu = None
    sk = _read(os.path.join(ROOT, "SKILL.md")) if os.path.exists(os.path.join(ROOT, "SKILL.md")) else ""
    m = re.search(r"步骤 0\.5 向导入口.*?```\n(.*?)```", sk, re.S)
    if m:
        real_menu = len(re.findall(r"^\s*\d+\.\s", m.group(1), re.M))
    # ---- 真源 3：撰写合同要素项数（drafting-guide 要素清单里编号最大的项；标题/排版变动不致失明）----
    real_elems = None
    dg = _read(os.path.join(ROOT, "drafting-guide.md")) if os.path.exists(os.path.join(ROOT, "drafting-guide.md")) else ""
    _en = [int(x) for x in re.findall(r"^\s*Qn(?:\+\d+)?\s+(\d+)\.\s", dg, re.M)]
    if _en:
        real_elems = max(_en)
    # ---- 真源 4：内置库数 ----
    real_seed = None
    gd = os.path.join(HERE, "guard.py")
    if os.path.exists(gd):
        m = re.search(r"SEED_INDUSTRIES\s*=\s*[\[\{](.*?)[\]\}]", _read(gd), re.S)
        if m:
            real_seed = len(re.findall(r"['\"]([a-z][a-z0-9]*)['\"]", m.group(1)))

    src_note = []
    if real_fmt:  src_note.append("格式 %d" % real_fmt)
    if real_menu: src_note.append("菜单 %d 项" % real_menu)
    if real_elems: src_note.append("要素 %d 项" % real_elems)
    if real_seed: src_note.append("内置库 %d 个" % real_seed)
    # 真源解析失败＝守卫失明（v3.26.0 质检发现：菜单块标题改名、--formats 跨行，
    # 曾导致 real_menu/real_fmt 静默为 None、整条数量守卫被跳过却 0 错通过）。
    # 故解析不到一律**告警**，逼人修正则、而非假绿放行。
    blind = [n for n, v in (("格式", real_fmt), ("菜单项数", real_menu),
                            ("要素项数", real_elems), ("内置库数", real_seed)) if v is None]
    if blind:
        warn("数字口径：真源未能解析（%s），对应数量守卫已降级——请检查 make-docx.py / "
             "SKILL.md 向导块 / drafting-guide.md 要素清单 / guard.py 的真源格式是否变动"
             % "、".join(blind))
    if not src_note:
        return

    fmt_bad, menu_bad, seed_bad, elems_bad = [], [], [], []
    for rel in DOCS:
        for ln, line in enumerate(_doc_lines(rel), 1):
            # 格式数：「N 种格式」与「N 格式」（v3.28.0 起后者也拦——OPEN-ISSUES H-15 的
            # 「5 格式」不带种字漏抓缺口就此补上）。两处**精确豁免**（豁免须写清理由，不许宽泛词表）：
            #   a. 行含「☐」＝选项编号＋类别名语境（如「☐6 格式与体例降级」是侧重选项，
            #      不是格式总数——v3.25.x 立守卫时实测误伤形态）；
            #   b. 行含「侧重」＝提示词版侧重清单，同类误伤源。
            # 「N 种封装」不算（那是发布包封装格式）。
            if real_fmt:
                for m in re.finditer(r"(\d+)\s*(?:种)?\s*格式", line):
                    if "封装" in line or ".skill" in line or ".zip" in line:
                        continue
                    if "☐" in line or "侧重" in line:
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
            # 撰写合同要素项数：「N 项要素」必须＝ real_elems（v3.26.0 质检发现一处写 13、实为 15）
            if real_elems and "要素" in line:
                for ns in re.findall(r"(\d+)\s*项要素", line):
                    n = int(ns)
                    if n != real_elems:
                        elems_bad.append("%s:%d 写 %d 项要素（应为 %d）" % (rel, ln, n, real_elems))
            # drafting-guide 要素清单流水号自述须与真实项数对齐（Qn…Qn+K，K=real_elems-1）
            if real_elems and rel == "drafting-guide.md" and "每项一个全局流水号" in line:
                want = "Qn…Qn+%d" % (real_elems - 1)
                if want not in line:
                    elems_bad.append("%s:%d 流水号自述未写成 %s（实为 %d 项）" % (rel, ln, want, real_elems))

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
    if elems_bad:
        err("撰写合同要素项数失准（真源 drafting-guide 要素清单共 %d 项）：%s"
            % (real_elems, "；".join(elems_bad)))

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

    # ---- 真源 5：通用规则条数（H-15 最后一条缺口，2026-11-06 补）----
    # 该数字在四份文档里写了 12 处，而原守卫只咬「core/01 头部 规则数 N」与
    # 「README 通用库 N 条」两种措辞——实测 SKILL.md 5 行全漏。而 README 对外写着
    # 「规则条数（159 条）已纳入常驻校验」（见 check_rules_meta 与 README 末节），
    # 承诺大于实际（25.3：承诺有例外必须写进句子）。
    # 难点在**措辞**不在数值：`N 条` 满文档都是（20 部法 725 条、民法典第 585 条、
    # PIPL 73 条、几条规则…），裸正则必假红。故只认下列**明确指涉规则条数**的措辞。
    # **宁漏不假红**：漏了只是覆盖不足（已在 README 写明覆盖到哪些措辞），
    # 假红会让人干脆把守卫关掉（12.5.9「噪声冒充红线 → 脱敏」）。
    real_rules = None
    _c01 = os.path.join(ROOT, "core", "01-general-risk-rules.md")
    if os.path.exists(_c01):
        real_rules = len(CORE_ID_RE.findall(_read(_c01)))
    # (正则, 是否强措辞)。**强措辞命中即判、不做法条豁免**——「规则库 N 条」这种话
    # 不可能是在说法条，若还允许豁免，等于给真错留后门（2026-11-06 独立复核 I6 实测：
    # 「规则库 158 条法规」因紧跟一个"法"字被放过）。弱措辞（数字清单、表格单元格）
    # 本身不含指涉词，才按**法条句式**豁免。
    RULE_PATS = (
        (r"规则\s*数\s*\**\s*(\d+)", True),                            # 规则数 159
        (r"通用(?:库|层|的)?[（(]?\s*\**\s*(\d+)\s*\**\s*条", True),   # 通用的 159 条／通用库（159 条）
        (r"规则库\s*\**\s*(\d+)\s*\**\s*条", True),                   # 规则库 159 条
        (r"(\d+)\s*\**\s*条\s*\**\s*规则(?!库)", True),                # 159 条规则（「N 条规则库」属去AI味库）
        (r"对标\s*\**\s*(\d+)\s*\**\s*条", True),                     # 对标 159 条
        (r"规则条数[（(]?\s*\**\s*(\d+)\s*\**\s*条", True),            # 规则条数（159 条）
        (r"[：:]\s*(\d{2,4})\s*条(?=[、，])", False),                   # 「数字只报实测值：159 条、…」顿号清单
        (r"\|\s*\**(\d{3})\s*\**\s*＋", False),                        # 表格三库计数「| 159 ＋ 9 ＋ 私有 |」
        (r"\|\s*\**(\d{3})\s*\**\s*条\s*\**\s*\|", False),             # 表格单元格「| **159 条** |」
    )

    # ---- 真源 6：交付物类型数（`--types` 的 slug）与脱敏两层类数 ----
    # 难点是**同形不同义**。实测分布：`10 类交付物`（真源 `--types` 的 10 个 slug）、
    # `10 类全脱`（真源 `desensitize.ALL_TYPES` 的 10 个字段类）、`审查用 6 类`
    # （真源 `REVIEW_TYPES` 的 6 个）。三处数字恰好 10／10／6，**一条 `(\d+) 类`
    # 会把三件事混成一个判据**——哪天脱敏扩到 12 而交付物仍 10，立刻假红。
    # 故按语义词分流：全脱／外发用 → ALL_TYPES；审查用 → REVIEW_TYPES；其余 → --types。
    # 同样宁漏不假红：`其余 8 类`（＝10 减默认两类）、`第 10 类`（序号）、
    # `4 类维护触发词`、`15 项要素` 一概不碰。
    real_types = real_mask = real_review = None
    if os.path.exists(mk):
        m = re.search(r'"--types".*?help="逗号分隔：([a-z,]+)', _read(mk), re.S)
        if m:
            real_types = len([x for x in m.group(1).split(",") if x])
    if _ds is not None:
        real_mask = len([x for x in _ds.ALL_TYPES.split(",") if x])
        real_review = len([x for x in _ds.REVIEW_TYPES.split(",") if x])
    TYPE_PATS = (
        (r"(\d+)\s*类\s*[×xX]\s*(\d+)\s*(?:格式|家族)", "types2"),  # 10 类 × 8 格式
        (r"(\d+)\s*类全脱", "mask"),
        (r"外发用[^0-9\n]{0,12}?(\d+)\s*类", "mask"),
        (r"(\d+)\s*类逐项", "mask"),
        (r"审查用[^0-9\n]{0,12}?(\d+)\s*类", "review"),
        (r"(\d+)\s*类(?:审查)?交付物", "types"),
        (r"交付物\s*\**\s*(\d+)\s*\**\s*类", "types"),
        (r"交付物类型[（(][^）)\n]{0,14}?(\d+)\s*类", "types"),
        (r"类型[（(]\s*(\d+)\s*类", "types"),
        (r"类型清单固定为(?:这)?\s*\**\s*(\d+)\s*类", "types"),
        (r"上述\s*(\d+)\s*类中文名", "types"),
        (r"(\d+)\s*类\s*Word", "types"),
        (r"一次把\s*(\d+)\s*类全部列出", "types"),
        (r"全部\s*(\d+)\s*类", "types"),
        (r"(\d+)\s*类／(\d+)\s*类", "pair"),                      # 「6 类／10 类占位符替换」
    )

    rules_bad, types_bad = set(), set()
    for rel in DOCS:
        for ln, line in enumerate(_doc_lines(rel), 1):
            if real_rules:
                for pat, strong in RULE_PATS:
                    for m in re.finditer(pat, line):
                        v = int(m.group(1))
                        if v == real_rules:
                            continue
                        ctx = line[max(0, m.start() - 20):m.end() + 12]
                        if "AI味" in ctx or "ai-tells" in ctx:
                            continue          # 去AI味规则库另有真源（33 条），不属本条
                        # 法条豁免只认**句式**，不认"附近有法字"（I6）：`部法 725 条`／`第 585 条`。
                        # 强措辞不豁免——那种话不可能是法条。
                        if not strong and re.search(r"(?:部法|第)\s*\**\s*%d\s*\**\s*条" % v, ctx):
                            continue
                        rules_bad.add("%s:%d 写 %d 条（应为 %d）" % (rel, ln, v, real_rules))
            for pat, kind in TYPE_PATS:
                for m in re.finditer(pat, line):
                    if kind == "types2":
                        v, nf = int(m.group(1)), int(m.group(2))
                        if real_types and v != real_types:
                            types_bad.add("%s:%d 「类×格式」写 %d 类（应为 %d）"
                                          % (rel, ln, v, real_types))
                        if real_fmt and nf != real_fmt:
                            types_bad.add("%s:%d 「类×格式」写 %d 格式（应为 %d）"
                                          % (rel, ln, nf, real_fmt))
                        continue
                    if kind == "pair":
                        v, v2 = int(m.group(1)), int(m.group(2))
                        if real_review and v != real_review:
                            types_bad.add("%s:%d 「审查用/外发用」写 %d 类（应为 %d）"
                                          % (rel, ln, v, real_review))
                        if real_mask and v2 != real_mask:
                            types_bad.add("%s:%d 「审查用/外发用」写 %d 类（应为 %d）"
                                          % (rel, ln, v2, real_mask))
                        continue
                    v = int(m.group(1))
                    exp, label = {"types": (real_types, "交付物类型"),
                                  "mask": (real_mask, "对外全脱"),
                                  "review": (real_review, "审查用" )}[kind]
                    if exp and v != exp:
                        types_bad.add("%s:%d %s类数写 %d（应为 %d）" % (rel, ln, label, v, exp))

    # 真源解析不到＝守卫失明。**不许静默**：与本函数前段那组（格式／菜单／要素／内置库）
    # 同一口径——解析失败一律告警，逼人修正则，而不是让这三条守卫无声停用还报「通过」。
    _blind_five = [n for n, v in (("通用规则条数", real_rules), ("交付物类型数", real_types),
                                  ("对外全脱类数", real_mask), ("审查用类数", real_review))
                   if v is None]
    if _blind_five:
        warn("数字口径：真源未能解析（%s），对应数量守卫已降级——请检查 core/01-general-risk-rules.md /"
             " make-docx.py 的 --types 帮助串 / desensitize.py 的 ALL_TYPES 与 REVIEW_TYPES"
             % "、".join(_blind_five))

    if real_rules and not rules_bad:
        src_note.append("规则 %d 条" % real_rules)
    if real_types and not types_bad:
        src_note.append("交付物 %d 类／全脱 %s 类／审查用 %s 类"
                        % (real_types, real_mask if real_mask is not None else "?",
                           real_review if real_review is not None else "?"))
    if rules_bad:
        err("通用规则条数失准（真源 core/01 实扫 %d 条）：%s"
            % (real_rules, "；".join(sorted(rules_bad))))
    if types_bad:
        err("交付物类型／脱敏类数失准（真源 --types／ALL_TYPES／REVIEW_TYPES）：%s"
            % "；".join(sorted(types_bad)))

    if not (fmt_bad or menu_bad or seed_bad or elems_bad or law_bad or rules_bad or types_bad):
        note = src_note + (["法条 %d 部 %d 条" % (real_laws, real_arts)] if real_laws else [])
        info("数字口径：格式／菜单项数／要素项数／内置库数／法规库规模／规则条数／交付物类数与真源一致（%s）"
             % "、".join(note))


def _check_doc_consistency():
    """跨文件术语一致性 + 禁止陈旧/错误表述守卫（v3.26.0 质检后新增）。

    专治两类复发：①「改了号没改话」——模型升级后旧表述残留（如尺度仍写「粗细×强弱两轴」、
    漏掉新增的「侧重可多选」）；②「同一词文档内自相矛盾」——能检/能核 在 SKILL 与 README
    内部各有一套相反定义。

    设计：单一**禁止陈旧表述注册表 FORBID** 集中登记已知错误/陈旧写法，命中即报错；
    另对 frontmatter 尺度描述、README 侧重清单做正向一致性断言。将来模型再变，改这里即可，
    不必满文档找。
    """
    DOCS = ("SKILL.md", "README.md", "安装使用教程.md",
            "文档合规审查助手AI合同提示词版.md", "drafting-guide.md",
            "permissions-and-libraries.md")

    def lines(rel):
        p = os.path.join(ROOT, rel)
        return [(i + 1, l) for i, l in enumerate(_read(p).split("\n"))] if os.path.exists(p) else []

    # ---- 禁止陈旧/错误表述注册表（命中即错；改模型时同步更新此表）----
    # 每条：(名称, 正则)。正则只抓「现行模型下绝不该出现」的写法。
    FORBID = [
        # 尺度旧两轴：把「强弱」错挂到「尺度」上、且漏掉 v3.26.0 新增的「侧重可多选」
        ("尺度旧两轴·强弱挂尺度", r"审查尺度分粗细（严苛/中性/宽松）与强弱势"),
        ("尺度旧两轴·强弱挂尺度·简", r"审查尺度分粗细与强弱势"),
        # 能检/能核 互换错写：能检被说成「查风险」、能核被说成「机械错误」
        ("能检错写成查风险", r"能检是\*\*查风险\*\*"),
        ("能检错写成拿规则库查文档", r"能检 是拿规则库去查文档"),
        ("能核错写成机械错误", r"能核\*\*是拿产物去对\"有没有机械错误\""),
        # 沿革不对外提供（v3.26.2）：history 与 VERSION.md 都不随包，旧口径「VERSION.md 随包、
        # 是沿革载体、可查看」一律禁止——它会让文档对外承诺一个包内根本不存在的文件。
        ("沿革仍写随包/唯一载体", r"VERSION\.md (?:已随包|随包|是沿革的唯一载体)"),
        ("可查看清单仍写 VERSION.md 六项", r"可查看的只有[^\n]{0,90}VERSION\.md[^\n]{0,40}六项"),
        ("技能本体仍写 6 项可看", r"技能本体只有\s*6\s*项可看"),
        ("可看的只有六项", r"可看的只有六项"),
        # 项数也钉住：可查看清单＝5 项（README／版本身份证／LICENSE／教程／提示词版）。
        # 写 6 项的一定是把 VERSION.md 又算进去了——数字与清单两头都拦，防「改了话没改数」。
        ("可查看项数仍写 6 项", r"(?:可查看的只有|可以看的只有|可看的只有)\s*\*{0,2}\s*6\s*项"),
    ]
    bad = []
    for rel in DOCS:
        for ln, line in lines(rel):
            for name, pat in FORBID:
                if re.search(pat, line):
                    bad.append("%s:%d 命中禁止表述[%s]" % (rel, ln, name))

    # ---- 正向断言：可查看清单里不得再出现 VERSION.md（沿革不对外提供）----
    # 允许「…五项（版本沿革 VERSION.md 不对外提供）」这类**明确否定**的说明句。
    for rel in ("README.md", "SKILL.md", "permissions-and-libraries.md"):
        for ln, line in lines(rel):
            if not re.search(r"(可查看的只有|可看的只有|项可看)", line):
                continue
            if "VERSION.md" not in line:
                continue
            if "不对外提供" in line or "不随包" in line:
                continue
            bad.append("%s:%d 可查看清单仍含 VERSION.md——沿革不对外提供，不能列为可查看项"
                       % (rel, ln))
    if bad:
        err("文档含禁止的陈旧/错误表述（与现行模型冲突）：%s" % "；".join(bad))

    # ---- frontmatter：三个 description 字段各司其职（v3.26.7 重定）----
    # 演变交代（不删历史，因为下一次想"再删一个"的人会踩同一坑）：
    #   v3.26.5 曾因「两段中文长文重复」**删掉 `description_zh`**，并把门禁写成负向断言。
    #   该判断在平台规范面前是错的——开放平台字段表里 `description_zh` 是**必填**，
    #   缺失时解析器直接报「缺少 Skill 中文描述(description_zh)」。删掉它等于把包变成
    #   一个平台必然拒收的包，而本地跑门禁一切正常（门禁只认我们自己的断言）。
    # 真正的病不是"有两个中文字段"，而是**两个字段都写成了同一份长文**。平台对二者的
    #   职责分得很清：`description` 给模型判触发（要写全用途与触发词），`description_zh`
    #   是**详情页给人看的简短介绍**。故修法是"各归其位"，不是"删掉一个"：
    #     · `description`      长文，判触发用（须含触发词与尺度口径）
    #     · `description_zh`   简短中文介绍，≤200 字（超了就是把触发长文抄了第二遍）
    #     · `description_en`   对应英文，≤700 字符
    sk = _read(os.path.join(ROOT, "SKILL.md"))
    fm = re.search(r"^---\n(.*?)\n---", sk, re.S)
    if not fm:
        err("SKILL.md 找不到 frontmatter 段，无法核对 description 尺度表述")
    else:
        fmb = fm.group(1)

        def _fmval(key):
            m = re.search(r"^%s:\s*(.*)$" % re.escape(key), fmb, re.M)
            if not m:
                return None
            v = m.group(1).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v

        # ① 三个字段都必须在（开放平台 frontmatter 必填项，缺一个即「解析失败」）
        for key in ("description", "description_zh", "description_en"):
            if _fmval(key) is None:
                err("SKILL.md frontmatter 缺 %s——开放平台字段表中该项为**必填**，"
                    "缺失时平台报「缺少 Skill …描述」直接拒收" % key)

        # ② description 须含触发口径（模型靠它判该不该触发）
        d = _fmval("description")
        if d is not None and "侧重可多选" not in d:
            err("SKILL.md frontmatter 的 description 未含「侧重可多选」——"
                "尺度模型已变，触发描述须同步")

        # ③ description_zh 须**简短**：上限 200 字。
        #    这条是"防回潮"的主体——v3.26.5 前的 501 字就是触发长文的复制品，
        #    平台详情页会把两屏长文连着渲染，使用者看到的是同一件事说了两遍。
        zh = _fmval("description_zh")
        if zh is not None and len(zh) > 200:
            err("SKILL.md frontmatter 的 description_zh 有 %d 字，超过 200 字上限——"
                "该字段是详情页的**简短**中文介绍，写长了就是把 description 复制第二遍"
                % len(zh))

        # ④ description_en 同理（限 700 字符）。v3.25.4 曾涨到 1861 字符，
        #    理由是"补能力不是冗余"——补能力对，但补错了字段：那四项能力在
        #    description 里已经写了，英文详情页不需要再来一遍。
        en = _fmval("description_en")
        if en is not None and len(en) > 700:
            err("SKILL.md frontmatter 的 description_en 有 %d 字符，超过 700 上限——"
                "该字段是英文详情页简介，不是 description 的译本" % len(en))

        # ⑤ 区分度守卫：description_zh 不得是 description 的开头一段
        #    （直接复制粘贴的典型形态；⑥ 的长度上限已能拦，但这一条给出更准的话术）。
        if zh and d and len(zh) > 40 and zh[:40] in d:
            err("SKILL.md 的 description_zh 前 40 字与 description 完全重合——"
                "两个字段读者不同（模型判触发／人看详情页），不是同一段话的两种长度")

    # ---- README 侧重清单须含「自定义」（与开场清单第 6 题「侧重 4–8」逐处对齐）----
    # 只在真正列举侧重项的行上查（以「合规底线加严」为标记），不误伤仅提及「侧重可多选」的简写行。
    for ln, line in lines("README.md"):
        if "合规底线加严" in line and "自定义" not in line:
            err("README.md:%d 列举了侧重项却未含「自定义」——与开场清单第 6 题（侧重 4–8）不一致" % ln)

    # ---- 提示词版（纯提示词分发包）专属正向断言（v3.26.4 加）----
    # 这类文档没有脚本、能力边界与完整版不同，最容易出现「照着完整版改了半句」：
    # 完整版改了口径，提示词版还是旧说法，而它恰恰是**不安装、直接粘贴就能用**的那份。
    # 三条都写成**正向**断言——不问「有没有写错」，而问「该有的在不在」：
    # 只拦登记过的错字面（12.5.4），换个说法就绕过去了。
    _pv = "文档合规审查助手AI合同提示词版.md"
    _pvt = _read(os.path.join(ROOT, _pv))
    if _pvt:
        # (1) 列举尺度档位的行必须同时给「侧重」——尺度的现行模型是「基准单选＋侧重多选」，
        #     只列严苛/中性/宽松等于把两级控件压成一级（旧写法正是靠「两轴各选一项」绕过 FORBID 的）。
        for ln, line in lines(_pv):
            if "严苛" in line and "中性" in line and "侧重" not in line:
                err("%s:%d 列举尺度档位却未带「侧重」——尺度是「基准单选＋侧重多选」两级，"
                    "只写基准会丢掉侧重这层" % (_pv, ln))
        # (2) 行业清单必须是 9 个（内置行业库 9 个，少列一个就少一个行业口径）。
        if "建筑地产" not in _pvt:
            err("%s 的行业清单缺「建筑地产」——内置行业库 9 个，少一个就少一个行业口径" % _pv)
        # (3) 必须有作答方式说明：无控件时用户要能「回数字」，否则多选会被误解析。
        if "作答方式" not in _pvt and "- 答法" not in _pvt:
            err("%s 缺「作答方式」说明（回数字／区间／全／全默认）——"
                "用户按习惯回多选会被当成一句话处理" % _pv)
        # (4) 默认交付物 ∩「本版做不出的」必须为空——默认就要求做一件做不到的事，
        #     是最难自察的矛盾：两句话隔了十几行，各看各的都对。
        _md = re.search(r"不选则默认出\s*([0-9]+(?:\s*[、,]\s*[0-9]+)*)", _pvt)
        _mc = re.search(r"本版确实做不出的[^\n]*", _pvt)
        if _md and _mc:
            _dflt = set(re.findall(r"\d+", _md.group(1)))
            _cant = set(re.findall(r"(\d+)\s*审查意见批注版", _mc.group(0)))
            _both = _dflt & _cant
            if _both:
                err("%s 的默认交付物含本版做不出的第 %s 类——"
                    "默认项里不得出现做不到的类型" % (_pv, "、".join(sorted(_both))))

    if not bad and fm:
        info("术语一致性：尺度/能检表述与现行模型一致（FORBID 注册表无命中）；提示词版四条正向断言通过")


def _check_pseudo_controls():
    """伪控件守卫：纯文本清单不得用 ☐／☑／○ 冒充勾选框（2026-10-29 加）。

    事实依据（不是审美偏好）：这些字符在聊天界面**只是普通文字，没有任何点击行为**。
    用户看到方框会去点，点了没反应，然后才怀疑是自己不会用——**省不下一次点击，只多一次困惑**。
    真能点的是平台自带控件（radio／checkbox），不靠字符模拟。

    判据两条：
      （1）负向——各文档出现这三个字符即报错；含「禁用／不得用」的说明行豁免
           （禁令自身要引用这些字符，不放行的话守卫会拦自己）。
      （2）正向——SKILL.md 必须存在「交互失败降级」条款：字符清干净了，但用户回报
           「选不中」时若无处可去，等于把人卡在原地。两条缺一不可。

    边界（不假装全覆盖）：``[ ]`` **不纳入机器判据**——它在 Markdown 里是合法的任务列表写法，
    机器分不清「冒充控件」与「真清单」，误伤面太大，留人工复核；此边界写在 SKILL 禁令段里。
    """
    PSEUDO = ("☐", "☑", "○")
    bad = []
    for rel in ("SKILL.md", "README.md", "安装使用教程.md",
                "文档合规审查助手AI合同提示词版.md", "drafting-guide.md",
                "permissions-and-libraries.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        for i, line in enumerate(_read(p).split("\n"), 1):
            if "禁用" in line or "不得用" in line:
                continue
            hit = "".join(c for c in PSEUDO if c in line)
            if hit:
                bad.append("%s:%d 含「%s」" % (rel, i, hit))
    if bad:
        err("纯文本清单用了伪控件符号（看着能点、点不了），改用「编号 名称 ｜ 编号 名称」：%s"
            % "；".join(bad[:6]))
    if "交互失败降级" not in _read(os.path.join(ROOT, "SKILL.md")):
        err("SKILL.md 缺「交互失败降级·逐条提问」条款——用户回报「选不中」时无路可走")
    else:
        info("交互：清单一律无伪控件符号；整块选不中时有逐条降级条款")


def check_naming_fields():
    """命名三字段守卫（铁律第 21 条）：`name` 显示名（可中文）／`slug` kebab-case／`display_name` 同值兼容位。

    **为什么非有这条不可**：2026-10-30 起字段分工重排——
      · `name` ← **显示名**（平台面板读它）。**可写中文**，允许但不强制——写成纯英文不违规，
        只是面板上显示英文；
      · `slug` ← **kebab-case 标识**（官方规范要求；进技能目录名、包名第四段、脚本内引用）；
      · `display_name` ← `name` 的同值**兼容位**（可选；保留则须逐字相同）。
    原来这两个角色都压在 `name` 一个字段上，拆开之后三种病都会悄悄发生，故逐条断言：

      a. **`name` 含文件名非法字符或控制字符** —— `pack.py` 的 `_safe_name` 会**静默剔除**，
         于是文件名与 `name` 不一致而无人知晓（12.5 禁止静默降级）。这是三条里最阴的一条：
         `name` 以前不进文件名（进的是 `display_name`），分工一换它**就进文件名了**；
      b. **`slug` 不是 kebab-case** —— 含大写／下划线／点／空格／全角符号即报。目录名、
         包名第四段、命令行引用三处一起坏，且坏在装机时才暴露；
      c. **`name` 与 `display_name` 不同值** —— 两处各存必漂（12.2），改一处忘另一处。

    **不查的一条**：`name` 是否含汉字。中文只是**允许**、不是**要求**——
    强制中文化会把纯英文命名的既有技能一律判红，那不是守卫该干的事。
    真源仍是 `SKILL.md` frontmatter；本函数只断言，不改写。
    """
    skill = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(skill):
        return
    m = re.search(r"^---\n(.*?)\n---", _read(skill), re.S)
    if not m:
        err("SKILL.md 找不到 frontmatter 段，命名守卫无法执行")
        return
    fmtext = m.group(1)

    def _v(key):
        mm = re.search(r"(?m)^%s:[ \t]*(.*)$" % re.escape(key), fmtext)
        return (mm.group(1) if mm else "").strip().strip('"').strip("'").strip()

    name, slug, disp = _v("name"), _v("slug"), _v("display_name")
    bad = []
    if not name:
        bad.append("缺 `name`——平台面板显示读的就是它（可写中文，也可纯英文）")
    elif re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
        bad.append("`name` 含文件名非法字符或控制字符（`%s`）——`pack.py` 的 `_safe_name` "
                   "会**静默剔除**它们，文件名将与 `name` 不一致" % name)
    elif name != name.strip():
        bad.append("`name` 首尾有空白（`%r`）" % name)
    if not slug:
        bad.append("缺 `slug`——应为 **kebab-case** 标识，进技能目录名与包名第四段")
    elif not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
        bad.append("`slug` 不合 kebab-case（`%s`）——只许小写字母与数字、单词间用**单个连字符**；"
                   "禁大写、下划线、点、空格与全角符号" % slug)
    if name and disp and name != disp:
        bad.append("`name`（`%s`）与 `display_name`（`%s`）不同值——"
                   "两者是同一真源的两个落点，须逐字一致；不保留 `display_name` 时须整体删去" % (name, disp))
    if bad:
        for b in bad:
            err("命名：" + b)
    else:
        info("命名三字段：name=%s｜slug=%s（kebab-case）%s" % (
            name, slug, "｜display_name 同值" if disp else "｜未设 display_name"))


def check_package_fields():
    """出包必填字段守卫：`pack.py` 组装文件名所依赖的 frontmatter 字段，必须齐且非空。

    真源不写死在 check.py——从 `pack.py` 里实际调用的 `_fm_field(base, "X")` 抽出来，
    以后 pack.py 新增依赖字段，本守卫自动跟上，不需要人回来改两张表。

    **为什么非有这条不可**：`package_stem` 对每个字段都写了 `or` 兜底，字段丢了**不报错**，
    只会静默降级——四段式看着仍合规，`verify_filename` 也照样放行。V3.11.2 把它列为遗留，
    本条即其落地：**不再允许静默**。
    （V3.11.6 起文件名第四段改用 slug；2026-10-30 起该角色由独立字段 `slug` 承担，
    `name` 改承担中文技能名、丢失会让产品名段退化成技能目录名；`display_name_en`
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


def _check_questionnaire_libraries():
    """开场清单「加载库」一题须列全内置行业库；清单题号须连续 1–11。

    为什么立这条（v3.26.0，用户要求「加载库时把 9 个库全部列出来，能多选」）：
    清单是使用者**唯一能看见选项的地方**——漏列一个库，等于该库从此不会被加载，
    而 industries/ 里的文件还在、其它守卫全绿，没人会发现。此前从没有守卫管这件事。
    判据数据驱动：行业名从 industries/*-meta.md 的 industry 字段读，不硬编码名单，
    新增行业库却忘了改清单，这里当场报出来。
    """
    sk = _read(os.path.join(ROOT, "SKILL.md"))
    m = re.search(r"(?m)^\s*4\.\s+加载库", sk)
    if not m:
        err("开场清单里找不到「4. 加载库」一题——加载库是必答项，不得删除")
        return
    seg = sk[m.start():m.start() + 1200]
    names = []
    idir = os.path.join(ROOT, "industries")
    if os.path.isdir(idir):
        for f in sorted(os.listdir(idir)):
            if not f.endswith("-meta.md") or f.startswith("_"):
                continue
            mm = re.search(r"(?m)^industry:\s*(.+)$", _read(os.path.join(idir, f)))
            if mm and mm.group(1).strip():
                names.append(mm.group(1).strip())
    lost = [n for n in names if n not in seg]
    if lost:
        err("开场清单「加载库」未列出 %d 个内置行业库：%s——"
            "使用者看不到的库等于不存在，该库从此不会被加载"
            % (len(lost), "、".join(lost)))
    # 题号连续性：清单必须 1–11 完整，缺号会让用户按题号作答时错位
    body = sk[sk.find("【开场清单"):sk.find("【开场清单") + 2000]
    nums = [int(x) for x in re.findall(r"(?m)^\s*(\d{1,2})\.\s", body)]
    want = list(range(1, 12))
    if nums[:11] != want:
        err("开场清单题号不连续：实测 %s，应为 1–11" % (nums[:11] or "无"))
    else:
        info("开场清单：11 题题号连续，加载库已列全 %d 个内置行业库" % len(names))
    # 尺度题必须「基准单选 ＋ 侧重多选」（v3.26.0 用户要求允许多选）。
    # 双向判：缺侧重段＝退回纯单选（用户要多选）；把基准也写成可多选＝语义自相矛盾。
    m6 = re.search(r"(?m)^\s*6\.\s+审查尺度", sk)
    if not m6:
        err("开场清单里找不到「6. 审查尺度」一题")
    else:
        seg6 = sk[m6.start():m6.start() + 900]
        if "基准" not in seg6 or "侧重" not in seg6:
            err("审查尺度须写明「基准（单选）＋侧重（可多选）」两段——"
                "缺侧重段即退回纯单选，用户就没有多选可用了")
        # 逐处检查：**每个**「侧重（…）」括号里都必须写「可多选」。
        # 只判「全文某处有可多选」是不够的——实测漏过一次：清单处标了、执行口径处没标，
        # 判据在别处命中就放行，等于两处表述分家却全绿。
        for mm in re.finditer(r"侧重[（(]([^）)]{0,60})[）)]", sk):
            if "可多选" not in mm.group(1):
                err("审查尺度的侧重段未标「可多选」（原文：%s）——"
                    "侧重是可叠加的多个方向，不标会被当成单选执行" % mm.group(0)[:40])
        if re.search(r"基准（\*\*只选一个\*\*|基准（只选一个", seg6) is None:
            err("审查尺度未标明基准「只选一个」——基准若也做成多选，「严苛＋宽松」会同时成立，语义矛盾")
    # 作答语法必须存在（降低打字难度的落地条款），否则「回数字即可」成了空话
    for must in ("3-11", "全默认", "同上"):
        if must not in sk:
            err("缺少作答语法写法 `%s`——用户少打字的入口被删了" % must)

    # ---- 行业清单四处逐字一致（v3.32.2 加）----
    # 由来（用户实测报「建筑行业库没有显示出来」）：库文件九个齐全、配对完整、
    # SKILL 三处清单都对，但 README 的规则库表把「建筑地产」写成「房地产」并挪到末位——
    # 成了第二套名称与顺序。按名检索搜不到、模型照它渲染就漏项。
    # 而原守卫只查 SKILL「4. 加载库」那一段，**表格形态的清单完全没有守卫**（上面那条
    # 「建筑地产」判据只盯着提示词版一处），于是这处口径分家漂了数个版本。
    # 判据：**名称集合**须与 industries/*-meta.md 的 industry 字段逐字相同（少一个即漏列、
    # 多一个即库里没有）；**顺序**以 SKILL 1.0.2 第 4 题为真源，其余三处逐位对齐——
    # 顺序不一致同样会让「第 11 项」指向不同库。顺序真源只取一处，不另立 order 字段
    # （12.2：同一事实不许两个真源，meta 里再造一份顺序，改清单时必漂）。
    _IND_ORDER = []
    if os.path.isdir(idir):
        _seen = set()
        for f in sorted(os.listdir(idir)):
            if not f.endswith("-meta.md") or f.startswith("_"):
                continue
            _mi = re.search(r"(?m)^industry:\s*(.+)$", _read(os.path.join(idir, f)))
            if _mi and _mi.group(1).strip():
                _IND_ORDER.append(_mi.group(1).strip())
                _seen.add(_mi.group(1).strip())

    def _names_in(text):
        """按出场顺序抽出文段中出现的行业名（长名优先，防「医药」吃掉「医疗卫生」）。"""
        if not _IND_ORDER:
            return []
        _hit, _rest = [], text
        for _n in sorted(_IND_ORDER, key=len, reverse=True):
            if _n in _rest:
                _hit.append((_rest.index(_n), _n))
                _rest = _rest.replace(_n, "\u0000" * len(_n))
        return [n for _, n in sorted(_hit)]

    # 三处的抽取锚点：SKILL 1.0.2 第 4 题／SKILL 1.4 勾选框／README 规则库表。
    # 只有三处——曾误以为「第九节菜单」是第四处，实为 1.4 段内的那行「行业库（内置 9 个…）」，
    # 第九节是「上签强制检查」，不含行业清单。锚点重复会让两个名字抽到同一段，
    # 报错指向错的地方（实测：只删 1.4 段却报「第九节菜单漏列」）。
    _spots = [("SKILL 1.0.2 第 4 题", sk, r"(?m)^\s*4\.\s+加载库")]
    _m14 = re.search(r"【Qn · 选择加载库", sk)
    if _m14:
        _spots.append(("SKILL 1.4 勾选框", sk, None))
    _rd = _read(os.path.join(ROOT, "README.md"))
    _spots.append(("README 规则库表", _rd, r"具体行业的专门规则"))
    # 段抽取一律**截到下一个段落锚点**，不用固定字数窗口——实测 900 字窗口会越过
    # 1.4 段尾爬到后面的说明文字里，而那里恰好也提到「建筑地产」，于是删掉选项行
    # 仍判「列全了」（假绿）。按锚点截断，段内没有就是没有。
    def _seg_until(text, start, stops):
        _end = len(text)
        for s in stops:
            j = text.find(s, start + 1)
            if j != -1 and j < _end:
                _end = j
        return text[start:_end]

    # **只留非引用块**：段内的举例句一律写在 `>` 引用块里（「> 不可用项照常列出并标注
    # （如「11. 建筑地产 —— 不可用：目录不存在」）」），它含行业名却**不是清单项**。
    # 实测：删掉 1.4 的第 11 项后，判据被这句示例喂饱仍判「列全了」（第二次假绿，
    # 第一次是字数窗口串段）。故先剔掉以 `>` 开头的行——选项与分组标题都不以 `>` 起。
    def _option_lines(seg):
        return "\n".join(_ln for _ln in seg.splitlines()
                         if not _ln.lstrip().startswith(">"))

    _i4_main = sk.find("4.  加载库")
    _segs = {
        "SKILL 1.0.2 第 4 题": _option_lines(_seg_until(sk, _i4_main, ["5.  我方身份"])) if _i4_main != -1 else "",
        "SKILL 1.4 勾选框": _option_lines(_seg_until(sk, _m14.start(), ["**步骤 1.5"])) if _m14 else "",
        "README 规则库表": _rd[_rd.find("具体行业的专门规则"):_rd.find("具体行业的专门规则") + 300] if "具体行业的专门规则" in _rd else "",
    }
    # 第三处外挂：提示词版的行业清单（纯文本版，编号自成一套：1 通用版 ＋ 2–10 行业）。
    # 它也是使用者能看见清单的地方，同样会「看不到就永远不加载」，故一并咬合。
    # 只比**名称集合**，不比顺序与编号——该版编号体系与主清单不同（含「1 通用版」打头）。
    _pv = _read(os.path.join(ROOT, "文档合规审查助手AI合同提示词版.md"))
    _pvseg = ""
    _mpv = re.search(r"(?m)^4\.\s+询问\*\*行业与适用场景", _pv)
    if _mpv:
        _pvseg = _seg_until(_pv, _mpv.start(), ["\n5. ", "\n4. "])
    if not _pvseg:
        err("行业清单咬合：提示词版找不到「4. 询问行业与适用场景」清单——"
            "纯文本版的使用者就没有行业库可勾了")
    else:
        _pgot = _names_in(_pvseg)
        _pmiss = [n for n in _IND_ORDER if n not in _pgot]
        if _pmiss:
            err("行业清单咬合：提示词版漏列 %d 个内置行业库：%s——"
                "纯文本版使用者看不到的库等于不存在，该库从此不会被加载" % (len(_pmiss), "、".join(_pmiss)))

    for _label, _txt, _ in _spots:
        _seg = _segs.get(_label, "")
        if not _seg:
            err("行业清单咬合：找不到 %s 的行业清单段——清单被改形或删除" % _label)
            continue
        _got = _names_in(_seg)
        _miss = [n for n in _IND_ORDER if n not in _got]
        _extra = [n for n in _got if n not in _IND_ORDER]
        if _miss:
            err("行业清单咬合：%s 漏列 %d 个内置行业库：%s——"
                "使用者看不到的库等于不存在，该库从此不会被加载"
                % (_label, len(_miss), "、".join(_miss)))
        if _extra:
            err("行业清单咬合：%s 出现库里没有的行业名：%s——"
                "名称与 industries/*-meta.md 的 industry 字段不符，按名检索会搜不到"
                % (_label, "、".join(_extra)))
    # 顺序真源＝SKILL 1.0.2 第 4 题（使用者最先、也最可能按题号作答的那处）。
    # 其余三处逐位对齐；顺序不同会让「第 11 项」在不同界面指向不同的库。
    _ref = _names_in(_segs.get("SKILL 1.0.2 第 4 题", ""))
    if len(_ref) == len(_IND_ORDER):
        for _label in ("SKILL 1.4 勾选框", "README 规则库表"):
            _got = _names_in(_segs.get(_label, ""))
            if len(_got) == len(_ref) and _got != _ref:
                err("行业清单咬合：%s 的顺序与清单第 4 题不一致（实测 %s ／ 应为 %s）——"
                    "顺序不同会让同一个题号指向不同的库"
                    % (_label, "·".join(_got), "·".join(_ref)))
        info("行业清单咬合：SKILL 1.0.2 ／ 1.4 ／ README 表三处，%d 个行业库名称与顺序逐字一致"
             % len(_IND_ORDER))
    else:
        err("行业清单咬合：清单第 4 题解析出 %d 个行业名，库里是 %d 个——"
            "顺序基准取不到，无法逐位对齐" % (len(_ref), len(_IND_ORDER)))

    # ---- 一个提问只装一个答案维度（2026-10-29 加，v3.26.9）----
    # 由来（实测）：出现过把「审查尺度（粗细）」与「谈判地位（强弱）」合成一张卡片，
    # 给出「中性·强势方／中性·均衡／严苛·强势方／宽松·弱势方」四个组合选项——
    # 3 档基准 × 4 档地位 = 12 种组合只给 4 个，用户想选的「严苛·均衡」根本没得选。
    # 文本层面早就分成两问（清单第 6、7 项），是**举例写法**「两轴独立取值、组合生效
    # （中性＋弱势方、严苛＋强势方皆合法组合）」被照抄成了选项清单。故立三道判据：
    #   (1) 总纲须有通则句——只写在 1.6 一节，换个提问处就管不住
    #   (2) 1.6 段内须有显式禁令——通则说了、该节仍可自行合并
    #   (3) 选项**行**不得是「档位·档位」——只抓行首编号的选项形态，**不抓正文举例**：
    #       举例是必要的反面材料（讲清"为什么不能合并"），抓了会逼着把证据删掉
    if "一个提问只装一个答案维度" not in sk:
        err("提问总纲缺「一个提问只装一个答案维度」通则——两个正交维度会被合成一题")
    _m16 = sk.find("步骤 1.6")
    if _m16 == -1:
        err("找不到步骤 1.6（审查尺度与谈判地位），无法核对两问分离口径")
    else:
        _seg16 = sk[_m16:_m16 + 1500]
        if "不得合并成一题" not in _seg16:
            err("1.6 节未写明「不得合并成一题」——两轴会被做成一组组合选项")
        if "不是候选项" not in _seg16:
            err("1.6 节举了两轴组合的例子，却未声明「不是候选项清单」——"
                "例子会被照抄成选项（v3.26.8 实测如此）")
    # 只认「行首编号／项目符号 + 档位·档位」这种**选项形态**
    _badopt = re.findall(r"(?m)^\s*(?:\d+[.、)]|[-*])\s*(?:严苛|中性|宽松)\s*[·・]\s*(?:强势|均衡|弱势)", sk)
    if _badopt:
        err("发现「档位·档位」组合选项 %d 处（如「%s」）——审查尺度与谈判地位须分两问，"
            "不得做成组合选项" % (len(_badopt), _badopt[0].strip()[:22]))
    else:
        info("提问结构：尺度与地位分两问（无「档位·档位」组合选项），总纲已立一屏一维度通则")


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
    for rel in ("README.md", "SECURITY.md", "文档合规审查助手AI合同提示词版.md", "安装使用教程.md"):
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


def check_net_tier_consistency():
    """联网档位一致性（安全声明同型病灶第三次复发）。

    背景（v3.23.4 质检）：README 的「处理文档脚本全离线、仅检查更新会联网」两档旧口径，
    在 v3.23.2 做四档后就没跟上，到 v3.23.4 才被质检发现——README 仍写「20 个脚本全部
    纯本地不联网」「仅检查更新会联网」、联网边界表缺「法规时效巡检」一行。同一事实散在四份
    文档各写一遍，改一处漏三处。**故强制**：SECURITY.md 为唯一真源，其余文档不得再出现
    两档旧口径，且「N 个脚本」必须与真实脚本数一致（check_version_consistency 也看，这里
    顺带覆盖 SKILL/提示词版）。
    """
    sec_p = os.path.join(ROOT, "SECURITY.md")
    if not os.path.exists(sec_p):
        return
    sec = _read(sec_p)
    n_py = len([f for f in os.listdir(os.path.join(ROOT, "scripts"))
                if f.endswith(".py")])
    # 真源档位计数（从 T1 结构化行抽：E0 ... 18 个脚本 ... E1 ... 1 个 ... E2 ... 2 个 ... E3 ... 2 个）
    tier = {}
    mt = re.search(r"E0[^\n]*?(\d+)\s*个脚本[^\n]*?E1[^\n]*?(\d+)\s*个[^\n]*?"
                   r"E2[^\n]*?(\d+)\s*个[^\n]*?E3[^\n]*?(\d+)\s*个", sec, re.S)
    if mt:
        tier = {"E0": int(mt.group(1)), "E1": int(mt.group(2)),
                "E2": int(mt.group(3)), "E3": int(mt.group(4))}
    stale, wrong = [], []
    for rel in ("README.md", "SKILL.md", "安装使用教程.md",
                "文档合规审查助手AI合同提示词版.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        t = _read(p)
        # 旧两档口径：只说「仅检查更新会联网」且整篇未提 E2（四档）→ 必然漏了失效巡检
        if re.search(r"仅[「\"']?检查更新[」\"']?(这一个动作)?会联网", t) and "E2" not in t:
            stale.append("%s 仍是两档旧口径（只提检查更新会联网，未提 E2 失效巡检）" % rel)
        # 出现「N 个脚本」但不等于真实数
        for m in re.finditer(r"(\d+)\s*个脚本", t):
            if int(m.group(1)) != n_py:
                wrong.append("%s 写 %s 个脚本（真实 %d）" % (rel, m.group(1), n_py))
        # 若文档声称四档（含 E2），则四档计数须与真源一致（防止手填数字漂）
        if tier and "E2" in t:
            for code, val in tier.items():
                for mm in re.finditer(r"%s[^\n]{0,20}?(\d+)\s*个" % code, t):
                    if int(mm.group(1)) != val:
                        wrong.append("%s 的 %s 档计数 %s ≠ 真源 %d"
                                     % (rel, code, mm.group(1), val))
    msgs = stale + wrong
    if msgs:
        err("联网档位与 SECURITY.md 不一致：%s" % "；".join(msgs))
    else:
        info("联网档位：README/SKILL/教程/提示词版 均与 SECURITY.md 四档一致（共 %d 脚本）" % n_py)


def check_engine_implementations():
    """引擎表「对应实现」反查（骨架表滞后，登记化）。

    背景（v3.23.4 质检）：README/SKILL 的引擎表曾只列 11 个，漏了安全引擎、法规库失效巡检、
    法规库交叉验证、失衡画像 4 个实际在跑的引擎；且「对应实现」列写的文件名，没人保证它真存在。
    故：扫两张引擎表，凡「对应实现」里点名的 .py/.md/.json 文件，必须能在技能目录里找着——
    文档声称的实现落点不存在，等于又一句「写了没验」（第 25 条形态）。规划中（—）不查。
    """
    missing = []
    for rel in ("README.md", "SKILL.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        in_engine_tbl = False          # 只盯「对应实现」表头之下的引擎表行——
                                       # README 还有守卫工具表等「| N |」编号表，
                                       # 其说明列也会提到 `private/` 等目录，非实现落点，不可误扫
        for ln in _read(p).splitlines():
            if "对应实现" in ln and ln.lstrip().startswith("|"):
                in_engine_tbl = True
                continue
            if in_engine_tbl and not ln.lstrip().startswith("|"):
                in_engine_tbl = False   # 表结束（空行/新章节）
            if not (in_engine_tbl and re.match(r"^\|\s*\d+\s*\|", ln)):
                continue
            for tok in re.findall(r"`([^`]+)`", ln):
                tok = tok.strip()
                # 跳过命令型（`python scripts/check.py`，带空格）与非落点标记（`net-tier`）。
                if " " in tok:
                    continue
                # 纯文件名型落点：`make-docx.py`／`core/x.md`；
                is_file = re.match(r"^[\w./+-]+\.(py|md|json)$", tok)
                # 目录型落点：`industries/`（引擎表「对应实现」列也会写目录而非单文件）。
                is_dir = re.match(r"^[\w./+-]+/$", tok)
                if not (is_file or is_dir):
                    continue
                if is_dir:
                    base = tok.rstrip("/")
                    cand = [os.path.join(ROOT, base),
                            os.path.join(ROOT, "scripts", base),
                            os.path.join(ROOT, "core", base)]
                else:
                    cand = [os.path.join(ROOT, tok),
                            os.path.join(ROOT, "scripts", tok),
                            os.path.join(ROOT, "core", tok)]
                if not any(os.path.exists(c) for c in cand):
                    missing.append("%s 引擎表声称的实现 `%s` 在技能目录里找不到" % (rel, tok))
    if missing:
        err("引擎实现落点失联：%s" % "；".join(missing))
    else:
        info("引擎表：README/SKILL 两张表点名的实现文件全部存在（落点可核验）")
    _check_engine_count()


def _check_menu_entries():
    """菜单完整性：引擎做了、菜单里却点不到（2026-10-29 加，v3.26.6）。

    事实依据：法规检索 `legal-search.py`、法规汇编 `legal-compile.py`、OCR
    `preprocess.py`、结构化 `structure.py` 四个引擎**早就在用**（引擎表标 ✅、
    `description` 也一直宣传「查法条、编法规汇编」），但 0.5 的功能菜单里**一个入口都没有**。
    用户按「向导」看到的是一份少了四行的功能表——等于做了没人用得上；
    而门禁一路全绿，因为没人查过「引擎表 ↔ 菜单」这一对。

    查四件事：
      ① 菜单编号连续（0..N-1，不缺不重）——编号跳号，用户回数字就会打空；
      ② 正文「一次性列出 N 项」与实数一致（改了菜单忘改这句，是同一类漂移）；
      ③ 七类能力关键词必须在菜单里现身（缺哪个报哪个）——防「再次漏项」的正面断言；
      ④ 每一项都要有去向——只列不指路，用户点进去仍是死路。

    不做什么：**不逐行比对引擎表**。菜单是面向使用者的组织，允许把两个引擎合成一项
    （如「格式转换」＝入向 preprocess ＋ 出向 make-docx），逐行比对会逼着把内部实现
    细节塞进菜单。故判据落在**能力层关键词**，不落在实现层引擎行。
    """
    p = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(p):
        return
    src = _read(p)
    m = re.search(r"【Q1 · 本技能功能 · 请单选[^\n]*\n(.*?)\n```", src, re.S)
    if not m:
        err("SKILL.md 找不到 0.5 的菜单块（【Q1 · 本技能功能 · 请单选）——"
            "菜单完整性无从核对")
        return
    block = m.group(1)
    nums = [int(x) for x in re.findall(r"(?m)^\s*(\d+)\.\s", block)]
    if not nums:
        err("0.5 菜单块里没解析出任何编号项（应形如「0. 背景资料录入」）")
        return
    n = len(nums)

    # ① 连续、不重复
    if sorted(nums) != list(range(n)):
        err("0.5 菜单编号不连续或有重复：%s（应为 0..%d）" % (nums, n - 1))

    # ② 声称的项数 = 实数
    mm = re.search(r"一次性列出\s*(\d+)\s*项", src)
    if not mm:
        err("SKILL.md 0.5 处找不到「一次性列出 N 项」的项数表述")
    elif int(mm.group(1)) != n:
        err("0.5 菜单实有 %d 项，正文却写「一次性列出 %s 项」——"
            "改了菜单没改这句话，用户会以为还有没显示的项"
            % (n, mm.group(1)))

    # ③ 能力关键词必须在场（正面断言：宁可多拦一次，不再漏项）
    MUST = {
        "背景资料录入": "前置项",
        "文档审查": "非合同类审查",
        "合同审查": "合同类审查",
        "文档脱敏": "脱敏引擎",
        "文档比对": "比对引擎",
        "撰写合同": "撰写引擎",
        "撰写合同模板": "模板撰写",
        "文档转模板": "转模板",
        "合同转模板": "转模板",
        "维护私有库": "私有层维护",
        "维护行业库": "行业层维护",
        "帮助说明": "手册",
        "精要总结": "总结能力",
        "格式转换": "preprocess 入向 / make-docx 出向",
        "OCR": "OCR 引擎",
        "结构化": "结构化引擎",
        "法规检索": "legal-search",
        "法规汇编": "legal-compile",
        "引用核验": "legal-verify",
        "公文写作": "gb9704 版式与体检",
        "套用模板": "tpl-engine.py use（模板库复用）",
    }
    miss = [k for k in MUST if k not in block]
    if miss:
        err("0.5 菜单缺以下能力入口：%s——引擎在用、菜单却没有，"
            "等于做了没人用得上（对应引擎：%s）"
            % ("、".join(miss), "；".join(MUST[k] for k in miss)))

    # ④ 每一项都要有去向
    dm = re.search(r"(?m)^> \*\*去向\*\*：(.*)$", src)
    if not dm:
        err("SKILL.md 0.5 处找不到「去向」段——菜单列了却不说每项走哪条链路")
        return
    dest = set()
    for seg in dm.group(1).replace("**", "").split("；"):
        sm = re.match(r"^\s*(\d+(?:[／/]\d+)*)\s*→", seg)
        if sm:
            for x in re.split(r"[／/]", sm.group(1)):
                dest.add(int(x))
    no_dest = sorted(set(nums) - dest)
    if no_dest:
        err("0.5 菜单第 %s 项没有去向（「去向」段里查不到该编号）——"
            "只列不指路，用户点进去仍是死路" % "、".join(map(str, no_dest)))


def _check_engine_count():
    """引擎数量与编号自洽：表里有多少行编号、正文就该写多少个引擎。

    为什么要单查一条：v3.24/v3.25 两次加引擎（16→17）时，**表格加了行、正文的
    「十五引擎」却一直没改**，门禁全绿放过——这正是「写了没验」的老病灶：
    落点检查只管「点名的文件在不在」，不管「说的数量对不对」。数字错了比文件
    缺失更隐蔽，因为文档读起来毫无异样。
    查三件事：① 编号连续（1..N 不缺不重）；② 正文「N 个引擎／N 引擎」＝N；
    ③ 两张表 N 一致。
    """
    counts = {}
    for rel in ("README.md", "SKILL.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        src = _read(p)
        nums, in_tbl = [], False
        for ln in src.splitlines():
            # 表头识别要兼容两种写法：README 写「对应实现」，SKILL 写「实现」。
            # 只认「对应实现」会漏掉 SKILL 表——那张表的编号就没人查了。
            if ln.lstrip().startswith("|") and re.search(
                    r"\|\s*#\s*\|.*引擎.*\|", ln):
                in_tbl = True
                continue
            if in_tbl and not ln.lstrip().startswith("|"):
                in_tbl = False
            if in_tbl:
                m = re.match(r"^\|\s*(\d+)\s*\|", ln)
                if m:
                    nums.append(int(m.group(1)))
        if not nums:
            continue
        n = len(nums)
        counts[rel] = n
        # ① 编号连续、不重复
        if sorted(nums) != list(range(1, n + 1)):
            err("%s 引擎表编号不连续或有重复：%s（应为 1..%d）"
                % (rel, nums, n))
        # ② 正文里的引擎数量表述必须等于实数（含「十七引擎」这类中文数字写法）
        #    中文数字必须真解析，不能只查一张对照表——表里漏了某个数字，
        #    那个数字就趁机溜过去（本轮实测：「十五」不在表内，注入后门禁照样全绿）。
        def _cn2int(t):
            if t.isdigit():
                return int(t)
            D = "零一二三四五六七八九"
            unit = {"十": 10, "百": 100}
            total, cur = 0, 0
            for ch in t:
                if ch in D:
                    cur = D.index(ch)
                elif ch in unit:
                    total += (cur or 1) * unit[ch]
                    cur = 0
                else:
                    return None
            return total + cur
        wrong = []
        for mm in re.finditer(r"([一二三四五六七八九十百]+|\d+)\s*(?:个)?引擎", src):
            raw = mm.group(1)
            # 「第 N 引擎」是**序号**（点名某一个引擎），不是总数，须排除，
            # 否则重排一次编号就会误报一次。
            if src[max(0, mm.start() - 2):mm.start()].strip().endswith("第"):
                continue
            val = _cn2int(raw)
            if val is not None and val != n:
                seg = src[max(0, mm.start() - 12):mm.end() + 6].replace("\n", " ")
                wrong.append("「%s」=%d（应为 %d）…%s" % (raw, val, n, seg))
        if wrong:
            err("%s 里引擎数量表述与表格行数（%d）不符：%s"
                % (rel, n, "；".join(wrong[:4])))
    if len(set(counts.values())) > 1:
        err("README 与 SKILL 的引擎表行数不一致：%s" % counts)
    elif counts:
        info("引擎表：%d 个引擎，两张表一致、编号连续，正文数量表述相符"
             % list(counts.values())[0])
    _check_engine_ordinal_in_scripts()
    _check_capability_count()
    _check_trigger_words()
    _check_subprocess_encoding()
    _check_format_default()


def _check_format_default():
    """「--formats 的默认值」必须与 SKILL 登记的默认值一致，且缺省必须被询问。

    为什么立这条（v3.25.6，千问办公用户反馈「产出物为何只有一个格式」）：
    `make-docx.py` 的 `--formats` 默认只有 `docx`，而文档对外承诺「10 类 × 5 格式」。
    默认值窄是有意的（不给用户塞一堆文件），但它是个**静默开关**——AI 跳过开场清单
    直接执行时，用户拿到「承诺 5 格式、实际 1 格式」，全程没有任何提示。
    **文档与代码在字面上一致**（文档确实写了「不选→仅 WORD」），所以此前门禁从不报错：
    字面一致不等于用户知情。

    判据刻意**不守措辞**（措辞一改守卫就废），而守两件事实：
      ① 代码里的 default 值，必须能在 SKILL 的文件格式节找到对应登记（文档别说谎）；
      ② 该节必须写明缺省时「必须问一次」（不许默默按默认值出件）。
    """
    mp = os.path.join(ROOT, "scripts", "make-docx.py")
    sp = os.path.join(ROOT, "SKILL.md")
    if not (os.path.exists(mp) and os.path.exists(sp)):
        return
    src_m = _read(mp)
    # v3.25.7：default 改为哨兵 None，真值落在 FORMAT_FALLBACK 常量。
    # 哨兵不是装饰——只有它能区分「用户没指定」与「用户显式写了 docx」，
    # 而这两者的唯一区别就是前者必须留一句提示。哨兵一丢，缺省提示永不触发。
    # 正则须同时吃下 default="docx" 与 default=None 两种写法（裸 None 不带引号）
    m = re.search(r'add_argument\(\s*"--formats"\s*,\s*default\s*=\s*"?([^",)\s]+)"?', src_m)
    raw = m.group(1) if m else None
    if raw == "None":
        # v3.31.0：FORMAT_FALLBACK 随格式引擎搬到 format-engine.py（格式家族真源），
        # 先查本文件、再查引擎——两处只许有一处定义，都在则取到的值必然相同。
        fb = (re.search(r'^FORMAT_FALLBACK\s*=\s*"([^"]+)"', src_m, re.M)
              or re.search(r'^FORMAT_FALLBACK\s*=\s*"([^"]+)"',
                           _read(os.path.join(ROOT, "scripts", "format-engine.py")), re.M))
        if not fb:
            err("--formats 用了哨兵 default=None，但找不到 FORMAT_FALLBACK 常量——"
                "缺省值无处可查，文档登记也就无从核对")
            return
        default = fb.group(1)
    else:
        default = raw
        if raw is not None:
            err("--formats 的 default 写成了固定值 %r 而非哨兵 None——"
                "这样无法区分「用户没指定」与「用户显式指定 %s」，缺省提示永不触发"
                % (raw, raw))
    if raw is None:
        err("--formats 未找到 default 声明，无法核对缺省格式")
        return
    src = _read(sp)
    # v3.28.0：锚点从「5 种」改「不定数字」——格式数一变（5→7）锚点就失明、守卫静默 return
    m = re.search(r"\*\*文件格式（(\d+)\s*种", src)
    if not m:
        return
    i = m.start()
    sec = src[i:i + 1200]
    # ① 文档登记的默认值须与代码一致（映射 WORD→docx 等）
    name_map = {"docx": "WORD", "md": "MD", "excel": "Excel", "html": "HTML", "pdf": "PDF",
                "pptx": "PPT", "mindmap": "思维导图"}
    codenames = [c.strip() for c in default.split(",") if c.strip()]
    for c in codenames:
        label = name_map.get(c, c)
        if label not in sec:
            err("SKILL.md 的文件格式节未登记代码默认值 %s（%s）——文档与代码分家，"
                "用户看到的承诺与实得的格式对不上" % (c, label))
    # 双向判：守卫首版只判了「默认窄、文档没写」，漏了反向「默认宽、文档还写仅 WORD」
    # （注入实测：把 default 改成 5 种，文档仍写「仅 WORD」，门禁全绿——漏报）。
    says_only_word = ("仅 WORD" in sec or "仅WORD" in sec)
    if len(codenames) == 1 and not says_only_word:
        err("代码默认只出 %s，而 SKILL 文件格式节未写「仅 WORD」——缺省行为必须写在明处"
            % default)
    if len(codenames) > 1 and says_only_word:
        err("代码默认已出 %d 种（%s），而 SKILL 文件格式节仍写「仅 WORD」——文档说的比给的少"
            % (len(codenames), default))
    # ② 缺省必须被询问，不许默默按默认值出件
    if "必须问" not in sec:
        err("SKILL.md 文件格式节未写明「产出前必须问一次」——缺省值窄可以，"
            "但不许不声不响只用默认格式出件")


def _check_subprocess_encoding():
    """subprocess.run 的 text=True 必须伴随 encoding="utf-8"。

    为什么立这条（v3.25.5，千问办公装机实测抓出）：Windows 下 text=True 默认按
    locale（简中即 GBK）解码子进程输出，而本技能所有脚本输出都是 UTF-8——
    中文报告一进管道就乱码，门禁自检报「门禁无输出」、装机冒烟 8 项全灭。
    **开发侧（Linux 全 UTF-8）一个错都不会报**，问题只在用户机器上炸——
    这正是「在我机器上是好的」的教科书形态。

    判据实现要点：不能按行 grep「subprocess.run 那行有没有 encoding」——
    多行调用的 encoding 写在续行，会误报。按括号配平抓出**完整参数区**再判。
    errors 一并建议（replace 优于 ignore：ignore 静默吞字节，replace 至少留痕）。
    """
    bad, noenv = [], []
    scripts_dir = os.path.join(ROOT, "scripts")
    if not os.path.isdir(scripts_dir):
        return
    for fn in sorted(os.listdir(scripts_dir)):
        if not fn.endswith(".py"):
            continue
        src = _read(os.path.join(scripts_dir, fn))
        for m in re.finditer(r"subprocess\.run\(", src):
            i = m.end()
            depth = 1
            while i < len(src) and depth:
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                i += 1
            args = src[m.end():i - 1]
            enc = args.count("encoding=")
            ln = src[:m.start()].count("\n") + 1
            # 判据是「恰好一次」而不是「至少一次」：v3.25.5 修复时自己踩过——
            # 多行调用续行里已有 encoding，按行 grep 误判为缺、又塞一个，
            # keyword argument repeated 直接把 make-docx 整条链路炸成 33 项失败。
            if enc > 1:
                bad.append("%s:%d（encoding 重复 %d 次）" % (fn, ln, enc))
            elif enc == 0 and "text=True" in args:
                bad.append("%s:%d" % (fn, ln))
            # 第二道保险：**本文件（check.py）**捕获子进程输出的调用必须显式给
            # env=_utf8_env()。为什么只盯 check.py：它拿子进程输出**做判据匹配**，
            # 一旦解码错位就会把乱码误诊成「判据被删／脚本崩了」——代价最高；
            # 其余脚本的 spawn 只把输出转给人看（且 errors 已设 replace/ignore），
            # 乱码是显示问题而非误判，且它们调的子进程都是本技能脚本（已全部自钉
            # stdout，见第三道）。make-docx 调的是 soffice（外部程序），env 无意义，
            # 一并豁免。这是有意的取舍，不是漏检。
            if fn == "check.py" and ("capture_output" in args or "stdout=subprocess.PIPE" in args):
                if "_utf8_env()" not in args:
                    noenv.append("%s:%d" % (fn, ln))

    # 第三道保险（v3.26.2 千问办公实测抓出）：**每个脚本自己**都要钉 stdout 编码。
    # 只查父侧 encoding 是不够的——父侧写对了、子脚本没钉，照样乱码：
    # 中文 Windows 控制台下子进程按 GBK 写 → 父侧 UTF-8 解出 U+FFFD → 判据全不匹配
    # → 门禁把「编码噪声」误报成「判据被删／脚本崩了」。这是**误诊**，比不检更坏。
    nopin = []
    for fn in sorted(os.listdir(scripts_dir)):
        if not fn.endswith(".py"):
            continue
        if "stdout.reconfigure" not in _read(os.path.join(scripts_dir, fn)):
            nopin.append(fn)

    if bad:
        err("subprocess.run 用了 text=True 却未指定 encoding（Windows 下按 GBK "
            "解码 UTF-8 输出会乱码，装机冒烟会全灭）：%s" % "、".join(bad))
    if noenv:
        err("subprocess.run 捕获子进程输出却未传 env=_utf8_env()（子进程会按 locale 写出，"
            "中文 Windows 下父侧解出乱码，判据全不匹配）：%s" % "、".join(noenv))
    if nopin:
        err("以下脚本未自钉 stdout 编码（`_sys.stdout.reconfigure(encoding=\"utf-8\")`）——"
            "被 spawn 时在非 UTF-8 环境会写出乱码，父侧据此误报判据失效：%s" % "、".join(nopin))
    if not (bad or noenv or nopin):
        n_py = sum(1 for x in os.listdir(scripts_dir) if x.endswith(".py"))
        info("subprocess 编码：text=True 均锁 UTF-8、捕获输出均传 _utf8_env()、"
             "%d 个脚本全部自钉 stdout（三处编码链闭环）" % n_py)


def _check_trigger_words():
    """description 的触发词不得在改写/精简中丢失。

    为什么单立一条（v3.25.4 精简时当场抓到）：「触发词」是 description 的唯一
    职能——用户在对话里说「帮我看看这份合同有没有坑」，模型靠它认出该触发。
    **丢一个词，那一类需求就再也不触发，而且没有任何报错**——技能安静地不工作。
    本轮把 description 从 833 精简到 687 字符时，就漏掉了「强势方／弱势方」
    （写成「与强弱两轴」只留了型、丢了值），说明靠人眼核不可靠。

    判据：给一份必含词清单（文种 / 动作 / 风险维度 / 用户口语 / 立场），
    逐个断言出现在 description 里。清单只增不减——新增能力就补词，
    精简文案时由它兜底，不许为了省字数把词删掉。
    """
    p = os.path.join(ROOT, "SKILL.md")
    if not os.path.exists(p):
        return
    m = re.search(r"(?m)^description:\s*(.+)$", _read(p))
    if not m:
        return
    d = m.group(1)
    MUST = [
        # 文种（用户会直接说这些）
        "合同", "协议", "授权书", "承诺函", "告知书", "声明", "委托书", "制度", "通知",
        "NDA", "SLA", "DPA",
        # 动作（用户会直接说这些）
        "审查", "起草", "修订", "比对", "脱敏", "模板", "法条", "汇编", "体检",
        "精要总结", "思维导图",
        # 风险维度（用户会拿这些词问）
        "违约金", "交付验收", "知识产权", "保密", "竞业", "管辖", "仲裁", "争议解决",
        "诉讼时效", "合同效力", "格式条款", "个人信息", "主体适格", "签章",
        # 立场与口语（立场决定审查口径；口语决定能否被日常说话触发）
        "强势", "弱势", "红线", "风险", "有坑", "回稿",
    ]
    # 判据用「词不被更长同类词吞掉」而不是裸子串包含：
    # 实测教训（连续踩两次）——「强弱势」这个词本身含「强势」「弱势」四字。
    # 裸子串判据下删掉「（强势方/均衡/弱势方）」后，「弱势」仍被判定为在（**漏报**）；
    # 补了「后接势不算」之后仍报不出「弱势」，因为还剩**前一字符是强**这一侧。
    # 故改为双向判断：前后任一方向构成「强弱势」合写，即视为该词未独立出现。
    def _has(word):
        for mm in re.finditer(re.escape(word), d):
            before = d[mm.start() - 1] if mm.start() > 0 else " "
            after = d[mm.end()] if mm.end() < len(d) else " "
            if word in ("强势", "弱势") and (before == "强" or after == "势"):
                # 组成「强弱势」合写：只说强弱、没说立场，不算该词命中
                continue
            return True
        return False

    lost = [w for w in MUST if not _has(w)]
    if lost:
        err("SKILL.md 的 description 丢了触发词：%s"
            "（丢一个词，该类需求就不再触发且无任何报错）" % "、".join(lost))
    else:
        info("description：%d 字符，%d 个必含触发词齐备"
             % (len(d), len(MUST)))


def _check_capability_count():
    """能力项数须与能力表实际行数相符。

    为什么补这条（v3.25.1 质检当场抓出）：v3.25.0 加了第 20 项能力「能汇编」，
    **表里加了行、正文却写「十九项」**——同样的病灶在引擎数上刚犯过一次，
    这次犯在能力数上。两次都是「加了东西但忘了改数字」，说明光靠人记不行。

    口径：以 README「#### N 项能力」小节的表格数据行数为准（那是给用户看的
    权威清单），比对 README 与 SKILL 两处的「N 项能力／N 个能力」表述。
    """
    readme = os.path.join(ROOT, "README.md")
    if not os.path.exists(readme):
        return
    src = _read(readme)
    # 抓能力表：从「| 能力 | 一句话 |」表头起，到非表格行为止
    rows = 0
    in_tbl = False
    for ln in src.splitlines():
        if ln.lstrip().startswith("|") and re.search(r"\|\s*能力\s*\|.*\|", ln):
            in_tbl = True
            continue
        if in_tbl and not ln.lstrip().startswith("|"):
            break
        if in_tbl and ln.lstrip().startswith("| **能"):
            rows += 1
    if not rows:
        return

    def _cn2int(t):
        if t.isdigit():
            return int(t)
        D = "零一二三四五六七八九"
        unit = {"十": 10, "百": 100}
        total, cur = 0, 0
        for ch in t:
            if ch in D:
                cur = D.index(ch)
            elif ch in unit:
                total += (cur or 1) * unit[ch]
                cur = 0
            else:
                return None
        return total + cur

    bad = []
    for rel in ("README.md", "SKILL.md"):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        s = _read(p)
        for mm in re.finditer(r"([一二三四五六七八九十百]+|\d+)\s*(?:项|个)\s*能力", s):
            val = _cn2int(mm.group(1))
            if val is not None and val != rows:
                seg = s[max(0, mm.start() - 10):mm.end() + 4].replace("\n", " ")
                bad.append("%s：「%s」=%d（表内实为 %d 项）…%s"
                           % (rel, mm.group(1), val, rows, seg))
    if bad:
        err("能力项数表述与能力表行数（%d）不符：%s" % (rows, "；".join(bad[:4])))
    else:
        info("能力表：%d 项，正文数量表述相符" % rows)


def _check_engine_ordinal_in_scripts():
    """脚本 docstring 里的「第 N 个引擎」须与引擎表真实编号相符。

    为什么补这一条（v3.25.1 质检当场抓出）：重排把核验引擎从 #11 挪到 #15，
    SKILL 的序号改了、`verify.py` 开头那行「第 11 个引擎」却留着——**代码里的
    序号没有任何人查**。前一条守卫只扫 README/SKILL 正文，脚本自述完全在射程外，
    而脚本 docstring 正是维护者读代码时第一眼看到的东西。

    判据怎么定：**不硬编码映射表**（那又会变成「改一处漏一处」）。改为按引擎表
    里的「实现」列反查——某个脚本名出现在哪一行的实现落点里，那一行的 # 就是它的
    编号；脚本 docstring 若自称「第 N 个引擎」，N 必须与之相等。一个脚本被多行
    点名时（如 make-docx.py 同时是 11/12/13）不判，因为「它是第几个」本身无唯一答案。
    """
    readme = os.path.join(ROOT, "README.md")
    if not os.path.exists(readme):
        return
    # 从引擎表抓 (编号 -> 该行实现列文本)
    owners = {}
    in_tbl = False
    for ln in _read(readme).splitlines():
        if ln.lstrip().startswith("|") and re.search(r"\|\s*#\s*\|.*引擎.*\|", ln):
            in_tbl = True
            continue
        if in_tbl and not ln.lstrip().startswith("|"):
            break
        if not in_tbl:
            continue
        m = re.match(r"^\|\s*(\d+)\s*\|", ln)
        if not m:
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        impl = cols[-2] if len(cols) >= 2 else ""
        owners[int(m.group(1))] = impl
    if not owners:
        return
    # 脚本 -> 被哪些编号点名
    named = {}
    for num, impl in owners.items():
        for fn in re.findall(r"([A-Za-z0-9_\-]+\.py)", impl):
            named.setdefault(fn, set()).add(num)
    bad = []
    for fn, nums in sorted(named.items()):
        if len(nums) > 1:
            continue          # 一线多职，序号无唯一答案
        path = os.path.join(ROOT, "scripts", fn)
        if not os.path.exists(path):
            continue
        m = re.search(r"第\s*(\d+)\s*个引擎", _read(path)[:2000])
        if not m:
            continue
        claim = int(m.group(1))
        real = list(nums)[0]
        if claim != real:
            bad.append("%s 自称「第 %d 个引擎」，引擎表中实为 #%d"
                       % (fn, claim, real))
    if bad:
        err("脚本 docstring 的引擎序号与引擎表不符：%s" % "；".join(bad))


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

    # ---- v3.25.7：只查版本号不够。v3.25.7 发版时实测踩到——版本号改对了，
    # 而 latest.date／summary／changes 还是上一版的，发布页会显示「新版本号配旧更新说明」；
    # 且 history 首条断档（v3.25.6 当初漏记）、文件末尾还留着更早的顶层 version。
    # 这型「改了号没改话」门禁此前完全看不见，故四层咬合：
    #   ① latest.date 须与 VERSION.md 当前版本行的日期一致（同一事实，两处不许分家）；
    #   ② latest 的 summary＋changes 里不得出现别的版本号（出现即说明文案忘改）；
    #   ③ history 首条须为本版（版本链从当前版起）；④ 顶层 version 字段须同步。
    tv = "v" + truth
    vd = str(lat.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", vd):
        err("version.json 的 latest.date 缺失或不是 YYYY-MM-DD：%r" % vd)
    else:
        vm = re.search(r"\|\s*\*\*v" + re.escape(truth) + r"\*\*\s*\|\s*(\d{4}-\d{2}-\d{2})",
                       _read(os.path.join(ROOT, "VERSION.md")))
        if vm and vm.group(1) != vd:
            err("version.json 的 latest.date=%s 与 VERSION.md 当前版本行日期 %s 不一致——"
                "对外清单与沿革各说各话" % (vd, vm.group(1)))
    blob = str(lat.get("summary") or "") + "".join(str(x) for x in (lat.get("changes") or []))
    others = sorted(set(o for o in re.findall(r"v\d+\.\d+\.\d+", blob) if o != tv))
    if others:
        err("version.json 的 latest 说明里出现其他版本号 %s——"
            "发布页会显示「新版本号配旧更新说明」，请同步 latest.summary／changes" % (others,))
    hist = (d or {}).get("history") or []
    if not hist:
        # v3.26.2：分「开发源」与「分包副本」两种身份，不再一概论错。
        # 起因（千问办公实测）：pack.py 从 v3.25.8 起按设计剥离 history，而这里要求
        # history 必须存在——于是同一份 check.py，开发源跑 0 错、装好的副本跑必红，
        # v3.25.8～v3.26.1 每一版都如此，只是此前从没人在产物上跑过门禁。
        # 判据用包内自带标记（pack.py 写 `_分发副本: true`），不靠路径/目录猜测：
        # 有标记＝分发包，history 缺失属设计内（历史不给看，本副本也不带 VERSION.md）；
        # 无标记＝开发源，history 必须存在（删了版本链校验全成空转）。
        if (d or {}).get("_分发副本") is True:
            info("version.json 无 history：本副本为分发包（pack.py 已按设计剥离，"
                 "带 `_分发副本` 标记）——历史版本信息不对外提供，只给最新一版")
        else:
            err("version.json 缺 history 数组——它是开发源的版本链真源，删了"
                "「首条＝本版／条目去重／链接指向自身」全套校验即成空转；"
                "出包时由 pack.py 自动剥离，无需手删（若这确是分发包，须带 `_分发副本: true`）")
    elif str(hist[0].get("version") or "") != tv:
        err("version.json 的 history 首条为 %r，应为当前版本 %s（新版本发布时须把旧 latest 挪入 history）"
            % (hist[0].get("version"), tv))
    top = str((d or {}).get("version") or "").strip().lstrip("vV")
    if top and top != truth:
        err("version.json 顶层 version=%r 与 SKILL.md 版本 %s 不一致"
            "（该字段按 _说明 定义为最新版本号）" % (d.get("version"), truth))
    # history 每条自洽（v3.25.8）：① 版本号不得重复；② files 直链的文件名须含自身版本号。
    # 真实事故：批量改版本串时把 history 里旧条目的链接一起替换了，历史条目指向别版包，
    # 用户点「历史版本」下到的是错的包——字面看一切正常，只有把版本号和链接对上才看得见。
    _seen = {}
    for x in hist:
        hv = str(x.get("version") or "")
        if hv in _seen:
            err("version.json 的 history 里版本号 %s 重复出现" % hv)
        _seen[hv] = 1
        for k, url in (x.get("files") or {}).items():
            u = str(url or "")
            if u and hv and ("_%s_" % hv) not in u:
                err("version.json 的 history[%s] 的 %s 链接指向别版包（…%s）——"
                    "历史条目必须指向自己那一版" % (hv, k, u[-46:]))
                break
    # latest 的直链同理：文件名须含当前版本号（写成别版＝下载页把用户引向旧包）
    for k, url in (lat.get("files") or {}).items():
        u = str(url or "")
        if u and ("_%s_" % tv) not in u:
            err("version.json 的 latest.files.%s 指向的不是当前版本包（…%s）——"
                "下载页会把用户引向旧包" % (k, u[-46:]))
    # VERSION.md 是沿革的唯一载体（history 不随技能分发），故对外公布的每个版本
    # 必须在沿革里出现过；反向不要求（沿革可以记未单独对外说明的版本）。
    # 实测过一次：history 里有 v3.11.9，沿革整行缺——对外公布了沿革里没有的版本。
    _vmd = _read(os.path.join(ROOT, "VERSION.md"))
    _vset = set("v" + x.lower() for x in re.findall(r"(?m)^\| \*\*[vV]([\d.]+)\*\* \|", _vmd))
    if _vset:
        _lost = [x for x in _seen if x.lower() not in _vset]
        if _lost:
            err("version.json 的 history 里有 VERSION.md 沿革未记载的版本：%s——"
                "history 是对外清单，不得公布沿革里没有的版本" % ("、".join(sorted(_lost))))


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


def check_tier_requirement():
    """保真档位体系守卫（设计文档 §4.3 门禁四条）。

    `make-docx.py` 的 `TIER_REQUIREMENT` 是要求类型真源，四条断言：
      1. 键集合必须与 TYPE_ORDER 相同（少/多/拼错即报错）；
      2. 键序必须与 TYPE_ORDER 一致（顺序漂移同样报错）；
      3. 值必须是五种要求类型之一；
      4. TIER_ALLOWED 中每种要求类型的允许落点必须覆盖 CONTENT_ONLY/NEWDOC 合法档，
         且 ORIGINAL_* 不得把 NEWDOC 列为允许落点（落点与要求相容的静态部分）。
    第 1 步（立体系）行为不变：本函数只做静态校验，不运行生成流程。
    """
    mp = os.path.join(HERE, "make-docx.py")
    try:
        import ast as _ast
        tree = _ast.parse(_read(mp))
    except Exception as e:  # noqa: BLE001
        err("档位体系：无法解析 make-docx.py（%s）" % e)
        return

    defs = {}
    for node in tree.body:
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], _ast.Name):
            name = node.targets[0].id
            if name in ("TYPE_ORDER", "TIER_REQUIREMENT", "TIER_LEVELS", "TIER_ALLOWED"):
                try:
                    defs[name] = _ast.literal_eval(node.value)
                except Exception:  # noqa: BLE001
                    err("档位体系：%s 不是可字面求值的常量" % name)
    if "TIER_REQUIREMENT" not in defs:
        err("档位体系：make-docx.py 未定义 TIER_REQUIREMENT（保真档位真源缺失）")
        return
    tier = defs["TIER_REQUIREMENT"]

    to = defs.get("TYPE_ORDER")
    if to is None:
        err("档位体系：make-docx.py 未定义 TYPE_ORDER")
        return
    # 第 1 条：键集合
    if set(tier.keys()) != set(to):
        miss = sorted(set(to) - set(tier.keys()))
        extra = sorted(set(tier.keys()) - set(to))
        err("档位体系：TIER_REQUIREMENT 键集合与 TYPE_ORDER 不一致"
            "（缺 %s / 多 %s）" % (miss or "无", extra or "无"))
    # 第 2 条：键序
    elif list(tier.keys()) != list(to):
        err("档位体系：TIER_REQUIREMENT 键序与 TYPE_ORDER 不一致——"
            "TYPE_ORDER=%s，TIER_REQUIREMENT=%s（顺序漂移同样算错）"
            % (list(to), list(tier.keys())))
    # 第 3 条：值合法
    levels = defs.get("TIER_LEVELS")
    if levels is None:
        err("档位体系：make-docx.py 未定义 TIER_LEVELS（五种要求类型清单缺失）")
    else:
        bad = {k: v for k, v in tier.items() if v not in levels}
        if bad:
            err("档位体系：TIER_REQUIREMENT 含未知要求类型（须为 %s 之一）：%s"
                % (list(levels), bad))
    # 第 4 条：相容矩阵静态自检
    allowed = defs.get("TIER_ALLOWED")
    if allowed is None:
        err("档位体系：make-docx.py 未定义 TIER_ALLOWED（要求→落点相容矩阵缺失）")
    elif levels is not None:
        if set(allowed.keys()) != set(levels):
            err("档位体系：TIER_ALLOWED 键集合与 TIER_LEVELS 不一致"
                "（缺 %s / 多 %s）"
                % (sorted(set(levels) - set(allowed)) or "无",
                   sorted(set(allowed) - set(levels)) or "无"))
        for lv, pts in allowed.items():
            if lv in ("ORIGINAL_STRICT", "ORIGINAL_IF_AVAILABLE") and "NEWDOC" in pts:
                err("档位体系：%s 的允许落点不得含 NEWDOC（与 §4.3 相容矩阵冲突）" % lv)
            if lv == "NEWDOC_ONLY" and set(pts) != {"NEWDOC"}:
                err("档位体系：NEWDOC_ONLY 的允许落点必须恰为 NEWDOC，现为 %s" % (pts,))
    else:
        info("档位体系：TIER_ALLOWED 静态自检跳过（TIER_LEVELS 缺失已另行报错）")
    if not ERRS or not any("档位体系" in m for m in ERRS):
        info("档位体系：TIER_REQUIREMENT 与 TYPE_ORDER 键集合/键序一致，"
             "五种要求类型与相容矩阵自检通过")


def check_format_matrix():
    """格式矩阵守卫（v3.28.0，风格同 check_tier_requirement）。

    格式维度新增 pptx/mindmap 后，「哪类交付物支持哪些格式」不能再靠三个生成器
    字典的隐式键对齐——PPT_GEN/MINDMAP_GEN 漏写一类是**静默缺口**，现有守卫发现不了。
    本守卫六判据（全部 AST 字面求值，静态校验、不跑生成流程）：
      1. FORMAT_ALL 键集合 == FORMAT_LABEL 键集合（少/多即报）；
      2. FORMAT_FALLBACK ∈ FORMAT_ALL；
      3. --formats 帮助串列出的键与 FORMAT_ALL 双向咬合（防帮助串漏登某键）；
      4. PPT_TYPES/MINDMAP_TYPES ⊆ TYPE_ORDER，且 PPT_TYPES ⊆ MINDMAP_TYPES
         （能出 PPT 的必能出导图——PPT 页面可用导图插图）；
      5. PPT_TYPES 各类的 TIER_REQUIREMENT ∈ {NEWDOC_ONLY, CITE_FIDELITY}
         （防把原稿操作件塞进 PPT——幻灯片冒充原稿是保真体系的破口）；
      6. PPT_GEN/MINDMAP_GEN 键集合 ⊆ 对应覆盖集，且 PPT_TYPES 每类都有导图。
    """
    # v3.31.0 引擎拆分：格式家族常量与生成器字典搬到 format-engine.py，
    # 而 TYPE_ORDER／TIER_REQUIREMENT 属交付物类型真源，仍在 make-docx.py。
    # 故两张 AST 分别解析、合并查表——**两边都读**才是拆分后不瞎的写法；
    # 只改路径不改判据，会让第 4/5 条悄悄降级成「未定义即报」的假红。
    mp = os.path.join(HERE, "format-engine.py")
    mp2 = os.path.join(HERE, "make-docx.py")
    try:
        import ast as _ast
        tree = _ast.parse(_read(mp))
        tree2 = _ast.parse(_read(mp2))
    except Exception as e:  # noqa: BLE001
        err("格式矩阵：无法解析 format-engine.py / make-docx.py（%s）" % e)
        return
    want = ("FORMAT_ALL", "FORMAT_FALLBACK", "FORMAT_LABEL",
            "PPT_TYPES", "MINDMAP_TYPES", "TYPE_ORDER", "TIER_REQUIREMENT")
    defs = {}
    for node in list(tree.body) + list(tree2.body):
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], _ast.Name):
            name = node.targets[0].id
            if name in want:
                try:
                    defs[name] = _ast.literal_eval(node.value)
                except Exception:  # noqa: BLE001
                    err("格式矩阵：%s 不是可字面求值的常量" % name)
    # PPT_GEN/MINDMAP_GEN 是函数字典（值不可字面求值），只取键名
    gens = {}
    for node in list(tree.body) + list(tree2.body):
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], _ast.Name) \
                and node.targets[0].id in ("PPT_GEN", "MINDMAP_GEN"):
            try:
                gens[node.targets[0].id] = sorted(
                    k.value for k in node.value.keys)
            except Exception:  # noqa: BLE001
                err("格式矩阵：%s 不是以字符串字面量为键的字典" % node.targets[0].id)
    for name in want:
        if name not in defs:
            err("格式矩阵：未定义 %s（格式真源缺失，应在 format-engine.py 或 make-docx.py）" % name)
            return
    fa, fb, fl = defs["FORMAT_ALL"], defs["FORMAT_FALLBACK"], defs["FORMAT_LABEL"]
    if not isinstance(fa, list) or not fa:
        err("格式矩阵：FORMAT_ALL 须为非空列表")
        return
    # 第 1 条：FORMAT_ALL == FORMAT_LABEL 键集
    if set(fa) != set(fl):
        err("格式矩阵：FORMAT_ALL 与 FORMAT_LABEL 键集合不一致"
            "（缺 %s / 多 %s）" % (sorted(set(fa) - set(fl)) or "无",
                                  sorted(set(fl) - set(fa)) or "无"))
    # 第 2 条：兜底 ∈ 全集
    if fb not in fa:
        err("格式矩阵：FORMAT_FALLBACK=%r 不在 FORMAT_ALL 内" % fb)
    # 第 3 条：帮助串双向咬合
    m = re.search(r'"--formats".*?help="逗号分隔：([a-z,]+)', _read(mp2), re.S)
    if not m:
        err("格式矩阵：--formats 帮助串未匹配到「逗号分隔：<清单>」——格式数守卫与帮助串双向咬合失明")
    else:
        help_keys = [x for x in m.group(1).split(",") if x]
        miss = sorted(set(fa) - set(help_keys))
        extra = sorted(set(help_keys) - set(fa))
        if miss or extra:
            err("格式矩阵：--formats 帮助串与 FORMAT_ALL 不一致"
                "（帮助串缺 %s / 多 %s）——帮助串是格式数真源，漏登即静默少数" % (miss or "无", extra or "无"))
    to = defs["TYPE_ORDER"]
    pt, mt = defs["PPT_TYPES"], defs["MINDMAP_TYPES"]
    # 第 4 条：覆盖集 ⊆ TYPE_ORDER，且 PPT ⊆ 导图
    for label, s in (("PPT_TYPES", pt), ("MINDMAP_TYPES", mt)):
        if not isinstance(s, tuple) or not s:
            err("格式矩阵：%s 须为非空元组" % label)
        elif set(s) - set(to):
            err("格式矩阵：%s 含 TYPE_ORDER 之外的类型：%s" % (label, sorted(set(s) - set(to))))
    if isinstance(pt, tuple) and isinstance(mt, tuple) and set(pt) - set(mt):
        err("格式矩阵：PPT_TYPES 不是 MINDMAP_TYPES 的子集（多出 %s）——"
            "能出 PPT 的必能出导图（PPT 页可插导图 PNG）" % sorted(set(pt) - set(mt)))
    # 第 5 条：PPT 类必须是新建/引文类（防幻灯片冒充原稿）
    tier = defs["TIER_REQUIREMENT"]
    for t in pt:
        if tier.get(t) not in ("NEWDOC_ONLY", "CITE_FIDELITY"):
            err("格式矩阵：PPT_TYPES 含原稿级/内容级交付物 %s（要求=%s）——"
                "PPT 仅覆盖 NEWDOC_ONLY/CITE_FIDELITY 类，原稿操作件不得做成幻灯片"
                % (t, tier.get(t)))
    # 第 6 条：GEN 字典键集 ⊆ 覆盖集，且 PPT 类都有导图
    if "PPT_GEN" not in gens:
        err("格式矩阵：format-engine.py 未定义 PPT_GEN（PPT 生成器字典缺失）")
    elif set(gens["PPT_GEN"]) != set(pt):
        err("格式矩阵：PPT_GEN 键集合与 PPT_TYPES 不一致"
            "（缺 %s / 多 %s）" % (sorted(set(pt) - set(gens["PPT_GEN"])) or "无",
                                  sorted(set(gens["PPT_GEN"]) - set(pt)) or "无"))
    if "MINDMAP_GEN" not in gens:
        err("格式矩阵：format-engine.py 未定义 MINDMAP_GEN（导图生成器字典缺失）")
    elif isinstance(mt, tuple):
        if set(gens["MINDMAP_GEN"]) - set(mt):
            err("格式矩阵：MINDMAP_GEN 含 MINDMAP_TYPES 之外的类型：%s"
                % sorted(set(gens["MINDMAP_GEN"]) - set(mt)))
        elif isinstance(pt, tuple) and set(pt) - set(gens["MINDMAP_GEN"]):
            err("格式矩阵：PPT_TYPES 中 %s 无导图生成器（PPT 类必有导图）"
                % sorted(set(pt) - set(gens["MINDMAP_GEN"])))
    # 第 7 条（v3.32.0）：image 家族咬合——
    #   a. "image" ∈ FORMAT_ALL 时，IMAGE_TYPES/IMG_TYPES 必须在 format-engine.py 定义；
    #   b. IMAGE_TYPES 六子格式 ⊆ {png,jpg,webp,gif,svg,ico}（防写错扩展名）；
    #   c. --image-formats 帮助串列出的子格式与 IMAGE_TYPES 双向咬合；
    #   d. --image-formats 参数必须排在 --formats 之后（数字口径守卫的惰性正则依赖此顺序）。
    if "image" in fa:
        want_img = ("IMAGE_TYPES", "IMG_TYPES")
        idefs = {}
        for node in tree.body:
            if isinstance(node, _ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], _ast.Name) \
                    and node.targets[0].id in want_img:
                try:
                    idefs[node.targets[0].id] = _ast.literal_eval(node.value)
                except Exception:  # noqa: BLE001
                    err("格式矩阵：%s 不是可字面求值的常量" % node.targets[0].id)
        for name in want_img:
            if name not in idefs:
                err("格式矩阵：format-engine.py 未定义 %s（image 家族真源缺失）" % name)
        it = idefs.get("IMAGE_TYPES")
        if isinstance(it, tuple):
            bad_sub = [x for x in it if x not in ("png", "jpg", "webp", "gif", "svg", "ico")]
            if bad_sub:
                err("格式矩阵：IMAGE_TYPES 含不认识的子格式 %s" % bad_sub)
        m2 = re.search(r'"--image-formats".*?help="逗号分隔：([a-z,]+)', _read(mp2), re.S)
        if not m2:
            err("格式矩阵：--image-formats 帮助串未匹配到「逗号分隔：<清单>」——"
                "image 家族的子格式咬合失明")
        elif isinstance(it, tuple):
            h2 = [x for x in m2.group(1).split(",") if x]
            if set(h2) != set(it):
                err("格式矩阵：--image-formats 帮助串与 IMAGE_TYPES 不一致"
                    "（帮助串缺 %s / 多 %s）" % (sorted(set(it) - set(h2)) or "无",
                                                sorted(set(h2) - set(it)) or "无"))
        src_mk = _read(mp2)
        pos_f = src_mk.find('"--formats"')
        pos_i = src_mk.find('"--image-formats"')
        if pos_f < 0 or pos_i < 0 or pos_i < pos_f:
            err("格式矩阵：--image-formats 必须声明在 --formats 之后——"
                "数字口径守卫的惰性正则按「--formats 之后第一处逗号清单」取格式数，"
                "顺序颠倒会把 image 子格式当成格式清单（格式数 8 被读成 6）")
    if not ERRS or not any("格式矩阵" in m for m in ERRS):
        info("格式矩阵：FORMAT_ALL %d 种（image 家族 %d 子格式），覆盖集与生成器字典、"
             "要求类型、帮助串判据自检通过"
             % (len(fa), len(idefs.get("IMAGE_TYPES") or ())))


def check_html_online_guard():
    """HTML 在线增强版守卫（v3.28.0）。

    在线版把白名单 CDN 外链写进产物 HTML——「离线零外部资源」的承诺就此有了例外，
    例外若无守卫必然回潮（要么默认变在线、要么白名单外偷偷加域）。五条断言：
      ① HTML_CDN_ALLOW 存在且非空；
      ② 每项都是纯主机名（无 scheme/路径/端口，防写成 "https://x/y" 绕过比对）；
      ③ 与 SECURITY.md 白名单名单双向一致（同 check_net_tiers 的咬合手法）；
      ④ format-engine.py 全文除常量定义外不得出现白名单以外的 http(s):// 主机字样；
      ⑤ html_page 的 online 参数默认值必须为 False（防「默认在线」回潮）。

    v3.31.0：本守卫原本读 make-docx.py，引擎拆分后白名单与 html_page 都搬进
    format-engine.py——只改代码不改守卫，守卫就会对着空文件「零命中通过」，是假绿。
    E0 口径：脚本自身不出网（红线是「脚本不出网」），产物含外链不改档位——
    本守卫只盯字符串层面的白名单，不涉及任何 import/网络调用。
    """
    # v3.31.0：白名单真源随格式引擎搬到 format-engine.py；hereafter 只读那一个文件。
    mp = os.path.join(HERE, "format-engine.py")
    src = _read(mp)
    m = re.search(r"^HTML_CDN_ALLOW\s*=\s*\(([^)]*)\)", src, re.M | re.S)
    if not m:
        err("HTML 在线守卫：format-engine.py 未定义 HTML_CDN_ALLOW（白名单真源缺失）")
        return
    allow = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip().strip("'\"")]
    if not allow:
        err("HTML 在线守卫：HTML_CDN_ALLOW 为空——在线版将无任何合法外链域")
        return
    for h in allow:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", h) or "/" in h or ":" in h:
            err("HTML 在线守卫：白名单项 %r 不是纯主机名（不得含 scheme/路径/端口）" % h)
        elif not re.match(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", h):
            err("HTML 在线守卫：白名单项 %r 不像合法域名" % h)
    # ③ 与 SECURITY.md 双向一致
    sec_path = os.path.join(ROOT, "SECURITY.md")
    if not os.path.exists(sec_path):
        err("HTML 在线守卫：找不到 SECURITY.md——白名单名单无从比对")
    else:
        sec = _read(os.path.join(ROOT, "SECURITY.md"))
        i = sec.find("白名单 CDN")
        if i < 0:
            err("SECURITY.md 未写「白名单 CDN」段——在线版外链名单须在文档登记，"
                "否则承诺与实现分家（25.2 形态）")
        else:
            sec_hosts = set(re.findall(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}",
                                       sec[i:i + 600]))
            sec_hosts = {h for h in sec_hosts if h in allow} | {
                h for h in allow if h in sec[i:i + 600]}
            miss = [h for h in allow if h not in sec[i:i + 600]]
            extra = [h for h in re.findall(r"(?:cdn|fonts)[a-z0-9.-]*\.[a-z]{2,}", sec[i:i + 600])
                     if h not in allow]
            if miss or extra:
                err("HTML 在线守卫：SECURITY.md 白名单名单与 HTML_CDN_ALLOW 不一致"
                    "（文档缺 %s / 文档多 %s）；两处须同步" % (miss or "无", extra or "无"))
    # ④ 白名单外 http(s):// 主机字样（xmlns 命名空间是标记语法不是外链，先剥除——
    #   v3.29.0 起 mindmap 产物为 SVG，模板含 xmlns="http://www.w3.org/2000/svg" 属正常）
    body = re.sub(r'xmlns="https?://[^"]+"', "", src[m.end():])
    for hm in re.finditer(r"https?://([a-zA-Z0-9.-]+)", body):
        host = hm.group(1).lower()
        if host not in [h.lower() for h in allow]:
            err("HTML 在线守卫：format-engine.py 出现白名单以外的主机字样 %s——"
                "在线版外链域只许 %s，如需扩展请先改白名单真源并同步 SECURITY.md"
                % (host, allow))
            break
    # ⑤ online 默认必须 False
    if not re.search(r"def html_page\([^)]*online\s*=\s*False", src):
        err("HTML 在线守卫：html_page 的 online 参数默认值不是 False——"
            "「默认离线」的承诺不许回潮（在线必须显式 --html-online）")
    if not ERRS or not any("HTML 在线守卫" in m for m in ERRS):
        info("HTML 在线守卫：白名单 %s 与 SECURITY.md 双向一致，默认离线，自检通过" % allow)


def check_mindmap_single_source():
    """导图单一真源守卫（v3.30.0）。

    为什么立这条：思维导图有两条入口——交付物 `--formats mindmap`（数据＝审查规格）
    与精要总结第二十一节（数据＝文档正文大纲）。数据来源不同是设计，**但渲染器必须同一套**；
    若两处各写一套，改了一处另一处不跟，就会静默分家（铁律第 12 条）。此前"同源"只写在
    SKILL 文档里，没有任何代码在盯——正是「文档写一套、代码做一套」的 25.2 形态。

    四条断言（AST 静态）：
      ① mindmap_svg / mindmap_html / mindmap_png 三个渲染函数存在且可解析；
      ② export_summary_mindmap（精要入口）的函数体必须**直接调用**上述三个函数名；
      ③ export_mindmap（交付物入口）同样必须调用三者（默认 SVG，HTML/PNG 按开关）；
      ④ 精要产物必须落隔离目录——函数体须出现 summary_dir 调用（防"总结件混进审查件"）。
    """
    # v3.31.0：三个渲染器搬进 format-engine.py，两个入口 wrapper 留在 make-docx.py
    # （export_summary_mindmap 要写 _精要总结/ 隔离目录、export_mindmap 要用 CLI 侧 outname）。
    # 故两个文件都解析：渲染函数找 format-engine，入口 wrapper 找 make-docx。
    # 只改一处路径就会让下面四条断言全部落空、守卫静默变瞎。
    mp = os.path.join(HERE, "make-docx.py")
    mp2 = os.path.join(HERE, "format-engine.py")
    try:
        import ast as _ast
        tree = _ast.parse(_read(mp))
        tree2 = _ast.parse(_read(mp2))
    except Exception as e:  # noqa: BLE001
        err("导图单一真源：无法解析 make-docx.py / format-engine.py（%s）" % e)
        return
    funcs = {}
    for node in list(tree.body) + list(tree2.body):
        if isinstance(node, _ast.FunctionDef):
            funcs[node.name] = node
    render = ("mindmap_svg", "mindmap_html", "mindmap_png")
    lack = [f for f in render if f not in funcs]
    if lack:
        err("导图单一真源：缺少渲染函数 %s——两种入口须共用同一套渲染器" % "、".join(lack))
        return
    for entry, need_dir in (("export_summary_mindmap", True), ("export_mindmap", False)):
        fn = funcs.get(entry)
        if fn is None:
            err("导图单一真源：缺少入口函数 %s" % entry)
            continue
        calls = {n.func.id for n in _ast.walk(fn)
                 if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)}
        miss = [r for r in render if r not in calls]
        if miss:
            err("导图单一真源：%s 未调用 %s——另起了一套渲染实现，两入口就此分家（第 12 条）"
                % (entry, "、".join(miss)))
        if need_dir and "summary_dir" not in calls:
            err("导图单一真源：export_summary_mindmap 未调用 summary_dir——"
                "精要产物必须落 _精要总结/ 隔离目录，不得与审查件混放")
    if not ERRS or not any("导图单一真源" in m for m in ERRS):
        info("导图单一真源：交付物与精要总结两入口共用 svg/html/png 三渲染器，精要产物隔离输出，自检通过")


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


def check_template_library():
    """模板库三真源咬合（v3.34.0）：目录／清单／指纹基线，缺一即报。

    为什么单设一条：此前 `tpl-engine.py` 的 manifest_md() 注释写着「check.py 会比对
    两者是否一致」，实际 check.py 里**根本没有**这条判据；template-guide.md 又承诺
    「改了模板没换版本号，脚本会拦下」，而 parse_meta_line 只校验 X.Y.Z 格式。
    两句都是「注释／文档说了、代码没做」。本守卫把两句兑现成机械判据：
      · 清单与实扫不一致 → 报出双方读数；
      · 正文改了但版本号没换（或版本换了正文没动）→ 报错；
      · 库目录不存在／没有 .tpl.md／基线缺失 → 一律 err，不静默跳过（12.5.4.2）。
    「有守卫」本身也要验：smoke-test.py 配反向注入，改坏清单或正文须当场报红。
    """
    td = os.path.join(ROOT, "templates")
    if not os.path.isdir(td):
        err("模板库目录缺失：templates/（随包内置示范模板＋清单＋指纹基线）")
        return
    tpls = [f for f in sorted(os.listdir(td)) if f.endswith(".tpl.md")]
    if not tpls:
        err("模板库 templates/ 内没有任何 .tpl.md 模板——库为空，清单与基线无从生效")
        return
    # 打包白名单：库不在 FULL_DIRS 里，则包里根本没有库，门禁却在开发源上判绿＝假绿
    pack = os.path.join(HERE, "pack.py")
    if os.path.exists(pack):
        pk = _read(pack)
        if not re.search(r"(?m)^TPL_DIR\s*=\s*[\"']templates[\"']", pk) or \
           "TPL_DIR" not in re.search(r"(?m)^FULL_DIRS\s*=.*$", pk).group(0):
            err("模板库 templates/ 未登记进 pack.py 的 FULL_DIRS——包内会缺库，"
                "本地门禁判绿属假绿")
    try:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_ck_tpl_lib", os.path.join(HERE, "tpl-engine.py"))
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
    except Exception as e:
        err("模板库守卫无法加载 tpl-engine.py：%s" % e)
        return
    problems = m.verify_manifest(td) + m.verify_baseline(td)
    if problems:
        err("模板库三真源不一致（%d 项）：%s" % (len(problems), "；".join(problems[:4])))
    else:
        info("模板库：%d 份模板，清单与指纹基线均与实扫一致" % len(tpls))


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
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=_utf8_env(), timeout=120)
    except Exception as e:
        err("条号对位自检跑不起来：%s" % e)
        return
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"引用 (\d+) 条｜基线 (\d+) 条｜条号位移 (\d+) 处｜条文变动 (\d+) 条",
                  out)
    if not m:
        hint = _garbled_hint(out)
        if hint:
            err(hint + "\n原始输出（乱码）：" + out.strip()[:160])
            return
        if r.returncode != 0:
            err("条号对位自检跑挂了（退出 %d）：%s"
                % (r.returncode, out.strip()[:200]))
            return
        err("条号对位自检输出无法解析（退出 0 但格式变了）：%s" % out.strip()[:200])
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
def _utf8_env():
    """给被 spawn 的子进程一份**强制 UTF-8** 的环境（编码链的第二道保险）。

    v3.26.2 千问办公实测：装好的副本跑 check.py 报两条 [E]——
    「条号对位自检输出无法解析（脚本可能崩了）」与「巡检自检缺少关键判据项，判据被删或改名」。
    两条**都是误诊**：真实原因是子脚本没自钉 stdout 编码，中文 Windows 控制台下按 GBK 写出，
    父侧按 UTF-8 解读出 U+FFFD 乱码 → 三条判据一条都匹配不上 → 被说成「判据被删」。
    **把编码噪声报成了红线失效，比不做检查更坏**：人按提示去查判据，越查越远。

    第一道是子脚本自身 `stdout.reconfigure(encoding="utf-8")`（28 个脚本全覆盖）；
    这里再做第二道，从环境上掐掉「子进程按非 UTF-8 写出」的可能——万一以后新加脚本漏钉。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _garbled_hint(out, n_scripts=None):
    """输出里出现 U+FFFD 替换符 ⇒ 编码链断了，不是脚本崩了、也不是判据被删。

    返回非空串＝确诊编码问题（调用方用它的文案报错）；返回空串＝输出可正常解读。
    单独成函数的原因：两处 spawn（legal-verify、freshness-patrol）都要这个判断，
    文案写两遍必分家——这正是本项目反复踩的「多处重写」型病灶。
    """
    n = (out or "").count("\ufffd")
    if not n:
        return ""
    exp = "28" if n_scripts is None else str(n_scripts)
    return ("子进程输出解码异常（含 %d 个替换符 U+FFFD）——**这是编码链断裂，不是脚本崩了，"
            "也不是判据被删或改名**。成因：子脚本未自钉 stdout 编码，或运行环境强制了非 UTF-8"
            "（中文 Windows 控制台即 GBK）。自检：`grep -l 'stdout.reconfigure' scripts/*.py "
            "| wc -l` 应为 %s；父侧已强制 PYTHONIOENCODING=utf-8，若仍复发说明该脚本被绕过"
            "（如被别的解释器启动）。**本项按「输出不可信」处理，不放行。**" % (n, exp))


def _read(p):
    if not os.path.exists(p):
        # 文件不在就按空内容处理：调用方一律是「有内容才校验」，空串自然跳过。
        # 分发包按设计不带 VERSION.md（沿革不随包），这里不能因此抛 FileNotFoundError
        # ——否则「装完即红」会从 history 换到这个路径上再来一次。
        return ""
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


def check_type_numbering():
    """交付物类型编号咬合守卫（v3.32.1 加）：三处 10 类清单必须同号同名。

    背景（事故留痕）：v3.27.0 重排编号（默认两类 1、2 置前）后，SKILL 第三节清单
    的 2/5 没跟上（2 写成批注版、5 写成报告），与 1.0.2 清单、make-docx.py 文件头、
    安装使用教程、提示词版全部相反；另有多处「4 批注版」「1、3 走原稿级修订」等
    旧编号残留。两处同题不同号，用户按哪处作答都有一半概率拿错件。
    守卫对三处清单各抽「编号 → 类型名」映射，互相比对——
    任何一处漂移（改名单没改号、互换两行只改一行）即红。
    """
    md = _read(os.path.join(ROOT, "scripts", "make-docx.py"))
    sk = _read(os.path.join(ROOT, "SKILL.md"))
    if not md or not sk:
        return

    def pairs(text, rx):
        out = {}
        for n, name in re.findall(rx, text):
            n = int(n)
            if 1 <= n <= 10 and n not in out:
                out[n] = name
        return out

    # 真源①：make-docx.py 文件头清单（`1) 修订版（首选）  2) 审查意见报告 …`）
    src_engine = pairs(md, r"(\d{1,2})\)\s*(修订版|审查意见报告|清洁版|红线标记修订版|审查意见批注版|原文脱敏版|原文照录版|文件比对报告|新旧比对|模板版)")
    # 真源②：SKILL 1.0.2 开场清单第 8 题（`1 修订版（默认） ｜ 2 审查意见报告 …`）
    src_list = pairs(sk, r"(\d{1,2})\s+(修订版|审查意见报告|清洁版|红线标记修订版|审查意见批注版|原文脱敏版|原文照录版|文件比对报告|新旧比对|模板版)")
    # 真源③：SKILL 第三节交付物清单（`2.  审查意见报告 —— …`）
    _m3 = re.search(r"```\s*\n(\s*【Qn · 交付物类型.*?)```", sk, re.S)
    src_sec = pairs(_m3.group(1), r"(\d{1,2})\.\s+(修订版|审查意见报告|清洁版|红线标记修订版|审查意见批注版|原文脱敏版|原文照录版|文件比对报告|新旧比对|模板版)") if _m3 else {}

    if len(src_engine) != 10:
        err("类型编号咬合：make-docx.py 文件头清单只解析出 %d 类（应为 10 类）——清单被改形" % len(src_engine))
        return
    if len(src_list) != 10:
        err("类型编号咬合：SKILL 1.0.2 清单第 8 题只解析出 %d 类（应为 10 类）——清单被改形" % len(src_list))
        return
    if len(src_sec) != 10:
        err("类型编号咬合：SKILL 第三节交付物清单只解析出 %d 类（应为 10 类）——清单被改形" % len(src_sec))
        return
    for label, got in (("SKILL 1.0.2 清单", src_list), ("SKILL 第三节清单", src_sec)):
        diff = {n: (src_engine[n], got[n]) for n in sorted(src_engine) if got.get(n) != src_engine[n]}
        if diff:
            bad = "；".join("第%d类 真源=%s/该处=%s" % (n, a, b) for n, (a, b) in diff.items())
            err("类型编号咬合：%s 与 make-docx.py 文件头不一致（%s）——"
                "两处同题不同号，用户按号作答会拿错件" % (label, bad))
            return
    info("类型编号咬合：make-docx 文件头 ↔ SKILL 1.0.2 清单 ↔ SKILL 第三节清单，10 类同号同名")


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
        _check_doc_consistency()
        check_type_numbering()
        _check_pseudo_controls()
        _check_menu_entries()
        check_package_fields()
        check_naming_fields()
        check_platform_limit()
        check_sample_baseline()
        check_legal_db()
        check_legal_crosscheck()
        check_cite_alignment()
        check_freshness_engine()
        check_net_tiers()
        check_net_tier_consistency()
        check_security_matrix()
        check_tpl_engine()
        check_template_library()
        check_verify_engine()
        check_tier_requirement()
        check_format_matrix()
        check_html_online_guard()
        check_mindmap_single_source()
        check_ai_tells_rules()
        check_imbalance_engine()
        check_engine_implementations()
        check_reproducible_build()
        check_gitignore()
        check_skill_ext_lowercase()
        check_version_consistency()
        _check_questionnaire_libraries()
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
