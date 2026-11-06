r"""数字审计 num-audit.py —— 交付物里每个数字都要被算到、被引到，或自己标成估计。

用法:
  python -X utf8 num-audit.py <doc.md> [--root S:/work/WCIS] [--anchor anchors.json] [--json]
  python -X utf8 num-audit.py <doc.md> --root S:/work/WCIS [--verbose] [--json]

检查项
  A1 等式   文中写出的 a op b = c 重新求值。
  A2 派生   用文中自己声明的口径重算(效率/加和/字节率/Mbps/pps/帧预算/片数/延迟/倍率)。
            ⇒ 抓数量级错与双重计数。基数必须来自文中或独立常数，对不上就 FAIL。
输出: 默认只打 FAIL 全量 + 每条 WARN 一行摘要(省 token); --verbose 打全部含 PASS; --json 另存全量报告.
  B  引用   `file.md:123`／`:123-456` 一律打开真文件：存在? 行号在范围内?
            引用句中出现的标识符(≥6 字符)真的落在被引区间里?
  C  锚点   anchors.json 里的外部独立常数(如千兆 1 488 100 pps、1 B = 8 bit)
            必须被文中真的引用过 ⇒ 防"拿自己的中间数自证"。

退出码 0=无 FAIL  1=有 FAIL  2=用法错。WARN 不改退出码。
"""

from __future__ import annotations

import json
import os
import re
import sys

NL = chr(10)
BS = chr(92)

# ------------------------------------------------------------------ 数字

TOKEN = r"\d[\d,_ ]*\d|\d"
NUM = rf"(?:{TOKEN})(?:\.\d+)?(?:%|万亿|亿|万|kB|KB|MB|GB|kb|K|M|G)?"
UNITS_MULT = (("万亿", 1e12), ("亿", 1e8), ("万", 1e4))


def norm_num(s):
    """'1 488' / '2 850 B' / '95.50%' / '2.35 MB' -> float 或 None。"""
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("_", "").replace("\u00a0", "")
    s = re.sub(r"(?<=\d)[ \u202f](?=\d)", "", s)  # 千位空格：1 488 -> 1488
    for u, m in UNITS_MULT:
        if s.endswith(u):
            try:
                return float(s[: -len(u)]) * m
            except ValueError:
                return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    for suf, m in (("kB", 1e3), ("KB", 1e3), ("MB", 1e6), ("GB", 1e9), ("kb", 1e3), ("K", 1e3), ("M", 1e6), ("G", 1e9)):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
            try:
                v = float(s)
            except ValueError:
                return None
            return v / 100.0 * m if pct else v * m
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if pct else v


def close(a, b, rel=0.02, abs_=0.01):
    if a is None or b is None:
        return False
    if a == b:
        return True
    d = abs(a - b)
    return d <= abs_ or d <= rel * max(abs(a), abs(b), 1e-12)


def rec(check, expr, expect, got, ok, why=None):
    return {
        "check": check,
        "expr": (expr or "").replace(NL, " ")[:74],
        "expect": None if expect is None else (round(expect, 4) if isinstance(expect, float) else expect),
        "got": None if got is None else (round(got, 4) if isinstance(got, float) else got),
        "status": "PASS" if ok else "FAIL",
        "why": why,
    }


# ------------------------------------------------------------------ A1 等式

EQ = re.compile(
    r"(?P<lhs>(?:\d[\d,_ ]*(?:\.\d+)?\s*[+\-×*/÷]\s*)+\d[\d,_ ]*(?:\.\d+)?)"
    r"\s*(?:≈|~|=|==)\s*(?P<c>\d[\d,_ ]*(?:\.\d+)?)(?P<per>%)?"
)


