"""aac 回归测试

要点
----
aac 的 console.log 走 WriteConsoleB 直写控制台句柄, 用 subprocess 重定向
stdout 什么都拿不到。因此每条命令都带 --log=<文件>, 断言时读日志文件。

另外所有命令都必须带 --no-pause, 否则结尾 console.pause() 在无 stdin 时
会永久挂起(表现为测试卡死)。

用法
----
    python run_tests.py                       # 全部用例
    python run_tests.py --aac %AARDIO_HOME%\\aac.exe
    python run_tests.py -k build              # 只跑名字含 build 的用例
"""
import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
import aacpath
DEFAULT_AAC = aacpath.find_aac()   # 环境变量 / 本机提示 / 常见安装目录
OUT = HERE / "tests" / "out"

# 多模块测试工程（含 .aproj 与 lib/ 子目录的那个)。
# 【为什么单独拎出来】它早先叫 ./test，和 ./tests 并列，名字只差一个字母：
# 外人根本分不清哪个才是夹具目录。开源前统一收进 tests/fixtures/ 按用途命名。
TESTPROJ = HERE / "tests" / "fixtures" / "multimod"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


class Ctx:
    def __init__(self, aac):
        self.aac = aac
        self.t0 = time.time()

    def run(self, *args, timeout=180, env=None):
        """运行 aac, 返回 (rc, 日志内容)

        注意: --log 必须插在 "--" 之前。
        "--" 的语义是「之后一律原样透传给脚本」, 工具自身的选项
        放在它后面不会生效 —— 这曾让 exec 用例因为没有隐含
        --no-pause 而活活挂到超时。

        env: 额外/覆盖的环境变量。这里唯一有价值的用法是塞 "=X:" 这类
        Windows 的「每驱动器当前目录」变量 —— 用来覆盖平时很难触发的分支。
        """
        OUT.mkdir(parents=True, exist_ok=True)
        log = OUT / ("%s.log" % self._seq())
        argv = [self.aac]
        if "--" in args:
            cut = list(args).index("--")
            argv += [str(a) for a in args[:cut]]
            argv.append("--log=%s" % log)
            argv += [str(a) for a in args[cut:]]
        else:
            argv += [str(a) for a in args]
            argv.append("--log=%s" % log)
        child_env = None
        if env:
            child_env = dict(os.environ)
            child_env.update(env)
        try:
            p = subprocess.run(argv, timeout=timeout, capture_output=True,
                               stdin=subprocess.DEVNULL, env=child_env)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            return -99, "[测试超时 %ss]" % timeout
        text = ""
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace")
        return rc, text

    _n = 0

    def _seq(self):
        Ctx._n += 1
        return "%02d" % Ctx._n


def md5(p):
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


def clean_out():
    if OUT.is_dir():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)


# ---------------- 用例 ----------------
@case("version")
def t_version(c):
    rc, txt = c.run("version")
    assert rc == 0, "rc=%s" % rc
    assert "aac " in txt, txt[:200]
    assert "内核指纹" in txt, txt[:200]


@case("help")
def t_help(c):
    rc, txt = c.run("help")
    assert rc == 0, "rc=%s" % rc
    assert "build" in txt and "--log" in txt, txt[:300]


@case("build_success")
def t_build(c):
    exe = OUT / "test.exe"
    rc, txt = c.run("build", str(TESTPROJ), "--out=%s" % exe)
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-1500:])
    assert "BUILD SUCCESS" in txt, txt[-1500:]
    assert exe.is_file(), "未生成 EXE"
    assert exe.stat().st_size > 100000, "EXE 大小异常: %s" % exe.stat().st_size
    return exe


@case("source_not_polluted")
def t_no_pollution(c):
    """构建绝不能改动磁盘上的源码（旧版会把构建信息写回 main.aardio）"""
    main = TESTPROJ / "main.aardio"
    before = md5(main)
    c.run("build", str(TESTPROJ), "--out=%s" % (OUT / "test2.exe"))
    after = md5(main)
    assert before == after, "main.aardio 被修改了!"
    assert "__BUILD_INFO_BEGIN__" not in main.read_text(encoding="utf-8"), "源码残留注入标记"


@case("build_idempotent")
def t_idempotent(c):
    p = OUT / "idem.exe"
    rc1, t1 = c.run("build", str(TESTPROJ), "--out=%s" % p)
    rc2, t2 = c.run("build", str(TESTPROJ), "--out=%s" % p)
    assert rc1 == 0 and rc2 == 0, "rc=%s/%s\n%s\n%s" % (rc1, rc2, t1[-800:], t2[-800:])


@case("exe_runs")
def t_exe_runs(c):
    exe = OUT / "test.exe"
    if not exe.is_file():
        c.run("build", str(TESTPROJ), "--out=%s" % exe)
    log = OUT / "run.log"
    argv = [str(exe), "--no-pause", "--log=%s" % log]
    p = subprocess.run(argv, timeout=120, capture_output=True)
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    assert p.returncode == 0, "EXE 退出码=%s\n%s" % (p.returncode, txt[-1200:])
    assert "RESULT:OK" in txt, txt[-1200:]
    assert "test v" in txt, "构建信息未注入: %s" % txt[-1200:]


@case("exe_args_passthrough")
def t_args(c):
    exe = OUT / "test.exe"
    if not exe.is_file():
        c.run("build", str(TESTPROJ), "--out=%s" % exe)
    log = OUT / "args.log"
    argv = [str(exe), "--no-pause", "--log=%s" % log, "hello", "世界"]
    p = subprocess.run(argv, timeout=120, capture_output=True)
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    assert p.returncode == 0, "rc=%s" % p.returncode
    assert "hello" in txt and "世界" in txt, "参数未透传: %s" % txt[-1200:]


@case("build_badproj_rc1")
def t_bad(c):
    rc, txt = c.run("build", str(HERE / "tests" / "fixtures" / "badproj"))
    assert rc == 1, "rc=%s（语法错必须返回 1）\n%s" % (rc, txt[-800:])
    assert "[ERR]" in txt, txt[-800:]


