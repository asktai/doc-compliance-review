#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同审核全能版 · 端到端冒烟测试（smoke-test）
===============================================================
用途：一条命令验证本机环境下技能链路是否可用——预处理（提取/清洗/留痕）→ 交付物产出
      （9 类型 × docx/excel/pdf）→ 结果自检，逐项打印 PASS/FAIL 并以退出码反映结果。

用法：
    python smoke-test.py [--base <工作根目录，默认取 config.json>] [--keep] [--in-base] [--full] [--fast]

    （默认）快速档：跳过 PDF 导出与 OCR 等耗时项，这些项记 SKIP、**项数不变**，
            保留链路与内容断言；实测耗时约为全量档的一半（约 40 秒 vs 90 秒）。
            **日常改动后跑这个即可**，省时省资源。
    --full    全量档：含 PDF 导出与 OCR，**装机验收与发版前请跑这一档**。
    --fast    （兼容旧用法）即快速档；因快速档已设为默认，此参数可省略、保留只为不打断旧脚本。
    --keep    保留测试产物（默认测试完成后清理临时目录）
    --in-base 把测试产物写入 <base>/输出（默认写入**系统临时目录**，不污染正式输出区）

产物隔离说明：测试产物默认落在系统临时目录（如 %TEMP%\\dcr-smoke\\_smoke-*），
即使清理被安全策略拦住，也不会混入 base/输出 这一客户文档集中区。

退出码：0=全部通过；1=存在失败（明细见输出）。
说明：本脚本不调用 AI、不联网，仅验证本地脚本链路与依赖（LibreOffice/openpyxl/python-docx）。
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
import sys
import json
import shutil
import argparse
import subprocess
import tempfile
import datetime
import time
import re

HERE = os.path.dirname(os.path.abspath(__file__))
# 冒烟结果台账（运行侧生成物，不随开发侧留存；供 check.py 校验文档所写项数是否为真）
SMOKE_LEDGER = os.path.join(os.path.dirname(HERE), "core", "_smoke-baseline.json")
sys.path.insert(0, HERE)

PY = sys.executable
FAILS = []
PASSES = []
SKIPS = []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  —— {detail}" if detail else ""))
    return ok


def skip(name, why=""):
    """可选依赖缺失时跳过：不计入失败，避免在未装 Poppler/Tesseract 的机器上必然红灯。"""
    SKIPS.append(name)
    print(f"  [SKIP] {name}" + (f"  —— {why}" if why else ""))


SAMPLE = """# 测试用采购合同（冒烟测试样例）

甲方：某某科技有限公司
乙方：某某供应链有限公司

第一条 标的：甲方向乙方采购服务器 10 台，型号 X200，单价人民币 10000.00 元。
第二条 付款：合同签订后甲方支付全部货款。法定代表人：张三 电话 13800138000。
第三条 交付：乙方应尽快交货，甲方及时验收。
第四条 争议解决：协商不成的，向原告方所在地人民法院起诉。
第五条 本合同一式两份，双方各执一份。
"""


