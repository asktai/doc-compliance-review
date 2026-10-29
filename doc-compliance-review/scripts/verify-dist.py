#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容（解包后实跑门禁与入口脚本），零网络库
"""
文档合规审查助手AI合同 · 产物验收（解包即验）
===============================================================
**验的是交付出去的那一份，不是它的产地。**

用法：
  python verify-dist.py <包路径> [<包路径>…]     验一个或多个 .skill / .zip
  python verify-dist.py --selftest               判据自测（变异注入，须全拦、对照组零误报）
  python verify-dist.py <包> --keep              保留解包目录（排障）
  python verify-dist.py <包> --no-gate           只验形态、跳过解包后跑门禁（排障用，发布禁用）

退出码：0=全部通过；1=存在不通过项。

为什么要有这一道（本项目实证）：
  v3.25.8 起 `pack.py` 按设计剥离 version.json 的 history，而 `check.py` 当时要求 history
  必须存在——同一份 check.py，**开发源 0 错、装好的副本必红**，四个版本都如此。原因不是
  判据写错，而是**从没人在产物上跑过门禁**：发布链验的是源目录与运行实例，两者都是"自己
  的地盘"，产物只是被"假定"与源一致。这个假定一直成立到它不成立为止。

设计边界（**不与 check.py 重复造判据**）：
  本脚本只验**产物独有的差异**——打包这一趟有损变换造成的得失：少了什么、被清空了什么、
  被改写成了什么、头部与负载是否自洽。结构、字段、数字口径、文档一致性等**通用门禁一律
  交 check.py**（解包后在副本里跑它）。两处各写一份判据，必然分叉（铁律 12.2 真源唯一）。
"""
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SKILL_DIR = os.path.basename(os.path.dirname(HERE))     # 从自身位置推，不写死
# 平台上限：真源是 pack.py 的常量（不在此另写一份，否则两处必漂）
try:
    sys.path.insert(0, HERE)
    import pack as _pack                                  # noqa: E402
    MAX_DEPTH = _pack.PLATFORM_MAX_DEPTH
    MAX_MB = _pack.PLATFORM_MAX_MB
    _CONST_SRC = "pack.py"
except Exception:                                          # 包内缺 pack.py 时降级，但仍须报错
    MAX_DEPTH, MAX_MB, _CONST_SRC = 2, 3, "内置默认（未取到 pack.py）"


def _utf8_env(extra=None):
    """spawn 子进程时的编码隔离（铁律 12.5.9：不在对方 locale 下赌运气）。"""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUTF8"] = "1"
    if extra:
        e.update(extra)
    return e


def _run(cmd, cwd, env=None, timeout=600):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=_utf8_env(env), timeout=timeout)


def open_payload(path):
    """返回 (ZipFile, 头部说明)。`.skill` 是自定义头部 ＋ zip 负载，须跳头并校验负载指纹。"""
    raw = open(path, "rb").read()
    if raw[:4] == b"SKLP":
        if len(raw) < 41:
            raise ValueError("头部不足 41 字节，非完整 .skill")
        ver, n = struct.unpack("<BI", raw[4:9])
        meta = json.loads(raw[9:9 + n].decode("utf-8"))
        want = raw[9 + n:9 + n + 32].hex()
        payload = raw[9 + n + 32:]
        got = hashlib.sha256(payload).hexdigest()
        note = ".skill 头 v%d ｜ 元数据 %s %s" % (ver, meta.get("id", "?"), meta.get("version", "?"))
        if want != got:
            raise ValueError("头部负载指纹不符（头记 %s…，实算 %s…）——包已损坏或被改过"
                             % (want[:12], got[:12]))
        return zipfile.ZipFile(io.BytesIO(payload)), note
    return zipfile.ZipFile(io.BytesIO(raw)), "裸 zip（无 .skill 头部）"


def _norm_ver(s):
    return re.sub(r"^[Vv]", "", (s or "").strip())


