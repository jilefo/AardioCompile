"""aac 源码静态陷阱审计

背景
----
这个项目踩过一批 aardio 语言层面的坑, 它们有几个共同特点:

  * 不报语法错误, 编译绿灯通过
  * 运行时不抛异常, 而是「静默地不生效」
  * 只在特定分支/特定机器上才暴露, 靠手点很难复现

典型例子:

  1. try{} / catch{} 里的 `return 值` 既不返回也不生效
     → cmdRun 的异常分支被吞, 崩溃的脚本照样返回退出码 0
  2. 顶层 `var f = function(){}` 必须先定义后使用, 否则运行时是 null
     → 报错信息是 "Attempt to call ... {Type}:null", 看不出是顺序问题
  3. 新增命令行选项只加进 valOpts(取值表) 没加进 allOpts(合法表)
     → 帮助里写着支持, 实际一用就被自己的校验判成"未知参数"
  4. string.save 不显式给代码页就按 GBK 写
     → 日志在中文环境全部乱码, 排错时没法读

这些都靠 "写的时候记住" 是守不住的, 必须由工具拦。本脚本就是那道闸。

用法
----
    python audit.py                 # 审所有源码
    python audit.py aac.aardio      # 只审指定文件
    python audit.py --json          # 机器可读输出

退出码: 0=无 ERROR  1=有 ERROR  2=脚本自身出错
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SOURCES = ["aac.aardio", "aardioHost.aardio", "lib/aacpkg.aardio"]

# ---------------------------------------------------------------- 词法扫描
# 把源码按字符标注类型, 这样探测 RegEx 只作用在真正的代码上,
# 不会把注释里写的反面例子（教学注释里常有 "// 千万别写 xxx"）当成问题。
CODE, STR, LCOM, BCOM, RAW = "code", "str", "lcom", "bcom", "raw"


def scan(src):
    """返回 (kind列表, 行首索引列表, 源码)。

    kind[i] 说明 src[i] 属于代码/字符串/注释, 便于在「抹掉非代码」后做结构分析。
    顺带 spaw 出字符串字面量中国的信息（如 `` 原义串）。
    """
    n = len(src)
    kinds = [CODE] * n
    i = 0
    state = CODE
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if state == LCOM:
            kinds[i] = LCOM
            if c == "\n":
                state = CODE
            i += 1
            continue

        if state == BCOM:
            kinds[i] = BCOM
            if c == "*" and nxt == "/":
                kinds[i + 1] = BCOM
                i += 2
                state = CODE
                continue
            i += 1
            continue

        if state == RAW:
            kinds[i] = RAW
            # 原义串里 `` 表示一个字面反引号
            if c == "`":
                if nxt == "`":
                    kinds[i + 1] = RAW
                    i += 2
                    continue
                state = CODE
            i += 1
            continue

        if state == STR:
            kinds[i] = STR
            # 数连续反斜杠: 奇数个说明下一个字符被转义
            j = i
            while j < n and src[j] == "\\":
                j += 1
            nb = j - i
            if nb:
                for k in range(i, j):
                    kinds[k] = STR
                # 奇数个反斜杠 + 引号 == 试图转义引号（aardio 不支持, 会让字符串跑飞）
                if nb % 2 == 1 and j < n:
                    kinds[j] = STR
                    i = j + 1
                    continue
                i = j
                continue
            if c == '"':
                state = CODE
            i += 1
            continue

        # ---- state == CODE ----
        if c == "/" and nxt == "/":
            kinds[i] = kinds[i + 1] = LCOM
            i += 2
            state = LCOM
            continue
        if c == "/" and nxt == "*":
            kinds[i] = kinds[i + 1] = BCOM
            i += 2
            state = BCOM
            continue
        if c == '"':
            kinds[i] = STR
            i += 1
            state = STR
            continue
        if c == "`":
            kinds[i] = RAW
            i += 1
            state = RAW
            continue
        i += 1

    return kinds


def code_view(src, kinds):
    """抹掉字符串/注释内容但保留位置与换行, 便于结构分析且行号不漂移。"""
    out = []
    for ch, k in zip(src, kinds):
        if k == CODE:
            out.append(ch)
        elif ch == "\n" or ch == "\r":
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def line_of(src, idx):
    return src.count("\n", 0, idx) + 1


def str_regions(src, kinds):
    """抽出所有字符串/原义串字面量: [(起, 止, 原文)]"""
    res = []
    i = 0
    n = len(src)
    while i < n:
        if kinds[i] in (STR, RAW):
            j = i
            while j < n and kinds[j] == kinds[i]:
                j += 1
            res.append((i, j, src[i:j]))
            i = j
        else:
            i += 1
    return res


# ---------------------------------------------------------------- 探测器
def find_matching_brace(txt, open_idx):
    """txt[open_idx] == '{', 返回配对的 '}' 索引；找不到返回 -1。"""
    depth = 0
    for i in range(open_idx, len(txt)):
        if txt[i] == "{":
            depth += 1
        elif txt[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


RET_RE = re.compile(r"\breturn\b([^;\n]*)")
TRY_RE = re.compile(r"\b(try|catch)\b\s*(?:\([^)]*\))?\s*\{")


def d_trycatch_return(path, src, view):
    """try/catch 块里的 return 不生效 —— 最阴的一类坑。

    允许 `return true/false`（这是传给回调的继续/中断信号, 语义本身正确）,
    其余一律报错, 包括 `return;`(无值)。
    """
    out = []
    for m in TRY_RE.finditer(view):
        open_idx = m.end() - 1
        close_idx = find_matching_brace(view, open_idx)
        if close_idx < 0:
            continue
        body = view[open_idx + 1:close_idx]
        for rm in RET_RE.finditer(body):
            operand = rm.group(1).strip()
            if operand in ("true", "false"):
                continue
            out.append((line_of(src, open_idx + 1 + rm.start()),
                        "return %s" % (operand or "<空>")))
    return out


TOPVAR_RE = re.compile(r"^var\s+([A-Za-z_]\w*)\s*=\s*function", re.M)


def d_forward_ref(path, src, view):
    """顶层 `var f = function(){}` 在使用点之后才定义 → 运行时是 null。"""
    defs = []
    for m in TOPVAR_RE.finditer(view):
        defs.append((m.start(), m.group(1)))
    out = []
    for defpos, name in defs:
        use = re.compile(r"(?<![\w.])%s\s*\(" % re.escape(name))
        for um in use.finditer(view):
            if um.start() >= defpos:
                continue
            # 只报真正的「调用/定义前引用」; 同一行内的自我递归不算
            out.append((line_of(src, um.start()), name, line_of(src, defpos)))
    return out


def _table_vals(text, name):
    """取 `var <name> = { ... };` 里的字符串字面量。

    【坑】必须在原始 text 上解析, 不能传抹过字符串的 view ——
    掩码后 { } 里全是空格, 取出来永远是空表, 规则静默失效。
    """
    m = re.search(r"var\s+%s\s*=\s*\{(.*?)\};" % re.escape(name), text, re.S)
    if not m:
        return None
    return re.findall(r'"([^"]*)"', m.group(1))


def d_opt_tables(path, src, view, strs):
    """选项清单漂移检测。

    三张表必须一致:
      valOpts  -- 需要跟值的选项
      allOpts  -- 合法选项（不在表内一律报"未知参数"）
      帮助文本 -- 对外承诺支持的选项
    任何一处不一致都会变成「文档写着能用、实际一用就 rc=1」这种最伤用户的 bug。
    """
    out = []
    val = _table_vals(src, "valOpts")
    all_ = _table_vals(src, "allOpts")
    if val is None or all_ is None:
        return out
    for v in val:
        if v not in all_:
            out.append((0, "valOpts 里的 %s 不在 allOpts 中 —— 它会被判成未知参数" % v))
    # 帮助里写了却没有实现的选项
    documented = set()
    for _a, _b, raw in strs:
        for m in re.finditer(r"--[A-Za-z][\w-]*", raw):
            documented.add(m.group(0))
    doc_opts = {d for d in documented if d.startswith("--")}
    # 帮助段里出现的形如 "--out=路径" 的条目才算「承诺」, 逐个出现在 emit("  --xx=...") 里
    for d in sorted(doc_opts):
        if d in all_:
            continue
        # 只报出现在「公共/build 选项」说明行里的（形如 emit("  --xxx ...")）
        hit = False
        for _a, _b, raw in strs:
            if re.match(r'\s*--%s\b' % re.escape(d[2:]), raw):
                hit = True
                break
        if hit:
            out.append((0, "帮助文本承诺了 %s, 但 allOpts 里没有 —— 用户照着打会报未知参数" % d))
    return out


# string.save 实测结论(见源码里 CP_UTF8 处的注释): 对纯字符串是字节直通,
# 第 4 个代码页参数不做任何转换。所以不存在"忘记给代码页导致乱码"这回事,
# 真正会乱码的是控制台(WriteConsoleB + 控制台代码页)。这条曾经的 WARN 因此撤下,
# 换成下面这条同样真实、同样致命的 split 陷阱。
SPLIT_RE = re.compile(r"string\.split\s*\(([^,()]+),")


def _decode_lit(raw):
    """粗略还原字面量里的转义, 用来判断分隔符到底包含几个真实字符。"""
    out = []
    k = 0
    esc = {"r": "\r", "n": "\n", "t": "\t"}
    while k < len(raw):
        c = raw[k]
        if c == "\\" and k + 1 < len(raw):
            nx = raw[k + 1]
            out.append(esc.get(nx, nx))
            k += 2
        else:
            out.append(c)
            k += 1
    return "".join(out)


def d_split_charset(path, src, view, strs):
    """string.split(s, sep) 的 sep 是「字符集」不是「分隔符」。

    传 "/\\\\" 表示按 "/" 或 "\\\\" 任一字符切 —— 这正是代码里想要的;
    但有人以为 sep 是整体分隔符时会传 "\\r\\n", 结果 r/n 被逐字符剔掉,
    得到一堆碎片且毫无报错。两字符的字符集属于惯用法, 不报;
    三字符及以上、或含 \\r\\n 的一律报。
    """
    out = []
    # 注意: view 里字符串已被抹成空格, 必须回原文本找紧随其后的字面量。
    # 正则刻意停在逗号处 —— 若再让正则尾部的 \s* 吃掉后续空白, 它会连
    # 「被掩码成空格的字符串」一起吃掉, 取到的就只剩右括号了。
    for m in SPLIT_RE.finditer(view):
        seg = src[m.end():m.end() + 80]
        lm = re.search(r'\s*"([^"\n]*)"', seg)
        if not lm:
            continue
        decoded = _decode_lit(lm.group(1))
        if len(decoded) >= 3 or "\r" in decoded or "\n" in decoded:
            out.append((line_of(src, m.start()),
                        "分隔符 %r 被当字符集逐字符切分（真实字符数 %d）"
                        % (lm.group(1), len(decoded))))
    return out


FOR_RE = re.compile(r"\bfor\s*\(([^;]*);([^;]*);")


def d_for_compound_cond(path, src, view):
    """for 的第二段写复合条件会因运算符优先级解析失败: Expected ')' Near 'and'。"""
    out = []
    for m in FOR_RE.finditer(view):
        cond = m.group(2)
        if re.search(r"\b(and|or)\b|&&|\|\|", cond):
            out.append((line_of(src, m.start()), "for 条件过于复杂: %s" % cond.strip()))
    return out


EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")


def d_empty_catch(path, src, view):
    """完全没有注释说明的空 catch —— 异常连同线索一起被吃掉。

    带注释解释「为什么可以忽略」的 catch 是刻意设计, 不报。
    """
    out = []
    # 必须在【原始文本】上找: view 里注释被抹成空格后会凭空多出一批"空 catch"
    for m in EMPTY_CATCH_RE.finditer(src):
        out.append((line_of(src, m.start()),
                    "空的 catch 块，异常连同线索一起被吃掉"))
    return out


DQ_ESC_RE = re.compile(r'(?<!\\)\\(?:\\\\)*\\"')


def d_backslash_quote(path, src, view, strs):
    """双引号串里 \\" 不是转义, 会让字符串跑到行尾, 编译期报莫名其妙的错。"""
    out = []
    for a, b, raw in strs:
        if not raw.startswith('"'):
            continue
        body = raw[1:-1] if raw.endswith('"') and len(raw) > 1 else raw[1:]
        # 数连续反斜杠判断是否真的在转义引号
        for m in re.finditer(r'\\+"', body):
            bs = m.group(0)[:-1]
            if len(bs) % 2 == 1:
                out.append((line_of(src, a + 1 + m.start()),
                            '疑似用 \\" 转义引号: %r' % m.group(0)))
    return out


