#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E2  不联网就用不成（能力依赖外部知识）；须显式调用，离线须明示降级
"""法条原文「抓取 + 解析」核心（随包；联网例外脚本之一）

为什么把它单独成文件（2026-10-23，v3.23.0）
------------------------------------------------------------------------------
法规库失效巡检（freshness-patrol.py）入包时遇到一个硬问题：巡检必须与建库
**共用同一条解析链**。这不是洁癖——巡检首跑时龙陵县版《劳动合同法》89/94 条被判
「疑似换版」，根因是巡检漏了建库那条 `strip_line_title`（该页把每条的小标题混进正文）。
**另写一套解析，必然在某一天漂移成两套判据**，而两套判据下的「一致/不一致」不可比。

故把抓取与解析从开发侧 build-legal-db.py 整段抽到这里，成为**唯一一份实现**：
  · 建库（开发侧 build-legal-db.py）→ import 本模块
  · 巡检（随包 freshness-patrol.py）→ import 本模块
两侧共用 fetch / to_text / parse_articles / strip_line_title / src_name。

联网说明（务必与 SECURITY.md 口径一致）
------------------------------------------------------------------------------
本模块含 urllib，是技能包内**三个联网例外**之一（另两个是 version.py 查更新、
freshness-patrol.py 巡检）。它**只抓公开法规页面，绝不接触使用者的文档**：
没有读取文档的参数，也没有回传任何内容。默认不会被自动调用——
只有显式跑巡检或建库时才会联网。
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__

# 输出编码自钉：本脚本可能被 check.py 等**作为子进程 spawn**，父侧按 UTF-8 解码 stdout。
# 不钉的话，中文 Windows（GBK 控制台）下会按 GBK 写出 → 父侧 UTF-8 解出 U+FFFD 乱码 →
# 判据一条都匹配不上，父侧误报「判据被删／脚本崩了」（v3.26.2 在千问办公实测到的假红）。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import html
import os
import re
import ssl
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

SRC_NAMES = {
    "ce.cn": "中国经济网", "hefucheng.jcy.gov.cn": "阜城县检察院",
    "guzhen.gov.cn": "固镇县政府", "longling.gov.cn": "龙陵县政府",
    "cac.gov.cn": "中央网信办", "huaiyin.jnjcy.gov.cn": "槐荫区检察院",
    "npc.gov.cn": "中国人大网", "samr.gov.cn": "市场监管总局",
    "zhongshan.jcy.gov.cn": "中山检察在线", "court.gov.cn": "最高人民法院",
    "gov.cn": "中国政府网", "rmzxw.com.cn": "人民政协网",
    "huancui.gov.cn": "威海环翠区政府", "gc.gov.cn": "石家庄藁城区政府",
    "gzns.gov.cn": "广州南沙区人大", "als.gov.cn": "阿拉善盟行署",
    "ynnl.gov.cn": "宁蒗县政府", "cpc.people.com.cn": "人民网·中国共产党新闻网",
    "hrss.yn.gov.cn": "云南省人社厅", "scjgj.yibin.gov.cn": "宜宾市市场监管局",
    "xjbz.gov.cn": "巴音郭楞州政府",
    "gzcourt.gov.cn": "广州审判网", "wxfy.gov.cn": "无锡法院",
    "dzscjg.dezhou.gov.cn": "德州市市场监管局",
    "sj.al.gov.cn": "阿里地区市场监管局", "jkj.hlj.gov.cn": "黑龙江省疾控局",
    "gxq.neijiang.gov.cn": "内江高新区管委会",
    "npc.people.com.cn": "人民网（全国人大频道）", "trs.gov.cn": "铜仁市政府",
    "police.xa.gov.cn": "西安市公安局", "longyang.gov.cn": "隆阳区政府",
    "jyj.bozhou.gov.cn": "亳州市教育局",
    "baoxing.gov.cn": "宝兴县政府", "ip.people.com.cn": "人民网·知识产权频道",
    "jhx.gov.cn": "剑河县政府", "ahxx.gov.cn": "萧县政府",
    "jiangdu.gov.cn": "扬州江都区政府", "fy.gov.cn": "阜阳市政府",
    "qzlc.gov.cn": "泉州鲤城区政府",
}

def fetch(url, enc, tries=3, verify_tls=None):
    """抓一个页面。

    `verify_tls` 三态（2026-11-06 加，默认 None 保持原行为，故建库与巡检不受影响）：
      · None  —— 不校验证书。**建库时的既定策略**：不少地方政府站证书链不完整，
                 严格校验会让这些源整片抓不到，而建库要求"同一部法至少两源"，缺源就建不成。
      · True  —— 严格校验。**核对用途（legal-lookup.py）默认走这条**：抓回来的条文是要被
                 当原文引用的，中间人替换比"抓不到"危险得多——抓不到可以如实说抓不到，
                 抓到一份被改过的"原文"却无从察觉。
      · False —— 显式不校验（使用者 `--insecure` 主动放宽时）。
    """
    if verify_tls is True:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45, context=ctx) as r:
                raw = r.read()
            break
        except Exception as ex:
            last = ex
            time.sleep(1.5 * (i + 1))
    else:
        raise last
    for e in (enc, "utf-8", "gb18030"):
        try:
            s = raw.decode(e)
            if "第" in s and "条" in s:
                return s
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def to_text(h):
    h = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    h = re.sub(r"<style.*?</style>", "", h, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", h))
    t = re.sub(r"[\u3000 \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t


CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9}


def cn2int(s):
    """中文数字转整数（够用到几千条：支持 千/百/十 与直读式）。"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    units = {"千": 1000, "百": 100, "十": 10}
    for ch in s:
        if ch in CN_NUM:
            cur = CN_NUM[ch]
        elif ch in units:
            total += (cur or 1) * units[ch]
            cur = 0
        else:
            return None
    return total + cur


