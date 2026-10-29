#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# net-tier: L0  接触文档内容 → 绝对离线，不得引入任何网络库
"""模板引擎加固：占位符必填校验 ＋ 条件条款段渲染 ＋ 模板版本留痕

用途：模板版（第 10 类交付物）在**出件之前**先过这一道——
      模板里写了的占位符必须出现在说明表里，说明表标了必填的必须在出件前填实，
      条件段的开关必须有明确取值。查出来的问题逐条列出，不带病出件。

三件事：
  1. **占位符校验**：`{{名称}}` 与说明表双向对齐（模板里有而表里没有的算「未登记」，
     表里有而模板里没用的算「无用登记」）；必填项未填、或填了还是 `{{…}}` 原样，一律拦下。
  2. **条件条款段**：`{{#开关}}…{{/开关}}` 单布尔条件，取值由调用方给（True/False）。
     未给取值的开关 → 报「开关未定」，**不默认按 True 出件**（默认保留等于偷偷加条款）。
     支持一层嵌套；`{{^开关}}` 为反选（开关为假时保留本段）。
  3. **版本留痕**：元数据有三个来源，优先级 body 内的 `<!-- tpl: … -->` 行 >
     spec.template.meta > 无。解析出的版本号写进出件文档属性与文末，模板改过就换版本号。

设计红线：
  · 只校验、只渲染，**不猜**。缺值就报缺值，不拿「（待填）」之类占位词糊过去。
  · 拦下的是「出件前就能确定的问题」，不做法律判断；条款实体是否合适仍归审查判断。
  · 零联网、零上传。

用法：
  python scripts/tpl-engine.py check  <spec.json>              # 只体检，不出件
  python scripts/tpl-engine.py render <spec.json> [--switch 有第三方=1 ...]
  python scripts/tpl-engine.py manifest <模板目录>              # 派生模板清单
"""
import sys as _sys
_sys.dont_write_bytecode = True   # 不在技能目录留下 __pycache__（避免缓存残留）

# 输出编码自钉：本脚本可能被 check.py 等**作为子进程 spawn**，父侧按 UTF-8 解码 stdout。
# 不钉的话，中文 Windows（GBK 控制台）下会按 GBK 写出 → 父侧 UTF-8 解出 U+FFFD 乱码 →
# 判据一条都匹配不上，父侧误报「判据被删／脚本崩了」（v3.26.2 在千问办公实测到的假红）。
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import argparse
import io
import json
import os
import re
import sys
import hashlib

# 占位符：{{名称}}；允许中文、字母、数字、下划线与短横，内部不许再有花括号
PH_RE = re.compile(r"\{\{\s*([^{}#/^][^{}]*?)\s*\}\}")
# 条件段：{{#开关}} … {{/开关}}；反向段 {{^开关}} … {{/开关}}
OPEN_RE = re.compile(r"\{\{\s*([#^])\s*([^{}/]+?)\s*\}\}")
CLOSE_RE = re.compile(r"\{\{\s*/\s*([^{}/]+?)\s*\}\}")
# 版本留痕行：<!-- tpl: 名称 | ver: 1.0.0 | date: 2026-01-01 | 变更: … -->
META_RE = re.compile(r"<!--\s*tpl\s*:(.*?)-->", re.S)

# 出件时允许留白的「非实质」占位符（签名、日期这类允许手签手填），仍会提示但不拦
SOFT_NAME_HINT = ("签字", "签章", "盖章", "签名", "日期", "年月日", "附件")


class TplError(Exception):
    pass


# ------------------------------------------------------------------ 元数据
def parse_meta_line(text):
    """从 `<!-- tpl: 名称 | ver: 1.0.0 | date: … | 变更: … -->` 里取字段。"""
    out = {}
    for m in META_RE.finditer(text or ""):
        for seg in re.split(r"[|｜]", m.group(1)):
            seg = seg.strip()
            if not seg:
                continue
            parts = re.split(r"[:：]", seg, 1)
            k = parts[0].strip()
            v = parts[1].strip() if len(parts) == 2 else ""
            key = {"名称": "name", "ver": "version", "version": "version",
                   "版本": "version", "date": "date", "日期": "date",
                   "变更": "change", "change": "change", "notes": "change"}.get(
                       k.lower() if k.isascii() else k)
            if key:
                out[key] = v
    if not out.get("version"):
        raise TplError("模板版本留痕缺版本号：请在模板首行写 "
                       "<!-- tpl: 名称 | ver: 1.0.0 | date: YYYY-MM-DD | 变更: … -->")
    if not re.match(r"^\d+\.\d+\.\d+$", out["version"]):
        raise TplError("模板版本号须为 X.Y.Z 形式，现为「%s」" % out["version"])
    return out


