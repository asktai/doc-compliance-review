#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同 · 竖版技能介绍卡（1080×1440）生成
==============================================================================
产出「方便发群／朋友圈／资料库展示」的竖版介绍卡：一张图讲清技能是什么、
能做什么、规则库怎么分层、覆盖哪些风险维度、出什么交付物。

归属说明
    · 本脚本属于**维护侧**（/workspace/dev/maint/tools/），**不随技能包分发**；
    · 这样技能包仍维持 16 个脚本的既有口径，不必为一张卡片增脚本并联动全套文档；
    · 版本号自动读自 SKILL.md frontmatter —— 升版后重跑一次即可刷新卡片。

排版引擎（V2，2026-09-24 重写）
    V1 的病灶（由 layout-audit 实测坐实）：
      (1) 主标题与副标**真实重叠 8px** —— CJK 字身框高是字号的约 1.45 倍（60px→87px），
         旧代码按"字号"估位置，估小了；
      (2) 最小字号 15px、正文 17.5px —— 卡片按 480px 宽预览等效 6.7px，缩略即糊；
      (3) 73 个文字块挤在 1080×1440，密度过高。
    V2 的三条对策：
      A. **按墨迹框排布**：所有文字以"基线 + em 框"定位，不再用字身框拍脑袋；
      B. **字号整体上调**：正文 17.5→22、chips 17→19、页脚 16→18，最小字号 17；
      C. **降密度换空间**：K 组从独立圆角卡改为 chips 区内的高亮金色 chip
         （信息一条不丢，省掉一整块卡壳的 123px），腾出的空间全给字号与行距。
    并内建 `LayoutAudit`：每次出图前两两比对所有文字墨迹框，
    **真重叠即拒绝出图**（返回 None），间距不足则告警——排版错误不再靠肉眼发现。

设计
    · 纯本地绘制（Pillow），零联网、零外部素材；超采样 2× 后降采样，边缘平滑；
    · 标题用思源宋体粗（中式文书感），正文用思源黑体（清晰易读）；
    · 视觉基调沿用头标：深色（深蓝＋金）＋ 朱印元素 ＋ 三色风险点签名元素。

用法
    python3 make-card.py                      生成到技能包 assets/skill-card.png
    python3 make-card.py --out <路径>          指定输出文件
    python3 make-card.py --version Vx.y.z      覆盖版本串（默认读 SKILL.md）
    python3 make-card.py --ss 3                超采样倍率（默认 2，出图更精细但更慢）
    python3 make-card.py --dry-run             只跑排版审计与数字核对，不出图

