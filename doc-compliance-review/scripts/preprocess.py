#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
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
文档合规审查助手AI合同 · 文档预处理脚本（独立 / 可配置 / 可留痕）
===========================================================================
功能：接收 合同文件（.doc/.docx/.rtf/.wps/.pdf/图片/.txt）→ 格式识别 → 文本提取 → 清洗 →
      输出「清洗后文本（审查唯一依据）」+「提取原始文本」+「元数据/日志」，并保留原始文件副本。

用法：
  python preprocess.py [<输入文件或目录...>] [--base <工作根目录>] [--in 输入] [--out 输出] [--no-ocr]
  留空输入时：自动读取默认输入文件夹 <工作根目录>\输入（把批量文档拖进去即可）；
  产出：输出文件夹下按文档名建子目录（raw/ text/ meta/）。

产出（在输出目录内）：
  raw/<name>.<ext>          原始文件副本（留痕，永不删）
  text/<name>.raw.txt       提取的原始文本
  text/<name>.clean.txt     清洗后文本（后续审查唯一依据）
  meta/<name>.json          元数据 + 清洗日志 + 异常标记（供回溯原文）

原则（见 SKILL 步骤 1「文档预处理」）：恢复形式、不改实质；标记异常、不臆测；留痕可追溯；人机结合。
依赖（缺失可降级）：LibreOffice / Poppler(pdftotext,pdftoppm) / Tesseract 或 PaddleOCR。
"""
import os, re, sys, json, shutil, hashlib, argparse, subprocess, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ===== 配置读取（scripts/config.json > 内置默认值；工具缺失自动回退 PATH）=====
try:
    import _config as _cfgmod
    _CFG = _cfgmod.load()
    SOFFICE = _cfgmod.tool(_CFG, "soffice")
    PDFTOTEXT = _cfgmod.tool(_CFG, "pdftotext")
    PDFTOPPM = _cfgmod.tool(_CFG, "pdftoppm")
    TESSERACT, TESSDATA = _cfgmod.tess(_CFG)
    BASE_DIR = _cfgmod.workdir(_CFG, "base_dir")
except Exception as _e:  # 配置模块异常时保持可用（不写死盘符：工具回退 PATH，工作目录回退用户目录）
    print("[preprocess] 配置加载失败，使用内置默认值：", _e)
    SOFFICE   = "soffice"
    PDFTOTEXT = "pdftotext"
    PDFTOPPM  = "pdftoppm"
    TESSERACT = "tesseract"
    TESSDATA  = ""
    BASE_DIR  = os.path.join(os.path.expanduser("~"), "文档合规审查报告")

IN_DIR   = os.path.join(BASE_DIR, "输入")
OUT_DIR  = os.path.join(BASE_DIR, "输出")
# 说明：以上均可被 config.json 覆盖，亦可由命令行 --base/--in/--out 覆盖。
# ============================================

DOC_EXTS = {".doc", ".docx", ".dot", ".dotx", ".rtf", ".wps", ".odt"}
# zip 容器的 Word 系：python-docx 可直读（约 0.015 s/份），优先走原生直读，不走外部转换器。
ZIP_DOC_EXTS = {".docx", ".dotx", ".docm", ".dotm"}
PDF_EXTS = {".pdf"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
TXT_EXTS = {".txt", ".md"}

def log(*a): print("[preprocess]", *a)

def sha256(path, n=1<<20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(n), b""):
            h.update(chunk)
    return h.hexdigest()

def sniff(path):
    """格式识别：扩展名 + 内容嗅探"""
    ext = os.path.splitext(path)[1].lower()
    head = open(path, "rb").read(8)
    if head[:4] == b"\xd0\xcf\x11\xe0":   fmt = "ole(doc/wps)"
    elif head[:2] == b"PK":               fmt = "zip(docx/odt)"
    elif head[:4] == b"%PDF":             fmt = "pdf"
    elif ext in IMG_EXTS:                 fmt = "image"
    elif ext in TXT_EXTS:                 fmt = "text"
    else:                                 fmt = "unknown"
    return ext, fmt

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    except Exception as e:
        log("命令失败:", cmd, e); return None

def soffice_ready():
    """LibreOffice 是否可用：配置的绝对路径存在，或命令名在 PATH 中。"""
    p = (SOFFICE or "").strip()
    if not p:
        return False
    if os.path.isabs(p):
        return os.path.exists(p)
    return bool(shutil.which(p))


def extract_docx_native(path):
    """不依赖 LibreOffice：用 python-docx 直读段落与表格（仅 zip 类 docx/dotx/docm）。

    主用途：docx 是最高频格式，直读约 0.015 s/份，比 LibreOffice 转换（约 9 s/份）快两个数量级，
    故对可直读格式**优先直读**，直读为空才回退转换器。
    老格式（.doc/.wps/.rtf/.odt，OLE 复合文档）python-docx 打不开，只能靠转换器，故返回空串。
    """
    try:
        from docx import Document
        doc = Document(path)
    except Exception as e:
        log("python-docx 直读失败:", e)
        return ""
    parts = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)
    for tb in doc.tables:
        for row in tb.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(x for x in cells if x))
    return "\n".join(parts)


def extract_office(path, outdir, force_convert=False):
    """Office → 文本，返回 (文本, 取道)。

    取道顺序（性能优先，产出文本一致）：
      1. docx/dotx/docm/dotm（zip 容器）→ python-docx 直读，约 0.015 s/份；
         **直读为空才回退** LibreOffice 转换。
      2. 老格式（.doc/.wps/.rtf/.odt，OLE 复合文档）→ python-docx 打不开，只能走转换器。
      3. --force-convert：一律走转换器（用于对齐旧产出文本或排查直读差异）。
    转换器不可用且无法直读时返回空文本并说明，由上层按「提取失败」处理。
    """
    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    if not force_convert and ext in ZIP_DOC_EXTS:
        native = extract_docx_native(path)
        if native.strip():
            log("python-docx 直读：", name)
            return native, "native"
        log("python-docx 直读为空 → 回退转换器：", name)
    if not soffice_ready():
        log("未检测到 LibreOffice，且该格式未能直读（.doc/.wps/.rtf/.odt 需转换器）：", name)
        return "", "native-fail"
    run([SOFFICE, "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", outdir, path])
    base = os.path.splitext(os.path.basename(path))[0]
    t = os.path.join(outdir, base + ".txt")
    txt = open(t, encoding="utf-8", errors="ignore").read() if os.path.exists(t) else ""
    if not txt.strip():
        native = extract_docx_native(path)
        if native:
            log("LibreOffice 转换结果为空 → python-docx 直读兜底：", name)
            return native, "native"
    return txt, "soffice"

def extract_pdf(path, outdir, allow_ocr=True):
    base = os.path.splitext(os.path.basename(path))[0]
    t = os.path.join(outdir, base + ".pdftotext.txt")
    run([PDFTOTEXT, "-layout", path, t])
    txt = open(t, encoding="utf-8", errors="ignore").read() if os.path.exists(t) else ""
    if len(txt.strip()) >= 50 or not allow_ocr:
        return txt, ("text" if txt.strip() else "empty")
    # 扫描件 → OCR
    log("PDF 文本层为空/过少 → 走 OCR：", os.path.basename(path))
    imgprefix = os.path.join(outdir, base + ".page")
    run([PDFTOPPM, "-r", "200", "-png", path, imgprefix])
    pages = sorted(f for f in os.listdir(outdir) if f.startswith(base + ".page") and f.endswith(".png"))
    parts = []
    env = dict(os.environ); env["TESSDATA_PREFIX"] = TESSDATA
    for p in pages:
        img = os.path.join(outdir, p)
        outp = os.path.join(outdir, p + ".ocr")
        r = subprocess.run([TESSERACT, img, outp, "-l", "chi_sim"],
                           encoding="utf-8", errors="replace",
                           capture_output=True, text=True, env=env)
        if os.path.exists(outp + ".txt"):
            parts.append(open(outp + ".txt", encoding="utf-8", errors="ignore").read())
    return "\n".join(parts), "ocr"

def extract_image(path, outdir):
    base = os.path.splitext(os.path.basename(path))[0]
    outp = os.path.join(outdir, base + ".ocr")
    env = dict(os.environ); env["TESSDATA_PREFIX"] = TESSDATA
    subprocess.run([TESSERACT, path, outp, "-l", "chi_sim"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    t = outp + ".txt"
    return open(t, encoding="utf-8", errors="ignore").read() if os.path.exists(t) else "", "ocr"

def clean_text(raw):
    """清洗：恢复形式、不改实质。返回 (clean, log[], anomalies[])"""
    lg, an = [], []
    t = raw.replace("\ufeff", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # 控制字符（保留 \n \t）
    t2 = "".join(ch for ch in t if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if t2 != t: lg.append("去除控制字符")
    t = t2
    lines = t.split("\n")
    out, buf = [], []
    page_re = re.compile(r"^\s*(第\s*\d+\s*页\s*(/\s*共?\s*\d+\s*页)?|[-—]?\s*\d{1,4}\s*[-—]?|page\s*\d+)\s*$", re.I)
    # 合并硬换行（行尾无标点，且下一行非编号/条款开头）
    def flush():
        if buf: out.append("".join(buf)); buf.clear()
    start_re = re.compile(r"^\s*(第[一二三四五六七八九十百零0-9]+条|第[一二三四五六七八九十]+[章部分]|[0-9]+[\.、]|（[一二三四五六七八九十0-9]+）|\([0-9]+\))")
    for ln in lines:
        s = ln.strip()
        if page_re.match(s):                      # 页码/页眉页脚
            flush(); continue
        if s == "":
            flush(); out.append(""); continue
        if start_re.match(s):                     # 新条款 → 断行
            flush(); out.append(s); continue
        if buf and not re.search(r"[。；;：:！？!?)”）】]$", buf[-1]):
            buf.append(s)                         # 续行合并
        else:
            flush(); buf.append(s)
    flush()
    t = "\n".join(out)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    lg.append("统一换行/空白、合并硬换行、去页码")
    # 异常标记（供人工抽检）
    if re.search(r"\ufffd|\u25a0|\u25a1", t): an.append("发现乱码字符（U+FFFD/方块），需人工校对")
    if len(t) < 50:                            an.append("提取文本过少，疑为扫描件或提取失败")
    # 关键项存在性提示
    for kw, name in [(r"金额|价款|总价|人民币|￥|¥|元", "金额"), (r"期限|有效期|起止|至", "期限"),
                     (r"签[字章]|盖章|法定代表人", "签字页")]:
        if not re.search(kw, t): an.append(f"未见明显「{name}」表述，建议人工抽检")
    return t, lg, an

def process_one(path, outroot, allow_ocr=True, force_convert=False):
    name = os.path.splitext(os.path.basename(path))[0]
    ext, fmt = sniff(path)
    for d in ("raw", "text", "meta", "_tmp"):
        os.makedirs(os.path.join(outroot, d), exist_ok=True)
    tmp = os.path.join(outroot, "_tmp")
    # 原始文件副本（留痕）
    rawcopy = os.path.join(outroot, "raw", os.path.basename(path))
    shutil.copy2(path, rawcopy)
    # 提取
    src = "office"
    if fmt.startswith("ole") or fmt.startswith("zip") or ext in DOC_EXTS:
        raw, how = extract_office(path, tmp, force_convert=force_convert)
        src = "office" if how == "soffice" else "office-native"
    elif fmt == "pdf":
        raw, kind = extract_pdf(path, tmp, allow_ocr); src = "pdf-text" if kind == "text" else "pdf-ocr"
    elif fmt == "image":
        raw, kind = extract_image(path, tmp); src = "image-ocr"
    elif fmt == "text" or ext in TXT_EXTS:
        raw = open(path, encoding="utf-8", errors="ignore").read(); src = "text"
    else:
        raw = ""; src = "unknown"
    clean, lg, an = clean_text(raw)
    with open(os.path.join(outroot, "text", name + ".raw.txt"), "w", encoding="utf-8") as f: f.write(raw)
    with open(os.path.join(outroot, "text", name + ".clean.txt"), "w", encoding="utf-8") as f: f.write(clean)
    meta = {
        "file": os.path.basename(path), "ext": ext, "format": fmt, "extract_source": src,
        "sha256": sha256(path), "size": os.path.getsize(path),
        "pages_chars_raw": len(raw), "chars_clean": len(clean),
        "cleaning_log": lg, "anomalies": an,
        "processed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": "清洗结果仅作审查依据；原始文件见 raw/；发现疑点请回溯 raw 原文核对。",
    }
    with open(os.path.join(outroot, "meta", name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    for d in ("_tmp",):
        shutil.rmtree(os.path.join(outroot, d), ignore_errors=True)
    log(f"完成：{name}  [{fmt}/{src}]  清洗字符 {len(clean)}  异常 {len(an)}")
    return meta

def main():
    ap = argparse.ArgumentParser(description="合同文档预处理（提取+清洗+留痕）")
    ap.add_argument("inputs", nargs="*", help="输入文件或目录（留空则读默认输入文件夹）")
    ap.add_argument("--base", default=None, help="工作根目录（默认 D:\\文档合规审查报告）")
    ap.add_argument("--in", dest="indir", default=None, help="输入文件夹（默认 <base>\\输入）")
    ap.add_argument("--out", default=None, help="输出目录（默认 <base>\\输出）")
    ap.add_argument("--no-ocr", action="store_true", help="禁用 OCR（扫描件仅标记）")
    ap.add_argument("--force-convert", action="store_true",
                    help="docx 类也强制走 LibreOffice 转换（默认直读，快约两个数量级；用于对齐旧产出文本）")
    args = ap.parse_args()
    base = args.base or BASE_DIR
    indir = args.indir or os.path.join(base, "输入")
    outdir = args.out or os.path.join(base, "输出")
    os.makedirs(indir, exist_ok=True); os.makedirs(outdir, exist_ok=True)
    inputs = list(args.inputs)
    if not inputs:
        inputs = [indir]
        log("未指定输入，读取默认输入文件夹：", os.path.abspath(indir))
    files = []
    missing = []
    for p in inputs:
        if os.path.isdir(p):
            for r, _, fs in os.walk(p):
                for f in fs: files.append(os.path.join(r, f))
        elif os.path.exists(p):
            files.append(p)
        else:
            missing.append(p)
    # ⚠ 2026-10-20 全量质检修（独立复核实测坐实）：输入文件不存在原来会被
    #   process_one 抛错 → except 记"跳过"→ 最终 exit 0，批量调用方/CI 全部假过。
    #   输入不存在属用法错误（exit 2），与"处理失败"（exit 1）分开。
    if missing:
        log("输入不存在（请核对路径）：", "、".join(os.path.abspath(p) for p in missing)); sys.exit(2)
    KNOWN = DOC_EXTS | PDF_EXTS | IMG_EXTS | TXT_EXTS
    files = [f for f in files if os.path.splitext(f)[1].lower() in KNOWN]
    if not files:
        log("输入文件夹内未发现可处理文档（支持 doc/docx/rtf/wps/odt/pdf/图片/txt/md）：", os.path.abspath(indir)); sys.exit(2)
    ok = 0
    for f in files:
        try:
            sub = os.path.join(outdir, os.path.splitext(os.path.basename(f))[0])
            process_one(f, sub, allow_ocr=not args.no_ocr, force_convert=args.force_convert); ok += 1
        except Exception as e:
            log("跳过（错误）：", f, e)
    log(f"共处理 {ok}/{len(files)} 个文件；来源：{'、'.join(os.path.abspath(p) for p in inputs[:3])}{' 等' if len(inputs) > 3 else ''}；输出：{os.path.abspath(outdir)}")
    if ok < len(files):
        sys.exit(1)   # 有文件处理失败：与"全部成功"分开，调用方可按退出码判

if __name__ == "__main__":
    main()
