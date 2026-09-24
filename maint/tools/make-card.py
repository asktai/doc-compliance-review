#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同审核全能版 · 竖版技能介绍卡（1080×1440）生成
==============================================================================
产出「方便发群／朋友圈／资料库展示」的竖版介绍卡：一张图讲清技能是什么、
能做什么、规则库怎么分层、覆盖哪些风险维度、出什么交付物。

归属说明
    · 本脚本属于**维护侧**（/workspace/dev/maint/tools/），**不随技能包分发**；
    · 这样技能包仍维持 16 个脚本的既有口径，不必为一张卡片增脚本并联动全套文档；
    · 版本号自动读自 SKILL.md frontmatter —— 升版后重跑一次即可刷新卡片。

设计
    · 纯本地绘制（Pillow），零联网、零外部素材；超采样 2× 后降采样，边缘平滑；
    · 标题用思源宋体粗（中式文书感），正文用思源黑体（清晰易读）；
    · 视觉基调沿用头标：深色（深蓝＋金）＋ 朱印元素 ＋ 三色风险点签名元素。

用法
    python3 make-card.py                      生成到技能包 assets/skill-card.png
    python3 make-card.py --out <路径>          指定输出文件
    python3 make-card.py --version Vx.y.z      覆盖版本串（默认读 SKILL.md）
    python3 make-card.py --ss 3                超采样倍率（默认 2，出图更精细但更慢）

