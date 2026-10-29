#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  只读写技能目录内的版本清单与文件 → 绝对离线，不得引入任何网络库
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）

"""把一份技能目录转为「分发形态」——运行实例与发布包应当长得一样。

为什么需要这个脚本（v3.26.2，实测踩出来的坑）：
    运行实例（如 /root/.codebuddy/skills/<技能>）是从开发源**整目录同步**来的。
    源里 `version.json` 带几十条 history、根目录有 VERSION.md——那是维护侧的东西。
    整目录同步会把它俩一起搬过去，于是实例变成半个开发源：
      1. 用户问「以前各版改了什么」，模型直接在 version.json 里读到全部沿革 → 泄露；
      2. 实例没有 VERSION.md，check.py 按「无 `_分发副本` 标记＝开发源」判，
         报「缺少文件: VERSION.md」→ 装好即红（与千问办公那次同型）。
    两件事同一个根因：**实例的形态该是「分发副本」，不是「开发源」**。
    手工剥一次不算解决——下次同步又带回来。所以固化成这一步。

做什么（三件，幂等）：
    1. version.json 剥掉 history，写入 `"_分发副本": true`（副本自证身份）；
    2. 删除 VERSION.md（沿革不随分发）；
    3. 打印结果，便于发布链留痕。

用法：
    python scripts/dist-mode.py <技能目录>            就地转换（可反复跑）
    python scripts/dist-mode.py <技能目录> --check    只体检，不合规退出码 1
"""

import argparse
import json
import os
import sys

VERSION_REL = "version.json"
HISTORY_FILE = "VERSION.md"
DIST_FLAG = "_分发副本"


def convert(root, check_only=False):
    """返回 (是否需要改动/是否不合规, 说明行列表)。"""
    notes = []
    dirty = []

    vj = os.path.join(root, VERSION_REL)
    if not os.path.exists(vj):
        return True, ["[E] 找不到 %s——不是技能目录？" % VERSION_REL]

    try:
        with open(vj, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return True, ["[E] %s 解析失败：%r" % (VERSION_REL, e)]
    if not isinstance(d, dict):
        return True, ["[E] %s 顶层不是对象" % VERSION_REL]

    hist = d.get("history")
    if hist:
        dirty.append("剥掉 history %d 条" % len(hist))
        if not check_only:
            d.pop("history", None)
    if d.get(DIST_FLAG) is not True:
        dirty.append("补写 `%s: true` 标记" % DIST_FLAG)
        if not check_only:
            d[DIST_FLAG] = True

    if dirty and not check_only:
        with open(vj, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")

    vm = os.path.join(root, HISTORY_FILE)
    if os.path.exists(vm):
        dirty.append("删除 %s（沿革不随分发）" % HISTORY_FILE)
        if not check_only:
            os.remove(vm)

    if dirty:
        head = "[E] 仍是开发源形态：" if check_only else "[OK] 已转为分发形态："
        notes.append(head + "；".join(dirty))
    else:
        notes.append("[OK] 已是分发形态（无 history、带 `%s` 标记、无 %s）"
                     % (DIST_FLAG, HISTORY_FILE))

    ver = (d.get("latest") or {}).get("version")
    if ver:
        notes.append("[i] 版本：%s" % ver)
    return bool(dirty), notes


def main():
    ap = argparse.ArgumentParser(
        description="把技能目录转为分发形态（剥 history、写 _分发副本 标记、删 VERSION.md）")
    ap.add_argument("root", help="技能目录（含 SKILL.md 与 version.json）")
    ap.add_argument("--check", action="store_true",
                    help="只体检不修改；不合规时退出码 1（供发布链/门禁调用）")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        print("[E] 不是目录：%s" % root)
        return 2
    bad, notes = convert(root, a.check)
    for n in notes:
        print(n)
    if a.check and bad:
        print("[E] 提示：跑 `python scripts/dist-mode.py %s` 就地转换（幂等，可反复跑）" % a.root)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
