#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同审核全能版 · 结构校验与环境自检（Python 版）
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
    "文档合规审查助手AI合同审核提示词版.md",
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
               os.path.join("scripts", "TONE.md"), "文档合规审查助手AI合同审核提示词版.md", "SECURITY.md"):
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
    """规则ID组字母白名单：①三脚本彼此一致 ②覆盖 core/01 实际用到的全部组。
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
DISC_FULL_DOCS = ["SKILL.md", "LICENSE.md", "安装使用教程.md", "文档合规审查助手AI合同审核提示词版.md"]
DISC_KEY_DOCS = ["README.md", "scripts/make-docx.py", "SECURITY.md", "core/01-general-risk-rules.md"]


def _norm(t):
    """去掉 Markdown 强调符与全部空白，便于跨排版比对同一句话。"""
    return re.sub(r"[*_\s]", "", t or "")


def check_disclaimer():
    """《免责声明》口径一致：每次使用先输出的那段，入口文档须逐字一致。

    入口文档（SKILL.md / LICENSE.md / 安装使用教程.md / 文档合规审查助手AI合同审核提示词版.md）要求**逐字全文**；
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
        err("SKILL.md 启动流程缺「步骤 0.0 免责声明」（每次使用先输出）")


# ---------------------------------------------------------------- 长文档分批口径
BATCH_DOCS = ["SKILL.md", "文档合规审查助手AI合同审核提示词版.md"]
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
    cur = ("V" + m.group(1)) if m else None
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
    # ① 其他脚本所在行（check.py 的 12 项、pack.py 的 5 项都不是冒烟项数）
    # ② 列表式表述「N 项：结构／字段／…」——那是分项的枚举，不是总数
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
            "文档合规审查助手AI合同审核提示词版.md")

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
    if not (fmt_bad or menu_bad or seed_bad):
        info("数字口径：格式／菜单项数／内置库数三处与真源一致（%s）" % "、".join(src_note))


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
    v = "V" + ver
    bad = []
    # SKILL 正文标题里的版本串
    if not re.search(r"\*\*%s\*\*" % re.escape(v), t):
        bad.append("SKILL.md 正文标题")
    # 各文档里应出现该版本串
    for rel in ("README.md", "SECURITY.md", "文档合规审查助手AI合同审核提示词版.md"):
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
        if hits and str(n_py) not in hits:
            bad.append("%s(脚本数=%d，文档写%s)" % (rel, n_py, "/".join(sorted(hits))))
    if bad:
        err("版本号 %s 未同步：%s" % (v, "、".join(bad)))
    else:
        info("版本一致性: %s（frontmatter / 正文 / README / SECURITY / 提示词版）一致；脚本数 %d 口径同步" % (v, n_py))


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
    ap = argparse.ArgumentParser(description="文档合规审查助手AI合同审核全能版 · 结构与环境自检（Python 版，替代 check.ps1）")
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
        check_sample_baseline()
        check_version_consistency()
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
    print("通过：结构 / 字段 / 头标 / 去企业化 / 规则ID / 免责声明 / 长文档分批 / 规则元数据 / 样例基线 / 版本一致性 / 配置 / 安全项 无错误（警告 %d 项，提示 %d 项）。"
          % (len(WARNS), len(INFOS)))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
