#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: E0  接触文档内容 → 绝对离线，不得引入任何网络库
"""
工作根目录查看与设置（scripts/set-workdir.py）
==============================================
用途：把"审查报告放哪儿"变成一条命令，不必改脚本、也不写死盘符。

用法：
    python set-workdir.py                 查看当前工作根目录与全部候选（含可用性）
    python set-workdir.py --path          只打印解析到的路径（供脚本/批处理取值）
    python set-workdir.py --set E:/我的审查报告      设为自定义路径（不存在则创建）
    python set-workdir.py --auto          恢复自动探测（base_dir=auto）
    python set-workdir.py --create        立即创建工作根目录及「输入」「输出」子目录

自动探测链（base_dir=auto 或留空时，前一个不可用自动顺延）：
    1. 环境变量 DOC_REVIEW_BASE      临时覆盖，优先级最高
    2. config.json 的绝对路径        自定义路径
    3. 推荐盘 D:\\文档合规审查报告      有 D 盘即用，无 D 盘自动跳过
    4. 文档库                        ~/Documents/文档合规审查报告
    5. 用户目录                      ~/文档合规审查报告
    6. 临时目录                      系统临时目录下的同名目录（保底）
"""
import sys as _sys
_sys.dont_write_bytecode = True
import os
import json
import argparse

try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, HERE)
import _config as _cfgmod

CFG_PATH = _cfgmod.CONFIG_PATH


def _write_base(value):
    """把 base_dir 写回 config.json（保留原有键与说明字段）。"""
    data = {}
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH, encoding="utf-8-sig") as f:
                data = json.load(f) or {}
        except Exception as e:
            print("[set-workdir] config.json 解析失败，将重建：%s" % e)
            data = {}
    wd = data.get("workdir") or {}
    wd["base_dir"] = value
    data["workdir"] = wd
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("[set-workdir] 已写入 %s -> base_dir=%s" % (CFG_PATH, value or "auto"))


def main():
    ap = argparse.ArgumentParser(description="工作根目录查看与设置")
    ap.add_argument("--set", metavar="路径", help="设为自定义工作根目录（不存在则创建）")
    ap.add_argument("--auto", action="store_true", help="恢复自动探测（base_dir=auto）")
    ap.add_argument("--create", action="store_true", help="创建工作根目录及输入/输出子目录")
    ap.add_argument("--path", action="store_true", help="只打印解析到的工作根目录路径")
    a = ap.parse_args()

    if a.set:
        p = os.path.abspath(os.path.expanduser(a.set.strip()))
        try:
            os.makedirs(p, exist_ok=True)
        except Exception as e:
            print("[set-workdir] 目录不可创建：%s（%s）" % (p, e))
            return 2
        _write_base(p)
        return 0
    if a.auto:
        _write_base("auto")
        return 0

    cfg = _cfgmod.load()
    base, src = _cfgmod.resolve_base(cfg, create=a.create)
    if a.path:
        print(base)
        return 0

    print("[set-workdir] 配置文件：%s" % (CFG_PATH if os.path.exists(CFG_PATH) else CFG_PATH + "（不存在，用内置默认值）"))
    print("[set-workdir] 当前工作根目录：%s   [来源：%s]" % (base, src))
    print("[set-workdir] 候选链（按优先级）：")
    for label, p, ok in _cfgmod.base_candidates(cfg):
        print("    %-14s %-46s %s" % (label, p, "可用" if ok else "不可用"))
    if a.create:
        for sub in ("输入", "输出"):
            d = os.path.join(base, sub)
            try:
                os.makedirs(d, exist_ok=True)
                print("[set-workdir] 已创建：%s" % d)
            except Exception as e:
                print("[set-workdir] 创建失败：%s（%s）" % (d, e))
    else:
        print("[set-workdir] 提示：加 --create 可立即建好工作根目录与「输入」「输出」子目录")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