ART_RE = re.compile(r"第([一二三四五六七八九十百千零〇\d]{1,8})条"
                    r"(?:之([一二三四五六七八九十]{1,3}))?[　 ]*")

# 条号必须出现在「行首」或紧跟在句末标点/右括号/冒号之后——否则是正文里的交叉引用
# （如「违反本法第四十六条规定」「不适用本法第十七条、第十八条」），把它当成条头会整体错位。
_HEAD_OK = set("。；：！？\n\r）)》”」")

# 序号式章节标题（「三、合同的效力」）的词表：只认这些，避免误伤正文列举项
_SECTION_TAIL = ("(?:总\s*则|附\s*则|合同的订立|合同的效力|合同的履行|合同的保全|"
                 "合同的变更和转让|合同的权利义务终止|违约责任|其他规定|一般规定)")


def _load_verify():
    """加载条号工具（来自 legal-verify.py）。

    为什么不在这里自己写一份：条号表示法（「205」/「205.1」）的解析规则只允许有一处实现。
    建库侧与核验侧各写一套，迟早出现「建库认得出 205 之一、核验认不出」的分叉——
    那正是本文件开头记的那次教训（巡检另写一套解析，误报「疑似换版」）。
    legal-verify.py 是 E0 纯标准库模块，本脚本（E2）依赖它不违反离线口径。
    """
    import importlib.util as _ilu
    here = os.path.dirname(os.path.abspath(__file__))
    spec = _ilu.spec_from_file_location("_lv_no", os.path.join(here, "legal-verify.py"))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_LV = _load_verify()
art_key, art_base, art_label = _LV.art_key, _LV.art_base, _LV.art_label


def _line_start_heads(text):
    """返回 [(start, end, no)]：只认行首或句末标点后的「第X条」。"""
    out = []
    for m in ART_RE.finditer(text):
        i = m.start()
        j = i - 1
        while j >= 0 and text[j] in " \t\u3000":
            j -= 1
        if j >= 0 and text[j] not in _HEAD_OK:
            continue
        no = cn2int(m.group(1))
        if not no:
            continue
        sub = m.group(2)
        if sub:
            n_sub = cn2int(sub)
            if n_sub:
                out.append((i, m.end(), "%d.%d" % (no, n_sub)))
                continue
        out.append((i, m.end(), str(no)))
    return out



