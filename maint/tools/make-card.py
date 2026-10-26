#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同 · 竖版技能介绍卡（1080×1440）生成
==============================================================================
产出「方便发群／朋友圈／资料库展示」的竖版介绍卡：一张图讲清技能是什么、
能做什么、凭什么可信、出什么交付物。全部文案取自技能推介文，
不留任何易变数字（规则条数、法规条数随版本浮动，卡片不背这个账）。

归属说明
    · 本脚本属于**维护侧**（/workspace/dev/maint/tools/），**不随技能包分发**；
    · 这样技能包仍维持既有脚本数口径，不必为一张卡片增脚本并联动全套文档；
    · 版本号／日期均自动读自 version.json（升版后重跑一次即可刷新卡片）。

排版引擎（V2 起，2026-10 重写）
    V1 的病灶（由 layout-audit 实测坐实）：
      (1) 主标题与副标**真实重叠 8px** —— CJK 字身框高是字号的约 1.45 倍（60px→87px），
         旧代码按"字号"估位置，估小了；
      (2) 最小字号 15px、正文 17.5px —— 卡片按 480px 宽预览等效 6.7px，缩略即糊；
      (3) 73 个文字块挤在 1080×1440，密度过高。
    V2 的三条对策：
      A. **按墨迹框排布**：所有文字以"基线 + em 框"定位，不再用字身框拍脑袋；
      B. **字号整体上调**：正文 22px，标题 30/64px，最小字号 16px；
      C. **降密度换空间**：删掉风险维度 chips 区与独立高亮卡，把版面让给
         「能做什么／凭什么可信／交付什么」三块浅底大字。
    并内建 `LayoutAudit`：每次出图前两两比对所有文字墨迹框，
    **真重叠即拒绝出图**（返回 None），间距不足则告警——排版错误不再靠肉眼发现。

渲染陷阱（本环境实测，勿改回）
    · **Pillow 的 RGBA 直绘不做混合**：`ImageDraw.Draw(img,"RGBA")` 的半透明
      fill 会把 alpha 直接丢弃、写成实色像素。故所有半透明底色一律
      **预混成不透明色**再画（BX_FILL／BX_STRIPE／BX_HL／底纹横线）。
      踩坑记录：底纹横线曾以 alpha=7 绘制，实际渲成实心亮蓝实线，
      满屏条纹看着"沉闷"。
    · **字体不混族**：标题与正文统一黑体族（Noto Sans CJK），
      早期"宋体标题＋黑体正文"中西混排发涩，且宋体 Bold 缩略后笔画糊团。

设计
    · 纯本地绘制（Pillow），零联网、零外部素材；超采样 2× 后降采样，边缘平滑；
    · 页面亮蓝渐变＋顶部金线，三块浅底（浅绿／浅粉／浅黄）承载正文，
      深色文字压浅底、对比充足，整页轻快；
    · 视觉基调沿用头标：深蓝＋金 ＋ 朱印元素 ＋ 三色风险点签名元素。

用法
    python3 make-card.py                      生成到技能包 assets/skill-card.png
    python3 make-card.py --out <路径>          指定输出文件
    python3 make-card.py --version Vx.y.z      覆盖版本串（默认读 version.json）
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
TAGLINE = "逐条对标标准立场 · 风险三色分级 · 出可交付的审查成果"
AUTHOR = "胡皓"


