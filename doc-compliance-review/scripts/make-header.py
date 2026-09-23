#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同审核全能版 · 头标（横幅 / 图标）生成
==========================================================================
产出「方便发布」的品牌头标：宽幅头图（放 README / SKILL 顶部、发行页首图）
＋方形图标（技能卡片 / 头像 / 应用图标）。

特点：
  · **纯本地绘制**（Pillow），零联网、零外部素材、可重复生成；
  · 版本号自动读自 SKILL.md frontmatter —— 版本升级后重跑一次即可刷新头图；
  · 超采样绘制（默认 4×）再降采样，边缘平滑；中文用系统字体，不会出现 AI 生图乱码；
  · 视觉基调＝中式文书（宣纸 / 朱印 / 天平）＋ 轻量 AI 点缀（扫描线 / 取景框 / AI 胶囊）；
  · 标题拆**主副两行**：主行「文档合规审查助手」，副行「AI 合同审核全能版」，
    长名称不被迫缩小字号。

用法：
  python make-header.py                    生成全部（2 套配色 × 横幅/图标）到 ../assets
  python make-header.py --theme dark       只生成深色（深蓝金）一套
  python make-header.py --out <目录>       指定输出目录
  python make-header.py --version Vx.y.z     覆盖版本串（默认自动读 SKILL.md，无需手填）
  python make-header.py --list             只看将产出哪些文件，不实际绘制

依赖：Pillow（pip install Pillow）；Windows 自带中文字体（msyh/simhei），
      非 Windows 请用 --font 指定一个中文字体文件。
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import re
import sys
import math
import argparse

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    print("缺少依赖 Pillow。请先安装：pip install Pillow", file=sys.stderr)
    raise SystemExit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 设计画板（所有坐标按这套尺寸书写）
BOARD_W, BOARD_H = 1600, 420
ICON = 512

# 图标里「印章」与「四角取景框」的尺寸基准（都是图标边长的比例）
#   · ICON_SEAL_K  —— 印面边长；卡片上图标只有几十像素，印面越大印文越清楚
#   · ICON_FRAME_K —— 取景框位置**冻结基准**：取景框由印章尺寸推算，若跟着印章一起放大
#     就会顶到描边、失去「取景」的余量。故取景框位置固定按此基准算，只让印章长大；
#     反过来，印面长大之后这个值要相应**收小**，让取景框仍贴着印章、不被落在外面（0.50→0.43）。
ICON_SEAL_K = 0.58
ICON_FRAME_K = 0.43
#   · ICON_CORNER_K —— 取景框**单个角的臂长**（按上面的冻结基准算）。
#     臂长越短越收敛、越像取景取景框；过长会绕着印章形成一圈方框，抢印文的视觉重心。
ICON_CORNER_K = 0.13

# —— 文案 ——
TITLE_MAIN = "文档合规审查助手"          # 主行（大字）
SUB_CAPS = "AI"                          # 副行行首胶囊
SUB_TEXT = "合同审核全能版"              # 副行（小字）
EN1 = "DOCUMENT COMPLIANCE REVIEW ASSISTANT"
EN2 = "AI CONTRACT AUDIT · ALL-ROUND EDITION"
TAGS = "合同 · 商务文档 · 逐条审查 · 三色风险分级 · 红线修订 · 脱敏与比对"
RISK = [("高", (216, 68, 60)), ("中", (227, 166, 55)), ("低", (62, 155, 107))]

