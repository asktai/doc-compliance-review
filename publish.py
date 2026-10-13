#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc-compliance-review · 云端开发侧发布脚本
==========================================
职责：把开发侧改动发布到 WorkBuddy 技能运行目录，并自动跑结构校验与指纹校验。

用法：
    python3 /workspace/dev/publish.py            # 同步 + 重建生成物 + 实例测试 + 校验
    python3 /workspace/dev/publish.py --check    # 只校验，不同步（不跑实例测试）
    python3 /workspace/dev/publish.py --pack     # 以上全绿后再出分发包（到 /workspace/dist）
    python3 /workspace/dev/publish.py --no-instance-test   # 应急：跳过实例测试（务必记 DEVLOG）

约定（写死）：
    - 开发主目录   /workspace/dev/doc-compliance-review/   （git 管理，改动在这里做）
    - 运行实例     /root/.codebuddy/skills/doc-compliance-review/
    - 维护侧目录   /workspace/dev/maint/                    （开发日志等，永不进技能包、永不发布）
    - 分发包产出   /workspace/dist/                         （pack.py 自动排除 private/）

发布链（顺序固定，勿调整）：
    sync → **重建生成物** → **实例测试** → verify → （--pack 时）pack

  (1) sync            rmtree 清干净后镜像重建运行实例
  (2) 重建生成物      规则基线、脚本指纹台账（rmtree 已把旧实例连同生成物一起删掉）
  (3) **实例测试**    在运行实例侧**端到端实跑**冒烟——这是唯一"真的跑一遍"的关卡，
                    验的是"装到实例后能不能真跑"（结构校验验不出这个）。**失败即阻断发布**。
                    档位：默认**轻量档**；带 `--pack` 出包时自动转**全量档**（发版前要求更严）。
                    放在 verify **之前**：冒烟会写"冒烟结果台账"，随后 check.py 即可校验到本次实跑的数字。
  (4) verify          结构校验 + 脚本指纹校验
  (5) pack            出分发包（仅在前面全绿时执行）


生成物治理（V3.8.2 定型，勿退化）：
    下列文件是**运行侧生成物**，开发侧一律不留存（已在 .gitignore 登记并移出 git）：
      - scripts/.integrity.json        check.py --sign 生成的脚本指纹台账
      - core/_rules-baseline.json      rule-baseline.py --update 生成的规则回归基线条账
      - core/_smoke-baseline.json      smoke-test.py 跑完自动记账的冒烟结果台账
    因为 sync 是「先 rmtree 清干净再镜像重建」，运行实例原有的生成物会被一并删除，
    故发布流程固定为：sync → **当场重建生成物** → **实例测试（冒烟）** → verify → pack。
    任何「把生成物复制回开发侧」的操作都会让陈旧副本随镜像同步反向污染，务必避免。
    例外：core/_sample-baseline.json 是**人工登记**台账（--add/--confirm 逐例录入），
    不可由代码重建，属开发资产，正常纳入 git 并随包分发。
"""
import os
import shutil
import subprocess
import sys

DEV = "/workspace/dev/doc-compliance-review"
RUN = os.path.expanduser("~/.codebuddy/skills/doc-compliance-review")
MAINT = "/workspace/dev/maint"
DIST = "/workspace/dist"
# 发布时排除的文件：只应存在于开发侧的，或不该由开发侧带入的
# （生成物即使在开发侧残留，也不允许随镜像同步覆盖运行实例的 fresh 版本）
EXCLUDE = {".git", "__pycache__", ".DS_Store",
           ".integrity.json", "_rules-baseline.json", "_smoke-baseline.json"}


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


def refresh_generated():
    """用当前代码当场重建运行侧生成物（rmtree 已把它连同旧实例一起删掉）。
    放在 verify 之前，保证 check.py 的「规则基线比对」与「指纹校验」比的是 fresh 台账。"""
    steps = [("规则基线条账", ["rule-baseline.py", "--update"]),
             ("脚本指纹台账", ["check.py", "--sign"])]
    ok = True
    for label, args in steps:
        r = subprocess.run([sys.executable, os.path.join(RUN, "scripts", args[0])] + args[1:],
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or ["(无输出)"]
        print("[publish] 重建 %-12s → %s" % (label, tail[0]))
        if r.returncode != 0:
            ok = False
    return 0 if ok else 1


def instance_test(full):
    """实例测试：**在运行实例侧端到端实跑一遍**（调运行实例的 smoke-test.py）。

    这是发布链里唯一"真的跑一遍"的关卡——verify 跑的 check.py 只验结构与口径，
    验不出"装到实例后能不能真跑"（脚本缺失、依赖探测失败、链路断掉都照样全绿）。
    失败即视为发布失败，由调用方阻断后续步骤。

    档位：默认轻量档（跳过 PDF/OCR 等耗时项，记跳过、总项数不变）；
          传 --pack 出包时由调用方升为全量档（装机验收与发版前要求更严）。
    """
    args = ["--full"] if full else []
    cmd = [sys.executable, os.path.join(RUN, "scripts", "smoke-test.py")] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip().splitlines()
    # 冒烟脚本的结论行形如"结果：通过 N 项，失败 M 项，跳过 K 项"
    summary = next((l.strip() for l in out if l.strip().startswith("结果：")), None)
    label = "实例测试（全量档）" if full else "实例测试（轻量档）"
    print("[publish] %-14s → %s" % (label, summary or (out[-1].strip() if out else "(无输出)")))
    if r.returncode != 0:
        print("[publish] ── 实例测试输出（末 15 行，供排查）──")
        for line in (out[-15:] or ["(无输出；退出码 %d)" % r.returncode]):
            print("           " + line)
    return r.returncode


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
    # pack.py 契约：位置参数是技能根目录，输出目录用 --out 指定
    r = subprocess.run([sys.executable, os.path.join(RUN, "scripts", "pack.py"),
                        RUN, "--out", DIST], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    return r.returncode


def main():
    a = sys.argv[1:]
    if "--check" in a:
        return verify()
    if sync() != 0:
        return 2
    if refresh_generated() != 0:
        return 2
    do_pack = "--pack" in a
    if "--no-instance-test" in a:
        print("[publish] ⚠ ⚠ 已按 --no-instance-test 跳过**实例测试**——这是应急口子，"
              "发布链的\"真的跑一遍\"关卡本次未执行。")
        print("[publish] ⚠ ⚠ 请务必：（1）在 DEVLOG 写明为何跳过；（2）事后补跑 "
              "smoke-test.py（出包用 --full）确认通过。")
    elif instance_test(full=do_pack) != 0:
        print("[publish] ✗ 实例测试未通过，**发布已中止**（不继续校验、不出包）。"
              "先修问题再重跑，勿用应急开关绕过。")
        return 2
    # **跨侧漂移不设发布链关卡**（2026-10-13 实测后决定）：
    # sync() 是"rmtree ＋ 完整镜像重建"，任何两侧差异在同步时即被抹平，
    # 故此处设关卡**几乎不可能触发**（手工改动被覆盖、漏拷也造不出——
    # copytree 要么全成要么抛异常，而异常早让 sync 返回非 0）。
    # 依铁律 2.5"不为不可能发生的事设关卡"，故不在此挂钩。
    # **跨侧巡检请用独立命令**（不经 sync 才有意义）：
    #     python3 maint/tools/check-dev-rules.py     # 第 (8) 项即跨侧一致性
    rc = verify()
    if do_pack and rc == 0:
        rc = pack() or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