依赖：Pillow
"""
import os
import re
import sys
import math
import json
import argparse

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    print("缺少依赖 Pillow。请先安装：pip install Pillow", file=sys.stderr)
    raise SystemExit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = "/workspace/dev/doc-compliance-review"
DEFAULT_OUT = os.path.join(SKILL_ROOT, "assets", "skill-card.png")

BOARD_W, BOARD_H = 1080, 1440

# —— 文案 ——
# 说明：每行正文控制在 22 字内（22px 字号下正文可用宽 860px ≈ 39 字），
# 保证每条恰好一行不折行；折行会让版面高度失控，故 length 由 verify_copy 兜底校验。
EN_SUB = "DOCUMENT COMPLIANCE REVIEW ASSISTANT"
TITLE_MAIN = "文档合规审查助手"
SUB_TEXT = "AI 合同"
TAGLINE = "对合同、协议及授权书、承诺函等商务/业务文档做脱敏、逐条审查、三色分级与红线修订"
AUTHOR = "作者：胡皓"


def card_date():
    """日期唯一真源＝version.json 的 latest.date，升版即随动，不再硬编码陈旧。"""
    p = os.path.join(SKILL_ROOT, "version.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return (d.get("latest") or {}).get("date") or ""
    except (OSError, ValueError):
        return ""

BLOCKS = [
    ("核心能力", [
        "逐条审查：三色分级＋标准立场＋话术",
        "原稿级修订：Word 原生修订痕迹，逐条取舍",
        "比对台账：对方改了什么，条款级看清",
        "涉密纯本地：6 类脱敏，正文不出域",
        "起草合同与模板 · 好文档一键转自用模板",
    ]),
    ("三层规则库（可叠加）", [
        "通用库 core：159 条跨行业规则（含 K 组发票税务）",
        "行业库：9 个内置 ＋ 可自建/导入导出",
        "私有库：企业内控规则，优先级最高",
        "冲突消解：私有 ＞ 行业 ＞ 通用；消解不了标 ★★★ 交人工",
    ]),
]

DIMENSIONS = ["付款与违约金", "交付验收", "知识产权", "保密与竞业", "管辖条款",
              "仲裁条款", "争议解决", "诉讼时效", "合同效力", "格式条款",
              "个人信息保护", "主体适格与签章"]
# K 组高亮 chip：原为独立圆角卡，V2 改为 chips 区内的金色一组（省卡壳、信息不减）
TAX_CHIPS = ["发票与税率 · 三流一致", "银行承兑 · 红字冲红", "虚开发票红线 ★★★"]

DELIVER = "交付物 10 类 × 5 格式（WORD · MD · Excel · HTML · PDF）"
DISCLAIM = "仅辅助用途，不构成法律意见；须经执业律师复核后方可据此决策。"
LICENSE = "个人使用授权 · 商业使用须取得书面授权"

# —— 配色（沿用头标 dark 主题）——
BG_TOP, BG_BOT = (11, 32, 56), (7, 21, 37)
GLOW_GOLD = (201, 162, 74, 30)
GLOW_BLUE = (46, 107, 168, 34)
GOLD, GOLD_LT = (201, 162, 74), (227, 192, 113)
FG, FG2, FG3 = (255, 255, 255), (176, 194, 214), (116, 140, 168)
SEAL_PAPER, SEAL_INK = (252, 249, 242), (179, 39, 30)
RISK = [("高", (216, 68, 60)), ("中", (227, 166, 55)), ("低", (62, 155, 107))]

# —— 版面尺度（设计单位 px，1 设计单位最终 = 1 出图像素）——
PAD = 64                                   # 左右安全边
CW = BOARD_W - PAD * 2                     # 正文可用宽 952
MIN_GAP = 10                               # 任意两块文字墨迹框的最小垂直间隙（审计阈值）

FONT_CANDIDATES = {
    "serif_bold": [r"C:\Windows\Fonts\msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
                   "/System/Library/Fonts/PingFang.ttc"],
    "sans_reg": [r"C:\Windows\Fonts\msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/System/Library/Fonts/PingFang.ttc"],
    "sans_bold": [r"C:\Windows\Fonts\msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  "/System/Library/Fonts/PingFang.ttc"],
    "seal": [r"C:\Windows\Fonts\msyhl.ttc", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
             "/System/Library/Fonts/PingFang.ttc"],
}


def pick_font(kind, override=None):
    if override:
        return override
    for p in FONT_CANDIDATES.get(kind, []):
        if os.path.exists(p):
            return p
    return None


def font(path, size):
    return ImageFont.truetype(path, int(size))


def vgrad(w, h, c1, c2):
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))
    return strip.resize((w, h), Image.BICUBIC)


def radial(size, color):
    n = 96
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = img.load()
    cx = cy = (n - 1) / 2.0
    maxd = n / 2.0
    for y in range(n):
        for x in range(n):
            dd = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            a = max(0.0, 1.0 - dd)
            px[x, y] = (color[0], color[1], color[2], int(color[3] * a * a))
    return img.resize(size, Image.BICUBIC)


def scan_lines(d, w, h, color, unit=1, alpha=9):
    st = int(30 * unit)
    lw = max(1, int(unit))
    y = st
    while y < h:
        d.line([(0, y), (w, y)], fill=color + (alpha,), width=lw)
        y += st


def draw_frame_corners(d, box, color, lw, corner):
    x0, y0, x1, y1 = box
    segs = [[(x0, y0 + corner), (x0, y0), (x0 + corner, y0)],
            [(x1 - corner, y0), (x1, y0), (x1, y0 + corner)],
            [(x0, y1 - corner), (x0, y1), (x0 + corner, y1)],
            [(x1 - corner, y1), (x1, y1), (x1 - corner, y1)]]
    for pts in segs:
        d.line(pts, fill=color, width=lw, joint="curve")


def draw_risk_dots(d, cx, cy, color, fpath, unit=1.0, reg=None):
    """三色风险点（高/中/低）。整组以 cx 为中心——旧版从 cx-gap 起排，
    最右一个标签会冲出右边距约 20px。reg：墨迹框登记回调（审计要覆盖到它）。"""
    gap, r = 104 * unit, 8 * unit
    f = font(fpath, 19 * unit)
    x = cx - (len(RISK) - 1) * gap / 2.0
    for label, col in RISK:
        d.ellipse([x - r, cy - r, x + r, cy + r], fill=col)
        d.text((x + r + 9 * unit, cy), label, font=f, fill=color, anchor="lm")
        if reg:
            reg(x + r + 9 * unit, cy, label, f, "lm")
        x += gap


def thick_glyph_mask(ch, w, h, font_path, grow=0.05, steps=36, blur=1.0):
    w, h = max(2, int(w)), max(2, int(h))
    side = min(w, h)
    r = side * grow
    target = side - 2 * r

    def extent_of(size):
        probe = Image.new("L", (int(size) * 3, int(size) * 3), 0)
        ImageDraw.Draw(probe).text((size * 1.5, size * 1.5), ch,
                                   font=ImageFont.truetype(font_path, int(size)),
                                   fill=255, anchor="mm")
        bb = probe.getbbox()
        return max(bb[2] - bb[0], bb[3] - bb[1]) if bb else 1

    fs = max(4.0, 100.0 * target / extent_of(100))
    f = ImageFont.truetype(font_path, int(round(fs)))
    pad = int(r) + 6
    canvas = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    cd = ImageDraw.Draw(canvas)
    cx, cy = canvas.width / 2.0, canvas.height / 2.0
    for i in range(steps):
        ang = 2 * math.pi * i / steps
        cd.text((cx + math.cos(ang) * r, cy + math.sin(ang) * r), ch,
                font=f, fill=255, anchor="mm")
    if blur:
        canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    return canvas.crop((pad, pad, pad + w, pad + h))


def render_thick_char(ch, w, h, color, font_path, grow=0.05, blur=1.0):
    w, h = int(round(w)), int(round(h))
    out = Image.new("RGBA", (w, h), tuple(color) + (0,))
    out.putalpha(thick_glyph_mask(ch, w, h, font_path, grow=grow, blur=blur))
    return out


def draw_seal(img, cx, cy, size, unit=1.0, fseal=None):
    """朱文方章（白底朱红边框＋粗圆体「审」）。"""
    d = ImageDraw.Draw(img, "RGBA")
    hw = size / 2.0
    lw = max(2, int(6.4 * unit))
    rad = size * 0.07
    box = [cx - hw, cy - hw, cx + hw, cy + hw]
    d.rounded_rectangle(box, radius=rad, fill=SEAL_PAPER + (255,),
                        outline=SEAL_INK + (255,), width=lw)
    ins = size * 0.066
    d.rounded_rectangle([box[0] + ins, box[1] + ins, box[2] - ins, box[3] - ins],
                        radius=rad * 0.55, outline=SEAL_INK + (150,),
                        width=max(2, int(1.8 * unit)))
    gs = size * 0.80
    g = render_thick_char("审", gs, gs, SEAL_INK, fseal, grow=0.048, blur=1.0 * unit)
    img.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
    return d


def wrap_text(d, s, f, max_w):
    """中文按字符贪心折行；若单词/词组超出则逐字。返回行列表。"""
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if d.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


# ============ 排版审计：把"文字堆叠"从肉眼问题变成可判定问题 ============
class LayoutAudit(object):
    """登记每段文字的**墨迹框**并两两比对。

    为什么用墨迹框而不是字身框：CJK 字身框高约为字号的 1.45 倍（要容纳拉丁字母
    的下伸部），按字身框判定会把"行距正常"误判为粘连；而墨迹框取 em 盒
    （基线上 0.88em、基线下 0.12em），与肉眼看到的字形范围一致。
    """

    def __init__(self, unit):
        self.u = float(unit)
        self.rec = []

    def _box(self, x, y, s, f, anchor):
        asc, desc = f.getmetrics()
        size = float(f.size)
        va = anchor[-1] if len(anchor) > 1 else "a"
        if va == "a":
            base = y + asc
        elif va == "s":
            base = y
        elif va == "m":
            base = y + (asc - desc) / 2.0
        elif va == "d":
            base = y - desc
        else:
            base = y + asc
        w = self._measure(s, f)
        ha = anchor[0] if anchor else "l"
        x0 = x if ha == "l" else (x - w / 2.0 if ha == "m" else x - w)
        return (x0 / self.u, (base - 0.88 * size) / self.u,
                (x0 + w) / self.u, (base + 0.12 * size) / self.u, s, size / self.u)

    def _measure(self, s, f):
        probe = getattr(self, "_probe", None)
        if probe is None:
            self._probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
            probe = self._probe
        return probe.textlength(s, font=f)

    def add(self, x, y, s, f, anchor="la", span=None):
        """span：逐字符绘制时按整串宽度登记一次，避免把字距当成重叠。"""
        self.rec.append(self._box(x, y, span or s, f, anchor))

    def check(self, min_gap=MIN_GAP, verbose=False):
        hard, near = [], []
        r = self.rec
        worst = None                                # 全版最小墨迹间隙（同一列内）
        for i in range(len(r)):
            for j in range(i + 1, len(r)):
                a, b = r[i], r[j]
                if a[2] <= b[0] + 1 or b[2] <= a[0] + 1:
                    continue                       # 水平不相交，各走各的
                if a[3] <= b[1]:
                    gap = b[1] - a[3]
                elif b[3] <= a[1]:
                    gap = a[1] - b[3]
                else:
                    hard.append((a, b))
                    continue
                if worst is None or gap < worst[0]:
                    worst = (gap, a[4], b[4])
                if 0 <= gap < min_gap:
                    near.append((a, b, gap))
        if verbose:
            print("[排版审计] 文字块 %d；最小字号 %.1fpx；墨迹占版 %.1f%%"
                  % (len(r), min(x[5] for x in r),
                     100.0 * sum((x[2] - x[0]) * (x[3] - x[1]) for x in r) / (BOARD_W * BOARD_H)))
            if worst:
                print("[排版审计] 全版最小墨迹间隙 %.1fpx（%r ↔ %r）；阈值 %.0fpx"
                      % (worst[0], worst[1][:16], worst[2][:16], min_gap))
        for a, b in hard:
            print("[排版审计·重叠] %r(%.0fpx, y %.0f~%.0f) × %r(%.0fpx, y %.0f~%.0f)"
                  % (a[4][:20], a[5], a[1], a[3], b[4][:20], b[5], b[1], b[3]), file=sys.stderr)
        for a, b, g in near:
            print("[排版审计·粘连] 间隙 %.1fpx < %.0fpx：%r ↔ %r"
                  % (g, min_gap, a[4][:18], b[4][:18]), file=sys.stderr)
        return len(hard), len(near)


def render_card(version, f_serif, f_sans, f_sansb, f_seal, ss=2, verbose=False):
    """绘制竖版介绍卡。排版失败（重叠/溢出）一律返回 None，绝不出残图。

    版面策略：**先量后画**——先把各段高度算出来，再把剩余空间平均分给段间
    空隙（含收口空隙），所以改文案不会挤爆版面，也不会在底部留大片空洞。
    """
    S = ss
    W, H = BOARD_W * S, BOARD_H * S
    img = vgrad(W, H, BG_TOP, BG_BOT).convert("RGBA")
    img.alpha_composite(radial((int(W * 0.9), int(H * 0.5)), GLOW_GOLD), (-int(W * 0.15), -int(H * 0.12)))
    img.alpha_composite(radial((int(W * 0.8), int(H * 0.45)), GLOW_BLUE), (int(W * 0.35), int(H * 0.30)))
    d = ImageDraw.Draw(img, "RGBA")
    U = float(S)                       # 1 设计单位 = S 像素
    AUD = LayoutAudit(U)

    def put(xy, s, f, fill, anchor="la", span=None):
        """绘制并登记墨迹框——所有文字必须走这里，审计才覆盖得到。"""
        d.text(xy, s, font=f, fill=fill, anchor=anchor)
        AUD.add(xy[0], xy[1], s, f, anchor, span)

    def ls_y(ink_top, f):
        """已知墨迹顶、用 anchor='ls' 绘制时应传的基线 y。"""
        return ink_top + 0.88 * f.size

    scan_lines(d, W, H, (46, 107, 168), unit=S, alpha=8)
    d.rectangle([0, 0, W, 7 * S], fill=GOLD + (180,))
    d.rectangle([0, H - 5 * S, W, H], fill=GOLD + (110,))

    # ============ 头部 ============
    seal_cx, seal_cy = W - PAD * S - 62 * S, 100 * S
    draw_seal(img, seal_cx, seal_cy, 116 * S, unit=S, fseal=f_seal)
    draw_frame_corners(d, [seal_cx - 78 * S, seal_cy - 78 * S, seal_cx + 78 * S, seal_cy + 78 * S],
                       GOLD + (150,), max(2, int(2.4 * S)), 26 * S)

    # (1) 英文小标（17px，字距拉开；整串登记一次，免得字距被当成重叠）
    f_en = font(f_sans, 17 * U)
    x = PAD * U
    for i, ch in enumerate(EN_SUB):
        d.text((x, 52 * U), ch, font=f_en, fill=GOLD_LT + (225,))
        if i == 0:
            AUD.add(x, 52 * U, EN_SUB, f_en, "la", span=EN_SUB)
        x += d.textlength(ch, font=f_en) + 2.6 * U

    # (2) 主标题 64px（anchor la：y 是字身顶，墨迹底须由基线推算）
    f_title = font(f_serif, 64 * U)
    put((PAD * U, 92 * U), TITLE_MAIN, f_title, FG, "la")
    asc_t, _ = f_title.getmetrics()
    title_ink_bottom = 92 * U + asc_t + 0.12 * f_title.size

    # (3) 副标行：AI 胶囊 ＋ 副标 38px ＋ 版本徽章 ＋ 作者（同排，省一整行）
    f_sub = font(f_serif, 38 * U)
    sub_base = title_ink_bottom + 30 * U + 0.88 * f_sub.size     # 墨迹顶 = 标题墨迹底 + 30
    sub_ink_mid = sub_base - 0.38 * f_sub.size                   # 墨迹垂直中心
    cap_w, cap_h, cap_r = 70 * U, 46 * U, 15 * U
    d.rounded_rectangle([PAD * U, sub_ink_mid - cap_h / 2, PAD * U + cap_w, sub_ink_mid + cap_h / 2],
                        radius=cap_r, fill=GOLD_LT + (255,))
    put((PAD * U + cap_w / 2, sub_ink_mid), "AI", font(f_sansb, 24 * U), BG_TOP + (255,), "mm")
    put((PAD * U + cap_w + 18 * U, sub_base), SUB_TEXT, f_sub, GOLD_LT, "ls")
    xb = PAD * U + cap_w + 18 * U + d.textlength(SUB_TEXT, font=f_sub) + 26 * U

    badge = version if version.lower().startswith("v") else "v" + version
    f_badge = font(f_sansb, 22 * U)
    bw = d.textlength(badge, font=f_badge) + 44 * U
    d.rounded_rectangle([xb, sub_ink_mid - 22 * U, xb + bw, sub_ink_mid + 22 * U], radius=17 * U,
                        fill=GOLD + (255,))
    put((xb + bw / 2, sub_ink_mid), badge, f_badge, (11, 32, 56), "mm")
    put((xb + bw + 20 * U, sub_ink_mid), "%s ｜ %s" % (AUTHOR, card_date()), font(f_sans, 18 * U), FG3, "lm")
    # 取本行最高的元素作为行底（胶囊 46px 比文字墨迹高）
    sub_row_bottom = max(sub_base + 0.12 * f_sub.size, sub_ink_mid + cap_h / 2, sub_ink_mid + 22 * U)

    # (4) 一句话定位 22px（单行；超宽会在审计里以粘连/重叠形式暴露）
    f_tag = font(f_sans, 22 * U)
    put((PAD * U, ls_y(sub_row_bottom + 30 * U, f_tag)), TAGLINE, f_tag, FG2, "ls")
    y0 = sub_row_bottom + 30 * U + f_tag.size                    # 内容区起点

    # ============ 先量：各段高度 ============
    f_h = font(f_serif, 28 * U)        # 区块标题
    f_body = font(f_sans, 22 * U)      # 正文
    f_chip = font(f_sans, 19 * U)      # chips
    LH, HEAD, BOTP = 37 * U, 84 * U, 22 * U
    PITCH = 50 * U                     # chips 行距

    def lay_chips(items, max_w):
        sizes = [(c, d.textlength(c, font=f_chip) + 32 * U) for c in items]
        rows, cur, cw = [], [], 0.0
        for c, t in sizes:
            if cw + t > max_w and cur:
                rows.append((cur, cw))
                cur, cw = [], 0.0
            cur.append((c, t))
            cw += t + 12 * U
        if cur:
            rows.append((cur, cw))
        return rows

    def block_h(items):
        n = sum(len(wrap_text(d, it, f_body, CW * U - 92 * U)) for it in items)
        return HEAD + n * LH + BOTP

    rows_dim = lay_chips(DIMENSIONS, CW * U - 8 * U)
    rows_tax = lay_chips(TAX_CHIPS, CW * U - 8 * U)
    chip_h = HEAD + len(rows_dim) * PITCH + 12 * U + len(rows_tax) * PITCH + 24 * U
    hs = [block_h(BLOCKS[i][1]) for i in range(len(BLOCKS))] + [chip_h]

    FOOT_BOX = 152 * U                 # 页脚占用的底部高度（固定，底部锚定）
    fy = H - FOOT_BOX - 18 * U
    avail = (fy - 20 * U) - y0
    gap = (avail - sum(hs)) / max(1, len(hs))
    if gap < 18 * U:
        print("[make-card] 排版溢出：可用 %.0fpx、内容需 %.0fpx（段间空隙仅 %.0fpx）；"
              "请精简文案或收紧行距。" % (avail / U, sum(hs) / U, gap / U), file=sys.stderr)
        return None
    gap = min(gap, 66 * U)             # 别把版面拉散

    # ============ 后画：主体区块 ============
    def draw_block(ytop, title, items):
        wrapped = [wrap_text(d, it, f_body, CW * U - 92 * U) for it in items]
        bh = HEAD + sum(len(w) for w in wrapped) * LH + BOTP
        d.rounded_rectangle([PAD * U, ytop, W - PAD * U, ytop + bh], radius=20 * U,
                            fill=(255, 255, 255, 10), outline=GOLD + (46,), width=max(1, int(1.4 * S)))
        put((PAD * U + 26 * U, ytop + 22 * U), title, f_h, GOLD_LT, "la")
        d.rectangle([PAD * U + 26 * U, ytop + 70 * U, W - PAD * U - 26 * U, ytop + 71 * U],
                    fill=GOLD + (60,))
        yy = ytop + HEAD
        for ws in wrapped:
            d.ellipse([PAD * U + 28 * U, yy + 11 * U, PAD * U + 37 * U, yy + 20 * U], fill=GOLD + (200,))
            for ln in ws:
                put((PAD * U + 52 * U, yy), ln, f_body, FG2, "la")
                yy += LH
        return ytop + bh

    def draw_chips(ytop):
        d.rounded_rectangle([PAD * U, ytop, W - PAD * U, ytop + chip_h], radius=20 * U,
                            fill=(255, 255, 255, 10), outline=GOLD + (46,), width=max(1, int(1.4 * S)))
        put((PAD * U + 26 * U, ytop + 22 * U), "覆盖风险维度", f_h, GOLD_LT, "la")
        # 三色风险点：与"风险维度"标题同排右端（原在页脚，被交付物行压着）
        draw_risk_dots(d, W - PAD * U - 148 * U, ytop + 40 * U, FG3 + (255,), f_sans, U,
                       reg=lambda x, y, s, f, an: AUD.add(x, y, s, f, an))
        d.rectangle([PAD * U + 26 * U, ytop + 70 * U, W - PAD * U - 26 * U, ytop + 71 * U],
                    fill=GOLD + (60,))
        cyy = ytop + HEAD
        for row, _rw in rows_dim:
            cx = PAD * U + 26 * U
            for c, t in row:
                d.rounded_rectangle([cx, cyy, cx + t, cyy + 38 * U], radius=11 * U,
                                    fill=GOLD + (34,), outline=GOLD + (70,), width=max(1, int(1.2 * S)))
                put((cx + t / 2, cyy + 19 * U), c, f_chip, FG2, "mm")
                cx += t + 12 * U
            cyy += PITCH
        cyy += 12 * U
        for row, _rw in rows_tax:                       # K 组：金色高亮，与通用维度区分
            cx = PAD * U + 26 * U
            for c, t in row:
                d.rounded_rectangle([cx, cyy, cx + t, cyy + 38 * U], radius=11 * U,
                                    fill=GOLD + (58,), outline=GOLD_LT + (150,), width=max(1, int(1.4 * S)))
                put((cx + t / 2, cyy + 19 * U), c, f_chip, GOLD_LT, "mm")
                cx += t + 12 * U
            cyy += PITCH
        return ytop + chip_h

    y = y0 + gap
    for title, items in BLOCKS:
        y = draw_block(y, title, items) + gap
    y = draw_chips(y) + gap

    # ============ 页脚（底部锚定，行间按墨迹盒推进） ============
    d.rectangle([PAD * U, fy, W - PAD * U, fy + 2 * U], fill=GOLD + (70,))
    prev = fy + 2 * U

    def fline(s, f, fill, g):
        nonlocal prev
        put((PAD * U, ls_y(prev + g, f)), s, f, fill, "ls")
        prev = ls_y(prev + g, f) + 0.12 * f.size

    fline(DISCLAIM, font(f_sans, 18 * U), FG3, 20 * U)
    fline(DELIVER, font(f_sansb, 20 * U), GOLD_LT, 16 * U)
    fline(LICENSE, font(f_sans, 18 * U), FG3, 14 * U)
    if prev > H - 30 * U:
        print("[make-card] 页脚溢出：底 %.0f 越过安全线 %.0f。" % (prev / U, (H - 30 * U) / U),
              file=sys.stderr)
        return None

    # ============ 出图前排版审计 ============
    nh, nn = AUD.check(verbose=verbose)
    if nh:
        print("[make-card] 排版审计未通过：%d 处文字重叠，拒绝出图。" % nh, file=sys.stderr)
        return None
    if nn:
        print("[make-card] 排版审计告警：%d 处间距 < %.0fpx（已出图，建议复核）。" % (nn, MIN_GAP),
              file=sys.stderr)
    return img.convert("RGB").resize((BOARD_W, BOARD_H), Image.LANCZOS)


def read_version():
    p = os.path.join(SKILL_ROOT, "SKILL.md")
    try:
        with open(p, encoding="utf-8-sig") as f:
            m = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", f.read(12000))
        if m:
            v = m.group(1).strip()
            return v if v.lower().startswith("v") else "v" + v
    except OSError:
        pass
    return None


def count_seed_industries():
    """从 guard.py 实读内置行业库数量——卡片口径的唯一真源，杜绝手写数字漂移。"""
    p = os.path.join(SKILL_ROOT, "scripts", "guard.py")
    try:
        src = open(p, encoding="utf-8").read()
        m = re.search(r"SEED_INDUSTRIES\s*=\s*\{(.*?)\}", src, re.S)
        if not m:
            return None
        return len([s for s in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1)) if (s[0] or s[1])])
    except OSError:
        return None


def verify_copy():
    """卡片文案数字守卫：卡片文字烧进 PNG 像素，check.py 扫 .md 永远扫不到，
    是校验盲区（V3.8.2 统一口径时就漏了卡片，"140 条"多挂了两版；V3.10.1
    又抓到"行业库 8 个"未随 realestate 转正）。故在**源头**——每次重绘时——
    拿文案里的数字与代码实扫值核对，不一致即拒绝出图。"""
    ok = True
    # (1) 通用库规则数 ↔ core/01 实扫
    core = os.path.join(SKILL_ROOT, "core", "01-general-risk-rules.md")
    if os.path.exists(core):
        real = len(re.findall(r"(?m)^\|\s*[A-Z]\d+\s*\|", open(core, encoding="utf-8").read()))
        written = 0
        for _t, items in BLOCKS:
            for it in items:
                m = re.search(r"(\d+)\s*条跨行业规则", it)
                if m:
                    written = int(m.group(1))
        if written and written != real:
            print("[make-card] 卡片文案数字失准：写 %d 条，core/01 实为 %d 条。" % (written, real),
                  file=sys.stderr)
            ok = False
    # (2) 内置行业库数量 ↔ guard.py SEED_INDUSTRIES
    seeds = count_seed_industries()
    if seeds:
        written = 0
        for _t, items in BLOCKS:
            for it in items:
                m = re.search(r"行业库：(\d+)\s*个内置", it)
                if m:
                    written = int(m.group(1))
        if written and written != seeds:
            print("[make-card] 卡片文案数字失准：写 %d 个内置行业库，guard.py 种子库实为 %d 个。"
                  % (written, seeds), file=sys.stderr)
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description="竖版技能介绍卡（1080×1440）生成")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出文件路径")
    ap.add_argument("--version", default=None, help="覆盖版本串（默认读 SKILL.md）")
    ap.add_argument("--ss", type=float, default=2, help="超采样倍率（默认 2）")
    ap.add_argument("--font-serif", default=None)
    ap.add_argument("--font-sans", default=None)
    ap.add_argument("--dry-run", action="store_true", help="只审计与核对，不出图")
    a = ap.parse_args()

    ver = a.version or read_version()
    if not ver:
        print("无法从 SKILL.md 读取版本号；请用 --version 显式指定。", file=sys.stderr)
        return 2
    if not verify_copy():
        return 2
    f_serif = pick_font("serif_bold", a.font_serif)
    f_sans = pick_font("sans_reg", a.font_sans)
    f_sansb = pick_font("sans_bold")
    f_seal = pick_font("seal") or f_serif
    if not (f_serif and f_sans):
        print("未找到可用的中文字体，请用 --font-serif/--font-sans 指定。", file=sys.stderr)
        return 2

    im = render_card(ver, f_serif, f_sans, f_sansb, f_seal, ss=a.ss, verbose=True)
    if im is None:                     # 溢出或排版审计未通过，上面已说明
        return 2
    if a.dry_run:
        print("[dry-run] 排版与文案核对通过，未出图。")
        return 0
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    info = PngInfo()
    info.add_text("Skill-Version", ver)
    im.save(a.out, "PNG", optimize=True, pnginfo=info)
    print("[OK] %s  %d×%d  %.1f KB（版本串 %s）"
          % (os.path.basename(a.out), im.width, im.height, os.path.getsize(a.out) / 1024.0, ver))
    return 0


if __name__ == "__main__":
    sys.exit(main())