THEMES = {
    "dark": dict(
        bg_top=(11, 32, 56), bg_bot=(7, 21, 37),
        glow_gold=(201, 162, 74, 26), glow_blue=(46, 107, 168, 30),
        gold=(201, 162, 74), gold_lt=(227, 192, 113),
        fg=(255, 255, 255), fg2=(168, 188, 210), fg3=(108, 134, 163),
        rule=(201, 162, 74, 90), sep=(201, 162, 74, 55),
        accent=(227, 192, 113),     # 副行/胶囊：金
        caps_fill=(227, 192, 113),  # 胶囊底色
        caps_fg=(11, 32, 56),       # 胶囊文字
        seal_paper=(252, 249, 242),  # 印面：白底（朱文印）
        seal_ink=(179, 39, 30),      # 印文与边框：朱红
        scan=(46, 107, 168),
    ),
    "light": dict(
        bg_top=(250, 247, 240), bg_bot=(240, 234, 222),
        glow_gold=(154, 123, 51, 26), glow_blue=(46, 107, 168, 14),
        gold=(154, 123, 51), gold_lt=(139, 108, 40),
        fg=(23, 38, 60), fg2=(85, 103, 126), fg3=(133, 146, 163),
        rule=(154, 123, 51, 110), sep=(23, 38, 60, 40),
        seal=(179, 39, 30),
        accent=(179, 39, 30),        # 副行/胶囊：朱红
        caps_fill=(179, 39, 30),
        caps_fg=(250, 247, 240),
        seal_paper=(254, 252, 247),  # 印面：白底（朱文印）
        seal_ink=(179, 39, 30),      # 印文与边框：朱红
        scan=(154, 123, 51),
    ),
}

# 字体候选（Windows 优先；给出回退顺序）
FONT_CANDIDATES = {
    "bold": [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\Dengb.ttf",
             r"C:\Windows\Fonts\simhei.ttf", "/System/Library/Fonts/PingFang.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
    "reg": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\Deng.ttf",
            r"C:\Windows\Fonts\simhei.ttf", "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    # 印章印文用：**必须选细体/中体**。膨胀是等量向内外推进的，
    # 粗体字的内腔本就窄，一膨胀就被吃掉、糊成墨团（实测 msyhbd 在 5.5% 膨胀下已不可辨）；
    # 细体的字腔宽，膨胀后既足够厚重、又保得住结构。
    "seal": [r"C:\Windows\Fonts\msyhl.ttc", r"C:\Windows\Fonts\Dengl.ttf",
             r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyhbd.ttc",
             "/System/Library/Fonts/PingFang.ttc",
             "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"],
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


def text_w(d, s, f, tracking=0):
    if not s:
        return 0
    w = d.textlength(s, font=f)
    if tracking:
        w += tracking * (len(s) - 1)
    return w


def draw_tracked(d, xy, s, f, fill, tracking=0):
    """带字距的文本绘制（英文小标题用）。"""
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + tracking


def vgrad(w, h, c1, c2):
    """垂直渐变：用 1×h 细条放大，快且平滑。"""
    strip = Image.new("RGB", (1, h))
    px = strip.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))
    return strip.resize((w, h), Image.BICUBIC)


def radial(size, color):
    """径向光晕：小图逐像素生成后放大，得到柔和渐变。"""
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


def paper_noise(w, h, amount=10):
    """极淡的纸张颗粒（浅色主题用）。"""
    import random
    rnd = random.Random(20260917)
    n = Image.new("L", (w, h))
    px = n.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = 128 + rnd.randint(-amount, amount)
    return n


def scan_lines(d, w, h, color, unit=1, step=None, alpha=9):
    """极淡的水平扫描线：暗示「文档被机器逐行读取」（AI 点缀，不干扰正文）。"""
    st = step or int(26 * unit)
    lw = max(1, int(unit))
    y = st
    while y < h:
        d.line([(0, y), (w, y)], fill=color + (alpha,), width=lw)
        y += st


def draw_frame_corners(d, box, color, lw, corner):
    """四角取景框（AI 识别感）：只画四个直角。"""
    x0, y0, x1, y1 = box
    segs = [
        [(x0, y0 + corner), (x0, y0), (x0 + corner, y0)],
        [(x1 - corner, y0), (x1, y0), (x1, y0 + corner)],
        [(x0, y1 - corner), (x0, y1), (x0 + corner, y1)],
        [(x1 - corner, y1), (x1, y1), (x1, y1 - corner)],
    ]
    for pts in segs:
        d.line(pts, fill=color, width=lw, joint="curve")


def ellipse_ring(d, box, color, width):
    d.ellipse(box, outline=color, width=width)