FAKE_ESC_RE = re.compile(r"\\[trn]")
BS = chr(92)


def d_fake_escape(path, src, view, strs):
    """双引号串里 "\\n" "\\r" "\\t" 是【字面字符】不是转义 —— 本项目最贵的一个坑。

    它带来的不是显示问题, 而是三类静默失效:
      trim 的字符集变成 {空格,\\,t,r,n}       → 库名 winex.caret 变 winex.care
      indexOf(src,"\\n") 永远匹配不到换行     → 整份源码被当一行, 注释后的 import 全漏检
      日志里写的是假的 \\r\\n                → 排错时是一坨挤成长行的文本
    另外 "\\" 在源码里是【两个】反斜杠, 拿它做单字符 == 比较是死代码。
    """
    out = []
    for a, b, raw in strs:
        if not raw.startswith('"'):
            continue
        body = raw[1:-1] if raw.endswith('"') and len(raw) > 1 else raw[1:]
        if FAKE_ESC_RE.search(body):
            out.append((line_of(src, a),
                        "字面量 %s 含假转义，实际是 \\\\+字母，不是换行/制表符" % raw))
    for m in re.finditer(r'(==|!=)\s*"' + re.escape(BS * 2) + r'"', src):
        out.append((line_of(src, m.start()),
                    '用 "%s" 比较单字符：它是两个反斜杠，该分支永不成立' % (BS * 2)))
    return out


