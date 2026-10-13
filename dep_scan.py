"""扫描真实语料库，统计"到底缺哪些库"。

和 corpus_test.py 的分工
------------------------
corpus_test.py 回答「能不能编过去」；本脚本回答「卡在哪个库」。
它只做依赖检查（--no-exe，不落 EXE），所以快、也不占磁盘，
用来决定"下一批该往宿主里预埋什么库"—— 用数据决定，而不是拍脑袋。

缺库分两类，出路完全不同：
  A. 本机 aardio 安装目录里有  -> aac host-add 一条命令补上（不用联网）
  B. 本机没有                  -> 第三方库或拼写错误，补不了

用法
----
    python dep_scan.py
    python dep_scan.py --limit 30
    python dep_scan.py --json depscan.json
"""
import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
import aacpath
DEFAULT_AAC = aacpath.find_aac()
DEFAULT_CORPUS = None   # 同上：语料库路径必须显式给出
SKIP_DIRS = {".git", ".build", "dist", "node_modules", ".svn", ".vs", "bin", "obj"}

RE_MISS = re.compile(r"宿主未预埋库:\s*([\w.]+)\s*（被\s*(.+?)\s*引用）")

# 【踩过的坑】最早这里靠匹配 aac 输出里的「标准库里没有这个库:」来判定
# "本机也没有"。后来 aac 把缺库报告改成了 A/B/C 三类，措辞全变了，
# 这条正则一个字都匹配不到 —— 于是 90 多个第三方库被统统算成
# "本机就有、能自动补"，报表看起来一片大好，实际按它去 host-add 全是空转。
# 判定"本机有没有"绝不能依赖另一条命令的输出文案，必须直接落盘查文件系统，
# 并且复用 build.py 里那份唯一的模块解析规则（库文件名可以带点）。
sys.path.insert(0, str(HERE))
from build import aardio_lib_dir, module_exists  # noqa: E402

_LIBDIR = aardio_lib_dir()


def on_disk(lib: str) -> bool:
    """本机 aardio 目录里是否真有这个库（不依赖任何命令输出）"""
    if not _LIBDIR:
        return False
    return module_exists(pathlib.Path(_LIBDIR), lib)


def find_projects(root):
    root = pathlib.Path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        has_main = "main.aardio" in filenames
        aproj = [f for f in filenames if f.lower().endswith(".aproj")]
        if has_main or aproj:
            found.append(pathlib.Path(dirpath))
    found.sort(key=lambda p: str(p).lower())
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--aac", default=DEFAULT_AAC)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    aac = pathlib.Path(args.aac)
    if not aac.is_file():
        print("找不到 aac: %s" % aac)
        return 2
    corpus = pathlib.Path(args.corpus)
    if not corpus.is_dir():
        print("找不到语料库: %s" % corpus)
        return 2

    projects = find_projects(corpus)
    if args.limit:
        projects = projects[:args.limit]
    print("语料库: %s" % corpus)
    print("待扫工程: %d 个" % len(projects))
    print("")

    # 频次: 库 -> 出现次数（一个工程内只算一次）
    freq = collections.Counter()
    # 库 -> 引用它的工程示例
    sample = {}
    # 标准库里也没有的（第三方/错字）
    notfound = collections.Counter()
    n_ok, n_err, n_other = 0, 0, 0
    t_all = time.time()

    with tempfile.TemporaryDirectory(prefix="aacdep_") as td:
        td = pathlib.Path(td)
        for idx, proj in enumerate(projects, 1):
            log = td / ("s%03d.log" % idx)
            out = td / ("s%03d" % idx)
            argv = [str(aac), "build", str(proj), "--no-exe",
                    "--out=%s" % out, "--no-pause", "--log=%s" % log]
            try:
                subprocess.run(argv, timeout=args.timeout, capture_output=True)
            except subprocess.TimeoutExpired:
                n_other += 1
                continue
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            hits = RE_MISS.findall(text)
            if not hits:
                if "依赖检查  : 通过" in text:
                    n_ok += 1
                else:
                    n_err += 1
                continue
            seen = set()
            for lib, frm in hits:
                if lib in seen:
                    continue
                seen.add(lib)
                freq[lib] += 1
                sample.setdefault(lib, str(proj))
    # 直接查文件系统, 不再看 aac 的输出文案
    notfound = collections.Counter()
    for lib in freq:
        if not on_disk(lib):
            notfound[lib] = freq[lib]

    addable = [(k, v) for k, v in freq.items() if k not in notfound]
    addable.sort(key=lambda x: -x[1])
    others = sorted(notfound.items(), key=lambda x: -x[1])

    print("用时 %.0fs" % (time.time() - t_all))
    print("依赖检查通过: %d    编译期报错: %d    其他: %d" % (n_ok, n_err, n_other))
    print("")
    print("── 可自动补的库（本机 aardio 里有，只是宿主没预埋）%d 种 ──" % len(addable))
    for k, v in addable[:40]:
        print("  %4d  %-34s  e.g. %s" % (v, k, sample[k][-58:]))
    print("")
    print("── 本机也没有（第三方库 / 拼写错误）%d 种 ──" % len(others))
    for k, v in others[:20]:
        print("  %4d  %s" % (v, k))

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps({
            "addable": [{"lib": k, "n": v, "sample": sample[k]} for k, v in addable],
            "notfound": [{"lib": k, "n": v} for k, v in others],
            "n_ok": n_ok, "n_err": n_err, "n_other": n_other,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("")
        print("明细已写入 %s" % args.json)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