def card_date():
    """日期唯一真源＝version.json 的 latest.date，升版即随动，不再硬编码陈旧。"""
    p = os.path.join(SKILL_ROOT, "version.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return (d.get("latest") or {}).get("date") or ""
    except (OSError, ValueError):
        return ""


# 三块正文（全部按推介文提炼，冒号前为亮点名，金色加粗）
BLOCKS = [
    ("能做什么", [
        "逐条审查：三色分级＋标准立场＋可用话术",
        "原稿级修订：Word 原生修订痕迹，逐条取舍",
        "改稿比对：条款级差异，夹带私货藏不住",
        "涉密纯本地：全量脱敏，正文不出电脑",
        "起草文书：合同与各类文书，可选公文风排版",
        "非合同也审：授权书／制度／NDA／SLA",
        "法规检索：原文＋出处＋适用要件，不下结论",
        "法规汇编：按主题编成册，带目录与时效",
    ]),
    ("凭什么可信", [
        "法条原文：逐条比对，不靠模型记忆",
        "法规库校验：本地＋云，双源双向核对",
        "机制登记：逐条钉着在跑的代码判据",
        "数字实扫：门禁核对，对不上出不了包",
    ]),
]

DIMENSIONS = ["付款与违约金", "交付验收", "知识产权", "保密与竞业", "管辖条款",
              "仲裁条款", "争议解决", "诉讼时效", "合同效力", "格式条款",
              "个人信息保护", "主体适格与签章"]
# K 组高亮 chip：原为独立圆角卡，V2 改为 chips 区内的金色一组（省卡壳、信息不减）
TAX_CHIPS = ["发票与税率 · 三流一致", "银行承兑 · 红字冲红", "虚开发票红线 ★★★"]

DELIVER_TITLE = "交付什么"
DELIVER = "审查意见报告 · 原稿级修订版 · 比对台账 · 脱敏版 · 模板版 · 文档汇编 · 摘要与思维导图"
FORMATS = [("Word", "可编辑原稿"), ("Markdown", "纯文本"), ("Excel", "差异台账"),
           ("HTML", "在线查阅"), ("PDF", "归档发送")]
DISCLAIM = "仅辅助用途，不构成法律意见；须经执业律师复核后方可据此决策。"
LICENSE = "个人使用授权 · 商业使用须取得书面授权"

# —— 配色（沿用头标 dark 主题）——
BG_TOP, BG_BOT = (30, 74, 128), (18, 52, 96)
GLOW_GOLD = (201, 162, 74, 30)
GLOW_BLUE = (108, 178, 236, 42)
GOLD, GOLD_LT = (201, 162, 74), (227, 192, 113)
FG, FG2, FG3 = (255, 255, 255), (240, 246, 252), (168, 190, 214)
SEAL_PAPER, SEAL_INK = (252, 249, 242), (179, 39, 30)
# 三框浅底（浅绿 / 浅粉 / 浅黄）＋ 边线 ＋ 隔行条；深色文字压浅底，对比足、页面轻快
BX_FILL = [(226, 243, 232), (252, 232, 238), (253, 246, 220)]
BX_STRIPE = [(212, 235, 221), (246, 218, 227), (250, 239, 203)]
BX_LINE = [(120, 178, 142, 190), (216, 138, 160, 190), (214, 178, 84, 200)]
BX_TITLE = [(31, 104, 66), (158, 52, 82), (146, 100, 20)]     # 框标题深色
BX_NAME = [(24, 122, 74), (176, 58, 90), (150, 98, 16)]       # 能力名（对应底色系）
BX_TEXT = [(32, 52, 44), (58, 38, 44), (52, 46, 28)]          # 正文深色
# 能力名高亮块：白 14% 预混到框底（不用 alpha——Pillow 混合失效会直接写成实色盖住字）
BX_HL = [(214, 238, 224), (250, 219, 229), (252, 240, 206)]
RISK = [("高", (216, 68, 60)), ("中", (227, 166, 55)), ("低", (62, 155, 107))]

# —— 版面尺度（设计单位 px，1 设计单位最终 = 1 出图像素）——
PAD = 64                                   # 左右安全边
CW = BOARD_W - PAD * 2                     # 正文可用宽 952
MIN_GAP = 10                               # 任意两块文字墨迹框的最小垂直间隙（审计阈值）

# 字体族：**全卡统一黑体族（Noto Sans CJK / 苹方 / 微软雅黑）**——
# 旧版把"标题"指向 serif_bold，候选首项还是微软雅黑（本机无此文件），
# 回退到 Noto Serif CJK Bold，于是**衬线标题配黑体正文**，中西文混排发涩；
# 且正文用 Bold 22px，缩略后笔画糊成团。现统一：标题亦用黑体 Bold，
# 正文用 Regular（细字更清），关键信息用 Bold，靠**字重**分层次而非靠字体族。
FONT_CANDIDATES = {
    "sans_reg": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 r"C:\Windows\Fonts\msyh.ttc",
                 "/System/Library/Fonts/PingFang.ttc"],
    "sans_bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  r"C:\Windows\Fonts\msyhbd.ttc",
                  "/System/Library/Fonts/PingFang.ttc"],
    "serif_bold": ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                   r"C:\Windows\Fonts\msyhbd.ttc",
                   "/System/Library/Fonts/PingFang.ttc"],
    "seal": ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
             r"C:\Windows\Fonts\msyhbd.ttc",
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
    """底纹横线。本环境 Pillow 的 RGBA 直绘**不做混合**（半透明 fill 被写成
    实色像素，alpha 直接丢弃），故这里把 alpha 与底色**预混成不透明色**再画，
    否则 alpha=7 也会变成一条亮蓝实线，满屏条纹。"""
    st = int(30 * unit)
    lw = max(1, int(unit))
    y = st
    while y < h:
        d.line([(0, y), (w, y)], fill=color, width=lw)
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