def _eval_chain(s):
    """'14 + 20 + 8 + 8' -> 50；先乘除后加减。括号注释先剥掉。失败 None。"""
    s = re.sub(r"（[^）]*）|\([^)]*\)", " ", s)
    s = s.replace(",", "").replace("_", "").replace("\u00a0", "")
    terms = re.split(r"\s*([+\-×*/÷])\s*", s.strip())
    if len(terms) < 3:
        return None
    try:
        nums = [float(t) for t in terms[0::2]]
    except ValueError:
        return None
    ops = terms[1::2]
    if len(ops) != len(nums) - 1:
        return None
    acc = [nums[0]]                      # 第一项；后续 + 开新项，- 折成负项
    for op, n in zip(ops, nums[1:]):
        if op in ("×", "*"):
            acc[-1] = acc[-1] * n
        elif op in ("/", "÷"):
            if not n:
                return None
            acc[-1] = acc[-1] / n
        elif op == "+":
            acc.append(n)
        else:
            acc.append(-n)
    return sum(acc)


def check_equations(text):
    out = []
    for m in EQ.finditer(text):
        e = _eval_chain(m.group("lhs"))
        c = norm_num(m.group("c"))
        if e is None or c is None or e != e:
            continue
        if "+" in m.group("lhs") and e > 1e11:  # 时间戳
            continue
        if m.group("per") and not close(e, c):
            e = e * 100  # 写成 a/b = c% 时比值要乘 100
        out.append(rec("A1:链", m.group(0), e, c, close(e, c)))
    return out


# ------------------------------------------------------------------ A2 派生

def gather_constants(text):
    """'片长 = 50 + 1400 = 1450 B' 取链上最后一个数。"""
    c = {}
    for m in re.finditer(r"(?P<name>[\w\u4e00-\u9fff]{1,14})\s*=\s*(?P<tail>[^\n]{1,120})", text):
        tail = m.group("tail").split("（")[0]
        ns = [v for v in (norm_num(x) for x in re.findall(NUM, tail)) if v is not None]
        if ns and ns[-1] < 1e15:
            c.setdefault(m.group("name"), ns[-1])
    return c


