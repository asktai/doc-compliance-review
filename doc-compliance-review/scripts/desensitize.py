#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True
"""
文档合规审查助手AI合同审核全能版 · 脱敏脚本（可选）
===================================================
用途：仅当需把文档**上传到外部/公有云 AI 平台**时使用；本地受控环境通常不必脱敏。
原则：最小必要 + 可逆伪名化（默认）+ 映射表**只留本机** + 可回填。

模式：
  mask    <输入>                        脱敏，输出 <输入>.masked.txt；映射表写入**隔离目录**（默认 ~/.dcr-maps/）
  restore <脱敏文本> [--map 映射.json]   用映射表回填；省略 --map 时自动到隔离目录按源文件匹配

映射表安全（重要）：
  映射表为**明文**真实值对照，是回填钥匙。默认写入用户主目录下的隔离目录 ~/.dcr-maps/，
  **不再写在源文件旁边**，避免源文件位于网盘/共享目录时映射表随之同步外泄、或整目录外发时一并送出。
  可用 --map 显式指定路径；用环境变量 DCR_MAP_DIR 可整体改换隔离目录位置。
  映射表仅留本机、勿随交付物外发；如无需回填，请用 --irreversible（不生成映射表）。

脱敏类型（--types，逗号分隔，默认＝审查用 6 类）：
  idcard **证件号总类**（身份证/居住证/港澳通行证/台胞证/护照/营业执照注册号/税号等）
  phone  **电话总类**（手机号 / 座机固话 / 带区号的 （010）62345678 写法，一律归电话）
  im     **即时通讯总类**（微信 / 钉钉 / QQ / 脸书 / 微博，一律归 IM）
  bank 银行账号 / email 邮箱 / postcode 邮编
  uscc 统一社会信用代码 / amount 绝对金额（元） / addr 地址 / name 人名（按“法定代表人：”等称谓上下文识别）
  说明：**归总类是为了不漏**——座机手机写法千变万化、IM 工具年年新增，拆分枚举必然挂一漏万；
  归并后统一标签 PHONE / IM，看得出该项是什么（可读性）又不泄露值本身（安全性），二者兼顾。
  uscc（公开工商信息、主体尽调必需）与 amount（金额阈值审查必需）**审查用脱敏默认不脱**，需显式加入才脱；
  交付物“原文脱敏版”默认 10 类全脱。**比例（如 30%）不属绝对金额、不脱敏、不受影响**。
  邮编/微信/钉钉/QQ 等按“标签＋值”识别（如「微信：wxid_abc」「邮编：518000」）；裸值无标签时正则识不到，
  用 --names 思路自行追加或先补标签。
  旧类型名仍可用：`landline` 并入 phone，`wechat`/`dingtalk`/`qq` 并入 im。

其他：
  --names        额外指定确切人名（逗号分隔）；正则识不到的人名用这个兜底
  --irreversible 不可逆（固定掩码，如 138****1234；不生成映射，不能回填）
  --keep         不脱敏的类型（优先级高于 --types）

例：
  python desensitize.py mask 文档.txt --types idcard,phone,bank,email,postcode,im,uscc,amount,addr,name
  python desensitize.py mask 文档.txt --names 张三,李四
  python desensitize.py restore 文档.txt.masked.txt --map 文档.txt.map.json --out 回填.txt

原则（见 SKILL 步骤 1「文档预处理」）：恢复形式、不改实质；标记异常、不臆测；留痕可追溯；人机结合。
"""
import os, re, sys, json, argparse, datetime, hashlib

# ===== 映射表隔离目录（含真实值，禁止与源文件同目录散落）=====
# 优先级：--map 显式路径 > 环境变量 DCR_MAP_DIR > 默认 ~/.dcr-maps
MAP_DIR = os.environ.get("DCR_MAP_DIR") or os.path.join(os.path.expanduser("~"), ".dcr-maps")


def _src_key(path):
    """源文件绝对路径的短指纹：同一源文件映射表位置稳定，不同源文件互不覆盖。"""
    return hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:8]


def default_map_path(src_path):
    stem = os.path.splitext(os.path.basename(src_path))[0]
    return os.path.join(MAP_DIR, f"{stem}.{_src_key(src_path)}.map.json")


