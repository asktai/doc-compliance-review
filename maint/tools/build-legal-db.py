#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法条原文库构建（开发侧工具，不随技能包分发）

用途：从公开官方转载页抓取法律条文原文，落成 `core/legal-articles.json`，
      供审查时**核验法条原文**——表里没有的条号一律标「待核验」，不得凭记忆引用。
原则：
  · 只抓一次、落成本地库，使用者侧完全离线，不联网。
  · 每条记来源 URL ＋ 抓取日期 ＋ 原文 SHA-256，可复核、可追溯。
  · 抓不到就留空并列入 `missing`，**绝不凭记忆补写条文**（那是另一种编造）。
  · 只做核验，不做法律意见；使用者仍须以现行有效版本为准。

用法（开发侧）：
  python maint/tools/build-legal-db.py [--out <路径>] [--only 民法典]
"""
import argparse
import html
import importlib.util
import json
import os
import re
import ssl
import sys
import time
import socket
import hashlib
import datetime
import urllib.parse
import urllib.request

CROSS = None   # 由 _load_crosscheck() 注入（legal-crosscheck.py）

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# 数据源：只用公开可访问的官方或官方转载页；每部法可给篇；抓完合并去重
SOURCES = {
    # 每个法名下可给多个 URL。注意区分两种「多 URL」：
    #   · 分页/补篇（同一份文本拆成几页）→ 拼起来是一份，**不构成交叉验证**
    #   · 独立来源（不同机构、不同网页各自发布全文）→ 才算交叉验证
    # 用 GROUPS 显式标注：同一组的 URL 视为「同一份文本的分页」，不同组之间才比。
    "民法典": [
        # ---- 组 0：转新华社同一篇的三处补篇（同一份文本，互不构成交叉验证）----
        # 中国经济网转载新华社《民法典》全文（GBK），覆盖第 1–917 条
        ("https://www.ce.cn/xwzx/gnsz/gdxw/202006/01/t20200601_35019528.shtml", "gbk"),
        # 阜城县检察院分篇（第（八）篇＝附则），补齐尾部
        ("https://www.hefucheng.jcy.gov.cn/jcyw/202010/t20201028_3000545.shtml", "gbk"),
        # 固镇县人民政府《民法典》第七编 侵权责任、附则（补齐 1200 条以后）
        ("https://www.guzhen.gov.cn/gzdt/ztzl/fzzfjs2/81249562.html", "utf-8"),
        # ---- 组 1：人民网·中国共产党新闻网刊《人民日报》2020-06-02 全文（分 7 页）----
        # 独立于新华社转发的那一份（人民日报自己排版发布），1–1260 条全覆盖。
        # 此前 301 条民法典条目全部单源，根子就在"三个 URL 全是转新华社同一篇"。
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-2.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-3.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-4.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-5.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-6.html", "utf-8"),
        ("https://cpc.people.com.cn/n1/2020/0602/c419242-31731828-7.html", "utf-8"),
    ],
    "劳动合同法": [
        ("https://www.longling.gov.cn/info/7359/2410199.htm", "utf-8"),
        # 交叉验证源：广州市南沙区人大转载 2012 年修订全文（98 条，独立于龙陵县政府）
        ("https://www.gzns.gov.cn/rd/flfg/gjflfg/201705/t20170505_345140.html", "utf-8"),
    ],
    "个人信息保护法": [
        # 中央网络安全和信息化委员会办公室（国家网信办）全文
        ("https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm", "utf-8"),
        # 交叉验证源：铜仁市政府转载全文（74 条，独立于网信办）
        ("https://www.trs.gov.cn/zwgk/zfxxgkzl/fdzdgknr/zcwj/flfg/202302/t20230227_78316401.html",
         "utf-8"),
        # 交叉验证源：西安市公安局转载全文（74 条，与上者亦不同站）
        ("https://police.xa.gov.cn/zwgk/zcfg/619f4376f8fd1c0bdc6dfdfb.html", "utf-8"),
    ],
    "民事诉讼法": [
        # 济南市槐荫区人民检察院转载 2023 年修正全文（GBK 页可能乱码，靠 _pick 兜底）
        ("http://huaiyin.jnjcy.gov.cn/page/zhifabanangongzuoliucheng/minshixingzhengjian/202601204353.html",
         "utf-8"),
        # 交叉验证源：广州审判网（广州市中级人民法院）发布 2023 年修正全文（306 条）
        ("https://www.gzcourt.gov.cn/other/swsdpt/ck634/2025/08/06170325835.html", "utf-8"),
        # 交叉验证源：无锡法院诉讼服务网「新法速递」全文（306 条）
        ("https://zy.wxfy.gov.cn/article/detail/2024/02/id/7817306.shtml", "utf-8"),
        # 注：2023-09-01 为第五次修正（涉外编为主），2024-01-01 施行，现行共 306 条。
        # 若见「284 条」的说法，那是 2021 年第四次修正版的条数，勿混用。
    ],
    "反不正当竞争法": [
        # ---- 2025-06-27 第二次修订，2025-10-15 施行，共 41 条 ----
        # **2026-10-22 换版**：原库内是 2019 年版（33 条）。2025 版把「混淆行为」提到第七条，
        # 商业贿赂从旧第七条挪到新第八条、商业秘密从旧第九条挪到新第十条、民事责任从旧第十七条
        # 挪到新第二十二条、商业秘密举证责任从旧第三十二条挪到新第三十九条。**条号整体错位**，
        # 而规则库当时正引「第七条第商业贿赂」「9条商业秘密」——引出的条号会指到别的行为上。
        # 故本法的 SOURCES 只能放 2025 版，旧版一律不得混入（跨版本比对必全冲突）。
        # 中国人大网 2025-06-27 修订全文
        ("http://www.npc.gov.cn/c2/c30834/202506/t20250627_446247.html", "utf-8"),
        # 交叉验证源：剑河县人民政府转载 2025 年修订全文（41 条）
        ("https://www.jhx.gov.cn/zfbm/scjdglj/zcwj/202510/t20251022_88716728.html", "utf-8"),
        # 交叉验证源：萧县人民政府转载全文（41 条，与上二者均不同站）
        ("https://www.ahxx.gov.cn/grassroots/247/163076811.html", "utf-8"),
        # 交叉验证源：扬州市江都区政府转载全文（41 条）
        ("http://www.jiangdu.gov.cn/zfxxgk/fdzdgknr/scgzbzhjgzfxx/scgzbz/art/2025/"
         "art_e58aaecdef144f4ab239ac2ad1e44fcb.html", "utf-8"),
    ],
    "反垄断法": [
        # 国家市场监督管理总局（2022 年修正全文）
        ("https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_f0fae9eb3a684fc39e84d89eabfc2caa.html",
         "utf-8"),
        # 交叉验证源：德州市市场监督管理局转载 2022 修订全文（70 条，独立于总局）
        ("https://dzscjg.dezhou.gov.cn/n47758756/n47758827/n50006369/n78413861/c78675184/content.html",
         "utf-8"),
    ],
    "著作权法": [
        # 中国人大网（2020 年第三次修正，2021-06-01 施行）
        ("http://www.npc.gov.cn/npc/c2/c30834/202011/t20201119_308796.html", "utf-8"),
        # 交叉验证源：中国政府网「国情」栏全文（2020 修正，67 条）
        ("https://www.gov.cn/guoqing/2021-10/29/content_5647633.htm", "utf-8"),
    ],
    "商标法": [
        # 中国人大网（2019 年第四次修正版）——注意：2026-06-26 已修订通过新版，2027-01-01 施行
        ("http://www.npc.gov.cn/c2/c30834/201906/t20190608_298036.html", "utf-8"),
        # 交叉验证源：人民网 IP 频道（2019 年修正全文）
        # 注意：该页解析出 72 条（缺一条），但缺的那条在**基准源里还在**，
        # 交叉验证按「两源都有该条才比」工作，故不影响比对，只影响该条的覆盖。
        ("https://ip.people.com.cn/GB/n1/2019/1106/c179663-31440313.html", "utf-8"),
    ],
    "广告法": [
        # 国家市场监督管理总局（2015 年修订全文，2021 年修正仅涉第二十九条等个别条）
        ("https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_5474cf75173c45d6a0379730fb4e8d97.html",
         "utf-8"),
        # 交叉验证源：巴音郭楞蒙古自治州政府转载 2021-04-29 第二次修正全文（74 条）
        ("https://www.xjbz.gov.cn/xjbz/c101593/202110/9ddf313d369947b58acba03e86173507.shtml",
         "utf-8"),
        # 交叉验证源：阜阳市政府转载全文（74 条，缺第 66 条；缺条不影响比对，只影响该条覆盖）
        ("https://www.fy.gov.cn/InKnowledgeBase/show/25174.html", "utf-8"),
        # **曾试作交叉验证源、已剔除**：中国政府网「国情」栏 content_5647620.htm 解析出 75 条，
        # 其第五十五条仍含「吊销广告发布登记证件」。而 2021-04-29《关于修改〈道路交通安全法〉
        # 等八部法律的决定》第（二）项**明确删去了第五十五条第三款、第五十七条、第五十八条
        # 第三款中的「吊销广告发布登记证件」**，第（三）项删去第六十条（故 75−1＝74 条）。
        # 即该页虽是「gov.cn」，内容却停留在 2015 年修正版。**域名权威 ≠ 版本现行**——
        # 这一条正是交叉验证抓出来的：两源都不含该短语，只有它含。
    ],
    "劳动法": [
        # **2026-10-22 换基准**：原基准是中国人大网《劳动法》2023 年前的旧页
        # （content_347911.htm），实为 **1994 年原版**——第十五条还是「必须依照国家有关规定，
        # 履行审批手续」、第六十九条「由经过政府批准的考核鉴定机构」、第九十四条「工商行政
        # 管理部门」，三处都停留在 2018 年修正**之前**的表述。
        # 判据不能看页面标题写没写「2018 修正」（多个政府转载页标题写着 2018、正文却是 1994 版），
        # 只能看这三处用词——这是 2018-12-29《关于修改〈中华人民共和国劳动法〉等七部法律的
        # 决定》对本法所做的**全部实质修改**（该次修正不增删条文，故仍 107 条）。
        # 基准：云南省人力资源和社会保障厅「2018年12月29日修正」全文，三处表述均已修正。
        ("https://hrss.yn.gov.cn/NewsView.aspx?pid=971&nid=63414&cid=682&isZt=7", "utf-8"),
        # 交叉验证源：宜宾市市场监督管理局转载主席令第 24 号全文（107 条，独立于云南人社厅）
        # 注意：该页第九十四条印作「由市场和监督管理部门」——多一个「和」字，属该页排印错字
        # （正式表述为「市场监督管理部门」）。库内收该条须以基准源为准，比对差异会如实落进
        # conflict 报告，不静默吞掉。
        ("https://scjgj.yibin.gov.cn/xbsy/xxfb/flfggz/202411/t20241128_2062379.html", "utf-8"),
        # 曾试作交叉验证源、已弃用：广州市消防救援支队、烟台市莱山区政府两页标题均标「2018修正」，
        # 正文第十五/六十九/九十四条却仍是 1994 原版表述。**标题不算证据，条文字面才算**。
    ],
    "食品安全法": [
        # **2026-10-22 换源**：原基准是中山检察在线转载页，只能解析出 5 条（第 148 条恰在其中），
        # 单源＋低覆盖，等于只有一条腿。以下三页均为 **2025-09-12 第三次修正、2025-12-01 施行**
        # 后的全文（154 条），互不隶属，构成真正的交叉验证。
        # 阿里地区市场监督管理局（全文 154 条）
        ("https://sj.al.gov.cn/info/3222/15361.htm", "utf-8"),
        # 黑龙江省疾病预防控制局（全文 154 条）
        ("https://jkj.hlj.gov.cn/hljjkj/countrynews/202510/c00_31879849.shtml", "utf-8"),
        # 内江高新技术产业开发区管委会（全文 154 条）
        ("https://gxq.neijiang.gov.cn/gxq/spypxgzc/202601/459a265bbe484e289b478920620c75f0.shtml",
         "utf-8"),
        # 注意：2025 修正为「小切口」，只动第 41、81、82、124、132 条，条号未增删，全法仍 154 条。
        # 若见「148 条」的说法，那是 2015 年修订版的条数，勿混用。
    ],
    "合同编通则解释": [
        # 最高人民法院《关于适用〈民法典〉合同编通则若干问题的解释》全文（法释〔2023〕13 号）
        ("https://www.court.gov.cn/fabu/xiangqing/419382.html", "utf-8"),
        # 交叉验证源：威海市环翠区政府转载全文（69 条，独立于最高法官网）
        ("http://www.huancui.gov.cn/art/2023/12/12/art_78980_4204746.html", "utf-8"),
    ],
    "公司法": [
        # 中国人大网 2023-12-29 修订全文（2024-07-01 施行）
        ("http://www.npc.gov.cn/npc/c2/c30834/202312/t20231229_433999.html", "utf-8"),
        # 交叉验证源：中国政府网转载新华社全文（266 条，独立于人大网）
        ("https://www.gov.cn/yaowen/liebiao/202312/content_6923395.htm", "utf-8"),
    ],
    "网络安全法": [
        # 中央网信办 2016 年全文（分 3 页，合一为一）；2025-10-28 修正，2026-01-01 施行，见 META.pending
        ("https://www.cac.gov.cn/2016-11/07/c_1119867116.htm", "utf-8"),
        ("https://www.cac.gov.cn/2016-11/07/c_1119867116_2.htm", "utf-8"),
        ("https://www.cac.gov.cn/2016-11/07/c_1119867116_3.htm", "utf-8"),
        # 曾试作交叉验证源、已弃用：宁蒗县政府 2016 版整页（79 条）——
        # 该页把「法律责任对照表」混排在全文之后，表内以「第二十五条」「第四十一条」
        # 开头的单元格被当成条头，导致 25/41/64 条正文串位。交叉验证正是靠这个
        # 才发现的（三源相比，它单方面对不上）。不换新版的理由：2025-10-28 修正后
        # 条号后移（新第八十一条＝旧第七十九条），跨版本比对必全冲突。
        # ---- 组 1–2：2016 版（79 条）独立源，**必须同版本**，否则条号后移必全冲突 ----
        # 人民网·中国共产党新闻网（人民日报 2016-11-23 第 14 版，79 条）
        ("https://npc.people.com.cn/n1/2016/1124/c14576-28892612.html", "utf-8"),
        # 亳州市教育局转载全文（79 条，与人民网亦不同站）
        ("https://jyj.bozhou.gov.cn/XxgkContent/show/2558525.html", "utf-8"),
        # 注意：蚌埠市淮上区版为 **81 条新法**（2025-10-28 修正后），与库内 79 条版条号整体后移，
        # 跨版本比对必全冲突，故**不采用**。这条经验写在这里，防止后人"看到有源就加"。
    ],
    "消费者权益保护法": [
        # 中国人大网 2013 年第二次修正全文（2014-03-15 施行，共 63 条）
        ("http://www.npc.gov.cn/zgrdw/npc/xinwen/2013-10/26/content_1811773.htm", "utf-8"),
        # 交叉验证源：阿拉善盟行政公署转载全文（63 条，独立于人大网）
        ("https://www.als.gov.cn/art/2019/8/20/art_74_255699.html", "utf-8"),
    ],
    "电子商务法": [
        # ---- 组 0：人民政协网受权发布全文（分 5 页，共 89 条；2019-01-01 施行）----
        ("https://www.rmzxw.com.cn/c/2018-08-31/2158330.shtml", "utf-8"),
        ("https://www.rmzxw.com.cn/c/2018-08-31/2158330_1.shtml", "utf-8"),
        ("https://www.rmzxw.com.cn/c/2018-08-31/2158330_2.shtml", "utf-8"),
        ("https://www.rmzxw.com.cn/c/2018-08-31/2158330_3.shtml", "utf-8"),
        ("https://www.rmzxw.com.cn/c/2018-08-31/2158330_4.shtml", "utf-8"),
        # ---- 组 1：中国人大网全文（89 条）----
        ("http://www.npc.gov.cn/zgrdw/npc/lfzt/rlyw/2018-08/31/content_2060827.htm", "utf-8"),
        # ---- 组 2：隆阳区人民政府转载全文（89 条）----
        ("https://www.longyang.gov.cn/info/13225/13672779.htm", "utf-8"),
    ],
    "数据安全法": [
        # 中央网信办全文（2021-09-01 施行，共 55 条）
        ("https://www.cac.gov.cn/2021-06/11/c_1624994566919140.htm", "utf-8"),
        # 交叉验证源：石家庄市藁城区政府转载全文（55 条，独立于网信办）
        ("https://www.gc.gov.cn/columns/8e15378c-0a26-4abf-b213-3a302d59a699/202204/08/"
         "3dc38a27-1d9f-4e93-a3f8-09b70600afc5.html", "utf-8"),
    ],
}

# 哪些 URL 属于「同一份文本的分页/补篇」——同组内的条号会自动拼接，**不与同组互证**。
# 只有跨组之间才做交叉验证，否则把同一页拆成几页就会误判成「两源一致」。
GROUPS = {
    "民法典": [0, 0, 0, 1, 1, 1, 1, 1, 1, 1],   # 前三处是转新华社同一篇（补篇），后七页为人民日报版（独立组 1）
    "网络安全法": [0, 0, 0, 1, 2],   # cac 分 3 页同组；人民网、亳州教育局各为独立组
    "电子商务法": [0, 0, 0, 0, 0, 1, 2],  # 人民政协 5 页同组；人大网组 1；隆阳区政府组 2
}
# 独立来源标注：给每个 URL 一个可读的「来源机构」名，写进库里的 sources 字段
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

# 法律版本元信息：核验时必须能回答「引的是哪一版、什么时候生效」。
# 无 effective 的表示抓到的是现行有效文本、但未核到精确施行日，核验报告按「来源页日期」提示。
META = {
    "民法典": {"version": "2020-05-28 通过", "effective": "2021-01-01"},
    "劳动合同法": {"version": "2012-12-28 修正", "effective": "2013-07-01"},
    "个人信息保护法": {"version": "2021-08-20 通过", "effective": "2021-11-01"},
    "民事诉讼法": {"version": "2023-09-01 修正", "effective": "2024-01-01"},
    "反不正当竞争法": {
        "version": "2025-06-27 第二次修订",
        "effective": "2025-10-15",
        # 换版留痕：条号相对 2019 版整体后移，历史意见/旧模板里的条号不能直接沿用。
        "note": "2025-10-15 施行。相对 2019 版条号后移：旧第七（商业贿赂）→新第八；"
                "旧第九（商业秘密）→新第十；旧第十七（民事责任）→新第二十二；"
                "旧第三十二（商业秘密举证责任）→新第三十九。引用 2019 年前文本的条号须重新对位。",
    },
    "反垄断法": {"version": "2022-06-24 修正", "effective": "2022-08-01"},
    "著作权法": {"version": "2020-11-11 修正", "effective": "2021-06-01"},
    "商标法": {
        "version": "2019-04-23 修正",
        "effective": "2019-11-01",
        "pending": {
            "version": "2026-06-26 修订",
            "effective": "2027-01-01",
            "note": "修订后条号整体前移（原第四十三条＝新第四十七条），引用时须注明所据版本",
        },
    },
    "广告法": {"version": "2021-04-29 修正", "effective": "2021-04-29"},
    "劳动法": {"version": "2018-12-29 修正", "effective": "2018-12-29"},
    "食品安全法": {
        "version": "2025-09-12 修正",
        "effective": "2025-12-01",
        # 该次为「小切口」修正：第四十一条加四款（重点液态食品道路散装运输许可）、
        # 第八十一条/第八十二条/第一百二十四条「婴幼儿配方乳粉」后加「婴幼儿配方液态乳」、
        # 第一百三十二条加三款。**条号未变**，故库内第一百四十八条仍沿用原文本；
        # 但引用第四十一、八十一、八十二、一百二十四、一百三十二条时须按 2025 版新表述。
        "note": "2025-12-01 施行「小切口」修正（重点液态食品散装运输许可、婴幼儿配方液态乳"
                "纳入注册管理）。改动集中在第 41、81、82、124、132 条，其余条文含库内"
                "第 148 条文本未变，条号亦未移动。",
    },
    "合同编通则解释": {"version": "法释〔2023〕13 号", "effective": "2023-12-05"},
    "公司法": {"version": "2023-12-29 修订", "effective": "2024-07-01"},
    "网络安全法": {
        "version": "2016-11-07 通过",
        "effective": "2017-06-01",
        "pending": {
            "version": "2025-10-28 修正",
            "effective": "2026-01-01",
            "note": "修正案主要调整法律责任章罚款幅度与部分义务条款，条号基本未动，但引用时须注明所据版本",
        },
    },
    "消费者权益保护法": {"version": "2013-10-25 第二次修正", "effective": "2014-03-15"},
    "电子商务法": {"version": "2018-08-31 通过", "effective": "2019-01-01"},
    "数据安全法": {"version": "2021-06-10 通过", "effective": "2021-09-01"},
}

# 需要重点核验的条号（来自 core 规则库与 02 核验清单的实际引用）
# 说明：以「规则库真在用」为主，再按合同/劳动/数据合规四条主线补到够用为止——
# 法律条文库不是法典全集，收进来就得能核准，宁少几不要错一条。
WANTED = {
    # 民法典：总则编法律行为效力＋合同编通则（合同审查真正高频区）
    "民法典": [
        # 总则编：意思表示与民事法律行为效力
        137, 140, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152,
        153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 165, 166, 167,
        168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179,
        # 总则编：代理、期间、诉讼时效
        188, 192, 194, 195,
        # 合同编通则：一般规定
        463, 464, 465, 466, 467, 468, 469,
        # 合同的订立（要约、承诺、格式条款、缔约过失）
        470, 471, 472, 473, 474, 475, 476, 477, 478, 479, 480, 481, 482,
        483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493, 494, 495,
        496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506, 507, 508,
        # 合同的效力、履行
        509, 510, 511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521,
        522, 523, 524, 525, 526, 527, 528, 529, 530, 531, 532, 533, 534,
        # 合同的保全、变更和转让
        535, 536, 537, 538, 539, 540, 541, 542, 543, 544, 545, 546, 547,
        548, 549, 550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560,
        # 合同的权利义务终止、违约责任
        561, 562, 563, 564, 565, 566, 567, 568, 569, 570, 571, 572, 573,
        574, 575, 576, 577, 578, 579, 580, 581, 582, 583, 584, 585, 586,
        587, 588, 589, 590, 591, 592, 593, 594,
        # 典型合同：买卖
        595, 596, 597, 598, 599, 600, 602, 603, 604, 605, 606, 607, 608,
        609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 620, 621,
        622, 623, 624, 625, 626, 627,
        # 典型合同：供用电水气热力、赠与、借款、保证、租赁
        628, 629, 630, 631, 632, 633, 634, 635, 636, 637, 638, 639, 640,
        641, 642, 643, 644, 645, 646, 667, 668, 669, 670, 671, 672, 673,
        674, 675, 676, 677, 678, 679, 680, 681, 682, 683, 684, 685, 686,
        687, 688, 689, 690, 691, 692, 693, 694, 695, 696, 697, 698, 699,
        700, 701, 702, 703, 704, 705, 706, 707, 708, 709, 710, 711, 712,
        713, 714, 715, 716, 717, 718, 719, 720, 721, 722, 723, 724, 725,
        726, 727, 728, 729, 730, 731, 732, 733, 734,
        # 侵权责任编：产品责任、机动车、饲养动物
        1202, 1203, 1206, 1207, 1213, 1245, 1246, 1247,
    ],
    "劳动合同法": [
        4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21,
        22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
        38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53,
        54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
        70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85,
        86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98,
    ],
    "个人信息保护法": [
        4, 5, 6, 13, 14, 15, 16, 17, 18, 21, 23, 24, 25, 26, 27, 28, 29,
        30, 31, 32, 33, 34, 35, 38, 39, 40, 44, 45, 46, 47, 49, 51, 52,
        55, 56, 57, 58, 59, 66, 69, 72,
    ],
    "民事诉讼法": [22, 23, 24, 34, 35, 36, 67, 122, 127, 235, 236, 260],
    "反不正当竞争法": [7, 8, 9, 10, 11, 12, 22, 39],
    "反垄断法": [17, 18, 19, 22, 56],
    "著作权法": [3, 10, 11, 17, 18, 19, 24, 52, 53, 54],
    "商标法": [43, 57, 63],
    # 4/29/44 是 industries/newmedia-rules.md 实际在引的条号（真实性原则、广告发布登记已删、
    # 大众媒介发布要求），此前 WANTED 没收，导致规则引了库里却没有、无从核对。
    "广告法": [4, 9, 15, 16, 17, 18, 28, 29, 38, 44, 46, 55, 56],
    "劳动法": [3, 25, 31, 36, 38, 41, 44, 47, 50, 72, 82],
    "食品安全法": [148],
    # 合同编通则解释：合同订立、效力、履行、违约责任四大块
    "合同编通则解释": [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37,
        38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53,
        54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
    ],
    # 公司法：出资、股权转让、股东权利、董监高义务、清算
    "公司法": [
        4, 5, 21, 22, 23, 44, 46, 47, 48, 49, 50, 51, 52, 53, 54, 56,
        57, 71, 84, 88, 89, 91, 152, 163, 180, 181, 182, 183, 184, 185,
        186, 188, 191, 192, 211, 232, 233, 240, 241, 251, 265, 266,
    ],
    # 网络安全法：等级保护、个人信息、关键信息基础设施、法律责任
    "网络安全法": [
        9, 10, 12, 21, 22, 23, 24, 25, 27, 28, 31, 34, 35, 37, 38, 40,
        41, 42, 43, 44, 45, 46, 64, 76,
    ],
    # 消费者权益保护法：经营者义务、格式条款、个人信息、惩罚性赔偿
    "消费者权益保护法": [
        4, 7, 8, 9, 10, 11, 16, 18, 19, 20, 22, 23, 24, 25, 26, 27, 28,
        29, 39, 44, 45, 49, 50, 51, 52, 53, 55, 56,
    ],
    # 电子商务法：平台责任、格式条款、电子合同、知识产权通知
    "电子商务法": [
        15, 17, 18, 19, 20, 21, 27, 28, 30, 31, 32, 34, 35, 36, 37, 38,
        39, 40, 41, 42, 43, 45, 48, 49, 50,
    ],
    # 数据安全法：分类分级、重要数据、数据处理者义务、跨境
    "数据安全法": [
        3, 4, 6, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 35,
        36, 37, 41, 42, 43, 44, 45, 46, 51,
    ],
}


def fetch(url, enc, tries=3):
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


ART_RE = re.compile(r"第([一二三四五六七八九十百千零〇\d]{1,8})条[　 ]*")

# 条号必须出现在「行首」或紧跟在句末标点/右括号/冒号之后——否则是正文里的交叉引用
# （如「违反本法第四十六条规定」「不适用本法第十七条、第十八条」），把它当成条头会整体错位。
_HEAD_OK = set("。；：！？\n\r）)》”」")

# 序号式章节标题（「三、合同的效力」）的词表：只认这些，避免误伤正文列举项
_SECTION_TAIL = ("(?:总\s*则|附\s*则|合同的订立|合同的效力|合同的履行|合同的保全|"
                 "合同的变更和转让|合同的权利义务终止|违约责任|其他规定|一般规定)")


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
        if no:
            out.append((i, m.end(), no))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="输出路径（默认 core/legal-articles.json）")
    ap.add_argument("--dump-raw", default=None,
                    help="把每个 URL 的原始抽条结果落盘（调试/复核用）")
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", "doc-compliance-review"))
    out = a.out or os.path.join(root, "core", "legal-articles.json")

    _load_crosscheck(here)

    result, missing, srcs = {}, {}, []
    stats = {}          # 法名 → {"multi-ok": n, "single": n, "conflict": n, "missing": n}
    conflicts = []      # 冲突明细（写进 report/legal-conflicts.json）
    raw_dump = {}

    for law, urls in SOURCES.items():
        groups = GROUPS.get(law) or list(range(len(urls)))
        if len(groups) != len(urls):
            print("[!] %s 的 GROUPS 长度(%d) 与 SOURCES(%d) 不符，按「每 URL 独立」处理"
                  % (law, len(groups), len(urls)))
            groups = list(range(len(urls)))

        # 逐 URL 抽条
        per_url = []
        for idx, (url, enc) in enumerate(urls):
            p = {"url": url, "grp": groups[idx], "name": src_name(url),
                 "got": {}, "ok": False}
            try:
                text = to_text(fetch(url, enc))
            except Exception as ex:
                print("[抓取失败] %s：%s" % (url, ex))
                per_url.append(p)
                continue
            got = parse_articles(text)
            print("[抓取] %-8s %s → %d 条" % (law, url[:52], len(got)))
            p["got"], p["ok"] = got, bool(got)
            per_url.append(p)
            srcs.append({"law": law, "url": url, "name": src_name(url),
                         "articles": len(got),
                         "fetched": datetime.date.today().isoformat()})
        raw_dump[law] = {p["url"]: len(p["got"]) for p in per_url}

        # 组分页拼接：同组内的条号是同一份文本的不同页，先拼后比
        grp_texts, grp_names = {}, {}       # grp → {条号: 正文} / grp → 来源名
        for p in per_url:
            if not p["ok"]:
                continue
            g = grp_texts.setdefault(p["grp"], {})
            grp_names.setdefault(p["grp"], p["name"])
            for k, v in p["got"].items():
                if k not in g or len(v) > len(g[k]):
                    g[k] = v

        # 逐条判定：同条号跨组比对（同组内是分页，不算独立源）
        merged, verdicts, cand_srcs = {}, {}, {}
        for no in sorted({k for g in grp_texts.values() for k in g}):
            # 比对前先剥「条文小标题」：部分转载页把「服务期」这类标题挤在条号后，
            # 另一源没有——不先剥就会把标题当正文差异，整部法误报冲突。
            cand = [("G%d·%s" % (gi, grp_names[gi]), strip_line_title(g[no], law, no))
                    for gi, g in sorted(grp_texts.items()) if no in g]
            merged[no] = cand[0][1] if len(cand) == 1 else _pick_best(cand)
            cand_srcs[no] = [s for s, _t in cand]
            verdicts[no] = CROSS.verdict(cand) if len(cand) > 1 else {
                "status": "single", "verified": False, "ratio": None, "conflict": None}

        want = WANTED.get(law) or sorted(merged)
        arts = {}
        stat = {"multi-ok": 0, "single": 0, "conflict": 0, "missing": 0}
        for no in want:
            body = merged.get(no)
            if body:
                body = strip_line_title(body, law, no)
                body = strip_footer(body)
            if body and looks_garbage(body):
                print("[可疑] %-8s 第%s条 疑似解析垃圾，已剔除 → %s" % (law, no, body[:40]))
                body = None
            if not body:
                missing.setdefault(law, []).append(no)
                stat["missing"] += 1
                continue
            v = verdicts.get(no) or {}
            ent = {
                "no": no,
                "anchor": short_anchor(body),
                "text": body,
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
                "verified": bool(v.get("verified")),
                "status": v.get("status") or "single",
            }
            if len(cand_srcs.get(no) or []) > 1:
                ent["sources"] = cand_srcs[no]
            if v.get("ratio") is not None:
                ent["ratio"] = v["ratio"]
            if v.get("conflict"):
                ent["conflict"] = v["conflict"]
                conflicts.append({"law": law, "no": no, "ratio": v["ratio"],
                                  **v["conflict"]})
            arts[str(no)] = ent
            key = ("multi-ok" if v.get("verified")
                   else "conflict" if v.get("conflict") else "single")
            stat[key] += 1
        result[law] = arts
        stats[law] = stat

    # 全局统计
    all_ents = [e for v in result.values() for e in v.values()]
    n_all = len(all_ents)
    n_ver = sum(1 for e in all_ents if e.get("verified"))
    n_con = sum(1 for e in all_ents if e.get("status") == "conflict")
    n_single = n_all - n_ver - n_con

    db = {
        "_说明": "法条原文核验库（开发侧生成，随技能包分发）。审查引法条时以本库为唯一真值来源；"
                 "本库没有的条号一律标「待核验」，不得凭记忆引用。条文以现行有效版本为准。",
        "_用法": "核验三件事：①条号存不存在 ②引述的句子能不能在本条原文里找到 ③引的是哪一版。"
                 "三者任一不过，一律降级为「待核验」并在报告里写明差在哪。",
        "_交叉验证": {
            "机制": "同一部法从 ≥2 个彼此独立的来源抓同一批条号，逐条比对正文；"
                    "一致记 verified=true，不一致记 verified=false + status=conflict 并保留两版差异，"
                    "只有一源记 verified=false + status=single。**不猜谁对**——冲突交人工裁决。",
            "比对口径": "只比中文字与数字，剔除标点空白；4 字片段双向覆盖率取较小值；"
                        "阈值 0.985（允许全半角/的 字等转载噪声，漏一句必跌破）。",
            "分页处理": "同一份文本拆成多页的 URL 记在 GROUPS 同组，先拼后比，"
                        "**不把分页当独立源**，否则会把「同一页」误判成「两源一致」。",
            "统计": {"总条数": n_all, "多源一致": n_ver, "单源未核": n_single,
                     "多源冲突": n_con,
                     "多源一致率": round(n_ver / float(n_all), 4) if n_all else 0},
            "口径": "verified=true 只表示「多源一致」，不等于「现行有效」；"
                    "冲突条与单源条引用时必须人工复核官方文本（flk.npc.gov.cn）。",
        },
        "generated": datetime.date.today().isoformat(),
        "sources": srcs,
        "laws": result,
        "meta": META,
        "missing": missing,
        "_校验": "每条含 sha256 前 16 位，供人工复核原文未被篡改。",
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    total = sum(len(v) for v in result.values())
    print("\n落盘：%s（%d 部法 / %d 条）" % (out, len(result), total))

    # 交叉验证报告
    rep = os.path.join(root, "report", "legal-crosscheck.json")
    os.makedirs(os.path.dirname(rep), exist_ok=True)
    with open(rep, "w", encoding="utf-8") as f:
        json.dump({"generated": db["generated"], "stats": stats,
                   "overall": db["_交叉验证"]["统计"],
                   "conflicts": conflicts}, f, ensure_ascii=False, indent=1)
    print("交叉验证报告：%s" % rep)

    print("\n%-14s %6s %8s %8s %8s" % ("法律", "条数", "多源一致", "单源", "冲突"))
    for law, st in stats.items():
        print("%-14s %6d %8d %8d %8d" % (law, len(result[law]), st.get("multi-ok", 0),
                                         st.get("single", 0), st.get("conflict", 0)))
    print("%-14s %6d %8d %8d %8d" % ("合计", total, n_ver, n_single, n_con))
    if n_con:
        print("\n[冲突] 以下条号多源不一致，须人工裁决（原文已保留，未择一）：")
        for c in conflicts[:20]:
            print("  《%s》第%s条  一致度 %.3f" % (c["law"], c["no"], c["ratio"]))
            print("    仅基准源有：%s" % (c.get("only_base") or "—"))
            print("    仅对比源有：%s" % (c.get("only_other") or "—"))
    if missing:
        print("\n未抓到（须人工补或标待核验）：", json.dumps(missing, ensure_ascii=False))
    if a.dump_raw:
        with open(a.dump_raw, "w", encoding="utf-8") as f:
            json.dump(raw_dump, f, ensure_ascii=False, indent=1)


def _pick_best(cand):
    """多源时选「最长」作底本——通常最完整；差异另记在 conflict 里，不丢信息。"""
    return max((t for _s, t in cand), key=len)


def _load_crosscheck(here):
    """加载比对模块。优先同目录（开发侧），其次随包 scripts/（已装运行实例）。"""
    global CROSS
    for p in (os.path.join(here, "legal-crosscheck.py"),
              os.path.join(here, "..", "..", "doc-compliance-review", "scripts",
                           "legal-crosscheck.py")):
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("legal_crosscheck", p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            CROSS = m
            return
    raise SystemExit("[E] 找不到 legal-crosscheck.py（比对模块），无法做交叉验证")


if __name__ == "__main__":
    main()
