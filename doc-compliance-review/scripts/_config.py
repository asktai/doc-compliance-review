#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
"""
文档合规审查助手AI合同 · 配置加载模块
===============================================
用途：把"工具路径 / 默认工作目录 / 渲染开关"从脚本中剥离到 `scripts/config.json`，
      使技能可跨机器、跨盘符部署而无需修改源码。

优先级：命令行参数 > 环境变量 DOC_REVIEW_BASE > config.local.json（本机覆盖，不进 git／不随包）
        > config.json（随包，不含本机路径）> 内置默认值（tools 一律留空＝按 PATH 自动探测）。

工具路径**允许自定义、但从不强制**：留空时按 PATH 中的命令名自动探测；填了绝对路径则优先用之，
路径不存在时自动回退 PATH，不作为错误——只有 PATH 里也找不到才算工具未安装。
想固定路径就用 `detect-tools.py --write`（写入 config.local.json）。

用法：
    import _config
    cfg = _config.load()
    soffice  = _config.tool(cfg, "soffice")
    base_dir = _config.workdir(cfg, "base_dir")
    tesseract, tessdata = _config.tess(cfg)
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
import json
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "config.json")
# 本机覆盖层：**不进 git、不随发布包**，只承载当前这台机器的工具路径。
# 想自定义就写这里（detect-tools.py --write 默认写它），从不修改随包的 config.json。
LOCAL_PATH = os.path.join(_HERE, "config.local.json")

# ---- 工作根目录解析（不写死盘符）-------------------------------------------
# base_dir 三种取值：
#   1) 绝对路径   —— 用户自定义，最高优先（可用 set-workdir.py --set 写入）
#   2) "auto"/空  —— 按候选链自动探测（推荐盘 → 文档库 → 用户目录 → 临时目录）
#   3) 环境变量 DOC_REVIEW_BASE —— 临时覆盖，优先级高于 config.json
WORKDIR_NAME = "文档合规审查报告"   # 工作根目录的目录名
ENV_BASE = "DOC_REVIEW_BASE"       # 临时覆盖工作根目录的环境变量名
AUTO_TOKENS = ("", "auto", "autodetect", "自动")   # 视为"自动探测"的取值

DEFAULTS = {
    # 工具路径**一律留空**＝按 PATH 自动探测，不写死任何盘符与安装位置。
    # 需要固定到某个安装位置时，跑 `detect-tools.py --write` 写入本机覆盖层
    # config.local.json（不进 git、不随包）；随包配置保持"零本机痕迹"。
    "tools": {
        "soffice": "",
        "pdftotext": "",
        "pdftoppm": "",
        "tesseract": "",
        "tessdata": "",
    },
    "workdir": {
        "base_dir": "auto",
        "in_dir": "",
        "out_dir": "",
    },
    "render": {
        "pdf_export": True,
        "pdf_timeout_sec": 180,
    },
    "privacy": {
        "fulltext_gate": True,          # 全文进模型前先确认密级
        "on_confidential": "local_only",  # 涉密文档的处理方式：local_only（纯本地脱敏）/ask（逐次询问）
        "warn_before_context": True,    # 读全文前显式提示数据出域
    },
    "output": {
        "per_source_subdir": True,      # 交付物自动落到以文档名命名的子目录（多客户不混放）
        "harden_acl": False,            # 输出目录访问控制（需显式运行 harden-dir.py 生效）
    },
}

# 配置项缺失时回退到 PATH 的命令名
_PATH_FALLBACK = {
    "soffice": "soffice",
    "pdftotext": "pdftotext",
    "pdftoppm": "pdftoppm",
    "tesseract": "tesseract",
}


def _deepcopy(d):
    return json.loads(json.dumps(d))


def load():
    """按「内置默认值 → config.json → config.local.json」三层叠加读出配置。

    后一层覆盖前一层。内置默认值与随包 config.json **不写死任何本机路径**，
    本机专属设定一律落在 `config.local.json`（不进 git、不随包）。
    任何一层解析异常都跳过它继续用上一层，绝不阻断主流程。
    """
    cfg = _deepcopy(DEFAULTS)
    for path in (CONFIG_PATH, LOCAL_PATH):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                user = json.load(f)
        except Exception as e:  # 配置损坏不应阻断主流程
            print("[config] %s 解析失败，跳过该层用上一层：%s"
                  % (os.path.basename(path), e))
            continue
        for k, v in (user or {}).items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update({kk: vv for kk, vv in v.items()})
            else:
                cfg[k] = v
    return cfg


def tool(cfg, key):
    """返回工具可执行路径：配置的绝对路径存在则用之，否则回退为命令名（依赖 PATH）。"""
    p = ((cfg.get("tools") or {}).get(key) or "").strip()
    if p and os.path.exists(p):
        return p
    return _PATH_FALLBACK.get(key, p)


def tool_available(cfg, key):
    """工具是否可用（绝对路径存在，或 PATH 中存在同名命令）。"""
    p = ((cfg.get("tools") or {}).get(key) or "").strip()
    if p and os.path.exists(p):
        return True
    name = _PATH_FALLBACK.get(key, "")
    if not name:
        return False
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        try:
            cand = os.path.join(d, name)
            if os.path.exists(cand) or os.path.exists(cand + ".exe"):
                return True
        except Exception:
            continue
    return False


def _drive_ok(path):
    """盘符是否存在（Windows 形如 D:\\...；非 Windows 恒真）。"""
    if len(path) >= 2 and path[1] == ":":
        try:
            return os.path.exists(path[:2] + os.sep)
        except Exception:
            return False
    return True


def _usable(path, create=False):
    """该目录能否落地：盘符存在，且已存在或可创建。"""
    if not path or not _drive_ok(path):
        return False
    if os.path.isdir(path):
        return True
    if not create:
        return os.path.exists(os.path.dirname(path) or path)
    try:
        os.makedirs(path, exist_ok=True)
        return os.path.isdir(path)
    except Exception:
        return False


def base_candidates(cfg):
    """工作根目录候选链：[(来源标签, 绝对路径, 是否可用)]，按优先级排列。

    只做探测、不建目录（避免一次探测建出一串空目录）。
    """
    out = []
    env = (os.environ.get(ENV_BASE) or "").strip()
    if env:
        p = os.path.abspath(env)
        out.append(("环境变量 %s" % ENV_BASE, p, _usable(p)))
    raw = ((cfg.get("workdir") or {}).get("base_dir") or "").strip()
    if raw and raw.lower() not in AUTO_TOKENS:
        p = os.path.abspath(raw)
        out.append(("config.json", p, _usable(p)))
    home = os.path.expanduser("~")
    auto = [
        ("推荐盘 D:", os.path.join("D:" + os.sep, WORKDIR_NAME)),
        ("文档库", os.path.join(home, "Documents", WORKDIR_NAME)),
        ("用户目录", os.path.join(home, WORKDIR_NAME)),
        ("临时目录", os.path.join(tempfile.gettempdir(), WORKDIR_NAME)),
    ]
    for label, p in auto:
        out.append((label, p, _usable(p)))
    return out


def resolve_base(cfg, create=True):
    """按优先级解析工作根目录，返回 (绝对路径, 来源标签)。

    自定义路径（环境变量 / config.json）不可用时，继续向下探测，
    因此换机、无 D 盘都不会因路径不存在而中断。create=True 时建目录。
    """
    for label, path, ok in base_candidates(cfg):
        if not ok:
            continue
        if create:
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                continue
        return path, label
    p = os.path.join(tempfile.gettempdir(), WORKDIR_NAME)
    try:
        os.makedirs(p, exist_ok=True)
    except Exception:
        pass
    return p, "兜底"


def workdir(cfg, key, default=None):
    """取工作目录配置项。

    base_dir 为 auto/空时走候选链自动解析（返回真实存在的绝对路径）；
    其余键为空时返回 default 或内置默认值。
    """
    val = ((cfg.get("workdir") or {}).get(key) or "").strip()
    if key == "base_dir":
        if val and val.lower() not in AUTO_TOKENS:
            return val
        if default is not None:
            return default
        return resolve_base(cfg)[0]
    if val:
        return val
    if default is not None:
        return default
    return (DEFAULTS["workdir"].get(key) or "")


def tess(cfg):
    """返回 (tesseract 可执行文件, tessdata 目录)。"""
    return tool(cfg, "tesseract"), ((cfg.get("tools") or {}).get("tessdata") or "")


def render_opt(cfg, key):
    return (cfg.get("render") or {}).get(key, DEFAULTS["render"].get(key))


def privacy_opt(cfg, key):
    """隐私/数据出域策略（low-risk-1）。"""
    return (cfg.get("privacy") or {}).get(key, DEFAULTS["privacy"].get(key))


def output_opt(cfg, key):
    """输出隔离策略（low-risk-2）。"""
    return (cfg.get("output") or {}).get(key, DEFAULTS["output"].get(key))


if __name__ == "__main__":
    c = load()
    print("[config] 文件：", CONFIG_PATH, "存在" if os.path.exists(CONFIG_PATH) else "不存在")
    for k in ("soffice", "pdftotext", "pdftoppm", "tesseract"):
        print(f"  {k:10s} -> {tool(c, k)}   可用={tool_available(c, k)}")
    base, src = resolve_base(c, create=False)
    print("  base_dir   ->", base, "   [来源: %s]" % src)
    for label, p, ok in base_candidates(c):
        print("     候选 %-14s %-46s %s" % (label, p, "可用" if ok else "不可用"))
    print("  out_dir    ->", (workdir(c, "out_dir") or os.path.join(base, "输出")))
    print("  privacy    -> fulltext_gate=%s on_confidential=%s" % (
        privacy_opt(c, "fulltext_gate"), privacy_opt(c, "on_confidential")))
    print("  output     -> per_source_subdir=%s harden_acl=%s" % (
        output_opt(c, "per_source_subdir"), output_opt(c, "harden_acl")))
