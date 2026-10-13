"""复现宿主的「启动期全量 import」并二分找出凶手。

为什么不用 IDE 反复发布来试
----------------------------
宿主是启动时一次性 import 全部预埋库的。只要有一个库在 import 时
有重副作用, 表现就是**每个产物都起不来**（winex.caret 那次: 所有
EXE 卡死在启动阶段, 日志一行都没有）。逐个单独试是试不出来的 ——
本脚本存在的理由就是: 单库正常, 组合起来照样炸。

但每试一次就重新发布宿主 = 每试一次弹一次 IDE, 机器受不了。
所以这里用 `aac run` 复现同样的加载序列: 同样是发布的独立 EXE、
同样一套标准库、同样按宿主的顺序全量 import —— 零 IDE 弹窗。

用法
----
    python host_import_bisect.py --file _hostlibs.txt
    python host_import_bisect.py --file _hostlibs.txt --timeout 25
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aacpath
import pathlib
import subprocess
import sys
import tempfile
import time

DEFAULT_AAC = aacpath.find_aac()


def try_imports(aac, names, timeout, tmp, tag):
    """按顺序 import 一批库，返回 (状态, 秒数)。"""
    src = tmp / ("b_%s.aardio" % tag)
    log = tmp / ("b_%s.log" % tag)
    body = "".join("import %s;\n" % n for n in names)
    src.write_text(body + '\nconsole.log("ALL_OK " + tostring(%d));\n' % len(names),
                   encoding="utf-8")
    argv = [aac, "run", str(src), "--log=%s" % log, "--no-pause"]
    t0 = time.time()
    try:
        p = subprocess.run(argv, timeout=timeout, capture_output=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        return "HANG", time.time() - t0
    dur = time.time() - t0
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if rc == 0 and "ALL_OK" in text:
        return "OK", dur
    return "ERR%s" % rc, dur


def bisect(aac, names, timeout, tmp, depth=0):
    """找出导致失败的最小库集合（逐个确认，避免漏掉多个凶手）。"""
    st, dur = try_imports(aac, names, timeout, tmp, "bis%d" % depth)
    if st == "OK":
        return []
    if len(names) == 1:
        return [(names[0], st, dur)]
    mid = len(names) // 2
    left = bisect(aac, names[:mid], timeout, tmp, depth + 1)
    # 左半干净就只查右半; 左半有问题也继续查右半(可能不止一个凶手)
    rest = bisect(aac, names[mid:], timeout, tmp, depth + 100)
    return left + rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="_hostlibs.txt")
    ap.add_argument("--aac", default=DEFAULT_AAC)
    ap.add_argument("--timeout", type=float, default=25)
    args = ap.parse_args()

    names = [x.strip() for x in pathlib.Path(args.file).read_text(
        encoding="utf-8").split(",") if x.strip()]
    print("待验证: %d 个库" % len(names))

    with tempfile.TemporaryDirectory(prefix="aacbis_") as td:
        td = pathlib.Path(td)
        st, dur = try_imports(args.aac, names, args.timeout, td, "all")
        print("全量 import: %s  %.1fs" % (st, dur))
        if st == "OK":
            print("组合没有问题，宿主挂死另有原因")
            return 0
        print("")
        print("开始二分...")
        bad = bisect(args.aac, names, args.timeout, td)
        print("")
        print("── 凶手 ──")
        for n, s, d in bad:
            print("  %-32s %-8s %.1fs" % (n, s, d))
        if bad:
            print("")
            print("从宿主里剔除后重新发布:")
            print("  aac host-del %s --rebuild" % ",".join(n for n, _, _ in bad))
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
