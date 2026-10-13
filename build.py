"""静默发布 aardio 工程(不弹 IDE 窗口、不误杀已存在的 IDE)

原理
----
aardio IDE 的「发布」= 给 IDE 主窗口发一条命令消息:

    User32.PostMessage(hIde, WM_COMMAND(0x0111), 0x8317 /*_IDE_ID_BUILD_PUBLISH*/, 0)

用法
----
    python build.py sync                          # 只把源码同步进 runner 工程
    python build.py all                           # 同步后发布 aac + aardioHost
    python build.py aac-runner                    # 发布单个工程(默认先 sync)
    python build.py aac-runner --out %AARDIO_HOME%\\aac.exe
    python build.py aardioHost-runner --out %AARDIO_HOME%\\aardioHost.exe
    python build.py test --timeout 240 --show     # 显示 IDE 窗口(调试)

源码是怎样进 runner 工程的
--------------------------
根目录的 aac.aardio / aardioHost.aardio 是「唯一源文件」, runner 工程
只是 IDE 发布用的壳。发布前会做一次 sync:

    1. 把 lib/aacpkg.aardio 的内容内联到 main.aardio 顶部
       (宿主是 loadcode 运行环境, import 工程库不可靠, 只能内联)
    2. 覆盖写入 <runner>/main.aardio

所以 **改完根目录的 .aardio 直接跑 build.py 即可**, 不要再手工复制文件。

与 WebexAuto/tools/build_aardio.py 的区别
-----------------------------------------
1. 按「工程名」过滤 IDE 窗口标题, 不会误抓到已打开的其他工程
2. 结束时只终止自己启动的那个 IDE 进程, 不做 taskkill /IM 全杀
3. 支持 --out 直接指定产物落点

依赖: 仅 Python 标准库 (ctypes)。
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aacpath  # 本机路径解析（开源仓库里不写死任何人的绝对路径）

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
IDE_ID_BUILD_PUBLISH = 0x8317
SW_HIDE = 0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001

HERE = pathlib.Path(__file__).resolve().parent

# aardio 安装位置与本机相关，一律交给 aacpath 解析（环境变量 → .local_paths.txt
# → PATH → 常见安装目录）。这里绝不保留作者本机的绝对路径。

# 发布前体检用的 aac（可能还没发布出新版本, 用已装的那份即可:
# 体检只是 import 一遍库, 与 aac 自身版本无关）
def _aac_exe():
    """发布前体检要用的 aac.exe（延迟解析：本机可能还没构建过产物）"""
    return aacpath.find_aac()

# 由 --no-gate 置位: 跳过发布前的 import 体检
NO_GATE = False


def log(m):
    print("[build] %s" % m, flush=True)


BEGIN_TAG = "// ===== BEGIN AUTO-INLINE: lib/aacpkg.aardio ====="
END_TAG = "// ===== END AUTO-INLINE ====="

# 根目录源文件 -> runner 工程入口
TARGETS = {
    "aac-runner": "aac.aardio",
    "aardioHost-runner": "aardioHost.aardio",
}


# ---------------- 源码同步 ----------------
def strip_inline(text: str) -> str:
    """去掉上一次内联进去的库代码, 只保留真正的源码"""
    b = text.find(BEGIN_TAG)
    if b < 0:
        return text
    e = text.find(END_TAG, b)
    if e < 0:
        return text
    return text[:b] + text[e + len(END_TAG):]


def aardio_lib_dir():
    """定位 aardio 标准库目录"""
    exe = find_aardio_exe()
    if not exe:
        return None
    for cand in (pathlib.Path(exe).parent / "lib",
                 pathlib.Path(exe).parent / "std"):
        if cand.is_dir():
            return cand
    return None


def module_exists(libdir: pathlib.Path, mod: str) -> bool:
    """按 aardio 的模块解析规则判断模块是否真实存在。

    aardio 的库文件名本身可以带点, 所以不能简单把模块名的点全换成斜杠:
        import fsys.dlg     -> lib\\fsys\\dlg.aardio
        import fsys.dlg.dir -> lib\\fsys\\dlg.dir.aardio   (末两段连成文件名!)
    通则是「前 k-1 段当目录、第 k 段起用点连成文件名」, k 从 1 试到 n。

    【踩过的坑】只按「点全换斜杠」判断时, 真实存在的 fsys.dlg.dir 被判成
    "不存在"，build.py 直接拒绝发布；而 aac 那边的 libSourcePath 又是
    按另一种布局找的 —— 两边不一致, 于是同一个库一个说有一个说没有。

    特殊情况: lib\\time\\ 这类「纯命名空间目录」里没有 _.aardio,
    只有 ole/zone/lunar 等子模块, 但 `import time` 依然成立。
    所以目录内只要含任意 .aardio 就放行, 不做过度收紧 ——
    真正的判据始终是 _bisect/findexact.py 的运行时加载测试。

    这一步不是洁癖: 曾经凭印象往宿主里写了 uuid / zip / sys.config /
    win.msgbox 等**根本不存在**的库名, IDE 发布时不报错但产物运行即卡死,
    排查代价极高。必须用文件系统硬校验拦住。
    """
    parts = mod.split(".")
    n = len(parts)

    for k in range(1, n + 1):
        d = "/".join(parts[:k - 1])
        f = ".".join(parts[k - 1:])
        base = (d + "/" + f) if d else f
        for rel in (base + ".aardio", base + "/_.aardio", base + "/main.aardio"):
            p = libdir / rel
            if p.is_file():
                return True

    # 纯命名空间目录: 各级都是目录, 且目录里有 .aardio（不要求 _.aardio）
    node = libdir
    for seg in parts:
        if not node.is_dir():
            return False
        entries = {c.name.lower(): c for c in node.iterdir()}
        node = entries.get(seg.lower())
        if node is None or not node.is_dir():
            return False
    for _ in node.rglob("*.aardio"):
        return True
    return False


def check_host_libs(text: str, libdir=None):
    """校验宿主的 import 列表与 HOST_LIBS_DECL 是否严格一致。

    这两处一旦漂移, 会出现"看起来预埋了其实没有"的诡异情况:
    build 阶段依赖检查放行, 运行时却报找不到库。
    """
    imports, order = [], []
    for m in re.finditer(r"^\s*import\s+([A-Za-z_][\w.]*)\s*;", text, re.M):
        name = m.group(1)
        if name not in imports:
            imports.append(name)
        order.append((m.start(), name))

    m = re.search(
        r'HOST_LIBS_DECL\s*=\s*"[/\*]*__HOST_LIBS__\*/([^"]*?)/\*__HOST_LIBS_END__\*/"',
        text,
    )
    if not m:
        raise RuntimeError("未找到 HOST_LIBS_DECL，能力清单无从发布")
    declared = [x for x in m.group(1).split(",") if x]

    duped = sorted({n for n, c in collections.Counter(n for _, n in order).items()
                    if c > 1})
    if duped:
        raise RuntimeError(
            "宿主源码里有重复的 import（多半是早期 host-add 的 --rebuild 静默失败导致的重复追加）:\n"
            "  %s\n"
            "  重复 import 没有语义差别，但会让哨兵清单失去意义。"
            "执行「aac host-add <其中任意一个库名>」会自动清理。" % ", ".join(duped)
        )

    missing = [x for x in imports if x not in declared]
    extra = [x for x in declared if x not in imports]
    if missing or extra:
        msg = ["宿主预埋库清单不一致："]
        if missing:
            msg.append("  import 了但未声明: %s" % ", ".join(missing))
        if extra:
            msg.append("  声明了但未 import: %s" % ", ".join(extra))
        msg.append("  请同步 aardioHost.aardio 的 import 列表与 HOST_LIBS_DECL")
        raise RuntimeError("\n".join(msg))

    # 位置校验: import 必须出现在 HOST_LIBS_DECL 之前,
    # 否则顶层语句执行到 return 时 DECL 还没赋值, 会取到 null
    for pos, name in order:
        if pos > m.start():
            raise RuntimeError(
                "import %s 位于 HOST_LIBS_DECL 之后，运行时会取不到能力清单" % name
            )
    # 存在性校验: 库名必须在 aardio 标准库里真实存在。
    # 不存在的库名编译期不报错, 发布后运行直接卡死, 必须在这里拦死。
    if libdir:
        ghost = [x for x in imports if not module_exists(libdir, x)]
        if ghost:
            raise RuntimeError(
                "以下 import 的库在 %s 下不存在：%s\n"
                "  aardio 对不存在的 import 不做编译期报错，\n"
                "  而是发布出一个运行即卡死的 EXE —— 必须在此拦住。\n"
                "  请用 _bisect/findexact.py 扫描出实际存在的模块名。"
                % (libdir, ", ".join(ghost)))
    return declared


HOST_CRITICAL_GLOBALS = [
    "loadcode", "dumpcode", "string", "console", "io", "table",
    "dotNet", "type", "tostring", "tonumber", "PKG", "loadModule",
    "error", "pcall",
]


def lib_overrides_globals(libdir, mod):
    """库顶层是否给宿主赖以生存的全局名赋过值。

    与 aac.aardio 里的 HOST_CRITICAL_GLOBALS 是同一条规则的两处实现,
    改一处必须改另一处 —— 一边靠它拒绝补库, 一边靠它在发布前兜底。
    """
    p = None
    parts = mod.split(".")
    for k in range(1, len(parts) + 1):
        d = "/".join(parts[:k - 1])
        f = ".".join(parts[k - 1:])
        base = (d + "/" + f) if d else f
        for rel in (base + ".aardio", base + "/_.aardio", base + "/main.aardio"):
            c = libdir / rel
            if c.is_file():
                p = c
                break
        if p:
            break
    if not p:
        return []
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    pat = re.compile(r"^\s*(%s)\s*=" % "|".join(HOST_CRITICAL_GLOBALS), re.M)
    return sorted(set(pat.findall(src)))


def gate_host_imports(libs, timeout=15.0, verbose=True):
    """发布前体检: 逐个 import 一遍, 拦住"一 import 就挂"的库。

    【为什么必须在发布前拦】
    宿主是启动时全量 import 的。塞进一个 import 时有重副作用的库,
    后果不是"这个库用不了", 而是**每一个产物都起不来** ——
    java.jre.v8 那次就是: 预埋后所有 EXE 卡死在启动阶段, 日志一行都没有,
    排查成本极高（要二分、要重新发布）。
    单独看库文件看不出问题, 必须真跑一遍 import。

    【为什么放在 build.py 而不是 aac 里】
    aardio 的 io.popen 无法给子进程设超时, 挂死的库会把自己也带挂。
    Python 这边可以带 timeout 强杀, 才能做到"体检不把自己搭进去"。
    """
    import lib_probe
    import json

    # 缓存: 体检要真跑一遍 import, 几百个库全跑一遍要一两分钟。
    # 结论是稳定的(同一个 aardio 版本下), 没必要每次发布都重跑。
    cache_path = HERE / ".gate_cache.json"
    cache = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # 静态检查只做【提示】, 不当硬门禁。
    # 【为什么不能拦死】库文件里 `console = {...}` / `dotNet = {...}` 往往只是
    # 在定义自己的命名空间, 而 win.ui / dotNet / web.form 里也有 `loadcode =`;
    # 它们全在 160 库基线上、工作正常。也就是说「顶层给关键全局名赋值」
    # 既不能证明有害也不能证明无害 —— 拿它拦发布只会误伤。
    # 真正的判据是发布后的端到端冒烟(见 smoke_test_host)。
    libdir = aardio_lib_dir()
    if libdir:
        clash = [(n, lib_overrides_globals(libdir, n)) for n in libs]
        clash = [(n, g) for n, g in clash if g]
        if clash and verbose:
            log("提示: %d 个预埋库里有顶层全局名赋值（多半是定义自身命名空间）: %s"
                % (len(clash), ", ".join("%s->%s" % (n, "/".join(g)) for n, g in clash[:6])
                   + (" ..." if len(clash) > 6 else "")))

    todo = [n for n in libs if cache.get(n) != "OK"]
    probe = _aac_exe()
    if not probe and todo:
        # 没有可用的 aac 就不做体检 —— 但不准假装通过：明确告诉用户少了一道闸
        log("[警告] 找不到 aac.exe，跳过发布前体检（本次发布少一道防线）")
        return None
    if verbose and todo:
        log("发布前体检: %d 个库（其中 %d 个有缓存可跳过）" % (len(todo), len(libs) - len(todo)))

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aacgate_"))
    bad = []
    try:
        for n in todo:
            st, dur, tail = lib_probe.probe_one(probe, n, timeout, tmp)
            cache[n] = st
            if st != "OK":
                bad.append((n, st, dur))
                if verbose:
                    log("  [体检] %-32s %-8s %.1fs  <<< 不能预埋" % (n, st, dur))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except Exception:
            pass

    if bad:
        raise RuntimeError(
            "以下库在 import 阶段就无法通过（%s），预埋后会让**每个产物**起不来:\n  %s\n"
            "  请用 aac host-del %s 把它们从宿主里剔除后重新发布。\n"
            "  确认必须预埋请用 --no-gate 跳过本检查（后果自负）。"
            % ("挂死" if any(b[1] == "HANG" for b in bad) else "报错",
               "\n  ".join("%s (%s, %.1fs)" % b for b in bad),
               ",".join(b[0] for b in bad)))
    return True


def smoke_test_host(host_exe, timeout=60):
    """发布后立即冒烟: 编一个 hello world 并真跑一遍。

    【这是整套防线里唯一可信的一关】
    预埋库的所有静态特征都证明不了安全性:
      - 单独 import 一遍? 正常(宿主崩的时候每个库单独 import 都是好的)
      - 顶层改写全局名? 误报一大片(160 库基线上就有 win.ui/dotNet 改写 loadcode)
      - 裸宿主能跑? 更不代表 —— 它压根不会走到 loadcode 那一步
    只有「打出一个真实 EXE 并运行」才能证明预埋是安全的。
    代价不到 3 秒, 而漏过一次的代价是: 每个产物静默失败, 退出码 -1,
    日志一个字都没有, 要二分 + 反复发布才能定位。
    """
    import subprocess as sp
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="aacsmoke_"))
    try:
        proj = tmp / "proj"
        proj.mkdir()
        (proj / "main.aardio").write_text(
            'import console;\nconsole.log("SMOKE_OK");\n', encoding="utf-8")
        _p = _aac_exe()
        aac = pathlib.Path(_p) if _p else None
        if not aac or not aac.is_file():
            log("冒烟跳过: 找不到可用的 aac.exe（设 AAC_EXE 或先执行 build.py aac-runner）")
            return True
            return True
        r = sp.run([str(aac), "build", str(proj), "--host=%s" % host_exe,
                    "--out=%s" % (tmp / "smoke.exe"), "--no-pause",
                    "--log=%s" % (tmp / "build.log")],
                   timeout=120, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError("冒烟: 编译失败\n%s" % _tail(tmp / "build.log"))
        exe = tmp / "smoke.exe"
        if not exe.is_file():
            raise RuntimeError("冒烟: 编译报成功却没有 EXE")
        run_log = tmp / "run.log"
        try:
            p = sp.run([str(exe), "--log=%s" % run_log], timeout=timeout,
                       capture_output=True)
        except sp.TimeoutExpired:
            raise RuntimeError("冒烟: 产物运行超过 %ss 未结束（启动期挂死）" % timeout)
        text = run_log.read_text(encoding="utf-8", errors="replace") if run_log.is_file() else ""
        if p.returncode != 0:
            raise RuntimeError(
                "冒烟: 产物运行失败 rc=%s\n%s" % (p.returncode, text[-1500:]))
        if "SMOKE_OK" not in text:
            raise RuntimeError("冒烟: 产物没跑出预期输出\n%s" % text[-1500:])
        log("冒烟通过: EXE 能起来并正常输出（%d 字节）" % exe.stat().st_size)
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _tail(p, n=1500):
    try:
        return pathlib.Path(p).read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def sync(verbose=True):
    libdir = aardio_lib_dir()
    if libdir and verbose:
        log("标准库: %s" % libdir)
    lib = (HERE / "lib" / "aacpkg.aardio").read_text(encoding="utf-8")
    block = "%s\n%s\n%s\n" % (BEGIN_TAG, lib.rstrip("\n"), END_TAG)
    for runner, src_name in TARGETS.items():
        src = (HERE / src_name).read_text(encoding="utf-8")
        src = strip_inline(src).lstrip("\n")
        if src_name == "aardioHost.aardio":
            declared = check_host_libs(src, libdir)
            if verbose:
                log("宿主能力清单校验通过：%d 个预埋库" % len(declared))
            if not NO_GATE:
                gate_host_imports(declared, verbose=verbose)
        main = HERE / runner / "main.aardio"
        main.write_text(block + src, encoding="utf-8")
        if verbose:
            log("同步 %s/main.aardio  <-  %s + lib/aacpkg.aardio" % (runner, src_name))
    return 0


# ---------------- Windows 辅助 ----------------
def find_aardio_exe():
    return aacpath.find_aardio_exe()


def enum_windows():
    out = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, _l):
        out.append(h)
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def pid_of(hwnd):
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def image_name_of(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def title_of(hwnd):
    n = u32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_ide_hwnd(exe_path, pid_hint=None, title_hint=""):
    """优先命中: 指定 PID + 含 MDIClient 的顶层窗口; 否则按标题关键词兜底"""
    target = os.path.basename(exe_path).lower()
    wins = []
    for h in enum_windows():
        pid = pid_of(h)
        if not pid:
            continue
        if pid_hint and pid != pid_hint:
            continue
        name = image_name_of(pid)
        if name and os.path.basename(name).lower() == target:
            wins.append(h)
    if not wins:
        return None
    if title_hint:
        for h in wins:
            if title_hint.lower() in title_of(h).lower():
                return h
    for h in wins:
        if u32.FindWindowExW(h, None, "MDIClient", None):
            return h
    return wins[0]


def other_visible_windows(main_hwnd, pid):
    res = []
    for h in enum_windows():
        if h == main_hwnd or pid_of(h) != pid:
            continue
        if u32.IsWindowVisible(h):
            res.append(h)
    return res


def terminate(pid):
    """强杀进程"""
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        k32.TerminateProcess(h, 1)
    finally:
        k32.CloseHandle(h)


def close_ide(pid, graceful_wait=6.0):
    """关闭 IDE。先 WM_CLOSE 优雅退出, 超时再 TerminateProcess 强杀。

    为什么必须先 WM_CLOSE: aardio IDE 在发布过程中会写临时文件与工程
    配置(USR.CFG 等), 直接 TerminateProcess 有概率让工程目录留下锁文件,
    导致下一次发布弹出「工程已被打开」对话框。
    """
    # 1) 优雅: 给该进程所有顶层窗口发 WM_CLOSE
    try:
        for h in enum_windows():
            if pid_of(h) == pid:
                u32.PostMessageW(h, WM_CLOSE, 0, 0)
    except Exception:
        pass

    t0 = time.time()
    while time.time() - t0 < graceful_wait:
        if not pid_alive(pid):
            log("IDE 已正常退出 (%.1fs)" % (time.time() - t0))
            return True
        time.sleep(0.3)

    # 2) 强杀
    terminate(pid)
    t1 = time.time()
    while time.time() - t1 < 5:
        if not pid_alive(pid):
            log("IDE 已强制结束 (强杀耗时 %.1fs)" % (time.time() - t1))
            return True
        time.sleep(0.3)
    log("[警告] IDE PID %d 仍存活，可能需要手动结束" % pid)
    return False


def pid_alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wt.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return False
    finally:
        k32.CloseHandle(h)


def kill_stale_ides(exe_path, keep_pids=()):
    """清掉本工具此前泄漏的 IDE 进程。

    多次中断/异常后可能残留若干个隐藏的 aardio.exe —— 它们不占窗口但
    持续吃内存, 累积起来会把机器拖垮。每次发布前顺手清理。
    """
    target = os.path.basename(exe_path).lower()
    killed = []
    for p in _all_processes():
        if p["pid"] in keep_pids:
            continue
        name = os.path.basename(p["image"] or "").lower()
        if name == target and p["pid"] != os.getpid():
            terminate(p["pid"])
            killed.append(p["pid"])
    return killed


def _all_processes():
    """枚举进程 (PID + 映像路径), 仅用 win32 API, 不依赖 psutil/tasklist"""
    out = []
    try:
        ctypes.windll.psapi  # noqa: F401
    except Exception:
        return out
    EnumProcesses = ctypes.windll.psapi.EnumProcesses
    EnumProcessModules = ctypes.windll.psapi.EnumProcessModules
    GetModuleFileNameExW = ctypes.windll.psapi.GetModuleFileNameExW
    arr = (wt.DWORD * 4096)()
    need = wt.DWORD()
    if not EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(need)):
        return out
    n = min(need.value // ctypes.sizeof(wt.DWORD), 4096)
    for i in range(n):
        pid = arr[i]
        if not pid:
            continue
        out.append({"pid": pid, "image": image_name_of(pid)})
    return out


# ---------------- 主流程 ----------------
_DEPLOY_WARNED = False


def warn_foreign_deploy_dir(deploy):
    """自定义部署目录里没有 aardio 标准库时，提前把后果讲清楚

    aac 运行时只从「自己所在目录\\lib」找标准库。用 --deploy-dir 拷到别处后，
    那个目录十有八九没有 lib\\ —— 表面上宿主能起来、EXE 也照样能发布，
    但**缺库判定会全线失灵**：真正的自带库被判成"第三方库"，
    host-add 对致命库 / 重副作用库的拦截也没了依据。

    这个失败模式不报错、只给错的结论（实测把已知致命库 ide 误报成第三方库），
    所以只能由我们在发布这一步 warn 出来。每轮只提示一次。
    """
    global _DEPLOY_WARNED
    if _DEPLOY_WARNED or not deploy:
        return
    _DEPLOY_WARNED = True
    ae = aacpath.find_aardio_exe()
    if not ae:
        return
    try:
        same = (os.path.normcase(os.path.abspath(deploy)) ==
                os.path.normcase(os.path.abspath(str(pathlib.Path(ae).parent))))
    except Exception:
        return
    if same or (pathlib.Path(deploy) / "lib").is_dir():
        return
    log("[警告] 部署目录里没有 aardio 标准库: %s\\lib" % deploy)
    log("       aac 只从「自身所在目录\\lib」找标准库。装到 aardio 安装目录之外时，")
    log("       缺库判定会给出错误结论（自带库被当成第三方库，A/B/C 分类随之失效，")
    log("       致命库与重副作用库的拦截也不再可靠），而且全程不报错。")
    log("       二选一：去掉 --deploy-dir 装到 aardio 安装目录；")
    log("              或把那个目录下的 lib\\ 复制/联接过来。")


def write_local_hint(install_dir):
    """在 aac.exe 的安装目录写一份 aac.local.txt，告诉它源码仓库在哪。

    【为什么要有这个文件】开源出去的仓库里不能写死任何人的绝对路径，
    但用户 clone 的目录又千差万别 —— aac.exe 放在 aardio 安装目录下，
    光靠"从 EXE 所在目录往上找"是找不到仓库的。
    于是把本机专属信息写在这个**不属于仓库**的文件里：
    仓库零个人信息，`aac host-add` 在任意目录敲也能找到宿主源码。
    """
    p = pathlib.Path(install_dir) / "aac.local.txt"
    try:
        p.write_text(
            "# 自动生成，勿手工修改（由 build.py 发布时写入）\n"
            "# 作用：告诉已安装的 aac.exe 本工程的源码仓库在哪里。\n"
            "# 本文件不属于版本库 —— 仓库里不该出现任何人的本机绝对路径。\n"
            "AAC_HOME=%s\n" % HERE,
            encoding="utf-8")
        log("已写入本机提示: %s" % p)
    except Exception as e:
        log("[提示] 写 aac.local.txt 失败（不影响产物，只影响"
            " `aac host-add` 能否在任意目录找到宿主源码）: %s" % e)


def publish(proj, args, out=""):
    """发布单个工程, 返回 0 表示成功"""
    exe = find_aardio_exe()
    if not exe:
        log("未找到 aardio.exe，请设置环境变量 AARDIO_EXE")
        return 2

    p = pathlib.Path(proj)
    if not p.is_absolute():
        p = HERE / p
    aproj = p if p.is_file() else (p / "default.aproj")
    if not aproj.is_file():
        log("未找到工程文件: %s" % aproj)
        return 2
    proj_dir = aproj.parent

    text = aproj.read_text(encoding="utf-8-sig")
    m_out = re.search(r'\boutput\s*=\s*"([^"]*)"', text)
    m_dir = re.search(r'publishDir\s*=\s*"([^"]*)"', text)
    m_name = re.search(r'\bname\s*=\s*"([^"]*)"', text)
    if not m_out:
        log("aproj 未指定 output")
        return 2
    out_name = m_out.group(1)
    proj_name = m_name.group(1) if m_name else proj_dir.name
    dist = proj_dir / (m_dir.group(1).strip("/\\") if m_dir else "dist")
    target = dist / out_name
    log("IDE   : %s" % exe)
    log("工程  : %s" % aproj)
    log("产物  : %s" % target)

    if target.is_file():
        target.unlink()

    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = SW_HIDE

    # 【为什么要在启动前先记账】IDE 会孵子进程/二次启动, 光关掉自己 spawn 的
    # 那个 PID 不够 —— 剩下的要等"下一次"构建才被扫到, 最后那次构建泄漏的就
    # 永远躺在后台。所以这里先把调用前已存在的 IDE 记下来:
    # 那多半是**用户自己打开**的编辑器, 只保护它们; 其余一律视为本次引入。
    def _ide_pids():
        target = os.path.basename(exe).lower()
        return {p["pid"] for p in _all_processes()
                if os.path.basename(p["image"] or "").lower() == target
                and p["pid"] != os.getpid()}

    user_ide_pids = _ide_pids()

    # 发布前先清掉历史上泄漏的 IDE（异常中断会留下吃内存的隐藏实例）
    for p in kill_stale_ides(exe, keep_pids=user_ide_pids):
        log("清理残留 IDE 进程 PID=%d" % p)

    proc = subprocess.Popen([exe, str(aproj)], startupinfo=si)
    my_pid = proc.pid
    log("IDE PID: %d" % my_pid)

    # 无论后续任何分支如何退出, IDE 都必须被关掉。
    # 曾经因为没有 finally 保护, 异常路径会把 IDE 留在后台,
    # 多次重试后累积到十几个实例直接拖垮机器。
    try:
        return _publish_inner(proj, args, out, exe, aproj, proj_dir,
                              target, dist, proj_name, my_pid, t0=time.time())
    finally:
        if not args.keep_ide:
            log("关闭 IDE PID=%d ..." % my_pid)
            if not close_ide(my_pid):
                log("[严重] IDE 未能关闭，请手动检查 PID %d" % my_pid)
            # 兜底: 关闭 my_pid 之后再复查一遍。
            # 【实测】发布过程中 IDE 会孵出子进程（clangwire 等辅助进程），
            # 只认 my_pid 时会漏 —— 今天就有一次：build.py 报告"已正常退出"，
            # 但紧接着 tasklist 里还有一个同名的 IDE 在跑。用户的硬要求是
            # "用完必须关干净"，所以这一步不能省。
            for p in kill_stale_ides(exe, keep_pids=user_ide_pids):
                log("清理本轮孵出的 IDE PID=%d" % p)
        else:
            log("--keep-ide: 保留 IDE 进程 PID=%d" % my_pid)


def _publish_inner(proj, args, out, exe, aproj, proj_dir, target, dist,
                   proj_name, my_pid, t0):
    hwnd = None
    while time.time() - t0 < 60:
        hwnd = find_ide_hwnd(exe, pid_hint=my_pid, title_hint=proj_name)
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        # 注意: 这里不必 terminate, 外层 finally 统一关, 避免重复杀
        log("未找到本进程启动的 IDE 主窗口")
        return 3
    log("主窗口: 0x%X 标题=%r" % (hwnd, title_of(hwnd)))

    if not args.show:
        u32.ShowWindow(hwnd, SW_HIDE)

    t1 = time.time()
    while time.time() - t1 < 40:
        if proj_name and proj_name in title_of(hwnd):
            log("工程已加载: %r" % title_of(hwnd))
            break
        for h in other_visible_windows(hwnd, my_pid):
            u32.PostMessageW(h, WM_CLOSE, 0, 0)
        time.sleep(0.5)
    time.sleep(2)

    u32.PostMessageW(hwnd, WM_COMMAND, IDE_ID_BUILD_PUBLISH, 0)
    log("已发送 WM_COMMAND 0x8317 (发布)")

    err = None
    seen = []
    stable, last = 0, -1
    t2 = time.time()
    while time.time() - t2 < args.timeout:
        for h in other_visible_windows(hwnd, my_pid):
            ti = title_of(h)
            if ti and ti not in seen:
                seen.append(ti)
                log("弹窗: %r" % ti)
            if ("失败" in ti) or ("错误" in ti) or ("Error" in ti):
                err = "发布失败对话框: %r" % ti
            u32.PostMessageW(h, WM_CLOSE, 0, 0)
        if err:
            break
        if target.is_file():
            size = target.stat().st_size
            if size > 0 and size == last:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last = size
        time.sleep(1)

    # 关闭 IDE 前先等产物稳定不再增长: 过早杀进程会把写了一半的 EXE
    # 留在磁盘上, 之后运行表现为「无原因卡死」, 极难关联到发布流程。
    if target.is_file():
        lastsz, stable = -1, 0
        for _ in range(20):
            sz = target.stat().st_size if target.is_file() else -1
            if sz > 0 and sz == lastsz:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            lastsz = sz
            time.sleep(0.5)

    # IDE 的关闭统一交给外层 finally, 此处不再处理

    if err:
        log(err)
        return 4
    if not target.is_file():
        log("超时: 未生成 %s" % target)
        return 5

    log("发布成功: %s (%d bytes, 用时 %.1fs)" % (target, target.stat().st_size, time.time() - t0))
    if out:
        dst = pathlib.Path(out)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # 先把旧宿主留个后路: 冒烟不过要能立刻回滚,
        # 否则一次失败的发布就把工具链整体打瘫, 连回退都要再弹一次 IDE。
        bak = None
        if dst.is_file() and proj == "aardioHost-runner":
            bak = dst.with_suffix(dst.suffix + ".bak")
            shutil.copy2(dst, bak)
        shutil.copy2(target, dst)
        log("已拷贝: %s" % dst)
        write_local_hint(dst.parent)

        if proj == "aardioHost-runner" and not args.no_gate:
            try:
                smoke_test_host(str(dst))
            except Exception as e:
                if bak and bak.is_file():
                    shutil.copy2(bak, dst)
                    log("[严重] 冒烟未通过，已回滚宿主到发布前的版本: %s" % dst)
                log("[严重] %s" % e)
                log("[严重] 请用 aac host-del 剔除可疑库后重新发布；"
                    "确需带病发布请加 --no-gate")
                return 6
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proj", nargs="?", default="all",
                    help="工程目录名或 *.aproj 路径; sync=只同步源码; all=同步并发布 aac + aardioHost")
    ap.add_argument("--out", default="", help="额外把产物拷贝到该路径(仅单个工程时有效)")
    ap.add_argument("--deploy-dir",
                    default=os.environ.get("AAC_DEPLOY_DIR", ""),
                    help="all 模式下产物的落点目录（不给出则拷到 aardio 安装目录下，"
                         "环境变量 AAC_DEPLOY_DIR 也能设置）")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--show", action="store_true", help="不隐藏 IDE 窗口(调试)")
    ap.add_argument("--keep-ide", action="store_true",
                    help="发布后保留 IDE 进程(默认必定关闭)")
    ap.add_argument("--no-sync", action="store_true", help="跳过源码同步")
    ap.add_argument("--no-gate", action="store_true",
                    help="跳过发布前的 import 体检(不推荐: 挂死的库会让每个产物起不来)")
    args = ap.parse_args()

    global NO_GATE
    NO_GATE = args.no_gate

    if args.proj == "sync":
        return sync()

    if args.proj == "all":
        targets = ["aac-runner", "aardioHost-runner"]
        if args.out:
            log("all 模式忽略 --out, 产物统一落到 %s" % args.deploy_dir)
    else:
        targets = [args.proj]

    if not args.no_sync:
        sync()

    rc = 0
    # all 模式的默认落点 = aardio 安装目录（aac 运行时就在那儿找自己依赖的宿主/库）。
    # 源码里不写死任何人的盘符：给不出就让 publish 跳过拷贝并明确提示。
    deploy = args.deploy_dir
    if not deploy:
        _ae = aacpath.find_aardio_exe()
        deploy = str(pathlib.Path(_ae).parent) if _ae else ""
    warn_foreign_deploy_dir(deploy)

    for t in targets:
        out = ""
        if len(targets) == 1:
            out = args.out
        elif deploy:
            exe_name = (HERE / t / "default.aproj")
            name = re.search(r'output\s*=\s*"([^"]*)"', exe_name.read_text(encoding="utf-8-sig"))
            if name:
                out = str(pathlib.Path(deploy) / name.group(1))
        else:
            log("[提示] 未指定 --deploy-dir 且找不到 aardio 安装目录，"
                "all 模式只保留 %s/dist 下的产物（设 AARDIO_EXE 或 AAC_DEPLOY_DIR 可自动安装）" % t)
        r = publish(t, args, out)
        if r and not rc:
            rc = r
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