依赖：Pillow
"""
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
SKILL_ROOT = "/workspace/dev/doc-compliance-review"
DEFAULT_OUT = os.path.join(SKILL_ROOT, "assets", "skill-card.png")

BOARD_W, BOARD_H = 1080, 1440

# —— 文案 ——
EN_SUB = "DOCUMENT COMPLIANCE REVIEW ASSISTANT"
TITLE_MAIN = "文档合规审查助手"
SUB_TEXT = "AI 合同审核全能版"
TAGLINE = "对合同、协议及授权书、承诺函等商务/业务文档做脱敏、逐条审查、三色分级与红线修订"

BLOCKS = [
    ("核心能力", [
        "文档脱敏（6 类敏感信息）后出可分享版本",
        "逐条合规审查，按条款给标准立场与话术",
        "风险三色分级（高/中/低）＋ 红线修订建议",
        "审查意见报告 · 新旧版本比对台账",
        "起草合同与可复用模板 · 好文档好合同一键转自用模板",
    ]),
    ("三层规则库（可叠加）", [
        "通用库 core：159 条跨行业规则（含 K 组发票税务）",
        "行业库：8 个内置 ＋ 可自建/导入导出",
        "私有库：企业内控规则，优先级最高",
        "冲突消解：私有 ＞ 行业 ＞ 通用；消解不了标 ★★★ 交人工",
    ]),
    ("K 组 · 发票税务与付款", [
        "发票条款与开票衔接 · 含税与税率调整",
        "三流一致 · 银行承兑与支票 · 红字发票冲红",
        "虚开发票与偷逃税红线（★★★）",
    ]),
]

DIMENSIONS = ["付款与违约金", "交付验收", "知识产权", "保密与竞业", "管辖条款",
              "仲裁条款", "争议解决", "诉讼时效", "合同效力", "格式条款",
              "个人信息保护", "主体适格与签章"]

DELIVER = "交付物 10 类（修订版 / 审查意见批注版 / 清洁版 / 红线格式版 / 意见报告 / 脱敏版 / 照录版 / 比对报告 / 新旧比对 / 模板版）× 4 格式（WORD · MD · Excel · PDF）"
DISCLAIM = "仅辅助用途，不构成法律意见；须经执业律师复核后方可据此决策。"

# —— 配色（沿用头标 dark 主题）——
BG_TOP, BG_BOT = (11, 32, 56), (7, 21, 37)
GLOW_GOLD = (201, 162, 74, 30)
GLOW_BLUE = (46, 107, 168, 34)
GOLD, GOLD_LT = (201, 162, 74), (227, 192, 113)
FG, FG2, FG3 = (255, 255, 255), (176, 194, 214), (116, 140, 168)
SEAL_PAPER, SEAL_INK = (252, 249, 242), (179, 39, 30)
RISK = [("高", (216, 68, 60)), ("中", (227, 166, 55)), ("低", (62, 155, 107))]

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


def draw_risk_dots(d, cx, cy, color, fpath, unit=1.0):
    gap, r = 104 * unit, 8 * unit
    f = font(fpath, 19 * unit)
    x = cx - gap
    for label, col in RISK:
        d.ellipse([x - r, cy - r, x + r, cy + r], fill=col)
        d.text((x + r + 9 * unit, cy), label, font=f, fill=color, anchor="lm")
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


def render_card(version, f_serif, f_sans, f_sansb, f_seal, ss=2):
    S = ss
    W, H = BOARD_W * S, BOARD_H * S
    img = vgrad(W, H, BG_TOP, BG_BOT).convert("RGBA")
    img.alpha_composite(radial((int(W * 0.9), int(H * 0.5)), GLOW_GOLD), (-int(W * 0.15), -int(H * 0.12)))
    img.alpha_composite(radial((int(W * 0.8), int(H * 0.45)), GLOW_BLUE), (int(W * 0.35), int(H * 0.30)))
    d = ImageDraw.Draw(img, "RGBA")
    U = S                              # 1 设计单位 = S 像素

    scan_lines(d, W, H, (46, 107, 168), unit=U, alpha=8)
    # 顶/底饰条
    d.rectangle([0, 0, W, 7 * U], fill=GOLD + (180,))
    d.rectangle([0, H - 5 * U, W, H], fill=GOLD + (110,))

    PAD = 72 * U
    CW = W - PAD * 2                   # 正文可用宽

    # ============ 头部 ============
    # 右上：朱印（视觉锚点）
    seal_cx, seal_cy = W - PAD - 62 * U, 96 * U
    draw_seal(img, seal_cx, seal_cy, 116 * U, unit=U, fseal=f_seal)
    draw_frame_corners(d, [seal_cx - 78 * U, seal_cy - 78 * U, seal_cx + 78 * U, seal_cy + 78 * U],
                       GOLD + (150,), max(2, int(2.4 * U)), 26 * U)

    y = 62 * U
    f_en = font(f_sans, 15 * U)
    x = PAD
    for ch in EN_SUB:                  # 字距英文小标
        d.text((x, y), ch, font=f_en, fill=GOLD_LT + (225,))
        x += d.textlength(ch, font=f_en) + 2.4 * U

    y = 96 * U
    d.text((PAD, y), TITLE_MAIN, font=font(f_serif, 60 * U), fill=FG, anchor="la")

    y = 200 * U                        # 副标：AI 胶囊 ＋ 小字（主标题 60px 自 96 排到约 168，须留出间距防堆叠）
    cap_w, cap_h, cap_r = 66 * U, 40 * U, 13 * U
    d.rounded_rectangle([PAD, y - cap_h / 2, PAD + cap_w, y + cap_h / 2],
                        radius=cap_r, fill=GOLD_LT + (255,))
    d.text((PAD + cap_w / 2, y), "AI", font=font(f_sansb, 22 * U), fill=BG_TOP + (255,), anchor="mm")
    d.text((PAD + cap_w + 16 * U, y), SUB_TEXT, font=font(f_serif, 34 * U), fill=GOLD_LT, anchor="lm")

    y = 260 * U                        # 版本徽章 ＋ 作者
    badge = "V" + version.lstrip("Vv") if not version.upper().startswith("V") else version
    f_badge = font(f_sansb, 21 * U)
    bw = d.textlength(badge, font=f_badge) + 40 * U
    d.rounded_rectangle([PAD, y - 19 * U, PAD + bw, y + 21 * U], radius=16 * U,
                        fill=GOLD + (255,))
    d.text((PAD + bw / 2, y), badge, font=f_badge, fill=(11, 32, 56), anchor="mm")
    d.text((PAD + bw + 20 * U, y), "作者：胡皓 ｜ 2026-09-24", font=font(f_sans, 18 * U),
           fill=FG3, anchor="lm")

    y = 306 * U                        # 一句话定位
    f_tag = font(f_sans, 19 * U)
    for ln in wrap_text(d, TAGLINE.replace("\n", ""), f_tag, CW):
        d.text((PAD, y), ln, font=f_tag, fill=FG2, anchor="la")
        y += 29 * U

    # ============ 主体 blocks ============
    def block(ytop, title, items):
        """圆角卡片：标题 + 项目列表。高度先按实际行数精确计算，杜绝溢出。
        行距 30；条目间另加 4px 透气（否则连续条目视觉上粘成一团）。"""
        f_h = font(f_serif, 24 * U)
        f_b = font(f_sans, 17.5 * U)
        LH = 30 * U                       # 列表行高
        GAP = 4 * U                       # 条目间距
        wrapped = [wrap_text(d, it, f_b, CW - 92 * U) for it in items]
        nlines = sum(len(ws) for ws in wrapped)
        bh = 82 * U + nlines * LH + (len(items) - 1) * GAP + 16 * U   # 标题区 82 + 列表 + 条目间距 + 底留白
        d.rounded_rectangle([PAD, ytop, W - PAD, ytop + bh], radius=18 * U,
                            fill=(255, 255, 255, 10), outline=GOLD + (46,), width=max(1, int(1.4 * U)))
        ty = ytop + 20 * U
        d.text((PAD + 26 * U, ty), title, font=f_h, fill=GOLD_LT, anchor="la")
        d.rectangle([PAD + 26 * U, ty + 36 * U, W - PAD - 26 * U, ty + 37 * U],
                    fill=GOLD + (60,))
        yy = ty + 60 * U
        for ws in wrapped:
            d.ellipse([PAD + 28 * U, yy + 8 * U, PAD + 35 * U, yy + 15 * U], fill=GOLD + (200,))
            for ln in ws:
                d.text((PAD + 50 * U, yy), ln, font=f_b, fill=FG2, anchor="la")
                yy += LH
            yy += GAP
        return ytop + bh

    y = 356 * U
    y = block(y, BLOCKS[0][0], BLOCKS[0][1]) + 18 * U
    y = block(y, BLOCKS[1][0], BLOCKS[1][1]) + 18 * U
    y = block(y, BLOCKS[2][0], BLOCKS[2][1]) + 18 * U

    # ============ 覆盖维度 chips ============
    f_chip = font(f_sans, 17 * U)
    f_h2 = font(f_serif, 25 * U)
    chips, lns = [], []
    for c in DIMENSIONS:
        t = d.textlength(c, font=f_chip) + 30 * U
        chips.append((c, t))
    cur, cur_w = [], 0
    for c, t in chips:
        if cur_w + t > CW - 4 * U and cur:
            lns.append((cur, cur_w))
            cur, cur_w = [], 0
        cur.append((c, t))
        cur_w += t + 10 * U
    if cur:
        lns.append((cur, cur_w))
    bh = 34 * U + len(lns) * 46 * U + 22 * U
    d.rounded_rectangle([PAD, y, W - PAD, y + bh], radius=18 * U,
                        fill=(255, 255, 255, 10), outline=GOLD + (46,), width=max(1, int(1.4 * U)))
    d.text((PAD + 26 * U, y + 24 * U), "覆盖风险维度", font=f_h2, fill=GOLD_LT, anchor="la")
    d.rectangle([PAD + 26 * U, y + 56 * U, W - PAD - 26 * U, y + 57 * U], fill=GOLD + (60,))
    cyoodle = y + 82 * U
    for row, rw in lns:
        cx = PAD + 26 * U
        for c, t in row:
            d.rounded_rectangle([cx, cyoodle, cx + t, cyoodle + 36 * U], radius=10 * U,
                                fill=GOLD + (34,), outline=GOLD + (70,), width=max(1, int(1.2 * U)))
            d.text((cx + t / 2, cyoodle + 18 * U), c, font=f_chip, fill=FG2, anchor="mm")
            cx += t + 10 * U
        cyoodle += 46 * U
    y += bh + 16 * U

    # ============ 页脚（锚定底部） ============
    f_dis = font(f_sans, 16 * U)
    dis_lines = wrap_text(d, DISCLAIM, f_dis, CW - 190 * U)
    foot_h = 24 * U + len(dis_lines) * 24 * U + 34 * U + 50 * U
    fy = H - foot_h - 16 * U
    # 溢出守卫：内容底若压到页脚顶，说明文案加多/行距加大后放不下了，宁可报错也不出重叠的图
    if y > fy:
        print("[make-card] 排版溢出：内容底 %d 已越过页脚顶 %d（差 %dpx 设计单位）；"
              "请精简文案或收紧行距。" % (y / U, fy / U, (y - fy) / U), file=sys.stderr)
        return None
    d.rectangle([PAD, fy, W - PAD, fy + 2 * U], fill=GOLD + (70,))
    yy = fy + 20 * U
    for ln in dis_lines:
        d.text((PAD, yy), ln, font=f_dis, fill=FG3, anchor="la")
        yy += 24 * U
    # 交付物一行（金色小字）＋ 右侧三色风险点（同行，右对齐）
    dy = yy + 10 * U
    d.text((PAD, dy), "交付物 10 类 × 4 格式（WORD · MD · Excel · PDF）",
           font=font(f_sansb, 17 * U), fill=GOLD_LT, anchor="la")
    draw_risk_dots(d, W - PAD - 88 * U, dy + 10 * U, FG3 + (255,), f_sans, U)
    d.text((PAD, H - 52 * U), "作者：胡皓 ｜ 个人使用授权 · 商业使用须取得书面授权",
           font=font(f_sans, 15.5 * U), fill=FG3, anchor="lm")

    return img.convert("RGB").resize((BOARD_W, BOARD_H), Image.LANCZOS)


def read_version():
    p = os.path.join(SKILL_ROOT, "SKILL.md")
    try:
        with open(p, encoding="utf-8-sig") as f:
            m = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", f.read(12000))
        if m:
            v = m.group(1).strip()
            return v if v.upper().startswith("V") else "V" + v
    except OSError:
        pass
    return None


def verify_numbers_in_copy():
    """卡片文案数字守卫：卡片文字烧进 PNG 像素，check.py 扫 .md 永远扫不到，
    是校验盲区（V3.8.2 统一口径时就漏了卡片，"140 条"多挂了两版）。故在**源头**
    ——每次重绘时——拿文案里写的规则数与 core/01 实扫值核对，不一致即拒绝出图。"""
    core = os.path.join(SKILL_ROOT, "core", "01-general-risk-rules.md")
    if not os.path.exists(core):
        print("[make-card] 找不到 core/01，跳过文案数字核对", file=sys.stderr)
        return True
    real = len(re.findall(r"(?m)^\|\s*[A-Z]\d+\s*\|", open(core, encoding="utf-8").read()))
    written = 0
    for _, items in BLOCKS:
        for it in items:
            m = re.search(r"(\d+)\s*条跨行业规则", it)
            if m:
                written = int(m.group(1))
    if written and written != real:
        print("[make-card] 卡片文案数字失准：写 %d 条，core/01 实为 %d 条；"
              "请改 BLOCKS 后重绘。" % (written, real), file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="竖版技能介绍卡（1080×1440）生成")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出文件路径")
    ap.add_argument("--version", default=None, help="覆盖版本串（默认读 SKILL.md）")
    ap.add_argument("--ss", type=float, default=2, help="超采样倍率（默认 2）")
    ap.add_argument("--font-serif", default=None)
    ap.add_argument("--font-sans", default=None)
    a = ap.parse_args()

    ver = a.version or read_version()
    if not ver:
        print("无法从 SKILL.md 读取版本号；请用 --version 显式指定。", file=sys.stderr)
        return 2
    if not verify_numbers_in_copy():
        return 2
    f_serif = pick_font("serif_bold", a.font_serif)
    f_sans = pick_font("sans_reg", a.font_sans)
    f_sansb = pick_font("sans_bold")
    f_seal = pick_font("seal") or f_serif
    if not (f_serif and f_sans):
        print("未找到可用的中文字体，请用 --font-serif/--font-sans 指定。", file=sys.stderr)
        return 2

    im = render_card(ver, f_serif, f_sans, f_sansb, f_seal, ss=a.ss)
    if im is None:                     # 排版溢出，render_card 已在 stderr 说明
        return 2
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    info = PngInfo()
    info.add_text("Skill-Version", ver)
    im.save(a.out, "PNG", optimize=True, pnginfo=info)
    print("[OK] %s  %d×%d  %.1f KB（版本串 V%s）"
          % (os.path.basename(a.out), im.width, im.height, os.path.getsize(a.out) / 1024.0, ver.lstrip("Vv")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