def thick_glyph_mask(ch, w, h, font_path, grow=0.05, steps=36, blur=1.0, grow_max=None):
    w, h = max(2, int(w)), max(2, int(h))
    side = min(w, h)
    r = side * grow
    if grow_max is not None:
        r = min(r, side * grow_max)   # 膨胀半径绝对上限：小印文少膨，防笔画间隙粘连
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


def render_thick_char(ch, w, h, color, font_path, grow=0.05, blur=1.0, grow_max=None):
    w, h = int(round(w)), int(round(h))
    out = Image.new("RGBA", (w, h), tuple(color) + (0,))
    out.putalpha(thick_glyph_mask(ch, w, h, font_path, grow=grow, blur=blur,
                                  grow_max=grow_max))
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
    # blur 相对印文的比例与 icon（make-header ss=4 降采样）对齐：0.4*unit
    g = render_thick_char("审", gs, gs, SEAL_INK, fseal, grow=0.030, blur=0.4 * unit,
                          grow_max=0.012)
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

    # 底纹横线：预混不透明色（浅蓝白 7/255 混进底色梯度），避免 RGBA 直绘不混合
    def _mix_tint(base, tint, a):
        return tuple(int(base[i] * (1 - a) + tint[i] * a) for i in range(3))

    def scan_tint(yy):
        t = yy / float(H)
        base = tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3))
        return _mix_tint(base, (150, 205, 245), 7 / 255.0)

    for _sy in range(int(30 * S), H, int(30 * S)):
        d.line([(0, _sy), (W, _sy)], fill=scan_tint(_sy), width=max(1, int(S)))
    d.rectangle([0, 0, W, 7 * S], fill=GOLD)
    d.rectangle([0, H - 5 * S, W, H], fill=_mix_tint(BG_BOT, GOLD, 110 / 255.0))

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
    put((xb + bw + 26 * U, sub_ink_mid), "%s · %s" % (AUTHOR, card_date()),
        font(f_sansb, 21 * U), FG2, "lm")
    # 取本行最高的元素作为行底（胶囊 46px 比文字墨迹高）
    sub_row_bottom = max(sub_base + 0.12 * f_sub.size, sub_ink_mid + cap_h / 2, sub_ink_mid + 22 * U)

    # (4) 一句话定位 22px（单行；超宽会在审计里以粘连/重叠形式暴露）
    f_tag = font(f_sans, 22 * U)
    tag_y = ls_y(sub_row_bottom + 30 * U, f_tag)
    put((PAD * U, tag_y), TAGLINE, f_tag, FG2, "ls")
    y0 = sub_row_bottom + 30 * U + f_tag.size                    # 内容区起点

    # ============ 先量：各段高度 ============
    f_h = font(f_sansb, 30 * U)        # 区块标题（黑体 Bold，30px）
    f_body = font(f_sans, 22 * U)      # 正文用 Regular（细字在浅底上更清）
    f_bodyb = font(f_sansb, 22 * U)    # 能力名用 Bold，与正文靠字重分层次
    LH, HEAD, BOTP = 37 * U, 84 * U, 22 * U

    def block_h(items):
        n = sum(len(wrap_text(d, it, f_body, CW * U - 92 * U)) for it in items)
        return HEAD + n * LH + BOTP

    f_deli = font(f_sans, 21 * U)
    f_fmt = font(f_sansb, 19 * U)
    deli_h = HEAD + 44 * U + 62 * U    # 标题 + 交付物一行 + 格式徽章一行
    hs = [block_h(BLOCKS[i][1]) for i in range(len(BLOCKS))] + [deli_h]

    FOOT_BOX = 96 * U                  # 页脚占用的底部高度（固定，底部锚定）
    fy = H - FOOT_BOX - 18 * U
    avail = (fy - 20 * U) - y0
    gap = (avail - sum(hs)) / max(1, len(hs))
    if gap < 18 * U:
        print("[make-card] 排版溢出：可用 %.0fpx、内容需 %.0fpx（段间空隙仅 %.0fpx）；"
              "请精简文案或收紧行距。" % (avail / U, sum(hs) / U, gap / U), file=sys.stderr)
        return None
    gap = min(gap, 66 * U)             # 别把版面拉散

    # ============ 后画：主体区块 ============
    def draw_block(ytop, title, items, bi):
        wrapped = [wrap_text(d, it, f_body, CW * U - 92 * U) for it in items]
        bh = HEAD + sum(len(w) for w in wrapped) * LH + BOTP
        d.rounded_rectangle([PAD * U, ytop, W - PAD * U, ytop + bh], radius=20 * U,
                            fill=BX_FILL[bi], outline=BX_LINE[bi], width=max(1, int(1.6 * S)))
        put((PAD * U + 26 * U, ytop + 22 * U), title, f_h, BX_TITLE[bi], "la")
        d.rectangle([PAD * U + 26 * U, ytop + 70 * U, W - PAD * U - 26 * U, ytop + 71 * U],
                    fill=BX_LINE[bi])
        yy = ytop + HEAD
        for k, ws in enumerate(wrapped):
            if k % 2 == 0:   # 隔行淡底色条，分隔条目便于阅读
                d.rounded_rectangle(
                    [PAD * U + 14 * U, yy - 4 * U, W - PAD * U - 14 * U, yy + LH - 2 * U],
                    radius=8 * U, fill=BX_STRIPE[bi])
            d.ellipse([PAD * U + 28 * U, yy + 11 * U, PAD * U + 37 * U, yy + 20 * U],
                      fill=BX_NAME[bi] + (235,))
            # 冒号前能力名：金色加粗；其余正文提亮
            first = ws[0]
            name, sep, rest = first.partition("：")
            if sep:
                nw = d.textlength(name + "：", font=f_bodyb)
                # 能力名加同色系浅底块，做视觉锚点（一眼扫到"是什么"）
                d.rounded_rectangle(
                    [PAD * U + 46 * U, yy - 2 * U, PAD * U + 52 * U + nw + 6 * U, yy + LH - 6 * U],
                    radius=6 * U, fill=BX_HL[bi])
                put((PAD * U + 52 * U, yy), name + "：", f_bodyb, BX_NAME[bi], "la")
                put((PAD * U + 52 * U + nw, yy), rest, f_body, BX_TEXT[bi], "la")
            else:
                put((PAD * U + 52 * U, yy), first, f_body, BX_TEXT[bi], "la")
            yy += LH
            for ln in ws[1:]:
                put((PAD * U + 52 * U, yy), ln, f_body, BX_TEXT[bi], "la")
                yy += LH
        return ytop + bh

    y = y0 + gap
    # 三色风险点签名：首块标题行右端（chips 区已移除，签名迁至此处）
    draw_risk_dots(d, W - PAD * U - 200 * U, y + 36 * U, (58, 84, 118) + (255,), f_sans, U,
                   reg=lambda x, y2, sa, fa, an: AUD.add(x, y2, sa, fa, an))
    for bi, (title, items) in enumerate(BLOCKS):
        y = draw_block(y, title, items, bi) + gap

    # ============ 交付什么（亮点块：金色描边加粗） ============
    d.rounded_rectangle([PAD * U, y, W - PAD * U, y + deli_h], radius=20 * U,
                        fill=BX_FILL[2], outline=BX_LINE[2], width=max(2, int(2.4 * S)))
    put((PAD * U + 26 * U, y + 22 * U), DELIVER_TITLE, f_h, BX_TITLE[2], "la")
    d.rectangle([PAD * U + 26 * U, y + 70 * U, W - PAD * U - 26 * U, y + 71 * U], fill=BX_LINE[2])
    put((PAD * U + 26 * U, y + HEAD + 6 * U), DELIVER, f_deli, BX_TEXT[2], "la")
    # 格式徽章一排
    bx = PAD * U + 26 * U
    for fm, why in FORMATS:
        tw = max(d.textlength(fm, font=f_fmt),
                 d.textlength(why, font(f_sans, 16 * U))) + 30 * U
        d.rounded_rectangle([bx, y + HEAD + 42 * U, bx + tw, y + HEAD + 106 * U], radius=11 * U,
                            fill=(255, 252, 238), outline=BX_LINE[2], width=max(1, int(1.6 * S)))
        put((bx + tw / 2, y + HEAD + 62 * U), fm, f_fmt, BX_TITLE[2], "mm")
        put((bx + tw / 2, y + HEAD + 92 * U), why, font(f_sans, 16 * U), (110, 88, 40), "mm")
        bx += tw + 10 * U
    y = y + deli_h + gap

    # ============ 页脚（底部锚定，行间按墨迹盒推进） ============
    d.rectangle([PAD * U, fy, W - PAD * U, fy + 2 * U],
                fill=_mix_tint(tuple(int(BG_BOT[i] * (1 - fy / float(H)) + BG_BOT[i] * (fy / float(H)))
                                     for i in range(3)), GOLD, 70 / 255.0))
    prev = fy + 2 * U

    def fline(s, f, fill, g):
        nonlocal prev
        put((PAD * U, ls_y(prev + g, f)), s, f, fill, "ls")
        prev = ls_y(prev + g, f) + 0.12 * f.size

    fline(DISCLAIM, font(f_sans, 18 * U), FG3, 24 * U)
    fline(LICENSE, font(f_sans, 18 * U), FG2, 16 * U)
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
    """版本真源＝version.json 的 latest.version；取不到再回落 SKILL.md frontmatter。
    卡片上的日期同理走 version.json 的 latest.date（见 card_date）。"""
    p = os.path.join(SKILL_ROOT, "version.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        v = str((d.get("latest") or {}).get("version") or "").strip()
        if v:
            return v if v.lower().startswith("v") else "v" + v
    except (OSError, ValueError):
        pass
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


def verify_copy(version=None):
    """卡片文案守卫：卡片文字烧进 PNG 像素，check.py 扫 .md 永远扫不到，
    是校验盲区（V3.8.2 统一口径时就漏了卡片，"140 条"多挂了两版；V3.10.1
    又抓到"行业库 8 个"未随 realestate 转正）。故在**源头**——每次重绘时——
    核对卡片上的断言与技能实况，不一致即拒绝出图。

    口径变更（V3.23.6 后）：卡片文案已按推介文改写，**不再出现任何易变数字**
    （规则条数／法规条数／内置库个数），故原先「N 条跨行业规则」「行业库 N 个内置」
    两道数字守卫已无对象、等于形同虚设，一并撤下。改为守卫**不会随版本漂移的
    结构性断言**：格式徽章必须对得上技能真实交付能力、交付物清单不得出现
    技能不产出的东西、版本串必须与 version.json 一致。
    """
    ok = True

    # (1) 格式徽章 ↔ 技能真实交付能力：徽章是给用户看的承诺，不能凭空许诺。
    #     真源是 make-docx.py 的 --formats 取值集合（README「文件格式」章同源）。
    #     **双向核对**：卡片列出的每个徽章都要有实据；技能支持的每个格式
    #     也都应出现在卡片上（少列＝少承诺，用户以为不支持）。
    fmt_src = os.path.join(SKILL_ROOT, "scripts", "make-docx.py")
    fmt_declared = set()
    if os.path.exists(fmt_src):
        src = open(fmt_src, encoding="utf-8").read()
        # 匹配**全部** --formats 出现处再取并集：文件里既有用法示例也有
        # argparse 定义，只取第一处会撞上文档说明行（"文件格式（--formats，逗号分隔）："）
        for line in src.splitlines():
            if "--formats" in line:
                fmt_declared |= set(re.findall(r"docx|md|excel|html|pdf", line))
    card_fmt = {"Word": "docx", "Markdown": "md", "Excel": "excel",
                "HTML": "html", "PDF": "pdf"}
    card_exts = set()
    for fmt, _why in FORMATS:
        ext = card_fmt.get(fmt)
        if ext is None:
            print("[make-card] 格式徽章「%s」不在受支持的格式表内（%s），疑为臆造。"
                  % (fmt, "／".join(sorted(card_fmt))), file=sys.stderr)
            ok = False
            continue
        card_exts.add(ext)
        if fmt_declared and ext not in fmt_declared:
            print("[make-card] 卡片承诺了「%s」交付，但 make-docx.py --formats 未声明 %s。"
                  % (fmt, ext), file=sys.stderr)
            ok = False
    if fmt_declared:
        missing = fmt_declared - card_exts
        if missing:
            print("[make-card] 技能支持但卡片未列出的格式：%s（用户会误以为不支持）。"
                  % "／".join(sorted(missing)), file=sys.stderr)
            ok = False

    # (2) 交付物清单 ↔ 引擎能力：**双向核对**——
    #     (2a) 已知交付物不得从卡片清单里漏掉；
    #     (2b) 卡片清单里出现清单外的条目＝技能不产出的东西，拒出图。
    deliverables = {
        "审查意见报告": ("review", "审查"),
        "原稿级修订版": ("tracked", "redline"),
        "比对台账": ("diff", "compare"),
        "脱敏版": ("mask", "desens"),
        "模板版": ("template", "tpl"),
        # 文档汇编＝法规汇编引擎（legal-compile.py）的产物，与 10 类审查交付物分立：
        # 审查交付物针对「这份文档」，汇编针对「一个领域」，故单列而不并进 10 类。
        "文档汇编": ("legal-compile", "汇编"),
    }
    scripts_text = ""
    sc = os.path.join(SKILL_ROOT, "scripts")
    if os.path.isdir(sc):
        for f in os.listdir(sc):
            if f.endswith(".py"):
                try:
                    scripts_text += open(os.path.join(sc, f), encoding="utf-8").read()
                except OSError:
                    pass
    for key, needles in deliverables.items():
        if key not in DELIVER:
            print("[make-card] 交付物清单缺项：%s。" % key, file=sys.stderr)
            ok = False
        elif scripts_text and not any(n in scripts_text for n in needles):
            print("[make-card] 交付物「%s」在 scripts/ 中找不到对应实现（%s）。"
                  % (key, "/".join(needles)), file=sys.stderr)
            ok = False
    # 卡片清单条目逐个核对：凡不在已知交付物表内的，须能在 scripts/ 找到实现证据
    listed = [x.strip() for x in re.split(r"[·/｜|、,，]", DELIVER) if x.strip()]
    known = set(deliverables) | {"摘要与思维导图"}
    for item in listed:
        if item in known:
            continue
        if scripts_text and not any(w in scripts_text for w in re.split(r"[^\w一-鿿]+", item)):
            print("[make-card] 交付物清单出现未知项「%s」，在 scripts/ 中找不到实现证据。"
                  % item, file=sys.stderr)
            ok = False

    # (3) 版本串 ↔ version.json：卡片上的版本必须与技能包真实版本一致
    vj = os.path.join(SKILL_ROOT, "version.json")
    try:
        latest = (json.load(open(vj, encoding="utf-8")).get("latest") or {})
        real_v = str(latest.get("version") or "")
    except (OSError, ValueError):
        real_v = ""
    if real_v:
        shown = str(version or "").lstrip("v")
        if shown and shown != real_v.lstrip("v"):
            print("[make-card] 版本串失准：卡片写 %s，version.json 为 %s。"
                  % (shown, real_v), file=sys.stderr)
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
        print("无法读取版本号（version.json / SKILL.md 均未取到）；请用 --version 显式指定。",
              file=sys.stderr)
        return 2
    if not verify_copy(ver):
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