@case("build_missing_path_rc1")
def t_missing(c):
    rc, txt = c.run("build", str(HERE / "tests" / "fixtures" / "no_such_proj"))
    assert rc == 1, "rc=%s" % rc
    assert "不存在" in txt, txt[-800:]


@case("unknown_cmd_rc1")
def t_unknown(c):
    rc, txt = c.run("frobnicate")
    assert rc == 1, "rc=%s" % rc
    assert "未知子命令" in txt, txt[-800:]


@case("info")
def t_info(c):
    pkg = OUT / "test.appkg"
    if not pkg.is_file():
        c.run("build", str(TESTPROJ), "--out=%s" % (OUT / "test.exe"))
    rc, txt = c.run("info", str(pkg))
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-800:])
    assert "格式版本" in txt and "内核指纹" in txt, txt[-800:]
    assert "main.aardio" in txt, txt[-800:]


@case("no_exe_only_pkg")
def t_no_exe(c):
    d = OUT / "noexe"
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    rc, txt = c.run("build", str(TESTPROJ), "--out=%s" % d, "--no-exe")
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-800:])
    assert (d / "test.appkg").is_file(), "未生成 appkg"
    assert not (d / "test.exe").exists(), "--no-exe 却生成了 EXE"


@case("build_out_dir")
def t_out_dir(c):
    d = OUT / "dirout"
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    rc, txt = c.run("build", str(TESTPROJ), "--out=%s" % d)
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-800:])
    assert (d / "test.exe").is_file(), str(list(d.iterdir()) if d.is_dir() else d)


@case("exclude_dirs")
def t_exclude(c):
    proj = HERE / "tests" / "fixtures" / "exclproj"
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "excl.exe"))
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-800:])
    rc2, t2 = c.run("info", str(OUT / "excl.appkg"))
    assert rc2 == 0, "rc=%s" % rc2
    assert "lib/keep.aardio" in t2, "lib 未打包: %s" % t2[-800:]
    assert "should_not_pack" not in t2, "dist/ 未排除: %s" % t2[-800:]
    assert "also_not_pack" not in t2, ".build/ 未排除: %s" % t2[-800:]


@case("help_flags_rc0")
def t_help_flags(c):
    """--help / --version 必须是 0: 旧版把它们当未知参数吞掉, 误返回 1"""
    for a in ("--help", "-h", "--version", "-V", "help", "version"):
        rc, txt = c.run(a)
        assert rc == 0, "rc=%s <- %s\n%s" % (rc, a, txt[-400:])


@case("unknown_option_rc1")
def t_unknown_option(c):
    """拼错的参数必须报错, 不能静默忽略（否则产物会落到默认位置）"""
    rc, txt = c.run("build", str(TESTPROJ), "--outt=%s" % (OUT / "x.exe"))
    assert rc == 1, "rc=%s（拼错的选项应返回 1）\n%s" % (rc, txt[-400:])
    assert "未知参数" in txt, txt[-400:]


@case("aproj_attrs_applied")
def t_aproj_attrs(c):
    """.aproj 的 FileVersion / publishDir / output 必须真正生效。

    旧实现取「全文第一个 >」当标签结束位置, 而 .aproj 首行是 XML 声明
    <?xml ...?>, 结果所有属性都读到 null: 版本号回退成 1.0.0,
    产物也不落在 publishDir。
    """
    dist = TESTPROJ / "dist"
    if dist.is_dir():
        shutil.rmtree(dist, ignore_errors=True)
    try:
        rc, txt = c.run("build", str(TESTPROJ))
        assert rc == 0, "rc=%s\n%s" % (rc, txt[-1200:])
        assert "1.0.0.0" in txt, "FileVersion 未生效: %s" % txt[-1200:]
        assert str(dist).replace("\\", "/") in txt.replace("\\", "/"), \
            "publishDir 未生效: %s" % txt[-1200:]
        assert (dist / "test.appkg").is_file(), "产物未落在 publishDir: %s" % list(dist.iterdir())
        rc2, t2 = c.run("info", str(dist / "test.appkg"))
        assert rc2 == 0 and "1.0.0.0" in t2, "包内版本错误: %s" % t2[-600:]
    finally:
        if dist.is_dir():
            shutil.rmtree(dist, ignore_errors=True)


@case("write_protect_host")
def t_write_protect_host(c):
    """--out 指向 aardioHost.exe 必须拒绝: 否则会直接毁掉工具链"""
    host = pathlib.Path(DEFAULT_AAC).parent / "aardioHost.exe"
    if not host.is_file():
        return
    before = host.stat().st_size
    rc, txt = c.run("build", str(TESTPROJ), "--out=%s" % host)
    assert rc == 1, "rc=%s（写入宿主必须被拒绝）\n%s" % (rc, txt[-600:])
    assert "已拒绝写入" in txt, txt[-600:]
    assert host.stat().st_size == before, "宿主文件被改动了!"


@case("write_protect_self")
def t_write_protect_self(c):
    rc, txt = c.run("build", str(TESTPROJ), "--out=%s" % c.aac)
    assert rc == 1, "rc=%s（写入 aac 自身必须被拒绝）\n%s" % (rc, txt[-600:])
    assert "已拒绝写入" in txt, txt[-600:]


@case("libs_lists_host_libs")
def t_libs(c):
    rc, txt = c.run("libs")
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-600:])
    assert "预埋库" in txt, txt[-600:]
    for lib in ("console", "fsys", "win", "json"):
        assert lib in txt, "预埋库清单缺少 %s: %s" % (lib, txt[-600:])


@case("missing_lib_blocked")
def t_missing_lib(c):
    """工程用到宿主未预埋的库时, build 阶段就要报错而不是等到运行时

    【踩过的坑】这里最早写死 web.view 当"缺库样本"。等宿主扩容到 274 个库
    之后 web.view 早就被预埋了, 用例立刻变成假红 —— 而它红的理由跟被测逻辑
    一点关系都没有。缺库样本必须运行时从宿主清单里反选出来,
    否则每扩一次容就要手工改一次测试。
    """
    proj = HERE / "tests" / "fixtures" / "misslib"
    proj.mkdir(parents=True, exist_ok=True)
    miss = pick_missing_lib(c)
    (proj / "main.aardio").write_text(
        'import console;\nimport %s;\nconsole.log("x");\n' % miss, encoding="utf-8"
    )
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "miss.exe"))
    assert rc == 1, "rc=%s（缺库应返回 1）\n%s" % (rc, txt[-900:])
    assert "宿主未预埋库" in txt, txt[-900:]
    assert miss in txt, "未指出具体缺哪个库(%s): %s" % (miss, txt[-900:])


