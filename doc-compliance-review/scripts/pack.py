#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
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
文档合规审查助手AI合同 · 发布包打包脚本（UTF-8 文件名）
===============================================================
用 Python zipfile 生成**唯一的发布 zip** —— 以开放平台（open.workbuddy.cn）的上架规范为准。

**只有一个包**：`doc-compliance-review-<版本>.zip`，解压后**第一层是技能目录**
`doc-compliance-review/`，进去才是 `SKILL.md`、`core/`、`scripts/`…。

    doc-compliance-review-V3.7.0.zip
      └─ doc-compliance-review/        ← 第一层即技能目录（平台要求，否则无法解析）
           ├─ SKILL.md               ← 每次会话都加载的主口径（刻意瘦身，只留常驻部分）
           ├─ permissions-and-libraries.md／drafting-guide.md／template-guide.md   ← 按需加载，命中入口才读
            ├─ README.md / 安装使用教程.md / LICENSE.md / VERSION.md
            ├─ 文档合规审查助手AI合同提示词版.md / SECURITY.md
            ├─ core/  industries/  scripts/（含 TONE.md）  assets/  samples/
           └─ …

一份源、一次打包、一个产物，不存在两处内容漂移的可能。纯提示词版也**不单独打包**，
它是包内的单个文件「文档合规审查助手AI合同提示词版.md」，复制粘贴即可用（少一个包就少一处不一致）。

**平台硬约束**：技能包内**至多两级目录**（`技能目录/二级目录/文件`）。
三级（如 `industries/<slug>/rules.md`）会被判「目录层级超限」直接拒收——故行业库平铺为
`industries/<slug>-rules.md`、自检样本直接放 `samples/` 顶层；`check.py` 与本脚本的出包
自检都会守住这条。

安全要点：
  **private/ 默认不打入发布包**。私有库是企业内控口径（审批流、风控底线、商业底线条款），
  一旦随发布包外泄即无法收回，故与 README「对外发布前务必剔除 private/」的要求保持一致：
  由脚本强制排除，而非依赖人工记得删。
  确需连同私有库一起打包（如企业内部留档）时，须显式加 --include-private，脚本会打印醒目警告，
  并在打包后复查包内是否混入 private/。

**作者本机路径不出包**：`scripts/config.json` 的 `tools` 段若填的是开发机绝对路径
（如 `D:\\Tools\\tesseract\\tesseract.exe`），随包分发会让每个新装使用者一跑 `check.py`
就吃一条「工具路径在本机不存在」的警告，跑全量档冒烟时 OCR/PDF 相关项还会失败。
故**出包时只清空包内副本的 tools 段**（磁盘上的文件一字不动），留空即按内置默认值与 PATH
回退——使用者要固化本机路径，跑一次 `detect-tools.py --write` 即可。
确需带本机路径出包（如给自己的另一台机器留档）时用 `--keep-tools`。

**文件名四段式**：`中文产品名_版本号_日期_(技能ID).封装格式`，例如

    广告合规审查_v1.7.0_20260928_(advertising-compliance-review).zip

四段定式：**版本号带小写 v**、**日期紧凑 8 位**、**技能 ID 用半角括号包裹置末**、
**分隔符一律下划线**；封装格式**默认同时出 `.skill` 与 `.zip` 两种**。

各段均**自动读取，不靠手填**，避免"版本升了文件名还写着旧号"：
产品名取 `SKILL.md` frontmatter 的 `display_name`，版本号取 `version`（统一补小写 `v`），
日期为**打包当天**（紧凑写 `%Y%m%d`），括号段取 `name`（**slug**，小写字母/数字/连字符）。
`display_name_en`（英文可读名）仍属出包必填字段——平台展示要用，但**不进文件名**。

> 注：文件名含成对半角括号，属合法文件名；在终端里操作记得加引号或用转义。
> `.skill` 全小写（V3.11.9 起；此前为大写 `.Skill`，因部分系统扩展名匹配大小写敏感，
> 统一小写更稳妥）。脚本内以 `FMT_EXT` 为准，勿另行硬拼。
- `.zip` ＝纯 ZIP，与开放平台（open.workbuddy.cn）实测口径一致（**平台官方收 zip、≤3 MB**）。

