#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""
外部依赖自动探测与写回（scripts/detect-tools.py）
=================================================
用途：装机最大的摩擦是"手工填 LibreOffice / Poppler / Tesseract 的路径"。
      本脚本按**常见安装位置 → PATH** 的顺序探测，找到即可一键写回，不必再手抄路径；
      找不到会给出该工具的用途与"缺了会怎样"，便于决定装不装。

工具路径**允许自定义，但不强制**——不配也能用：留空时按 PATH 自动探测，填了绝对路径则优先用之，
路径失效时自动回退 PATH，不算错误。

配置分三层（后者覆盖前者）：
    内置默认值      tools 全空＝按 PATH 探测，**不含任何本机路径**
    config.json     随发布包分发，同样保持零本机痕迹
    config.local.json  **本机覆盖层**——`--write` 默认写这里，不进 git、不随包

故 `--write` 不会污染随包配置；把 config.local.json 删掉即彻底回到自动探测。

用法：
    python detect-tools.py              查看探测结果（外部工具 ＋ Python 环境，不改动任何文件）
    python detect-tools.py --write      把探测到的路径写入**本机覆盖层** config.local.json（推荐）
    python detect-tools.py --write-config   写回随包的 config.json（要把整包拷到别的机器时才用）
    python detect-tools.py --path <键>  只打印某项的解析结果（soffice/pdftotext/pdftoppm/tesseract/tessdata）
    python detect-tools.py --install-guide       打印**缺失项**的分平台安装命令
    python detect-tools.py --install-guide --out install-deps.bat
                                                 把命令写成脚本文件，自行核对后再运行

探测顺序（先命中先得）：常见安装位置（含版本目录通配）→ PATH 中的同名命令。
写回只覆盖**探测到的项**，未探测到的项保留原值，避免把已填好的路径清空。
退出码：必需依赖（LibreOffice）缺失为 1，其余为 0（缺可选依赖只提示、不判失败）。

**不联网、不自动安装**：安装指引只负责把**该敲的命令**摆出来（也可写成脚本文件），
由使用者自己决定跑不跑——装包会访问网络，这一步必须留在人的手里。
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import glob
import json
import shutil
import argparse

try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, HERE)
import _config as _cfgmod

CFG_PATH = _cfgmod.CONFIG_PATH
LOCAL_PATH = _cfgmod.LOCAL_PATH   # 本机覆盖层（不进 git、不随包）

# 各工具用途与缺失影响（写给人看：决定装不装）
USAGE = {
    "soffice": ("老格式转文本、docx 生成、PDF 导出", "必需"),
    "pdftotext": ("PDF 取字（文字型 PDF）", "推荐"),
    "pdftoppm": ("PDF 转图 / 扫描件处理", "推荐"),
    "tesseract": ("扫描件与图片 OCR（中文需 chi_sim）", "推荐"),
    "tessdata": ("OCR 语言包目录", "推荐（随 tesseract）"),
}

# Python 侧依赖：(导入名, pip 包名, 用途, 级别)
PY_DEPS = [
    ("docx", "python-docx", "Word 读取与生成（.docx 提取、9 类交付物）", "必需"),
    ("openpyxl", "openpyxl", "Excel 比对台账与清单", "推荐"),
    ("PIL", "Pillow", "头标绘制（只在重画 assets 时需要）", "可选"),
    ("markdown", "markdown", "HTML 交付物转换（缺失时自动降级内置转换器，HTML 照样出）", "可选"),
    ("pptx", "python-pptx", "PPT 讲解版（仅 2/8/9 报告讲解类；缺失时跳过不阻断）", "推荐"),
    ("matplotlib", "matplotlib", "思维导图 PNG（缺失时只出交互 HTML 导图，跳过不阻断）", "推荐"),
]