# 故意长期不预埋的样本池: 只要有一个不在宿主清单里就够用。
# 选的都是"确实存在但有意不预埋"的库, 不能随便编一个不存在的名字,
# 否则走的是"库不存在"分支而不是"未预埋"分支, 测的就不是这回事了。
MISSING_LIB_POOL = (
    "winex.caret", "java.jre.v8", "inet.file", "ide",
    "web.blink", "wsock.tcp.server", "win.ui.debug", "process.popen.exe",
)


def pick_missing_lib(c):
    """从宿主预埋清单里反选出一个当前确实没预埋的库名"""
    rc, txt = c.run("libs")
    assert rc == 0, "aac libs 失败: %s" % txt[-400:]
    have = set()
    for line in txt.split("\n"):
        s = line.strip()
        if s and not s.startswith("宿主") and "预埋库" not in s and ":" not in s:
            have.add(s)
    for cand in MISSING_LIB_POOL:
        if cand not in have:
            return cand
    raise AssertionError("样本池里的库都被预埋了, 请扩充 MISSING_LIB_POOL: %s"
                         % (MISSING_LIB_POOL,))


@case("missing_lib_can_bypass")
def t_missing_lib_bypass(c):
    """--no-lib-check 是明确的逃生阀"""
    proj = HERE / "tests" / "fixtures" / "misslib"
    rc, txt = c.run(
        "build", str(proj), "--out=%s" % (OUT / "miss2.exe"), "--no-lib-check"
    )
    assert rc == 0, "rc=%s（--no-lib-check 应放行）\n%s" % (rc, txt[-900:])


@case("run_exit_code")
def t_run_exit_code(c):
    """脚本 return 出来的数字必须成为 aac 的退出码, 否则 CI 无法判定"""
    src = HERE / "tests" / "fixtures" / "return7.aardio"
    src.write_text('import console;\nconsole.log("ret7");\nreturn 7;\n', encoding="utf-8")
    rc, txt = c.run("run", str(src))
    assert rc == 7, "rc=%s（期望脚本返回值 7）\n%s" % (rc, txt[-600:])


@case("exec_exit_code_and_passthrough")
def t_exec_exit_code(c):
    """exec 的退出码 + "--" 之后的参数原样透传"""
    proj = HERE / "tests" / "fixtures" / "exitproj"
    rc, _ = c.run("build", str(proj), "--out=%s" % (OUT / "exitapp.exe"))
    assert rc == 0, "fixture 构建失败 rc=%s" % rc
    rc2, t2 = c.run("exec", str(OUT / "exitapp.appkg"), "--", "--exit=7")
    assert rc2 == 7, "rc=%s（期望 7）\n%s" % (rc2, t2[-800:])
    assert "code=7" in t2, "脚本未收到参数: %s" % t2[-800:]


@case("exe_exit_code")
def t_exe_exit_code(c):
    """独立 EXE 的 main 返回值同样要成为进程退出码"""
    exe = OUT / "exitapp.exe"
    if not exe.is_file():
        c.run("build", str(HERE / "tests" / "fixtures" / "exitproj"), "--out=%s" % exe)
    log = OUT / "exit.log"
    p = subprocess.run([str(exe), "--exit=9", "--log=%s" % log],
                       timeout=120, capture_output=True)
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    assert p.returncode == 9, "EXE 退出码=%s（期望 9）\n%s" % (p.returncode, txt[-800:])
    assert "code=9" in txt, "EXE 未收到参数: %s" % txt[-800:]


@case("compile_and_run")
def t_compile(c):
    src = HERE / "tests" / "fixtures" / "hello.aardio"
    src.write_text('import console;\nconsole.log("HELLO_FROM_COMPILE");\n', encoding="utf-8")
    dump = OUT / "hello.dump"
    rc, txt = c.run("compile", str(src), str(dump))
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-800:])
    assert dump.is_file(), "未生成 .dump"
    rc2, t2 = c.run("run", str(dump))
    assert rc2 == 0, "rc=%s\n%s" % (rc2, t2[-800:])
    assert "HELLO_FROM_COMPILE" in t2, t2[-800:]


@case("import_scan_sees_lib_after_comment")
def t_import_gap(c):
    r"""两条 import 之间夹了注释，依赖检查必须照样看得见后面的库。

    【怎么踩的】找换行写成 indexOf(src, "\n")，而双引号串里它只是 \ 和 n
    两个字面字符 —— 永远匹配不到真换行，整份源码就被当成一行处理，
    一遇到非 import 内容就停止解析。于是构建报「依赖检查：通过」，
    产物一运行就 import failed。失败发生在构建之后、以为成功之后，最要命。
    """
    # 缺库样本同样运行时反选: 写死 gdip.brush 时它确实没预埋,
    # 但宿主一扩容就变成 rc=0, 用例红的理由跟被测逻辑毫无关系。
    proj = OUT / "importgap"
    proj.mkdir(parents=True, exist_ok=True)
    miss = pick_missing_lib(c)
    (proj / "main.aardio").write_text(
        'import console;\n// 中间夹一行注释\nimport %s;\nconsole.log("x");\n' % miss,
        encoding="utf-8",
    )
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "gap.exe"))
    assert rc == 1, "rc=%s —— 注释后的库被漏检了\n%s" % (rc, txt[-1200:])
    assert miss in txt, "未指出缺哪个库(%s): %s" % (miss, txt[-1200:])
    assert "宿主未预埋库" in txt, txt[-1200:]


