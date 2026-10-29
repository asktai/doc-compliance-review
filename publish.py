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
    sync → **转分发形态** → **重建生成物** → **实例测试** → verify → （--pack 时）pack

  (1) sync            rmtree 清干净后镜像重建运行实例
  (1b) 转分发形态      剥 version.json 的 history、删 VERSION.md、写 `_分发副本` 标记——
                     **实例该长成使用者看到的样子**，不是开发源的样子（整目录同步会把
                     维护侧的沿革一起搬过去）。此前靠人手动跑，忘一次就多给一份沿革。
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


def to_dist_mode():
    """把运行实例转成**分发形态**（剥 version.json 的 history、删 VERSION.md、写 `_分发副本` 标记）。

    为什么写进链子而不是靠人手动跑：这个形态此前是手工命令，**忘了的后果是实例里带着
    完整沿革**——使用者能看到比该给的更多的东西。凡"靠人记得"的步骤，最终都会有一次不记得
    （铁律 13.2 第 2 条：挂在绕不过的位置）。脚本幂等，可反复跑。
    """
    p = os.path.join(RUN, "scripts", "dist-mode.py")
    if not os.path.exists(p):
        print("[publish] ✗ 缺 scripts/dist-mode.py，实例无法转分发形态")
        return 1
    r = subprocess.run([sys.executable, p, RUN], capture_output=True, text=True)
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or ["(无输出)"]
    print("[publish] %-14s → %s" % ("实例转分发形态", tail[0]))
    return r.returncode


def refresh_generated():
    """用当前代码当场重建生成物，**实例侧与开发侧各刷一次**。

    放在 verify 之前，保证 check.py 的「规则基线比对」与「指纹校验」比的是 fresh 台账。

    为什么必须刷两处（v3.26.3 补）：生成物 `scripts/.integrity.json` **随包分发**，而
    **出包源是开发侧**（`pack()` 传的是 `DEV`）、生成物重建却只做在运行实例侧——两棵
    不同的树。开发侧台账陈旧时它会原样打进包，包内 check.py 于是自带一条"脚本已被修改"
    的警告，而**退出码仍是 0**：v3.26.2 的包就这么出去了（29 个脚本里 smoke-test.py 一行
    是旧哈希）。现在 pack.py 会在出包口硬拒陈旧台账（`verify_integrity_fresh`），此处
    则保证正常流程压根不会走到那一步——**两个位置各司其职：一个让问题暴露，一个让它不
    发生**，缺一则要么假绿、要么天天卡壳。
    """
    steps = [("规则基线条账", ["rule-baseline.py", "--update"]),
             ("脚本指纹台账", ["check.py", "--sign"])]
    ok = True
    for where, base in (("实例", RUN), ("出包源", DEV)):
        for label, args in steps:
            # 出包源只重签指纹台账：源侧的规则基线是长期维护的开发资产，不由发布链改写
            if base == DEV and label != "脚本指纹台账":
                continue
            r = subprocess.run([sys.executable, os.path.join(base, "scripts", args[0])] + args[1:],
                               capture_output=True, text=True)
            tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or ["(无输出)"]
            print("[publish] 重建 %s%s → %s" % (where, label, tail[0]))
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


def separation():
    """分离守卫（铁律第 9 条）：开发侧／技能侧不得互相串（维护侧关卡）。

    放在 sync 之后、verify 之前：先确保镜像干净，再核"技能目录里有没有
    本不该在那的东西"（白名单目录混入／未登记素材／开发资料越界）。
    出包环节 pack.py 也会硬拒未登记素材；此处提前一关，是为了**同步之后立刻**
    发现问题——而非等到打包才暴露。
    """
    r = subprocess.run([sys.executable, os.path.join(MAINT, "tools", "check-separation.py")],
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip().splitlines()
    summary = next((l.strip() for l in out if l.strip().startswith("结果：")), None)
    print("[publish] %-14s → %s" % ("分离守卫", summary or (out[-1].strip() if out else "(无输出)")))
    if r.returncode != 0:
        for line in out:
            if line.strip().startswith("·"):
                print("           " + line.strip())
    return r.returncode


def pack():
    os.makedirs(DIST, exist_ok=True)
    # **从开发源出包，不从运行实例**：实例已按 (1b) 转成分发形态（无 history、无 VERSION.md），
    # 而 pack.py 会**正当地**拒收"源里没有沿革"的目录——拿它当出包源只会得到一份自己都不认的包。
    # 内容不会因此走样：sync 是 rmtree ＋ 镜像重建，两边除"分发形态那三处差异"外逐字节相同，
    # 而那三处本来就由 pack.py 在出包时剥掉。
    r = subprocess.run([sys.executable, os.path.join(RUN, "scripts", "pack.py"),
                        DEV, "--out", DIST], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    return r.returncode


def main():
    a = sys.argv[1:]
    if "--check" in a:
        return verify()
    if sync() != 0:
        return 2
    # 实例必须长成「分发副本」的样子（剥沿革、删 VERSION.md、写标记）：
    # 整目录同步会把源的沿革一并搬进实例，等于把维护侧的东西摆给使用者看。
    if to_dist_mode() != 0:
        return 2
    if refresh_generated() != 0:
        return 2
    # 分离守卫：技能目录里不得混入开发资料／未登记素材（铁律第 9 条）
    # 放在 verify 之前——同步后立刻查，早于打包暴露（pack.py 另有一道硬拒）
    if separation() != 0:
        print("[publish] ✗ 分离守卫未通过，**发布已中止**（技能目录混入了不该随包的内容）。")
        print("[publish]   处置：把开发资料移到 maint/ai-notes｜test-data｜scratch；")
        print("[publish]        新样本须登记 maint/samples-manifest.json 后方可随包。")
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
    # 依铁律 12.5"不为不可能发生的事设关卡"，故不在此挂钩。
    # **跨侧巡检请用独立命令**（不经 sync 才有意义）：
    #     python3 maint/tools/check-dev-rules.py     # 第 (8) 项即跨侧一致性
    rc = verify()
    if do_pack and rc == 0:
        rc = pack() or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