def parse_articles(text):
    """抽「第X条 正文」，返回 {条号int: 正文}。正文到下一个条头或篇/章标题为止。"""
    out = {}
    marks = _line_start_heads(text)
    for i, (s, e, no) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else min(len(text), e + 4000)
        body = text[e:end]
        # 砍掉尾部的篇/章/节标题噪声
        body = re.split(r"\n\s*(?:第[一二三四五六七八九十]+[编章节]|附\s*则)", body)[0]
        body = re.sub(r"\s*\n\s*", "", body).strip()
        body = re.sub(r"（责任编辑：[^）]*）.*$", "", body).strip()
        # 条首「【罪名】」注记：整合版页面常把编者加的罪名提要紧贴条号后
        # （如四川省公安厅版《刑法》「第二百零五条 【虚开增值税专用发票…罪】虚开…」）。
        # **那不是条文内容**——正式条文没有这对方括号，罪名是编者按修正案梳理出来的。
        # 不剥的后果有二：① 库里存的「原文」多了一段本不存在的话，引述核对会把
        # 正确引文判成对不上；② 干净源与带注记的源比对时必然判冲突，白丢一个源。
        # 只剥**紧贴条首、40 字以内**的一处，不做泛化（正文中间的【】可能真是原文）。
        body = re.sub(r"^【[^】]{1,40}】\s*", "", body)
        body = strip_tail_noise(body)
        # 部分来源（如最高法司法解释）用「三、合同的效力」这种序号式章节标题分隔，
        # 会被并进上一条正文尾，须砍掉。只认**已知章节标题词**，不做泛化缩写，
        # 否则会把正文末尾真正的「三、……」列举项一并砍掉。
        body = re.sub(r"[。；]?\s*[一二三四五六七八九十]{1,3}、\s*" + _SECTION_TAIL + r"\s*$",
                      lambda m: m.group(0)[:1] if m.group(0)[:1] in "。；" else "", body).strip()
        body = strip_footer(body)
        if len(body) < 4:
            continue
        if no not in out or len(body) > len(out[no]):
            out[no] = body
    return out


# 正文里绝不能出现的「解析垃圾」——出现即说明抽到了导航/页脚/交叉引用残句
_GARBAGE_RE = re.compile(r"(上一篇|下一篇|打印本页|关闭窗口|责任编辑|扫一扫|分享到|"
                         r"浏览次数|网站地图|版权所有|ICP备|返回顶部|字体[：:]大|"
                         r"相关链接|首页\s*[>＞]|文章来源)")

# 页脚/导航尾巴：从最先出现的标记处整段砍掉
_FOOT_RE = re.compile(r"(相关链接|版权所有|Copyright|ICP备|举报电话|主办单位|"
                      r"地址[：:]|网站标识码|返回顶部)")


def strip_footer(body):
    m = _FOOT_RE.search(body)
    if m and m.start() > 20:
        return body[:m.start()].strip()
    return body


# 页面编辑署名尾巴：位置固定在各页正文末条之后，属噪声但不在 _FOOT_RE 词表里。
# 只在正文已经够长（>40 字）时才砍，避免把正常的短条文砍没。
_TAIL_NOISE = re.compile(
    r"(?:编\s*辑[：:]\s*[\u4e00-\u9fa5]{2,4}\s*责\s*编[：:]\s*[\u4e00-\u9fa5]{2,4}"
    r"|责\s*编[：:]\s*[\u4e00-\u9fa5]{2,4}"
    r"|【我要纠错】"
    r"|扫一扫在手机打开当前页|扫一扫在手机上打开当前页"
    r"|上一篇[：:]|下一篇[：:]|打印本页|打印页面|【TOP】|【打印页面】|【关闭页面】"
    r"|网站地图"
    r"|相关文章|相关稿件|相关链接)"
)


def strip_tail_noise(body, floor=8):
    """砍页面署名尾巴。判据是「噪声出现的位置不太靠前」，而非正文有多长——
    按长度判会把「本法自2008年1月1日起施行。」这类短条文连带砍没（它只有 16 字，
    但后续 40 字全是「扫一扫/上一篇/下一篇」导航）。

    **2026-10-22 补两类（v3.22.2）**：抓电子商务法时，人民政协网每页末条把整块尾部导航
    并进了正文——「编辑：李敏杰0102030405点击上方数字…关键词：…更多2018年一大波新规…」。
    这类垃圾**不是法条分歧**，却让交叉验证报出 2 条 conflict（一致度 0.13），
    差点被当成「两源版本不同」去人工裁决。补的两种判据：
      · 翻页控件（`0102030405 点击上方数字`／`键盘上"←""→"键`）——纯 UI，绝不会出现在法条里
      · 「关键词：…」标签后紧跟正文导航——标签本身在条文中不出现
    """
    m = _TAIL_NOISE.search(body)
    if m and m.start() >= floor:
        return body[:m.start()].strip()
    m2 = _PAGER_RE.search(body)
    if m2 and m2.start() >= floor:
        return body[:m2.start()].strip()
    return body


