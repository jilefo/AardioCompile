"""变异测试：在真实源码上人为植入已知 bug，确认审计规则真抓得住。

为什么要做这个
--------------
审计报表一片绿有两种可能：代码干净，或者探测器根本没在工作。
只跑「干净源码」无法区分这两者 —— 这是本项目踩过的坑的元模式：
写出来的时候觉得它在守着，第一次真出事才发现它一直是哑的。

所以这里反过来做：把历史上真实发生过的三个 bug 重新植入源码副本，
要求 audit.py 必须报红。有一条抓不住，就算失败。

用法
----
    python mutation_test.py
"""
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit  # noqa: E402

# (说明, 锚点原文, 替换后文本, 期望命中的规则号)
MUTATIONS = [
    ("选项只加 valOpts 不加 allOpts（曾导致 --cwd 一用就报未知参数）",
     'var allOpts = {\n    "--out"; "--ver"; "--host"; "--log"; "--exclude"; "--name"; "--cwd";',
     'var allOpts = {\n    "--out"; "--ver"; "--host"; "--log"; "--exclude"; "--name";',
     "P3"),

    ("try 里放 return 值（不生效，错误分支被吞掉）",
     '    try{\n        var sys = dotNet.import("System");',
     '    try{\n        return 1;\n        var sys = dotNet.import("System");',
     "P1"),

    # 【坑】锚点千万别挑会随业务变化的文本。
    # 原来锚的是 var AAC_VERSION = "2.2.0"; —— 把版本号改成 2.3.0 之后，
    # 这条用例被静默 SKIP，变异数从 7 掉到 6，而退出码仍然是 0（"全通过"）。
    # 与 dep_scan 踩的是同一个坑：**声称还在防守的防线，其实已经不在了**。
    # 所以锚点改用语义恒定、几乎不可能被改动的 import 行；
    # 同时 SKIP 现在的下场是算失败（见 main）。
    ("顶层函数前向引用（运行时是 null）",
     'import dotNet;',
     'import dotNet;\nvar _probeForward = emit(1);',
     "P2"),

    ("双引号串里用反斜杠转义引号（字符串会跑飞）",
     'var escStr = function(s){',
     'var escStr = function(s){\n    var _probe = "he said \\"hi\\"";',
     "P6"),

    ("for 第二段写复合条件（解析失败）",
     "var sortByRel = function(arr){",
     "var sortByRel = function(arr){\n    for(i = 1; #arr && #arr < 6; 1){ }",
     "P5"),

    ("用假转义找换行（整份源码被当成一行，注释后的 import 全漏检）",
     "        var nl = string.indexOf(src, CH_LF, pos);",
     '        var nl = string.indexOf(src, "\\n", pos);',
     "P10"),

    ("字符集写成 ' \\t\\r\\n'（会把库名首尾的 t/r/n 字母啃掉）",
     "    return string.trim(S(s), WS);",
     '    return string.trim(S(s), " \\t\\r\\n");',
     "P10"),
]

TARGET = "aac.aardio"


def main():
    src_path = HERE / TARGET
    if not src_path.is_file():
        print("找不到源码: %s" % src_path)
        return 2
    base = src_path.read_text(encoding="utf-8")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aac-mut-"))
    ok = bad = skipped = 0
    try:
        for desc, old, new, expect in MUTATIONS:
            if old not in base:
                # SKIP 不是"跳过"，是"这条防线已经不在了"。
                # 早期版本把 SKIP 扔向 `continue`，既不计成功也不计失败，
                # 于是变异数从 7 悄悄掉到 6、退出码依旧是 0 ——
                # 审计一片绿，其实是少了一盏灯自己在开心。必须算失败。
                bad += 1
                skipped += 1
                print("  FAIL  %s —— 锚点已不在源码里，该规则已无人证明:"
                      "\n        %r" % (desc, old[:90]))
                continue
            q = tmp / TARGET
            q.write_text(base.replace(old, new, 1), encoding="utf-8")
            try:
                got = [f[1] for f in audit.audit_file(q)]
            except Exception as e:
                print("  ERR   %s —— 审计抛异常: %s: %s" % (desc, type(e).__name__, e))
                bad += 1
                continue
            hit = any(expect in g for g in got)
            if hit:
                ok += 1
                print("  PASS  %s" % desc)
            else:
                bad += 1
                print("  FAIL  %s —— 期望命中 %s，实际: %s"
                      % (desc, expect, got or "无告警"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("")
    print("变异测试: 通过 %d / 失败 %d / 共 %d" % (ok, bad, len(MUTATIONS)))
    if skipped:
        print("  其中 %d 条是锚点腐化（毒药都塞不进去了，谈不上验证）" % skipped)
    if ok + bad != len(MUTATIONS):
        print("  参与数 %d != 用例总数 %d，有人在装死" % (ok + bad, len(MUTATIONS)))
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