def resolve_meta(spec):
    """版本留痕三来源取其一：body 内注释行 > spec.template.meta > 报错。"""
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    body = t.get("body") or ""
    m = META_RE.search(body)
    if m:
        meta = parse_meta_line(m.group(0))
        meta["source"] = "body"
        return meta
    given = t.get("meta") if isinstance(t.get("meta"), dict) else {}
    if given.get("version"):
        if not re.match(r"^\d+\.\d+\.\d+$", str(given["version"])):
            raise TplError("模板版本号须为 X.Y.Z 形式，现为「%s」" % given["version"])
        g = dict(given)
        g["source"] = "spec"
        return g
    raise TplError("模板版没有版本留痕：在模板正文首行加 "
                   "<!-- tpl: 名称 | ver: 1.0.0 | date: YYYY-MM-DD | 变更: 初版 -->，"
                   "或在 spec.template.meta 里给 version/date/change")


def strip_meta(text):
    """版本留痕行是给机器读的，出件正文里不留。"""
    return META_RE.sub("", text or "").strip()


# ------------------------------------------------------------------ 条件段
def find_switches(text):
    """返回 (开关名集合, 错误列表)：开关必须成对、且不得交叉嵌套。"""
    errs, stack, names = [], [], set()
    tokens = []
    for m in OPEN_RE.finditer(text or ""):
        tokens.append((m.start(), "open", m.group(1), m.group(2).strip()))
    for m in CLOSE_RE.finditer(text or ""):
        tokens.append((m.start(), "close", None, m.group(1).strip()))
    tokens.sort()
    for _, kind, sigil, name in tokens:
        if kind == "open":
            stack.append(name)
            names.add(name)
        else:
            if not stack:
                errs.append("条件段闭合多余：{{/%s}} 没有对应的开始标记" % name)
                continue
            top = stack.pop()
            if top != name:
                errs.append("条件段交叉嵌套：{{#%s}} 里闭合了 {{/%s}}（须成对且不得交叉）"
                            % (top, name))
    for left in stack:
        errs.append("条件段未闭合：{{#%s}} 缺少 {{/%s}}" % (left, left))
    named = set(names)
    for m in CLOSE_RE.finditer(text or ""):
        if m.group(1).strip() not in named:
            errs.append("条件段闭合无对应开始：{{/%s}}" % m.group(1).strip())
    return names, errs


def _match_close(text, start):
    """从 start（{{#x}} 的结尾）起找配对的 {{/x}}，返回 (inner_start, inner_end, after) 。"""
    depth, pos = 1, start
    while True:
        nxt_o = OPEN_RE.search(text, pos)
        nxt_c = CLOSE_RE.search(text, pos)
        if not nxt_c:
            raise TplError("条件段未闭合")
        if nxt_o and nxt_o.start() < nxt_c.start():
            depth += 1
            pos = nxt_o.end()
            continue
        depth -= 1
        if depth == 0:
            return start, nxt_c.start(), nxt_c.end()
        pos = nxt_c.end()


def _render_segments(text, switches, errs, depth=0):
    """逐段展开条件块。不支持嵌套超过 1 层——超了直接报，避免实现与预期不一致。"""
    if depth > 1:
        raise TplError("条件段只支持一层嵌套")
    out, pos = [], 0
    while True:
        m = OPEN_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        name, sigil = m.group(2).strip(), m.group(1)
        inner_s, inner_e, after = _match_close(text, m.end())
        inner = text[inner_s:inner_e]
        if name not in switches:
            errs.append("条件段开关未定：{{%s%s}}（须显式给值，不默认保留）" % (sigil, name))
            val = False
        else:
            val = bool(switches[name])
        if sigil == "^":
            val = not val
        if val:
            out.append(_render_segments(inner, switches, errs, depth + 1))
        pos = after
    return "".join(out)


