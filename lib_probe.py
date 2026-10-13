"""逐个 import 候选库，找出「一 import 就出事」的那些。

为什么需要它
------------
宿主是启动时全量 import 的。往里塞一个 import 时有重副作用的库,
结果不是"这个库用不了", 而是**每一个产物都起不来** ——
winex.caret 那次就是: 预埋后所有 EXE 卡死在启动阶段, 日志一行都没有。
补库之前必须先体检, 而且是**零 IDE 弹窗**地体检。

原理: aac run 会用 aardio 运行时执行脚本, 且能从磁盘加载未预埋的库,
所以逐个 `import X` 跑一遍就能提前知道它在启动期的代价。
宿主真正的加载环境与之等价(都是发布的独立 EXE + 同一套标准库)。

用法
----
    python lib_probe.py fsys.config fsys.dlg ...
    python lib_probe.py --file _libs.txt
    python lib_probe.py --file _libs.txt --timeout 15 --json probe.json
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aacpath
import json
import pathlib
import subprocess
import sys
import tempfile
import time

DEFAULT_AAC = aacpath.find_aac()


def probe_one(aac, name, timeout, tmp):
    src = tmp / (name.replace(".", "_") + ".aardio")
    log = tmp / (name.replace(".", "_") + ".log")
    src.write_text('import %s;\nconsole.log("PROBE_OK");\n' % name,
                   encoding="utf-8")
    argv = [aac, "run", str(src), "--log=%s" % log, "--no-pause"]
    t0 = time.time()
    try:
        p = subprocess.run(argv, timeout=timeout, capture_output=True)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = "HANG"
    dur = time.time() - t0
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if rc == "HANG":
        status = "HANG"
    elif rc == 0 and "PROBE_OK" in text:
        status = "OK"
    elif rc == 0:
        status = "SILENT"     # 退出 0 但没跑到我们的输出: 库里 exit 了
    else:
        status = "ERR%s" % rc
    return status, round(dur, 2), (text.strip().splitlines() or [""])[-1][:150]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file", default="", help="逗号分隔的库名文件")
    ap.add_argument("--aac", default=DEFAULT_AAC)
    ap.add_argument("--timeout", type=float, default=15)
    ap.add_argument("--slow", type=float, default=1.5,
                    help="超过这个秒数就标记为慢(启动期代价高)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [x for x in pathlib.Path(args.file).read_text(
            encoding="utf-8").split(",") if x.strip()]
    names = [n.strip() for n in names if n.strip()]
    if not names:
        print("没有要探测的库名")
        return 2

    print("探测 %d 个库（单库超时 %ss，慢阈值 %ss）" % (len(names), args.timeout, args.slow))
    print("")
    rows = []
    with tempfile.TemporaryDirectory(prefix="aacprobe_") as td:
        td = pathlib.Path(td)
        for i, n in enumerate(names, 1):
            st, dur, tail = probe_one(args.aac, n, args.timeout, td)
            rows.append({"lib": n, "status": st, "sec": dur, "tail": tail})
            flag = ""
            if st != "OK":
                flag = "   <<< 不能预埋"
            elif dur >= args.slow:
                flag = "   <<< 慢"
            print("  [%3d/%3d] %-32s %-8s %6.2fs%s" % (i, len(names), n, st, dur, flag))

    bad = [r for r in rows if r["status"] != "OK"]
    slow = [r for r in rows if r["status"] == "OK" and r["sec"] >= args.slow]
    print("")
    print("── 汇总 ──")
    print("  可用   %d" % (len(rows) - len(bad)))
    print("  不可用 %d  %s" % (len(bad), ", ".join(r["lib"] for r in bad) or "-"))
    print("  偏慢   %d  %s" % (len(slow), ", ".join(
        "%s(%.1fs)" % (r["lib"], r["sec"]) for r in slow) or "-"))

    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("明细已写入 %s" % args.json)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