def verify_artifact(path, gate=True, gbk=True, quiet=False):
    """验一个产物。返回错误列表（空＝通过）。**pack.py 出包末尾直接复用本函数。**"""
    errs = []

    def bad(m):
        errs.append(m)

    try:
        zf, note = open_payload(path)
    except Exception as e:
        return ["包无法打开：%s（%s）" % (e, os.path.basename(path))]
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not quiet:
        print("产物：%s" % os.path.basename(path))
        print("      %s ｜ %d 个文件条目" % (note, len(names)))

    # ── 1. 条目名安全：绝对路径或 .. 会造成解包穿越（解包前必须判）
    unsafe = [n for n in names if n.startswith("/") or ".." in n.split("/") or ":" in n[:3]]
    if unsafe:
        bad("条目名越界（绝对路径／..／盘符）：%s" % unsafe[:3])
        return errs                       # 不再解包

    # ── 2. 形态：顶层唯一技能目录、SKILL.md 恰 1、层级与体积合平台上限
    tops = sorted({n.split("/")[0] for n in names})
    if tops != [SKILL_DIR]:
        bad("顶层条目 %s——须只有技能目录 %s（多一层少一层平台都解析不到）" % (tops, SKILL_DIR))
    if sum(1 for n in names if n == SKILL_DIR + "/SKILL.md") != 1:
        bad("SKILL.md 计数 %d（须恰 1，且在技能目录下）"
            % sum(1 for n in names if n == SKILL_DIR + "/SKILL.md"))
    deep = [n for n in names if n.count("/") > MAX_DEPTH]
    if deep:
        bad("目录层级超过 %d 级（平台拒收），例如 %s" % (MAX_DEPTH, deep[0]))
    mb = os.path.getsize(path) / 1048576.0
    if mb > MAX_MB:
        bad("体积 %.2f MB 超平台上限 %d MB（上限取自 %s）" % (mb, MAX_MB, _CONST_SRC))

    # ── 3. 沿革不随包：VERSION.md 与 history 都不得出现（一个管文档、一个管 JSON，两处都得拦）
    if (SKILL_DIR + "/VERSION.md") in names:
        bad("包内混入 VERSION.md（版本沿革）——沿革不随技能分发")
    vj = SKILL_DIR + "/version.json"
    if vj not in names:
        bad("包内缺 version.json（检查更新要靠它）")
    else:
        try:
            vd = json.loads(zf.read(vj).decode("utf-8"))
        except Exception as e:
            bad("包内 version.json 无法解析：%s" % e)
            vd = {}
        if "history" in vd:
            bad("包内 version.json 仍含 history %d 条——剥离未生效" % len(vd.get("history") or []))
        if vd.get("_分发副本") is not True:
            bad("包内 version.json 缺 `_分发副本: true` 标记——装好的副本将无法自证"
                "「本副本不提供历史版本信息」，门禁会把「无 history」误判为缺陷")
        # ── 4. 版本三处自洽：包名 ／ SKILL.md frontmatter ／ version.json latest
        m = re.search(r"_(v\d+\.\d+\.\d+)_\d{8}_\(", os.path.basename(path))
        by_name = _norm_ver(m.group(1)) if m else ""
        by_manifest = _norm_ver(((vd.get("latest") or {}).get("version")) or "")
        by_skill = ""
        if SKILL_DIR + "/SKILL.md" in names:
            head = zf.read(SKILL_DIR + "/SKILL.md").decode("utf-8-sig", "replace")
            ms = re.search(r"(?m)^version:\s*([0-9][0-9A-Za-z.\-]*)", head)
            by_skill = _norm_ver(ms.group(1)) if ms else ""
        if not by_name:
            bad("包文件名不含四段式版本段（须 …_vX.Y.Z_YYYYMMDD_(技能ID)）")
        trio = {"包名": by_name, "SKILL.md": by_skill, "version.json": by_manifest}
        if len({v for v in trio.values() if v}) > 1:
            bad("版本三处不一致：%s" % "／".join("%s=%s" % (k, v or "?") for k, v in trio.items()))

    # ── 5. 打包这一趟的"清空/排除"是否真的生效
    cfg = SKILL_DIR + "/scripts/config.json"
    if cfg in names:
        try:
            cd = json.loads(zf.read(cfg).decode("utf-8"))
        except Exception as e:
            bad("包内 config.json 无法解析：%s" % e)
            cd = {}
        filled = sorted(k for k, v in (cd.get("tools") or {}).items() if str(v or "").strip())
        if filled:
            bad("包内 config.json 仍带本机工具路径（%s）——作者机器路径会随包外发"
                % "、".join(filled))
    if any(n.startswith(SKILL_DIR + "/private/") for n in names):
        bad("包内混入 private/（企业内控口径，不得外发）")
    junk = [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".pyo"))]
    if junk:
        bad("包内混入字节码缓存 %d 个，例如 %s" % (len(junk), junk[0]))

    if not gate:
        return errs

    # ── 6. 解包后跑真门禁：这是"产物能不能用"的唯一硬证据
    tmp = tempfile.mkdtemp(prefix="dcr-verify-")
    try:
        zf.extractall(tmp)
        root = os.path.join(tmp, SKILL_DIR)
        ck = os.path.join(root, "scripts", "check.py")
        if not os.path.exists(ck):
            bad("产物内缺 scripts/check.py——使用者装完无法自检")
        else:
            rounds = [("UTF-8", None)]
            if gbk:
                # 中文 Windows 控制台默认 GBK：只在本机（UTF-8）跑等于没验环境维度
                rounds.append(("GBK", {"PYTHONIOENCODING": "gbk"}))
            for label, env in rounds:
                r = _run([PY, ck], tmp, env)
                out = (r.stdout or "") + (r.stderr or "")
                tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or [""]
                if not quiet:
                    print("      check.py［%s］退出码 %d ｜ %s" % (label, r.returncode, tail[0][:100]))
                if r.returncode != 0:
                    bad("［%s］解包后跑 check.py 未通过（退出码 %d）：%s"
                        % (label, r.returncode, tail[0][:300]))
                # **警告也要拦**：check.py 的「警告 N 项」多为指纹不一致、口径漂移这类
                # 「结构没坏但产物不干净」的问题，退出码仍是 0。只看退出码＝判据漏一半
                # （12.5.4 假绿的典型形态：信号在，但没读）。
                mw = re.search(r"警告\s*(\d+)\s*项", out)
                if mw and int(mw.group(1)) > 0:
                    warns = [ln.strip() for ln in out.splitlines() if ln.startswith("[W]")]
                    bad("［%s］解包后跑 check.py 有 %s 项警告（退出码 0 不代表干净）：%s"
                        % (label, mw.group(1), "；".join(warns[:3])[:300] or "（见完整输出）"))
                if "\ufffd" in out:
                    bad("［%s］check.py 输出含替换符 U+FFFD——编码链断裂（先修编码，别急着查判据）"
                        % label)
        # 入口脚本可用性：解包后至少 version.py 要能跑（装完第一件事就是查版本）
        vp = os.path.join(root, "scripts", "version.py")
        if os.path.exists(vp):
            r = _run([PY, vp], tmp, timeout=120)
            if r.returncode != 0:
                bad("产物内 version.py 退出码 %d（装好的副本查不了版本）" % r.returncode)
    finally:
        if os.environ.get("DCR_VERIFY_KEEP"):
            print("      [i] 解包目录已保留：%s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return errs


# ------------------------------------------------------------------ 判据自测（变异注入）
def selftest():
    """证明判据"有区分度"：造 7 个变异包，每个都须被**对应**的判据抓住；再验干净基线 0 错。

    只有"注入了就报错"不算证明（会与别的原因混淆），故逐项比对**报错关键词**；
    基线包同时充当**对照组**，若它报错即说明判据误拦（12.5.4.1）。
    """
    base_skill = ("---\nname: doc-compliance-review\ndisplay_name: 文档合规审查助手AI合同\n"
                  "display_name_en: Doc Compliance Review\ndescription: selftest\n"
                  "version: 9.9.9\n---\n# sk\n")
    base_vj = json.dumps({"latest": {"version": "v9.9.9"}, "_分发副本": True}, ensure_ascii=False)
    base_cfg = json.dumps({"tools": {"tesseract": "", "libreoffice": ""}}, ensure_ascii=False)

    def make(root, *, history=False, marker=True, vmd=False, tools=None, ver="9.9.9",
             private=False, evil=False):
        os.makedirs(os.path.join(root, SKILL_DIR, "scripts"), exist_ok=True)
        sk = base_skill.replace("9.9.9", ver)
        open(os.path.join(root, SKILL_DIR, "SKILL.md"), "w", encoding="utf-8").write(sk)
        vd = {"latest": {"version": "v" + ver}}
        if marker:
            vd["_分发副本"] = True
        if history:
            vd["history"] = [{"version": "v0.0.1"}]
        open(os.path.join(root, SKILL_DIR, "version.json"), "w", encoding="utf-8").write(
            json.dumps(vd, ensure_ascii=False))
        open(os.path.join(root, SKILL_DIR, "scripts", "config.json"), "w",
             encoding="utf-8").write(json.dumps({"tools": tools or {}}, ensure_ascii=False))
        if vmd:
            open(os.path.join(root, SKILL_DIR, "VERSION.md"), "w", encoding="utf-8").write("# 沿革\n")
        if private:
            os.makedirs(os.path.join(root, SKILL_DIR, "private"), exist_ok=True)
            open(os.path.join(root, SKILL_DIR, "private", "x.txt"), "w").write("x")
        return root

    def pack_to(root, out, evil=False):
        with zipfile.ZipFile(out, "w") as zo:
            for dp, _dn, fns in os.walk(root):
                for fn in fns:
                    fp = os.path.join(dp, fn)
                    if os.path.abspath(fp) == os.path.abspath(out):
                        continue          # 自测包放在同一临时目录里，别把自己收进去
                    zo.write(fp, os.path.relpath(fp, root).replace(os.sep, "/"))
            if evil:
                zo.writestr(SKILL_DIR + "/../../evil.txt", "x")
        return out

    cases = [
        ("对照组（干净基线）", {}, None),
        ("混入 VERSION.md", {"vmd": True}, "VERSION.md"),
        ("回归 history", {"history": True}, "history"),
        ("丢 _分发副本 标记", {"marker": False}, "_分发副本"),
        ("带本机工具路径", {"tools": {"tesseract": "/opt/tools/tesseract"}}, "本机工具路径"),
        ("版本三处不一致", {"ver": "9.9.8"}, "版本三处不一致"),
        ("混入 private/", {"private": True}, "private/"),
    ]
    ok = True
    for name, kw, want in cases:
        tmp = tempfile.mkdtemp(prefix="dcr-st-")
        try:
            root = make(tmp, **kw)
            zp = pack_to(root, os.path.join(tmp, "x_v9.9.9_20260101_(doc-compliance-review).zip"),
                         evil=(name.startswith("条目名")))
            got = verify_artifact(zp, gate=False, quiet=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if want is None:
            hit = not got
            print("  [%s] %s%s" % ("PASS" if hit else "FAIL", name, "" if hit else "  误报：%s" % got))
        else:
            hit = any(want in g for g in got)
            print("  [%s] %s%s" % ("PASS" if hit else "FAIL", name,
                                   "" if hit else "  未命中「%s」，实得：%s" % (want, got)))
        ok = ok and hit

    # 解包穿越单独测：条目名带 .. 须在解包前拦下（不落盘）
    tmp = tempfile.mkdtemp(prefix="dcr-st-")
    try:
        root = make(tmp)
        zp = pack_to(root, os.path.join(tmp, "y_v9.9.9_20260101_(doc-compliance-review).zip"),
                     evil=True)
        got = verify_artifact(zp, gate=False, quiet=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    hit = any("条目名越界" in g for g in got)
    print("  [%s] 条目名穿越（../）%s" % ("PASS" if hit else "FAIL", "" if hit else "  未拦：%s" % got))
    ok = ok and hit
    print("\n判据自测：%s" % ("全部通过（隔项命中、对照组零误报）" if ok else "存在未命中项"))
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--selftest" in args:
        sys.exit(selftest())
    if "--keep" in args:
        os.environ["DCR_VERIFY_KEEP"] = "1"
    gate = "--no-gate" not in args
    gbk = "--no-gbk" not in args
    quiet = "--quiet" in args
    pkgs = [a for a in args if not a.startswith("--")]
    if not pkgs:
        print("用法：python verify-dist.py <包路径>… [--selftest] [--no-gate] [--no-gbk] [--keep]")
        sys.exit(2)
    fails = 0
    for p in pkgs:
        e = verify_artifact(p, gate=gate, gbk=gbk, quiet=quiet)
        if e:
            fails += 1
            print("\n[x] %s：%d 处不通过" % (os.path.basename(p), len(e)))
            for x in e:
                print("    [E] " + x)
        else:
            print("\n[OK] %s：产物验收通过" % os.path.basename(p))
        print("")
    sys.exit(1 if fails else 0)