# ------------------------------------------------------------------ 占位符
def scan_placeholders(text):
    """模板正文里实际用到的占位符名（去重保序，排除条件段语法）。"""
    body = OPEN_RE.sub("", CLOSE_RE.sub("", text or ""))
    seen = []
    for m in PH_RE.finditer(body):
        n = m.group(1).strip()
        if n and n not in seen:
            seen.append(n)
    return seen


def _norm_name(s):
    return (s or "").strip().strip("{}").strip()


def check(spec, switches=None, strict_sign=True, filling=True):
    """体检：返回 dict(errors, warnings, info)。不抛异常，供出件前统一拦。

    filling=True  —— 出件模式：必填占位符必须有值（值可来自 template.values）；
    filling=False —— 体检模式：只查结构（登记是否齐、条件段是否成对、版本是否有留痕），
                     不管现在填没填。模板刚写出来时就该用这个。
    """
    errors, warns = [], []
    switches = switches or {}
    t = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    raw_body = t.get("body") or ""
    if not raw_body.strip():
        return {"errors": ["模板正文为空：spec.template.body 缺失"], "warnings": [], "info": {}}
    try:
        meta = resolve_meta(spec)
    except TplError as ex:
        return {"errors": [str(ex)], "warnings": [], "info": {}}

    body = strip_meta(raw_body)
    # ① 条件段结构
    _, sw_errs = find_switches(body)
    errors.extend(sw_errs)
    sw_names, _ = find_switches(body)

    # ② 说明表登记
    declared = {}
    for p in (t.get("placeholders") or []):
        if not isinstance(p, dict):
            continue
        n = _norm_name(p.get("name"))
        if n:
            declared[n] = p
    used = scan_placeholders(body)
    unreg = [n for n in used if n not in declared]
    unused = [n for n in declared if n not in used]
    if unreg:
        errors.append("模板里有、说明表没登记（模板作者补说明表）：%s"
                      % "、".join("{{%s}}" % n for n in unreg))
    if unused:
        warns.append("说明表登记了、模板正文没用（删掉或补进正文）：%s"
                     % "、".join("{{%s}}" % n for n in unused))

    # ③ 必填未填（体检模式不看这一项——模板刚写出来时就该能过结构检查）
    values = t.get("values") if isinstance(t.get("values"), dict) else {}
    filled = {_norm_name(k): v for k, v in values.items()}
    blanks, still_tpl = [], []
    for n in used:
        p = declared.get(n) or {}
        req = bool(p.get("required"))
        v = filled.get(n)
        if v is None or str(v).strip() == "":
            if req:
                blanks.append(n)
            continue
        if re.search(r"\{\{[^{}]*\}\}", str(v)):
            still_tpl.append(n)
    if blanks and not filling:
        warns.append("必填占位符尚未填值（体检模式不拦，出件时必须填实）：%s"
                     % "、".join("{{%s}}" % n for n in blanks))
        blanks = []
    if blanks:
        soft = [n for n in blanks if any(k in n for k in SOFT_NAME_HINT)] if not strict_sign else []
        hard = [n for n in blanks if n not in soft]
        if hard:
            errors.append("必填占位符未填实：%s" % "、".join("{{%s}}" % n for n in hard))
        if soft:
            warns.append("签名/日期类未填（可留待手签，出件前仍建议核对）：%s"
                         % "、".join("{{%s}}" % n for n in soft))
    if still_tpl:
        errors.append("占位符填的还是占位符（等于没填）：%s"
                      % "、".join("{{%s}}" % n for n in still_tpl))

    # ④ 开关未给值（仅出件模式要求；体检模式只提示有哪些开关）
    for s in sw_names:
        if s not in switches:
            msg = "条件段开关未给值：%s（可取值 1/0、true/false、是/否）" % s
            (errors if filling else warns).append(msg)

    info = {"meta": meta, "switches": sorted(sw_names), "used": used,
            "declared": list(declared), "body": body, "template_name": (t.get("name") or "").strip()}
    return {"errors": errors, "warnings": warns, "info": info}


def render(spec, switches=None):
    """出件前渲染：必填必须已填实（filling=True），再展开条件段。"""
    r = check(spec, switches, filling=True)
    if r["errors"]:
        raise TplError("模板未通过校验，不能出件：\n  - " + "\n  - ".join(r["errors"]))
    body = r["info"]["body"]
    errs = []
    out = _render_segments(body, switches or {}, errs)
    if errs:
        raise TplError("条件段渲染失败：\n  - " + "\n  - ".join(errs))
    # 去掉因条件段被裁掉而留下的空行堆积
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, r["info"]