def guess_map_for_masked(masked_path):
    """由「<源名>.masked.txt」反推源文件路径，再定位隔离目录中的映射表；无法推断返回 None。"""
    p = os.path.abspath(masked_path)
    for suf in (".masked.txt", ".masked.md"):
        if p.endswith(suf):
            return default_map_path(p[: -len(suf)])
    return None

TAGS = {"idcard": "IDC", "phone": "PHONE", "bank": "BANK", "email": "EMAIL",
        "postcode": "POST", "im": "IM",
        "uscc": "USCC", "amount": "AMT", "addr": "ADDR", "name": "NAME"}
# 「前缀保留型」：正则形如 (前缀)(值) 两组，替换时保留前缀只换值。
# 例：「邮编：518000」→「邮编：[[POST-1]]」；「法定代表人：张三」→「法定代表人：[[NAME-1]]」。
# 保留标签/称谓是为了让脱敏后的文本仍可读（看得出这一项是什么），又不泄露值本身。
PREFIXED = {"idcard", "name", "postcode", "im"}   # 证件号仅其「标签兜底」那条是前缀型，靠 groups>=2 自动分流
PATTERNS = {
    # 邮箱：兼容全角＠、@ 两侧至多一个空格、中文域名（如 @公司.中国）
    "email":  re.compile(r"[A-Za-z0-9._%+\-]{1,64}\s?[＠@]\s?[A-Za-z0-9\u4e00-\u9fa5]"
                         r"(?:[A-Za-z0-9.\-\u4e00-\u9fa5]*[A-Za-z0-9\u4e00-\u9fa5])?"
                         r"\.(?:[A-Za-z]{2,}|[\u4e00-\u9fa5]{2,})"),
    # 电话总类：两条规则 —— 先座机（区号 0 开头，括号写法**半角/全角都要认**）后手机。
    # 座机必须排在手机之前：「01062345678」这类连写座机若被手机号规则先对齐会漏；两者互不冲突（手机号 1[3-9] 起）。
    "phone": [
        re.compile(r"(?<![\d\-])(?:[（(]0\d{2,3}[）)]\s?\d{7,8}|0\d{2,3}[-\s]?\d{7,8})(?!\d)"),
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ],
    # 即时通讯总类：微信 / 钉钉 / QQ / 脸书 / 微博 —— 一律「标签＋值」识别，统一打 IM 标签。
    # 裸值一律不猜（QQ 号是纯数字、脸书与微博账号格式不定，裸值必误伤订单号、日期、编号）。
    "im": [
        # 微信：字母开头的 ID、wxid_ 号，或以手机号注册的微信号
        re.compile(r"((?:微信号|微信|WeChat|wechat|WECHAT|WX|wx)\s*(?:号)?\s*[:：]\s*)"
                   r"([A-Za-z][-A-Za-z0-9_]{5,19}|wxid_[-A-Za-z0-9_]{5,19}|1[3-9]\d{9})"),
        # 钉钉：值为非空且不含句读的连续串（4–20 位）
        re.compile(r"((?:钉钉号|钉钉|DingTalk|dingtalk|DINGTALK)\s*(?:号)?\s*[:：]\s*)"
                   r"([^\s，。；、,;：（）()]{4,20})"),
        # QQ：5–11 位、首位非 0 的数字
        re.compile(r"((?:QQ号|QQ|qq|Qq|扣扣号|扣扣)\s*(?:号)?\s*[:：]\s*)([1-9]\d{4,10})(?!\d)"),
        # 脸书
        re.compile(r"((?:Facebook|facebook|FB|fb|脸书|脸書)\s*(?:号|账号|帳號)?\s*[:：]\s*)"
                   r"([^\s，。；、,;：（）()]{3,30})"),
        # 微博
        re.compile(r"((?:微博号|微博|Weibo|weibo|WEIBO)\s*(?:号)?\s*[:：]\s*)"
                   r"([^\s，。；、,;：（）()]{2,30})"),
    ],
    # 邮编：标签＋6 位，或紧跟在省市区县镇乡/路街道巷弄栋室等地址字之后的 6 位
    "postcode": re.compile(r"((?:邮政编码|邮编|POSTCODE|Postcode|ZIP|Zip)\s*[:：]?\s*"
                           r"|[省市区县镇乡路街道巷弄栋室]\s?)(\d{6})(?!\d)"),
    # 证件号（idcard 的实际语义＝**证件号总类**，不止身份证）：三条规则依次是
    # ① 18 位居民身份证／港澳台居民居住证（810000/820000/830000 开头同样落在这条）
    # ② 出入境证件裸号：港澳通行证 C/M/W、台胞证 T、中国护照 E/G/P，均为「字母＋8 位数字」
    # ③ 标签兜底：**凡写明××证号的，其后号码一律脱** —— 这是覆盖外国身份证/外国护照/
    #    营业执照注册号/税号等"格式不定证件"的唯一可靠办法（裸值无法判定，只认标签）
    "idcard": [
        re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"),
        re.compile(r"(?<![A-Za-z0-9])[CMEGPTW]\d{8}(?![A-Za-z0-9])"),
        re.compile(r"((?:证件号码|证件号|身份证号码|身份证号|护照号码|护照号|通行证号码|通行证号|"
                   r"港澳通行证号|台胞证号|居住证号码|居住证号|营业执照号|营业执照注册号|注册号|"
                   r"登记证号|税务登记号|税号|社保号|军官证号|驾驶证号)\s*[:：]?\s*)"
                   r"([A-Za-z0-9][A-Za-z0-9\-（）()]{4,24})"),
    ],
    "uscc":   re.compile(r"(?<![0-9A-Z])(?=[0-9]*[A-HJ-NPQRTUWXY])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])"),
    "name":   re.compile(r"((?:法定代表人|委托代理人|授权代表|技术负责人|项目负责人|经办人|联系人|签收人|被授权人|负责人|签字人)(?:的)?(?:姓名)?[:：]\s*)([\u4e00-\u9fa5]{2,4})(?=[，。；、,;:\s]|$)"),
    "addr":   re.compile(r"[\u4e00-\u9fa5]{2,10}(?:省|自治区)[\u4e00-\u9fa50-9\-#·]{0,12}市?[\u4e00-\u9fa50-9\-#·]{0,12}(?:区|县|旗)[\u4e00-\u9fa50-9\-#·]{0,12}(?:路|街|道|巷|弄)[\u4e00-\u9fa5]?[\s]*\d+[\s]*(?:号|栋|幢|楼|层|室)[\d\-号楼室栋]*|[\u4e00-\u9fa5]{2,8}市[\u4e00-\u9fa5]{2,8}(?:区|县)[\u4e00-\u9fa50-9\-#·]{0,12}(?:路|街|道|巷|弄)[\u4e00-\u9fa5]?[\s]*\d+[\s]*(?:号|栋|幢|楼|层|室)?[\d\-号楼室栋]*"),
    "bank":   re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    "amount": re.compile(r"(?:人民币)?\s?\d[\d,]*(?:\.\d+)?\s*(?:万元|亿元|元整|元)"),
}
# 先特异后泛，避免重叠：邮箱/信用代码/证件号 → 称谓人名/地址 → 银行 → **IM（值可能是手机号，须早于 phone）**
# → 电话（先座机后手机，见 PATTERNS 内顺序）→ 邮编（6 位数字最易误伤，放最后并靠上下文约束）→ 金额
ORDER = ["email", "uscc", "idcard", "name", "addr", "bank", "im", "phone", "postcode", "amount"]
# 两类默认口径（SKILL 12.1 / README 2.3 同口径，改一处须同步其余）
REVIEW_TYPES = "idcard,phone,bank,email,postcode,im"                # 审查用 6 类：保留信用代码/金额/地址/人名
ALL_TYPES = ("idcard,phone,bank,email,postcode,im,"
             "uscc,amount,addr,name")                               # 对外出域 10 类全脱