用法：
  python pack.py <技能根目录> [--out <发布包目录，默认 <根>/_发布包>]
                             [--include-private] [--tag <版本标签，默认读 SKILL.md>]
                             [--keep-tools] [--format skill|zip|both]
"""
import os, re, sys, json, hashlib, zipfile, argparse, datetime

# SECURITY.md 必须随包：README 目录树、SKILL 第十二节、提示词版边界条款均指向它，
# 漏掉会变成「包内文档指向包外不存在的文件」。
# 注：`scripts/TONE.md`（感谢语参考）**不在此列**——scripts/ 由 FULL_DIRS 整体递归打包，
# 再列一次会写出同名重复条目（zipfile 会告警且条目数虚增）。它随 scripts/ 进包即达目的。
FULL_FILES = ["SKILL.md", "README.md", "安装使用教程.md", "LICENSE.md", "VERSION.md",
              "文档合规审查助手AI合同提示词版.md", "SECURITY.md",
              # 按需加载的三份专项口径：SKILL 里只留索引段，命中对应入口时才读这几份，
              # 以此压住 SKILL 的常驻体积。必须随包，否则索引指向包外不存在的文件。
              "permissions-and-libraries.md", "drafting-guide.md", "template-guide.md",
              # 对外版本清单（供在线检查更新）。随包是为了让使用者能**离线核对**
              # "本包自称是哪一版、官方最新是哪一版"；也是发布时随包上传到仓库的那一份。
              # 版本一致性由 check.py 的 check_manifest_version() 守卫（铁律 19.3）。
              "version.json"]
# assets/ 必须随包（README/SKILL 顶部引用了头标，缺了就是裂图）；private/ 仍默认排除
# samples/ 下**只带顶层文件**（即自检样本）；samples/输出样例、公开范本、通用样例属
# 开发侧素材，一律不随包。
# **平台约束（V3.3.0 实测）**：开放平台解析技能包时只接受「根目录/二级目录/文件」两级，
# 三级（如 industries/<slug>/rules.md）直接报「目录层级超限」而拒收——故自检样本也**不再
# 放子目录**，行业库改平铺（industries/<slug>-rules.md），scripts/ 校验会守住这条。
# smoke-test 的「真实文件链路」与「比对链路」用它们验证 Word 提取、扫描型 PDF 与图片
# 合同的 OCR、真实敏感信息脱敏、以及 A/B 两版比对。
# 若使用者自行删掉这些样本（例如只留提示词版），smoke-test 相关项一律 SKIP 而非 FAIL。
SELFTEST_DIR = "samples"
FULL_DIRS = ["assets", "core", "industries", "scripts", SELFTEST_DIR]
NONREC_DIRS = {"samples"}   # 只带该目录下的文件，不递归其子目录（子目录为开发侧素材）
PRIVATE_DIR = "private"
EXCLUDE_DIRS = {"_归档", "_分发包", "_发布包", "测试合同", "__pycache__"}
EXCLUDE_FILES = {"regression-report-V2.0.0.md",
                 # 本机跑冒烟的产物：随包会把**作者机器**的冒烟结果带给使用者，
                 # check.py 的 check_smoke_count() 读到的是别人的基线，判自己机器的项数必错。
                 # 注：`_rules-baseline.json`（规则台账）与 `.integrity.json`（脚本指纹）**有意随包**，
                 # 前者供 rule-baseline.py 比对改动，后者供 check.py --verify 校验脚本未被改。
                 "_smoke-baseline.json",
                 # 本机工具路径覆盖层：由 detect-tools.py --write 生成，只对当前这台机器有意义，
                 # 随包会把作者的本机路径带给使用者，在新机器上必然失效并触发 PATH 回退告警。
                 "config.local.json"}

# 技能目录名 —— 必须与 SKILL.md frontmatter 的 name 一致，平台据此识别技能；
# 上架版要求解压后第一层就是它。
SKILL_DIR = "doc-compliance-review"
# 平台上限（2026-09-20 实测口径）；超出会被拒收，故打包后自检会拦
PLATFORM_MAX_MB = 3
# 平台只解析两级（技能目录/二级目录/文件）
PLATFORM_MAX_DEPTH = 2

# 出包时需清空的配置文件（相对技能根）——只清 tools 段，其余段（隐私/输出策略）保持原样
CONFIG_REL = "scripts/config.json"

# zip 条目**固定时间戳**（可复现构建）：
#   zf.write() 默认写源文件 mtime，而发布链 sync() 是 rmtree＋copytree 全量重建，
#   重建后全部文件 mtime 都是同步时刻 → 同一版本每次重跑，包内容未变、字节却全变。
# 统一用固定时间戳，内容相同则包字节必相同，包哈希可复现、可用于校验与缓存。
# 取 1980-01-01 00:00:00（zip 格式可表示的最小合法值，避免各平台对 0 值的兼容差异）。
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def neutralise_config(text):
    """把 config.json 的 tools 段清成空串，返回新文本；无需改动则返回 None。

    只动 tools：workdir/privacy/output 是策略项，留着才对（workdir 本就是 auto）。
    解析失败一律返回 None（宁可原样打包，也不写出一个坏掉的 config）。
    """
    try:
        d = json.loads(text)
    except Exception:
        return None
    tools = d.get("tools")
    if not isinstance(tools, dict) or not any((v or "").strip() for v in tools.values()):
        return None
    for k in tools:
        tools[k] = ""
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


def _zip_write(zf, fp, arc, blank_tools=False, report=None):
    """把单个文件写入 zip，**条目时间戳固定**，保证可复现构建。

    为什么要固定：`zf.write()` 默认把**源文件 mtime** 写进 zip 条目，而发布链的
    `sync()` 是 `rmtree ＋ copytree` 全量重建，重建后所有文件 mtime 都变成同步时刻——
    于是同一版本每次重跑，包内容一字未改、**字节却全变**，包哈希不可复现。
    这里统一用固定时间戳（`ZIP_EPOCH`），内容相同则包字节必相同。

    config.json 的"清空工具路径"分支走 `writestr`，此处一并统一时间戳。
    """
    if blank_tools and arc == CONFIG_REL:
        try:
            with open(fp, encoding="utf-8") as cf:
                got = neutralise_config(cf.read())
        except Exception:
            got = None
        if got:
            zi = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, got)
            if report is not None:
                report.append(arc)
            return
    zi = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    with open(fp, "rb") as f:
        zf.writestr(zi, f.read())


def add_tree(zf, base, relpath, recurse=True, prefix="", blank_tools=True, report=None):
    src = os.path.join(base, relpath)
    for root, dirs, files in os.walk(src):
        if recurse:
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        else:
            dirs[:] = []   # 不进入子目录：非随包目录（如 samples/公开范本）不得混入
        for f in sorted(files):
            if f in EXCLUDE_FILES:
                continue
            if f.startswith("_") and f.endswith(".log.txt"):
                continue   # 本地测试日志（如 _testrb.log.txt）不得混入发布包
            fp = os.path.join(root, f)
            arc = os.path.relpath(fp, base).replace("\\", "/")
            _zip_write(zf, fp, prefix + arc if prefix else arc,
                       blank_tools=blank_tools, report=report)

def verify_zip(zp):
    """出包自检：把上次被平台拒收的硬伤，做成**出包即拦**的守门（退码非 0 即视为打包失败）。

    校验项均来自开放平台的实测口径：
      1. 顶层只有技能目录一个条目（第一层须是 SKILL_DIR）→ 否则平台解析不到技能
      2. SKILL.md 恰 1 份且在技能目录下          → 多份或缺份都会 400
      3. 目录层级 ≤ 2（技能目录/二级目录/文件）    → 三级直接判「目录层级超限」拒收
      4. 体积 ≤ 3 MB                              → 平台上传上限
      5. private/ 未混入                          → 企业内控口径不得外泄
    """
    bad = []
    with zipfile.ZipFile(zp) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = sorted(set(n.split("/")[0] for n in names))
    if tops != [SKILL_DIR]:
        bad.append("顶层条目 %s —— 第一层须是技能目录 %s，且只有它" % (tops, SKILL_DIR))
    n_skill = sum(1 for n in names if n == SKILL_DIR + "/SKILL.md")
    if n_skill != 1:
        bad.append("SKILL.md 计数 %d（须恰为 1，且在技能目录下）" % n_skill)
    # 两级目录 ＝ 技能目录/二级目录/文件 ⇒ 相对 zip 根最多 2 个斜杠
    deep = sorted(set(n for n in names if n.count("/") > PLATFORM_MAX_DEPTH))
    if deep:
        bad.append("目录层级超限（>%d 级）共 %d 条，例如：%s"
                   % (PLATFORM_MAX_DEPTH, len(deep), deep[0]))
    mb = os.path.getsize(zp) / 1048576.0
    if mb > PLATFORM_MAX_MB:
        bad.append("体积 %.2f MB > 平台上限 %d MB" % (mb, PLATFORM_MAX_MB))
    leaked = [n for n in names if n.startswith(SKILL_DIR + "/" + PRIVATE_DIR + "/")]
    if leaked:
        bad.append("private/ 混入了 %d 个文件（企业内控口径，不得外发）" % len(leaked))
    return bad


# ------------------------------------------------------------------ 封装格式与四段式命名
# `.skill`＝自定义头部 ＋ zip 负载（**自描述格式**，非平台公开规范）。
# 头部布局（小端）：
#   0   4B   magic = b"SKLP"
#   4   1B   头部格式版本（当前 1）
#   5   4B   meta_len：元数据 JSON 字节数
#   9   nB   元数据 JSON（UTF-8）
#   9+n 32B  负载（zip 字节）的 SHA-256
#   41+n …   负载：标准 ZIP 数据，与同名 `.zip` **字节完全一致**
# 这样安排的好处：负载是裸 zip，Python zipfile 与 unzip 都能直接解开
# （unzip 会提示"前面多了若干字节"但仍能处理），不需要专用工具也能取内容。
SKILL_MAGIC = b"SKLP"
SKILL_FMT_VER = 1
# 文件名四段式：`中文产品名_版本号_日期_(技能ID).封装格式`
#   例：广告合规审查_v1.7.0_20260928_(advertising-compliance-review).zip
# 四段定式（2026-09-29 定，V3.11.6 起生效）：
#   · 版本号 **带小写 v** 前缀（`v1.7.0`，不是 `V1.7.0`、也不是裸 `1.7.0`）
#     ——2026-10-14（v1.32.0）由大写 V 统一改为小写 v，与铁律 19.2／15.2 同步。
#   · 日期 **紧凑 8 位**（`%Y%m%d`，如 20260928）
#   · 技能 ID 用 **半角括号**包裹，内容为 **slug**（`name` 字段，小写字母/数字/连字符）
#   · 分隔符一律 **下划线**
#   · 封装格式默认同时出 `.skill` 与 `.zip` 两种（见 `--format`，默认 both）
# 段序、分隔符与大小写一律以本常量为准，**不要在别处另行拼装文件名**。
FMT_EXT = {"zip": "zip", "skill": "skill"}


def _fm_field(base, key):
    """从 SKILL.md frontmatter 取一个标量字段（够用即可，不引第三方 yaml）。"""
    try:
        with open(os.path.join(base, "SKILL.md"), encoding="utf-8-sig", errors="ignore") as f:
            head = f.read(4000)
    except OSError:
        return ""
    m = re.search(r"(?m)^%s:\s*(.+)$" % re.escape(key), head)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def package_stem(base, tag, date=None):
    """四段式文件名主干：**中文产品名_版本号_日期_(技能ID)**。返回 (主干, 产品名, 技能ID, 日期, 英文名)。

    对照规范（示例见文档）：

        广告合规审查_v1.7.0_20260928_(advertising-compliance-review).zip
        └─产品名─┘ └版本号┘ └─日期─┘ └────技能ID（slug）────┘ └封装┘

    各段取值：
      · 产品名 ← frontmatter 的 `display_name`（去引号、去文件名非法字符）
      · 版本号 ← tag（`read_skill_version` 自动读 `version`，**统一补小写 v**，不靠手填）
      · 日期   ← 打包当天，**紧凑写**（`%Y%m%d`，如 20260928）；
                 可用 `date` 参数（命令行 `--date`）覆盖，供复现某日包或 CI 固定日期
      · 技能ID ← frontmatter 的 `name`（slug，小写字母/数字/连字符），**配半角括号置末**
                 ——2026-09-29 起由英文可读名改为 slug，与平台/目录名保持同一套标识
      · 英文名 `display_name_en` **仍读取**但**不进文件名**（平台展示用；保留在 pack.py 的
                 `_fm_field` 调用里，`check.py` 的出包必填字段守卫仍会校验它，守卫不削弱）
    四段一并返回，供 .skill 头部元数据复用——**不要从文件名反解**：
    产品名可能含空格、中点或与分隔符同形的字符，按 `_` 切会错位，
    一律以本函数的返回值为准（slug 段本身不含空格，可安全切）。
    """
    product = _fm_field(base, "display_name") or _fm_field(base, "name") or SKILL_DIR
    sid = _fm_field(base, "name") or SKILL_DIR
    en = _fm_field(base, "display_name_en") or sid
    product = _safe_name(product) or SKILL_DIR
    en = _safe_name(en) or sid
    sid = _safe_name(sid) or SKILL_DIR
    date = date or datetime.date.today().strftime("%Y%m%d")
    return "%s_%s_%s_(%s)" % (product, tag, date, sid), product, sid, date, en


def _safe_name(s):
    """文件名安全化：去掉 Windows/Linux 非法字符与首尾空白，保留空格与中点。"""
    return re.sub(r'[\\/:*?"<>|]+', "", s).strip()


# 四段式文件名正则：`中文产品名_版本号_日期_(技能ID).封装格式`
#   · 版本号段 **必须**带小写 v（大写 V、裸数字一律不合规）
#   · 日期段紧凑 8 位（合法性另由 verify_filename 用 strptime 复核）
#   · 技能 ID 段由**半角括号**包裹，内容为 slug（字母/数字/`.`/`_`/`-`，**不含空格**）
#     旧版此处放英文可读名（含空格与中点），改 slug 后此正则即能把它挡住，防旧形态回流。
STEM_RE = re.compile(r"^.+_v\d+(?:\.\d+)*_\d{8}_\([A-Za-z0-9][A-Za-z0-9._-]*\)$")


def verify_filename(stem):
    """出包前自测文件名是否符合四段式规范。返回错误列表（空＝合规）。

    规范只是一段文档的话，改代码的人很容易忘（或按旧习惯拼出一个看似合理的名字）。
    这里把它做成**每次出包都会跑**的断言，格式漂移当场拦下。
    """
    bad = []
    if not STEM_RE.match(stem):
        bad.append("文件名不合四段式「产品名_版本号(带小写v)_日期8位_(技能ID slug)」：%s" % stem)
    # 逐段再核一遍，报错指向具体哪一段（比只报"不合格式"更好排查）
    m = re.match(r"^(?P<p>.+?)_(?P<v>[Vv]?\d+(?:\.\d+)*)_(?P<d>\d{8})_(?P<i>\(.+\))$", stem)
    if m:
        v, d, i = m.group("v"), m.group("d"), m.group("i")
        if not v.startswith("v"):
            bad.append("版本号段应以小写 v 开头（如 v1.7.0）：%s" % v)
        if len(d) != 8:
            bad.append("日期段应为 8 位紧凑写（%%Y%%m%%d）：%s" % d)
        else:
            try:
                datetime.datetime.strptime(d, "%Y%m%d")
            except ValueError:
                bad.append("日期段不是合法日期（%%Y%%m%%d）：%s" % d)
        if not (i.startswith("(") and i.endswith(")")):
            bad.append("技能ID 段应由半角括号包裹：%s" % i)
        elif " " in i or "（" in i or "）" in i:
            bad.append("技能ID 段应为 slug（半角括号、无空格、不用全角括号）：%s" % i)
    return bad


def write_skill(zp, out, product, sid, version, date):
    """把打好的 zip 封装成 .skill（头部 ＋ zip 负载）。返回 (元数据, 头部字节数)。"""
    raw = open(zp, "rb").read()
    with zipfile.ZipFile(zp) as zf:
        n_entry = len([n for n in zf.namelist() if not n.endswith("/")])
    meta = {
        "format": "dcr-skill-package/%d" % SKILL_FMT_VER,
        "product": product,
        "id": sid,
        "version": version,
        "date": date,
        "payload": "application/zip",
        "payload_bytes": len(raw),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "entries": n_entry,
    }
    mj = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    head = (SKILL_MAGIC + bytes([SKILL_FMT_VER]) + len(mj).to_bytes(4, "little")
            + mj + hashlib.sha256(raw).digest())
    with open(out, "wb") as f:
        f.write(head + raw)
    return meta, len(head)


def verify_admission_manifest(base):
    """素材准入硬拒（铁律第 9.4 条）：**默认拒绝随包**，未登记即**拒绝出包**。

    背景：FULL_DIRS 是**整体递归打包**，`samples/` 里多出来的东西会被**照单全收**。
    更早以前是"白名单外的顶层条目静默丢弃"——于是"忘了登记"的失败方向是
    **包静默少一个样本**，使用者那边冒烟只会 SKIP、不会报错，**无人知晓**。
    准入制把这方向反过来：**多出来的东西 → 出包直接失败**，逼你先登记。

    准入清单在**开发侧** `maint/samples-manifest.json`（不随包，属工程管理凭据）。
    核验两个方向：
      · 包内有、册上无 → 拒绝（未许可即随包，违反默认拒绝）；
      · 册上有、包内无 → 拒绝（使用者会缺样本）。
    清单缺失时**不拒绝**（旧包/无清单项目的兼容），但打醒目警告。

    返回 (list_of_errors, list_of_warnings)。
    """
    bad, warns = [], []
    # 清单在**开发侧** `dev/maint/`，而 base 是 `dev/doc-compliance-review`
    # （也可能是运行实例 ~/.codebuddy/skills/…）。故：向上找到含 maint/ 的那一级。
    # ⚠ 早期版本用 `dirname(dirname(base))` —— 多算一层，路径永远错，
    #   于是每次都走"清单缺失 → 仅警告"分支，**静默放行**（负测试当场暴露）。
    manifest = None
    cur = os.path.abspath(base)
    for _ in range(3):
        cur = os.path.dirname(cur)
        cand = os.path.join(cur, "maint", "samples-manifest.json")
        if os.path.exists(cand):
            manifest = cand
            break
    sdir = os.path.join(base, SELFTEST_DIR)
    if not os.path.isdir(sdir):
        return bad, warns
    if manifest is None:
        warns.append("未找到素材准入清单（在 %s 上溯 3 级未命中 maint/samples-manifest.json）"
                     "——无法核验 samples/ 的随包许可（铁律 9.4 准入制）" % base)
        return bad, warns
    try:
        man = json.load(open(manifest, encoding="utf-8"))
    except Exception as e:
        bad.append("素材准入清单解析失败：%s（%s）" % (e, manifest))
        return bad, warns
    reg = {e.get("file") for e in (man.get("entries") or [])}
    actual = {f for f in os.listdir(sdir)
              if os.path.isfile(os.path.join(sdir, f))}
    for fn in sorted(actual - reg):
        bad.append("samples/ 内含未登记素材「%s」——准入制为默认拒绝，"
                   "须先在 maint/samples-manifest.json 登记「许可随包 ＋ 理由」" % fn)
    for fn in sorted(reg - actual):
        bad.append("准入清单登记了「%s」，但 samples/ 内没有此文件"
                   "——使用者将缺该样本（冒烟相关项会 SKIP 而非 FAIL）" % fn)
    return bad, warns


def build(base, outdir, include_private=False, tag="v3.0.0", keep_tools=False, fmt="both",
          date=None):
    os.makedirs(outdir, exist_ok=True)
    priv_path = os.path.join(base, PRIVATE_DIR)
    prefix = SKILL_DIR + "/"   # 上架版结构：所有条目都套一层技能目录
    blanked = []               # 本次包内被清空工具路径的配置文件（用于收尾提示）
    stem, product, sid, _date = package_stem(base, tag, date)[:4]
    _bad = verify_filename(stem)
    if _bad:
        for b in _bad:
            print("  [FAIL] " + b)
        print("  [x] 文件名不合四段式规范，已中止出包（勿手工改名绕过，去修 package_stem）。")
        return False
    # 素材准入硬拒（铁律 9.4）：未登记即拒绝出包，杜绝"包静默少一个样本"
    _adm_bad, _adm_warn = verify_admission_manifest(base)
    if _adm_bad:
        for b in _adm_bad:
            print("  [FAIL] " + b)
        print("  [x] 素材准入核验未通过，已中止出包"
              "（登记后重跑；勿删样本绕过，去补 maint/samples-manifest.json）。")
        # **清理本次目标文件**：留下上一次的旧包会被误当成"本次已生成"
        for _ext in set(FMT_EXT.values()):
            _stale = os.path.join(outdir, "%s.%s" % (stem, _ext))
            if os.path.exists(_stale):
                os.remove(_stale)
                print("  [i] 已删除上次残留的 %s（避免误当成新产物）"
                      % os.path.basename(_stale))
        return False
    for w in _adm_warn:
        print("  [警告] " + w)
    for files, dirs, name in [
        (FULL_FILES, list(FULL_DIRS), "%s.%s" % (stem, FMT_EXT["zip"])),
    ]:
        dirs = list(dirs)
        with_private = include_private and os.path.isdir(priv_path)
        if with_private:
            dirs.append(PRIVATE_DIR)
        zp = os.path.join(outdir, name)
        if os.path.exists(zp):
            os.remove(zp)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                fp = os.path.join(base, f)
                if os.path.exists(fp):
                    _zip_write(zf, fp, prefix + f, blank_tools=keep_tools is False,
                               report=blanked)
            for d in dirs:
                if os.path.isdir(os.path.join(base, d)):
                    add_tree(zf, base, d, recurse=(d not in NONREC_DIRS), prefix=prefix,
                             blank_tools=not keep_tools, report=blanked)
        with zipfile.ZipFile(zp) as zf:
            entries = zf.namelist()
        n_entry = len([n for n in entries if not n.endswith("/")])
        print("built", zp, "entries", len(entries))
        print("  [i] 结构：第一层 %s/（上架版规范），共 %d 个文件条目" % (SKILL_DIR, n_entry))
        leaked_hit = [n for n in entries if n.startswith(SKILL_DIR + "/" + PRIVATE_DIR + "/")]
        if leaked_hit:
            print("  [警告] 本包内含 private/ 共 %d 个文件（企业内控口径）——请确认发布对象，勿对外发布！"
                  % len(leaked_hit))
        else:
            print("  [OK] 已排除 private/（企业内控口径未入包）")
        if blanked:
            print("  [OK] 已清空包内 %s 的 tools 段（作者本机路径不随包；使用者跑 "
                  "detect-tools.py --write 写入本机路径）" % "、".join(blanked))
        elif not keep_tools:
            print("  [i] 包内 config.json 的 tools 段本就为空，无需清空")
        bad = verify_zip(zp)
        if bad:
            for b in bad:
                print("  [FAIL] " + b)
            print("  [x] 出包自检未通过：请勿发布，修正后重打。")
            return False
        print("  [OK] 出包自检通过：顶层／SKILL.md 计数／层级（≤%d 级）／体积（≤%d MB）／private 五项全过"
              % (PLATFORM_MAX_DEPTH, PLATFORM_MAX_MB))

        # ---- 封装为 .skill（头部 ＋ 同一个 zip 负载）
        sp = os.path.join(outdir, "%s.%s" % (stem, FMT_EXT["skill"]))
        if fmt in ("both", "skill"):
            meta, nhead = write_skill(zp, sp, product, sid, tag, _date)
            with zipfile.ZipFile(sp) as zf2:
                n2 = len([n for n in zf2.namelist() if not n.endswith("/")])
            same = hashlib.sha256(open(zp, "rb").read()).hexdigest() == meta["payload_sha256"]
            print("built", sp, "（头部 %d B ＋ zip 负载 %d B）" % (nhead, meta["payload_bytes"]))
            print("  [i] 头部元数据：%s ｜ %s ｜ %s ｜ %s ｜ 条目 %d ｜ sha256 %s…"
                  % (meta["product"], meta["id"], meta["version"], meta["date"], meta["entries"],
                     meta["payload_sha256"][:16]))
            print("  [%s] .skill 解开即 %d 条目，负载与 .zip 字节一致"
                  % ("OK" if (n2 == n_entry and same) else "FAIL", n2))
        if fmt == "skill" and os.path.exists(zp):
            os.remove(zp)   # 只要 .skill 时，中间的 zip 不留
        if fmt == "zip" and os.path.exists(sp):
            os.remove(sp)
    return True

def read_skill_version(base):
    """从 SKILL.md frontmatter 读取版本串作为发布包标签（同时也是 zip 文件名的一部分）。

    不用写死的默认值：否则版本升级后忘记传 --tag，会静默打出旧版本标签的包。
    """
    try:
        with open(os.path.join(base, "SKILL.md"), encoding="utf-8-sig") as f:
            # 注意：frontmatter 的 description 会随版本变长（曾出现 1200 字符读不到 version 行、
            # 静默退化成 v0.0.0 包的事故），故取足 4000 字符，并只从 frontmatter 段内匹配。
            head = f.read(4000)
        m = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", head)
        if m:
            v = m.group(1).strip()
            # 四段式要求版本号**带小写 v**：frontmatter 里写 `3.11.5` 或 `V3.11.5` 都统一成 `v3.11.5`
            return "v" + re.sub(r"^[Vv]", "", v)
    except OSError:
        pass
    return "v0.0.0"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="生成唯一的发布 zip（上架版结构：第一层为技能目录 %s）" % SKILL_DIR)
    ap.add_argument("base", help="技能根目录（含 SKILL.md）")
    ap.add_argument("--out", help="输出目录，默认 <根>/_发布包")
    ap.add_argument("--include-private", action="store_true",
                    help="将 private/ 一并打入包内（默认排除；内含企业内控口径，慎用）")
    ap.add_argument("--tag", default=None, help="版本标签（默认自动读 SKILL.md frontmatter）")
    ap.add_argument("--keep-tools", action="store_true",
                    help="保留 config.json 里填好的工具路径（默认清空，避免作者本机路径随包外发）")
    ap.add_argument("--format", choices=["skill", "zip", "both"], default="both",
                    help="封装格式（默认 both＝两种都出，主格式为 .skill）："
                         "skill＝只出 .skill；zip＝只出 .zip（平台上传多认这个）")
    ap.add_argument("--date", default=None, metavar="YYYYMMDD",
                    help="文件名日期段（默认打包当天）。需复现某日包或 CI 固定日期时指定；"
                         "此参数**只影响文件名与 .skill 头部**，不改变包内容")
    a = ap.parse_args()
    if a.include_private:
        print("[警告] --include-private 已启用，private/（企业内控口径）将被打入发布包，"
              "请确认发布对象，勿对外发布。")
    if a.keep_tools:
        print("[注意] --keep-tools 已启用：config.json 的工具路径将**原样入包**，"
              "确认这些路径对接收方有效。")
    ok = build(a.base, a.out or os.path.join(a.base, "_发布包"), a.include_private,
               a.tag or read_skill_version(a.base), a.keep_tools, a.format, a.date)
    sys.exit(0 if ok else 1)
