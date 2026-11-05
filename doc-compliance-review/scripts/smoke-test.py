#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E3  门禁自检类：文件内出现网络关键字，但自身不发起联网
"""
文档合规审查助手AI合同 · 端到端冒烟测试（smoke-test）
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
import hashlib

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
        # 版本留痕行（ver/date/变更）是模板版出件的硬要求：没有它就无法反查用的是哪版模板。
        "template": {
            "name": "设备采购合同模板（冒烟样例）",
            "placeholders": [
                {"name": "{{甲方全称}}", "meaning": "采购方主体全称", "example": "某某科技有限公司", "required": True},
                {"name": "{{设备名称}}", "meaning": "设备规格型号", "example": "XX-2000 型", "required": True},
                {"name": "{{数量}}", "meaning": "采购数量", "example": "10", "required": True},
                {"name": "{{合同金额}}", "meaning": "含税总价（大小写一致）", "example": "人民币壹佰万元整（¥1,000,000.00）", "required": True},
                {"name": "{{交付期限}}", "meaning": "收到订单后的交货天数", "example": "15 个工作日", "required": False},
            ],
            "values": {"甲方全称": "某某科技有限公司", "设备名称": "XX-2000 型", "数量": "10",
                       "合同金额": "人民币壹佰万元整（¥1,000,000.00）"},
            "body": "<!-- tpl: 设备采购合同模板 | ver: 1.0.0 | date: 2026-01-01 | 变更: 冒烟样例初版 -->\n"
                    "第一条 标的：{{甲方全称}}向乙方采购{{设备名称}} {{数量}}台。\n"
                    "第二条 价款：合同总价{{合同金额}}，含增值税专用发票。\n"
                    "第三条 交付：乙方应于收到订单后{{交付期限}}内交货。\n"
                    "{{#有第三方担保}}\n第五条 丙方为乙方履约提供连带责任保证。\n{{/有第三方担保}}\n"
                    "第四条 争议解决：协商不成的，向被告所在地有管辖权的人民法院提起诉讼。",
            "switches": {"有第三方担保": False},
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


def make_src_docx(path, text):
    """由纯文本（SAMPLE）生成一个 .docx 原稿，每行一段，供 --source-docx 联调原稿级修订。

    选用 SAMPLE 是因为 spec 里各条款的 original 文本本就是 SAMPLE 的子串，
    能稳定落到原稿段落、产出真正的 Word 原生修订（w:ins/w:del），而非降级。
    """
    import docx as _dx
    d = _dx.Document()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        d.add_paragraph(line)
    d.save(path)
    return path


def run(cmd, timeout=600):
    # errors="replace"（**不是 ignore**）：被 spawn 的脚本都已自钉 stdout 为 UTF-8，正常不会有
    # 非法字节；万一真有（子脚本崩在写一半、第三方工具吐 GBK），**ignore 会把字符静默吞掉**，
    # 断言表现为"匹配不上"，而输出里连替换符都没有，`_garbled_hint` 之类的编码诊断也就无从触发
    # ——正好落回 12.5.9 说的"报错指错方向"（会被当成判据被删／脚本崩了）。replace 让字节显形。
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


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


# 反向注入用的跑法：**不跑整个 check.py**，只在本进程里导入副本的 check 模块、
# 直接调那一个门禁函数，再把 err()/warn() 收到的文本取出来。
# 为什么不做 `python check.py` 整个跑：check.py 有 30 多个检查，前 20 多个都要读
# 技能根的文件（SKILL.md / rules/ …），临时副本里没有，会先抛 FileNotFoundError——
# 退出码同样是 1，但报错跟被注入的门禁毫无关系，就成了「退出码对、理由错」的假过。
# 当天已经踩过一次这个坑，故这里把注入点与门禁一一对应，判据只认该门禁的专属措辞。
_INJECT_RUNNER = r'''
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("dcr_check_probe", sys.argv[1])
m = importlib.util.module_from_spec(spec)
sys.modules["dcr_check_probe"] = m
spec.loader.exec_module(m)
which = sys.argv[2]
# 第三个参数是 config 路径；不给就读副本自带的 config.json。
# （早先漏了这一步，argv[3] 越界 → 崩溃信息与门禁无关，差点又变成"退出码对、理由错"）
cfgp = sys.argv[3] if len(sys.argv) > 3 else None
try:
    if which == "online":
        data = {}
        if cfgp:
            with open(cfgp, encoding="utf-8") as f:
                data = json.load(f)
        m._check_online_gate(data)
    elif which == "net_tiers":
        m.check_net_tiers()
    elif which == "sec_matrix":
        m.check_security_matrix()
    elif which == "fmt_default":
        m._check_format_default()
    elif which == "fmt_matrix":
        m.check_format_matrix()
    elif which == "html_online":
        m.check_html_online_guard()
    elif which == "mm_source":
        m.check_mindmap_single_source()
    elif which == "ai_tells":
        m.check_ai_tells_rules()
    else:
        m._check_no_bytecode()
except BaseException as e:
    import traceback
    print(json.dumps({"crash": repr(e), "tb": traceback.format_exc()}, ensure_ascii=False))
    sys.exit(0)
print(json.dumps({"errs": m.ERRS, "warns": m.WARNS}, ensure_ascii=False))
'''


def _inject_gate_tests(tmp):
    """反向注入：把门禁故意改坏，断言门禁**必须报错**（铁律 25.5.3）。

    为什么非要这一组：正向用例只能说"现在的代码是对的"，说不了"以后改坏了会被拦住"。
    不可测的承诺等于没有承诺——这正是 SECURITY.md 那次事故的根源（句子写了、没人验）。

    做法：临时目录造一个假技能目录（只拷 `scripts/`），逐项改坏后**只调对应门禁函数**，
    断言它报出了该门禁的专属措辞。不入技能目录、不改正式文件，跑完即删。
    返回 [(用例名, 是否通过, 说明)]。
    """
    out = []
    real_scripts = HERE
    base = os.path.join(tmp, "skillsim")
    tgt = os.path.join(base, "scripts")
    try:
        # 不排除 .integrity.json：安全机制登记表要验指纹基线覆盖度，
        # 副本里缺了它，门禁报的是"缺基线"而不是被注入的那一处——误报会掩盖真信号。
        shutil.copytree(real_scripts, tgt,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # 带上 SECURITY.md：安全引擎门禁要拿文档名单与代码自标比对，
        # 副本里缺了它，门禁会报"文档缺名单"而不是被注入的那一处——误报会掩盖真信号。
        shutil.copy(os.path.join(os.path.dirname(HERE), "SECURITY.md"), base)
        # v3.32.0：带上 core/ 的去AI味两件（json 真源＋md 人读版）——
        # ai_tells 门禁要在副本里读它们；缺了会报"文件不存在"而非注入点。
        _core_dst = os.path.join(base, "core")
        os.makedirs(_core_dst, exist_ok=True)
        for _f in ("ai-tells.json", "03-ai-tells.md"):
            _src_f = os.path.join(os.path.dirname(HERE), "core", _f)
            if os.path.exists(_src_f):
                shutil.copy(_src_f, _core_dst)
    except Exception as e:
        return [("反向注入：准备临时副本", False, repr(e))]

    runner = os.path.join(tmp, "_inject_runner.py")
    with open(runner, "w", encoding="utf-8") as f:
        f.write(_INJECT_RUNNER)

    def run_gate(which, cfgp=None):
        """跑单个门禁，返回 (是否崩溃说明, errs, warns)。崩溃时 errs=[崩溃说明]。"""
        cmd = [PY, runner, os.path.join(tgt, "check.py"), which]
        if cfgp:
            cmd.append(cfgp)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"   # 别让探针自己往副本里扔 .pyc
        # Windows 下 text=True 默认按 locale（GBK）解码子进程的 UTF-8 输出，
        # JSON 最后一行直接乱码 → 「门禁无输出」，且 8 项用例全灭。
        # 两端锁死 UTF-8：这里按 UTF-8 解码，子进程端用 PYTHONIOENCODING 强制。
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env=env)
        txt = (r.stdout or "").strip()
        try:
            d = json.loads(txt.splitlines()[-1]) if txt else {}
        except Exception:
            d = {}
        if "crash" in d:
            # 崩溃也算失败：门禁没跑完，结论不可信。把最后一行 traceback 带进详情，便于定位。
            tb = [l for l in (d.get("tb") or "").splitlines() if l.strip()]
            return "门禁执行崩溃（%s）｜%s" % (d["crash"], tb[-1] if tb else ""), [], []
        if not d:
            # errs 必须带上说明：正向用例（断言 errs 为空）若看到 [] 会把
            # 「门禁没跑成」误判为「通过」——假绿比失败更糟。
            msg = "门禁无输出（退出码 %s）：%s" % (r.returncode, tail_line(r.stderr or r.stdout))
            return msg, [msg], []
        return "", d.get("errs") or [], d.get("warns") or []

    def rewrite(fn, old, new):
        fp = os.path.join(tgt, fn)
        t = open(fp, encoding="utf-8").read()
        if old not in t:
            return False
        open(fp, "w", encoding="utf-8").write(t.replace(old, new, 1))
        return True

    # ① 安全引擎门禁：给一个接触文档的 E0 脚本偷塞联网调用 → ERR 里必须点名"E0 档"
    #    注：注入点故意用 `import sys as _sys`（每个脚本都有的一行），不挑业务 import，
    #    否则换个脚本就"注入点未命中"——那种失败是测试自己脆，不是门禁失效。
    ok_hit = rewrite("preprocess.py", "import sys as _sys",
                     "import sys as _sys\nimport urllib.request")
    if ok_hit:
        bad, errs, _ = run_gate("net_tiers")
        hit = any("E0 档" in m and "preprocess.py" in m for m in errs)
        out.append(("反向注入①：E0 档脚本偷加 urllib → 安全引擎门禁必须拦下",
                    hit,
                    "已报 E0 越界" if hit else ("未报；" + (bad or "errs=%s" % errs))))
        rewrite("preprocess.py", "import sys as _sys\nimport urllib.request",
                "import sys as _sys")
    else:
        out.append(("反向注入①：处理脚本偷加 urllib → 联网门禁必须拦下",
                    False, "注入点未命中（preprocess.py 里找不到 `import sys as _sys`）"))

    # ② 缓存门禁：删掉某脚本的字节码开关 → ERR 里必须点名"未在文件头关闭字节码写入"
    ok_hit = rewrite("verify.py",
                     "import sys as _sys\n_sys.dont_write_bytecode = True",
                     "import sys as _sys")
    if ok_hit:
        bad, errs, _ = run_gate("bytecode")
        hit = any("关闭字节码写入" in m and "verify.py" in m for m in errs)
        out.append(("反向注入②：删掉 verify.py 的字节码开关 → 缓存门禁必须拦下",
                    hit,
                    "已报漏写" if hit else ("未报漏写；" + (bad or "errs=%s" % errs))))
        # 还原（否则后面 ④ 对照组会把这条注入当成"副本未改坏"来判，误报）
        rewrite("verify.py", "import sys as _sys",
                "import sys as _sys\n_sys.dont_write_bytecode = True")
    else:
        out.append(("反向注入②：删掉 verify.py 的字节码开关 → 缓存门禁必须拦下",
                    False, "注入点未命中（verify.py 里找不到标准开关写法）"))

    # ③ 联网开关门禁：把出厂默认改成 true → WARN 里必须提示"设为 true"
    cfgp = os.path.join(tgt, "config.json")
    try:
        cfg = json.loads(open(cfgp, encoding="utf-8").read())
        cfg.setdefault("update", {})["check_online_by_default"] = True
        open(cfgp, "w", encoding="utf-8").write(
            json.dumps(cfg, ensure_ascii=False, indent=1))
        bad, errs, warns = run_gate("online", cfgp)
        hit = any("check_online_by_default 设为 true" in m for m in warns)
        out.append(("反向注入③：把联网开关改回 true → 必须告警（默认不发请求的承诺被打破）",
                    hit,
                    "已告警" if hit else ("未告警；" + (bad or "warns=%s" % warns))))
        # 立即还原：后面 ④ 对照组会跑安全机制登记表，M4 要读同一个 config.json，
        # 不还原就会报"默认会自己发请求"——那是本条注入的残留，不是新信号。
        cfg["update"]["check_online_by_default"] = False
        open(cfgp, "w", encoding="utf-8").write(
            json.dumps(cfg, ensure_ascii=False, indent=1))
    except Exception as e:
        out.append(("反向注入③：把联网开关改回 true → 必须告警", False, repr(e)))

    def rewrite_doc(old, new):
        """改副本根上的 SECURITY.md（安全机制门禁要拿它做文档咬合与完备性反查）。"""
        fp = os.path.join(base, "SECURITY.md")
        t = open(fp, encoding="utf-8").read()
        if old not in t:
            return False
        open(fp, "w", encoding="utf-8").write(t.replace(old, new, 1))
        return True

    def case(name, hit, hit_detail, miss_detail):
        out.append((name, hit, hit_detail if hit else miss_detail))

    # ⑤ 锚点型加固（v3.23.4 复盘实测①）：只验"函数还在"是不够的——
    #    把 check_security() 里私有库的判据行掏空，M7 必须红（旧写法照样全绿）。
    if rewrite("check.py", 'and re.search(r"PR-\d+", l)]', "and False]"):
        bad, errs, _ = run_gate("sec_matrix")
        hit = any("M7" in m and "判据行" in m for m in errs)
        case("反向注入⑤：掏空 check_security() 里的私有库判据行 → M7 必须红",
             hit, "已报 M7 判据行丢失", "未报；" + (bad or "errs=%s" % errs))
        rewrite("check.py", "and False]", 'and re.search(r"PR-\d+", l)]')
    else:
        out.append(("反向注入⑤：掏空私有库判据行 → M7 必须红", False, "注入点未命中"))

    def rewrite_doc_all(old, new):
        fp = os.path.join(base, "SECURITY.md")
        t = open(fp, encoding="utf-8").read()
        if old not in t:
            return False
        open(fp, "w", encoding="utf-8").write(t.replace(old, new))
        return True

    # ⑥ 文档咬合加固（复盘实测②）：整条承诺被弱化到文档里查不到 → M4 必须红。
    #    旧写法是单个关键词 `in` 全文：把「默认关」改成「可关」后，
    #    "默认"在别处仍出现 17 次，门禁照样全绿——拿"词在别处"冒充"承诺还在"。
    #    注意本条验的是**承诺整条消失**；只弱化其中一处（总述与分述并存）仍不会红，
    #    那是第 25 条的活儿——咬合防"文档没说"，不防"文档说弱了"，已在铁律 27.3.4 写明。
    if rewrite_doc_all("默认关", "可关"):
        bad, errs, _ = run_gate("sec_matrix")
        hit = any("M4" in m for m in errs)
        case("反向注入⑥：把「默认关」弱化成「可关」→ 文档咬合必须红",
             hit, "已报 M4 找不到承诺句", "未报；" + (bad or "errs=%s" % errs))
        rewrite_doc_all("可关", "默认关")
    else:
        out.append(("反向注入⑥：弱化文档承诺 → M4 必须红", False, "注入点未命中"))

    # ⑦ 完备性反查（复盘实测③）：删掉认领表里 T4 一行 → 必须有承诺无人认领。
    if rewrite_doc("| T4 无执行策略绕过 | M14 | 机械 |\n", ""):
        bad, errs, _ = run_gate("sec_matrix")
        hit = any("T4" in m and ("无人认领" in m or "认领" in m) for m in errs)
        case("反向注入⑦：删掉认领表 T4 一行 → 完备性反查必须红",
             hit, "已报 T4 无人认领", "未报；" + (bad or "errs=%s" % errs))
        rewrite_doc("| T9 输出隔离与限权 | M6 | 机械 |",
                    "| T4 无执行策略绕过 | M14 | 机械 |\n| T9 输出隔离与限权 | M6 | 机械 |")
    else:
        out.append(("反向注入⑦：删认领表一行 → 反查必须红", False, "注入点未命中"))

    # ⑧ M13 脱敏口径：把纯本地链路的默认口径降成审查用的 6 类 → 涉密文档漏脱。
    if rewrite("local-only.py", "_d.ALL_TYPES if _d else", "_d.REVIEW_TYPES if _d else"):
        bad, errs, _ = run_gate("sec_matrix")
        hit = any("M13" in m for m in errs)
        case("反向注入⑧：纯本地链路默认口径降成 6 类 → M13 必须红",
             hit, "已报 M13 口径被降", "未报；" + (bad or "errs=%s" % errs))
        rewrite("local-only.py", "_d.REVIEW_TYPES if _d else", "_d.ALL_TYPES if _d else")
    else:
        out.append(("反向注入⑧：降低脱敏默认口径 → M13 必须红", False, "注入点未命中"))

    # ⑨ M14 无执行策略绕过：塞进一条要求绕过 PowerShell 的调用 → 必须红。
    # 注入串**拼接构造**：检查器自己若把"策略名＋Bypass"按连续形态写进源码（含注释），
    # M14 判据会把 smoke-test.py 也报成绕过面——检查器自指，本项目第三次踩，
    # 且这次是**注释里的完整串**命中的，注释也算源码。
    _bypass = "powershell -Execution" + "Policy Bypass -File x.ps1"
    if rewrite("preprocess.py", "import sys as _sys",
               'import sys as _sys\n_BYPASS = "%s"' % _bypass):
        bad, errs, _ = run_gate("sec_matrix")
        hit = any("M14" in m for m in errs)
        case("反向注入⑨：引入执行策略绕过调用 → M14 必须红",
             hit, "已报 M14 存在绕过面", "未报；" + (bad or "errs=%s" % errs))
        rewrite("preprocess.py",
                'import sys as _sys\n_BYPASS = "%s"' % _bypass,
                "import sys as _sys")
    else:
        out.append(("反向注入⑨：引入执行策略绕过 → M14 必须红", False, "注入点未命中"))

    # ⑩–⑬ 格式缺省（v3.25.7）：代码默认只出 WORD 是有意的，但必须是**明示的缺省**，
    #    不能是静默的。守卫一旦失效，症状不是报错而是"用户拿到一份 WORD 还以为只有这一种"。
    #    副本根要先造一份 SKILL.md：格式门禁读不到「**文件格式（5 种」那一节就直接 return，
    #    注入再狠也全绿——"副本缺文件"造成的假绿，比门禁失效更难发现（本轮实测踩过一次）。
    _skill_ok = True
    try:
        with open(os.path.join(base, "SKILL.md"), "w", encoding="utf-8") as _f:
            _f.write("## 十一、交付格式\n\n"
                     "**文件格式（7 种：WORD／MD／Excel／HTML／PDF／PPT／思维导图）**\n\n"
                     "格式由开场清单第 9 项收集，不选或回「默认」→ 仅 WORD。\n\n"
                     "格式是产出前必收项：清单被跳过或该项未答时，产出前必须问一次，"
                     "用户回「默认」或直接回车即按 WORD 出，但这一问本身不能省。\n")
    except Exception as e:
        _skill_ok = False
        out.append(("反向注入⑩–⑬：准备副本 SKILL.md", False, repr(e)))

    def rewrite_root(fn, old, new):
        """改副本根上的文档（格式门禁要拿 SKILL.md 与代码缺省值对账）。"""
        fp = os.path.join(base, fn)
        try:
            t = open(fp, encoding="utf-8").read()
        except Exception:
            return False
        if old not in t:
            return False
        open(fp, "w", encoding="utf-8").write(t.replace(old, new, 1))
        return True

    if _skill_ok:
        # ⑩ 兜底值悄悄放宽到 5 种，文档却仍写「仅 WORD」——说的比给的少
        # v3.31.0：FORMAT_FALLBACK 搬到 format-engine.py（格式家族真源），注入点随代码搬家。
        # 注入点不跟着搬，断言就变成「注入点未命中」——冒烟会红，但红的是冒烟自己，
        # 不是被守卫抓住，等于守卫失守却看不出来（正是 v3.30.0 修过的同类假信号）。
        if rewrite("format-engine.py", 'FORMAT_FALLBACK = "docx"',
                   'FORMAT_FALLBACK = "docx,md,excel,html,pdf"'):
            bad, errs, _ = run_gate("fmt_default")
            hit = any("文档说的比给的少" in m for m in errs)
            case("反向注入⑩：默认格式悄悄放宽到 5 种 → 文档仍写「仅 WORD」必须红",
                 hit, "已报文档说的比给的少", "未报；" + (bad or "errs=%s" % errs))
            rewrite("format-engine.py", 'FORMAT_FALLBACK = "docx,md,excel,html,pdf"',
                    'FORMAT_FALLBACK = "docx"')
        else:
            out.append(("反向注入⑩：放宽 FORMAT_FALLBACK → 必须红", False, "注入点未命中"))

        # ⑪ 文档删掉「必须问」——缺省不许不声不响，这是 v3.25.6 立的规矩
        if rewrite_root("SKILL.md", "必须问", "必须-问"):
            bad, errs, _ = run_gate("fmt_default")
            hit = any("必须问" in m for m in errs)
            case("反向注入⑪：SKILL 删掉「产出前必须问一次」→ 格式门禁必须红",
                 hit, "已报缺省未要求询问", "未报；" + (bad or "errs=%s" % errs))
            rewrite_root("SKILL.md", "必须-问", "必须问")
        else:
            out.append(("反向注入⑪：删「必须问」→ 必须红", False, "注入点未命中"))

        # ⑫ 兜底值塞进文档压根没登记过的格式名
        if rewrite("format-engine.py", 'FORMAT_FALLBACK = "docx"', 'FORMAT_FALLBACK = "docx,xyz"'):
            bad, errs, _ = run_gate("fmt_default")
            hit = any("未登记" in m and "xyz" in m for m in errs)
            case("反向注入⑫：兜底值塞入未登记格式 xyz → 文档与代码分家必须红",
                 hit, "已报 xyz 未登记", "未报；" + (bad or "errs=%s" % errs))
            rewrite("format-engine.py", 'FORMAT_FALLBACK = "docx,xyz"', 'FORMAT_FALLBACK = "docx"')
        else:
            out.append(("反向注入⑫：塞未登记格式 → 必须红", False, "注入点未命中"))

        # ⑬ 哨兵丢失：default 改回固定值后，再也分不清「用户没指定」与「用户显式写了 docx」，
        #    缺省尾注永不触发；而文档与代码字面仍一致，这正是 v3.25.6 之前门禁从不报错的原因。
        if rewrite("make-docx.py", '"--formats", default=None,', '"--formats", default="docx",'):
            bad, errs, _ = run_gate("fmt_default")
            hit = any("哨兵" in m for m in errs)
            case("反向注入⑬：--formats 哨兵 default=None 改回固定值 → 必须红",
                 hit, "已报哨兵丢失", "未报；" + (bad or "errs=%s" % errs))
            rewrite("make-docx.py", '"--formats", default="docx",', '"--formats", default=None,')
        else:
            out.append(("反向注入⑬：哨兵改回固定值 → 必须红", False, "注入点未命中"))

        # ⑭ 帮助串漏登一个格式键（v3.28.0）：--formats 帮助串是格式数真源，
        #    漏写一键 → 格式数静默少数、文档承诺对不上。check_format_matrix 第 3 条必须拦。
        if rewrite("make-docx.py", "excel,pdf,html,pptx,mindmap,image（不写则仅",
                   "excel,pdf,html,pptx,mindmap（不写则仅"):
            bad, errs, _ = run_gate("fmt_matrix")
            hit = any("帮助串" in m and "不一致" in m for m in errs)
            case("反向注入⑭：--formats 帮助串漏写 mindmap → 格式矩阵必须红",
                 hit, "已报帮助串与 FORMAT_ALL 不一致", "未报；" + (bad or "errs=%s" % errs))
            rewrite("make-docx.py", "excel,pdf,html,pptx,mindmap（不写则仅",
                    "excel,pdf,html,pptx,mindmap,image（不写则仅")
        else:
            out.append(("反向注入⑭：帮助串漏登 → 必须红", False, "注入点未命中"))

        # ⑮ 白名单外 CDN 域混入（v3.28.0）：在线版外链只许 HTML_CDN_ALLOW 三域，
        #    偷加一个域就是「离线零外部资源」承诺的暗门。check_html_online_guard 第 ④ 条必须拦。
        if rewrite("format-engine.py", "HTML_CDN_ALLOW = (",
                   "HTML_CDN_ALLOW = (\"evil.example.com\","):
            bad, errs, _ = run_gate("html_online")
            hit = any("白名单" in m and ("以外" in m or "不一致" in m) for m in errs)
            case("反向注入⑮：白名单混入 evil.example.com → HTML 在线守卫必须红",
                 hit, "已报白名单违规", "未报；" + (bad or "errs=%s" % errs))
            rewrite("format-engine.py", 'HTML_CDN_ALLOW = ("evil.example.com",',
                    "HTML_CDN_ALLOW = (")
        else:
            out.append(("反向注入⑮：白名单外域 → 必须红", False, "注入点未命中"))

        # ⑯ 精要入口另起一套渲染（v3.30.0）：把 export_summary_mindmap 的 svg 调用换掉，
        #    模拟"两入口各写一套渲染器"——check_mindmap_single_source 必须拦。
        # v3.31.0：精要入口 export_summary_mindmap 整体搬进 format-engine.py，注入点随之搬。
        if rewrite("format-engine.py",
                   "write(mindmap_svg(title_txt, nodes))",
                   'write("<svg/>")'):
            bad, errs, _ = run_gate("mm_source")
            hit = any("导图单一真源" in m and "未调用" in m for m in errs)
            case("反向注入⑯：精要入口改用自建 SVG 渲染 → 导图单一真源必须红",
                 hit, "已报两入口分家", "未报；" + (bad or "errs=%s" % errs))
            rewrite("format-engine.py", 'write("<svg/>")', "write(mindmap_svg(title_txt, nodes))")
        else:
            out.append(("反向注入⑯：精要入口另起渲染 → 必须红", False, "注入点未命中"))

        # ⑰ image 子格式写坏（v3.32.0）：IMAGE_TYPES 混入不认识的扩展名 → 格式矩阵第 7 条必须拦。
        if rewrite("format-engine.py", 'IMAGE_TYPES = ("png", "jpg", "webp", "gif", "svg", "ico")',
                   'IMAGE_TYPES = ("png", "jpg", "webp", "gif", "svg", "bmp")'):
            bad, errs, _ = run_gate("fmt_matrix")
            hit = any("IMAGE_TYPES 含不认识" in m for m in errs)
            case("反向注入⑰：image 子格式混入 bmp → 格式矩阵必须红",
                 hit, "已报 IMAGE_TYPES 越界", "未报；" + (bad or "errs=%s" % errs))
            rewrite("format-engine.py", 'IMAGE_TYPES = ("png", "jpg", "webp", "gif", "svg", "bmp")',
                    'IMAGE_TYPES = ("png", "jpg", "webp", "gif", "svg", "ico")')
        else:
            out.append(("反向注入⑰：image 子格式写坏 → 必须红", False, "注入点未命中"))

        # ⑱ --image-formats 插到 --formats 之前：数字口径守卫的惰性正则会把子格式
        #    当成格式清单（8 被读成 6）——格式矩阵第 7d 条必须拦。
        src_mk = open(os.path.join(tgt, "make-docx.py"), encoding="utf-8").read()
        moved = src_mk.replace('    ap.add_argument("--formats", default=None,',
            '    ap.add_argument("--image-formats", default=None, help="x")\n'
            '    ap.add_argument("--formats", default=None,', 1)
        if moved != src_mk:
            open(os.path.join(tgt, "make-docx.py"), "w", encoding="utf-8").write(moved)
            bad, errs, _ = run_gate("fmt_matrix")
            hit = any("--image-formats" in m and ("必须声明在" in m or "不一致" in m) for m in errs)
            case("反向注入⑱：--image-formats 插到 --formats 之前 → 格式矩阵必须红",
                 hit, "已报参数顺序违规", "未报；" + (bad or "errs=%s" % errs))
            open(os.path.join(tgt, "make-docx.py"), "w", encoding="utf-8").write(src_mk)
        else:
            out.append(("反向注入⑱：参数顺序颠倒 → 必须红", False, "注入点未命中"))

        # ⑲ 去AI味规则库计数漂移（v3.32.0）：md 写的条数与 json 实算不一致 → 必须拦。
        if True:
            # 改副本 core/03-ai-tells.md 的条数声明
            _md = os.path.join(base, "core", "03-ai-tells.md")
            _msrc = open(_md, encoding="utf-8").read()
            _mbad = _msrc.replace("规则组数：5 组／**规则条数**：33 条",
                                  "规则组数：5 组／**规则条数**：30 条", 1)
            if _mbad != _msrc:
                open(_md, "w", encoding="utf-8").write(_mbad)
                bad, errs, _ = run_gate("ai_tells")
                hit = any("去AI味规则库" in m and "30 条" in m for m in errs)
                case("反向注入⑲：去AI味规则库条数漂移（33→30）→ 必须红",
                     hit, "已报条数不一致", "未报；" + (bad or "errs=%s" % errs))
                open(_md, "w", encoding="utf-8").write(_msrc)
            else:
                out.append(("反向注入⑲：规则库条数漂移 → 必须红", False, "注入点未命中"))

        # ⑳ 去AI味规则库组名漂移：md 组标题与 json 组名不一致 → 必须拦。
        _md = os.path.join(base, "core", "03-ai-tells.md")
        _msrc = open(_md, encoding="utf-8").read()
        _mbad = _msrc.replace("### A · 空洞套话", "### A · 空话套语", 1)
        if _mbad != _msrc:
            open(_md, "w", encoding="utf-8").write(_mbad)
            bad, errs, _ = run_gate("ai_tells")
            hit = any("组标题" in m and "不一致" in m for m in errs)
            case("反向注入⑳：去AI味 md 组标题与 json 组名漂移 → 必须红",
                 hit, "已报组名不一致", "未报；" + (bad or "errs=%s" % errs))
            open(_md, "w", encoding="utf-8").write(_msrc)
        else:
            out.append(("反向注入⑳：规则库组名漂移 → 必须红", False, "注入点未命中"))

    # ④ 对照组：副本**没改坏**时两个门禁都必须零 ERR。
    #    为什么要这一组：只验"改坏了会报"还不够——一个见谁报谁的门禁同样能通过 ①②③。
    #    必须同时证明"没改坏时不报"，才能说明报错是被注入的那一处触发的。
    bad, errs, _ = run_gate("online")
    bad2, errs2, _ = run_gate("bytecode")
    bad3, errs3, _ = run_gate("net_tiers")
    bad4, errs4, _ = run_gate("sec_matrix")
    bad5, errs5, _ = run_gate("fmt_default")
    bad6, errs6, _ = run_gate("fmt_matrix")
    bad7, errs7, _ = run_gate("html_online")
    bad8, errs8, _ = run_gate("mm_source")
    bad9, errs9, _ = run_gate("fmt_matrix")      # 含 image 第 7 条
    bad10, errs10, _ = run_gate("ai_tells")
    clean = not (errs or errs2 or errs3 or errs4 or errs5 or errs6 or errs7 or errs8 or errs9 or errs10)
    out.append(("反向注入④（对照）：副本未改坏时十个门禁必须零报错",
                clean,
                "均零报错" if clean
                else ("误报：" + (bad or bad2 or bad3 or bad4 or bad5 or bad6 or bad7 or bad8
                                 or str(errs + errs2 + errs3 + errs4 + errs5 + errs6 + errs7
                                        + errs8 + errs9 + errs10)))))

    shutil.rmtree(tmp, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="文档合规审查助手AI合同·端到端冒烟测试")
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
    print("文档合规审查助手AI合同 · 端到端冒烟测试")
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
    src_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
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
    # 安全机制「不改原件」的**行为判据**（25.6：能证明"没做"优于"能证明没写"）。
    # 只在源码里 grep "有没有写回源文件" 证明不了运行时真的没写——跑完比一次 sha256 才算数。
    now_sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
    check("安全机制：处理前后源文档 sha256 不变（产物一律新建，原件零写入）",
          now_sha == src_sha, "前 %s… 后 %s…" % (src_sha[:12], now_sha[:12]))

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
                # 跳过项须与全量档**逐项一一对上**，否则两档总数不守恒，
                # 而 check.py 的项数守卫默认「两档一致」，文档写哪个数都会漂。
                # 全量档此用例真正 check 的是 3 项：预处理执行 / 取出可审文本 /
                # 内容可识别（「提取并可审」不是独立 check，故此处也不记）。
                for sub in ("预处理执行", "取出可审文本", "内容可识别（关键词命中）"):
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
    print("\n[2] 交付物链路（10 类型 × docx/excel/html/pdf/pptx/mindmap）")
    spec = build_spec(os.path.join(work, "spec.json"))
    outdir = os.path.join(work, "交付物")
    fmts = ("docx,excel,html" if a.fast
            else "docx,excel,html,pdf,pptx,mindmap")   # --fast 跳过 PDF 导出（耗时大头）
    # v3.29.0：mindmap 默认只出 SVG；全量档加 --mindmap-html/--mindmap-png 验证三形态
    mk = run([PY, os.path.join(HERE, "make-docx.py"), spec,
              "--reviewer", "SMOKE-TEST", "--ts", datetime.datetime.now().strftime("%Y%m%d-%H%M"),
              "--formats", fmts, "--comments", "--out", outdir,
              "--types", "tracked,reportc,clean,redline,report,masked,original,diff,compare,template"]
             + ([] if a.fast else ["--mindmap-html", "--mindmap-png"]))
    check("make-docx.py 执行", mk.returncode == 0, (mk.stdout or "")[-300:] if mk.returncode else "")
    produced = sorted(os.listdir(outdir)) if os.path.isdir(outdir) else []
    # 注：本综合用例未传 --source-docx，故类型 1 修订版会按设计降级为 4 红线标记修订版
    # （二者去重），下方只核验实际产物；类型 1 的原生修订粒度改由 [2.x] 有原稿场景单独验证。
    kinds = ["红线标记修订版", "清洁版", "审查意见报告",
             "原文脱敏版", "原文照录版", "文件比对报告", "新旧比对", "模板版"]
    for k in kinds:
        check(f"产出 {k}.docx", any(k in f and f.endswith(".docx") and "批注版" not in f for f in produced))
    check("产出 审查意见批注版.docx（类型 5，--comments 兼容开关）",
          any("批注版" in f and f.endswith(".docx") for f in produced))

    # 格式缺省尾注（v3.25.7）：不指定 --formats 时，出件后必须留一句"还有四种可勾选"；
    # 显式指定则不许再啰嗦——两种情形出的文件一模一样，区别只在**用户有没有被问过**。
    _ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    _od = os.path.join(work, "格式缺省")
    _k = [PY, os.path.join(HERE, "make-docx.py"), spec, "--reviewer", "SMOKE-TEST",
          "--ts", _ts, "--types", "tracked", "--out", _od]
    _a = run(_k)
    _oa = _a.stdout or ""
    check("格式缺省：未指定 --formats 时出件后必须提示其余可勾选格式",
          _a.returncode == 0 and "本次未指定 --formats" in _oa, tail_line(_oa))
    _b = run(_k + ["--formats", "docx"])
    _ob = _b.stdout or ""
    check("格式缺省（对照）：显式指定 --formats docx 时不再提示",
          _b.returncode == 0 and "本次未指定 --formats" not in _ob, tail_line(_ob))
    check("产出 Excel（.xlsx）", any(f.endswith(".xlsx") for f in produced))
    # 无 --source-docx 时 1 修订版降级为 4 红线标记修订版（去重），故实出 9 类 HTML
    check("产出 HTML（.html，9 类全覆盖：无原稿时 1 降级为 4）",
          sum(1 for f in produced if f.endswith(".html")) >= 9)
    # --- v3.28.0：PPT 讲解版与思维导图（一物两件）；快速档 fmts 不含 pptx/mindmap，须 skip 保持项数守恒 ---
    # 项数守恒铁律：快速档的每条 skip 必须与全量档的每条 check **逐条同名一一对应**。
    # 早期写法用一条 skip（「思维导图三形态」）顶掉全量档四条 check，导致 fast 比 full 少 4 项，
    # 而 check_smoke_count 会拿 fast 的 total 去比文档——两档不再守恒时它就误报。此处改为一一对应。
    if a.fast:
        skip("产出 PPT 讲解版（.pptx，仅 2/8/9 三类）", "快速档已跳过（跑全量档加 --full）")
        skip("PPT 不套原稿操作件（1/3/4/5/6/7 无 .pptx）", "快速档已跳过")
        skip("产出 思维导图 SVG（默认静态形态，2/8/9/10 四类）", "快速档已跳过（跑全量档加 --full）")
        skip("产出 思维导图 HTML（--mindmap-html，四类）", "快速档已跳过")
        skip("产出 思维导图 PNG（--mindmap-png 兜底，四类）", "快速档已跳过")
        skip("导图覆盖集外无产物（原稿操作件无导图）", "快速档已跳过")
        skip("导图 HTML 自检（可折叠树/零外链）", "快速档已跳过")
        skip("导图 SVG 自检（合法标记/零外链/含内容）", "快速档已跳过")
    else:
        check("产出 PPT 讲解版（.pptx，仅 2/8/9 三类）",
              sum(1 for f in produced if f.endswith(".pptx")) == 3)
        _orig_ops = ("修订版", "清洁版", "红线", "批注版", "脱敏", "照录")
        check("PPT 不套原稿操作件（1/3/4/5/6/7 无 .pptx）",
              not any(f.endswith(".pptx") and any(k in f for k in _orig_ops) for f in produced))
        # v3.29.0：mindmap 默认 SVG；--mindmap-html/--mindmap-png 开关追加（本跑已带，验三形态各 4 件）
        check("产出 思维导图 SVG（默认静态形态，2/8/9/10 四类）",
              sum(1 for f in produced if f.endswith(".svg") and "思维导图" in f) == 4)
        check("产出 思维导图 HTML（--mindmap-html，四类）",
              sum(1 for f in produced if f.endswith(".html") and "思维导图" in f) == 4)
        check("产出 思维导图 PNG（--mindmap-png 兜底，四类）",
              sum(1 for f in produced if f.endswith(".png") and "思维导图" in f) == 4,
              f"实出 {sum(1 for f in produced if f.endswith('.png') and '思维导图' in f)} 张")
        check("导图覆盖集外无产物（原稿操作件无导图）",
              not any(f.endswith((".svg", ".png")) and any(k in f for k in _orig_ops) for f in produced))
        _mm_html = next((os.path.join(outdir, f) for f in produced
                         if f.endswith(".html") and "思维导图" in f and "审查意见报告" in f), None)
        ok_mm = False
        if _mm_html and os.path.isfile(_mm_html):
            try:
                mh = open(_mm_html, encoding="utf-8").read()
                ok_mm = ("mm-node" in mh and "addEventListener" in mh
                         and 'src="http' not in mh and 'href="http' not in mh)
            except Exception:
                ok_mm = False
        check("导图 HTML 自检（可折叠树/零外链）", ok_mm)
        _mm_svg = next((os.path.join(outdir, f) for f in produced
                        if f.endswith(".svg") and "思维导图" in f and "审查意见报告" in f), None)
        ok_svg = False
        if _mm_svg and os.path.isfile(_mm_svg):
            try:
                sv = open(_mm_svg, encoding="utf-8").read()
                ok_svg = (sv.lstrip().startswith("<svg") and "</svg>" in sv
                          and "http" not in sv.replace('xmlns="http://www.w3.org/2000/svg"', "")
                          and "审查" in sv)
            except Exception:
                ok_svg = False
        check("导图 SVG 自检（合法标记/零外链/含内容）", ok_svg)
    if a.fast:
        skip("产出 思维导图 PNG（matplotlib，300dpi）", "快速档已跳过（跑全量档加 --full）")
        skip("思维导图 PNG 位图自检（魔数/体积）", "快速档已跳过")
    else:
        _pngs = [f for f in produced if f.endswith(".png") and "思维导图" in f]
        check("产出 思维导图 PNG（matplotlib，300dpi）", len(_pngs) == 4,
              f"实出 {len(_pngs)} 张")
        if _pngs:
            _p0 = os.path.join(outdir, _pngs[0])
            ok_png = (open(_p0, "rb").read(8) == b"\x89PNG\r\n\x1a\n"
                      and os.path.getsize(_p0) > 20 * 1024)
            check("思维导图 PNG 位图自检（魔数/体积）", ok_png)
        else:
            check("思维导图 PNG 位图自检（魔数/体积）", False, "无 PNG 可检")
    # PPT 内容级自检（可解析、页数、页脚免责）
    _pp = next((os.path.join(outdir, f) for f in produced
                if f.endswith(".pptx") and "审查意见报告" in f), None)
    if a.fast:
        skip("PPT 可解析且页脚带免责（python-pptx）", "快速档已跳过")
    else:
        ok_ppt, why_ppt = False, "无 pptx 可检"
        if _pp and os.path.isfile(_pp):
            try:
                from pptx import Presentation as _P
                _prs = _P(_pp)
                _txt = "\n".join(sh.text_frame.text
                                 for sl in _prs.slides
                                 for sh in sl.shapes if sh.has_text_frame)
                ok_ppt = len(_prs.slides._sldIdLst) >= 3 and "不构成法律意见" in _txt
                why_ppt = f"{len(_prs.slides._sldIdLst)} 页"
            except Exception as e:
                ok_ppt, why_ppt = False, repr(e)
        check("PPT 可解析且页脚带免责（python-pptx）", ok_ppt, why_ppt)
    # 在线增强版（--html-online）：外链域必须 ⊆ HTML_CDN_ALLOW 白名单（运行时读真源）
    _ol_dir = os.path.join(work, "在线HTML")
    _ol = run([PY, os.path.join(HERE, "make-docx.py"), spec,
               "--reviewer", "SMOKE-TEST", "--ts", datetime.datetime.now().strftime("%Y%m%d-%H%M"),
               "--formats", "html", "--types", "report", "--html-online", "--out", _ol_dir])
    _ol_hosts, _ol_ok = set(), False
    if _ol.returncode == 0 and os.path.isdir(_ol_dir):
        _ol_files = [x for x in os.listdir(_ol_dir) if x.endswith(".html")]
        if _ol_files:
            _oh = open(os.path.join(_ol_dir, _ol_files[0]), encoding="utf-8").read()
            _ol_hosts = set(re.findall(r'(?:src|href)="https?://([^/"]+)', _oh))
            import importlib.util as _ilu
            _spec_m = _ilu.spec_from_file_location("_mk_probe", os.path.join(HERE, "make-docx.py"))
            _mk_m = _ilu.module_from_spec(_spec_m)
            try:
                _spec_m.loader.exec_module(_mk_m)
                _allow = set(_mk_m.HTML_CDN_ALLOW)
            except Exception:
                _allow = {"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"}
            _ol_ok = _ol_hosts <= _allow and '<nav class="toc">' in _oh and bool(_ol_hosts)
    check("HTML 在线增强版仅引用白名单 CDN 域（核心交互仍内联）", _ol_ok,
          f"外链域 {_ol_hosts or '无'}")
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

    # --- 2.x 降级链 1→4 与 原稿级修订粒度（v3.26.15 新增；v3.27.0 编号随 3/4/5 互换更新）---
    print("\n[2.x] 降级链 1→4（无原稿→红线标记修订版）· 原稿级修订粒度（有原稿）")
    _xdir = os.path.join(work, "降级链")
    # (a) 无 --source-docx：类型 1 必须按设计降级为 4 红线标记修订版（不得冒充原稿修改）
    _xmk = run([PY, os.path.join(HERE, "make-docx.py"), spec,
                "--reviewer", "SMOKE-TEST", "--ts", datetime.datetime.now().strftime("%Y%m%d-%H%M"),
                "--formats", "docx,md", "--out", _xdir, "--types", "tracked,report"])
    check("降级链：make-docx 执行（tracked+report，无 --source-docx）", _xmk.returncode == 0, (_xmk.stderr or "")[-200:])
    _xprod = sorted(os.listdir(_xdir)) if os.path.isdir(_xdir) else []
    _x_has_rl = any("红线标记修订版" in f and "批注版" not in f and f.endswith(".docx") for f in _xprod)
    _x_has_tr = any("修订版" in f and "红线" not in f and "批注版" not in f and f.endswith(".docx") for f in _xprod)
    _x_has_rp = any("审查意见报告" in f and f.endswith(".docx") for f in _xprod)
    check("降级链：1 降级为 4（产出 红线标记修订版，且文件名带 -准原稿 档位标记）",
          _x_has_rl and any("-准原稿" in f for f in _xprod), "产出：" + "/".join(_xprod[:3]))
    check("降级链：修订版未产出（无原稿不得冒充原稿修改）", not _x_has_tr, "/".join(_xprod[:3]))
    check("降级链：审查意见报告(2) 不受影响，照常产出", _x_has_rp)
    # (b) 有 --source-docx（由 SAMPLE 生成可匹配原稿）：类型 1 必须产出真正的 Word 原生修订
    _sdir_x = os.path.join(work, "src_sample.docx")
    make_src_docx(_sdir_x, SAMPLE)
    # 注意：本目录须与 [3.z] 原稿级修订块的 rout（work/原稿修订）区分，
    # 二者都跑「tracked + --source-docx」，make-docx 不清理输出目录，
    # 若同名则 [3.z] 的 _tr[0] 会误取本块用 SAMPLE 生成的「修订版」。
    _gdir = os.path.join(work, "原稿修订_有原稿")
    _gmk = run([PY, os.path.join(HERE, "make-docx.py"), spec,
                "--reviewer", "SMOKE-TEST", "--ts", datetime.datetime.now().strftime("%Y%m%d-%H%M"),
                "--formats", "docx", "--out", _gdir, "--source-docx", _sdir_x,
                "--types", "tracked"])
    check("原稿级修订：make-docx 执行（tracked + --source-docx）", _gmk.returncode == 0, (_gmk.stderr or "")[-200:])
    _gprod = sorted(os.listdir(_gdir)) if os.path.isdir(_gdir) else []
    _g_tr = [x for x in _gprod if "修订版" in x and "红线" not in x and "批注版" not in x and x.endswith(".docx")]
    _g_rl = [x for x in _gprod if "红线标记修订版" in x and x.endswith(".docx")]
    check("原稿级修订：产出 修订版（原稿级，无 -准原稿 档位标记）",
          bool(_g_tr) and not _g_rl and not any("-准原稿" in x for x in _g_tr), "/".join(_gprod[:3]))
    try:
        import zipfile as _zf2
        _tf = _g_tr[0]
        with _zf2.ZipFile(os.path.join(_gdir, _tf)) as _z2:
            _dx2x = _z2.read("word/document.xml").decode("utf-8")
        _segs = re.findall(r"<w:(?:ins|del) [^>]*>(.*?)</w:(?:ins|del)>", _dx2x, re.S)
        _lens = [len("".join(re.findall(r"<w:(?:t|delText)[^>]*>(.*?)</w:(?:t|delText)>", s, re.S)))
                 for s in _segs]
        check("原稿级修订粒度：存在局部改动片段（非整段替换，w:ins/w:del）",
              bool(_lens) and min(_lens) <= 10, "%d 处痕迹，最短 %s 字" % (len(_lens), min(_lens) if _lens else "-"))
    except Exception as e:
        check("原稿级修订粒度自检", False, str(e))

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
        cf = os.path.join(outdir, [f for f in produced if "清洁版" in f and f.endswith(".docx")][0])
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
    print("\n[3.z] 交付物呈现口径（去抬头 · 文档属性 · 零批注）")
    # 本综合用例无 --source-docx：类型 1 已降级为 4 红线标记修订版，故以「红线标记修订版」入表
    # （slug 仅作标注，查找靠中文名）；修订版不入表（无原稿不产出，由 [2.x] 单独验证）。
    _DOC_KINDS = {"红线标记修订版": "redline", "清洁版": "clean",
                  "原文脱敏版": "masked", "原文照录版": "original"}
    _HEADER_MARKS = ["（修订模式）", "（红线格式）", "（清洁版）", "（原文脱敏版）", "（原文照录版）"]
    _ZERO_COMMENT = ["清洁版", "原文脱敏版", "原文照录版"]
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

    # --- 3.z 原稿级修订（1 修订版 / 4 红线版：在原稿 run 之间插痕迹）---
    print("\n[3.z] 原稿级修订（1 修订版 / 4 红线版）")
    try:
        import docx as _dxr
        from docx.oxml.ns import qn as _qn
        sd = os.path.join(sdir, "合同比对A版.docx")
        if not os.path.exists(sd):
            for n in ("原稿修订：插入 w:ins/w:del 痕迹",
                      "原稿修订：接受全部修订＝改后文本",
                      "原稿修订：拒绝全部修订＝原文",
                      "原稿修订：红线版删除线/下划线并存",
                      "原稿修订：定位失败时降级并标注"):
                skip(n, "无 A 版样本（自检样本缺失）")
        else:
            _src = _dxr.Document(sd)
            _paras = [_p.text.strip() for _p in _src.paragraphs if _p.text.strip()]
            # 取「第一条 项目内容：…」整段做用例（标题＝首个分句，原文＝其后的正文）
            _whole = next((t for t in _paras if t.startswith("第一条")), _paras[-1])
            _head = _whole.split("：")[0] + "：" if "：" in _whole else _whole
            _orig = _whole[_whole.index("：") + 1:] if "：" in _whole else _whole
            _new = _orig.replace("四个阶段", "五个阶段") if "四个阶段" in _orig else _orig + "（已改）"
            rspec = {"name": "原稿修订自检", "source": "合同比对A版", "clauses": [
                {"heading": _head, "original": _orig, "revised": _new,
                 "comment": "自检用", "basis": "自检", "rating": "★"}]}
            rsp = os.path.join(work, "rev-spec.json")
            with open(rsp, "w", encoding="utf-8") as f:
                json.dump(rspec, f, ensure_ascii=False)
            rout = os.path.join(work, "原稿修订")
            rc = run([PY, os.path.join(HERE, "make-docx.py"), rsp,
                      "--reviewer", "SMOKE-TEST", "--types", "tracked,redline",
                      "--source-docx", sd, "--out", rout, "--ts", "20260101-0000"])
            check("原稿级修订：make-docx 执行", rc.returncode == 0,
                  (rc.stderr or "")[-160:] if rc.returncode else "")
            _fs = sorted(os.listdir(rout)) if os.path.isdir(rout) else []
            _tr = [f for f in _fs if "修订版" in f]
            _rl = [f for f in _fs if "红线" in f]

            def _acc(p):
                return "".join(t.text or "" for t in p._p.iter(_qn("w:t")))

            def _rej(p):
                out = []
                for el in p._p.iter():
                    if el.tag == _qn("w:t") and el.getparent().getparent().tag != _qn("w:ins"):
                        out.append(el.text or "")
                    elif el.tag == _qn("w:delText"):
                        out.append(el.text or "")
                return "".join(out)

            if not _tr:
                check("原稿修订：产出修订版", False, "未见修订版文件")
            else:
                d = _dxr.Document(os.path.join(rout, _tr[0]))
                ins = d.element.body.findall(".//" + _qn("w:ins"))
                dele = d.element.body.findall(".//" + _qn("w:del"))
                check("原稿修订：插入 w:ins/w:del 痕迹", bool(ins) and bool(dele),
                      "ins=%d del=%d" % (len(ins), len(dele)))
                _auth = {e.get(_qn("w:author")) for e in ins + dele}
                check("原稿修订：修订者＝审查人", _auth == {"SMOKE-TEST"}, str(_auth))
                _all = list(d.paragraphs)
                _hit = [p for p in _all if _new in _acc(p)]
                check("原稿修订：接受全部修订＝改后文本", bool(_hit),
                      (_acc(_hit[0])[:60] if _hit else "未找到改后文本"))
                _hit2 = [p for p in _all if _orig in _rej(p)]
                check("原稿修订：拒绝全部修订＝原文", bool(_hit2),
                      (_rej(_hit2[0])[:60] if _hit2 else "未找到原文"))
                check("原稿修订：版式沿用原稿（段落数不变）",
                      len(d.paragraphs) == len(_src.paragraphs),
                      "%d 段 vs 原稿 %d 段" % (len(d.paragraphs), len(_src.paragraphs)))
            if not _rl:
                check("原稿修订：产出红线版", False, "未见红线版文件")
            else:
                d2 = _dxr.Document(os.path.join(rout, _rl[0]))
                _st = [_r for p in d2.paragraphs for _r in p.runs if _r.font.strike]
                _ul = [_r for p in d2.paragraphs for _r in p.runs
                       if _r.font.underline and not _r.font.strike]
                check("原稿修订：红线版删除线/下划线并存", bool(_st) and bool(_ul),
                      "删除 %d 段／新增 %d 段" % (len(_st), len(_ul)))
            # 负向：给一条原稿里根本没有的条款 → 必须降级并标注，不得静默
            bspec = {"name": "原稿修订负向", "source": "合同比对A版", "clauses": [
                {"heading": "第九十九条 原稿根本不存在", "original": "原稿中并无此段文字内容",
                 "revised": "改后的内容"}]}
            bsp = os.path.join(work, "rev-bad.json")
            with open(bsp, "w", encoding="utf-8") as f:
                json.dump(bspec, f, ensure_ascii=False)
            bout = os.path.join(work, "原稿修订负向")
            run([PY, os.path.join(HERE, "make-docx.py"), bsp, "--reviewer", "SMOKE-TEST",
                 "--types", "tracked", "--source-docx", sd, "--out", bout,
                 "--ts", "20260101-0000"])
            _bf = [f for f in os.listdir(bout)] if os.path.isdir(bout) else []
            _deg = [f for f in _bf if "-准原稿B" in f]
            _cm = ""
            if _bf:
                try:
                    _cm = _dxr.Document(os.path.join(bout, _bf[0])).core_properties.comments or ""
                except Exception:
                    _cm = ""
            check("原稿修订：定位失败时降级并标注（文件名档位标记＋文档属性两处）",
                  bool(_deg) and "降级" in _cm,
                  "文件名档位标记=%s 属性含降级=%s" % (bool(_deg), "降级" in _cm))
    except Exception as e:
        check("原稿级修订自检", False, repr(e))

    # --- 3.z2 原稿就地批注（5 批注版：正文＝原稿、意见挂在原稿段落上）---
    # 这一组是 D-2 的回归守卫：v3.26.6 及以前 type 2 根本不读 --source-docx，
    # 交出的是「新建清单 ＋ 批注挂在清单标题上」，与 1 修订版行为不一致却看不出来。
    # 判据取**段落序列逐段相等**——只要它偷懒重建，段落数与文字必然不同，一眼红。
    print("\n[3.z2] 原稿就地批注（5 审查意见批注版）")
    _NC = ["批注版：以 --source-docx 为底（段落序列与原稿逐段相等）",
           "批注版：意见挂到原稿对应段落",
           "批注版：批注者＝审查人、条数＝实质意见数",
           "批注版：无原稿时回退并标注非原稿",
           "批注版：部分定位不到仍属原稿件（无档位标记、属性标注部分落位）",
           "批注版：.doc 老格式先转 .docx 再做底"]
    try:
        import docx as _dxn
        from docx.oxml.ns import qn as _qn2
        _sd = os.path.join(sdir, "合同比对A版.docx")
        if not os.path.exists(_sd):
            for _n in _NC:
                skip(_n, "无 A 版样本（自检样本缺失）")
        else:
            _src = _dxn.Document(_sd)
            _ptx = [p.text for p in _src.paragraphs]

            def _cl(i):
                """取第 i 段切出「标题＋正文」当一条审查意见（原文＝该段冒号后的整段）。"""
                head, _, body = _ptx[i].partition("：")
                return {"heading": head + "：", "original": body,
                        "revised": body + "（自检改写）", "rating": "★★",
                        "comment": "自检用", "basis": "自检用"}

            _si = [i for i, t in enumerate(_ptx) if t.startswith("第五条")][0]
            _cs = [_cl(_si), _cl(_si + 1)]
            _csp = os.path.join(work, "cmt-spec.json")
            with open(_csp, "w", encoding="utf-8") as f:
                json.dump({"name": "批注版自检", "source": "合同比对A版", "clauses": _cs},
                          f, ensure_ascii=False)

            def _run_cmt(spec_path, outdir, src=None, types="reportc"):
                cmd = [PY, os.path.join(HERE, "make-docx.py"), spec_path,
                       "--reviewer", "SMOKE-TEST", "--types", types,
                       "--out", outdir, "--ts", "20260101-0000"]
                if src:
                    cmd += ["--source-docx", src]
                run(cmd)
                fs = [x for x in os.listdir(outdir) if x.endswith(".docx")] if os.path.isdir(outdir) else []
                return fs

            _cout = os.path.join(work, "原稿批注")
            _fs = _run_cmt(_csp, _cout, _sd)
            if not _fs:
                for _n in _NC:
                    check(_n, False, "未见批注版产出")
            else:
                _f = _fs[0]
                _od = _dxn.Document(os.path.join(_cout, _f))
                _otx = [p.text for p in _od.paragraphs]
                check(_NC[0], _otx == _ptx,
                      "%d 段 vs 原稿 %d 段%s" % (len(_otx), len(_ptx),
                                                "" if _otx == _ptx else "（首处不同：%s ↔ %s）"
                                                % (next((a for a, b in zip(_otx, _ptx) if a != b), "")[:18],
                                                   next((b for a, b in zip(_otx, _ptx) if a != b), "")[:18])))
                # 批注锚点：必须落在原稿对应那一段上（不是新加的清单标题）
                _anch = [i for i, p in enumerate(_od.paragraphs)
                         if p._p.findall(".//" + _qn2("w:commentRangeStart"))]
                check(_NC[1], _anch == [_si, _si + 1],
                      "锚点段落 %s（应为 %s）" % (_anch, [_si, _si + 1]))
                import zipfile as _zfn
                with _zfn.ZipFile(os.path.join(_cout, _f)) as _z:
                    _cxml = (_z.read("word/comments.xml").decode("utf-8")
                             if "word/comments.xml" in _z.namelist() else "")
                _auth = set(re.findall(r'<w:comment [^>]*w:author="([^"]*)"', _cxml))
                check(_NC[2], len(re.findall(r"<w:comment ", _cxml)) == 2 and _auth == {"SMOKE-TEST"},
                      "%d 条，作者 %s" % (len(re.findall(r"<w:comment ", _cxml)), _auth))

                # 负向 1：不给原稿 → 必须回退「重建清单」并在文件名与正文同时标注，不得静默
                _dg = os.path.join(work, "批注无原稿")
                _df = _run_cmt(_csp, _dg)
                _dtx = "".join(p.text for p in _dxn.Document(os.path.join(_dg, _df[0])).paragraphs) if _df else ""
                check(_NC[3], bool(_df) and "-准原稿B" in _df[0] and "非原稿" in _dtx,
                      "%s｜正文标注=%s" % (_df[0] if _df else "无产出", "非原稿" in _dtx))

                # 负向 2：部分条款对不上 → 仍是原稿件（文件名无 -准原稿 标记），正文不作重建
                _psp = os.path.join(work, "cmt-part.json")
                with open(_psp, "w", encoding="utf-8") as f:
                    json.dump({"name": "批注版部分", "source": "合同比对A版",
                               "clauses": _cs + [{"heading": "第九十九条 原稿没有这一段",
                                                  "original": "原稿中并不存在这段文字",
                                                  "revised": "改后", "comment": "自检"}]},
                              f, ensure_ascii=False)
                _po = os.path.join(work, "批注部分落位")
                _pf = _run_cmt(_psp, _po, _sd)
                _ptx2 = ([p.text for p in _dxn.Document(os.path.join(_po, _pf[0])).paragraphs]
                         if _pf else [])
                import zipfile as _zfp
                _czmeta = ""
                if _pf:
                    with _zfp.ZipFile(os.path.join(_po, _pf[0])) as _zc:
                        _czmeta = _zc.read("docProps/core.xml").decode("utf-8", "replace")
                check(_NC[4], bool(_pf) and "-准原稿" not in _pf[0]
                          and "降级（部分）" in _czmeta and _ptx2 == _ptx,
                      "%s｜段落序列仍等于原稿=%s｜属性含部分落位=%s"
                      % (_pf[0] if _pf else "无产出", _ptx2 == _ptx, "降级（部分）" in _czmeta))

                # 正路 2：.doc 老格式——预读按文件头识别、转 .docx 后再做底
                _soc = shutil.which("soffice") or shutil.which("libreoffice")
                if not _soc:
                    skip(_NC[5], "本机无 LibreOffice：.doc 转换路径未验（缺它时技能降级并标注）")
                else:
                    _dd = os.path.join(work, "doc样本")
                    os.makedirs(_dd, exist_ok=True)
                    try:
                        run([_soc, "-env:UserInstallation=file://" + os.path.join(_dd, "lo-profile"),
                             "--headless", "--convert-to", "doc:MS Word 97", "--outdir", _dd, _sd],
                            timeout=300)
                    except Exception:
                        pass
                    _docf = os.path.join(_dd, os.path.splitext(os.path.basename(_sd))[0] + ".doc")
                    if not os.path.exists(_docf):
                        skip(_NC[5], "LibreOffice 未产出 .doc 样本，转换路径未验")
                    else:
                        _do = os.path.join(work, "批注-doc源")
                        _dff = _run_cmt(_csp, _do, _docf)
                        _dtx2 = ([p.text for p in _dxn.Document(os.path.join(_do, _dff[0])).paragraphs]
                                 if _dff else [])
                        check(_NC[5], _dtx2 == _ptx,
                              "%s｜段落序列与原稿一致=%s" % (_dff[0] if _dff else "无产出", _dtx2 == _ptx))
    except Exception as _e:
        check("原稿就地批注自检", False, repr(_e))

    # --- 3.4 法条核验（legal-verify.py ＋ core/legal-articles.json）---
    print("\n[3.4] 法条核验（离线原文库比对）")
    try:
        lv = os.path.join(HERE, "legal-verify.py")
        dbp = os.path.join(HERE, "..", "core", "legal-articles.json")
        check("法条核验：原文库可读且非空",
              os.path.exists(dbp) and os.path.getsize(dbp) > 20000,
              "%d 字节" % (os.path.getsize(dbp) if os.path.exists(dbp) else 0))
        if not os.path.exists(lv):
            check("法条核验：脚本存在", False, "缺 scripts/legal-verify.py")
        else:
            _ok = "《民法典》第五百八十五条规定，当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金。\n" \
                  "《劳动合同法》第四十六条规定，劳动者依照本法第三十八条规定解除劳动合同的，用人单位应当向劳动者支付经济补偿。\n"
            _okf = os.path.join(work, "lv-ok.md")
            with open(_okf, "w", encoding="utf-8") as f:
                f.write(_ok)
            r_ok = run([PY, lv, "--file", _okf])
            check("法条核验：正确引用判「通过」并退出 0",
                  r_ok.returncode == 0 and "通过" in (r_ok.stdout or ""),
                  head_lines(r_ok.stdout))
            # 负向一：编造的条号内容（585 条里没有「百分之三十」）
            _bad = "《民法典》第五百八十五条规定，违约金不得超过合同总价款的百分之三十。\n" \
                   "《民事诉讼法》第九百九十九条规定，当事人可以协议管辖。\n"
            _badf = os.path.join(work, "lv-bad.md")
            with open(_badf, "w", encoding="utf-8") as f:
                f.write(_bad)
            r_bad = run([PY, lv, "--file", _badf])
            check("法条核验：引述失真／条号不在库时判「待核验」并退出 1",
                  r_bad.returncode == 1 and "待核验" in (r_bad.stdout or ""),
                  head_lines(r_bad.stdout))
            # 负向二：版本提示（商标法 2027-01-01 起施行的新版条号整体前移）
            _ver = "《商标法》第四十三条规定，商标注册人可以通过签订商标使用许可合同，许可他人使用其注册商标。\n"
            _verf = os.path.join(work, "lv-ver.md")
            with open(_verf, "w", encoding="utf-8") as f:
                f.write(_ver)
            r_ver = run([PY, lv, "--file", _verf])
            check("法条核验：换代在即的法律给出「已修订／施行日」提示",
                  "修订" in (r_ver.stdout or "") and "2027-01-01" in (r_ver.stdout or ""),
                  head_lines(r_ver.stdout))
            # 机读输出
            _jf = os.path.join(work, "lv-out.json")
            run([PY, lv, "--file", _okf, "--json", _jf])
            _rows = []
            try:
                with open(_jf, encoding="utf-8") as f:
                    _rows = json.load(f).get("rows") or []
            except Exception:
                _rows = []
            check("法条核验：--json 产出机读结果（条号/判定/版本齐备）",
                  bool(_rows) and all({"law", "no", "status", "version"} <= set(r) for r in _rows),
                  "%d 行" % len(_rows))
            # 库规模与新增法：只**读库**不抓网，防止扩库后口径回退或法名识别漏配
            _dbj = {}
            try:
                with open(dbp, encoding="utf-8") as f:
                    _dbj = json.load(f)
            except Exception:
                _dbj = {}
            _nl = len(_dbj.get("laws") or {})
            _na = sum(len(v) for v in (_dbj.get("laws") or {}).values())
            check("法条核验：原文库规模达「多部法、覆盖面够用」",
                  _nl >= 15 and _na >= 300, "%d 部法、%d 条" % (_nl, _na))
            # 新增的合同／公司／数据合规四部法必须能被法名识别并核到条文
            _new = ("《公司法》第四十七条规定，全体股东认缴的出资额由股东按照公司章程的规定自公司成立之日起五年内缴足。\n"
                    "《数据安全法》第二十一条规定，国家建立数据分类分级保护制度。\n"
                    "《消费者权益保护法》第二十五条规定，经营者采用网络等方式销售商品，消费者有权自收到商品之日起七日内退货。\n")
            _newf = os.path.join(work, "lv-new.md")
            with open(_newf, "w", encoding="utf-8") as f:
                f.write(_new)
            r_new = run([PY, lv, "--file", _newf])
            check("法条核验：新增法（公司法／数据安全法／消保法）可识别并核到原文",
                  r_new.returncode == 0 and (r_new.stdout or "").count("通过") >= 3,
                  head_lines(r_new.stdout))

            # --- v3.26.5：三部新法 + 「之一」条 ---
            # 这三部是「规则正文引了、库里查不到」的那几部（发票条款、虚开发票两罪、
            # 药品广告），闭掉它们才算真能核。
            _three = ("《刑法》第二百零五条之一规定，虚开本法第二百零五条规定以外的其他发票，情节严重的，"
                      "处二年以下有期徒刑、拘役或者管制，并处罚金。\n"
                      "《药品管理法》第八十九条规定，药品广告应当经广告主所在地省、自治区、直辖市人民政府"
                      "确定的广告审查机关批准；未经批准的，不得发布。\n"
                      "《发票管理办法》第二十一条规定，开具发票应当按照规定的时限、顺序、栏目，"
                      "全部联次一次性如实开具。\n")
            _threef = os.path.join(work, "lv-three.md")
            with open(_threef, "w", encoding="utf-8") as f:
                f.write(_three)
            r_three = run([PY, lv, "--file", _threef])
            check("法条核验：新增三部（刑法／药品管理法／发票办法）可识别并核到原文",
                  r_three.returncode == 0 and (r_three.stdout or "").count("通过") >= 3,
                  head_lines(r_three.stdout))
            # 增设条必须与主条分开存：合并即「两个罪名一条文」，且查得到 205、
            # 查不到 205 之一而看不出少了（v3.26.5 修的就是这个）
            _xj = (_dbj.get("laws") or {}).get("刑法") or {}
            check("法规库：增设条独立成条（205 与 205.1 并存）",
                  "205" in _xj and "205.1" in _xj,
                  "刑法条号：%s" % ",".join(sorted(_xj, key=lambda k: float(k))))
            # 版本关：1997 年原文第 205 条含「处无期徒刑或者死刑」，
            # 该档已由修正案八（2011-05-01）删除。库里若还有，就是把废条文当真值源。
            _t205 = (_xj.get("205") or {}).get("text") or "未收录"
            check("法规库：刑法 205 为现行文本（不含修正案八已删的死刑档）",
                  _t205 != "未收录" and "死刑" not in _t205, _t205[:40])
            # 检索侧：条号标签要把「之一」放在「条」后（第205条之一），写成
            # 「第205 之一条」既不成话、也会让条号解析匹配不到
            r_one = run([PY, os.path.join(HERE, "legal-search.py"),
                         "--article", "刑法", "205之一"])
            check("法规检索：按「205之一」精确命中增设条",
                  r_one.returncode == 0 and "第205条之一" in (r_one.stdout or ""),
                  head_lines(r_one.stdout))

            # --- v3.26.11（H-08）：「待核验」拆成因 ---
            # 病征不是「判错了」，而是**判对了却读不懂**：判词只有「待核验」三个字时，
            # 使用者一律读成「库里没这条」，于是把「条号旧了」记成「库缺条」，信任被自己的工具消耗掉。
            # 判据三样：①映射解析得出（防「注记写着、核验不输出」）②四种成因各自可辨 ③不许一刀切误伤。
            def _row1(out):
                return [l for l in (out or "").splitlines() if l.startswith("| 1 |")]

            import importlib.util as _ilu8
            _sp8 = _ilu8.spec_from_file_location("_lv8", lv)
            _m8 = _ilu8.module_from_spec(_sp8)
            _sp8.loader.exec_module(_m8)
            _omap = {k: _m8.old_new_map(((_dbj.get("meta") or {}).get(k) or {}).get("note"))
                     for k in ("发票管理办法", "反不正当竞争法")}
            check("法条核验：旧条号映射能从版本注记里解析出来（防「注记写着、核验不输出」）",
                  _omap.get("发票管理办法", {}).get(22) == 21
                  and _omap.get("反不正当竞争法", {}).get(7) == 8,
                  "发票 %s；反不正当竞争 %s" % (_omap.get("发票管理办法"), _omap.get("反不正当竞争法")))

            _case8 = [
                ("lv-shift1.md", "《发票管理办法》第二十二条规定，任何单位和个人不得虚开发票。\n",
                 "条号疑旧", "第21条",
                 "引 2019 版旧条号 → 判「条号疑旧」并直接给出「旧22→新21」"),
                ("lv-shift2.md", "《反不正当竞争法》第七条规定，经营者不得采用财物或者其他手段贿赂交易相对方的工作人员。\n",
                 "条号疑旧", "第8条",
                 "另一部法的旧条号同样识别（旧7→新8）——不能只认一部法"),
                ("lv-outside.md", "《食品安全法》第一百条规定，食品生产经营者应当建立食品安全追溯体系。\n",
                 "库外未收录", "",
                 "真库外条号判「库外未收录」，不得与「条号疑旧」混为一谈"),
                ("lv-summ.md", "《刑法》第二百零五条规定，虚开增值税专用发票的，构成虚开增值税专用发票罪。\n",
                 "表述偏差", "",
                 "罪名式概括判「表述偏差」——大意是对的，说成「引述失真」会冤枉人"),
            ]
            for _fn, _txt, _cause, _extra, _name in _case8:
                _fp = os.path.join(work, _fn)
                with open(_fp, "w", encoding="utf-8") as f:
                    f.write(_txt)
                _r = run([PY, lv, "--file", _fp])
                _r1 = _row1(_r.stdout)
                # 成因在「判定」列（表格行里查），改写后的新条号在「逐条说明」里（全文查）——
                # 两处分开放，是因为判据要钉的正是「判定与解释都得对」，只对一半也算没过。
                check("法条核验：" + _name,
                      bool(_r1) and _cause in _r1[0] and (_extra in (_r.stdout or "") if _extra else True),
                      _r1[0][:130] if _r1 else head_lines(_r.stdout))
            # 反向：改引现条号后必须判「通过」，且判定列**不带成因后缀**
            # （只要带了，就说明判据是一刀切挂上去的，不是按成因给的）
            _nowf = os.path.join(work, "lv-now.md")
            with open(_nowf, "w", encoding="utf-8") as f:
                f.write("《发票管理办法》第二十一条规定，开具发票应当按照规定的时限、顺序、栏目，"
                        "全部联次一次性如实开具。\n")
            _r_nw = run([PY, lv, "--file", _nowf])
            _r1nw = _row1(_r_nw.stdout)
            check("法条核验：改引现条号后判「通过」，判定列不带成因后缀（不许一刀切）",
                  bool(_r1nw) and "通过" in _r1nw[0] and "·" not in _r1nw[0].split("|")[4],
                  _r1nw[0][:130] if _r1nw else head_lines(_r_nw.stdout))
    except Exception as e:
        check("法条核验自检", False, repr(e))

    # --- 3.45 模板引擎（占位符必填／条件段／版本留痕）---
    print("\n[3.45] 模板引擎（模板版出件前的硬闸）")
    try:
        te = os.path.join(HERE, "tpl-engine.py")
        if not os.path.exists(te):
            check("模板引擎：脚本存在", False, "缺 scripts/tpl-engine.py")
        else:
            check("模板引擎：脚本存在", True, "scripts/tpl-engine.py")

            def _tpl(body, values=None, sw=None, meta=None, placeholders=None):
                t = {"name": "T（模板）", "body": body,
                     "placeholders": placeholders if placeholders is not None else
                     [{"name": "{{甲方全称}}", "meaning": "x", "required": True}],
                     "values": values if values is not None else {"甲方全称": "某公司"}}
                if sw is not None:
                    t["switches"] = sw
                if meta is not None:
                    t["meta"] = meta
                return {"name": "T", "template": t}

            HDR = "<!-- tpl: T | ver: 1.0.0 | date: 2026-01-01 | 变更: 初版 -->\n"
            # ① 体检模式：结构对就过（不看必填填没填）
            p_ok = os.path.join(work, "tpl-ok.json")
            json.dump(_tpl(HDR + "甲方：{{甲方全称}}\n{{#有担保}}\n担保。\n{{/有担保}}\n"
                           "{{^有担保}}\n无担保。\n{{/有担保}}", sw={"有担保": True}),
                      open(p_ok, "w", encoding="utf-8"), ensure_ascii=False)
            r1 = run([PY, te, "check", p_ok])
            check("模板引擎：结构合规的模板体检通过",
                  r1.returncode == 0 and "版本 1.0.0" in (r1.stdout or ""), head_lines(r1.stdout))

            # ② 出件模式：必填未填要拦
            p_blank = os.path.join(work, "tpl-blank.json")
            json.dump(_tpl(HDR + "甲方：{{甲方全称}}", values={}, sw={}),
                      open(p_blank, "w", encoding="utf-8"), ensure_ascii=False)
            r2 = run([PY, te, "render", p_blank])
            check("模板引擎：必填占位符未填实即拦下（退出 1）",
                  r2.returncode == 1 and "必填占位符未填实" in (r2.stdout or ""),
                  head_lines(r2.stdout))

            # ③ 条件段按开关取舍：开=留、关=删
            p_sw = os.path.join(work, "tpl-sw.json")
            json.dump(_tpl(HDR + "前段。\n{{#有担保}}\n担保条款。\n{{/有担保}}\n后段。"),
                      open(p_sw, "w", encoding="utf-8"), ensure_ascii=False)
            o_on = run([PY, te, "render", p_sw, "--switch", "有担保=1"])
            o_off = run([PY, te, "render", p_sw, "--switch", "有担保=0"])
            check("模板引擎：条件段按开关取舍（开则留、关则删）",
                  "担保条款" in (o_on.stdout or "") and "担保条款" not in (o_off.stdout or ""),
                  "开=%s／关=%s" % ("留" if "担保条款" in (o_on.stdout or "") else "删",
                                   "留" if "担保条款" in (o_off.stdout or "") else "删"))

            # ④ 开关未给值不得默认保留（默认保留＝偷偷加条款）
            r4 = run([PY, te, "render", p_sw])
            check("模板引擎：条件段开关未给值即拦下（不默认保留）",
                  r4.returncode == 1 and "开关未给值" in (r4.stdout or ""),
                  head_lines(r4.stdout))

            # ⑤ 版本留痕缺失要拦；版本号写得出
            p_nover = os.path.join(work, "tpl-nover.json")
            json.dump(_tpl("甲方：{{甲方全称}}"), open(p_nover, "w", encoding="utf-8"),
                      ensure_ascii=False)
            r5 = run([PY, te, "check", p_nover])
            check("模板引擎：缺版本留痕即拦下（模板改了没法追溯）",
                  r5.returncode == 1 and "版本留痕" in (r5.stdout or ""), head_lines(r5.stdout))

            # ⑥ make-docx 出模板版：版本号进文档属性与正文
            p_full = os.path.join(work, "tpl-full.json")
            json.dump(_tpl(HDR + "甲方：{{甲方全称}}", sw={}), open(p_full, "w", encoding="utf-8"),
                      ensure_ascii=False)
            outd = os.path.join(work, "tpl-out")
            r6 = run([PY, os.path.join(HERE, "make-docx.py"), p_full, "--types", "template",
                      "--reviewer", "冒烟测试", "--out", outd, "--ts", "20260101-0000"])
            got = ""
            try:
                from docx import Document as _Doc
                fns = [f for f in os.listdir(outd) if f.endswith(".docx")]
                if fns:
                    _d = _Doc(os.path.join(outd, fns[0]))
                    got = (_d.core_properties.subject or "") + "".join(p.text for p in _d.paragraphs)
            except Exception:
                pass
            check("模板引擎：模板版出件把版本号写进文档属性与正文",
                  r6.returncode == 0 and "1.0.0" in got, "版本串%s在产出中" % ("" if "1.0.0" in got else "不"))

            # ⑦ 出件闸生效：必填未填时 make-docx 必须拒绝出件
            r7 = run([PY, os.path.join(HERE, "make-docx.py"), p_blank, "--types", "template",
                      "--reviewer", "冒烟测试", "--out", os.path.join(work, "tpl-out2"),
                      "--ts", "20260101-0000"])
            check("模板引擎：模板不合规时 make-docx 拒绝出件（拦得住）",
                  r7.returncode != 0 and "校验未通过" in ((r7.stdout or "") + (r7.stderr or "")),
                  head_lines(r7.stdout))
    except Exception as e:
        check("模板引擎自检", False, repr(e))

    # --- 3.47 核验引擎（产物出得去出不去的裁判）---
    print("\n[3.47] 核验引擎（四类核验／三档出口）")
    try:
        vf = os.path.join(HERE, "verify.py")
        if not os.path.exists(vf):
            check("核验引擎：脚本存在", False, "缺 scripts/verify.py")
        else:
            check("核验引擎：脚本存在", True, "scripts/verify.py")

            # ① 干净文本必须判「通过」（不许误伤）
            p_ok = os.path.join(work, "vf-ok.md")
            open(p_ok, "w", encoding="utf-8").write(
                "第一条 甲方应于2025年3月1日前交货。\n"
                "第二条 货款人民币12,000元（大写：壹万贰仟元整）。\n"
                "第三条 未尽事宜依照第一条办理。\n")
            r1 = run([PY, vf, "--file", p_ok, "--only", "caliber"])
            check("核验引擎：干净文本判通过（不误伤）",
                  r1.returncode == 0 and "通过" in (r1.stdout or ""), head_lines(r1.stdout))

            # ② 四类机械错误各拦一次，且必须给定位
            p_bad = os.path.join(work, "vf-bad.md")
            open(p_bad, "w", encoding="utf-8").write(
                "第一条 甲方：{{甲方全称}}。\n"
                "第二条 自2025年3月1日至2025年1月1日止。\n"
                "第三条 货款人民币12,000元（大写：壹拾贰万元整）。\n"
                "第四条 依照第九条办理。\n")
            r2 = run([PY, vf, "--file", p_bad, "--only", "caliber"])
            o2 = r2.stdout or ""
            check("核验引擎：占位符残留／日期倒置／金额大小写不一致 三类拦下（退出 1）",
                  r2.returncode == 1 and "占位符" in o2 and "日期区间倒置" in o2
                  and "金额大小写" in o2, head_lines(o2))
            check("核验引擎：每个问题都给定位（不给定位于使用者无用）",
                  "第 1 行" in o2 and "第 2 行" in o2 and "第 3 行" in o2,
                  "定位出现 %d 次" % o2.count("第 "))

            # ③ 机器可读：--json 落盘且结构完整
            p_json = os.path.join(work, "vf.json")
            r3 = run([PY, vf, "--file", p_bad, "--only", "caliber", "--json", p_json])
            ok_json, why = False, "未生成"
            try:
                d = json.load(open(p_json, encoding="utf-8"))
                fs = d.get("findings") or []
                ok_json = (d.get("level") == "拦下" and fs
                           and all(f.get("loc") for f in fs if f.get("level") != "通过"))
                why = "level=%s／%d 项" % (d.get("level"), len(fs))
            except Exception as e:
                why = repr(e)
            check("核验引擎：--json 输出机读结果且复核项均带定位", ok_json, why)

            # ④ 金额大小写按钱数比、不按字形比（合法异写不得误报）
            p_amt = os.path.join(work, "vf-amt.md")
            open(p_amt, "w", encoding="utf-8").write(
                "第一条 货款人民币100,000元（大写：拾万元整）。\n"
                "第二条 货款人民币12,000元（大写：壹万贰仟圆整）。\n"
                "第三条 货款人民币12,000.05元（大写：壹万贰仟元零伍分）。\n")
            r4 = run([PY, vf, "--file", p_amt, "--only", "caliber"])
            check("核验引擎：大写合法异写不误报（拾万＝壹拾万／圆＝元／零伍分）",
                  r4.returncode == 0, head_lines(r4.stdout))
    except Exception as e:
        check("核验引擎自检", False, repr(e))

    # --- 3.48 失衡画像（单文档内部多处问题的横向归纳）---
    print("\n[3.48] 失衡画像（横向归纳）")
    try:
        im = os.path.join(HERE, "imbalance.py")
        if not os.path.exists(im):
            check("失衡画像：脚本存在", False, "缺 scripts/imbalance.py")
        else:
            check("失衡画像：脚本存在", True, "scripts/imbalance.py")
            r1 = run([PY, im, "--self-test"])
            check("失衡画像：内置判定用例全过",
                  r1.returncode == 0 and "自检通过" in (r1.stdout or ""), head_lines(r1.stdout))

            # 真跑一组：11 条计入、9 条不利 → 系统性偏移，且只列真正集中的维度
            p_rows = os.path.join(work, "imb-rows.json")
            rows = [{"no": "8.%d" % i, "level": "★★", "dim": "违约责任", "against": True}
                    for i in range(1, 5)]
            rows += [{"no": "4.%d" % i, "level": "★★", "dim": "付款与结算", "against": True}
                     for i in range(1, 4)]
            rows += [{"no": "3.2", "level": "★★", "dim": "交付与验收", "against": True},
                     {"no": "12.1", "level": "★★", "dim": "管辖与争议解决", "against": True},
                     {"no": "6.5", "level": "★★", "dim": "解除与终止", "against": False},
                     {"no": "2.1", "level": "★", "dim": "交付与验收", "against": True}]
            json.dump(rows, open(p_rows, "w", encoding="utf-8"), ensure_ascii=False)
            r2 = run([PY, im, "--rows", p_rows, "--side", "甲方"])
            o2 = r2.stdout or ""
            check("失衡画像：同向占多数即判系统性偏移，并给出证据计数",
                  r2.returncode == 0 and "系统性有利于对方" in o2
                  and "计入 10 条" in o2 and "占 90%" in o2, head_lines(o2))
            check("失衡画像：★ 提示项不参与统计",
                  "已剔除 1 条 ★" in o2, head_lines(o2))
            check("失衡画像：最集中维度不把只有 1 条的维度算进去",
                  "最集中维度：违约责任、付款与结算" in o2, head_lines(o2))

            # 样本不足必须不判（宁可交诚实结论，不硬凑洞察）
            p_empty = os.path.join(work, "imb-empty.json")
            json.dump([{"no": "1", "level": "★★", "dim": "违约责任", "against": True},
                       {"no": "2", "level": "★★", "dim": "违约责任", "against": True}],
                      open(p_empty, "w", encoding="utf-8"), ensure_ascii=False)
            r3 = run([PY, im, "--rows", p_empty, "--side", "甲方"])
            check("失衡画像：样本不足 3 条时明说不判（不硬凑系统性结论）",
                  r3.returncode == 0 and "未发现系统性偏移" in (r3.stdout or "")
                  and "不足 3 条" in (r3.stdout or ""), head_lines(r3.stdout))

            # 没立场 → 不许给偏向结论，也不许印百分比（数字会被直接抄走）
            r4 = run([PY, im, "--rows", p_rows])
            o4 = r4.stdout or ""
            check("失衡画像：未指定立场时不给偏向结论，也不印百分比",
                  r4.returncode == 0 and "不做偏向判断" in o4
                  and "占 " not in o4 and "维度分布" not in o4, head_lines(o4))

            # 坏数据必须报错退出，不能静默给一份假结论
            p_badrows = os.path.join(work, "imb-bad.json")
            open(p_badrows, "w", encoding="utf-8").write('{"a": 1}')
            r5 = run([PY, im, "--rows", p_badrows, "--side", "甲方"])
            check("失衡画像：数据格式不对时报错退出（不静默给假结论）",
                  r5.returncode == 2, tail_line(r5.stdout))
    except Exception as e:
        check("失衡画像自检", False, repr(e))

    # --- 3.49 法规库失效巡检（引擎 13：库与已登记源是否仍一致）---
    print("\n[3.49] 法规库失效巡检（离线自检，不联网）")
    try:
        fp = os.path.join(HERE, "freshness-patrol.py")
        if not os.path.exists(fp):
            check("法规库失效巡检：脚本存在", False, "缺 scripts/freshness-patrol.py")
        else:
            check("法规库失效巡检：脚本存在", True, "scripts/freshness-patrol.py")
            r = run([PY, fp, "--self-test"])
            o = r.stdout or ""
            check("法规库失效巡检：离线自检全过（判据可分辨一致/换版，库内源可定位）",
                  r.returncode == 0
                  and "同一条文必判一致" in o
                  and "混入条目标题须判不一致" in o
                  and "库内 sources 均带 grp/enc" in o,
                  head_lines(o))
    except Exception as e:
        check("法规库失效巡检自检", False, repr(e))

    # --- 3.50 法规库交叉验证（引擎 14：库内条文多源比对是否可信）---
    print("\n[3.50] 法规库交叉验证（多源比对算法 + 库内置信）")
    try:
        xc = os.path.join(HERE, "legal-crosscheck.py")
        if not os.path.exists(xc):
            check("法规库交叉验证：模块存在", False, "缺 scripts/legal-crosscheck.py")
        else:
            check("法规库交叉验证：模块存在", True, "scripts/legal-crosscheck.py")
            import importlib.util as _ilu
            _sp = _ilu.spec_from_file_location("_xc_probe", xc)
            _xm = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_xm)
            a_same = "用人单位自用工之日起即与劳动者建立劳动关系。"
            a_diff = "经营者不得实施下列混淆行为，引人误认为是他人商品。"
            v_same = _xm.verdict([("A", a_same), ("B", a_same)])
            v_diff = _xm.verdict([("A", a_same), ("B", a_diff)])
            v_single = _xm.verdict([("A", a_same)])
            check("法规库交叉验证：两源全等判 multi-ok（已核）",
                  v_same["status"] == "multi-ok" and v_same["verified"] is True, str(v_same))
            check("法规库交叉验证：两源明显不同判 conflict（不猜谁对）",
                  v_diff["status"] == "conflict", str(v_diff))
            check("法规库交叉验证：单源判 single、verified=False（绝不伪装已核）",
                  v_single["status"] == "single" and v_single["verified"] is False, str(v_single))
            # 库内置信：下钻到条文层，凡有 status 字段者不得瞒报 single/conflict
            dbp = os.path.join(os.path.dirname(HERE), "core", "legal-articles.json")
            db = json.load(open(dbp, encoding="utf-8"))
            arts = []
            for _lw, _val in (db.get("laws") or {}).items():
                if isinstance(_val, dict):
                    arts.extend(_val.values())
                elif isinstance(_val, list):
                    arts.extend(_val)
            bad = [a.get("status") for a in arts
                   if isinstance(a, dict) and a.get("status") not in ("multi-ok", None)]
            check("法规库交叉验证：库内条文状态可信（无 single/conflict 瞒报）",
                  not bad, "异常状态: %s" % bad[:5])
    except Exception as e:
        check("法规库交叉验证自检", False, repr(e))

    # --- 3.51 法规检索引擎（引擎 16：检索 + 要件呈现，红线是「不下结论」）---
    print("\n[3.51] 法规检索引擎（要件呈现 + 红线：不下结论）")
    try:
        lp = os.path.join(HERE, "legal-search.py")
        if not os.path.exists(lp):
            check("法规检索：脚本存在", False, "缺 scripts/legal-search.py")
        else:
            check("法规检索：脚本存在", True, "scripts/legal-search.py")

            # (a) 精确条号命中，且要件是原文片段
            r = run([PY, lp, "--article", "民法典", "585"])
            o = r.stdout or ""
            check("法规检索：精确条号命中并给出原文",
                  r.returncode == 0 and "第五百八十五条" not in o and "违约金" in o,
                  head_lines(o))
            check("法规检索：要件逐条列出（非空即说明抽取生效）",
                  "适用要件" in o or "无可机械拆解" in o, head_lines(o))

            # (b) 未命中必须明说「未收录」，退出码 1
            r2 = run([PY, lp, "--article", "民法典", "99999"])
            o2 = r2.stdout or ""
            check("法规检索：库外条号明说未收录、不猜（退出码 1）",
                  r2.returncode == 1 and "未收录" in o2 and "不凭记忆" in o2,
                  head_lines(o2))

            # (c) 覆盖面必须自报（防止被当成法律全集）
            r3 = run([PY, lp, "--coverage"])
            o3 = r3.stdout or ""
            check("法规检索：主动报覆盖面（非法律全集）",
                  r3.returncode == 0 and "不是法律全集" in o3, head_lines(o3))

            # (d) 红线：脚本生成部分不得出现结论性用语
            #     法条原文里的「构成违约」是法条自己的话，须先剔除再扫
            import importlib.util as _ilu2
            _sp = _ilu2.spec_from_file_location("_ls_probe", lp)
            _ls = _ilu2.module_from_spec(_sp)
            _sp.loader.exec_module(_ls)
            _db = _ls.load_db()
            BANNED = ["建议你", "你应当", "你可以主张", "胜诉", "败诉", "胜算",
                      "本案应", "你有权要求", "结论是", "因此你", "判令", "法院会"]
            dirty = []
            for _q in ["竞业限制期限", "违约金", "个人信息处理", "格式条款",
                       "劳动合同解除", "担保"]:
                _res = _ls.search_in_db(_q, _db, limit=5)
                if not _res:
                    continue
                _md = _ls.render(_res, _q, _db)
                _scrub = _md
                for _r in _res:
                    _scrub = _scrub.replace(_r["text"], "")
                    _rq = _ls.split_requirements(_r["text"])
                    for _x in [_rq["scene"]] + _rq["reqs"] + _rq["excepts"]:
                        if _x:
                            _scrub = _scrub.replace(_x, "")
                _hit = [w for w in BANNED if w in _scrub]
                if _hit:
                    dirty.append((_q, _hit))
            check("法规检索：脚本生成部分无结论性用语（只讲要件不下结论）",
                  not dirty, "越界: %s" % dirty[:3])
    except Exception as e:
        check("法规检索引擎自检", False, repr(e))

    # --- 3.52 结构化引擎（引擎 3：字段树 + 原文锚点）---
    print("\n[3.52] 结构化引擎（字段树 + 原文锚点）")
    try:
        sp2 = os.path.join(HERE, "structure.py")
        if not os.path.exists(sp2):
            check("结构化：脚本存在", False, "缺 scripts/structure.py")
        else:
            check("结构化：脚本存在", True, "scripts/structure.py")
            sample = ("甲方：北京某某科技有限公司\n乙方：上海某某贸易有限公司\n"
                      "第二条 标的：服务器设备一批\n"
                      "第三条 甲方应于2026年1月1日前支付货款100万元。\n"
                      "第四条 乙方应于收到货款后30日内交付。\n"
                      "第五条 违约责任：按合同总价20%支付违约金。\n"
                      "第六条 其他事项另行约定。")
            r = run([PY, sp2, "--text", sample])
            o = r.stdout or ""
            check("结构化：当事人/金额/日期/期限/标的均抽出",
                  r.returncode == 0 and "北京某某科技有限公司" in o
                  and "100万元" in o and "2026年1月1日" in o
                  and "30日内" in o and "服务器设备一批" in o, head_lines(o))
            check("结构化：比例型金额单独识别（合同总价20%）",
                  "比例金额" in o and "合同总价20%" in o, head_lines(o))
            check("结构化：「另行约定」标为另约而非漏抽",
                  "另约" in o, head_lines(o))
            check("结构化：每个取值都带原文锚点",
                  o.count("…") >= 6, "锚点数 %d" % o.count("…"))
            # 抽不到必须明说未识别，不许编
            r2 = run([PY, sp2, "--text", "本合同未尽事宜由双方协商解决。"])
            o2 = r2.stdout or ""
            check("结构化：抽不到即标「未识别」，不猜测",
                  "未识别" in o2 and "不猜测" in o2, head_lines(o2))
    except Exception as e:
        check("结构化引擎自检", False, repr(e))

    # --- 3.53 公文格式引擎（引擎 10：GB/T 9704 体检）---
    print("\n[3.53] 公文格式引擎（GB/T 9704 体检）")
    try:
        gp = os.path.join(HERE, "gb9704.py")
        if not os.path.exists(gp):
            check("公文格式：脚本存在", False, "缺 scripts/gb9704.py")
        else:
            check("公文格式：脚本存在", True, "scripts/gb9704.py")
            r = run([PY, gp, "--rules"])
            o = r.stdout or ""
            check("公文格式：覆盖项清单可读，且标注可机测与否",
                  r.returncode == 0 and "可机器判定" in o and "否" in o, head_lines(o))

            # 造两份 docx：一份合标、一份故意不合规，验证判据方向不反
            try:
                from docx import Document
                from docx.shared import Pt, Mm
                from docx.enum.text import WD_ALIGN_PARAGRAPH
                import tempfile as _tf
                _td = _tf.mkdtemp(prefix="gb9704-")
                good = os.path.join(_td, "good.docx")
                d = Document()
                s = d.sections[0]
                s.page_width, s.page_height = Mm(210), Mm(297)
                s.top_margin, s.bottom_margin = Mm(37), Mm(35)
                s.left_margin, s.right_margin = Mm(28), Mm(26)
                p = d.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run("关于开展检查工作的通知").font.size = Pt(22)
                p2 = d.add_paragraph()
                p2.add_run("各单位应于本月底前完成自查。").font.size = Pt(16)
                d.save(good)

                bad = os.path.join(_td, "bad.docx")
                d2 = Document()
                s2 = d2.sections[0]
                s2.top_margin, s2.left_margin = Mm(25), Mm(20)
                p3 = d2.add_paragraph()
                p3.add_run("标题").font.size = Pt(14)
                d2.save(bad)

                rg = run([PY, gp, "--check", good])
                rb = run([PY, gp, "--check", bad])
                check("公文格式：合标件判通过（退出码 0）",
                      rg.returncode == 0 and "不符合 0 项" in (rg.stdout or ""),
                      head_lines(rg.stdout))
                check("公文格式：不合规件报不符合并给偏差值（退出码 1）",
                      rb.returncode == 1 and "差" in (rb.stdout or "")
                      and "不符合" in (rb.stdout or ""), head_lines(rb.stdout))
                check("公文格式：算不出的项明标「需人工」，不冒充机测",
                      "需人工" in (rg.stdout or ""), head_lines(rg.stdout))

                # 接入核验引擎第四维：给 docx 应真跑，不给应如实标未启用
                vp = os.path.join(HERE, "verify.py")
                v1 = run([PY, vp, "--text", "测试", "--only", "fmt"])
                v2 = run([PY, vp, "--text", "测试", "--only", "fmt", "--docx", good])
                check("公文格式：未给 docx 时核验引擎如实标「未启用」",
                      "未启用" in (v1.stdout or ""), head_lines(v1.stdout))
                check("公文格式：给了 docx 后核验引擎第四维真跑（不再是占位）",
                      "GB/T 9704 版式" in (v2.stdout or "")
                      and "未启用" not in (v2.stdout or ""), head_lines(v2.stdout))
                import shutil as _sh
                _sh.rmtree(_td, ignore_errors=True)
            except ImportError:
                skip("公文格式：docx 体检（需 python-docx）")
    except Exception as e:
        check("公文格式引擎自检", False, repr(e))

    # --- 3.54 法规汇编引擎（引擎 17：编册，红线是「只搬运不撰写」）---
    print("\n[3.54] 法规汇编引擎（编册 + 红线：只搬运不撰写）")
    try:
        cp2 = os.path.join(HERE, "legal-compile.py")
        if not os.path.exists(cp2):
            check("法规汇编：脚本存在", False, "缺 scripts/legal-compile.py")
        else:
            check("法规汇编：脚本存在", True, "scripts/legal-compile.py")
            import tempfile as _tf2
            _ctd = _tf2.mkdtemp(prefix="compile-")

            # (a) 按主题汇编：必须成册——目录、正文、索引、附录齐备
            out1 = os.path.join(_ctd, "a.md")
            r = run([PY, cp2, "--ask", "竞业限制", "--title", "竞业限制法规汇编",
                     "--out", out1])
            md = ""
            if os.path.exists(out1):
                md = open(out1, encoding="utf-8").read()
            check("法规汇编：按主题成册，体例五段齐备（说明/目录/条文/索引/附录）",
                  r.returncode == 0 and all(k in md for k in
                                            ("一、编制说明", "二、目录", "三、条文",
                                             "四、条号索引", "五、附录")),
                  head_lines(md))
            check("法规汇编：每部法带版本与施行日（时效可核）",
                  "版本" in md and "施行" in md, head_lines(md))
            check("法规汇编：自报覆盖面，明说非法律全集",
                  "不是法律全集" in md, head_lines(md))

            # (b) 逐条指定：跨法、条号升序、区间紧凑
            out2 = os.path.join(_ctd, "b.md")
            r2 = run([PY, cp2, "--articles", "民法典:585,577 劳动合同法:23",
                      "--title", "跨法汇编", "--out", out2])
            md2 = open(out2, encoding="utf-8").read() if os.path.exists(out2) else ""
            check("法规汇编：逐条指定可跨法成册且条号升序",
                  r2.returncode == 0 and md2.index("第577条") < md2.index("第585条")
                  and "劳动合同法" in md2, head_lines(md2))

            # (c) 库外条号：明说未收录、列名、不补不替，退出码 1（全未收录不产空册）
            r3 = run([PY, cp2, "--articles", "民法典:99999", "--title", "空册",
                      "--out", os.path.join(_ctd, "c.md")])
            o3 = (r3.stdout or "") + (r3.stderr or "")
            check("法规汇编：库外条号明说未收录且不产空册（退出码 1）",
                  r3.returncode == 1 and "未收录" in o3 and "不凭记忆" in o3,
                  head_lines(o3))

            # (d) 部分未收录：命中照录、缺失逐条列名
            out4 = os.path.join(_ctd, "d.md")
            run([PY, cp2, "--articles", "民法典:585,99999", "--title", "部分",
                 "--out", out4])
            md4 = open(out4, encoding="utf-8").read() if os.path.exists(out4) else ""
            check("法规汇编：部分未收录时命中照录、缺失项在附录逐条列名",
                  "第585条" in md4 and "5.2 未收录" in md4 and "第99999条" in md4,
                  head_lines(md4))

            # (e) 红线：汇编全文不得出现结论性用语
            #     与 3.51 同理——法条原文里的话是法条自己的，先剔除再扫
            import importlib.util as _ilu3
            _sp3 = _ilu3.spec_from_file_location("_lc_probe", cp2)
            _lc = _ilu3.module_from_spec(_sp3)
            _sp3.loader.exec_module(_lc)
            _cdb = _lc.load_db()
            BANNED2 = ["建议", "评析", "我们认为", "本案", "胜诉", "败诉",
                       "风险等级", "综上", "因此可", "结论是", "应予认定",
                       "应认定", "构成违约", "属于违法", "宜认定", "不宜"]
            _pk, _ab = _lc.collect(_cdb, ask="个人信息", limit=20)
            _mdx, _st = _lc.build(_cdb, _pk, _ab, "红线自检", ask="个人信息")
            _scrub2 = _mdx
            for _r in _pk:
                _scrub2 = _scrub2.replace(_r["text"], "")
                _rq2 = _lc.ls.split_requirements(_r["text"])
                for _x in [_rq2["scene"]] + _rq2["reqs"] + _rq2["excepts"]:
                    if _x:
                        _scrub2 = _scrub2.replace(_x, "")
            _hit2 = [w for w in BANNED2 if w in _scrub2]
            check("法规汇编：脚本生成部分无结论性用语（只搬运不撰写）",
                  not _hit2 and _st["articles"] > 0, "越界: %s" % _hit2)

            # (f) docx 输出不得漏出 Markdown 标记
            try:
                out5 = os.path.join(_ctd, "e.docx")
                r5 = run([PY, cp2, "--ask", "竞业限制", "--title", "汇编 Word 版",
                          "--format", "docx", "--out", out5])
                if r5.returncode == 0 and os.path.exists(out5):
                    from docx import Document as _Doc
                    _d5 = _Doc(out5)
                    _ps5 = [p.text for p in _d5.paragraphs if p.text.strip()]
                    _leak = [x for x in _ps5 if "**" in x or "`" in x or "<sub>" in x]
                    check("法规汇编：Word 版不漏 Markdown 标记且正文非空",
                          not _leak and len(_ps5) > 5,
                          "残留 %d 处 / 段落 %d" % (len(_leak), len(_ps5)))
                else:
                    check("法规汇编：Word 版不漏 Markdown 标记且正文非空",
                          False, head_lines(r5.stderr))
            except ImportError:
                skip("法规汇编：Word 版（需 python-docx）")

            import shutil as _sh2
            _sh2.rmtree(_ctd, ignore_errors=True)
    except Exception as e:
        check("法规汇编引擎自检", False, repr(e))

    # --- 3.55 品牌头标（横幅／图标／技能卡片：一次出齐 5 张，卡片不许成孤儿）---
    # 为什么单列一段：skill-card.png 的生成器曾是临时脚本 make-card.py（从未入 git、用完即丢），
    # 升级后没人记得怎么重刷，头标守卫两次拦下「第 5 张图仍是旧版本」（v3.25.1、v3.25.7）。
    # v3.25.7 把卡片并入 make-header.py，这里补上独立用例，防它再退化回孤儿。
    print("\n[3.55] 品牌头标（5 张，含技能卡片）")
    try:
        import re as _re3
        with open(os.path.join(HERE, "..", "SKILL.md"), encoding="utf-8-sig") as _sf:
            _mv = _re3.search(r"(?m)^version:\s*([\d.]+)\s*$", _sf.read(4000))
        _ver = _mv.group(1) if _mv else ""
        _hd = os.path.join(work, "hdr")
        _lst = run([PY, os.path.join(HERE, "make-header.py"), "--list"])
        _items = [x.strip() for x in (_lst.stdout or "").splitlines() if x.strip().endswith(".png")]
        check("品牌头标：--list 列出 5 个产物且含 skill-card.png（卡片不许从产出清单里消失）",
              len(_items) == 5 and any("skill-card.png" in x for x in _items),
              "%d 项：%s" % (len(_items), "、".join(os.path.basename(x) for x in _items)))
        run([PY, os.path.join(HERE, "make-header.py"), "--out", _hd])
        _card = os.path.join(_hd, "skill-card.png")
        _ok, _detail, _spread = False, "卡片未生成", -1
        if os.path.exists(_card):
            from PIL import Image as _Im3
            _im3 = _Im3.open(_card)
            _gray = _im3.convert("L")
            _lo, _hi = _gray.getextrema()
            _spread = _hi - _lo
            _ok = (_im3.format == "PNG" and _im3.size == (810, 1080)
                   and _im3.info.get("Skill-Version") == "v" + _ver)
            _detail = "%s %s 版本戳=%r（期望 v%s）" % (
                _im3.format, _im3.size, _im3.info.get("Skill-Version"), _ver)
        check("品牌头标：技能卡片实跑生成（PNG 810×1080 竖版，版本戳＝当前版本）", _ok, _detail)
        # 版本戳必须是**真参数**而非写死：换一个版本串重出，元数据须跟着变
        _hd2 = os.path.join(work, "hdr-v0")
        run([PY, os.path.join(HERE, "make-header.py"), "--out", _hd2, "--version", "v0.0.0"])
        _c2 = os.path.join(_hd2, "skill-card.png")
        _v2 = None
        if os.path.exists(_c2):
            from PIL import Image as _Im4
            _v2 = _Im4.open(_c2).info.get("Skill-Version")
        check("品牌头标：卡片版本戳随 --version 变化（烧的是参数，不是写死值）",
              _v2 == "v0.0.0", "实测 %r" % (_v2,))
        # 非空白：卡片由多色区块与文字构成，灰度极差过小＝只出了一张底色
        check("品牌头标：卡片非空白（灰度极差 > 60，防生成一张纯色图）",
              _spread > 60, "灰度极差 %d" % _spread)
    except Exception as e:
        check("品牌头标自检", False, repr(e))

    # --- 3.56 出包裁剪（version.json 只带 latest，history 不随技能分发）---
    # 决策依据：history 是发布侧演进记录，与 VERSION.md 重复维护必分家（v3.25.7 实测断档）；
    # 使用者只需 latest。这里钉住裁剪函数与出包自检两头，防有人「顺手把 history 加回来」。
    print("\n[3.56] 出包裁剪（包内 version.json 只带 latest）")
    try:
        import importlib.util as _iu3
        _sp3 = _iu3.spec_from_file_location("_pk3", os.path.join(HERE, "pack.py"))
        _pk3 = _iu3.module_from_spec(_sp3)
        _sp3.loader.exec_module(_pk3)
        _raw = '{"latest":{"version":"v1.0.0"},"history":[{"version":"v0.9.0"}]}'
        _cut = _pk3.strip_version_history(_raw)
        _noop = _pk3.strip_version_history('{"latest":{"version":"v1.0.0"}}')
        check("出包：version.json 裁掉 history 且保留 latest；无 history 时不动（返回 None）",
              _cut is not None and "history" not in _cut and "v1.0.0" in _cut and _noop is None,
              (_cut or "").replace("\n", " ")[:90])
        _src = open(os.path.join(HERE, "pack.py"), encoding="utf-8").read()
        check("出包：自检函数含「包内不得含 history」判据（裁剪失效能在出包时拦下）",
              "仍含 history" in _src and "strip_history" in _src, "")
    except Exception as e:
        check("出包裁剪自检", False, repr(e))

    # --- 3.57 分包副本自证（history 不进包，但副本要能说清沿革在哪）---
    # 背景（千问办公实测）：pack.py 从 v3.25.8 起按设计剥离 history，而 check.py 要求
    # history 必须存在 → 同一份 check.py，开发源 0 错、装好的副本必红，四个版本都如此，
    # 只是此前从没人在**产物**上跑过门禁。修法是让包自带 `_分发副本: true` 标记自证身份。
    # 这里做真副本双向验证：有标记＝分发态须过；无标记且无 history＝开发源须报错。
    print("\n[3.57] 分包副本自证（历史版本信息不对外提供）")
    _tmp4 = None
    try:
        import importlib.util as _iu4, shutil as _sh4, tempfile as _tf4
        _sp4 = _iu4.spec_from_file_location("_pk4", os.path.join(HERE, "pack.py"))
        _pk4 = _iu4.module_from_spec(_sp4)
        _sp4.loader.exec_module(_pk4)
        _cut2 = json.loads(_pk4.strip_version_history(
            '{"latest":{"version":"v1.0.0"},"history":[{"version":"v0.9.0"}]}'))
        check("出包：裁剪后带 `_分发副本: true` 标记（副本能自证「不提供历史版本信息」）",
              _cut2.get("_分发副本") is True and "history" not in _cut2,
              json.dumps(_cut2, ensure_ascii=False)[:90])
        _root4 = os.path.dirname(HERE)
        # 本目录的形态决定期望方向：**开发源**（有 history）→ 源侧断言须放行；
        # **分发副本**（实例已按发布链转形态，无 history）→ 源侧断言须拒。
        # 两个方向都验，才证明这条断言真在拦，而不是恒返回空表（12.5.4 假绿）。
        try:
            _is_dist4 = (json.load(open(os.path.join(_root4, "version.json"),
                                        encoding="utf-8")).get("_分发副本") is True)
        except Exception:
            _is_dist4 = False
        _srcbad = _pk4.verify_source_manifest(_root4)
        if _is_dist4:
            check("出包：分发副本（无 history）当出包源时源侧断言须拒——证明它真在拦",
                  _srcbad != [], "未拦（假绿）：%s" % (str(_srcbad)[:80]))
        else:
            check("出包：源侧断言认「源里有 history」为通过（包内仍会自动剥离）",
                  _srcbad == [], str(_srcbad)[:90])
        check("出包：FULL_FILES 不含 VERSION.md（沿革不随包）",
              "VERSION.md" not in _pk4.FULL_FILES, str(_pk4.FULL_FILES)[:70])
        _tmp4 = _tf4.mkdtemp(prefix="dcr_dist_")
        _dst4 = os.path.join(_tmp4, "doc-compliance-review")
        _sh4.copytree(_root4, _dst4,
                      ignore=_sh4.ignore_patterns("__pycache__", "_发布包", ".git"))
        # 模拟真实分发包：沿革不随包，先把 VERSION.md 拿掉
        # 源侧指纹台账自洽（v3.26.3）：台账随包分发，陈旧就会随包发出——装包的人
        # 跑 check.py 会先看到一条"脚本已被修改"的警告，而退出码是 0（假绿的经典形态）。
        _if_ok = _pk4.verify_integrity_fresh(_root4)
        check("出包：源侧台账与脚本自洽时放行（陈旧台账会随包发出）",
              _if_ok == [], str(_if_ok)[:90])
        _dirty4 = os.path.join(_dst4, "scripts", "guard.py")
        _bak4 = open(_dirty4, encoding="utf-8").read()
        open(_dirty4, "a", encoding="utf-8").write("\n# 冒烟注入：改了脚本但不同步重签台账\n")
        _if_bad = _pk4.verify_integrity_fresh(_dst4)
        open(_dirty4, "w", encoding="utf-8").write(_bak4)
        check("出包：脚本改了却未重签台账须拒包——证明这条断言真在拦（不是恒返空表）",
              _if_bad != [], "返回：%s" % (str(_if_bad)[:80]))
        _vm4 = os.path.join(_dst4, "VERSION.md")
        _had_vm = os.path.exists(_vm4)
        if _had_vm:
            os.remove(_vm4)
        _vj4 = os.path.join(_dst4, "version.json")
        _d4 = json.loads(open(_vj4, encoding="utf-8").read())
        _d4.pop("history", None)
        _d4["_分发副本"] = True
        open(_vj4, "w", encoding="utf-8").write(
            json.dumps(_d4, ensure_ascii=False, indent=2) + "\n")
        _r4 = run([PY, os.path.join(_dst4, "scripts", "check.py")])
        check("分包副本（无 history／无 VERSION.md／有标记）跑 check.py 须 0 错"
              "——千问办公「装完即红」的回归",
              _r4.returncode == 0,
              tail_line(_r4.stdout) + " " + tail_line(_r4.stderr))
        # 反向：把沿革塞回分发包 → 必须报错（「沿革不给看」不能只靠出包时自觉）。
        # 分发副本里没有 VERSION.md 可拷，就写一个最简的顶上——判据是「包里不许出现这个文件名」，
        # 与内容无关。**不得因"没有源文件"就跳过本项**，那会让两档项数不守恒。
        if _had_vm:
            _sh4.copyfile(os.path.join(_root4, "VERSION.md"), _vm4)
        else:
            open(_vm4, "w", encoding="utf-8").write("# 版本沿革（测试用空壳）\n")
        _r6 = run([PY, os.path.join(_dst4, "scripts", "check.py")])
        check("分发包里塞回 VERSION.md 须报错——沿革不随包不能只靠自觉",
              _r6.returncode != 0 and "VERSION.md（版本沿革）" in (_r6.stdout or ""),
              tail_line(_r6.stdout))
        os.remove(_vm4)
        _d4.pop("_分发副本", None)
        open(_vj4, "w", encoding="utf-8").write(
            json.dumps(_d4, ensure_ascii=False, indent=2) + "\n")
        # 还原成「开发源」形态：VERSION.md 必须在（源侧沿革是维护真源）
        if _had_vm:
            _sh4.copyfile(os.path.join(_root4, "VERSION.md"), _vm4)
        _r5 = run([PY, os.path.join(_dst4, "scripts", "check.py")])
        check("开发源（无 history 且无标记）跑 check.py 须报错"
              "——防有人把源的 history 删了还一路绿",
              _r5.returncode != 0 and "缺 history" in (_r5.stdout or ""),
              tail_line(_r5.stdout))
    except Exception as e:
        check("分包副本自证", False, repr(e))
    finally:
        if _tmp4:
            import shutil as _sh5
            _sh5.rmtree(_tmp4, ignore_errors=True)

    # --- 3.58 编码链（非 UTF-8 环境下门禁不得误诊）---
    print("\n[3.58] 编码链（中文 Windows／GBK 环境）")
    try:
        # 千问办公实测（v3.26.2）：装好的副本在 GBK 控制台下跑 check.py 报两条 [E]——
        # 「条号对位自检输出无法解析（脚本可能崩了）」与「巡检自检缺少关键判据项，
        # 判据被删或改名」。两条**都是误诊**：子脚本没自钉 stdout，按 GBK 写出，
        # 父侧 UTF-8 解出 U+FFFD，三条判据一条都匹配不上 → 被说成「判据被删」。
        # 开发侧（Linux 全 UTF-8）永远复现不了，这是「在我机器上是好的」的又一形态。
        # 这里用 PYTHONIOENCODING=gbk 精确复现该环境，要求 0 错且输出无替换符。
        _env_gbk = dict(os.environ, PYTHONIOENCODING="gbk")
        _rg = subprocess.run([PY, os.path.join(HERE, "check.py")], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             env=_env_gbk, timeout=240)
        _og = (_rg.stdout or "") + (_rg.stderr or "")
        check("GBK 环境跑 check.py 须 0 错且无乱码——复现千问「判据被删」误报",
              _rg.returncode == 0 and "\ufffd" not in _og,
              tail_line(_og))
        _nopin = []
        for _fn in sorted(os.listdir(HERE)):
            if not _fn.endswith(".py"):
                continue
            with open(os.path.join(HERE, _fn), encoding="utf-8", errors="replace") as _fh:
                if "stdout.reconfigure" not in _fh.read():
                    _nopin.append(_fn)
        check("全部脚本自钉 stdout 编码（被 spawn 时不会按 locale 写出）",
              not _nopin, "、".join(_nopin))
    except Exception as e:
        check("编码链", False, repr(e))

    # --- 3.59 产物验收（验交付物，不验产地）---
    # 背景：发布链此前只验开发源与运行实例，两者都是"自家的地盘"，产物只是被**假定**与源一致。
    # 这个假定一直成立到它不成立为止——「装好的副本跑门禁必红」连存四个版本无人知，正是因为
    # **从没人在产物上跑过**。这一节改真出包、真解包、真跑，不再用"拷目录模拟产物"。
    print("\n[3.59] 产物验收（解包即验，不用目录模拟）")
    _tmp6 = None
    try:
        import importlib.util as _iu6, tempfile as _tf6, contextlib as _ctx6, io as _io6
        _root6 = os.path.dirname(HERE)
        # 出包只能从**开发源**出：分发副本没有 history（沿革不外泄），源侧断言会正当地拒包。
        # 故在实例（分发态）里跑冒烟时这两项记 SKIP 而非 FAIL——这不是缺陷，是设计。
        _is_dist6 = False
        try:
            _is_dist6 = (json.load(open(os.path.join(_root6, "version.json"),
                                        encoding="utf-8")).get("_分发副本") is True)
        except Exception:
            pass
        if _is_dist6:
            skip("产物验收：真出包（分发副本无沿革，不能当出包源——出包只在开发源做）")
            skip("产物验收：源有沿革而产物没有（同上，需出包源）")
        else:
            _tmp6 = _tf6.mkdtemp(prefix="dcr_packopt_")
            _sp6 = _iu6.spec_from_file_location("_pk6", os.path.join(HERE, "pack.py"))
            _pk6 = _iu6.module_from_spec(_sp6)
            _sp6.loader.exec_module(_pk6)
            _log6 = _io6.StringIO()
            with _ctx6.redirect_stdout(_log6):      # 出包日志不进冒烟输出，失败时再取尾行
                # tag 显式传（不靠默认值）：默认值写死过一次 "v3.0.0"，打出错版本的包是静默的
                _ok6 = _pk6.build(_root6, _tmp6, tag=_pk6.read_skill_version(_root6), fmt="zip")
            _z6 = [os.path.join(_tmp6, f) for f in sorted(os.listdir(_tmp6))
                   if f.endswith(".zip")]
            _tail6 = (_log6.getvalue().strip().splitlines() or [""])[-1]
            check("产物验收：真出包须通过（出包末尾自动解包、在副本里跑门禁）",
                  bool(_ok6) and len(_z6) == 1, _tail6[:110])
            if _z6:
                _sp7 = _iu6.spec_from_file_location("_vd6", os.path.join(HERE, "verify-dist.py"))
                _vd6 = _iu6.module_from_spec(_sp7)
                _sp7.loader.exec_module(_vd6)
                _e6 = _vd6.verify_artifact(_z6[0], gate=False, quiet=True)
                _srcvm = os.path.exists(os.path.join(_root6, "VERSION.md"))
                check("产物验收：源里有 VERSION.md／history，产物里都没有（剥离在产物上可验）",
                      not _e6 and _srcvm, "源有 VERSION.md=%s；产物问题 %s" % (_srcvm, _e6[:2]))
    except Exception as e:
        check("产物验收", False, repr(e))
    finally:
        if _tmp6:
            shutil.rmtree(_tmp6, ignore_errors=True)

    print("\n[3.59b] 产物验收判据自测（变异注入）")
    try:
        _r7 = run([PY, os.path.join(HERE, "verify-dist.py"), "--selftest"])
        check("产物验收判据有区分度：七类注入逐项命中、对照组零误报（不是「跑了就绿」）",
              _r7.returncode == 0 and "全部通过" in (_r7.stdout or ""), tail_line(_r7.stdout))
    except Exception as e:
        check("产物验收判据自测", False, repr(e))

    print("\n[3.60] 交互降级（清单一律无伪控件符号 · 选不中即逐条问）")
    _skp = os.path.join(os.path.dirname(HERE), "SKILL.md")
    _skbak = None
    try:
        _skbak = open(_skp, "rb").read()
        _skt = _skbak.decode("utf-8")
        check("SKILL.md 有「交互失败降级·逐条提问」条款，且给了可直接照做的版式",
              "交互失败降级" in _skt and "逐条" in _skt and "（共 11 题）" in _skt, "")
        # 负向注入：把伪控件符号塞回清单 → **不自己造判据**，直接看门禁输不输出。
        # 这一项验的是「那条判据有区分度」，不是重写一遍判据（13.2 边界：不与通用门禁重复造判据）。
        _skbad = _skt.replace("基础层（默认 1，不可取消）：1 通用版 ｜ 2 私有库",
                              "基础层（默认 1，不可取消）：☐1 通用版  ☐2 私有库", 1)
        if _skbad == _skt:
            check("负向注入的锚点仍在（清单基础层那一行未被改写过）", False,
                  "锚点丢失，注入无效")
        else:
            open(_skp, "wb").write(_skbad.encode("utf-8"))
            _r8 = run([PY, os.path.join(HERE, "check.py")])
            check("把 ☐ 塞回清单，门禁须报错——证明「无伪控件符号」是真在查（不是恒绿）",
                  _r8.returncode != 0 and "伪控件" in (_r8.stdout or ""),
                  tail_line(_r8.stdout))
    except Exception as e:
        check("交互降级", False, repr(e))
    finally:
        if _skbak is not None:
            open(_skp, "wb").write(_skbak)      # 无论成败都按字节还原，正式文件不留污染

    print("\n[3.61] 提示词版正向断言（默认项不得含做不出的类型 · 行业须 9 个）")
    _pvp = os.path.join(os.path.dirname(HERE), "文档合规审查助手AI合同提示词版.md")
    _pvbak = None
    try:
        _pvbak = open(_pvp, "rb").read()
        _pvt = _pvbak.decode("utf-8")
        # 逐条注入、逐条还原：两次注入不叠加，且**只读门禁输出**，不自己重写判据（13.2 边界）。
        # 这两条正好对应两类病害：①「默认要求做一件做不到的事」（逻辑不自洽）；
        # ②「库数少了一个」（数字口径漂移）——都是文案改一半就复发的。
        for _tag, _old, _new, _kw in [
            ("默认交付物含本版做不出的第 4 类", "不选则默认出 1、2", "不选则默认出 1、2、4",
             "默认交付物含本版做不出的"),
            ("行业清单缺「建筑地产」", "建筑地产", "其他行业", "缺「建筑地产」"),
        ]:
            if _old not in _pvt:
                check("提示词版注入锚点仍在（%s）" % _tag, False, "锚点丢失，注入无效")
                continue
            open(_pvp, "wb").write(_pvt.replace(_old, _new).encode("utf-8"))
            _r9 = run([PY, os.path.join(HERE, "check.py")])
            open(_pvp, "wb").write(_pvbak)
            check("注入[%s] 门禁须报错——证明这条正向断言有区分度（不是恒绿）" % _tag,
                  _r9.returncode != 0 and _kw in (_r9.stdout or ""),
                  tail_line(_r9.stdout))
    except Exception as e:
        check("提示词版正向断言", False, repr(e))
    finally:
        if _pvbak is not None:
            open(_pvp, "wb").write(_pvbak)      # 无论成败都按字节还原，正式文件不留污染

    print("\n[3.62] 功能菜单完整性（引擎在用，就必须在菜单里点得到）")
    _skp = os.path.join(os.path.dirname(HERE), "SKILL.md")
    _skbak = None
    try:
        _skbak = open(_skp, "rb").read()
        _skt = _skbak.decode("utf-8")
        _mm = re.search(r"【Q1 · 本技能功能 · 请单选[^\n]*\n(.*?)\n```", _skt, re.S)
        _blk = _mm.group(1) if _mm else ""
        _nums = [int(x) for x in re.findall(r"(?m)^\s*(\d+)\.\s", _blk)]
        # 编号连续是硬要求：跳号的话用户回「12」会打空，而菜单看上去毫无异样
        check("功能菜单 20 项、编号 0–19 连续",
              len(_nums) == 20 and _nums == list(range(20)),
              "实有 %d 项：%s" % (len(_nums), _nums))
        # 七类曾漏掉（或从未有过入口）的能力必须在场——正面断言，缺一项即红
        _need = ["格式转换", "OCR", "结构化", "法规检索", "法规汇编", "引用核验", "公文写作"]
        _lost = [k for k in _need if k not in _blk]
        check("菜单含曾漏掉的七类能力入口（格式转换/OCR/结构化/法规检索/汇编/引用核验/公文写作）",
              not _lost, "缺：%s" % "、".join(_lost) if _lost else "七类齐备")
        # 区分度：把「法规检索」那一行删掉，门禁必须报错——否则上面两条只是恒绿的装饰
        _line = re.search(r"(?m)^\s*\d+\.\s*法规检索.*\n", _blk)
        if _line:
            open(_skp, "wb").write(
                _skt.replace(_blk, _blk.replace(_line.group(0), "", 1), 1).encode("utf-8"))
            _r62 = run([PY, os.path.join(HERE, "check.py")])
            open(_skp, "wb").write(_skbak)
            check("注入[菜单删「法规检索」] 门禁须报错——证明这条断言有区分度",
                  _r62.returncode != 0 and "法规检索" in (_r62.stdout or ""),
                  tail_line(_r62.stdout))
        else:
            check("注入锚点：菜单里的「法规检索」行仍在", False, "锚点丢失，注入无效")
    except Exception as e:
        check("功能菜单完整性", False, repr(e))
    finally:
        if _skbak is not None:
            open(_skp, "wb").write(_skbak)      # 无论成败按字节还原，正式文件不留污染

    print("\n[3.63] frontmatter 平台必填字段（缺一个，平台就整包拒收）")
    # 背景（这条守卫的来历，别删）：v3.26.5 因「两段中文长文重复」把 `description_zh`
    # 整个删了，还在门禁里写了**负向断言**防回潮——结果是把包做成了平台必然拒收的包：
    # 开放平台字段表里 `description_zh` 是必填，缺失时解析器报
    # 「缺少 Skill 中文描述(description_zh)」。本地门禁全绿，因为它只认我们自己的断言。
    # 真病是「两个字段写成同一份长文」，修法是各归其位，不是删掉一个。
    _skp2 = os.path.join(os.path.dirname(HERE), "SKILL.md")
    _bak2 = None
    try:
        _bak2 = open(_skp2, "rb").read()
        _txt2 = _bak2.decode("utf-8")
        _fm2 = re.search(r"^---\n(.*?)\n---", _txt2, re.S)
        _fmb2 = _fm2.group(1) if _fm2 else ""

        def _val(k):
            m = re.search(r"^%s:\s*(.*)$" % re.escape(k), _fmb2, re.M)
            if not m:
                return None
            v = m.group(1).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v

        # 平台字段表里的必填项（不含 allowed-tools / examples_* 这两组选填）
        # 2026-10-30 起 `slug` 也是必填：`name` 改承担中文显示名，ASCII 标识独立成字段
        _must = ["name", "slug", "display_name", "display_name_en", "description",
                 "description_zh", "description_en", "version", "author"]
        _gone = [k for k in _must if _val(k) is None]
        check("frontmatter 平台必填 9 字段齐备（name/slug/两个展示名/三个描述/version/author）",
              not _gone, "缺：%s" % "、".join(_gone) if _gone else "九项齐备")

        # 命名分工：slug 必须是 kebab-case；name 可中文（允许不强制），只需无文件名非法字符
        _n2, _s2 = _val("name") or "", _val("slug") or ""
        check("slug 是 kebab-case（小写＋单连字符），name 非空且无文件名非法字符",
              bool(_n2) and not re.search(r'[\\/:*?"<>|]', _n2)
              and bool(re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", _s2)),
              "name=%s｜slug=%s" % (_n2, _s2))

        # 区分度注入一：slug 写成中文，门禁必须报（kebab-case 断言真的在跑）
        open(_skp2, "wb").write(
            re.sub(r"(?m)^slug:.*$", "slug: 文档合规审查", _txt2).encode("utf-8"))
        _rslug = run([PY, os.path.join(HERE, "check.py")])
        check("slug 写成中文 → 门禁报「不合 kebab-case」",
              _rslug.returncode != 0 and "kebab-case" in _rslug.stdout,
              "退出码 %d" % _rslug.returncode)

        # 区分度注入二：slug 用下划线——看着像 slug，其实不合 kebab-case（kebab 不是「随手一个 ASCII」）
        open(_skp2, "wb").write(
            re.sub(r"(?m)^slug:.*$", "slug: doc_compliance_review", _txt2).encode("utf-8"))
        _rslug2 = run([PY, os.path.join(HERE, "check.py")])
        check("slug 用下划线 → 门禁报「不合 kebab-case」（区分 snake_case 与 kebab-case）",
              _rslug2.returncode != 0 and "kebab-case" in _rslug2.stdout,
              "退出码 %d" % _rslug2.returncode)

        # 区分度注入三：name 含半角冒号——最阴的一条，_safe_name 会静默剔除它
        open(_skp2, "wb").write(
            re.sub(r"(?m)^name:.*$", "name: 文档:合规审查", _txt2).encode("utf-8"))
        _rname = run([PY, os.path.join(HERE, "check.py")])
        check("name 含半角冒号 → 门禁报「文件名非法字符」（_safe_name 会静默剔除）",
              _rname.returncode != 0 and "文件名非法字符" in _rname.stdout,
              "退出码 %d" % _rname.returncode)

        _zh2, _en2 = _val("description_zh") or "", _val("description_en") or ""
        check("description_zh 是简短介绍（≤200 字），不是触发长文的复制品",
              _zh2 and len(_zh2) <= 200, "当前 %d 字" % len(_zh2))
        check("description_en 是英文简介（≤700 字符），不是 description 的译本",
              _en2 and len(_en2) <= 700, "当前 %d 字符" % len(_en2))

        # 区分度注入一：删掉 description_zh，门禁必须报
        open(_skp2, "wb").write(re.sub(r"(?m)^description_zh:.*\n", "", _txt2).encode("utf-8"))
        _r63 = run([PY, os.path.join(HERE, "check.py")])
        open(_skp2, "wb").write(_bak2)
        check("注入[删 description_zh] 门禁须报「缺 description_zh」——"
              "这正是 v3.26.5 犯过的错，不能再静默通过",
              _r63.returncode != 0 and "description_zh" in (_r63.stdout or ""),
              tail_line(_r63.stdout))

        # 区分度注入二：把 description_zh 抄成 description 的长文，门禁必须报超长
        _d2 = _val("description") or ""
        open(_skp2, "wb").write(
            re.sub(r"(?m)^description_zh:.*$", "description_zh: " + _d2, _txt2).encode("utf-8"))
        _r63b = run([PY, os.path.join(HERE, "check.py")])
        open(_skp2, "wb").write(_bak2)
        check("注入[description_zh 抄成长文] 门禁须报超 200 字——防「各归其位」退回「各写一遍」",
              _r63b.returncode != 0 and "200" in (_r63b.stdout or ""),
              tail_line(_r63b.stdout))
    except Exception as e:
        check("frontmatter 平台必填字段", False, repr(e))
    finally:
        if _bak2 is not None:
            open(_skp2, "wb").write(_bak2)

    print("\n[3.64] 提问结构：一个提问只装一个答案维度（v3.26.9）")
    # 背景（别删）：实测出现过把「审查尺度（粗细）」与「谈判地位（强弱）」合成一张卡片，
    # 只给「中性·强势方／中性·均衡／严苛·强势方／宽松·弱势方」四个组合选项——
    # 3 档 × 4 档 = 12 种组合只给 4 个，用户想选的「严苛·均衡」根本没得选，
    # 还被迫在一个动作里同时决定两件事。文本早就分成两问（清单第 6、7 项），
    # 是**举例写法**「组合皆合法」被照抄成了选项清单。三项判据各自独立，缺一即留缺口。
    _sk64 = os.path.join(os.path.dirname(HERE), "SKILL.md")
    _b64 = None
    try:
        _b64 = open(_sk64, "rb").read()
        _t64 = _b64.decode("utf-8")
        _lack = [n for n, k in (("总纲通则", "一个提问只装一个答案维度"),
                                ("1.6 禁令", "不得合并成一题"),
                                ("举例声明", "不是候选项")) if k not in _t64]
        check("两轴分两问：总纲通则 ＋ 1.6 禁令 ＋ 举例已声明非选项（三项齐备）",
              not _lack, ("缺：%s" % "、".join(_lack)) if _lack else "三项齐备")

        def _inj64(name, needle, repl, want):
            """改坏 SKILL.md → 跑门禁 → 按字节还原；替换未命中判「锚点漂移」，不判据失效。"""
            _mut = _t64.replace(needle, repl, 1)
            if _mut == _t64:
                check("注入[%s] 锚点" % name, False, "锚点漂移，注入无效（先修锚点再谈判据）")
                return
            open(_sk64, "wb").write(_mut.encode("utf-8"))
            try:
                _r = run([PY, os.path.join(HERE, "check.py")])
            finally:
                open(_sk64, "wb").write(_b64)
            check("注入[%s] 门禁须报错——证明判据有区分度" % name,
                  _r.returncode != 0 and want in (_r.stdout or ""), tail_line(_r.stdout))

        _inj64("删总纲通则", "一个提问只装一个答案维度（禁止把两个正交维度合成一题）",
               "（已删）", "一个提问只装一个答案维度")
        _inj64("删 1.6 禁令", "**两问必须分开出——不得合并成一题、一屏或一组组合选项。**",
               "**两问尽量分开出。**", "不得合并成一题")
        _inj64("塞组合选项行", "**轴一 · 审查尺度（粗细：基准单选 ＋ 侧重多选）**",
               "1. 中性·强势方\n**轴一 · 审查尺度（粗细：基准单选 ＋ 侧重多选）**",
               "组合选项")
        _inj64("删举例声明", "不是候选项清单，不得照抄成选项", "可以照抄成选项", "不是候选项")
    except Exception as e:
        check("提问结构：一屏一维度", False, repr(e))
    finally:
        if _b64 is not None:
            open(_sk64, "wb").write(_b64)      # 无论成败按字节还原，正式文件不留污染

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
        # 联网边界：默认配置下 --notice 必须零请求、零输出、退 0
        cfg_p = os.path.join(HERE, "config.json")
        cfg = json.loads(open(cfg_p, encoding="utf-8").read())
        gate = ((cfg.get("update") or {}).get("check_online_by_default"))
        check("联网边界：config.json 出厂默认关闭在线检查（check_online_by_default=false）",
              gate is False, "实为 %r" % (gate,))
        n = run([PY, os.path.join(HERE, "version.py"), "--notice"])
        check("联网边界：默认配置下 version.py --notice 零输出、退 0（不发任何请求）",
              n.returncode == 0 and not (n.stdout or "").strip(),
              "退出码 %s，输出 %r" % (n.returncode, (n.stdout or "")[:80]))
        # ── 安全引擎：联网按「**数据出域**」分四档（第 26 条）──────────────────
        # 不再写「脚本全部不联网」——那是把**手段当目的**。红线是"文档不出域"，
        # 不是"没有 urllib"；一刀切会把「法规库失效巡检」一起废掉，而它不联网根本做不成。
        # 档位真源**只有一个**：每个脚本文件头那行 `# net-tier: En`。
        # check.py 与此处都从它派生，**谁都不另立清单**——两份清单必漂（第 12 条）。
        #   E0 接触文档 → 零网络库（唯一的一刀切，切在这里）｜E1 在线只读公开信息 → 须可关
        #   E2 不联网就用不成 → 须显式调用           ｜E3 门禁自检 → 自身不联网
        # 关键字集**故意用宽的**（不带 `import`）：与客户可复现的那条 grep 命令同口径。
        # 窄集（"import urllib"）会少命中一个文件——同一句话两套答案，正是"写死预期"的危险处。
        net_ks = ("requests", "urllib", "socket", "http.client", "aiohttp", "httpx",
                  "curl", "wget", "Invoke-WebRequest", "smtplib", "urlopen(")
        tier_re = re.compile(r"^#[ \t]*net-tier:[ \t]*(E[0-3])\b", re.M)
        # 行首匹配真正的 import 语句；检查器自持的关键字清单是行中间的字符串，不会自指命中。
        imp_re = re.compile(r"^[ \t]*(?:import|from)[ \t]+(?:urllib|requests|socket"
                            r"|http\.client|aiohttp|httpx|smtplib|ftplib|xmlrpc)\b", re.M)
        call_re = re.compile(r"urlopen\(|requests\.(?:get|post|put)\("
                             r"|socket\.(?:socket|create_connection)\("
                             r"|(?:PARSE|_PARSE|parse)\.fetch\(", re.M)
        tiers, srcs = {}, {}
        for fn in sorted(os.listdir(HERE)):
            if not fn.endswith(".py"):
                continue
            srcs[fn] = open(os.path.join(HERE, fn), encoding="utf-8").read()
            m = tier_re.search(srcs[fn])
            tiers[fn] = m.group(1) if m else None
        by = lambda t: sorted(n for n, v in tiers.items() if v == t)  # noqa: E731
        no_tag = sorted(n for n, t in tiers.items() if t is None)
        check("安全引擎：全部 %d 个脚本均已定档（新增脚本须先定档再入库）" % len(tiers),
              not no_tag, "缺标: %s" % ", ".join(no_tag))
        check("安全引擎：档位取值只许 E0—E3", set(tiers.values()) <= {"E0", "E1", "E2", "E3"},
              "非法: %s" % sorted(set(t for t in tiers.values() if t)))
        bad = [n for n in by("E0") if any(k in srcs[n] for k in net_ks)]
        check("安全引擎：E0 档（接触文档）%d 个脚本零网络库" % len(by("E0")),
              not bad, "越界: %s" % ", ".join(bad))
        # 判据反证（**不落盘**，直接喂样本）：证明上面那条不是"永远绿"
        check("安全引擎判据：E0 样本含 import socket 须被抓出（否则门禁形同虚设）",
              imp_re.search("import os\nimport socket\n") is not None)
        check("安全引擎判据：检查器自持的关键字清单不得被误判为 import（行首正则的自指防护）",
              imp_re.search('KS = ("import urllib", "import requests",)') is None)
        dead = [n for n in by("E1") + by("E2")
                if not (imp_re.search(srcs[n]) or call_re.search(srcs[n]))]
        check("安全引擎：E1／E2 档确实接有联网路径（档位不许是空头标签）", not dead,
              "无联网路径: %s" % ", ".join(dead))
        bad3 = [n for n in by("E3") if imp_re.search(srcs[n])]
        check("安全引擎：E3 档（门禁自检）只持关键字清单、不许真 import", not bad3,
              "真 import: %s" % ", ".join(bad3))
        # 文档名单与代码自标逐档一致——25.2 的事故形态就是"文档一套、代码一套，无人比对"
        doc_t = {}
        for line in open(os.path.join(os.path.dirname(HERE), "SECURITY.md"), encoding="utf-8"):
            mm = re.match(r"[ \t]*(E[0-3])[ \t]*:[ \t]*([A-Za-z0-9_.\- ]+)$", line)
            if mm and all(x.endswith(".py") for x in mm.group(2).split()):
                doc_t[mm.group(1)] = sorted(mm.group(2).split())
        diff = [t for t in ("E0", "E1", "E2", "E3") if doc_t.get(t) != by(t)]
        check("安全引擎：SECURITY.md 档位名单与脚本自标逐档一致（文档不得与代码分家）",
              not diff, "不一致档位: %s" % ", ".join(diff))
        # ── 安全机制登记表（第 27 条）──────────────────────────────────────
        # 上面那组管"谁可以联网"，这组管"**承诺过的整套安全机制是不是真装上了**"。
        # 登记表只钉落点、不复制实现，故这里验的是**登记表自身的形状**：
        # 编号连续（漏登记会当场看出来）、每条都有判据或锚点（不许有空登记）。
        try:
            import importlib.util as _ilu
            _sp = _ilu.spec_from_file_location("_mx_probe", os.path.join(HERE, "check.py"))
            _m = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_m)          # 只读其登记表，不跑 main（有 __main__ 守卫）
            _ids = [r[0] for r in _m.SEC_MATRIX]
            check("安全机制：登记表 %d 条在册、编号 M1—M%d 连续" % (len(_ids), len(_ids)),
                  _ids == ["M%d" % i for i in range(1, len(_ids) + 1)], "实测 %s" % _ids)
            _dead = [r[0] for r in _m.SEC_MATRIX if r[4] is None and not r[5]]
            check("安全机制：每条都有判据或锚点（不许有空登记）", not _dead, "空登记 %s" % _dead)
            _lay = {r[2] for r in _m.SEC_MATRIX}
            check("安全机制：三层类目齐全（数据层／产物层／代码层）",
                  _lay == {"数据层", "产物层", "代码层"}, "实测 %s" % sorted(_lay))
            # v3.23.4 复盘加固：锚点只给函数名＝守不住"函数里的检查被删光"
            _bare = [r[0] for r in _m.SEC_MATRIX
                     if r[5] and not (isinstance(r[5], tuple) and len(r[5]) == 2 and r[5][1])]
            check("安全机制：锚点型必须钉到判据行（只给函数名＝内容被删照样绿）",
                  not _bare, "裸锚点 %s" % _bare)
            # 咬合用单个关键词会被"词在别处"骗过（实测把「默认关」改成「可关」仍全绿）
            _solo = [r[0] for r in _m.SEC_MATRIX if not r[3] or len(r[3]) < 2]
            check("安全机制：文档咬合必须是词组（单个关键词会被「词在别处」骗过）",
                  not _solo, "单词条 %s" % _solo)
            _badst = [r[0] for r in _m.SEC_MATRIX if r[6] not in ("机械", "行为", "弱", "人工")]
            check("安全机制：强度字段须为四态之一（不许把弱的混进机械里报数）",
                  not _badst, "实测 %s" % _badst)
        except Exception as e:
            check("安全机制：登记表可加载（SEC_MATRIX 在位）", False, repr(e))
        # 每个脚本都在 import 前关掉字节码写入（否则被 import 时在技能目录留 .pyc）。
        # **判据取自 check.py 的 bytecode_leaks()，不在本文件另抄一份**：抄一份就是两个副本，
        # 实测过——本是同一条判据，一边改了另一边没改，两边各报各的"漏写"。
        leak = _m.bytecode_leaks()
        check("缓存防护：每个脚本在 import 前关闭字节码写入", not leak,
              "漏写: %s" % ", ".join(leak))
        # 两档项数守恒（v3.30.0）：快档是用 skip **占位**，不是删条目。台账分键记两档 total，
        # check.py 据 total_full／total_fast 断言相等。这里做判据反证——把一份台账改坏，
        # 直接喂给判据函数，必须报错；不落盘、不碰真台账。
        try:
            import tempfile as _tf_fast
            _bad_dir = _tf_fast.mkdtemp(prefix="dcr_led_")
            os.makedirs(os.path.join(_bad_dir, "core"), exist_ok=True)
            _bad_led = os.path.join(_bad_dir, "core", "_smoke-baseline.json")
            open(_bad_led, "w", encoding="utf-8").write(json.dumps(
                {"total": 270, "total_full": 270, "total_fast": 265,
                 "failed": 0, "mode": "full"}, ensure_ascii=False))
            _errs_before = len(_m.ERRS)
            _old_root = getattr(_m, "ROOT", None)
            _m.ROOT = _bad_dir     # 让判据在临时目录找台账
            _m.check_smoke_count()
            _caught = len(_m.ERRS) > _errs_before
            _m.ERRS[:] = _m.ERRS[:_errs_before]
            if _old_root is not None:
                _m.ROOT = _old_root
            check("两档守恒判据：台账 total_full≠total_fast 须报「不守恒」", _caught,
                  "已报不守恒" if _caught else "未拦（假绿）")
        except Exception as e:
            check("两档守恒判据：台账 total_full≠total_fast 须报「不守恒」", False, repr(e))

        # ── 反向注入（铁律 25.5.3：门禁须证明拦得住，不做注入等于"尚未落实"）──
        # 上面几条是**正向断言**（现状必须合规），只能证明"现在是对的"；
        # 证明不了"将来改坏了会被拦住"。故在临时目录造一个**假技能目录**（拷 scripts/），
        # 故意改坏一处，跑一次 check.py，要求它**必须报错**。用完即删。
        inj = _inject_gate_tests(tempfile.mkdtemp(prefix="dcr-inject-"))
        for name, ok, detail in inj:
            check(name, ok, detail)
    except Exception as e:
        check("版本与依赖自检", False, repr(e))

    # --- 4. 汇总 ---
    print("\n" + "=" * 62)
    print(f"结果：通过 {len(PASSES)} 项，失败 {len(FAILS)} 项，跳过 {len(SKIPS)} 项")
    # 记账：把本次真实项数落盘，供 check.py 校验「文档里写的项数」是否属实。
    # 两档项数守恒（全量把 OCR 两步拆开，快档合并为一步，总数一致），故只记 total。
    # v3.30.0：**同一档位的 total 分键记录**（total_full / total_fast），check.py 据此断言两档相等。
    # 背景：曾有 fast 比 full 少 4 项（用一条 skip 顶掉四条 check），两档不再守恒时
    # check_smoke_count 会拿 fast 的 total 去比文档，导致「在别的机器上装完即红」。
    _tot = len(PASSES) + len(FAILS) + len(SKIPS)
    _mode = "fast" if a.fast else "full"
    try:
        # 先读旧值再开写——顺序不能颠倒：以 "w" 打开那一刻文件已被截断，此时再读只会得到空串，
        # 另一档的项数就会被静默抹成 null（本项初版即踩此坑）。
        _old = {}
        try:
            _old = json.loads(open(SMOKE_LEDGER, encoding="utf-8").read())
        except Exception:
            _old = {}
        with open(SMOKE_LEDGER, "w", encoding="utf-8") as f:
            json.dump({"_说明": "冒烟结果台账（smoke-test.py 自动生成，运行侧生成物不随开发侧留存）；"
                               "供 check.py 校验 README/教程所写项数是否为真。"
                               "total_full／total_fast 两键各自记最近一次该档的项数，"
                               "check.py 断言二者相等——两档项数必须守恒，否则文档口径无法同时成立。",
                       "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       "mode": _mode,
                       "total": _tot,
                       "total_full": _tot if _mode == "full" else _old.get("total_full"),
                       "total_fast": _tot if _mode == "fast" else _old.get("total_fast"),
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
