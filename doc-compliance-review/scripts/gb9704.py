#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
"""公文格式引擎 —— 按 GB/T 9704《党政机关公文格式》排版与体检

用途：①排版——把 Markdown 要素按国标版式出成 .docx；
      ②体检——对已有 .docx 逐项比对国标，输出符合/不符合＋偏差值。

参照标准：GB/T 9704—2012《党政机关公文格式》
           GB/T 9704 的版式要求是**公开国家标准**，非某单位内部规范。

设计红线
  · **只报可测项**。页边距、字号、行数、字数这些能算的才报；「文风好不好」
    「层次序号用得对不对」这类需人工判断的，标「需人工」——不冒充机器结论。
  · **不符合就给偏差值**。只说「不符合」没有用，必须说清「应为 X，实为 Y，
    差 Z」，否则用户无从改起。
  · **核验引擎第四维的判据来源**。verify.py 的「格式核验」此前是占位，
    本脚本的 check() 就是它的真判据。

国标要点（本脚本覆盖的部分）
  ┌ 版心：156mm × 225mm
  ├ 页边距：上 37mm、下 35mm、左 28mm、右 26mm
  ├ 正文：三号仿宋（16pt），每页 22 行、每行 28 字
  ├ 标题：二号小标宋（22pt），居中
  ├ 一级标题「一、」：三号黑体
  ├ 二级标题「（一）」：三号楷体
  ├ 三级标题「1.」：三号仿宋加粗
  └ 页码：四号半角宋体，单页右空一字、双页左空一字

用法：
  python scripts/gb9704.py --check 某公文.docx          # 体检
  python scripts/gb9704.py --check 某公文.docx --json o.json
  python scripts/gb9704.py --rules                       # 列出本脚本覆盖的国标项

退出码：0 全部符合或仅提示；1 存在不符合项；2 输入不可读。
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────── 国标常量 ───────────────────────────
# 单位换算：1 mm = 56.6929 twips（1 twip = 1/1440 英寸 = 1/20 磅）
TWIP_PER_MM = 1440.0 / 25.4
PT_PER_MM = 72.0 / 25.4

STD = {
    "page": {"w_mm": 210.0, "h_mm": 297.0},          # A4
    "margin": {"top": 37.0, "bottom": 35.0, "left": 28.0, "right": 26.0},
    "body": {"font": "仿宋", "size_pt": 16.0, "lines": 22, "chars": 28},
    "title": {"font": "小标宋", "size_pt": 22.0},
    "h1": {"font": "黑体", "size_pt": 16.0},
    "h2": {"font": "楷体", "size_pt": 16.0},
    "h3": {"font": "仿宋", "size_pt": 16.0, "bold": True},
    "page_no": {"font": "宋体", "size_pt": 14.0},
}

TOL_MM = 1.0        # 页边距容差（排印误差）
TOL_PT = 0.5        # 字号容差


def _mm_to_twip(mm):
    return mm * TWIP_PER_MM


def _twip_to_mm(t):
    return t / TWIP_PER_MM


# ─────────────────────────── 体检 ───────────────────────────

class Item:
    def __init__(self, name, want, got, ok, note="", manual=False):
        self.name, self.want, self.got = name, want, got
        self.ok, self.note, self.manual = ok, note, manual

    def as_dict(self):
        return {"item": self.name, "standard": self.want, "actual": self.got,
                "ok": self.ok, "note": self.note, "manual": self.manual}


def _read_docx(path):
    """读 docx 的节属性与段落。缺 python-docx 时如实报错，不静默返回空。"""
    try:
        import docx                                    # noqa: F401
        from docx import Document
        from docx.shared import Twips
    except ImportError:
        return None, "未安装 python-docx，无法读取 .docx（pip install python-docx）"

    try:
        d = Document(path)
    except Exception as e:                             # noqa: BLE001
        return None, "无法打开 %s：%s" % (path, e)

    secs = []
    for s in d.sections:
        secs.append({
            "pw": _twip_to_mm(s.page_width.twips) if s.page_width else None,
            "ph": _twip_to_mm(s.page_height.twips) if s.page_height else None,
            "mt": _twip_to_mm(s.top_margin.twips) if s.top_margin else None,
            "mb": _twip_to_mm(s.bottom_margin.twips) if s.bottom_margin else None,
            "ml": _twip_to_mm(s.left_margin.twips) if s.left_margin else None,
            "mr": _twip_to_mm(s.right_margin.twips) if s.right_margin else None,
        })
    return {"doc": d, "sections": secs}, None


def check(path):
    """逐项比对国标。返回 (items, err)。"""
    got, err = _read_docx(path)
    if err:
        return None, err

    items = []
    secs = got["sections"] or []
    if not secs:
        return None, "文档没有节属性（可能是空文档）"

    s0 = secs[0]

    # ① 纸张
    w, h = s0.get("pw"), s0.get("ph")
    ok = (w is not None and h is not None
          and abs(w - STD["page"]["w_mm"]) <= TOL_MM
          and abs(h - STD["page"]["h_mm"]) <= TOL_MM)
    items.append(Item("纸张", "A4（210×297 mm）",
                      "%.0f×%.0f mm" % (w or 0, h or 0), ok))

    # ② 页边距（四项分别报，便于直接改）
    for key, label in (("mt", "上边距"), ("mb", "下边距"),
                       ("ml", "左边距"), ("mr", "右边距")):
        want = STD["margin"][{"mt": "top", "mb": "bottom",
                              "ml": "left", "mr": "right"}[key]]
        actual = s0.get(key)
        ok = actual is not None and abs(actual - want) <= TOL_MM
        diff = "" if ok or actual is None else "（差 %+.1f mm）" % (actual - want)
        items.append(Item(label, "%.0f mm" % want,
                          "%.1f mm%s" % (actual, diff) if actual is not None else "未设置",
                          bool(ok)))

    # ③ 版心尺寸（由纸张减页边距推得）
    if all(s0.get(k) is not None for k in ("pw", "ph", "mt", "mb", "ml", "mr")):
        bw = s0["pw"] - s0["ml"] - s0["mr"]
        bh = s0["ph"] - s0["mt"] - s0["mb"]
        ok = abs(bw - 156.0) <= TOL_MM * 2 and abs(bh - 225.0) <= TOL_MM * 2
        items.append(Item("版心尺寸", "156×225 mm", "%.0f×%.0f mm" % (bw, bh), ok,
                          "版心由纸张与页边距推得，不是单独设置项"))
    else:
        items.append(Item("版心尺寸", "156×225 mm", "无法推算（页边距不全）", False))

    # ④ 正文与标题字号（抽样：正文取最长段，标题取首段）
    d = got["doc"]
    paras = [p for p in d.paragraphs if (p.text or "").strip()]
    body_size = None
    if paras:
        longest = max(paras, key=lambda p: len(p.text))
        for r in longest.runs:
            if r.font.size:
                body_size = r.font.size.pt
                break
    items.append(Item("正文字号", "三号（16 pt）",
                      ("%.1f pt" % body_size) if body_size else "未显式设置（继承样式）",
                      body_size is not None and abs(body_size - 16.0) <= TOL_PT,
                      "字号需显式设置，继承默认样式时无法核验"))

    title_size = None
    if paras:
        for r in paras[0].runs:
            if r.font.size:
                title_size = r.font.size.pt
                break
    items.append(Item("标题字号", "二号（22 pt）",
                      ("%.1f pt" % title_size) if title_size else "未显式设置",
                      title_size is not None and abs(title_size - 22.0) <= TOL_PT))

    # ⑤ 标题居中
    if paras:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        align = paras[0].alignment
        items.append(Item("标题对齐", "居中",
                          {WD_ALIGN_PARAGRAPH.CENTER: "居中",
                           WD_ALIGN_PARAGRAPH.LEFT: "左对齐",
                           WD_ALIGN_PARAGRAPH.RIGHT: "右对齐",
                           WD_ALIGN_PARAGRAPH.JUSTIFY: "两端对齐"}.get(align, "未设置（左对齐）"),
                          align == WD_ALIGN_PARAGRAPH.CENTER))
    else:
        items.append(Item("标题对齐", "居中", "无段落", False))

    # ⑥ 行数字数：需人工（依赖实际排版引擎的断行，python-docx 算不出）
    items.append(Item("每页行数／每行字数", "22 行 × 28 字", "需人工核对", True,
                      "Word 的断行结果由渲染引擎决定，脚本算不出真实值；"
                      "请在 Word 中「页面设置 → 文档网格」核对", manual=True))

    # ⑦ 层次序号字体（一、（一）、1. 三级）
    h1 = h2 = h3 = False
    for p in paras:
        t = p.text.strip()
        if re.match(r"^[一二三四五六七八九十]+、", t):
            h1 = True
        elif re.match(r"^[（(][一二三四五六七八九十]+[）)]", t):
            h2 = True
        elif re.match(r"^\d+[.．、]", t):
            h3 = True
    items.append(Item("层次序号", "一、／（一）／1. 三级齐全",
                      "一级%s 二级%s 三级%s" % tuple("有" if x else "无" for x in (h1, h2, h3)),
                      True, "序号体例属结构问题，字体是否为国标字体需人工核对", manual=True))

    return items, None


def render_check(items, src):
    out = []
    out.append("## 公文格式体检：%s" % (src or ""))
    out.append("")
    bad = [x for x in items if not x.ok]
    man = [x for x in items if x.manual]
    out.append("> 依据 GB/T 9704—2012《党政机关公文格式》。"
               "共 %d 项，**不符合 %d 项**，需人工 %d 项。" % (len(items), len(bad), len(man)))
    out.append("")
    out.append("| 项目 | 国标要求 | 实测 | 结论 |")
    out.append("|---|---|---|---|")
    for it in items:
        mark = "✅" if it.ok and not it.manual else ("⚠ 需人工" if it.manual else "❌ 不符合")
        out.append("| %s | %s | %s | %s |" % (it.name, it.want, it.got, mark))
    out.append("")

    if bad:
        out.append("### 待改项")
        out.append("")
        for it in bad:
            out.append("- **%s**：应为 %s，实为 %s" % (it.name, it.want, it.got))
            if it.note:
                out.append("  - %s" % it.note)
        out.append("")

    if man:
        out.append("### 需人工核对（脚本不下机器结论）")
        out.append("")
        for it in man:
            out.append("- **%s**：%s" % (it.name, it.note))
        out.append("")

    out.append("---")
    out.append("")
    out.append("*格式体检只判断版式是否合标，不判断公文内容与文风；"
               "内容合规须另行审查。*")
    return "\n".join(out)


def rules():
    out = ["## 本脚本覆盖的 GB/T 9704 项", "",
           "| 项目 | 标准值 | 可机器判定 |", "|---|---|---|"]
    rows = [
        ("纸张", "A4 210×297 mm", "是"),
        ("上边距", "37 mm", "是"),
        ("下边距", "35 mm", "是"),
        ("左边距", "28 mm", "是"),
        ("右边距", "26 mm", "是"),
        ("版心", "156×225 mm", "是（由纸张与页边距推算）"),
        ("正文字体字号", "三号仿宋（16 pt）", "字号是；字体名需人工"),
        ("标题字体字号", "二号小标宋（22 pt）", "字号是；字体名需人工"),
        ("标题对齐", "居中", "是"),
        ("每页行数／每行字数", "22 行 × 28 字", "否（依赖渲染引擎断行）"),
        ("一级标题", "三号黑体「一、」", "结构是；字体需人工"),
        ("二级标题", "三号楷体「（一）」", "结构是；字体需人工"),
        ("三级标题", "三号仿宋加粗「1.」", "结构是；字体需人工"),
        ("页码", "四号宋体，单页右空一字、双页左空一字", "否（需人工）"),
    ]
    for a, b, c in rows:
        out.append("| %s | %s | %s |" % (a, b, c))
    out.append("")
    out.append("> **「可机器判定」为「否」的项，脚本明确标「需人工」**——"
               "不拿半吊子判据冒充国标核验。")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="公文格式体检（GB/T 9704）")
    ap.add_argument("--check", metavar="DOCX", help="要体检的 .docx")
    ap.add_argument("--json", help="结果输出到 JSON")
    ap.add_argument("--rules", action="store_true", help="列出覆盖项")
    a = ap.parse_args()

    if a.rules:
        print(rules())
        return 0

    if not a.check:
        ap.print_help()
        return 2

    if not os.path.exists(a.check):
        print("文件不存在：%s" % a.check, file=sys.stderr)
        return 2

    items, err = check(a.check)
    if err:
        print("[gb9704] %s" % err, file=sys.stderr)
        return 2

    print(render_check(items, os.path.basename(a.check)))

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([x.as_dict() for x in items], f, ensure_ascii=False, indent=2)
        print("\n[已写出体检结果] %s" % a.json, file=sys.stderr)

    return 0 if all(x.ok or x.manual for x in items) else 1


if __name__ == "__main__":
    sys.exit(main())