def check_derived(text, consts):
    res = []

    def grab(pat):
        return re.search(pat, text, re.S)

    def line_base():
        """线速基数(MB/s)：文中声明优先，否则千兆的 1 Gbit/s ÷ 8 = 125。"""
        for k in ("线上原始速率", "线速", "原始速率", "速率"):
            if k in consts and 1 < consts[k] <= 1000:
                return consts[k], k
        if re.search(r"千兆|GbE|TEMAC|RGMII|1 Gbit/s|1 ?Gbps", text):
            return 125.0, "1 Gbit/s ÷ 8"
        return None, None

    pay = wire = pct = None
    m = grab(r"载荷效率\s*=\s*([\d _]+)\s*/\s*([\d _]+)\s*=\s*([\d.]+)%")
    if m:
        pay, wire, pct = norm_num(m.group(1)), norm_num(m.group(2)), float(m.group(3))
        res.append(rec("A2:载荷效率", m.group(0), pay / wire * 100, pct, close(pay / wire * 100, pct, 0.01, 0.05)))
    if pay is None:
        m = grab(r"payload[^\d]{0,12}?(\d{3,5})")
        pay = norm_num(m.group(1)) if m else None
    if wire is None:
        m = grab(r"线上一片\s*=\s*[^\n=]*=\s*([\d _]+)\s*B")
        wire = norm_num(m.group(1)) if m else None

    # 加和：声明的组成必须真的加起来等于和（防同一串字节算两遍）
    m = grab(r"(线上一片|头|片长)\s*=\s*([^=\n]{4,140}?)=\s*([\d _]+)\s*B")
    if m:
        plain = re.sub(r"（[^）]*）|\([^)]*\)", " ", m.group(2))
        add = [v for v in (norm_num(x) for x in re.findall(NUM, plain)) if v is not None and v < 5000]
        tot = norm_num(m.group(3))
        if add and tot:
            s = sum(add)
            res.append(
                rec("A2:%s 加和" % m.group(1), "%s = %s" % (add, tot), s, tot, s == tot,
                    None if s == tot else "加数和与声明不符 ⇒ 疑重复计入")
            )

    base, bname = line_base()
    if pay and wire and base:
        eff = pay / wire
        m = grab(r"可用[^\n]{0,120}?MB/s")
        if m:
            ns = re.findall(r"([\d.,]+)\s*MB/s", m.group(0))
            if not ns:
                ns = re.findall(r"≈\s*([\d.]+)\s*Mbps", m.group(0))
                g = norm_num(ns[-1] + "Mbps") if ns else None
                e = base * eff * 8
            else:
                g = float(ns[-1].replace(",", ""))
                e = base * eff
            res.append(
                rec("A2:可用字节率(基数 %g←%s)" % (base, bname), "%g × %g/%g" % (base, pay, wire), e, g,
                    close(e, g, 0.03, 0.5),
                    None if close(e, g, 0.03, 0.5) else "声明值对不上任何自述基数 ⇒ 无出处")
            )
        m = grab(r"≈\s*([\d,.]+)\s*Mbps")
        if m:
            g = norm_num(m.group(1))
            e = base * eff * 8
            res.append(rec("A2:Mbps=MB/s×8", "×8", e, g, close(e, g, 0.03, 6)))
        m = grab(r"最高包速\s*≈?\s*([\d _]+)\s*pps")
        if m:
            g = norm_num(m.group(1))
            e = base * 1e6 / wire
            res.append(rec("A2:最高包速", "%g e6/%g" % (base, wire), e, g, close(e, g, 0.02, 300)))
        m = grab(r"帧字节预算\s*[\(（]\s*([\d.]+)\s*MB")
        fm = grab(r"@\s*(\d+)\s*fps")
        if m and fm:
            fps = float(fm.group(1))
            e = base * eff / fps
            res.append(rec("A2:帧字节预算", "eff×线速/%g" % fps, e, float(m.group(1)), close(e, float(m.group(1)), 0.03, 0.06)))
        # 表格行：每帧字节 -> 片数 -> pps -> Mbps -> 余量
        row = re.compile(r"\|\s*([\d.]+)\s*(KB|MB)\s*\|\s*([\d _]+)\s*\|\s*\*{0,2}([\d,.]+)\s*Mbps\*{0,2}\s*\|\s*\*{0,2}([\d _]+)\s*pps\*{0,2}\s*\|\s*[^|]*?余\s*\*{0,2}([\d.]+)\s*倍")
        for mm in row.finditer(text):
            sz = norm_num(mm.group(1) + mm.group(2))
            pk, mbps, pps = norm_num(mm.group(3)), norm_num(mm.group(4)), norm_num(mm.group(5))
            margin = float(mm.group(6))
            if None in (sz, pk, mbps, pps) or not pay or not wire:
                continue
            fps = float(fm.group(1)) if fm else 25.0
            e_pk = -(-sz // pay)
            e_pps = e_pk * fps
            e_mbps = e_pps * wire * 8 / 1e6
            e_margin = base * 1e6 * eff / fps / sz
            ok = e_pk == pk and close(e_pps, pps, 0.02, 30) and close(e_mbps, mbps, 0.03, 5) and close(e_margin, margin, 0.06, 1)
            res.append(rec("A2:表行 %s%s" % (mm.group(1), mm.group(2)),
                           "期望 片%g pps%g Mbps%.1f 余%.1f" % (e_pk, e_pps, e_mbps, e_margin),
                           None, "文中 片%g pps%g Mbps%g 余%g" % (pk, pps, mbps, margin), ok))
    # 攒积延迟
    m = grab(r"延迟\s*=\s*([\d.]+)\s*B\s*÷[^\n]{0,60}?(.{0,320})")
    if m:
        n = float(m.group(1))
        for mm in re.finditer(r"([\d.]+)\s*MB/s[^\d]{0,40}?([\d.]+)\s*ms", m.group(2)):
            rate = float(mm.group(1)) * 1e6
            g = float(mm.group(2))
            e = n / rate * 1000
            res.append(rec("A2:攒积延迟", "%g B ÷ %g MB/s" % (n, rate / 1e6), e, g, close(e, g, 0.25, 0.06),
                           None if close(e, g, 0.25, 0.06) else "声明比实算大 %g 倍" % round(g / e)))
    # 倍率
    m = grab(r"快约\s*([\d.]+)\s*倍\s*[\(（]?\s*([\d.]+)\s*MB/s\s*对\s*([\d.]+)\s*MB/s")
    if m:
        g, a, b = (float(x) for x in m.groups())
        res.append(rec("A2:线/编码器倍率", "%g/%g" % (a, b), a / b, g, close(a / b, g, 0.06, 0.06)))
    return res


# ------------------------------------------------------------------ B 引用

EXT = r"(?:md|txt|v|sv|svh|xdc|tcl|py|json|log|csv|ini|h|c|sh|xci|bd|lib|hdl)"
# 空格只允许出现在反引号里：散文里的两个词不能被吃成文件名。
REF = re.compile(
    r"(?P<file>`[^`\n|]{1,140}?\." + EXT + r"|[\w./\\\-\u4e00-\u9fff]+\." + EXT + r")"
    r"(?::|#)(?P<lo>\d+)(?:\s*[-–]\s*(?P<hi>\d+))?"
)
BARE = re.compile(r"[（(]([^（）()]{0,40}?)[::]（?(?P<lo>\d+)(?:\s*[-–]\s*(?P<hi>\d+))?）?\)")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{5,}")


def resolve(ref, root, index):
    ref = ref.replace("\\", os.sep)
    for cand in (os.path.join(root, ref), ref):
        if os.path.isfile(cand):
            return cand
    base = os.path.basename(ref)
    hits = index.get(base.lower(), [])
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


def build_index(root):
    idx = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv", "largefiles")]
        for f in files:
            idx.setdefault(f.lower(), []).append(os.path.join(dirpath, f))
    return idx


def check_refs(lines, root):
    res = []
    index = build_index(root)
    pathc, linec = {}, {}
    for i, l in enumerate(lines, 1):
        for m in REF.finditer(l):
            f, lo = m.group("file").strip("`").strip(), int(m.group("lo"))
            hi = int(m.group("hi")) if m.group("hi") else lo
            if f not in pathc:
                pathc[f] = resolve(f, root, index)
            path = pathc[f]
            name = "%s:%d%s" % (f, lo, ("-%d" % hi) if hi != lo else "")
            if path is None:
                res.append({"check": "B:引用", "line": i, "expr": name, "status": "FAIL",
                            "expect": "文件存在", "got": "全仓找不到同名文件", "why": None})
                continue
            if path not in linec:
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        linec[path] = fh.read().split(NL)
                except OSError as e:
                    res.append({"check": "B:引用", "line": i, "expr": name, "status": "FAIL",
                                "expect": "可读", "got": str(e), "why": None})
                    continue
            tgt = linec[path]
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if hi > len(tgt):
                res.append({"check": "B:引用", "line": i, "expr": name, "status": "FAIL",
                            "expect": "≤%d 行" % len(tgt), "got": hi, "why": None})
                continue
            body = " ".join(tgt[lo - 1: hi])
            # 同句里像标识符的词必须出现在被引区间
            ctx = NL.join(lines[max(0, i - 3): i + 2])
            want = [w for w in dict.fromkeys(IDENT.findall(ctx)) if not w.startswith("http")]
            hits = [w for w in want if w in body]
            ok = bool(hits) or not want
            res.append({
                "check": "B:引用", "line": i, "expr": name, "path": rel,
                "expect": ",".join(hits) if hits else ("句中有标识符可比" if want else "无标识符"),
                "got": (body.strip()[:60] if not hits else "命中"),
                "status": "PASS" if ok else "WARN",
                "why": None if ok else "被引区间里找不到本句的标识符，人工确认行号",
            })
    return res


# ------------------------------------------------------------------ C 锚点

def check_anchors(text, anchors):
    res = []
    for name, spec in anchors.items():
        if not any(re.search(p, text) for p in spec.get("only_if", [""])):
            continue
        pats = spec["assert"]
        got = [bool(re.search(p, text)) for p in pats]
        res.append({
            "check": "C:锚点", "name": name, "value": spec.get("value"),
            "expect": pats, "got": got,
            "status": "PASS" if all(got) else "FAIL",
            "why": spec.get("why", ""),
        })
    return res



DERIVED_RE = re.compile(r"[\d][\d,_ ]*(?:\.\d+)?\s*(?:MB/s|Mbps|kbps|Kbps|pps|ms|us|ns|倍|%|kB|KB|MB|px|bit)\b")
FORMULA_RE = re.compile(r"[=÷×+\-*/]|÷|×|实测|测得|读数|来自|标定|黄金模型|判据|A 级|\|\|\|\|")
MARKED_RE = re.compile(r"估|约|量级|待测|待实测|未实测|B\b|D\b|参考|假设")


def check_bare_numbers(lines):
    """A3 裸数字：带单位的断言若同段无算式、又没标"估/实测/待"，就是要你补链。"""
    res = []
    for i, l in enumerate(lines, 1):
        ls = l.strip()
        if not ls or ls.startswith("#"):
            continue
        hits = DERIVED_RE.findall(ls)
        if not hits:
            continue
        if FORMULA_RE.search(ls) or MARKED_RE.search(ls):
            continue
        res.append({"check": "A3:裸数字", "line": i, "expr": ls[:70],
                    "expect": "同段给算式，或标 估/实测/待测", "got": ",".join(sorted(set(hits))[:4]),
                    "status": "WARN", "why": None})
    return res


# ------------------------------------------------------------------ main


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    doc = args[0]
    root = os.getcwd()
    here = os.path.dirname(os.path.abspath(__file__))
    anchor_file = os.path.join(here, "anchors.json")
    as_json = "--json" in argv
    verbose = "--verbose" in argv
    for a in argv[1:]:
        if a.startswith("--root="):
            root = a.split("=", 1)[1]
        elif a.startswith("--anchor="):
            anchor_file = a.split("=", 1)[1]
    with open(doc, encoding="utf-8") as fh:
        raw = fh.read()
    lines = raw.split(NL)
    anchors = json.load(open(anchor_file, encoding="utf-8")) if os.path.isfile(anchor_file) else {}
    consts = gather_constants(raw)

    groups = [
        ("A1 等式", check_equations(raw)),
        ("A2 派生复算", check_derived(raw, consts)),
        ("A3 裸数字(逼出算式/实测标记)", check_bare_numbers(lines)),
        ("B 引用回查", check_refs(lines, root)),
        ("C 外部锚点", check_anchors(raw, anchors)),
    ]
    fails = warns = 0
    print("== num-audit  %s  (%d 行, 根=%s) ==" % (os.path.basename(doc), len(lines), root))
    for title, items in groups:
        items = [x for x in items if x]
        f = [x for x in items if x.get("status") == "FAIL"]
        w = [x for x in items if x.get("status") == "WARN"]
        fails += len(f)
        warns += len(w)
        print(NL + "-- %s: %d 项 | FAIL %d | WARN %d" % (title, len(items), len(f), len(w)))
        for x in items:
            st = x.get("status")
            if st == "FAIL" or verbose:
                print("   " + json.dumps(x, ensure_ascii=False))
            elif st == "WARN":
                print("   WARN %s:%s %s" % (x.get("check"), x.get("line"),
                                            str(x.get("expr")).replace(NL, " ")[:70]))
    print(NL + "总计 FAIL %d / WARN %d" % (fails, warns))
    if as_json:
        with open(doc + ".audit.json", "w", encoding="utf-8") as fh:
            json.dump({g[0]: g[1] for g in groups}, fh, ensure_ascii=False, indent=1)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
