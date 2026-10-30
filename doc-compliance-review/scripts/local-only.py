#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""
文档合规审查助手AI合同 · 纯本地链路（local-only）
===========================================================
用途（对应安全项「审查模式需将文档全文读入模型上下文」的缓解措施）：
    当文档涉密、或不允许外发到任何模型/云平台时，用本脚本完成**提取 + 脱敏**，
    产出可安全外发的脱敏文本；**全程不联网、不调用 AI、不进模型上下文**。

链路：preprocess.py（本机 LibreOffice/Poppler/Tesseract 提取清洗）→ desensitize.py（本机正则脱敏）
      两者均为纯本地脚本；本脚本自身除调用上述两个本地脚本外，不发起任何网络请求。

用法：
    python local-only.py <文件或目录> [--types ...] [--keep ...] [--names 张三,李四]
                                       [--irreversible] [--no-ocr]
                                       [--base <工作根目录>] [--clean-workdir]

脱敏口径（重要）：本链路面向**对外出域**，默认 **10 类全脱**（证件号/电话/银行/邮箱/邮编/IM/
    信用代码/绝对金额/地址/人名），与「审查用脱敏」的默认口径（只脱 6 类、保留信用代码/金额/地址/人名
    以便尽调比对）**不同**——后者不适用于外发场景。
    如需保留某类，用 --keep（如 --keep amount）；--names 传入正则识不到的确切人名（逗号分隔）。

产出：
    <base>/输出/<文档名>/text/<文档名>.clean.txt          清洗后原文（本机留存，勿外发）
    <base>/输出/<文档名>/text/<文档名>.clean.txt.masked.txt  **脱敏后可外发文本**
    映射表 → 隔离目录（默认 ~/.dcr-maps/，仅留本机、勿随交付物外发）；--irreversible 则不生成

说明：本链路不含「审查」环节——脱敏文本可再交模型审查；若文档不涉密，直接走正常审查流程即可。
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
import subprocess
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, HERE)
try:
    import _config as _cfgmod
    _CFG = _cfgmod.load()
except Exception:
    _cfgmod = None
    _CFG = {}

# 脱敏口径的唯一真源：types 默认值直接取 desensitize.ALL_TYPES，不在本文件写死第二份
try:
    import desensitize as _d
except Exception:
    _d = None

BASE_DIR = (_cfgmod.workdir(_CFG, "base_dir") if _cfgmod
            else os.path.join(os.path.expanduser("~"), "文档合规审查报告"))
OUT_DIR = ((_cfgmod.workdir(_CFG, "out_dir") if _cfgmod else "") or os.path.join(BASE_DIR, "输出"))

SUPPORTED = (".doc", ".docx", ".rtf", ".wps", ".odt", ".pdf", ".txt", ".md",
             ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def run(cmd, label):
    print("[local-only] %s …" % label)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if p.returncode != 0:
        print("[local-only] %s 失败（exit=%d）" % (label, p.returncode))
        if p.stdout:
            print(p.stdout.strip()[-1500:])
        if p.stderr:
            print(p.stderr.strip()[-1500:])
    return p.returncode


def collect(target):
    if os.path.isfile(target):
        return [target]
    out = []
    for r, d, fs in os.walk(target):
        d[:] = [x for x in d if x not in ("__pycache__",)]
        out += [os.path.join(r, f) for f in fs if f.lower().endswith(SUPPORTED)]
    return out


def main():
    ap = argparse.ArgumentParser(description="纯本地链路：提取 + 脱敏（不联网、不调 AI、不进模型）")
    ap.add_argument("target", help="待处理的文件或目录")
    # 直接引用 desensitize.py 的 ALL_TYPES（10 类全脱），不在本文件第二处写死，避免改口径时漏改。
    # 别名 landline/wechat/dingtalk 由 desensitize 内部映射到 phone / im，旧写法仍可传入。
    ap.add_argument("--types",
                    default=(_d.ALL_TYPES if _d else
                             "idcard,phone,bank,email,postcode,im,uscc,amount,addr,name"),
                    help="脱敏类型，逗号分隔（默认 10 类全脱；区别于审查用脱敏的 6 类默认）")
    ap.add_argument("--keep", default="", help="保留不脱的类型，逗号分隔（如 amount）")
    ap.add_argument("--names", default="", help="额外确切人名，逗号分隔（正则识不到的人名兜底）")
    ap.add_argument("--irreversible", action="store_true", help="不可逆占位，不生成映射表（无需回填时更安全）")
    ap.add_argument("--no-ocr", action="store_true", help="跳过扫描件 OCR")
    ap.add_argument("--base", default=None, help="工作根目录（默认取 config.json）")
    ap.add_argument("--clean-workdir", action="store_true", help="完成后删除中间产物（raw/_tmp），仅留脱敏文本")
    a = ap.parse_args()

    base = a.base or BASE_DIR
    out_dir = os.path.join(base, "输出")
    print("[local-only] 纯本地模式：不联网、不调用 AI、文档全文不进入模型上下文。")
    print("[local-only] 脱敏口径：%s%s（对外出域建议 10 类全脱）"
          % (a.types, ("；保留 " + a.keep) if a.keep else ""))
    print("[local-only] 工作根目录：%s" % base)

    files = collect(a.target)
    if not files:
        print("[local-only] 未发现可处理文档（支持 %s）" % ", ".join(SUPPORTED))
        return 2

    ok, masked_list = 0, []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        cmd = [_sys.executable, os.path.join(HERE, "preprocess.py"), f, "--base", base]
        if a.no_ocr:
            cmd.append("--no-ocr")
        if run(cmd, "提取清洗 %s" % os.path.basename(f)) != 0:
            continue
        clean = os.path.join(out_dir, stem, "text", stem + ".clean.txt")
        if not os.path.exists(clean):
            print("[local-only] 未找到清洗文本，跳过：%s" % clean)
            continue
        mcmd = [_sys.executable, os.path.join(HERE, "desensitize.py"), "mask", clean,
                "--types", a.types]
        if a.keep:
            mcmd += ["--keep", a.keep]
        if a.names:
            mcmd += ["--names", a.names]
        if a.irreversible:
            mcmd.append("--irreversible")
        if run(mcmd, "脱敏 %s" % stem) != 0:
            continue
        masked = clean + ".masked.txt"
        if os.path.exists(masked):
            masked_list.append(masked)
            ok += 1
        if a.clean_workdir:
            import shutil
            for d in ("raw", "_tmp"):
                shutil.rmtree(os.path.join(out_dir, stem, d), ignore_errors=True)

    print("\n[local-only] 完成：%d/%d 份成功。" % (ok, len(files)))
    for m in masked_list:
        print("  可外发（脱敏后）→ %s" % m)
    if masked_list and not a.irreversible:
        mapdir = os.environ.get("DCR_MAP_DIR") or os.path.join(os.path.expanduser("~"), ".dcr-maps")
        print("  映射表（含真实值，仅留本机、勿外发）→ %s" % mapdir)
    print("  提示：清洗后原文（*.clean.txt）含真实信息，本机留存、勿外发。")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    _sys.exit(main())
