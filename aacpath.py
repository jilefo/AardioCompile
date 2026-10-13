# -*- coding: utf-8 -*-
"""本机路径解析——**开源仓库里不能写死任何人的绝对路径**。

为什么要有这个文件
------------------
工程里所有脚本都需要知道两件事：aardio 装在哪、aac.exe 在哪。
最早它们各自写着一行本机绝对路径：

    DEFAULT_AAC = r"%AARDIO_HOME%\\aac.exe"

这在自己机器上没问题，一开源就变成三重伤害：
  1. 别人 clone 下来每个脚本都跑不起来（还不一定能看懂为什么）；
  2. 把作者机器的盘符与目录布局泄漏出去；
  3. 想改的人得去六个文件里逐个搜标。

现在统一由这里解析，优先级是**显式 > 本机提示 > 自动发现**：

    1. 环境变量      AARDIO_EXE / AAC_EXE        —— CI 与临时覆盖用
    2. 本机提示文件  <仓库>/.local_paths.txt      —— 不进仓库（已 gitignore），
                                                    作者把自己的路径写这里即可
    3. 自动发现      PATH / 常见安装目录 / 仓库构建产物

第 2 步是关键：既让仓库保持"零个人信息"，又不牺牲本机便利性。
"""

import os
import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
HINT_FILE = HERE / ".local_paths.txt"

# 常见安装位置。注意这里刻意**不含**任何作者专用的路徑——
# 那类路径请写进 .local_paths.txt。
COMMON_AARDIO = [
    r"C:\aardio\aardio.exe",
    r"C:\Program Files\aardio\aardio.exe",
    r"C:\Program Files (x86)\aardio\aardio.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\aardio\aardio.exe"),
]


def _hint(key):
    """读本机提示文件里的 <KEY>=<路径>。文件不在或被注释掉都返回空串。"""
    try:
        if not HINT_FILE.is_file():
            return ""
        for line in HINT_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip().upper() == key.upper():
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _first_existing(cands):
    for c in cands:
        if c and pathlib.Path(c).is_file():
            return str(pathlib.Path(c))
    return None


def find_aardio_exe():
    """定位 aardio.exe（用来驱动它的 IDE 做发布）"""
    return _first_existing(
        [os.environ.get("AARDIO_EXE", ""), _hint("AARDIO_EXE"),
         shutil.which("aardio.exe")] + COMMON_AARDIO)


def find_aac():
    """定位已发布的 aac.exe

    顺序刻意把「仓库刚构建出来的产物」放在自动发现的最后：
    本机已经装了一份的话，日常当然优先用装的那份；
    但对一个刚 clone 完、还没安装的人来说，仓库里刚编出来的就是唯一选择。
    """
    return _first_existing([
        os.environ.get("AAC_EXE", ""),
        _hint("AAC_EXE"),
        shutil.which("aac.exe"),
        HERE / "aac-runner" / "dist" / "aac.exe",
    ])


def find_aardio_lib():
    """aardio 标准库目录（<aardio安装目录>/lib 或 /std）"""
    exe = find_aardio_exe()
    if not exe:
        return None
    for cand in (pathlib.Path(exe).parent / "lib",
                 pathlib.Path(exe).parent / "std"):
        if cand.is_dir():
            return cand
    return None


def require(kind):
    """给命令行脚本用：找不到就打印一段能照着操作的提示并返回 None"""
    if kind == "aac":
        p = find_aac()
        if not p:
            print("找不到 aac.exe。请任选一种方式告诉它在哪：")
            print("  1) 环境变量:  set AAC_EXE=<路径>\\aac.exe")
            print("  2) 提示文件:  在仓库根目录建 .local_paths.txt，写一行")
            print("                AAC_EXE=<路径>\\aac.exe")
            print("  3) 命令行参数: 本脚本支持 --aac <路径>")
            print("   （还没有 aac.exe？先执行 python build.py aac-runner）")
            return None
        return p
    if kind == "aardio":
        p = find_aardio_exe()
        if not p:
            print("找不到 aardio.exe。请任选一种方式告诉它在哪：")
            print("  1) 环境变量:  set AARDIO_EXE=<路径>\\aardio.exe")
            print("  2) 提示文件:  在仓库根目录建 .local_paths.txt，写一行")
            print("                AARDIO_EXE=<路径>\\aardio.exe")
            return None
        return p
    raise ValueError("未知的 kind: %r" % kind)