def draw_scales(d, cx, cy, span, color, lw, knob=True):
    """天平（线稿）。span＝横梁总宽。"""
    top = cy - span * 0.58
    beam_y = cy - span * 0.30
    base_y = cy + span * 0.60
    d.line([(cx, top), (cx, base_y)], fill=color, width=lw)
    if knob:
        r = lw * 1.7
        d.ellipse([cx - r, top - r, cx + r, top + r], fill=color)
    d.line([(cx - span / 2, beam_y), (cx + span / 2, beam_y)], fill=color, width=lw)
    hl = max(1, int(lw * 0.55))
    for sgn in (-1, 1):
        px = cx + sgn * span / 2
        d.line([(px, beam_y), (px - span * 0.13, beam_y + span * 0.24)], fill=color, width=hl)
        d.line([(px, beam_y), (px + span * 0.13, beam_y + span * 0.24)], fill=color, width=hl)
        d.arc([px - span * 0.17, beam_y + span * 0.14,
               px + span * 0.17, beam_y + span * 0.40],
              start=0, end=180, fill=color, width=lw)
    d.line([(cx - span * 0.15, base_y), (cx + span * 0.15, base_y)], fill=color, width=lw)


def draw_risk_dots(d, cx, cy, color, font_path, unit):
    """红/橙/绿三点＋高/中/低（技能签名元素）。"""
    gap, r = 86 * unit, 7 * unit
    f = font(font_path, 17 * unit)
    total = gap * (len(RISK) - 1)
    x = cx - total / 2
    for label, col in RISK:
        d.ellipse([x - r, cy - r, x + r, cy + r], fill=col)
        d.text((x + r + 8 * unit, cy), label, font=f, fill=color, anchor="lm")
        x += gap


# —— 印章文字：专业字形 + 圆盘膨胀 ＝ 粗圆体 ——
# 本机 `C:\Windows\Fonts` 共 286 个字体：不仅没有篆书，`SIMLI.TTF`（隶书）与
# `STLITI.TTF`（华文隶书）**均不存在**；汉仪魏碑简非篆非隶且属商业字体、字魂老招牌
# 标注“商用需授权”，用于发布物料有版权隐患。
# 手绘折线能仿其形、却逼近不了字库的笔锋，且「规」这类复杂字在横幅小尺寸下必然糊成一团。
# 故改为「渲染 + 形态学加工」两步：
#   1. 用系统**细体中文字体**（msyhl / Dengl，回退 simhei）渲染 —— 字架结构由专业字库保证，
#      零授权风险；**必须用细体**：膨胀是等量向内外推进的，粗体字内腔窄，一膨胀就糊成墨团；
#   2. 以**圆盘做膨胀**（沿圆周多次偏移叠加、取并集）将笔画加粗到目标厚度，
#      同时把笔画的端头与折角一并磨圆 —— 正是“粗壮圆润、饱满”的圆笔效果（半径 5.5% 为实测最佳）。


def thick_glyph_mask(ch, w, h, font_path, grow=0.055, steps=36, blur=1.0):
    """生成一个字的「粗圆体」蒙版（L 模式，尺寸 w×h）。

    做法：先把字渲染到留足膨胀余量的字号，再沿半径为「grow×短边」的圆周
    重复绘制并取并集（＝圆盘膨胀），最后轻微模糊把折角磨圆。
    """
    w, h = max(2, int(w)), max(2, int(h))
    side = min(w, h)
    r = side * grow
    target = side - 2 * r                      # 膨胀后正好填满短边

    # 1. 定字号：在 100 号下量一次真实包围盒，再按目标尺寸等比换算
    def extent_of(size):
        probe = Image.new("L", (int(size) * 3, int(size) * 3), 0)
        ImageDraw.Draw(probe).text((size * 1.5, size * 1.5), ch,
                                   font=ImageFont.truetype(font_path, int(size)),
                                   fill=255, anchor="mm")
        bb = probe.getbbox()
        return max(bb[2] - bb[0], bb[3] - bb[1]) if bb else 1

    fs = max(4.0, 100.0 * target / extent_of(100))
    f = ImageFont.truetype(font_path, int(round(fs)))

    # 2. 圆盘膨胀：36 个角度足以让边界误差远小于 1px
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