# 翻页控件与「关键词：」标签：只可能来自网页外壳，法条正文不会有。
# 单独成表而不并进 _TAIL_NOISE，是因为它们只在**位置不太靠前**时才可信，
# 判据与 strip_tail_noise 的 floor 一致，合并会丢掉 floor 保护。
# 刻意不收 `-->`：HTML 注释残留在正文任何位置都可能出现，收进来会误砍真条文。
_PAGER_RE = re.compile(
    r"(?:点击上方数字|可翻页阅读|键盘上\s*[“\"][←→][”\"]"
    r"|关键词[：:]\s*[\u4e00-\u9fa5A-Za-z0-9]+\s+[\u4e00-\u9fa5A-Za-z0-9]+\s+[\u4e00-\u9fa5A-Za-z0-9]+"
    # 「编辑：李敏杰0102030405」——署名直接粘着页码串，也是网页外壳。真实署名
    # 后面跟的是「责编：」或空，不会紧跟一串数字。
    r"|编\s*辑[：:]\s*[\u4e00-\u9fa5]{2,4}\s*\d{4,})")


def looks_garbage(body):
    if _GARBAGE_RE.search(body):
        return True
    # 以「的/和/或/及/与/并/但/而」这类纯连接词开头，多半是从半句中间切出来的；
    # 「因/对/在/为/以」等可作句首，不在此列。
    if body[:1] in "的、，。；：了和或及与并但而":
        return True
    return False


# 部分转载页把条文小标题（「服务期」「经济补偿」）挤在条号后、正文前，需剥离，
# 否则引用会变成「第二十二条规定：服务期用人单位……」。
# 两个来源：①人工核对过的条号→小标题对照表（准）；②通用规则（次）。
# 通用规则只在「小标题＋紧随正文首字」同时成立时才切，宁可不切也不错切。
LINE_TITLES = {
    # 劳动合同法（龙陵县政府网页版，逐条带小标题，已逐条目视核对）
    "劳动合同法": {
        1: "立法宗旨", 2: "适用范围", 3: "基本原则", 4: "规章制度",
        5: "协调劳动关系三方机制", 6: "集体协商机制", 7: "劳动关系的建立",
        8: "用人单位的告知义务和劳动者的说明义务",
        9: "用人单位不得扣押劳动者证件和要求提供担保", 10: "订立书面劳动合同",
        11: "未订立书面劳动合同时劳动报酬不明确的解决", 12: "劳动合同的种类",
        13: "固定期限劳动合同", 14: "无固定期限劳动合同",
        15: "以完成一定工作任务为期限的劳动合同", 16: "劳动合同的生效",
        17: "劳动合同的内容", 18: "劳动合同对劳动报酬和劳动条件约定不明确的解决",
        19: "试用期", 20: "试用期工资", 21: "试用期内解除劳动合同", 22: "服务期",
        23: "保密义务和竞业限制", 24: "竞业限制的范围和期限", 25: "违约金",
        26: "劳动合同的无效", 27: "劳动合同部分无效",
        28: "劳动合同无效后劳动报酬的支付", 29: "劳动合同的履行", 30: "劳动报酬",
        31: "加班", 32: "劳动者拒绝违章指挥、强令冒险作业",
        33: "用人单位名称、法定代表人等的变更", 34: "用人单位合并或者分立",
        35: "劳动合同的变更", 36: "协商解除劳动合同", 37: "劳动者提前通知解除劳动合同",
        38: "劳动者单方解除劳动合同", 39: "用人单位单方解除劳动合同（过失性辞退）",
        40: "无过失性辞退", 41: "经济性裁员", 42: "用人单位不得解除劳动合同的情形",
        43: "工会在劳动合同解除中的监督作用", 44: "劳动合同的终止",
        45: "劳动合同的逾期终止", 46: "经济补偿", 47: "经济补偿的计算",
        48: "违法解除或者终止劳动合同的法律后果", 49: "社会保险关系跨地区转移接续",
        50: "劳动合同解除或者终止后双方的义务", 51: "集体合同的订立和内容",
        52: "专项集体合同", 53: "行业性集体合同、区域性集体合同",
        54: "集体合同的报送和生效", 55: "集体合同中劳动报酬、劳动条件等标准",
        56: "集体合同纠纷和法律救济", 57: "劳务派遣单位的设立",
        58: "劳务派遣单位、用工单位及劳动者的权利义务", 59: "劳务派遣协议",
        60: "劳务派遣单位的告知义务", 61: "跨地区派遣劳动者的劳动报酬、劳动条件",
        62: "用工单位的义务", 63: "被派遣劳动者同工同酬",
        64: "被派遣劳动者参加或者组织工会", 65: "劳务派遣中解除劳动合同",
        66: "劳务派遣的适用岗位", 67: "用人单位不得自设劳务派遣单位",
        68: "非全日制用工的概念", 69: "非全日制用工的劳动合同",
        70: "非全日制用工不得约定试用期", 71: "非全日制用工的终止用工",
        72: "非全日制用工的劳动报酬", 73: "劳动合同制度的监督管理体制",
        74: "劳动行政部门监督检查事项", 75: "监督检查措施和依法行政、文明执法",
        76: "其他有关主管部门的监督管理", 77: "工会监督检查的权利",
        78: "劳动者权利救济途径", 79: "对违法行为的举报", 80: "规章制度违法的法律责任",
        81: "缺乏必备条款、不提供劳动合同文本的法律责任",
        82: "不订立书面劳动合同的法律责任", 83: "违法约定试用期的法律责任",
        84: "扣押劳动者身份等证件的法律责任",
        85: "未依法支付劳动报酬、经济补偿等的法律责任",
        86: "订立无效劳动合同的法律责任", 87: "违反解除或者终止劳动合同的法律责任",
        88: "侵害劳动者人身权益的法律责任", 89: "不出具解除、终止书面证明的法律责任",
        90: "劳动者的赔偿责任", 91: "用人单位的连带赔偿责任",
        92: "劳务派遣单位的法律责任", 93: "无营业执照经营单位的法律责任",
        94: "个人承包经营者的连带赔偿责任", 95: "不履行法定职责、违法行使职权的法律责任",
        96: "事业单位聘用制劳动合同的法律适用", 97: "过渡性条款", 98: "施行时间",
    },
}