# 旧类型名别名：归并后仍可被命令行接受并映射到新总类，避免历史脚本与外部文档里的旧写法静默失效
ALIASES = {"landline": "phone", "tel": "phone", "mobile": "phone",
           "wechat": "im", "dingtalk": "im", "qq": "im", "facebook": "im", "weibo": "im"}
TOKEN_RE = re.compile(r"\[\[[A-Z]+-[A-Z0-9]+\]\]")
TAG2TYPE = {v: k for k, v in TAGS.items()}   # 占位符标记 → 类型，供不可逆模式回填固定掩码时反查


def _tag_of(tok):
    return tok[2:].split("-")[0]

def fixed_mask(t, v):
    if t == "idcard":
        # 证件号长短不一（18 位身份证 / 9 位通行证护照 / 15 位营业执照注册号），按长度分档，
        # 短号若沿用「前 6 后 4」会只掩中间几位，等于没脱
        n = len(v)
        if n >= 15: return v[:6] + "********" + v[-4:]
        if n >= 8:  return v[:2] + "*" * (n - 4) + v[-2:]
        return v[:1] + "*" * max(1, n - 1)
    if t == "phone":
        # 电话长短不一（11 位手机号 / 带区号连写 11 位 / （010）62345678 十二字 / 分机号更长），按形态分档。
        # 判「像不像手机号」用「11 位且 1[3-9] 起」，不是只看长度——避免把同长度的座机套成手机格式。
        v2 = re.sub(r"\D", "", v)
        if len(v2) == 11 and re.match(r"^1[3-9]\d{9}$", v2):
            return v[:3] + "****" + v[-4:]
        return v[:3] + "****" + v[-2:]
    if t == "bank":   return "*" * max(0, len(v) - 4) + v[-4:]
    if t == "email":
        u, _, d = v.partition("@"); return (u[:1] + "***@" + d) if u else "***@" + d
    if t == "uscc":   return v[:4] + "**********" + v[-4:]
    if t == "amount": return "【金额已脱敏】"
    if t == "addr":   return v[:3] + "****"
    if t == "name":   return v[:1] + "*" * max(1, len(v) - 1)
    if t == "postcode": return v[:2] + "****"
    if t == "im":       return v[:2] + "****"
    return "***"

