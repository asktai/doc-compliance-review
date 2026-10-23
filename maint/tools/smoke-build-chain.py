#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建库链冒烟（开发侧，**离线**）

为什么要有它（2026-10-23 质检发现）
------------------------------------------------------------------------------
v3.23.0 把抓取＋解析整段抽到随包的 `scripts/legal-parse.py`，建库侧改为 import。
当时**逐个点名绑定**了 9 个函数（fetch/to_text/parse_articles/...），
而 `main()` 里还直接用到 `strip_footer` 等——**重构后一次都没真跑过建库**，
质检时 `--only 劳动法` 当场 NameError。也就是说：
**换库这条链路在 v3.23.0 里是坏的，而 check.py 与冒烟都覆盖不到开发侧脚本**。

本脚本做的正是那次没做的事：离线加载建库模块、注入解析链，
断言 main() 会用到的名字**全都在位**。不联网、不写库，秒级可跑。
"""
import importlib.util
import os
import sys

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.abspath(os.path.join(HERE, "..", "..", "doc-compliance-review"))

# main() 里会直接调用的名字（**不是**全部导出，是建库真正依赖的那些）
NEEDED = ["fetch", "to_text", "parse_articles", "strip_line_title", "src_name",
          "strip_footer", "strip_tail_noise", "looks_garbage", "is_garbage_text",
          "short_anchor", "cn2int", "UA", "SRC_NAMES", "LINE_TITLES"]


def main():
    ok, bad = [], []

    def check(name, cond, detail=""):
        (ok if cond else bad).append("%s%s" % (name, ("：" + detail) if detail else ""))

    p = os.path.join(HERE, "build-legal-db.py")
    spec = importlib.util.spec_from_file_location("build_legal_db", p)
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    B._load_parse(HERE)
    B._bind_parse()

    missing = [n for n in NEEDED if not hasattr(B, n)]
    check("建库所需的解析链名字全部在位（漏一个就会在中途 NameError）",
          not missing, "缺 %s" % "、".join(missing) if missing else "")
    check("解析链来自**随包那份**（不是开发侧副本）",
          os.path.realpath(B.PARSE.__file__).startswith(os.path.realpath(SKILL)),
          os.path.realpath(B.PARSE.__file__))

    # 巡检与建库必须指到同一个模块——两套解析链会让「一致/不一致」不可比
    pp = os.path.join(SKILL, "scripts", "freshness-patrol.py")
    check("包内巡检存在", os.path.exists(pp))
    src = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
    check("巡检经 legal-parse.py 联网（不自带网络库，网络代码集中一处）",
          "PARSE.fetch" in src and "import urllib" not in src)

    # GROUPS 与 SOURCES 长度必须相符，否则分页会被当成独立源
    mism = [law for law, urls in B.SOURCES.items()
            if law in B.GROUPS and len(B.GROUPS[law]) != len(urls)]
    check("GROUPS 与 SOURCES 长度一致（分页不被误当独立源）", not mism,
          "、".join(mism) if mism else "")

    print("建库链冒烟（离线）")
    for x in ok:
        print("  [OK] " + x)
    for x in bad:
        print("  [FAIL] " + x)
    print("结果：%d 项通过、%d 项失败" % (len(ok), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