# ------------------------------------------------------------------ 清单派生
def scan_dir(d):
    """扫模板目录里所有 *.tpl.md（或 .md），抽版本留痕，派生清单。"""
    rows = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith((".tpl.md", ".md")):
            continue
        p = os.path.join(d, fn)
        try:
            text = io.open(p, encoding="utf-8").read()
        except Exception:
            continue
        m = META_RE.search(text)
        if not m:
            continue
        try:
            meta = parse_meta_line(m.group(0))
        except TplError as ex:
            rows.append({"file": fn, "error": str(ex)})
            continue
        body = strip_meta(text)
        rows.append({"file": fn, "name": meta.get("name") or fn,
                     "version": meta.get("version"), "date": meta.get("date") or "",
                     "change": meta.get("change") or "",
                     "placeholders": scan_placeholders(body),
                     "switches": sorted(find_switches(body)[0]),
                     "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]})
    return rows


def manifest_md(rows):
    L = ["# 模板清单（自动派生，勿手改）", "",
         "> 真源是各模板首行的 `<!-- tpl: … -->` 留痕；本清单由 `scripts/tpl-engine.py manifest` 扫描生成，",
         "> `check.py` 会比对两者是否一致——改了模板忘更新清单会直接报错。", "",
         "| 模板 | 版本 | 日期 | 占位符 | 条件开关 | 正文指纹 | 变更 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("error"):
            L.append("| %s | — | — | — | — | — | ⚠ %s |" % (r["file"], r["error"]))
            continue
        L.append("| %s | %s | %s | %d 个 | %s | `%s` | %s |"
                 % (r["name"], r["version"], r["date"], len(r["placeholders"]),
                    "、".join(r["switches"]) or "—", r["sha256"], r["change"]))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ CLI
def _read_spec(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_switches(pairs):
    out = {}
    for s in pairs or []:
        if "=" not in s:
            raise SystemExit("开关须写成 名称=1/0，收到：%s" % s)
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().lower() in ("1", "true", "yes", "y", "是", "有")
    return out


def main():
    ap = argparse.ArgumentParser(description="模板引擎加固：占位符校验／条件段／版本留痕")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="体检模板结构（不要求必填已填，不出件）")
    c.add_argument("spec")
    c.add_argument("--switch", action="append", default=[], help="开关=1/0，可重复")

    r = sub.add_parser("render", help="按出件口径校验（必填须已填实）并渲染正文")
    r.add_argument("spec")
    r.add_argument("--switch", action="append", default=[])
    r.add_argument("--out", default=None)

    m = sub.add_parser("manifest", help="扫描模板目录，派生清单 Markdown")
    m.add_argument("dir")
    m.add_argument("--out", default=None)

    a = ap.parse_args()

    if a.cmd == "manifest":
        rows = scan_dir(a.dir)
        md = manifest_md(rows)
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(md)
            print("已写：%s（%d 个模板）" % (a.out, len(rows)))
        else:
            print(md)
        return 0

    spec = _read_spec(a.spec)
    sw = _parse_switches(a.switch)
    filling = (a.cmd == "render")
    res = check(spec, sw, filling=filling)
    if res["errors"]:
        print("[E] 模板校验未通过（%d 项）" % len(res["errors"]))
        for e in res["errors"]:
            print("  - " + e)
    for w in res["warnings"]:
        print("[W] " + w)
    if res["info"]:
        mt = res["info"]["meta"]
        print("[i] 模板：%s ｜ 版本 %s（%s）｜ 占位符 %d 个 ｜ 开关 %d 个"
              % (res["info"]["template_name"] or "未命名", mt.get("version"),
                 mt.get("date") or "—", len(res["info"]["used"]), len(res["info"]["switches"])))

    if res["errors"]:
        return 1
    if a.cmd == "render":
        body, _ = render(spec, sw)
        if a.out:
            io.open(a.out, "w", encoding="utf-8").write(body)
            print("[OK] 已渲染：%s" % a.out)
        else:
            print("-" * 60)
            print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