TOSTR_RE = re.compile(r"(?<![\w.])tostring\s*\(")


def _enclosing(src, line_no):
    """粗略取包含第 line_no 行的函数体范围: (起行, 止行)。"""
    lines = src.split("\n")
    start = 1
    for i in range(line_no - 1, -1, -1):
        if re.match(r"^var\s+\w+\s*=\s*function", lines[i]):
            start = i + 1
            break
    end = len(lines)
    for j in range(line_no, len(lines)):
        if lines[j] == "};":
            end = j + 1
            break
    return "\n".join(lines[start - 1:end])


def d_tostring(path, src, view):
    """tostring(null) 会抛异常 —— 项目里统一用 S() 兜底。

    为了不把 10 个已经判过空的调用刷成噪声, 这里做上下文判断:
      实参被同一函数内的 null 检查保护过 → 不报
      实参是常量 / #取长 / 成员访问 / 算术表达式 → 不报
    剩下的才是真正可能在 null 上炸的点。
    """
    out = []
    for m in TOSTR_RE.finditer(view):
        ln = line_of(src, m.start())
        # 取实参(到行尾或分号/右括号为止)
        tail = src[m.end():]
        stop = min([x for x in [tail.find("\n"), tail.find(";")] if x >= 0] or [len(tail)])
        arg = tail[:stop].strip().rstrip(")")
        if not arg:
            continue
        if re.fullmatch(r"-?\d+", arg):
            continue
        if arg.startswith("#") or "." in arg or '"' in arg:
            continue
        body = _enclosing(src, ln)
        guard = re.search(r"\b" + re.escape(arg) + r"\s*(==|!=)\s*null", body)
        if guard:
            continue
        out.append((ln, "tostring(%s) 无判空保护，建议换成 S(%s)" % (arg, arg)))
    return out