def canonical_list(spec):
    """把「逗号分隔的类型串」规一化为有序去重的新类型列表：别名归到总类，未知类型丢弃。

    返回 (types, dropped)。旧写法 --types landline,wechat 在新口径下不会再静默失效，
    而是分别落到 phone 与 im；两者同为电话/同为 IM 时不重复计数。
    """
    out, dropped = [], []
    for raw in (spec or "").split(","):
        t = raw.strip().lower()
        if not t:
            continue
        t = ALIASES.get(t, t)
        if t in PATTERNS:
            if t not in out:
                out.append(t)
        else:
            dropped.append(raw.strip())
    return out, dropped


def mask_text(text, types, reversible):
    counters, mapping = {t: 0 for t in types}, {}
    stats = {t: 0 for t in types}
    for t in ORDER:
        if t not in types: continue
        # 一个类型可对应多条规则（如证件号＝18 位身份证 / 出入境证件 / 标签兜底），逐条过
        rxs = PATTERNS[t] if isinstance(PATTERNS[t], (list, tuple)) else [PATTERNS[t]]
        def repl(m, t=t):
            counters[t] += 1; stats[t] += 1
            # 前缀保留型（证件号标签/称谓/邮编/微信/钉钉）：只换值，保留「身份证号：」「微信：」等标签
            # 判据用 groups>=2：同一类型若有多条规则，非前缀型那条组数为 0，自动走整体替换
            prefix, v = ("", m.group(0))
            if t in PREFIXED and m.re.groups >= 2:
                prefix, v = m.group(1), m.group(2)
            tok = f"[[{TAGS[t]}-{counters[t]}]]"; mapping[tok] = v
            return prefix + tok
        for rx in rxs:
            text = rx.sub(repl, text)
    if not reversible:
        # 不可逆：统一先置换成占位符，扫完再一次性换成固定掩码。
        # 不能边扫边打码——证件号这类"一类型多条规则"的场景会重复打码：掩码里剩下的数字
        # 又被下一条规则当成新号码再打一次，实测出现过「310101********0101********8765」。
        def fin(m):
            tok = m.group(0)
            return fixed_mask(TAG2TYPE.get(_tag_of(tok), ""), mapping.get(tok, ""))
        text = TOKEN_RE.sub(fin, text)
        mapping = {}   # 不可逆不产出映射（本来就不可回填）
    return text, mapping, stats

