#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc-compliance-review · 云端开发侧发布脚本
==========================================
职责：把开发侧改动发布到 WorkBuddy 技能运行目录，并自动跑结构校验与指纹校验。

用法：
    python3 /workspace/dev/publish.py            # 同步 + 校验
    python3 /workspace/dev/publish.py --check    # 只校验，不同步
    python3 /workspace/dev/publish.py --pack     # 发布后另跑 pack.py 出分发包（到 /workspace/dist）

约定（写死）：
    - 开发主目录   /workspace/dev/doc-compliance-review/   （git 管理，改动在这里做）
    - 运行实例     /root/.codebuddy/skills/doc-compliance-review/
    - 维护侧目录   /workspace/dev/maint/                    （开发日志等，永不进技能包、永不发布）
    - 分发包产出   /workspace/dist/                         （pack.py 自动排除 private/）
"""
import os
import shutil
import subprocess
import sys

DEV = "/workspace/dev/doc-compliance-review"
RUN = os.path.expanduser("~/.codebuddy/skills/doc-compliance-review")
MAINT = "/workspace/dev/maint"
DIST = "/workspace/dist"
# 发布时排除的维护侧/生成物文件（只存在于开发侧，不进运行实例；
# .integrity.json 是运行实例 --sign 生成的指纹台账，属运行侧生成物，
# 同步会以开发侧旧版覆盖新指纹导致 --verify 误报）
EXCLUDE = {".git", "__pycache__", ".DS_Store", ".integrity.json"}


def sync():
    if not os.path.isdir(DEV):
        print("[publish] 开发目录不存在：%s" % DEV, file=sys.stderr)
        return 2
    if os.path.isdir(RUN):
        shutil.rmtree(RUN)
    shutil.copytree(DEV, RUN, ignore=shutil.ignore_patterns(*EXCLUDE))
    n = sum(len(f) for _, _, f in os.walk(RUN))
    print("[publish] 已同步 %d 个文件 → %s" % (n, RUN))
    return 0


def verify():
    ok = True
    for args in (["check.py"], ["check.py", "--verify"]):
        r = subprocess.run([sys.executable, os.path.join(RUN, "scripts", args[0])] + args[1:],
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or ["(无输出)"]
        print("[publish] %-12s → %s" % (" ".join(args), tail[0]))
        if r.returncode != 0:
            ok = False
    return 0 if ok else 1


def pack():
    os.makedirs(DIST, exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(RUN, "scripts", "pack.py"),
                        "--out", DIST], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    return r.returncode


def main():
    a = sys.argv[1:]
    if "--check" in a:
        return verify()
    if sync() != 0:
        return 2
    rc = verify()
    if "--pack" in a and rc == 0:
        rc = pack() or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