# 分平台安装命令（只列主流包管理器；使用者按自己机器挑一条）
INSTALL = {
    "soffice": {
        "win": ["winget install -e --id TheDocumentFoundation.LibreOffice",
                "choco install libreoffice -y",
                "scoop install libreoffice"],
        "mac": ["brew install --cask libreoffice"],
        "linux": ["sudo apt install -y libreoffice",
                  "sudo dnf install -y libreoffice",
                  "sudo pacman -S --noconfirm libreoffice"],
    },
    "poppler": {
        "win": ["winget install -e --id oschwartz10612.Poppler",
                "scoop install poppler"],
        "mac": ["brew install poppler"],
        "linux": ["sudo apt install -y poppler-utils",
                  "sudo dnf install -y poppler-utils",
                  "sudo pacman -S --noconfirm poppler"],
    },
    "tesseract": {
        "win": ["winget install -e --id UB-Mannheim.TesseractOCR",
                "choco install tesseract -y",
                "scoop install tesseract"],
        "mac": ["brew install tesseract tesseract-lang"],
        "linux": ["sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim",
                  "sudo dnf install -y tesseract tesseract-langpack-chi_sim",
                  "sudo pacman -S --noconfirm tesseract tesseract-data-chi_sim"],
    },
}

CHI_SIM_NOTE = {
    "win": "Windows 安装 Tesseract 时勾选 Chinese Simplified；已装则把 chi_sim.traineddata 放进 tessdata 目录。",
    "mac": "brew install tesseract-lang 已含中文包。",
    "linux": "包管理器装 tesseract-ocr-chi-sim（Debian/Ubuntu）或对应语言包。",
}


def _roots():
    """常见安装根目录（不含盘符字面量，避免路径写死）。"""
    out = []
    for k in ("ProgramFiles", "ProgramFiles(x86)", "SystemDrive"):
        v = os.environ.get(k) or ""
        if v:
            out.append(v if k != "SystemDrive" else v + os.sep)
    home = os.path.expanduser("~")
    out.append(os.path.join(home, "Tools"))
    # 推荐盘（有该盘才列入）
    for d in ("D:", "E:"):
        if os.path.exists(d + os.sep):
            out.append(d + os.sep)
            out.append(os.path.join(d + os.sep, "Program Files"))
            out.append(os.path.join(d + os.sep, "Tools"))
    return [r for r in out if r]