def strip_line_title(body, law=None, no=None):
    """剥离条文小标题。先查人工核对过的对照表；不命中就原样返回（不猜）。"""
    titles = LINE_TITLES.get(law or "")
    t = titles.get(no) if titles else None
    # 条号自 v3.26.5 起统一为字符串（「205」「205.1」），对照表的键仍是整数：
    # 「之一」条按主条号回查，命中与否都安全（不命中即不剥，保守方向）。
    if not t and titles:
        try:
            t = titles.get(art_base(no))
        except (TypeError, ValueError):
            t = None
    if not (t and body.startswith(t)):
        return body
    rest = body[len(t):]
    # 两道守卫，防「把正文当标题剥掉」：
    #   ① 剥完不能太短（短了说明这一条本来就只是那一行）
    #   ② 剥完不能以标点开头——条文正文不会以「，」「。」起头，
    #      以标点起头说明 t 其实是正文的一部分（如「固定期限劳动合同，是指……」里的
    #      「固定期限劳动合同」正是本条首句的主语，不是小标题）。
    if len(rest) < 10 or rest[:1] in "，。、；：,.;:":
        return body
    return rest


def short_anchor(body, n=40):
    """取条文最靠前的 40 字作「特征句」，供核验时回读比对（跳过纯列举开头）。"""
    s = body
    k = re.search(r"[。；]", s)
    head = s[:k.start()] if k and k.start() >= 12 else s
    return head[:n].strip()


def src_name(url):
    """把 URL 映射成可读的机构名，写进库里 sources 字段。

    **2026-10-22 修正**：原实现是「按 dict 顺序，第一个 endswith 命中的就返回」。而
    `gov.cn` 在 SRC_NAMES 里排得早，于是 `jhx.gov.cn`（剑河县政府）、`ahxx.gov.cn`（萧县）、
    `jiangdu.gov.cn`（江都区）、`sj.al.gov.cn`（阿里地区）、`gxq.neijiang.gov.cn`（内江高新区）
    统统被标成「中国政府网」；`court.gov.cn` 同理把广州审判网、无锡法院标成「最高人民法院」。
    结果就是：**库里的 `sources` 说假话**——交叉验证明明比的是三个不同站点，却显示成同一家。
    改为「按后缀长度降序匹配」，具体域名恒优先于泛域名；仍无命中则回落到 host 本身。
    """
    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    for k in sorted(SRC_NAMES, key=len, reverse=True):
        if host == k or host.endswith("." + k):
            return SRC_NAMES[k]
    return host


def is_garbage_text(body):
    return looks_garbage(body) or len(body) < 4