@case("log_file_has_real_newlines")
def t_log_newlines(c):
    """日志文件必须有真正的换行，不能是字面 \\r\\n 四个字符挤成一坨。

    排错是靠读日志的，日志成一行就等于没有日志。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / "nl_probe.log"
    if log.is_file():
        log.unlink()
    p = subprocess.run([c.aac, "version", "--no-pause", "--log=%s" % log],
                       timeout=120, capture_output=True)
    assert p.returncode == 0, "rc=%s" % p.returncode
    raw = log.read_bytes()
    assert raw.count(b"\r\n") >= 2, "日志里没有真正的 CRLF 换行: %r" % raw[:200]
    assert b"\\r\\n" not in raw, "日志里出现了字面 \\r\\n 文本: %r" % raw[:200]


@case("lib_name_not_truncated_by_trim")
def t_trim_charset(c):
    """以 t / r / n 结尾的库名不能被 trim 啃掉字符。

    string.trim(s, " \\t\\r\\n") 的字符集是 {空格, \\, t, r, n}，
    string.trim(s, " \\t\\r\\n") 的字符集是 {空格, \\, t, r, n}，
    于是 winex.caret -> winex.care、ncolor -> colo。补库命令因此永远补不上。
    """
    rc, txt = c.run("host-add", "zzz.libtest")
    # 有毒的 trim 字符集会把结尾的 t 吃掉。
    # 用一个不存在的名字试探即可 —— 这样不会真的改动宿主源码。
    assert "zzz.libtest" in txt, \
        "库名被 trim 啃掉了（结尾的 t 没了）: %s" % txt[-1200:]
    assert "zzz.libtes\"" not in txt, txt[-1200:]


@case("host_add_refuses_heavy_side_effect_lib")
def t_host_add_risky(c):
    """预埋「import 时有重副作用」的库必须被拦下 —— 这是实测炸出来的。

    winex.caret 顶部有 `if(_WIN7_LATER){ import System.Windows.Automation.3 }`。
    把它写进宿主源码后，宿主 EXE 一启动就要加载 UIA 程序集，
    于是【每一个】由它打出的 EXE 都卡死在启动阶段：120 秒超时，
    日志文件连一行都没有。原本只是干净地报 import failed —— 预埋反而
    把可诊断的失败变成了静默挂死。这类库必须默认拒绝。
    """
    rc, txt = c.run("host-add", "winex.caret")
    assert rc == 1, "rc=%s\n%s" % (rc, txt[-1200:])
    assert "重依赖" in txt or "已跳过" in txt, \
        "未提示重副作用风险: %s" % txt[-1200:]
    assert "已更新宿主源码" not in txt, \
        "危险库仍被写进了宿主源码: %s" % txt[-1200:]
    assert "import winex.caret" not in (HERE / "aardioHost.aardio").read_text(
        encoding="utf-8"), "宿主源码里出现了 winex.caret"


@case("added_lib_is_really_usable")
def t_added_lib_usable(c):
    """走完整个补库链路后，那个库必须真的能用。

    host-add 只改源码，预埋要经 IDE 发布；这一步验证「源码改了 + 重建了」
    之后，之前 import failed 的库确实进了宿主。前面的用例都在验证
    "缺库会被拦住"，这条验证"补了之后真好使" —— 只做一半等于没做。
    """
    proj = HERE / "tests" / "fixtures" / "addedlib"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "main.aardio").write_text(
        'import console;\nimport string.res;\nconsole.log("ADDED_LIB_OK");\n',
        encoding="utf-8",
    )
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "added.exe"))
    assert rc == 0, "补进去的库仍不可用，链路没走通:\n%s" % txt[-1200:]
    exe = OUT / "added.exe"
    assert exe.is_file(), "未生成 EXE"
    log = OUT / "added_run.log"
    p = subprocess.run([str(exe), "--no-pause", "--log=%s" % log],
                       timeout=120, capture_output=True)
    out = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    assert p.returncode == 0, "EXE 运行失败 rc=%s\n%s" % (p.returncode, out[-1200:])
    assert "ADDED_LIB_OK" in out, out[-1200:]


# ---------------- 静态门禁 ----------------

def _py(script, *extra):
    p = subprocess.run([sys.executable, str(HERE / script), *extra],
                       timeout=180, capture_output=True)
    out = (p.stdout or b"").decode("utf-8", "replace")
    return p.returncode, out


@case("static_audit_clean")
def t_static_audit(c):
    """源码必须过静态陷阱审计。

    这些坑的共同点是「编译绿灯通过、运行时静默不生效」，
    靠 review 记不住，只能由工具拦。
    """
    rc, txt = _py("audit.py")
    assert rc == 0, "静态审计未通过:\n%s" % txt[-2000:]


@case("audit_detectors_really_work")
def t_audit_selftest(c):
    """探测器自检: 喂已知坏样例必须报红。

    防止出现「报表永远全绿、因为探测器早就哑了」这种最坏情况。
    """
    rc, txt = _py("audit.py", "--selftest")
    assert rc == 0, "探测器自检失败:\n%s" % txt[-2000:]
    assert "失败 0" in txt, txt[-800:]


@case("mutation_test_catches_real_bugs")
def t_mutation(c):
    """变异测试: 把历史上真实发生过的 bug 植回源码，审计必须抓得住。"""
    rc, txt = _py("mutation_test.py")
    assert rc == 0, "变异测试失败（有规则抓不住已知 bug）:\n%s" % txt[-2000:]


# ---------------- 第二轮新增：针对已定位的深层语言陷阱 ----------------

@case("run_runtime_error_rc1")
def t_run_runtime_error(c):
    """脚本抛运行时错误时必须返回 1。

    aardio 的坑: return 写在 try{} / catch{} 里既不返回也不生效。
    cmdRun 原本是 catch(e){ return exitErr(...) }, 结果错误被吞掉,
    崩溃的脚本照样返回退出码 0 —— CI 里就是「失败被判成功」。
    """
    src = HERE / "tests" / "fixtures" / "boom.aardio"
    src.write_text(
        'import console;\nconsole.log("before-boom");\nerror("BOOM_TEST");\n',
        encoding="utf-8",
    )
    rc, txt = c.run("run", str(src))
    assert rc == 1, "rc=%s（运行时错误应返回 1）\n%s" % (rc, txt[-800:])
    assert "运行时错误" in txt, txt[-800:]


@case("exec_runtime_error_rc1")
def t_exec_runtime_error(c):
    """同上，但走 aac exec / 独立 EXE 这条链路（宿主也有一样的坑）"""
    proj = HERE / "tests" / "fixtures" / "boomproj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "main.aardio").write_text(
        'import console;\nconsole.log("pack-boom");\nerror("PACK_BOOM");\n',
        encoding="utf-8",
    )
    pkg = OUT / "boom.appkg"
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "boom.exe"))
    assert rc == 0, "fixture 构建失败 rc=%s\n%s" % (rc, txt[-800:])
    rc2, t2 = c.run("exec", str(pkg))
    assert rc2 == 1, "rc=%s（exec 运行时错误应返回 1）\n%s" % (rc2, t2[-800:])
    assert "运行时错误" in t2, t2[-800:]

    exe = OUT / "boom.exe"
    if exe.is_file():
        log = OUT / "boomrun.log"
        p = subprocess.run([str(exe), "--log=%s" % log], timeout=120,
                           capture_output=True)
        assert p.returncode == 1, "独立EXE 退出码=%s（运行时错误应返回 1）" % p.returncode


@case("isdir_used_by_scanner")
def t_scanner_sees_real_lib(c):
    """标准库扫描必须真的扫得到二级目录下的组件。

    fsys.enum 对「目录」条目回调时, 第一个参数是目录【名字】而不是路径。
    曾经把它当路径塞回队列, 于是 lib/winex/caret.aardio 这种明明存在的库
    被判成"标准库里没有"。这里用一个真实存在的二级标准库做探测:
    build 的缺库报告必须把它归到「一条命令可自动补」那一类。
    """
    proj = HERE / "tests" / "fixtures" / "needlib2"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "main.aardio").write_text(
        'import console;\nimport gdip.brush;\nconsole.log("x");\n', encoding="utf-8"
    )
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "need2.exe"))
    assert rc == 1, "rc=%s（缺库应返回 1）\n%s" % (rc, txt[-1200:])
    assert "gdip.brush" in txt, "未列出缺失库: %s" % txt[-1200:]
    assert "aac host-add" in txt, \
        "本机有这个标准库，应给出自动补库命令而不是让去下第三方库: %s" % txt[-1200:]
    assert "标准库里没有这个库" not in txt, \
        "扫描器没看到 gdip.brush（fsys.enum 目录参数用错了）: %s" % txt[-1200:]


@case("missing_lib_suggests")
def t_missing_lib_suggests(c):
    """直觉库名写错时要给候选, 而不是只说一句"找不到" """
    rc, txt = c.run("host-add", "this_lib_does_not_exist_zzz")
    assert rc == 1, "rc=%s\n%s" % (rc, txt[-800:])
    assert "标准库里没有这个库" in txt or "没有需要新增的库" in txt, txt[-800:]


@case("host_add_rejects_unknown")
def t_host_add_unknown(c):
    """host-add 必须拒绝未知库名，且不能改坏宿主源码"""
    rc, txt = c.run("host-add", "zzz_no_such_lib_1")
    assert rc == 1, "rc=%s（未知库名应拒绝）\n%s" % (rc, txt[-800:])


@case("cwd_option_resolves_relative")
def t_cwd_option(c):
    """--cwd 必须能改变相对路径的基准。

    aardio 独立 EXE 会把当前目录劫持到 EXE 目录，进程内拿不回调用方的 CWD，
    只能由调用方显式告知。这条用例锁住这条契约。
    """
    d = OUT / "cwdsrc"
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    src = d / "x.aardio"
    src.write_text('import console;\nconsole.log("CWD_OK");\n', encoding="utf-8")
    # 两种写法都必须支持: 选项在子命令前 / 在位置参数后
    for argv in ((("--cwd=%s" % d), "run", "x.aardio"),
                 ("run", "x.aardio", "--cwd=%s" % d)):
        rc, txt = c.run(*argv)
        assert rc == 0, "rc=%s argv=%s（相对路径没按 --cwd 解析）\n%s" % (
            rc, argv, txt[-800:])
        assert "CWD_OK" in txt, argv and txt[-800:]


@case("relative_path_without_cwd_hints")
def t_relative_hint(c):
    """不给 --cwd 又写相对路径时，必须把原因和三种写法讲清楚"""
    rc, txt = c.run("run", "not_here_zzz.aardio")
    assert rc == 1, "rc=%s\n%s" % (rc, txt[-800:])
    assert "EXE 所在目录" in txt, "未解释aardio的CWD行为: %s" % txt[-900:]
    assert "--cwd" in txt, "未给出可行动的修法: %s" % txt[-900:]


@case("aproj_version_churn_is_normalized")
def t_aproj_version_pinned(c):
    """IDE 自增的 FileVersion/ProductVersion 必须能被按回固定值

    aardio IDE 每次发布都会自增 default.aproj 里的这两个版本号。它们与
    本工程无关（真正的版本写在 aac.aardio 的 AAC_VERSION 里），但会让
    每次 build.py all 之后 git 工作区变脏 —— 贡献者很容易顺手把这种纯噪音
    提交进来。build.py 靠 normalize_aproj_versions() 把它钉住，这里验证
    它真的会把被改动的文件改回去（而不是只写在注释里）。
    """
    import build

    targets = [HERE / proj / "default.aproj"
               for proj in ("aac-runner", "aardioHost-runner")]
    for f in targets:
        raw = f.read_text(encoding="utf-8-sig")
        f.write_text(raw.replace('FileVersion="%s"' % build.APROJ_PINNED_VERSION,
                                 'FileVersion="9.9.9.9"')
                        .replace('ProductVersion="%s"' % build.APROJ_PINNED_VERSION,
                                 'ProductVersion="9.9.9.9"'),
                     encoding="utf-8-sig")
        # 前置校验：这一步没生效的话，后面的"已恢复"就是假绿
        assert "9.9.9.9" in f.read_text(encoding="utf-8-sig"), "没能篡改版本号: %s" % f

    build.normalize_aproj_versions()

    for f in targets:
        after = f.read_text(encoding="utf-8-sig")
        assert "9.9.9.9" not in after, "版本号没被按回去: %s" % f
        assert 'FileVersion="%s"' % build.APROJ_PINNED_VERSION in after, \
            "没有恢复到固定值: %s" % f
        # BOM 不能被弄丢（写回时用 utf-8-sig）
        assert f.read_bytes().startswith(b"\xef\xbb\xbf"), "BOM 丢了: %s" % f


@case("caller_cwd_recovered_and_never_guessed")
def t_caller_cwd(c):
    """cmd 继承下来的「每驱动器当前目录」要能自动采用，但出现歧义时必须拒绝猜测

    aardio 独立 EXE 会把进程当前目录劫持到 EXE 目录，进程内拿不回调用方站在哪。
    唯一例外：cmd.exe 会维护 "<盘符>:=<该盘当前目录>" 并继承给子进程，
    所以在 cmd 里跑 aac 时能把真实位置捞回来 —— 交互式用法不必再手写 --cwd。

    这条用例同时锁住两件事：
      · 恰好一个盘符变量 → 采用；
      · 两个及以上 → 无法判断用户站在哪个盘，宁可退回明确报错也不许乱猜。
    （第二分支平时几乎触发不到，所以要刻意构造，否则它又是一条"没参与过却报通过"的规则）
    """
    d = OUT / "callercwd"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    (d / "y.aardio").write_text(
        'import console;\nconsole.log("RECOVERED");\n', encoding="utf-8")

    # 形如 "D:" -> "=D:"
    drive = str(d.drive)
    assert len(drive) == 2 and drive[1] == ":", "拿不到盘符: %r" % drive
    key = "=" + drive

    # 1) 恰好一个 → 相对路径按它解析
    rc, txt = c.run("run", "y.aardio", env={key: str(d)})
    assert rc == 0, "单个盘符变量应能自动恢复 CWD\n%s" % txt[-900:]
    assert "RECOVERED" in txt, "脚本没跑起来: %s" % txt[-900:]

    # 2) 两个 → 有歧义，必须拒绝猜测并给可行动提示
    rc, txt = c.run("run", "y.aardio", env={key: str(d), "=Z:": r"Z:\fake"})
    assert rc == 1, "有歧义时不该继续猜目录\n%s" % txt[-900:]
    assert "--cwd" in txt, "歧义场景下没给出可行动的修法\n%s" % txt[-900:]


@case("host_add_already_embedded")
def t_host_add_dup(c):
    """已经预埋的库要跳过，而不是把 import 写两遍"""
    rc, txt = c.run("host-add", "console")
    assert rc == 1 or "已预埋" in txt, "rc=%s\n%s" % (rc, txt[-800:])


@case("host_add_refuses_fatal_lib")
def t_host_add_fatal(c):
    """实测会杀死产物的库必须默认拒绝（--force 才能强加）

    ide 是 host_grow 真发布 + 真跑出来的结论: 预埋后每个产物 EXE
    都是 rc=-1、日志为空。放行它等于把工具链整体打瘫。
    """
    rc, txt = c.run("host-add", "ide")
    assert rc == 1, "rc=%s（致命库应被拒绝）\n%s" % (rc, txt[-900:])
    assert "ide" in txt and ("致命" in txt or "起不来" in txt or "风险" in txt), (
        "未说明拒绝理由: %s" % txt[-900:])


@case("exe_log_clean_without_trace")
def t_trace_off(c):
    """--log 里默认不能有 [TRACE] 行

    宿主的启动期旁路诊断是为了排查「产物静默失败」加的，代价是每写一行
    都往日志里塞 [TRACE]。默认打开的话，用户自己的输出就被淹了 ——
    诊断设施不能反过来损害正常路径的可读性。只有 --trace 才开。
    """
    exe = OUT / "test.exe"
    if not exe.is_file():
        c.run("build", str(TESTPROJ), "--out=%s" % exe)
    log = OUT / "traceoff.log"
    if log.is_file():
        log.unlink()
    subprocess.run([str(exe), "--no-pause", "--log=%s" % log],
                   timeout=120, capture_output=True)
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    assert "RESULT:OK" in txt, txt[-1200:]
    assert "[TRACE]" not in txt, "默认就把日志污染了:\n%s" % txt[-1200:]


def host_sandbox(name):
    """造一个运行 host-add / host-del 的隔离沙箱

    为什么必须拷贝一份 aac.exe 而不是用 --cwd:
      findFileUpwards("aardioHost.aardio") 是从 **EXE 所在目录**向上找的，
      CWD 对它毫无影响；lib 同理只看 exeDir/lib。所以要把 aac 放到沙箱里，
      再用一个只有几行的假宿主源码 + 假的 lib 目录，
      既不触碰仓库里真正的 279 库宿主，又能完整跑通补库逻辑。
    """
    box = OUT / name
    if box.is_dir():
        shutil.rmtree(box, ignore_errors=True)
    (box / "lib").mkdir(parents=True, exist_ok=True)
    return box


def fake_lib(box, *names):
    for n in names:
        p = box / "lib" / ("%s.aardio" % n)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("namespace %s{}\n" % n, encoding="utf-8")


def write_fake_host(box, imports, sentinel):
    body = ["// head"]
    for n in imports:
        body.append("import %s;" % n)
    body += ["", "var x = 1;", "",
             'HOST_LIBS_DECL = "/*__HOST_LIBS__*/%s/*__HOST_LIBS_END__*/";'
             % ",".join(sentinel),
             "return 0;", ""]
    host = box / "aardioHost.aardio"
    # newline="" 必须有: 默认的 write_text 会把 '\n' 再翻译成 '\r\n',
    # 于是 '\r\n' 变成 '\r\r\n', 假源码的行尾就比真实宿主源码多一个 '\r'
    with open(host, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(body))
    return host


def read_fake_host(box):
    return (box / "aardioHost.aardio").read_text(encoding="utf-8")


def read_fake_host_bytes(box):
    """按字节读：read_text 会把 \\r\\n 归一化成 \\n，看不出行尾被没被动过"""
    return (box / "aardioHost.aardio").read_bytes()


def run_in_box(box, *args, timeout=120):
    log = box / "run.log"
    if log.is_file():
        log.unlink()
    aac = box / "aac.exe"
    argv = [str(aac)] + [str(a) for a in args] + ["--log=%s" % log]
    p = subprocess.run(argv, timeout=timeout, capture_output=True,
                       stdin=subprocess.DEVNULL)
    txt = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    return p.returncode, txt


@case("host_add_is_idempotent")
def t_host_add_idempotent(c):
    """同一个库补两次只能写进一条 import，且哨兵里也只能出现一次

    host-add 早期只拿「宿主 EXE 里的哨兵」判断已预埋。预埋是在 IDE 发布
    那一刻才写进 EXE 的 —— 只要上一次 rebuild 没真成功（python 起不来/
    IDE 发布被中断/宿主被回滚），哨兵里就没有刚加的库，于是同一个库被
    反复追加。实测 string.cmdline 被追加了 5 次。
    判断依据必须换成源码本身的 import 区块 + 写入前整体去重。
    """
    box = host_sandbox("hostadd")
    shutil.copy2(c.aac, box / "aac.exe")
    fake_lib(box, "fsys")
    # 故意留一条重复项，验证旧账也会被顺手清掉
    write_fake_host(box, ["console", "string", "math", "math"],
                    ["console", "string", "math", "math"])

    rc, txt = run_in_box(box, "host-add", "fsys")
    assert rc == 0, "rc=%s（新增库失败了）\n%s" % (rc, txt[-1200:])
    src = read_fake_host(box)
    assert src.count("import math;") == 1, "重复 import 没被清理:\n%s" % src
    assert src.count("import fsys;") == 1, "import fsys 条数不对:\n%s" % src
    decl = src.split("__HOST_LIBS__*/")[1].split("/*__HOST_LIBS_END__")[0]
    assert decl.count("math") == 1, "哨兵里仍然重复:\n%s" % decl
    assert decl.count("fsys") == 1, "哨兵没同步 fsys:\n%s" % decl
    assert read_fake_host_bytes(box).endswith(b"\r\n"), "末尾换行被弄丢了"

    # 第二次必须是幂等空操作: 不报错、不重复写入
    before = read_fake_host(box)
    rc2, txt2 = run_in_box(box, "host-add", "fsys")
    after = read_fake_host(box)
    assert before == after, "重复补库把源码改了:\n%s" % after
    assert rc2 == 0, "已预埋应返回 0（幂等命令不能让 CI 断在第二遍），实际 %s\n%s" % (
        rc2, txt2[-800:])


@case("host_del_is_idempotent_and_tidy")
def t_host_del_idempotent(c):
    """host-del 删干净、删不存在的返回 0、且不破坏文件末尾换行

    老实现按行重建时把最后那个换行符吃掉了 —— 每次 host-del 都会多一行
    无意义 diff，久而久之没人敢 review 这个文件。
    """
    box = host_sandbox("hostdel")
    shutil.copy2(c.aac, box / "aac.exe")
    write_fake_host(box, ["console", "math", "math"], ["console", "math", "math"])

    rc, txt = run_in_box(box, "host-del", "math")
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-1200:])
    src = read_fake_host(box)
    assert "math" not in src, "没删干净:\n%s" % src
    raw = read_fake_host_bytes(box)
    assert raw.endswith(b"return 0;\r\n"), "末尾换行被弄丢了:\n%r" % raw[-40:]
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n"), (
        "CRLF 被退化成 LF 了（行尾 '\r' 应该随行一起保留）:\n%r" % raw[:120])

    rc2, txt2 = run_in_box(box, "host-del", "math")
    assert rc2 == 0, "删本来就没有的库不该报错，实际 %s\n%s" % (rc2, txt2[-800:])


@case("import_line_with_trailing_comment_agrees_with_build_py")
def t_import_trailing_comment(c):
    """`import x; // 说明` 这种行必须和 build.py 的判定完全一致

    曾经 aac 侧要求整行以 ';' 结尾才算 import，而 build.py 的
    `^\\s*import\\s+(\\w+)\\s*;` 不锚行尾 —— 于是：
        build.py : 认这是 x 的 import，纳入清单，发布通过
        aac 侧   : 看不见它 → host-add x 又追加一条
        → 源码里两条 → check_host_libs 报「重复 import」发布失败
        → 而它给出的修复命令恰恰就是制造重复的那条命令，死循环。

    两边规则必须同一个语义；这条用例把「带行尾注释」和「带块注释收尾」
    两种写法都钉死。
    """
    box = host_sandbox("hostcomment")
    shutil.copy2(c.aac, box / "aac.exe")
    fake_lib(box, "gamma", "delta")
    body = [
        "// head",
        "import console;",
        "import gamma;   // 行尾注释：很常见的写法",
        "import delta;   /* 块注释收尾 */",
        "",
        'HOST_LIBS_DECL = "/*__HOST_LIBS__*/console,gamma,delta'
        '/*__HOST_LIBS_END__*/";',
        "return 0;",
        "",
    ]
    with open(box / "aardioHost.aardio", "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(body))

    # host-add 必须认出来"已经有了"，而不是再写一条
    rc, txt = run_in_box(box, "host-add", "gamma")
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-1200:])
    src = read_fake_host(box)
    assert src.count("import gamma") == 1, "带注释的 import 被重复追加了:\n%s" % src
    assert "行尾注释" in src, "原始注释被破坏了:\n%s" % src

    # host-del 也必须能删掉带注释的那一行
    rc2, txt2 = run_in_box(box, "host-del", "delta")
    assert rc2 == 0, "rc=%s\n%s" % (rc2, txt2[-1200:])
    src2 = read_fake_host(box)
    assert "delta" not in src2, "带块注释的 import 删不掉:\n%s" % src2
    assert src2.count("import gamma") == 1, "顺手把别的行也弄坏了:\n%s" % src2


@case("host_add_ignores_stale_exe_sentinel")
def t_host_add_ignores_stale_exe_sentinel(c):
    """host-del 完还没 --rebuild 时，host-add 必须能把库补回来

    哨兵 = 上一次【成功发布】写进宿主 EXE 的快照，源码 = 下一次发布会预埋什么。
    host-del 只改源码，EXE 要等重建才更新 —— 中间这段窗口哨兵必然比源码"多"。
    2.3.0 把 host-add 的判定换成源码之后，却在跳过条件里留了 declared（EXE 哨兵），
    于是出现：
        host-del gamma → host-add gamma → 「已预埋，跳过」，源码一字未动
        → 下次发布真的没有 gamma → 用户补库 → 还是「已预埋」→ 死循环。
    判定只能认源码 import 区块；哨兵充其量用来给出"两边没同步"的诊断。

    【为什么以前的用例没抓到】沙箱里从来没有宿主 EXE，declared 恒为空，
    这条分支从未被执行 —— 所谓"幂等测试通过"其实压根没走到它。
    """
    box = host_sandbox("hoststale")
    shutil.copy2(c.aac, box / "aac.exe")
    fake_lib(box, "alpha", "gamma")

    # 扮演"陈旧的宿主 EXE"：extractHostLibs 只按字节找哨兵串，纯文本就够，
    # 不必真发布一次。里面写着 gamma —— 装的正是 host-del 之前的状态。
    (box / "aardioHost.exe").write_text(
        "/*__HOST_LIBS__*/alpha,gamma/*__HOST_LIBS_END__*/", encoding="ascii")

    # 源码侧：gamma 已被 host-del 删掉，哨兵也已按源码重写
    write_fake_host(box, ["alpha"], ["alpha"])

    rc, txt = run_in_box(box, "host-add", "gamma")
    assert rc == 0, "rc=%s\n%s" % (rc, txt[-1200:])
    assert "已预埋，跳过" not in txt, (
        "拿陈旧的 EXE 哨兵判了已预埋，gamma 永远补不回来:\n%s" % txt[-1200:])
    src = read_fake_host(box)
    assert src.count("import gamma;") == 1, "gamma 没被补进源码:\n%s" % src
    decl = src.split("__HOST_LIBS__*/")[1].split("/*__HOST_LIBS_END__")[0]
    assert decl.count("gamma") == 1, "哨兵没同步 gamma:\n%s" % decl
    # 顺便验证诊断口：应当明确告诉用户两边不同步
    assert ("哨兵" in txt), "没提示哨兵与源码不同步，用户只能猜:\n%s" % txt[-1200:]

    # 第二遍仍然幂等
    before = read_fake_host(box)
    rc2, txt2 = run_in_box(box, "host-add", "gamma")
    assert before == read_fake_host(box), "补完之后重复执行又把源码改了:\n%s" % read_fake_host(box)
    assert rc2 == 0, "第二遍应返回 0，实际 %s\n%s" % (rc2, txt2[-800:])


@case("host_add_rebuild_really_rebuilds")
def t_host_add_rebuild(c):
    """--rebuild 必须真的重建宿主，并且自己验证过再说成功

    早期版本用 io.popen 跑 build.py，拿不到输出就 return 0：
    宿主压根没重建，命令却报成功，用户再 build 一次还是同样的缺库。
    后来又踩到两个连环坑：python 在这种子进程里 stdin 还是管道时会崩在
    init_sys_streams；命令以引号开头会被 cmd /c 的去引号规则切烂。
    这条用例用「已预埋的库」触发一次真实重建（不改库集合），
    要求 rc=0 且日志里出现验证通过的字样。
    """
    rc, txt = c.run("host-add", "console", "--rebuild", timeout=300)
    assert rc == 0, "rc=%s（--rebuild 失败了却没报出来）\n%s" % (rc, txt[-1200:])
    assert "宿主已重建" in txt, "没做事实校验就返回 0:\n%s" % txt[-1200:]
    assert "Fatal Python error" not in txt, "python 在子进程里没起来:\n%s" % txt[-800:]
    assert "不是内部或外部命令" not in txt, "命令行被 cmd 切坏了:\n%s" % txt[-800:]


@case("include_root_relative_resolves")
def t_include_root(c):
    """$"/res/x.aardio" 这类工程根相对包含必须按工程目录解析

    真实语料里 16/25 的编译失败都栽在这: 独立 EXE 会把前导斜杠解析成
    aac 自己所在目录（io.fullpath("/res/x") -> %AARDIO_HOME%\\res\\x），
    而 IDE 是按工程目录解析的。
    """
    proj = OUT / "incroot"
    if proj.is_dir():
        shutil.rmtree(proj, ignore_errors=True)
    (proj / "res").mkdir(parents=True, exist_ok=True)
    (proj / "res" / "x.txt").write_text("INCLUDE_OK", encoding="utf-8")
    (proj / "main.aardio").write_text(
        'import console;\n'
        'var s = $"/res/x.txt";\n'
        'console.log(s);\n',
        encoding="utf-8")
    rc, txt = c.run("build", str(proj), "--out=%s" % (OUT / "incroot.exe"))
    assert rc == 0, "rc=%s（工程根相对包含没被解析）\n%s" % (rc, txt[-900:])
    assert "Cannot include" not in txt, txt[-900:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aac", default=DEFAULT_AAC)
    ap.add_argument("-k", default="", help="只跑名字含该关键字的用例")
    args = ap.parse_args()

    aac = pathlib.Path(args.aac)
    if not aac.is_file():
        print("找不到 aac: %s" % aac)
        return 2

    clean_out()
    c = Ctx(str(aac))
    passed, failed = 0, []
    for name, fn in CASES:
        if args.k and args.k not in name:
            continue
        t0 = time.time()
        try:
            fn(c)
            print("  PASS  %-24s (%.1fs)" % (name, time.time() - t0))
            passed += 1
        except AssertionError as e:
            print("  FAIL  %-24s (%.1fs)\n        %s" % (name, time.time() - t0, str(e).replace("\n", "\n        ")))
            failed.append(name)
        except Exception as e:
            print("  ERR   %-24s (%.1fs)\n        %s: %s" % (name, time.time() - t0, type(e).__name__, e))
            failed.append(name)

    print("")
    print("通过 %d / 失败 %d / 共 %d" % (passed, len(failed), passed + len(failed)))
    if failed:
        print("失败用例: %s" % ", ".join(failed))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