def candidates(key):
    """返回该工具的候选路径列表（按常见安装位置优先）。"""
    roots = _roots()
    out = []
    if key == "soffice":
        for r in roots:
            out.append(os.path.join(r, "LibreOffice", "program", "soffice.exe"))
        out += ["/usr/bin/soffice", "/usr/local/bin/soffice",
                "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    elif key in ("pdftotext", "pdftoppm"):
        for r in roots:
            out += sorted(glob.glob(os.path.join(r, "poppler", "*", "Library", "bin", key + ".exe")), reverse=True)
            out.append(os.path.join(r, "poppler", "bin", key + ".exe"))
        out += [os.path.join("/usr", "bin", key), os.path.join("/usr", "local", "bin", key)]
    elif key == "tesseract":
        for r in roots:
            out.append(os.path.join(r, "Tesseract-OCR", "tesseract.exe"))
            out.append(os.path.join(r, "tesseract", "tesseract.exe"))
        out += ["/usr/bin/tesseract", "/usr/local/bin/tesseract"]
    elif key == "tessdata":
        for r in roots:
            out.append(os.path.join(r, "Tesseract-OCR", "tessdata"))
            out.append(os.path.join(r, "tesseract", "tessdata"))
        out += ["/usr/share/tesseract-ocr/*/tessdata", "/usr/local/share/tessdata"]
    return [p for p in out if p]


def _which(name):
    w = shutil.which(name)
    return w or ""


def probe(key):
    """探测单个工具：返回 (路径, 来源)；未找到返回 ('', '')。"""
    for p in candidates(key):
        for hit in (glob.glob(p) if any(ch in p for ch in "*?") else [p]):
            if os.path.exists(hit):
                return hit, "常见安装位置"
    w = _which(key if key != "tessdata" else "")
    if w:
        return w, "PATH"
    # tessdata 无可执行文件：退而求其次，找 tesseract 旁边的 tessdata
    if key == "tessdata":
        tp, _ = probe("tesseract")
        if tp:
            cand = os.path.join(os.path.dirname(tp), "tessdata")
            if os.path.exists(cand):
                return cand, "随 tesseract"
    return "", ""


def chi_sim_ok(tessdata):
    return bool(tessdata) and os.path.exists(os.path.join(tessdata, "chi_sim.traineddata"))


def platform_key():
    p = _sys.platform
    if p.startswith("win"):
        return "win"
    if p == "darwin":
        return "mac"
    return "linux"


def probe_python():
    """Python 侧就绪检查：版本 ＋ 三个包能否导入。返回 [(导入名, pip名, 用途, 级别, 可用)]。"""
    out = []
    for mod, pip, usage, level in PY_DEPS:
        ok = False
        try:
            import importlib.util
            ok = importlib.util.find_spec(mod) is not None
        except Exception:
            ok = False
        out.append((mod, pip, usage, level, ok))
    return out


def pip_cmd(pkgs, plat=None):
    """pip 安装命令。Windows 用当前解释器绝对路径（避免装到别的 Python 里），
    mac/Linux 用 python3（为别的平台生成脚本时，本机路径在对方机器上不存在）。"""
    plat = plat or platform_key()
    exe = '"%s"' % _sys.executable if plat == "win" else "python3"
    return "%s -m pip install %s" % (exe, " ".join(pkgs))


def install_guide(miss_tools, miss_pips, plat, out_file=None):
    """生成缺失项的安装命令。out_file 非空时写成脚本文件（不执行）。"""
    lines = []
    if miss_tools or miss_pips:
        lines.append("缺失项安装命令（平台：%s）—— 逐条核对后再运行，装包会联网" % plat)
    if "soffice" in miss_tools:
        lines.append("")
        lines.append(":: LibreOffice（老格式转换、PDF 导出）")
        lines += ["    " + c for c in INSTALL["soffice"][plat]]
    if "pdftotext" in miss_tools or "pdftoppm" in miss_tools:
        lines.append("")
        lines.append(":: Poppler（PDF 取字 / 转图）")
        lines += ["    " + c for c in INSTALL["poppler"][plat]]
    if "tesseract" in miss_tools:
        lines.append("")
        lines.append(":: Tesseract（扫描件 OCR）")
        lines += ["    " + c for c in INSTALL["tesseract"][plat]]
    if "tesseract" in miss_tools or "tessdata" in miss_tools:
        # 顶格写：写进 .bat/.sh 时会被转成注释，不会被当成命令执行
        lines.append("中文语言包 chi_sim：%s" % CHI_SIM_NOTE[plat])
    if miss_pips:
        lines.append("")
        lines.append(":: Python 包")
        lines.append("    " + pip_cmd(miss_pips, plat))
    lines.append("")
    lines.append(":: 装完回到技能目录重跑：python scripts/detect-tools.py --write && python scripts/smoke-test.py --fast")

    if out_file:
        # 写成脚本：命令去缩进，说明行转注释（Windows 用 REM，其余用 #）
        mark = "REM " if plat == "win" else "# "
        body = []
        for l in lines:
            if l.startswith("    "):
                body.append(l[4:])
            elif l.strip():
                body.append(mark + l.lstrip(":").strip())
            else:
                body.append("")
        header = ("@echo off\nREM 由 detect-tools.py 生成 · 请逐行核对后运行（会联网）\n\n"
                  if plat == "win" else "#!/usr/bin/env bash\n# 由 detect-tools.py 生成 · 请逐行核对后运行（会联网）\n\n")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(body) + ("\npause\n" if plat == "win" else "\n"))
        print("[detect-tools] 已生成安装脚本：%s（未执行，请自行核对后运行）" % out_file)
        return lines
    for l in lines:
        print(l)
    return lines