missing_api = ["string.mid", "string.conv"]


def d_missing_api(path, src, view):
    """本机内核里不存在的 API（查过一次, 别再踩）"""
    out = []
    for api in missing_api:
        for m in re.finditer(re.escape(api) + r"\s*\(", view):
            out.append((line_of(src, m.start()), "%s 在本机内核里不存在" % api))
    return out


DETECTORS = [
    ("P1 try/catch 内 return 失效", d_trycatch_return, "ERROR"),
    ("P2 顶层函数前向引用", d_forward_ref, "ERROR"),
    ("P3 命令行选项清单漂移", d_opt_tables, "ERROR"),
    ("P4 多字符分隔符被当字符集", d_split_charset, "WARN"),
    ("P5 for 复合条件", d_for_compound_cond, "ERROR"),
    ("P6 双引号串里转义引号", d_backslash_quote, "ERROR"),
    ("P7 不存在的 API", d_missing_api, "ERROR"),
    ("P8 tostring 可能踩 null", d_tostring, "WARN"),
    ("P9 空 catch", d_empty_catch, "WARN"),
    ("P10 假转义字面量", d_fake_escape, "ERROR"),
]


def audit_file(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    kinds = scan(src)
    view = code_view(src, kinds)
    strs = str_regions(src, kinds)
    lines = src.split("\n")
    findings = []
    for name, fn, level in DETECTORS:
        try:
            if fn.__code__.co_argcount == 4:
                res = fn(str(path), src, view, strs)
            else:
                res = fn(str(path), src, view)
        except Exception as e:  # 探测器自身出错不能静默
            findings.append((level, name, 0, "探测器异常: %s: %s" % (type(e).__name__, e), None))
            continue
        for r in res:
            ln = r[0]
            loc = lines[ln - 1] if 0 < ln <= len(lines) else ""
            if "audit:ok" in loc:
                continue  # 人工确认过是安全写法，行内显式豁免
            if len(r) == 2:
                findings.append((level, name, r[0], r[1], None))
            else:
                findings.append((level, name, r[0], r[1], r[2]))
    return findings


SELFTESTS = [
    ("P1 try/catch 内 return 失效", """
var f = function(){
    try{
        var v = 1;
        return v;
    }
    catch(e){
    }
    return 0;
};
""", "P1"),

    ("P2 顶层函数前向引用", """
var caller = function(){
    return helper(1);
};
var helper = function(x){
    return x;
};
""", "P2"),

    ("P3 帮助写了但没实现", """
var valOpts = {"--out"; "--nope"};
var allOpts = {"--out"; "--quiet"};
emit("用法:");
emit("  aac build <目录> [选项]");
emit("build 选项:");
emit("  --nope=xx      说明文字");
emit("公共选项:");
emit("  --quiet        少输出");
""", "P3"),

    ("P4 多字符分隔符", """
var lines = string.split(s, "\\r\\n");
""", "P4"),

    ("P5 for 复合条件", """
for(i = 1; #a && #b < 6; 1){
    x = x + 1;
}
""", "P5"),

    ("P6 双引号串里转义引号", """
var s = "he said \\"hi\\" now";
""", "P6"),

    ("P7 不存在的 API", """
var t = string.mid(s, 2, 3);
""", "P7"),

    ("P8 tostring 无保护", """
var g = function(v){
    return tostring(v);
};
""", "P8"),

    ("P9 空 catch", """
try{
    risky();
}
catch(e){
}
""", "P9"),

    ("P10 假转义换行", 'var lines = "a\\nb";\n', "P10"),
    ("P10 双反斜杠做单字符比较", 'if(c == "\\\\"){ x = 1; }\n', "P10"),

    ("抑制标记生效（不应报错）", """
var g = function(v){
    return tostring(v);   // 调用方保证非 null: audit:ok
};
""", None),
]


def selftest():
    """探测器自检: 喂已知坏样例, 确认每条规则真的会报红。

    一片绿的审计报表有两种可能 —— 代码干净, 或者探测器根本没在工作。
    不验证后者, 这个工具就等于没有。
    """
    import tempfile
    ok = bad = 0
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aac-audit-"))
    for i, (desc, body, expect) in enumerate(SELFTESTS):
        p = tmp / ("case%02d.aardio" % i)
        p.write_text(body, encoding="utf-8")
        got = [f[1] for f in audit_file(p)]
        hit = any(expect in g for g in got) if expect else (not got)
        if hit:
            ok += 1
            print("  PASS  %s" % desc)
        else:
            bad += 1
            detail = ("应命中 %s" % expect) if expect else "应无告警"
            print("  FAIL  %s  —— %s，实际: %s" % (desc, detail, got or "无"))
    print("")
    print("自检: 通过 %d / 失败 %d" % (ok, bad))
    return 1 if bad else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv[1:] if not a.startswith("-")]
    as_json = "--json" in argv

    files = [HERE / a for a in args] if args else [HERE / s for s in SOURCES]
    files = [f for f in files if f.is_file()]

    all_findings = {}
    for f in files:
        all_findings[str(f.relative_to(HERE))] = audit_file(f)

    n_err = n_warn = 0
    for fname, items in all_findings.items():
        for level, name, ln, msg, extra in items:
            if level == "ERROR":
                n_err += 1
            else:
                n_warn += 1

    if as_json:
        import json
        print(json.dumps(
            {k: [{"level": a, "rule": b, "line": c, "msg": d}
                 for a, b, c, d, _e in v]
             for k, v in all_findings.items()},
            ensure_ascii=False, indent=2))
        return 1 if n_err else 0

    total = 0
    for fname, items in all_findings.items():
        if not items:
            continue
        print("── %s" % fname)
        for level, name, ln, msg, extra in sorted(items, key=lambda x: x[2]):
            total += 1
            loc = ("第 %s 行" % ln) if ln else "文件级"
            tail = ""
            if extra is not None:
                tail = "（定义在第 %s 行）" % extra
            print("   [%s] %s %s: %s%s" % (level, loc, name, msg, tail))
    print("")
    print("ERROR %d 条 / WARN %d 条" % (n_err, n_warn))
    return 1 if n_err else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv))
