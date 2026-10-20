#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元自测：把每一维守卫「打瘸」，全量冒烟须当场报"未拦住"。

依据铁律 12.5.4.3：判据不得是"注入了就报错"，须是"因这一注入而新增报错"；
并须以元自测证明——**把被测项打瘸，冒烟当场须报"未拦住"**。
反之，"判据失去区分度，等同没验"。

做法：生成若干"变异版自检脚本"（每个禁掉一维的报错出口），
用 `smoke-dev-rules.py --check <变异脚本>` 跑，**期望该脚本以非零退出、且报出"未拦住"**。
若某个变异版本竟让冒烟**照常通过**，即证明该维判据无区分度——本元自测报错。

不碰正式文件；全部变异体写在临时目录，跑完即删。
"""
import os
import re
import subprocess
import sys

DEV = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECK = os.path.join(DEV, "maint", "tools", "check-dev-rules.py")
SMOKE = os.path.join(DEV, "maint", "tools", "smoke-dev-rules.py")

# 每项：(维号, 说明, 该维在 main() 里的调用语句)
# 原则：**直接让该维不再被调用**（从 main 里删掉那一行）——
# 这样若冒烟仍报"通过"，就说明它没有真正验证这一维。
# 2026-10-20 改：原先按"把 err("改成 info(" 打瘸"，但 (9)(10)(13) 等维是
#   **累积到 b 再统一 err(b)**，不写内联 err，替换字符串压根对不上——
#   对不上的打瘸点等于**没验**（元自测自己踩了 12.5.4.3 的坑）。
#   改为按**调用语句**打瘸，与各维内部实现解耦。
CRIPPLES = [
    (1, "条号连续性", "check_structure(s)"),
    (2, "导读表", "check_guide(s)"),
    (3, "悬空引用", 'check_refs(s, show="--refs" in args)'),
    (4, "废止词", "check_wording(s)"),
    (5, "表述", "check_expression(s)"),
    (6, "路径真实", "check_paths(s)"),
    (7, "版本串", "check_rules_version(s)"),
    (9, "目录锚点", "check_toc_anchor(s)"),
    (10, "引用锚点", "check_ref_anchor(s)"),
    (11, "加粗编号", "check_bold_heading(s)"),
    (12, "元规则", "check_meta_rules(s)"),
    (13, "落实总表", "check_closure_table(s)"),
]

TAG = "元自测"

# 第 8、14 维走"单独一档"（要改磁盘文件才能注入），不能从 main 里删调用——
# 那样连基线都跑不起来（自检只解析出 0 维，属"脚本未运行"而非"守卫失效"）。
# 改为**让该维函数一进就 return**：维度标题照出，只是不报任何错。
# 判据：冒烟须报"守卫失效"，**且不得是靠"基线未过"蒙对的**。
CRIPPLES_FN = [
    (8, "跨侧一致性", "def check_cross_side(s_ignored=None):"),
    (14, "在线版同步", "def check_online_md(s):"),
]


def run_smoke(script):
    """跑冒烟，返回 (rc, out)。"""
    p = subprocess.run([sys.executable, SMOKE, "--check", script],
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


def main():
    src = open(CHECK, encoding="utf-8").read()
    # **变异体必须写在 check-dev-rules.py 同目录**：该脚本按 `__file__` 反推 DEV 根，
    # 放进 /tmp 会找不到 DEV-RULES.md，报"规范文件不存在"——那是**脚本没跑起来**，
    # 不是"守卫失效"，两者混淆会让元自测假过（2026-10-20 实测踩过）。
    here = os.path.dirname(CHECK)
    fails = []
    print("铁律冒烟·元自测（把守卫打瘸，看冒烟报不报）")
    print("=" * 62)
    print("依据 12.5.4.3：判据须有区分度——弄坏了却仍报通过，等于没验。\n")

    made = []
    try:
        for dim, name, call in CRIPPLES:
            # 只删 main() 里那一行调用（该行在 main 内出现且只出现一次）
            old = "    " + call + "\n"
            if old not in src:
                fails.append((dim, name, "打瘸点未命中（main 里的调用语句已改形，需更新本表）"))
                print("  [E] (%2d) %-12s 打瘸点未命中——本项**没验到**" % (dim, name))
                continue
            bad = src.replace(old, "", 1)
            p = os.path.join(here, "_crippled_%d.py" % dim)
            made.append(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(bad)
            rc, out = run_smoke(p)
            # 期望：冒烟非零退出，且输出里出现「未拦住」或「用例失效」
            caught = rc != 0 and ("未拦住" in out or "用例失效" in out or "[E]" in out)
            if caught:
                print("  [OK] (%2d) %-12s 冒烟当场报错（rc=%d）" % (dim, name, rc))
            else:
                fails.append((dim, name, "打瘸后冒烟**仍报通过**——该维判据无区分度"))
                print("  [E] (%2d) %-12s **打瘸后冒烟仍通过**（rc=%d）— 该维等于没验"
                      % (dim, name, rc))

        for dim, name, sig in CRIPPLES_FN:
            if sig not in src:
                fails.append((dim, name, "打瘸点未命中（函数签名已改形，需更新本表）"))
                print("  [E] (%2d) %-12s 打瘸点未命中——本项**没验到**" % (dim, name))
                continue
            bad = src.replace(sig, sig + "\n    return", 1)
            p = os.path.join(here, "_crippled_%d.py" % dim)
            made.append(p)
            with open(p, "w", encoding="utf-8") as f:
                f.write(bad)
            rc, out = run_smoke(p)
            # 判据要**更严**：须出现该维的"守卫失效"字样，
            # 不能因为"基线未过"（脚本没跑起来）就算数——那是假过。
            hit_gone = "守卫失效" in out or "未报" in out
            if rc != 0 and hit_gone:
                print("  [OK] (%2d) %-12s 冒烟当场报「守卫失效」（rc=%d）" % (dim, name, rc))
            else:
                why = "打瘸后冒烟仍通过" if rc == 0 else "报错但非「守卫失效」——可能是基线未过，属误判"
                fails.append((dim, name, why))
                print("  [E] (%2d) %-12s %s" % (dim, name, why))
    finally:
        for p in made:
            try:
                os.remove(p)
            except OSError:
                pass

    print("\n" + "=" * 62)
    # 数字**从两张表派生**，不手写常量——写死过一次：两组各改各的，
    # 结论行仍报"12 个打瘸点"，而实际跑了 14 个（铁律第 12 条：同一事实两处写必漂）。
    total = len(CRIPPLES) + len(CRIPPLES_FN)
    if fails:
        print("元自测未通过：%d／%d 个打瘸点未被发现（该项判据无区分度）"
              % (len(fails), total))
        for dim, name, why in fails:
            print("  · (%d) %s：%s" % (dim, name, why))
        return 1
    print("元自测通过：%d 个打瘸点（逐维 %d ＋ 单列档 %d），冒烟全部当场发现"
          % (total, len(CRIPPLES), len(CRIPPLES_FN)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