def main():
    ap = argparse.ArgumentParser(description="文档脱敏/回填（可选工具）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mask"); m.add_argument("input")
    m.add_argument("--out"); m.add_argument("--map")
    # 类型名先过 canonical_list()：别名（landline/wechat/dingtalk/qq…）自动归到 phone / im 总类
    m.add_argument("--types", default=REVIEW_TYPES,
                   help="脱敏类型，逗号分隔（默认＝审查用 6 类；对外出域请显式给 10 类全脱）")
    m.add_argument("--keep", default="")
    m.add_argument("--names", default="", help="额外确切人名（逗号分隔），正则识不到的人名用这个兜底")
    m.add_argument("--irreversible", action="store_true")
    r = sub.add_parser("restore"); r.add_argument("input")
    r.add_argument("--map", default=None, help="映射表路径；省略时自动到隔离目录按源文件匹配")
    r.add_argument("--out")
    a = ap.parse_args()

    if a.cmd == "mask":
        types, dropped = canonical_list(a.types)
        keep = {ALIASES.get(t.strip().lower(), t.strip().lower())
                for t in a.keep.split(",") if t.strip()}
        types = [t for t in types if t not in keep]
        for d in dropped:
            print(f"[desensitize] 忽略未知类型：{d}（可用：{', '.join(PATTERNS)}）")
        text = open(a.input, encoding="utf-8-sig").read()
        names = [x.strip() for x in (a.names or "").split(",") if x.strip()]
        pre_map = {}
        for i, nm in enumerate(names, 1):
            if not a.irreversible:
                tok = f"[[NAME-K{i}]]"; pre_map[tok] = nm; text = text.replace(nm, tok)
            else:
                text = text.replace(nm, nm[0] + "*" * max(1, len(nm) - 1))
        out_text, mapping, stats = mask_text(text, types, not a.irreversible)
        if pre_map: mapping = {**pre_map, **mapping}
        out = a.out or (a.input + ".masked.txt")
        open(out, "w", encoding="utf-8").write(out_text)
        print("[desensitize] 已脱敏 →", os.path.abspath(out))
        print("[desensitize] 统计：", {t: stats[t] for t in types if stats.get(t)})
        if not a.irreversible and mapping:
            mp = a.map or default_map_path(a.input)
            os.makedirs(os.path.dirname(os.path.abspath(mp)), exist_ok=True)
            json.dump({"created": datetime.datetime.now().isoformat(timespec="seconds"),
                       "source": os.path.basename(a.input), "tokens": mapping},
                      open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print("[desensitize] 映射表（**含真实值 · 仅留本机 · 勿随交付物外发**）→", os.path.abspath(mp))
            print("[desensitize] 已在隔离目录存放（默认 ~/.dcr-maps/），不再与源文件同目录，避免网盘同步或整目录外发时一并送出。")
        elif a.irreversible:
            print("[desensitize] 不可逆模式：未生成映射表，无法回填。")
    else:
        mp = a.map or guess_map_for_masked(a.input)
        if not mp or not os.path.exists(mp):
            print("[desensitize] 未找到映射表，无法回填。")
            print("              隔离目录（默认）：", MAP_DIR)
            if mp:
                print("              已尝试：", os.path.abspath(mp))
            print("              若为 V3.0.1 及更早版本生成的映射表（位于源文件同目录 <源名>.map.json），请用 --map 显式指定。")
            sys.exit(2)
        text = open(a.input, encoding="utf-8-sig").read()
        mapping = json.load(open(mp, encoding="utf-8")).get("tokens", {})
        def back(mo): return mapping.get(mo.group(0), mo.group(0))
        out_text = TOKEN_RE.sub(back, text)
        out = a.out or (a.input + ".restored.txt")
        open(out, "w", encoding="utf-8").write(out_text)
        print("[desensitize] 已回填 →", os.path.abspath(out), "（映射条目", len(mapping), "个，映射表", os.path.abspath(mp), "）")

if __name__ == "__main__":
    main()