def build_spec(path):
    spec = {
        "name": "冒烟测试采购合同",
        "source": "冒烟测试合同",
        "report_title": "文档合规审查意见报告——冒烟测试采购合同",
        "reviewer": "SMOKE-TEST",
        "round": "1",
        "original_text": SAMPLE,
        "compare": {
            "a_label": "旧版",
            "b_label": "新版",
            "a_text": "第一条 标的：采购服务器 10 台。\n第二条 付款：签订后支付全部货款。\n第三条 交付：尽快交货。\n",
            "b_text": "第一条 标的：采购服务器 12 台。\n第二条 付款：签订后支付 30% 预付款，余款验收合格后 30 日内付清。\n"
                      "第三条 交付：收到订单后 15 个工作日内交货。\n第四条 争议解决：向被告所在地有管辖权的人民法院起诉。\n",
        },
        "clauses": [
            {
                "heading": "第二条 付款——预付全款且泄露个人信息",
                "original": "合同签订后甲方支付全部货款。法定代表人：张三 电话 13800138000。",
                "revised": "甲方于合同签订后支付合同总价30%作为预付款，余款于验收合格并收到合规发票后30日内支付；本条款中个人信息应删除或取得单独同意。",
                "rating": "★★★ 高风险",
                "basis": "《民法典》第626条、第526条；《个人信息保护法》第13条",
                "comment": "发货前付清全款，丧失先验收后付款抗辩；合同文本直接载录自然人姓名与手机号，存在个人信息泄露风险。",
            },
            {
                "heading": "第三条 交付与验收——表述不可量化",
                "original": "乙方应尽快交货，甲方及时验收。",
                "revised": "乙方应于收到订单后15个工作日内交货；甲方应于收货后7个工作日内完成验收，逾期未提出异议的视为验收合格。",
                "rating": "★★ 中风险",
                "basis": "《民法典》第601条、第621条",
                "comment": "“尽快”“及时”不可量化、不可执行，交付与验收期限均无法主张。",
            },
            {
                "heading": "第四条 争议解决——管辖约定不确定",
                "original": "协商不成的，向原告方所在地人民法院起诉。",
                "revised": "协商不成的，向被告所在地有管辖权的人民法院提起诉讼。",
                "rating": "★★ 中风险",
                "basis": "《民事诉讼法》第35条",
                "comment": "“原告方所在地”起诉前不确定，存在被认定约定不明、回归法定管辖的风险。",
            },
        ],
        # 第 10 类「模板版」：转模板 / 撰写模板 两条链路共用（缺字段时退化为条款骨架，故这里给全）
        "template": {
            "name": "设备采购合同模板（冒烟样例）",
            "placeholders": [
                {"name": "{{甲方全称}}", "meaning": "采购方主体全称", "example": "某某科技有限公司", "required": True},
                {"name": "{{合同金额}}", "meaning": "含税总价（大小写一致）", "example": "人民币壹佰万元整（¥1,000,000.00）", "required": True},
                {"name": "{{交付期限}}", "meaning": "收到订单后的交货天数", "example": "15 个工作日", "required": False},
            ],
            "body": "第一条 标的：{{甲方全称}}向乙方采购{{设备名称}} {{数量}}台。\n"
                    "第二条 价款：合同总价{{合同金额}}，含增值税专用发票。\n"
                    "第三条 交付：乙方应于收到订单后{{交付期限}}内交货。\n"
                    "第四条 争议解决：协商不成的，向被告所在地有管辖权的人民法院提起诉讼。",
            "optional": [
                {"name": "竞业限制", "scene": "涉及核心技术或渠道的交易", "advice": "我方强势时可加，弱势时不必争取"},
                {"name": "审计权", "scene": "对方掌握成本/用量数据的长期合作", "advice": "建议保留，但限定频次与提前通知期"},
            ],
            "notes": "1. 占位符填实后即为具体合同，须经执业律师复核。\n2. 每次使用前核对主体全称、金额大小写与管辖。",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    return path


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout)


def head_lines(text, budget=200, max_lines=3):
    """按「整行」截断子进程输出，用来做检查项详情。

    为什么不直接 text[:90]：冒烟日志是给人看的证据，按字符硬切会把一行从中间
    切断（实例侧路径比开发侧长，同一个检查项在两侧切出来的残句还不一样，看日志
    的人会误以为字段值本身就是残缺的）。这里改为整行取舍：放得下的行完整保留，
    放不下就停下并标省略号——宁可少一行，不出残句。
    """
    out = []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line:
            continue
        if len(out) >= max_lines or sum(len(x) for x in out) + len(line) > budget:
            out.append("…")
            break
        out.append(line)
    return " / ".join(out)


def tail_line(text, budget=90):
    """取最后一条非空行做详情（用于「最后一行才是结论」的输出）。整行不动，超长才切头。"""
    lines = [l.rstrip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return ""
    last = lines[-1]
    return last if len(last) <= budget else "…" + last[-(budget - 1):]


def main():
    ap = argparse.ArgumentParser(description="文档合规审查助手AI合同审核全能版·端到端冒烟测试")
    ap.add_argument("--base", default=None, help="工作根目录（默认取 config.json 的 base_dir）")
    ap.add_argument("--keep", action="store_true", help="保留测试产物")
    ap.add_argument("--in-base", action="store_true",
                    help="把测试产物写入 <base>/输出（默认写入系统临时目录，避免污染正式输出区）")
    ap.add_argument("--full", action="store_true",
                    help="全量档：含 PDF 导出与 OCR（默认快速档，跳过这些耗时项）")
    ap.add_argument("--fast", action="store_true",
                    help="（兼容旧用法）快速档；已设为默认，可省略")
    a = ap.parse_args()
    # 默认即快速档（日常省资源），--full 才是全量；--fast 保留以便旧脚本/文档不失效
    a.fast = not a.full

    try:
        import _config as _cfgmod
        cfg = _cfgmod.load()
        base = a.base or _cfgmod.workdir(cfg, "base_dir")
        tools = {k: _cfgmod.tool_available(cfg, k) for k in ("soffice", "pdftotext", "pdftoppm", "tesseract")}
    except Exception as e:
        cfg, base, tools = {}, os.path.join(os.getcwd(), "文档合规审查报告"), {}
        print("[smoke] 配置加载异常，使用默认目录：", e)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    # 默认写入系统临时目录：测试产物不得混入 base/输出（客户文档集中区）。
    if a.in_base:
        work = os.path.join(base, "输出", f"_smoke-{ts}")
    else:
        work = os.path.join(tempfile.gettempdir(), "dcr-smoke", f"_smoke-{ts}")
    os.makedirs(work, exist_ok=True)
    print("=" * 62)
    print("文档合规审查助手AI合同审核全能版 · 端到端冒烟测试")
    print("模式：", "快速档（PDF/OCR/老格式转换 记为 SKIP，项数不变）；跑全量档请加 --full"
          if a.fast else "全量档（含 PDF 导出与 OCR）")
    print("工作目录：", work)
    print("=" * 62)

    # --- 0. 依赖自检 ---
    print("\n[0] 依赖自检")
    for m in ("docx", "openpyxl"):
        try:
            __import__(m)
            check(f"Python 依赖 {m}", True)
        except Exception as e:
            check(f"Python 依赖 {m}", False, str(e))
    for k, ok in tools.items():
        if k == "soffice":
            check("外部依赖 LibreOffice（必需：doc 转换 / PDF 导出）", ok, "缺失时 doc 类文件无法预处理")
        else:
            check(f"外部依赖 {k}（可选）", ok, "缺失仅影响 PDF/扫描件功能")

    # --- 1. 预处理链路 ---
    print("\n[1] 预处理链路（提取→清洗→留痕）")
    src = os.path.join(work, "冒烟测试合同.md")
    with open(src, "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    pp = run([PY, os.path.join(HERE, "preprocess.py"), src, "--base", base, "--out", os.path.join(work, "预处理")])
    check("preprocess.py 执行", pp.returncode == 0, (pp.stderr or "")[-160:] if pp.returncode else "")
    pre_out = os.path.join(work, "预处理", "冒烟测试合同")
    clean = os.path.join(pre_out, "text", "冒烟测试合同.clean.txt")
    check("生成清洗文本 text/*.clean.txt", os.path.exists(clean))
    if os.path.exists(clean):
        txt = open(clean, encoding="utf-8").read()
        check("清洗文本非空且含关键内容", len(txt) > 100 and "服务器" in txt, f"{len(txt)} 字符")
    check("生成元数据 meta/*.json（含 sha256/异常标记）",
          os.path.exists(os.path.join(pre_out, "meta", "冒烟测试合同.json")))
    check("原始文件留痕 raw/", os.path.exists(os.path.join(pre_out, "raw", "冒烟测试合同.md")))

    # --- 1.5 真实文件链路（随包自检样本：Word 含敏感信息 / 扫描型 PDF / 图片合同）---
    print("\n[1.5] 真实文件链路（samples/ 下自检样本）")
    sdir = os.path.join(os.path.dirname(HERE), "samples")
    ocr_ok = bool(tools.get("pdftoppm")) and bool(tools.get("tesseract"))
    cases = [
        ("敏感信息示例.docx", "Word 含敏感信息", ["智元科技", "12,800.00"], False, False),
        ("扫描件示例.pdf", "扫描型 PDF（无文字层）", ["设备维护服务合同", "违约金"], True, False),
        ("图片合同示例.jpg", "图片格式合同", ["采购合同", "质保"], True, False),
        ("合同比对A版.docx", "合同 A 版（docx）", ["软件开发服务合同", "贰拾捌万元"], False, False),
        ("合同比对B版.doc", "合同 B 版（.doc 老格式）", ["软件开发服务合同", "叁拾贰万元"], False, True),
    ]
    sample_out = os.path.join(work, "样本预处理")
    if not any(os.path.exists(os.path.join(sdir, c[0])) for c in cases):
        # 自检样本缺失时（如使用者只保留提示词版）：逐项 SKIP 而非 FAIL，总项数保持一致（便于对齐报告）
        for fn, label, kws, need_ocr, need_soffice in cases:
            skip(f"样本存在：{label}", "未找到 samples/ 下的自检样本（已被移除）")
            skip(f"{label} 预处理执行", "无样本目录")
            skip(f"{label} 取出可审文本", "无样本目录")
            skip(f"{label} 内容可识别（关键词命中）", "无样本目录")
    else:
        for fn, label, kws, need_ocr, need_soffice in cases:
            p = os.path.join(sdir, fn)
            if not check(f"样本存在：{label}", os.path.exists(p), "" if os.path.exists(p) else fn):
                continue
            tip = "（需 Poppler + Tesseract）" if need_ocr else "（需 LibreOffice 转换 .doc）"
            if a.fast and need_ocr:   # 只跳 OCR（耗时大头）；.doc 转换保留，以保住 A/B 比对链路
                for sub in ("提取并可审" + tip, "取出可审文本", "内容可识别（关键词命中）"):
                    skip(f"{label} {sub}", "快速档已跳过（耗时项；跑全量档加 --full）")
                continue
            if need_ocr and not ocr_ok:
                skip(f"{label} 提取并可审（需 Poppler + Tesseract）", "可选依赖缺失，补齐后重跑")
                continue
            if need_soffice and not tools.get("soffice"):
                skip(f"{label} 提取并可审（需 LibreOffice 转换 .doc）", "依赖缺失，补齐后重跑")
                continue
            r = run([PY, os.path.join(HERE, "preprocess.py"), p, "--out", sample_out])
            if not check(f"{label} 预处理执行", r.returncode == 0,
                         (r.stderr or "")[-160:] if r.returncode else ""):
                continue
            base = os.path.splitext(fn)[0]
            cl = os.path.join(sample_out, base, "text", base + ".clean.txt")
            if not check(f"{label} 取出可审文本", os.path.exists(cl) and os.path.getsize(cl) > 60,
                         f"{os.path.getsize(cl)} 字节" if os.path.exists(cl) else "未生成 clean.txt"):
                continue
            t = open(cl, encoding="utf-8", errors="ignore").read()
            check(f"{label} 内容可识别（关键词命中）", any(k in t for k in kws), f"{len(t)} 字符")

    # --- 1.6 脱敏链路（对样本提取文本实跑，校验真实敏感信息被替换）---
    print("\n[1.6] 脱敏链路（敏感信息样本）")
    cl = os.path.join(sample_out, "敏感信息示例", "text", "敏感信息示例.clean.txt")
    if not os.path.exists(cl):
        for n in ("desensitize.py 执行（样本）", "样本脱敏：手机号已去除", "样本脱敏：身份证号已去除"):
            skip(n, "无清洗文本（自检样本缺失，或前置提取失败）")
    else:
        dsout = os.path.join(work, "样本脱敏")
        os.makedirs(dsout, exist_ok=True)
        masked = os.path.join(dsout, "敏感信息示例.masked.txt")   # --out 是文件路径，不是目录
        r = run([PY, os.path.join(HERE, "desensitize.py"), "mask", cl,
                 "--out", masked, "--map", os.path.join(dsout, "map.json")])
        check("desensitize.py 执行（样本）", r.returncode == 0,
              (r.stderr or "")[-160:] if r.returncode else "")
        if os.path.exists(masked):
            mt = open(masked, encoding="utf-8", errors="ignore").read()
            check("样本脱敏：手机号已去除", "13800138000" not in mt)
            check("样本脱敏：身份证号已去除", "110101199001011234" not in mt)
        else:
            check("样本脱敏：产出脱敏文本", False, "未见输出文件")

    # --- 1.7 比对链路（A/B 两版样本 → 文件比对报告，兼验 .doc 老格式可比对）---
    print("\n[1.7] 比对链路（合同 A/B 两版样本）")
    ta = os.path.join(sample_out, "合同比对A版", "text", "合同比对A版.clean.txt")
    tb = os.path.join(sample_out, "合同比对B版", "text", "合同比对B版.clean.txt")
    if not (os.path.exists(ta) and os.path.exists(tb)):
        for n in ("make-docx.py 比对执行（样本 A/B）",
                  "比对报告：差异条数 ≥ 8",
                  "比对报告：命中实质改动（价款/仲裁/知识产权）"):
            skip(n, "无两份清洗文本（自检样本缺失，或前置提取失败）")
    else:
        cdir = os.path.join(work, "样本比对")
        os.makedirs(cdir, exist_ok=True)
        sp = os.path.join(cdir, "spec-ab.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump({"name": "软件开发服务合同", "source": "合同比对A版",
                       "report_title": "文档合规审查意见报告——软件开发服务合同",
                       "reviewer": "SMOKE-TEST", "round": "1",
                       "original_text": "样本比对测试用占位文本。", "clauses": []},
                      f, ensure_ascii=False, indent=2)
        cout = os.path.join(cdir, "out")
        r = run([PY, os.path.join(HERE, "make-docx.py"), sp,
                 "--reviewer", "SMOKE-TEST", "--types", "diff", "--formats", "md",
                 "--out", cout, "--cmp-a", ta, "--cmp-b", tb])
        check("make-docx.py 比对执行（样本 A/B）", r.returncode == 0,
              (r.stderr or "")[-160:] if r.returncode else "")
        mds = []
        if os.path.isdir(cout):
            mds = [x for x in os.listdir(cout) if x.lower().endswith(".md")]
        if not mds:
            check("比对报告：产出 markdown", False, "未见输出文件")
        else:
            body = open(os.path.join(cout, mds[0]), encoding="utf-8", errors="ignore").read()
            m = re.search(r"共\s*(\d+)\s*处差异", body)
            n = int(m.group(1)) if m else 0
            check("比对报告：差异条数 ≥ 8", n >= 8, f"检出 {n} 处")
            hits = [k for k in ("叁拾贰万元", "仲裁", "知识产权") if k in body]
            check("比对报告：命中实质改动（价款/仲裁/知识产权）", len(hits) == 3,
                  f"命中 {len(hits)}/3")

    # --- 1.8 降级通道（未装 LibreOffice 时的 python-docx 直读兜底）---
    print("\n[1.8] 降级通道（python-docx 直读 docx）")
    try:
        import preprocess as _pp
        nd = os.path.join(sdir, "合同比对A版.docx")
        if not os.path.exists(nd):
            skip("python-docx 直读 docx（降级通道可用）", "无 A 版样本（自检样本缺失）")
        else:
            native = _pp.extract_docx_native(nd)
            check("python-docx 直读 docx（降级通道可用）",
                  "软件开发服务合同" in native and "贰拾捌万元" in native,
                  f"{len(native)} 字符")
    except Exception as e:
        check("python-docx 直读 docx（降级通道可用）", False, repr(e))

    # --- 2. 交付物链路 ---
    print("\n[2] 交付物链路（10 类型 × docx/excel/html/pdf）")
    spec = build_spec(os.path.join(work, "spec.json"))
    outdir = os.path.join(work, "交付物")
    fmts = "docx,excel,html" if a.fast else "docx,excel,html,pdf"   # --fast 跳过 PDF 导出（耗时大头）
    mk = run([PY, os.path.join(HERE, "make-docx.py"), spec,
              "--reviewer", "SMOKE-TEST", "--ts", datetime.datetime.now().strftime("%Y%m%d-%H%M"),
              "--formats", fmts, "--comments", "--out", outdir,
              "--types", "tracked,reportc,clean,redline,report,masked,original,diff,compare,template"])
    check("make-docx.py 执行", mk.returncode == 0, (mk.stdout or "")[-300:] if mk.returncode else "")
    produced = sorted(os.listdir(outdir)) if os.path.isdir(outdir) else []
    kinds = ["修订版", "红线修订格式版", "修改后清洁版", "审查意见报告",
             "原文脱敏版", "原文照录版", "文件比对报告", "新旧比对", "模板版"]
    for k in kinds:
        check(f"产出 {k}.docx", any(k in f and f.endswith(".docx") and "批注版" not in f for f in produced))
    check("产出 审查意见批注版.docx（类型 2，--comments 兼容开关）",
          any("批注版" in f and f.endswith(".docx") for f in produced))
    check("产出 Excel（.xlsx）", any(f.endswith(".xlsx") for f in produced))
    check("产出 HTML（.html，10 类全覆盖）",
          sum(1 for f in produced if f.endswith(".html")) >= 10)
    hp = next((os.path.join(outdir, f) for f in produced
               if f.endswith(".html") and "审查意见报告" in f), None)
    ok_html = False
    if hp and os.path.isfile(hp):
        try:
            h = open(hp, encoding="utf-8").read()
            # 单文件自检：目录导航 + 三色风险标签 + 打印按钮 + 零外部资源
            ok_html = ('<nav class="toc">' in h and 'class="risk r' in h
                       and 'id="btn-print"' in h
                       and 'src="http' not in h and 'href="http' not in h)
        except Exception:
            ok_html = False
    check("HTML 单文件自检（目录/三色标签/打印按钮/零外链）", ok_html)
    if a.fast:
        skip("产出 PDF（.pdf，依赖 LibreOffice）", "快速档已跳过（跑全量档加 --full）")
    else:
        check("产出 PDF（.pdf，依赖 LibreOffice）", any(f.endswith(".pdf") for f in produced))

    # --- 3. 内容自检 ---
    print("\n[3] 产出内容自检")
    try:
        import docx
        d = docx.Document(os.path.join(outdir, [f for f in produced if "审查意见报告" in f and "批注" not in f and f.endswith(".docx")][0]))
        body = "\n".join(p.text for p in d.paragraphs)
        check("报告含免责声明（报告段＋使用段全文）",
              "免责声明" in body and "现行有效" in body
              and "执业律师复核" in body and "商业使用须获作者书面授权" in body)
        check("报告含风险描述与法条", "风险描述" in body and "法律依据" in body)
    except Exception as e:
        check("报告内容自检", False, str(e))
    try:
        import zipfile
        p = os.path.join(outdir, [f for f in produced if "批注版" in f and f.endswith(".docx")][0])
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/comments.xml").decode("utf-8", "ignore") if "word/comments.xml" in z.namelist() else ""
        check("批注版含 Word 批注（comments.xml）", xml.count("<w:comment ") >= 3, f"{xml.count('<w:comment ')} 条")
    except Exception as e:
        check("批注版内容自检", False, str(e))
    try:
        import openpyxl
        xf = os.path.join(outdir, [f for f in produced if f.endswith(".xlsx")][0])
        ws = openpyxl.load_workbook(xf).active
        check("Excel 含数据行", ws.max_row >= 3, f"{ws.max_row} 行")
    except Exception as e:
        check("Excel 内容自检", False, str(e))
    try:
        import docx as _dx2
        df = os.path.join(outdir, [f for f in produced if "文件比对报告" in f and f.endswith(".docx")][0])
        dd = _dx2.Document(df)
        dtext = "\n".join(p.text for p in dd.paragraphs) + "\n" + \
                "\n".join(c.text for t in dd.tables for r in t.rows for c in r.cells)
        check("文件比对报告含差异台账（变更类型 + 新增/修改行）",
              "变更类型" in dtext and ("新增" in dtext or "修改" in dtext))
    except Exception as e:
        check("文件比对报告内容自检", False, str(e))
    try:
        import docx as _dx
        mf = os.path.join(outdir, [f for f in produced if "原文脱敏版" in f and f.endswith(".docx")][0])
        mt = "\n".join(p.text for p in _dx.Document(mf).paragraphs)
        check("原文脱敏版已脱敏（手机号/姓名占位）", "13800138000" not in mt, "手机号已替换为占位符")
    except Exception as e:
        check("脱敏版内容自检", False, str(e))
    try:
        import docx as _dx3
        tf = os.path.join(outdir, [f for f in produced if "模板版" in f and f.endswith(".docx")][0])
        tt = "\n".join(p.text for p in _dx3.Document(tf).paragraphs)
        check("模板版含占位符说明表与占位符",
              "占位符说明表" in tt and "{{甲方全称}}" in tt and "模板正文" in tt)
        check("模板版含可选条款区与使用须知", "可选条款区" in tt and "使用须知" in tt)
        import zipfile as _zf3
        with _zf3.ZipFile(tf) as _z3:
            _c3 = (_z3.read("word/comments.xml").decode("utf-8")
                   if "word/comments.xml" in _z3.namelist() else "")
        check("模板版：标题说明批注 ＋ 可选条款批注（≥2 条）",
              _c3.count("<w:comment ") >= 2, "%d 条" % _c3.count("<w:comment "))
    except Exception as e:
        check("模板版内容自检", False, str(e))
    # --- 3.x 排版保真（B 档：样式档位 ＋ 段落角色推断，只对 1、3、4、6、7 生效） ---
    try:
        import docx as _dxf
        from docx.enum.text import WD_ALIGN_PARAGRAPH as _AL
        cf = os.path.join(outdir, [f for f in produced if "修改后清洁版" in f and f.endswith(".docx")][0])
        ps = _dxf.Document(cf).paragraphs
        check("排版档位：清洁版文档标题居中", bool(ps) and ps[0].alignment == _AL.CENTER,
              (ps[0].text[:16] if ps else "无段落"))
        indented = [p for p in ps[2:] if p.text.strip() and p.paragraph_format.first_line_indent]
        check("排版档位：正文首行缩进 2 字符",
              any(p.paragraph_format.first_line_indent.pt >= 20 for p in indented),
              "%d 段已缩进" % len(indented))
        check("排版档位：行距 1.5 与段前距已套用",
              any(p.paragraph_format.line_spacing == 1.5 for p in ps)
              and any(p.paragraph_format.space_before for p in ps))
        rf = os.path.join(outdir, [f for f in produced if "审查意见报告" in f and "批注" not in f and f.endswith(".docx")][0])
        rps = _dxf.Document(rf).paragraphs
        check("排版档位：报告类不套样式档位（正文不缩进 / 行距未改，2、5、8、9、10）",
              bool(rps) and not any(p.paragraph_format.first_line_indent for p in rps)
              and not any(p.paragraph_format.line_spacing for p in rps))
        # 报告型五类标题居中：报告类不套样式档位，但标题对齐属报告固有版式（Title 样式默认左对齐，须显式居中）
        for _rp in ("审查意见批注版", "审查意见报告", "新旧比对", "文件比对报告", "模板版"):
            _cand = [f for f in produced if _rp in f and f.endswith(".docx")]
            if _rp == "审查意见报告":
                _cand = [f for f in _cand if "批注" not in f]
            if not _cand:
                check("报告型标题居中：%s" % _rp, False, "未见输出文件")
                continue
            _pp = _dxf.Document(os.path.join(outdir, _cand[0])).paragraphs
            check("报告型标题居中：%s" % _rp,
                  bool(_pp) and _pp[0].alignment == _AL.CENTER,
                  (_pp[0].text[:18] if _pp else "无段落"))
    except Exception as e:
        check("排版档位自检", False, str(e))

    # --- 3.z 交付物呈现口径（文档型不人为增加抬头；元数据进文档属性；3/6/7 零批注） ---
    print("\n[3.z] 交付物呈现口径（去抬头 · 文档属性 · 零批注 · 修订粒度）")
    _DOC_KINDS = {"修订版": "tracked", "修改后清洁版": "clean", "红线修订格式版": "redline",
                  "原文脱敏版": "masked", "原文照录版": "original"}
    _HEADER_MARKS = ["（修订模式）", "（红线格式）", "（清洁版）", "（原文脱敏版）", "（原文照录版）"]
    _ZERO_COMMENT = ["修改后清洁版", "原文脱敏版", "原文照录版"]
    try:
        import zipfile as _zf
        for _zh in _DOC_KINDS:
            _f = [x for x in produced if _zh in x and "批注版" not in x and x.endswith(".docx")][0]
            with _zf.ZipFile(os.path.join(outdir, _f)) as _z:
                _xml = _z.read("word/document.xml").decode("utf-8")
                _core = _z.read("docProps/core.xml").decode("utf-8") if "docProps/core.xml" in _z.namelist() else ""
                _nc = (len(re.findall(r"<w:comment ", _z.read("word/comments.xml").decode("utf-8")))
                       if "word/comments.xml" in _z.namelist() else 0)
            _bad = [h for h in _HEADER_MARKS if h in _xml]
            check(f"文档型不人为增加抬头：{_zh}", not _bad,
                  "残留 " + "/".join(_bad) if _bad else "标题即原文标题、正文无说明段")
            check(f"类型/审查人/轮次已写入文档属性：{_zh}",
                  "cp:category" in _core and "SMOKE-TEST" in _core and "r1" in _core, _core[:0] or "core.xml")
            if _zh in _ZERO_COMMENT:
                check(f"对外/原文类零批注：{_zh}", _nc == 0, "%d 条批注（应为 0）" % _nc)
    except Exception as e:
        check("交付物呈现口径自检", False, str(e))
    try:
        import zipfile as _zf2
        _tf = [x for x in produced if "修订版" in x and "批注版" not in x and x.endswith(".docx")][0]
        with _zf2.ZipFile(os.path.join(outdir, _tf)) as _z2:
            _dx2x = _z2.read("word/document.xml").decode("utf-8")
        _segs = re.findall(r"<w:(?:ins|del) [^>]*>(.*?)</w:(?:ins|del)>", _dx2x, re.S)
        _lens = [len("".join(re.findall(r"<w:(?:t|delText)[^>]*>(.*?)</w:(?:t|delText)>", s, re.S)))
                 for s in _segs]
        check("修订粒度：存在局部改动片段（非整段替换）",
              bool(_lens) and min(_lens) <= 10, "%d 处痕迹，最短 %s 字" % (len(_lens), min(_lens) if _lens else "-"))
    except Exception as e:
        check("修订粒度自检", False, str(e))

    # --- 3.y 半档 C（--source-docx：3、6、7 以原稿做底，版式沿用原稿） ---
    print("\n[3.y] 半档C 排版保真（--source-docx）")
    try:
        import docx as _dxc
        sd = os.path.join(sdir, "合同比对A版.docx")
        if not os.path.exists(sd):
            for n in ("半档C：make-docx 执行（--source-docx）",
                      "半档C：以原稿做底（段落数与原稿一致）",
                      "半档C：页边距沿用原稿"):
                skip(n, "无 A 版样本（自检样本缺失）")
        else:
            cout2 = os.path.join(work, "半档C")
            rc = run([PY, os.path.join(HERE, "make-docx.py"), spec,
                      "--reviewer", "SMOKE-TEST", "--types", "clean",
                      "--source-docx", sd, "--out", cout2])
            check("半档C：make-docx 执行（--source-docx）", rc.returncode == 0,
                  (rc.stderr or "")[-160:] if rc.returncode else "")
            fs = [f for f in os.listdir(cout2) if f.endswith(".docx")] if os.path.isdir(cout2) else []
            if not fs:
                check("半档C：产出清洁版", False, "未见输出文件")
            else:
                od = _dxc.Document(os.path.join(cout2, fs[0]))
                sd0 = _dxc.Document(sd)
                check("半档C：以原稿做底（段落数与原稿一致）",
                      len(od.paragraphs) == len(sd0.paragraphs),
                      "%d 段 vs 原稿 %d 段" % (len(od.paragraphs), len(sd0.paragraphs)))
                check("半档C：页边距沿用原稿（版式未重建）",
                      od.sections[0].left_margin == sd0.sections[0].left_margin,
                      str(od.sections[0].left_margin))
    except Exception as e:
        check("半档C 自检", False, str(e))

    # --- 3.5 版本与依赖（分发与落地成本）---
    print("\n[3.5] 版本与依赖")
    try:
        v = run([PY, os.path.join(HERE, "version.py")])
        check("version.py 版本身份证（含版本号与规模）",
              v.returncode == 0 and "v3." in (v.stdout or ""), head_lines(v.stdout))
        me = os.path.dirname(HERE)          # 与自身比对：应判「已是最新版」
        c = run([PY, os.path.join(HERE, "version.py"), "--check", me])
        check("version.py --check 自身（应判已是最新）",
              c.returncode == 0 and "已是最新版" in (c.stdout or ""), head_lines(c.stdout))
        g = run([PY, os.path.join(HERE, "detect-tools.py"), "--install-guide"])
        check("detect-tools.py --install-guide 可执行（只给命令、不代装）",
              g.returncode == 0, tail_line(g.stdout))
    except Exception as e:
        check("版本与依赖自检", False, repr(e))

    # --- 4. 汇总 ---
    print("\n" + "=" * 62)
    print(f"结果：通过 {len(PASSES)} 项，失败 {len(FAILS)} 项，跳过 {len(SKIPS)} 项")
    # 记账：把本次真实项数落盘，供 check.py 校验「文档里写的项数」是否属实。
    # 两档项数守恒（全量把 OCR 两步拆开，快档合并为一步，总数一致），故只记 total。
    try:
        with open(SMOKE_LEDGER, "w", encoding="utf-8") as f:
            json.dump({"_说明": "冒烟结果台账（smoke-test.py 自动生成，运行侧生成物不随开发侧留存）；"
                               "供 check.py 校验 README/教程所写项数是否为真。",
                       "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "mode": "fast" if a.fast else "full",
                       "total": len(PASSES) + len(FAILS) + len(SKIPS),
                       "passed": len(PASSES), "failed": len(FAILS), "skipped": len(SKIPS)},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("提示：冒烟台账写入失败（不影响本次结果）：", repr(e))
    if SKIPS:
        print("跳过项（可选依赖缺失，不计入失败）：")
        for s in SKIPS:
            print("  -", s)
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  -", f)
    else:
        print("全部通过：预处理/交付物/内容自检链路可用。")
    print("=" * 62)
    if not a.keep:
        # LibreOffice 转换 PDF 后可能短暂占用文件，直接 rmtree 会被静默忽略而留下残渣；
        # 故改为重试清理，并在确实清不掉时显式提示（不再静默）。
        for _ in range(4):
            shutil.rmtree(work, ignore_errors=True)
            if not os.path.exists(work):
                break
            time.sleep(1.5)
        if os.path.exists(work):
            tip = ("（位于 base/输出，属客户文档集中区，请尽快手动删除）"
                   if a.in_base else "（位于系统临时目录，不影响正式输出区）")
            print("提示：测试产物未能完全清理（可能仍被 LibreOffice 占用），请稍后手动删除：", work, tip)
        else:
            print("已清理测试产物（--keep 可保留）。")
    else:
        print("测试产物已保留：", work)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
