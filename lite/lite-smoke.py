#!/usr/bin/env python3
"""lite-smoke.py —— lite-selfcheck.py 的全量冒烟（元自测，铁律第 12 条）。

对「技能开发规范（铁律）」发布版（或任何 Lite 系文档）注入 15 个打瘸点，
逐个验证 lite-selfcheck.py 能拦住；再对检查器自身做 2 个 (L0) 打瘸
（哑维度／维度失踪），验证检查器能发现自己坏了。

用法：python3 lite-smoke.py <目标.md> [检查器路径]
  默认检查器为本脚本同目录的 lite-selfcheck.py。
退出码：0＝全部拦住；1＝有漏网（守卫失效，按 12.1 处置）。
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHECKER = os.path.join(HERE, "lite-selfcheck.py")


def run_checker(checker, path):
    p = subprocess.run([sys.executable, checker, path],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def mutate_delete_section(src, head_re):
    """删掉从匹配 head_re 的 '## ' 行到下一个 '## ' 之前的整段。"""
    lines = src.split("\n")
    start = next(i for i, l in enumerate(lines) if re.match(head_re, l))
    end = next(i for i in range(start + 1, len(lines))
               if lines[i].startswith("## "))
    return "\n".join(lines[:start] + lines[end:])


def mutate_first_table_row_drop_col(src):
    """第一张表的表体首行删掉一列。"""
    lines = src.split("\n")
    sep = next(i for i, l in enumerate(lines)
               if re.match(r"^\s*\|[\s:|-]+\|\s*$", l))
    row = lines[sep + 1]
    cells = row.split("|")
    lines[sep + 1] = "|".join(cells[:-2]) + "|"  # 少一列
    return "\n".join(lines)


def mutate_sep_col_mismatch(src):
    """第一张表的分隔行改成列数不符。"""
    lines = src.split("\n")
    sep = next(i for i, l in enumerate(lines)
               if re.match(r"^\s*\|[\s:|-]+\|\s*$", l))
    lines[sep] = "|---|"
    return "\n".join(lines)


def mutate_empty_table(src):
    """第一张表删成只剩表头＋分隔行（空表）。"""
    lines = src.split("\n")
    sep = next(i for i, l in enumerate(lines)
               if re.match(r"^\s*\|[\s:|-]+\|\s*$", l))
    i = sep + 1
    while i < len(lines) and lines[i].strip().startswith("|"):
        del lines[i]
    return "\n".join(lines)


def mutate_toc_remove(src):
    lines = src.split("\n")
    i = next(i for i, l in enumerate(lines)
             if l.startswith("- [第 5 条"))
    del lines[i]
    return "\n".join(lines)


def mutate_toc_add(src):
    lines = src.split("\n")
    i = next(i for i, l in enumerate(lines)
             if l.startswith("- [第 16 条"))
    lines.insert(i + 1, "- [第 17 条 编造](#第-17-条-编造)")
    return "\n".join(lines)


# 15 个打瘸点：(名字, 期望拦它的维度, 变异函数/追加行)
def build_cases(src):
    return [
        ("删一整条（第 9 条）→ 条号跳号", "(L1)",
         mutate_delete_section(src, r"## 第 9 条")),
        ("款号 5.2 改成 5.9 → 款号跳号", "(L1)",
         src.replace("**5.2", "**5.9", 1)),
        ("引用不存在的第 17 条 → 悬空", "(L2)",
         src + "\n\n依据第 17 条执行。\n"),
        ("表体少一列 → 表格不完整", "(L3)",
         mutate_first_table_row_drop_col(src)),
        ("分隔行与表头列数不符 → 表格不完整", "(L3)",
         mutate_sep_col_mismatch(src)),
        ("表体整段删空 → 空表", "(L3)",
         mutate_empty_table(src)),
        ("塞回项目专有名词 check.py → 残留", "(L4)",
         src + "\n\n迁移时参照 check.py 的做法。\n"),
        ("专有名词大写变体 CHECK.PY → 残留", "(L4)",
         src + "\n\nCHECK.PY 也要一并带上。\n"),
        ("unix 绝对路径 /data9xq/x → 路径残留", "(L5)",
         src + "\n\n产物放在 /data9xq/x 下面。\n"),
        ("家目录写法 ~/zq9x → 路径残留", "(L5)",
         src + "\n\n备份在 ~/zq9x 目录。\n"),
        ("Windows 盘符正斜杠 C:/zq9x/f → 路径残留", "(L5)",
         src + "\n\n临时文件在 C:/zq9x/f。\n"),
        ("Windows 盘符反斜杠 D:\\zq9x\\f → 路径残留", "(L5)",
         src + "\n\n临时文件在 D:\\zq9x\\f。\n"),
        ("目录删一条 → 目录不一致", "(L6)",
         mutate_toc_remove(src)),
        ("目录编一条（第 17 条）→ 目录不一致", "(L6)",
         mutate_toc_add(src)),
        ("引用不存在的表格行 `8.2 第 99 行` → 虚指", "(L7)",
         src + "\n\n见 `8.2 第 99 行` 的口径。\n"),
    ]


def mute_dim_err(checker_src, dim):
    """把某维代码体里的 err( 全部改成 er_r( —— 维度照跑但哑了。"""
    marks = [(int(m.group(1)), m.start()) for m in
             re.finditer(r"(?m)^\s*RAN\.append\((\d+)\)\s*$", checker_src)]
    marks.sort(key=lambda x: x[1])
    spans = {}
    for idx, (n, pos) in enumerate(marks):
        end = marks[idx + 1][1] if idx + 1 < len(marks) else len(checker_src)
        spans[n] = (pos, end)
    a, b = spans[dim]
    return checker_src[:a] + checker_src[a:b].replace("err(", "er_r(") \
        + checker_src[b:]


def drop_ran(checker_src, dim):
    """删掉某维的 RAN.append —— 维度声明了却一声没吭。"""
    return re.sub(r"(?m)^(\s*)RAN\.append\(%d\)\s*$" % dim,
                  r"\1pass  # RAN.append(%d) 被删" % dim, checker_src, count=1)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "DEV-RULES-LITE.md")
    checker = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHECKER
    src = open(target, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="lite-smoke-")
    fails = []

    # 0. 基准：原样必须全过（exit 0），否则打瘸结论无意义
    code, out = run_checker(checker, target)
    if code != 0:
        print("基准失败：未打瘸的文档就没过自检，先修文档再说：\n" + out)
        return 1
    print("基准：原样七项全过 ✓")

    # 1. 文档侧 15 个打瘸点
    ok = 0
    for name, dim, mutated in build_cases(src):
        p = os.path.join(tmp, "case.md")
        open(p, "w", encoding="utf-8").write(mutated)
        code, out = run_checker(checker, p)
        if code != 0 and dim in out:
            ok += 1
            print("  [拦下] %s" % name)
        else:
            fails.append(name)
            print("  [漏网] %s —— exit=%d，输出未含 %s" % (name, code, dim))
    print("文档侧打瘸点：%d/15 拦下" % ok)

    # 2. 检查器自身打瘸（L0）
    csrc = open(checker, encoding="utf-8").read()
    for name, mut in [
        ("哑维度：删掉第 3 维的全部 err( → (L0) 判据失效", mute_dim_err(csrc, 3)),
        ("维度失踪：删掉第 5 维的 RAN.append → (L0) 一声没吭", drop_ran(csrc, 5)),
    ]:
        cp = os.path.join(tmp, "crippled.py")
        open(cp, "w", encoding="utf-8").write(mut)
        code, out = run_checker(cp, target)
        if code != 0 and "(L0)" in out:
            print("  [拦下] %s" % name)
        else:
            fails.append(name)
            print("  [漏网] %s —— exit=%d，输出未含 (L0)" % (name, code))

    if fails:
        print("\n冒烟未过：%d 处漏网 —— 按 12.1 属守卫失效，先修守卫：" % len(fails))
        for f in fails:
            print("  - " + f)
        return 1
    print("\n冒烟全量通过：15/15 打瘸点拦下 ＋ 检查器自身 2 项 (L0) 打瘸拦下")
    return 0


if __name__ == "__main__":
    sys.exit(main())