def render_thick_char(ch, w, h, color, font_path, grow=0.055, blur=1.0):
    """一个字的粗圆体成品图（RGBA，可直接 alpha_composite 到画布）。"""
    w, h = int(round(w)), int(round(h))
    out = Image.new("RGBA", (w, h), tuple(color) + (0,))
    out.putalpha(thick_glyph_mask(ch, w, h, font_path, grow=grow, blur=blur))
    return out


def draw_seal_scan(img, cx, cy, size, t, unit=1, font_heavy=None, frame_size=None):
    """白底朱文印 + 四角取景框（图标主体）。size＝印面边长。

    印式＝**朱文印**（白底红字、红边框）；印文「审」＝系统粗黑体渲染后经圆盘膨胀
    处理成的粗圆体，见上方「印章文字」说明。传 img 而非 ImageDraw，是为了能用
    alpha_composite 贴图。

    frame_size＝取景框的尺寸基准（默认与印面同尺寸）。传入固定基准可让取景框
    位置不随印面放大而外移——印面越长越大时，取景框仍停在原处，留白由印章去占。
    """
    d = ImageDraw.Draw(img, "RGBA")
    hw = size / 2.0
    lw = max(2, int(6.4 * unit))          # 边框（朱文印边框须略粗于笔画）
    rad = size * 0.07
    box = [cx - hw, cy - hw, cx + hw, cy + hw]
    # 印面：白底 + 朱红边框
    d.rounded_rectangle(box, radius=rad, fill=t["seal_paper"] + (255,),
                        outline=t["seal_ink"] + (255,), width=lw)
    # 内细边（双框，传统朱文印常见）
    ins = size * 0.066
    d.rounded_rectangle([box[0] + ins, box[1] + ins, box[2] - ins, box[3] - ins],
                        radius=rad * 0.55, outline=t["seal_ink"] + (150,),
                        width=max(2, int(1.8 * unit)))
    # 印文「审」（粗圆体）：占印面八成二——在更大的印面上仍有干净边白，
    # 内细边同步收到 0.066，双框不糊（小尺寸下更需留白）
    gs = size * 0.82
    g = render_thick_char("审", gs, gs, t["seal_ink"], font_heavy,
                          grow=0.048, blur=1.0 * unit)
    img.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
    # 外侧四角取景框：锚定**固定框**（半边长＝基准/2＋基准×0.24），与印章大小解耦，
    # 印章放大时取景框停在原处不动（若锚在印章外框上，印面一大就把框顶到圆角处被裁）；
    # 取景框本身的**收紧／放开**只调 ICON_FRAME_K 一个值即可，四角一并内收。
    fz = frame_size or size
    half = fz / 2.0 + fz * 0.24
    corner = fz * ICON_CORNER_K
    draw_frame_corners(d, [cx - half, cy - half, cx + half, cy + half],
                       t["gold"] + (170,), max(2, int(3.2 * unit)), corner)