def main():
    ap = argparse.ArgumentParser(description="外部依赖自动探测与写回")
    ap.add_argument("--write", action="store_true",
                    help="把探测到的路径写入本机覆盖层 config.local.json（推荐；不进 git、不随包）")
    ap.add_argument("--write-config", action="store_true",
                    help="写回随包的 config.json（仅当要把整包拷到别的机器；会把本机路径写进随包配置）")
    ap.add_argument("--path", metavar="键", help="只打印某项解析结果（soffice/pdftotext/pdftoppm/tesseract/tessdata）")
    ap.add_argument("--install-guide", action="store_true", help="打印**缺失项**的分平台安装命令（不执行、不联网）")
    ap.add_argument("--out", metavar="文件", help="配合 --install-guide：把命令写成 .bat/.sh 供核对后运行")
    a = ap.parse_args()

    cfg = _cfgmod.load()
    found = {}
    for k in ("soffice", "pdftotext", "pdftoppm", "tesseract", "tessdata"):
        cur = ((cfg.get("tools") or {}).get(k) or "").strip()
        if cur and os.path.exists(cur):
            found[k] = (cur, "（已填且存在）")
        else:
            found[k] = probe(k)

    if a.path:
        print(found.get(a.path, ("", ""))[0])
        return 0

    print("[detect-tools] 配置层：config.json（随包）＋ %s"
          % ("config.local.json（本机覆盖，已存在）" if os.path.exists(LOCAL_PATH)
             else "config.local.json（本机覆盖，尚未生成）"))
    print("[detect-tools] 探测结果：")
    for k, (p, src) in found.items():
        usage, level = USAGE[k]
        if p:
            print("    %-10s [可用] %-52s %s" % (k, p[:52], src))
        else:
            print("    %-10s [缺失] %-52s 用途：%s（%s）" % (k, "——", usage, level))
    td = found.get("tessdata", ("", ""))[0]
    if td:
        print("    中文语言包 chi_sim：%s" % ("已安装" if chi_sim_ok(td) else "未安装（OCR 中文将失败）"))

    py = probe_python()
    print("[detect-tools] Python 环境：%s" % _sys.version.split()[0])
    for mod, pip, usage, level, ok in py:
        print("    %-10s [%s] %-44s %s（%s）" % (mod, "可用" if ok else "缺失", pip[:44], usage, level))

    miss_tools = [k for k, (p, _) in found.items() if not p and k != "tessdata"]
    if "tesseract" in miss_tools:
        miss_tools.append("tessdata")
    miss_pips = [pip for _m, pip, _u, _l, ok in py if not ok]

    if a.install_guide:
        print("")
        if not miss_tools and not miss_pips:
            print("[detect-tools] 依赖齐全，无需安装。")
        else:
            install_guide(miss_tools, miss_pips, platform_key(), a.out)
        return 0

    if a.write or a.write_config:
        target = LOCAL_PATH if a.write else CFG_PATH
        tname = os.path.basename(target)
        data = {}
        if os.path.exists(target):
            try:
                with open(target, encoding="utf-8-sig") as f:
                    data = json.load(f) or {}
            except Exception as e:
                print("[detect-tools] %s 解析失败，将重建：%s" % (tname, e))
                data = {}
        tools = data.get("tools") or {}
        written = []
        for k, (p, src) in found.items():
            if p and src != "（已填且存在）":
                tools[k] = p
                written.append(k)
        data["tools"] = tools
        if target == LOCAL_PATH:
            data["_说明"] = ("本机工具路径覆盖层：由 detect-tools.py --write 生成，"
                            "**不进 git、不随发布包**；留空或删除本文件即回到按 PATH 自动探测。")
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("[detect-tools] 已写回 %s：%d 项（%s）"
              % (tname, len(written), "、".join(written) or "无新增，原配置已可用"))
        print("[detect-tools] 未探测到的项保持原值，未清空。")
        if target == LOCAL_PATH:
            print("[detect-tools] 该文件只在本机生效，不进发布包；删除它即彻底回到自动探测。")
    else:
        print("[detect-tools] 提示：加 --write 写入本机覆盖层（不污染随包配置）；"
              "--write-config 写回 config.json。")

    miss = [k for k, (p, _) in found.items() if not p]
    need_pip = [pip for _m, pip, _u, lv, ok in py if not ok and lv == "必需"]
    if need_pip:
        print("[detect-tools] 缺少必需的 Python 包：%s" % "、".join(need_pip))
        print("[detect-tools] 安装：" + pip_cmd(need_pip))
    if miss or miss_pips:
        print("[detect-tools] 缺什么、怎么装：python scripts/detect-tools.py --install-guide")
    if "soffice" in miss:
        print("[detect-tools] LibreOffice 未找到：老格式（.doc/.wps/.rtf/.odt）与 PDF 导出不可用，.docx 仍可直读。")
        return 1
    if miss:
        print("[detect-tools] 可选依赖缺失（不影响主流程）：%s" % "、".join(miss))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
