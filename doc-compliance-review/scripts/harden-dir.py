#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档合规审查助手AI合同 · 输出目录访问控制（harden-dir）
=================================================================
用途（对应安全项「输出目录集中存放所有客户文档、无访问控制」）：
    把工作输出目录（默认 `<base>/输出`）的权限收敛为**仅本机当前用户 + 系统/管理员**可访问，
    并**关闭权限继承**，避免同机其他账户或其他用户配置读取到全部客户的合同与审查报告。

策略：
    Windows —— icacls 关闭继承(/inheritance:r)，显式仅授权：
               当前用户、SYSTEM(S-1-5-18)、Administrators(S-1-5-32-544) 完全控制
    macOS/Linux —— chmod 700（--undo 恢复 755）

用法：
    python harden-dir.py --dir D:\\文档合规审查报告\\输出        # 收紧权限（仅当前用户/系统可访问）
    python harden-dir.py --dir ... --recursive                 # 连同子目录一并收紧
    python harden-dir.py --dir ... --show                      # 仅显示当前权限，不做修改
    python harden-dir.py --dir ... --undo                      # 恢复继承/默认权限
    （省略 --dir 时使用 config.json 的 workdir.out_dir，或 <base_dir>/输出）

注意：
    - 本脚本**只改权限、不删除任何文件**；请显式运行，技能不会自动调用。
    - 收紧后普通管理员以外的账户将无法访问；如需共享给同事，请勿使用本脚本，改用受控共享目录。
"""
import sys as _sys

# 输出编码保护：非 UTF-8 终端（Windows GBK 控制台、重定向到文件时）print 中文会抛
# UnicodeEncodeError 直接崩；统一按 UTF-8 输出，无法编码的字符替换而非崩溃。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）
import os
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, HERE)
try:
    import _config as _cfgmod
    _CFG = _cfgmod.load()
except Exception:
    _cfgmod = None
    _CFG = {}

BASE_DIR = (_cfgmod.workdir(_CFG, "base_dir") if _cfgmod
            else os.path.join(os.path.expanduser("~"), "文档合规审查报告"))
DEFAULT_DIR = ((_cfgmod.workdir(_CFG, "out_dir") if _cfgmod else "") or os.path.join(BASE_DIR, "输出"))

SID_SYSTEM = "*S-1-5-18"
SID_ADMINS = "*S-1-5-32-544"
GRANT_FULL = ":(OI)(CI)F"


def _run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if p.stdout:
        print(p.stdout.rstrip())
    if p.stderr:
        print(p.stderr.rstrip())
    return p.returncode


def show(path):
    print("[harden] 当前权限：%s" % path)
    if os.name == "nt":
        return _run(["icacls", path])
    return _run(["ls", "-ld", path])


def harden(path, recursive=False):
    if os.name == "nt":
        user = os.environ.get("USERNAME") or ""
        grants = [SID_ADMINS + GRANT_FULL, SID_SYSTEM + GRANT_FULL]
        if user:
            grants.append(user + GRANT_FULL)
        cmd = ["icacls", path, "/inheritance:r", "/grant:r"] + grants
        if recursive:
            cmd.append("/T")
        rc = _run(cmd)
        if rc == 0:
            print("[harden] 已收紧：仅 %s、SYSTEM、Administrators 可访问（继承已关闭）%s"
                  % (user or "当前用户", "（含子目录）" if recursive else ""))
        return rc
    rc = _run(["chmod", "700", path])
    if rc == 0:
        print("[harden] 已收紧：chmod 700（仅属主可访问）")
    return rc


def undo(path, recursive=False):
    if os.name == "nt":
        user = os.environ.get("USERNAME") or ""
        cmd = ["icacls", path, "/inheritance:e"]
        if user:
            cmd += ["/remove:g", user]
        if recursive:
            cmd.append("/T")
        rc = _run(cmd)
        if rc == 0:
            print("[harden] 已恢复继承（显式授权已移除）")
        return rc
    rc = _run(["chmod", "755", path])
    if rc == 0:
        print("[harden] 已恢复 chmod 755")
    return rc


def main():
    ap = argparse.ArgumentParser(description="输出目录访问控制（只改权限，不删文件）")
    ap.add_argument("--dir", default=None, help="目标目录（默认取 config.json 的输出目录）")
    ap.add_argument("--recursive", action="store_true", help="连同子目录一并处理（icacls /T）")
    ap.add_argument("--show", action="store_true", help="仅显示当前权限")
    ap.add_argument("--undo", action="store_true", help="恢复默认/继承权限")
    a = ap.parse_args()

    path = a.dir or DEFAULT_DIR
    if not os.path.isdir(path):
        print("[harden] 目录不存在：%s" % path)
        return 2
    if a.show:
        return 0 if show(path) == 0 else 1
    if a.undo:
        rc = undo(path, a.recursive)
        show(path)
        return 0 if rc == 0 else 1
    print("[harden] 即将收紧权限（不删除任何文件）：%s" % path)
    rc = harden(path, a.recursive)
    show(path)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    _sys.exit(main())