def render_banner(theme_name, version, font_bold, font_reg, ss=4, k=1.0, font_seal=None):
    t = THEMES[theme_name]
    fseal = font_seal or font_bold
    W, H = int(BOARD_W * k), int(BOARD_H * k)
    S = int(ss * k)                      # 超采样倍率
    CW, CH = W * S, H * S

    img = vgrad(CW, CH, t["bg_top"], t["bg_bot"]).convert("RGBA")
    # 光晕
    img.alpha_composite(radial((int(CW * 0.62), int(CH * 1.5)), t["glow_gold"]), (-int(CW * 0.08), -int(CH * 0.35)))
    img.alpha_composite(radial((int(CW * 0.55), int(CH * 1.6)), t["glow_blue"]), (int(CW * 0.52), -int(CH * 0.4)))
    if theme_name == "light":
        # 极淡纸张颗粒（幅度过大会让 PNG 体积翻倍，压到 ±4）
        noise = paper_noise(240, 64, amount=4).resize((CW, CH), Image.BICUBIC)
        img = Image.composite(Image.new("RGBA", (CW, CH), (255, 255, 255, 255)), img,
                              noise.point(lambda v: max(0, min(255, int((v - 124) * 0.6)))))

    d = ImageDraw.Draw(img, "RGBA")
    U = S                                  # 1 设计单位 = U 像素

    # —— 扫描线（画在文字之下）——
    scan_lines(d, CW, CH, t["scan"], unit=U)

    # —— 顶部/底部装饰细线 ——
    d.rectangle([0, 0, CW, 5 * U], fill=t["gold"] + (170,))
    d.rectangle([0, CH - 3 * U, CW, CH], fill=t["gold"] + (90,))

    PAD = 84 * U
    f_main = font(font_bold, 64 * U)
    f_sub = font(font_bold, 34 * U)
    f_caps = font(font_bold, 21 * U)
    f_en = font(font_reg, 18 * U)
    f_tag = font(font_reg, 21 * U)
    f_meta = font(font_reg, 16.5 * U)

    # —— 主标题 ——
    d.text((PAD, 54 * U), TITLE_MAIN, font=f_main, fill=t["fg"], anchor="la")

    # —— 副标题：AI 胶囊 + 小字，二者共用垂直中心 ——
    cy_sub = 152 * U
    cap_w, cap_h, cap_r = 62 * U, 38 * U, 12 * U
    cap_x = PAD + 2 * U
    d.rounded_rectangle([cap_x, cy_sub - cap_h / 2, cap_x + cap_w, cy_sub + cap_h / 2],
                        radius=cap_r, fill=t["caps_fill"] + (255,))
    d.text((cap_x + cap_w / 2, cy_sub), SUB_CAPS, font=f_caps, fill=t["caps_fg"], anchor="mm")
    d.text((cap_x + cap_w + 16 * U, cy_sub), SUB_TEXT, font=f_sub, fill=t["accent"], anchor="lm")

    # —— 英文小标题（字距） ——
    draw_tracked(d, (PAD + 2 * U, 206 * U), EN1, f_en, t["gold_lt"] + (235,), 4.6 * U)
    draw_tracked(d, (PAD + 2 * U, 228 * U), EN2, f_en, t["fg3"] + (235,), 4.6 * U)

    # —— 分隔线 ——
    d.rectangle([PAD, 254 * U, PAD + 300 * U, 256 * U], fill=t["rule"])

    # —— 标签行 ——
    d.text((PAD, 268 * U), TAGS, font=f_tag, fill=t["fg2"], anchor="la")

    # —— 版本 / 作者 ——
    d.text((PAD, 336 * U), version + "   ｜   作者：胡皓", font=f_meta, fill=t["fg3"], anchor="la")

    # —— 右侧：分隔线 + 徽标 ——
    d.rectangle([1010 * U, 74 * U, 1011 * U, 346 * U], fill=t["sep"])
    cx = 1252 * U
    if theme_name == "dark":
        cy = 180 * U
        ellipse_ring(d, [cx - 104 * U, cy - 104 * U, cx + 104 * U, cy + 104 * U],
                     t["gold"] + (130,), max(2, int(2.2 * U)))
        draw_scales(d, cx, cy, 118 * U, t["gold_lt"] + (255,), max(2, int(3.4 * U)))
        # AI 点缀：天平外一圈极淡的取景框角标（收在 ±126，避免与底部三色点相碰）
        draw_frame_corners(d, [cx - 126 * U, cy - 126 * U, cx + 126 * U, cy + 126 * U],
                           t["gold"] + (110,), max(2, int(2.0 * U)), 30 * U)
    else:
        # 朱文印：白底朱红边框 + 粗圆体「合规审查」，四字**横排左起**
        # （竖排四字按传统右起读会成「审查合规」，故一律横排以免误读）
        sw, sh = 330, 120
        seal = Image.new("RGBA", (sw * S, sh * S), (0, 0, 0, 0))
        sd = ImageDraw.Draw(seal, "RGBA")
        rad = int(9 * S)
        sd.rounded_rectangle([0, 0, sw * S - 1, sh * S - 1], radius=rad,
                             fill=t["seal_paper"] + (255,),
                             outline=t["seal_ink"] + (255,), width=max(2, int(3.4 * S)))
        ins = int(7 * S)
        sd.rounded_rectangle([ins, ins, sw * S - 1 - ins, sh * S - 1 - ins],
                             radius=max(1, rad - int(2 * S)),
                             outline=t["seal_ink"] + (160,), width=max(2, int(1.5 * S)))
        pad_x, pad_y = 20 * S, 18 * S
        gw = (sw * S - pad_x * 2) / 4.0
        gh = sh * S - pad_y * 2
        # 字格取正方形：字形各自为正方块，横排四字才不会高矮不齐
        cell = min(gw * 0.82, gh * 0.94)
        for i, ch in enumerate("合规审查"):
            mx = pad_x + i * gw + gw / 2.0
            my = pad_y + gh / 2.0
            g = render_thick_char(ch, cell, cell, t["seal_ink"], fseal,
                                  grow=0.048, blur=1.0 * S)
            seal.alpha_composite(g, (int(mx - g.width / 2), int(my - g.height / 2)))
        seal = seal.rotate(-2, resample=Image.BICUBIC, expand=True)
        img.alpha_composite(seal, (int(cx - seal.width / 2), int(170 * U - seal.height / 2)))
        d = ImageDraw.Draw(img, "RGBA")
        # AI 点缀：印章外四角取景框
        draw_frame_corners(d, [cx - 196 * U, 170 * U - 96 * U, cx + 196 * U, 170 * U + 96 * U],
                           t["gold"] + (120,), max(2, int(2.0 * U)), 34 * U)
        d.text((cx, 282 * U), "逐条审查 · 风险三色分级", font=font(font_reg, 17 * U),
               fill=t["fg2"], anchor="mm")

    draw_risk_dots(d, cx, 330 * U, t["fg3"] + (255,), font_reg, U)

    return img.convert("RGB").resize((W, H), Image.LANCZOS)


