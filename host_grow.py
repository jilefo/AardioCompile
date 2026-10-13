# -*- coding: utf-8 -*-
"""
host_grow.py —— 宿主预埋库的"渐进扩容"工具

为什么不能一次性把 100 多个库塞进宿主:
  曾经一次性加到 275 个, 编译、解包、自检全都正常, 唯独产物 EXE 起不来:
  退出码 -1、日志一个字都没有。事后证明预埋库里混进了会在 import 期
  把进程搞死的库(java.jre.v8 导入即挂、inet.file 导入即错), 而**任何静态
  特征都预测不了**这件事——单独 import 是好的、组合 import 也是好的、
  裸宿主能跑、aac info 的 CRC 也是对的。

所以扩容只能走"加一批 → 真发布 → 打真实 EXE 并运行"的闭环:
  - 每批通过才落盘, 失败立刻回滚源码
  - 失败时对批内逐个二分, 定位到具体库名并记进 blacklist.txt
  - 全过程由 build.py 保证 IDE 必定关闭

用法:
  python host_grow.py                 # 从 pending_libs.txt 分批扩容
  python host_grow.py --batch 5       # 每批 5 个
  python host_grow.py --limit 30      # 最多处理 30 个
  python host_grow.py --only A,B,C    # 只处理指定库
"""
import argparse
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).parent

sys.path.insert(0, str(HERE))
import aacpath
SRC = HERE / "aardioHost.aardio"
PENDING = HERE / "pending_libs.txt"
BLACK = HERE / "blacklist.txt"
ADDED = HERE / "added_libs.txt"
HOST_OUT = None   # 宿主 EXE 落点：由命令行的 --out 指定，别写死在仓库里

BEGIN_TAG = "// ===== BEGIN AUTO-INLINE"


def log(m):
    print("[grow] %s" % m, flush=True)


def read_libs():
    """读出宿主源码里当前的 import 列表（跳过被内联进去的库代码）"""
    lines = SRC.read_text(encoding="utf-8").split("\n")
    out = []
    for l in lines:
        if l.startswith(BEGIN_TAG):
            break
        if l.startswith("import "):
            out.append(l[len("import "):].rstrip(";"))
    return out


def write_libs(libs):
    """重写 import 区块 + HOST_LIBS_DECL，两者严格一致"""
    lines = SRC.read_text(encoding="utf-8").split("\n")
    i0 = next(i for i, l in enumerate(lines) if l.startswith("import "))
    idecl = next(i for i, l in enumerate(lines) if l.startswith("HOST_LIBS_DECL"))
    # 宿主能力清单那段注释紧跟在 import 区块之后，保留它
    icomment = idecl
    while icomment - 1 > i0 and (
            lines[icomment - 1].startswith("//") or lines[icomment - 1].strip() == ""):
        icomment -= 1
    block = ["import %s;" % x for x in libs]
    new = lines[:i0] + block + lines[icomment:idecl] + [
        'HOST_LIBS_DECL = "/*__HOST_LIBS__*/%s/*__HOST_LIBS_END__*/";' % ",".join(libs)
    ] + lines[idecl + 1:]
    SRC.write_text("\n".join(new), encoding="utf-8")


def publish(tag=""):
    """发布并冒烟。build.py 内部自带冒烟失败回滚，返回码 6 = 冒烟没过"""
    t = time.time()
    r = subprocess.run(
        [sys.executable, "build.py", "aardioHost-runner", "--out", HOST_OUT],
        cwd=str(HERE), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900)
    ok = (r.returncode == 0)
    tail = ((r.stdout or "") + (r.stderr or "")).strip().split("\n")
    for line in tail[-4:]:
        log("   | " + line.strip())
    log("%s %s (%.1fs)" % ("发布通过" if ok else "发布失败", tag, time.time() - t))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    base = read_libs()
    log("起始预埋库: %d" % len(base))

    if args.only:
        pending = [x.strip() for x in args.only.split(",") if x.strip()]
    else:
        pending = [x.strip() for x in PENDING.read_text(encoding="utf-8").split("\n")
                   if x.strip()]
    pending = [x for x in pending if x not in base]
    if args.limit:
        pending = pending[:args.limit]
    log("待补: %d" % len(pending))

    black = []
    if BLACK.is_file():
        black = [x.strip() for x in BLACK.read_text(encoding="utf-8").split("\n")
                 if x.strip()]
    added = []

    i = 0
    while i < len(pending):
        batch = pending[i:i + args.batch]
        i += args.batch
        batch = [x for x in batch if x not in black]
        if not batch:
            continue

        write_libs(base + batch)
        if publish("+%s" % ",".join(batch)):
            base = base + batch
            added.extend(batch)
            _append(ADDED, batch)
            continue

        # 整批失败: 批内逐个试，定位到具体库
        log("整批失败，批内逐个定位: %s" % ",".join(batch))
        for one in batch:
            write_libs(base + [one])
            if publish("+%s" % one):
                base = base + [one]
                added.append(one)
                _append(ADDED, [one])
            else:
                black.append(one)
                log("[剔除] %s 会让产物起不来" % one)
        # 逐个试完再把本批通过的集合起来复验一次（防交互性问题）
        survivors = [x for x in batch if x not in black]
        if len(survivors) > 1:
            write_libs(base)
            log("复验本批幸存者交互: %s" % ",".join(survivors))
            if not publish("复验"):
                log("[严重] 幸存者组合后仍失败，逐个回退")
                for one in reversed(survivors):
                    base = [x for x in base if x != one]
                    black.append(one)
                    write_libs(base)
                    if publish("回退-%s" % one):
                        break

    write_libs(base)
    _append(BLACK, black, dedup=True)
    log("最终预埋库: %d（新增 %d，剔除 %d）" % (len(base), len(added), len(black)))
    if black:
        log("黑名单: %s" % ", ".join(black))
    return 0


def _append(path, items, dedup=False):
    if not items:
        return
    old = []
    if path.is_file():
        old = [x.strip() for x in path.read_text(encoding="utf-8").split("\n")
               if x.strip()]
    if dedup:
        seen = set(old)
        items = [x for x in items if x not in seen]
    path.write_text("\n".join(old + items) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