def render_icon(theme_name, font_bold, ss=4, font_seal=None):
    t = THEMES[theme_name]
    fseal = font_seal or font_bold
    S = ss
    C = ICON * S
    img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # 底板：先在不透明层做「渐变＋光晕」，最后才用圆角蒙版裁切
    # （顺序反了光晕会溢出圆角、在透明区留下黄斑）
    tile = vgrad(C, C, t["bg_top"], t["bg_bot"]).convert("RGBA")
    gc = t["glow_gold"]
    tile.alpha_composite(radial((int(C * 0.95), int(C * 0.95)), (gc[0], gc[1], gc[2], int(gc[3] * 0.7))),
                         (int(C * 0.05), int(C * 0.04)))
    mask = Image.new("L", (C, C), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, C - 1, C - 1], radius=int(112 * S), fill=255)
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img, "RGBA")

    # 内描边
    d.rounded_rectangle([int(26 * S), int(26 * S), C - 1 - int(26 * S), C - 1 - int(26 * S)],
                        radius=int(88 * S), outline=t["gold"] + (120,), width=max(2, int(2.4 * S)))

    # 扫描线（限制在内描边之内，避免压到圆角区）
    inner = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    idr = ImageDraw.Draw(inner, "RGBA")
    scan_lines(idr, C, C, t["scan"], unit=S, alpha=10)
    imask = Image.new("L", (C, C), 0)
    ImageDraw.Draw(imask).rounded_rectangle([int(28 * S), int(28 * S), C - int(28 * S), C - int(28 * S)],
                                            radius=int(86 * S), fill=255)
    cut = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    cut.paste(inner, (0, 0), imask)
    img.alpha_composite(cut, (0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # 主图形：朱方章 + 四角取景框（小尺寸辨识度优于天平）
    # 印面 0.50→0.58：卡片上图标仅几十像素，印面越大印文越清楚；
    # 取景框位置按 ICON_FRAME_K 冻结，不随印章放大而外移
    draw_seal_scan(img, C / 2, C * 0.44, C * ICON_SEAL_K, t, S, font_heavy=fseal,
                   frame_size=C * ICON_FRAME_K)
    # 三色风险点
    draw_risk_dots(d, C / 2, C * 0.815, t["fg2"] + (255,), font_bold, S * 1.32)

    # 收尾：圆角之外保留**透明**，圆角之内维持既往观感不逐像素改变。
    #   · 不能直接 convert("RGB")：那会把透明区压成不透明黑，四角露出黑块；
    #   · 也不能拿半透明笔画去叠底：alpha 170/150 的框线与扫描线叠加后会变浅，
    #     与既往版本观感不一致。
    # 故：内容层原样取 RGB（含半透明笔画的既有取值），只在圆角外用同款渐变补底
    # （alpha=0 处不可见，仅为边界抗锯齿不留黑边），最后把圆角蒙版写回 alpha。
    base = vgrad(C, C, t["bg_top"], t["bg_bot"]).convert("RGB")
    out = Image.composite(img.convert("RGB"), base, mask).convert("RGBA")
    out.putalpha(mask)
    return out.resize((ICON, ICON), Image.LANCZOS)


def read_version():
    p = os.path.join(ROOT, "SKILL.md")
    try:
        with open(p, encoding="utf-8-sig") as f:
            head = f.read(12000)
        m = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", head)
        if m:
            v = m.group(1).strip()
            return v if v.upper().startswith("V") else "V" + v
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description="文档合规审查助手AI合同审核全能版 · 头标（横幅/图标）生成")
    ap.add_argument("--out", default=os.path.join(ROOT, "assets"), help="输出目录（默认 ../assets）")
    ap.add_argument("--theme", default="all", choices=["all", "dark", "light"], help="配色：all/dark/light")
    ap.add_argument("--version", default=None, help="覆盖版本串（默认读 SKILL.md frontmatter）")
    ap.add_argument("--font", default=None, help="中文字体文件（非 Windows 环境用）")
    ap.add_argument("--scale", type=float, default=1.0, help="横幅尺寸倍率（1=1600×420，2=3200×840）")
    ap.add_argument("--list", action="store_true", help="只列出将产出的文件")
    a = ap.parse_args()

    themes = ["dark", "light"] if a.theme == "all" else [a.theme]
    ver = a.version or read_version()
    if not ver:
        print("无法从 SKILL.md 读取版本号（frontmatter 缺 version 或过长）；"
              "请用 --version 显式指定，避免头图烧错版本串。", file=sys.stderr)
        return 2
    fb = pick_font("bold", a.font)
    fr = pick_font("reg", a.font)
    if not fb or not fr:
        print("未找到可用的中文字体，请用 --font 指定。", file=sys.stderr)
        return 2
    # 印文用细体（粗体膨胀会糊成墨团），取不到时退回粗体
    fseal = pick_font("seal", a.font) or fb

    sfx = "" if abs(a.scale - 1.0) < 1e-6 else "@%gx" % a.scale
    jobs = []
    for th in themes:
        jobs.append((os.path.join(a.out, "banner-%s%s.png" % (th, sfx)), "banner", th))
        if abs(a.scale - 1.0) < 1e-6:
            jobs.append((os.path.join(a.out, "icon-%s.png" % th), "icon", th))

    if a.list:
        for p, kind, _ in jobs:
            print(os.path.relpath(p, ROOT).replace("\\", "/"))
        return 0

    os.makedirs(a.out, exist_ok=True)
    for path, kind, th in jobs:
        if kind == "banner":
            im = render_banner(th, ver, fb, fr, ss=4, k=a.scale, font_seal=fseal)
        else:
            im = render_icon(th, fb, ss=4, font_seal=fseal)
        # 把绘制时的版本串写进 PNG 元数据（tEXt），供 check.py 校验
        # 「图片里烧的版本」与 SKILL.md 版本是否一致——升版忘了重绘时会当场报警。
        _info = PngInfo()
        _info.add_text("Skill-Version", ver)
        im.save(path, "PNG", optimize=True, pnginfo=_info)
        kb = os.path.getsize(path) / 1024.0
        print("[OK] %-34s %4d×%-4d  %6.1f KB" % (os.path.basename(path), im.width, im.height, kb))
    print("完成：%d 个文件 → %s（版本串 %s）" % (len(jobs), a.out, ver))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
