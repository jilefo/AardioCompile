# aac — aardio 命令行编译器

> **纯命令行 aardio 编译工具，编译运行全程不弹出 IDE 窗口，支持生成独立 EXE。**

[English](#english-quick-start) | [简体中文文档](#目录)

---

## English Quick Start

`aac` turns [aardio](https://www.aardio.com/) projects into standalone Windows
EXEs **from the command line** — no IDE window pops up during the build, which
makes it usable in CI. It drives the locally installed aardio IDE once to
publish a *runtime host*, and from then on every build is just
`dumpcode` + pack.

Prerequisites: Windows, Python 3.8+, and a locally installed aardio.

```bat
:: 1. tell the build script where aardio lives (once per machine)
set AARDIO_EXE=C:\path\to\aardio\aardio.exe

:: 2. build aac itself and install it next to aardio
python build.py all

:: 3. use it
aac build myproject --out=myapp.exe
```

The full documentation below is in Chinese. Key entry points:

| If you want to… | read |
|---|---|
| install & first build | [二、首次安装](#二首次安装仅需一次) |
| see every subcommand | [三、子命令详解](#三子命令详解) |
| understand why it works | [一、工具概览](#一工具概览) |
| troubleshoot a failure | [十、FAQ](#十faq) |
| change the code safely | [流程：改代码后必跑的四道门禁](#流程改代码后必跑的四道门禁) |
| known limits | [十五、已知限制](#十五已知限制做不到--没做的事) |

Demo recording: [`aac.mp4`](./aac.mp4) — what the whole flow looks like
(≈4 MB, included in this repository).

License: **MIT** — see [`LICENSE`](./LICENSE). Note that aardio itself is a
separate third-party product with its own license; this repository ships none
of aardio's source and merely invokes the installed IDE as an external tool.

---

## 目录

- [一、工具概览](#一工具概览)
- [二、首次安装（仅需一次）](#二首次安装仅需一次)
- [三、子命令详解](#三子命令详解)
  - [3.1 build — 编译完整工程](#31-build--编译完整工程)
  - [3.2 compile — 编译单文件](#32-compile--编译单文件)
  - [3.3 run — 运行脚本](#33-run--运行脚本)
  - [3.4 exec — 运行工程包](#34-exec--运行工程包)
  - [3.5 info — 查看包信息](#35-info--查看包信息)
  - [3.6 version — 版本与内核指纹](#36-version--版本与内核指纹)
- [四、独立 EXE 生成](#四独立-exe-生成)
- [五、多模块工程开发](#五多模块工程开发)
- [六、构建信息注入](#六构建信息注入)
- [七、实际场景示例](#七实际场景示例)
  - [场景 1：CI/CD 自动构建](#场景-1cicd-自动构建)
  - [场景 2：批量编译多个工程](#场景-2批量编译多个工程)
  - [场景 3：开发调试工作流](#场景-3开发调试工作流)
  - [场景 4：发布带版本号的构建](#场景-4发布带版本号的构建)
  - [场景 5：源码保护分发](#场景-5源码保护分发)
- [八、.aproj 工程文件格式](#八aproj-工程文件格式)
- [九、退出码与输出约定](#九退出码与输出约定)
- [十、FAQ](#十faq)
- [十一、包格式 v2](#十一包格式-v2)
- [十二、回归测试](#十二回归测试)
- [十三、已修复的致命 BUG](#十三已修复的致命-bug)
- [十四、工程内的辅助工具](#十四工程内的辅助工具)
- [十五、已知限制（做不到 / 没做的事）](#十五已知限制做不到--没做的事)
- [十六、开源相关](#十六开源相关)
  - [流程：改代码后必跑的四道门禁](#流程改代码后必跑的四道门禁)
  - [16.2 本机路径是怎么解耦的](#162-本机路径是怎么解耦的)
  - [16.3 许可证与第三方声明](#163-许可证与第三方声明)

---

## 一、工具概览

### 核心原理

```
源码 .aardio ──dumpcode──> 字节码 ──打包──> .appkg 字节码包
                                 ──追加到宿主──> 独立 .exe（双击即运行）
```

| 技术 | 说明 |
|------|------|
| `dumpcode(源码)` | aardio 内置函数，编译源码为字节码（只编译不执行） |
| `loadcode(字节码)` | aardio 内置函数，加载字节码为可执行函数对象 |
| `.appkg` | aac 定义的字节码包格式，包含清单 + 所有文件的字节码流 |
| 独立 EXE | 运行时宿主 `aardioHost.exe` + 追加的字节码载荷 |

### 演示录屏

[`aac.mp4`](./aac.mp4)（随仓库发布，约 4 MB）：从 `build.py all` 一键自举，
到用 `aac build` 发布一个工程、运行它、再到缺库报告的完整流程。
先看一遍比读十页文档快。

### 文件结构

```
<仓库根目录>\
│
├── aac.aardio               ← 编译器源码（唯一源，改这里）
├── aardioHost.aardio        ← 运行时宿主源码（唯一源，改这里）
├── lib\aacpkg.aardio        ← 包格式编解码（编译器与宿主共享的唯一源）
│
├── build.py                 ← 同步源码 + 静默发布 + 发布后冒烟（IDE 自动化）
├── run_tests.py             ← 回归测试（52 个用例）
│
├── aac-runner\              ← IDE 引导工程①：发布生成 aac.exe
│   ├── default.aproj
│   └── main.aardio          ← [自动生成] = lib/aacpkg.aardio + aac.aardio
│
├── aardioHost-runner\       ← IDE 引导工程②：发布生成 aardioHost.exe
│   ├── default.aproj
│   └── main.aardio          ← [自动生成] = lib/aacpkg.aardio + aardioHost.aardio
│
├── tests\fixtures\          ← 测试用工程（含故意写错的 badproj、验证排除的 exclproj）
│   └── multimod\            ← 示例工程（构建信息 / 模块加载 / 参数 / 退出码）
│       ├── default.aproj
│       ├── main.aardio
│       └── lib\utils.aardio
│
│   ── 质量工具（详见「十四、工程内的辅助工具」）──
├── host_grow.py             ← 宿主预埋库渐进扩容（分批真发布 + 真冒烟）
├── corpus_test.py           ← 真实开源工程压测（--integrity 顺带验证不改用户源码）
├── dep_scan.py              ← 语料依赖扫描：统计到底缺哪些库
├── audit.py                 ← 源码静态陷阱审计（aardio 语言级坑）
├── mutation_test.py         ← 给 audit.py 做体检：植入已知 bug 必须报红
├── lib_probe.py             ← 单库体检：找「一 import 就出事」的库
├── host_import_bisect.py    ← 复现宿主启动期全量 import 并二分定位
│
│   ── 运行时产生的数据文件 ──
├── blacklist.txt            ← 实测会杀死产物的库，永不预埋
├── pending_libs.txt         ← 待补库清单（host_grow 的输入）
├── added_libs.txt           ← 已补进去的库（留档）
├── corpus_latest.json       ← 最近一次语料压测结果
├── depscan_latest.json      ← 最近一次依赖扫描结果
├── lib_probe.json           ← 最近一次单库体检结果
│
└── aac-readme.md            ← 本文档
```

> **唯一源原则**：`aac-runner\main.aardio` 和 `aardioHost-runner\main.aardio`
> 都是 `build.py` 自动生成的（把 `lib/aacpkg.aardio` 内联到源码顶部），
> **不要手工编辑**。改根目录的 `aac.aardio` / `aardioHost.aardio` / `lib\aacpkg.aardio` 就行。

---

## 二、首次安装（仅需一次）

> **为什么需要这一步？** `aardio.exe` 是 IDE 程序，不能直接执行 `.aardio` 脚本。必须先用 IDE 发布出 `aac.exe` 这个命令行工具，之后所有操作都走纯命令行。

### 一键发布（推荐）

```bat
cd /d <仓库根目录>
python build.py all
```

> 下文所有的 `<仓库根目录>` 都指你 clone 后得到的那个文件夹，路径因人而异。

这一条命令会：

1. 把 `lib\aacpkg.aardio` 内联进两个 runner 工程；
2. 静默启动 IDE 发布 `aac.exe` 与 `aardioHost.exe`（不弹窗、不误杀已开的 IDE）；
3. 把产物拷到 `%AARDIO_HOME%\`（可用 `--deploy-dir` 改）。

全过程约 17~33 秒（含两个工程各自的发布后冒烟），不需要手工点 IDE。

> **跑完构建不应弄脏工作区**：aardio IDE 每次发布都会自增 `default.aproj` 里的
> `FileVersion` / `ProductVersion`。这两个数字与本工程无关，却会让每次构建后
> `git status` 变脏。`build.py` 在发布前后各归一一次（回归用例
> `aproj_version_churn_is_normalized` 盯着这件事），所以正常跑完应该是干净的。
> **发布后必定关 IDE**：`build.py` 用 `try/finally` 包住整个发布流程，
> 正常、失败、异常三条路径都会把 IDE 关掉。曾经没有这层保护，
> 异常重试会在后台积累十几个隐藏 IDE 实例，直接拖垮机器。

### 手工发布（IDE 出问题时兜底）

1. 打开 aardio IDE
2. 菜单 → 文件 → 打开工程 → 选择 `aac-runner\default.aproj`（宿主则是 `aardioHost-runner\default.aproj`）
3. 按 **F7** 发布
4. 把 `dist\aac.exe` / `dist\aardioHost.exe` 拷到 `%AARDIO_HOME%\`

也可以只发布单个工程：

```bat
python build.py aac-runner --out %AARDIO_HOME%\aac.exe
python build.py aardioHost-runner --out %AARDIO_HOME%\aardioHost.exe
```

### 只同步源码（不发布）

```bat
python build.py sync
```

### 配置环境变量

把 **`aac.exe` 所在的部署目录**（默认 `%AARDIO_HOME%`，即第 2 步 `build.py all` 拷贝产物的地方）
加入系统 PATH，之后任意位置可用 `aac` 命令。注意加的是**部署目录而不是仓库根目录** ——
仓库根里没有 `aac.exe`：

```bat
setx PATH "%PATH%;%AARDIO_HOME%"

:: 验证安装（重新开一个终端让 PATH 生效）
aac version --no-pause
```

> `%AARDIO_HOME%` 是本文档里指代「你本机 aardio 安装目录」的记号，不是真实存在的环境变量。
> 实际地址随每个人的安装位置而定；你也可以换个地方部署（`--deploy-dir`），PATH 跟着改即可。

### 相对路径与当前目录（初次使用请读这一段）

**现象**：`cd` 到自己的工程目录后执行 `aac build myproj`，却报「myproj 不存在」；
但换成绝对路径就正常。

**原因**（aardio 的语言级行为，不是 aac 的 bug）：aardio 发布的独立 EXE 会在
任何用户代码执行**之前**，把进程的当前目录强制设为 EXE 所在目录。即使写个不含任何
`import` 的脚本，第一条语句读到的当前目录也已经是 EXE 目录 —— 进程内部无从还原你站在哪。

**2.4.0 起的处理**：在 **cmd.exe** 里无需再为这件事操心。cmd 会为每个驱动器维护一个隐藏
环境变量 `<盘符>:=<该盘当前目录>`（per-drive CWD）**并继承给子进程**，
`aac` 启动时据此把真实位置捞回来：

```bat
D:\work> aac build myproj          :: 2.4.0 起正常：自动按 D:\work 解析
```

前提是**只存在一条**这样的变量。若同时有多条（cmd 里切过多个盘），
aac 无法判断你到底站在哪个盘 —— 此时不猜，明确报错并给出下面三种写法。

**PowerShell / Git-Bash / CI** 不维护这种变量，拿不到就得显式告知：

```bat
rem 写法1：显式基准目录（最稳，CI 推荐）
aac build myproj --cwd=D:\work

rem 写法2：绝对路径
aac build D:\work\myproj

rem 写法3：用随包的包装器 aac.cmd（它会把 %CD% 注入成 --cwd）
aac.cmd build myproj
```

> **PATH 的小陷阱**：`PATHEXT` 里 `.EXE` 排在 `.CMD` 前面，所以当同一个目录里
> 同时有 `aac.exe` 和 `aac.cmd` 时，敲 `aac` 走的**总是裸 EXE**，包装器不会被执行。
> 要用写法 3 就请完整敲 `aac.cmd`，或者自己给终端配一个别名。

### 完成

从此**不再需要打开 IDE**，所有编译操作都在命令行完成。

---

## 三、子命令详解

### 3.1 build — 编译完整工程

**功能：** 将完整的 aardio 工程编译为 `.appkg` 字节码包，并可选生成独立 `.exe`。

**语法：**

```bat
aac build <工程目录 或 .aproj文件> [--out=路径] [--name=应用名] [--ver=版本号]
          [--host=aardioHost.exe路径] [--no-exe] [--exclude=目录名,目录名]
          [--no-pause] [--quiet] [--log=文件]
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `<工程目录>` | 包含 `.aproj` 文件的目录路径 |
| `<.aproj文件>` | 直接指定 `.aproj` 工程文件路径 |
| `--out=路径` | 三种语义见下表 |
| `--name=应用名` | 覆盖应用名（优先级最高） |
| `--ver=版本号` | 覆盖工程中的版本号 |
| `--host=路径` | 指定 `aardioHost.exe`（用于生成独立 EXE） |
| `--no-exe` | 只生成 `.appkg`，不生成独立 EXE |
| `--exclude=a,b` | **追加**排除的目录名（默认已排除 `dist` `.build` `bin` `obj` `.git` `.svn` `node_modules` `.vscode`） |
| `--no-pause` | 结束时不暂停（CI 必须加） |
| `--log=文件` | 输出镜像落盘（隐含 `--no-pause`，CI 排错必备） |
| `--quiet` / `-q` | 只输出 `[OK]` / `[ERR]` / `[WARN]` |

`--out` 的三种语义（这里旧版本有个坑，2.0 已修正）：

| 写法 | 含义 |
|------|------|
| `--out=D:\dist` 或以 `/` `\` 结尾 | **目录**，PKG 与 EXE 都输出到该目录 |
| `--out=D:\dist\myapp.exe` | 独立 EXE 的完整路径；PKG 放同目录、同名 `.appkg`，应用名取文件名 |
| `--out=D:\dist\myapp.appkg` | 包文件路径；EXE 放同目录、同名 `.exe` |

**应用名取值顺序：** `--name` → `--out` 的文件名 → `.aproj` 的 `output` → `.aproj` 的 `name` → 工程目录名。
**输出目录顺序：** `--out` 指定的目录 → `.aproj` 的 `publishDir` → 工程目录。

**编译流程：**

1. 解析 `.aproj`（XML 宽容解析）提取输出文件名、版本号、`publishDir`
2. 递归收集所有 `.aardio` 源文件（排除构建目录，按路径排序保证可复现）
3. **在内存中**把 `APP_NAME` / `APP_VERSION` / `BUILD_TIME` 拼到 `main.aardio` 前面
   （磁盘上的源码一个字节都不动）
4. 逐文件 `dumpcode` 编译为字节码；**失败会汇总所有文件再退出**，一次看全问题
5. 打包为 v2 格式 `.appkg`（带内核指纹 + CRC）
6. 如果找到 `aardioHost.exe`，复制宿主 + 追加载荷 = 独立 `.exe`

**示例：**

```bat
:: 最简用法：编译当前目录下的工程
aac build . --no-pause

:: 指定工程目录
aac build "D:\myproject" --no-pause

:: 直接指定 .aproj 文件
aac build "D:\myproject\default.aproj" --no-pause

:: 指定输出目录
aac build "D:\myproject" --out="D:\output" --no-pause

:: 指定输出 EXE 路径（需要 aardioHost.exe）
aac build "D:\myproject" --out="D:\output\myapp.exe" --no-pause

:: 覆盖版本号
aac build "D:\myproject" --ver=2.1.0 --no-pause

:: 指定 aardioHost.exe 路径
aac build "D:\myproject" --host="D:\tools\aardioHost.exe" --no-pause

:: 组合使用
aac build "D:\myproject" --out="D:\release\myapp.exe" --ver=3.0.0 --host="D:\tools\aardioHost.exe" --no-pause

:: CI 用法：日志落盘 + 只出包不出 EXE
aac build "D:\myproject" --out="D:\release" --no-exe --log="D:\release\build.log"

:: 追加排除目录（默认已排除 dist/.build/.git 等）
aac build "D:\myproject" --exclude=temp,generated --no-pause
```

**输出示例（有 aardioHost.exe 时）：**

```
[INFO] 工程目录: D:/Projects/MyApp
[INFO] 工程文件: D:/Projects/MyApp/default.aproj
[INFO] 应用名称: MyApp
[INFO] 版本号  : 1.0.0.0
[INFO] 输出目录: D:/Projects/MyApp/dist
[INFO] 发现源文件: 3 个
[INFO] ---- 开始编译 ----
[OK] main.aardio (1234 字节)
[OK] lib/config.aardio (890 字节)
[OK] lib/utils.aardio (567 字节)
[INFO] 运行时宿主: %AARDIO_HOME%/aardioHost.exe
[OK] 包文件: D:/Projects/MyApp/dist/MyApp.appkg (2891 字节)
[OK] 独立EXE: D:/Projects/MyApp/dist/MyApp.exe (1498955 字节)

==========================================
  构建完成
  应用名称 : MyApp
  应用版本 : 1.0.0.0
  源文件数 : 3
  包文件   : D:/Projects/MyApp/dist/MyApp.appkg (2891 字节)
  独立EXE  : D:/Projects/MyApp/dist/MyApp.exe
==========================================

[OK] BUILD SUCCESS
[OK] PKG=D:/Projects/MyApp/dist/MyApp.appkg
[OK] EXE=D:/Projects/MyApp/dist/MyApp.exe

运行方式:
  D:/Projects/MyApp/dist/MyApp.exe
```

最后三行是给 CI / AI 解析的固定格式：成功必有 `BUILD SUCCESS`，
随后是 `PKG=` 与 `EXE=`（用了 `--no-exe` 时没有 `EXE=`）。

---

### 3.2 compile — 编译单文件

**功能：** 将单个 `.aardio` 源文件编译为 `.dump` 字节码文件。

**语法：**

```bat
aac compile <源文件.aardio> <输出.dump> [--no-pause]
```

**示例：**

```bat
:: 编译单个文件
aac compile "D:\src\hello.aardio" "D:\out\hello.dump" --no-pause

:: 批量编译目录下所有 .aardio 文件（配合 for 命令）
for %f in ("D:\src\*.aardio") do aac compile "%f" "D:\out\%~nf.dump" --no-pause
```

**输出示例：**

```
[INFO] 正在编译: D:/src/hello.aardio
[OK] 编译成功: D:/src/hello.aardio -> D:/out/hello.dump
[INFO] 字节码大小: 456 字节
[INFO] 运行: aac run "D:/out/hello.dump"
[INFO] 提示: 字节码无法还原源代码，可保护源码;
[INFO] 提示: aardio 升级后旧字节码会提示 bad code，重新 compile 即可。
```

**注意事项：**
- 字节码与 aardio 内核版本绑定，升级 aardio 后需重新编译
- 字节码无法还原回源代码，可保护源码

---

### 3.3 run — 运行脚本

**功能：** 直接运行 `.aardio` 源码文件或 `.dump` 字节码文件，无需编译步骤。

**语法：**

```bat
aac run <脚本文件> [参数...] [--no-pause]
```

**示例：**

```bat
:: 运行源码脚本
aac run "D:\scripts\hello.aardio" --no-pause

:: 运行字节码
aac run "D:\out\hello.dump" --no-pause

:: 传递参数给脚本
aac run "D:\scripts\process.aardio" --input="data.txt" --verbose --no-pause
```

**说明：**
- `run` 使用 `loadcode` 直接加载并执行，不生成中间文件
- 既能运行 `.aardio` 源码，也能运行 `.dump` 字节码
- 脚本中的 `_ARGV` 为 aac 进程的完整参数列表（含 `run`、脚本路径等），非仅脚本参数

---

### 3.4 exec — 运行工程包

**功能：** 加载 `.appkg` 字节码包并执行其中的 `main.aardio`。

**语法：**

```bat
aac exec <包文件.appkg> [参数...] [--no-pause]
```

**示例：**

```bat
:: 运行工程包
aac exec "D:\output\MyApp.appkg" --no-pause

:: 传递参数
aac exec "D:\output\MyApp.appkg" --config="prod.ini" --no-pause
```

**说明：**
- `.appkg` 包含工程所有文件的字节码，`exec` 会还原完整的运行环境
- 包内 `main.aardio` 可使用 `loadModule()` 加载其他模块
- 不需要 `aardioHost.exe`，`aac.exe` 本身就能运行 `.appkg`
- `exec` 后面的参数会**作为函数实参**传入 `main.aardio`，同时也放进全局 `APP_ARGS`
  （`_ARGV` 是内核常量改不了，里面仍是 aac 自己的完整参数）

---

### 3.5 info — 查看包信息

**功能：** 打印 `.appkg`（或独立 EXE）里的元信息与文件清单，排错用。

**语法：**

```bat
aac info <包文件.appkg 或 独立EXE> [--no-pause]
```

**输出示例：**

```
文件    : D:/output/MyApp.appkg
格式版本: 2
应用名  : MyApp
版本    : 1.0.0
构建时间: 2026/10/12 23:26:11
内核指纹: 812207111（本机 812207111）
CRC     : 3721093（校验通过）
字节码  : 2891 字节

文件清单:
  main.aardio  (1234 字节)
  lib/utils.aardio  (567 字节)
```

独立 EXE 也支持宿主参数 `--pkg-info`，效果相同：

```bat
MyApp.exe --pkg-info
```

**典型用途**

- 拿到的 EXE 跑不起来：先看「内核指纹」是否与本机一致，不一致就是 aardio 版本换了，重新 build 即可；
- 怀疑漏打包某个模块：看文件清单；
- 包被截断/损坏：CRC 校验会直接报错而不是运行到一半崩。

---

### 3.6 version — 版本与内核指纹

```bat
aac version --no-pause
```

```
aac 2.0.0
包格式 : v2
内核指纹: 812207111
```

**内核指纹**是「一段固定源码编译出的字节码 CRC32」，用来标识 aardio 内核版本。
它会被写进每个包里：宿主加载时发现与本机不一致就告警，
避免只看到一句莫名的 `bad code`。升级 aardio 后重新 build 即可。

---

## 四、独立 EXE 生成

### 工作原理

```
[aardioHost.exe 原始字节] + [__AARDIO_PKG__] + [10位清单长度] + [清单] + [字节码流]
```

1. `aac build` 编译工程所有文件为字节码，打包为载荷
2. 复制 `aardioHost.exe`，将载荷追加到末尾
3. 生成的 EXE 启动时：
   - 读取自身文件，定位 `__AARDIO_PKG__` 标记
   - 解析清单，还原 PKG 表（相对路径 → 字节码）
   - 提供全局 `loadModule()` 函数
   - 加载并执行 `main.aardio`

### aardioHost.exe 查找顺序

`aac build` 按以下顺序自动查找 `aardioHost.exe`：

1. `--host=` 参数指定的路径
2. `aac.exe` 同目录下的 `aardioHost.exe`
3. `aac.exe` 上级目录下的 `aardioHost.exe`

### 生成独立 EXE

```bat
:: 方法 1：把 aardioHost.exe 放在 aac.exe 同目录（推荐，自动检测）
:: aac.exe 和 aardioHost.exe 都在部署目录 %AARDIO_HOME%\（build.py all 的默认落点）
aac build "D:\myproject" --no-pause
:: → 自动生成 D:\myproject\myproject.exe

:: 方法 2：用 --host 参数指定 aardioHost.exe 路径
aac build "D:\myproject" --host="D:\tools\aardioHost.exe" --no-pause

:: 方法 3：用 --out 指定 EXE 输出路径
aac build "D:\myproject" --out="D:\release\MyApp_v2.exe" --no-pause
```

### 生成的 EXE 特性

- **完全独立**：不需要安装 aardio，不需要任何外部文件
- **双击即运行**：和普通 EXE 一样使用
- **源码保护**：内嵌字节码，无法还原源代码
- **体积**：约 `aardioHost.exe` 大小 + 字节码载荷大小

---

## 五、多模块工程开发

### 工程结构示例

```
MyApp\
├── default.aproj          ← 工程文件
├── main.aardio            ← 主入口（必须有）
├── lib\
│   ├── utils.aardio       ← 子模块
│   └── config.aardio      ← 配置模块
└── res\
    └── data.json          ← 资源文件（不会被打包，需自行处理分发）
```

> **注意：** `aac build` 只收集 `.aardio` 源文件编译为字节码包。非 `.aardio` 文件（如 `.json`、`.xml`、图片等）不会包含在 `.appkg` 或独立 EXE 中。如需资源文件，请自行复制到输出目录或通过其他方式分发。

### 模块加载规范

```aardio
// ========================================
// main.aardio — 主入口
// ========================================
import console;
import process;
import fsys;

// 标准库用 import 加载
import math;

// 工程内自定义模块用 loadModule() 加载
var utils = loadModule("lib/utils.aardio");
var config = loadModule("lib/config.aardio");

// 使用模块
utils.init();
var dbHost = config.get("db_host");

console.log("应用启动完成!");
```

```aardio
// ========================================
// lib/utils.aardio — 工具模块
// ========================================
import console;
import string;

// 模块内的代码在 loadModule 时立即执行
console.log("utils 模块已加载");

// 可以返回一个函数或表供调用者使用
var greet = function(name){
    console.log("Hello, " ++ name ++ "!");
};

// 返回函数作为模块接口
return greet;
```

### 关键规则

| 类型 | 加载方式 | 示例 |
|------|----------|------|
| 标准库 / 扩展库 | `import` | `import console;` `import fsys;` |
| 工程内自定义模块 | `loadModule()` | `var m = loadModule("lib/utils.aardio");` |

- `loadModule()` 的路径是相对于工程根目录的
- 路径分隔符统一用 `/`（正斜杠）
- 在生成的独立 EXE 中，`loadModule()` 从内嵌载荷加载模块

---

## 六、构建信息注入

`aac build` 会自动向 `main.aardio` 注入构建信息。在 `main.aardio` 中可以直接使用以下全局变量：

```aardio
// main.aardio
import console;

console.log("应用名称: " ++ APP_NAME);       // 从 .aproj 提取
console.log("版本号: " ++ APP_VERSION);       // 从 .aproj 或 --ver 参数
console.log("构建时间: " ++ BUILD_TIME);      // Unix 时间戳
```

**注入机制（2.0 起：只在内存里拼，绝不写磁盘）**

- aac 读取 `main.aardio` 后，在**内存**中把构建信息块拼到源码最前面再编译；
- 磁盘上的 `main.aardio` **一个字节都不会被改动**，没有备份文件，也没有回滚逻辑；
- 因此编译失败、进程被 Ctrl-C 中断，源码都不会留下污染，可无限次重复构建。

> 1.x 的做法是「写回文件 + 备份 + 失败回滚」，一旦中断就会把注入块留在源码里，
> 下次构建还会拼出嵌套注释导致语法崩溃——这是 2.0 重点修掉的问题。
> 如果你的源码里还残留着 `/*__BUILD_INFO_BEGIN__*/...` 这一段，直接删掉即可，
> aac 在读取时也会自动剥离它。

**手动指定版本号：**

```bat
aac build "D:\myproject" --ver=2.3.1 --no-pause
```

---

## 七、实际场景示例

### 场景 1：CI/CD 自动构建

**GitHub Actions 示例：**

```yaml
name: aardio-build
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: 准备 aardio 环境
        shell: cmd
        run: |
          :: 下载 aardio 绿色版到 C:\aardio
          :: 下载 aac.exe 和 aardioHost.exe 到 C:\aardio
          :: 将 C:\aardio 加入 PATH

      - name: 编译工程
        shell: cmd
        run: |
          aac build "src\myapp.aproj" --out=dist\myapp.exe --ver=1.0.%GITHUB_RUN_NUMBER% --host=C:\aardio\aardioHost.exe --no-pause

      - name: 验证产物
        shell: cmd
        run: |
          if not exist dist\myapp.exe exit /b 1
          dir dist\myapp.exe

      - name: 上传产物
        uses: actions/upload-artifact@v4
        with:
          name: myapp
          path: dist\myapp.exe
```

**Jenkins 示例：**

```groovy
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                bat 'aac build "src\\myapp.aproj" --out=dist\\myapp.exe --ver=%BUILD_NUMBER% --no-pause'
            }
        }
        stage('Test') {
            steps {
                bat 'dist\\myapp.exe --self-test'
            }
        }
    }
}
```

**关键点：**
- 所有命令必须加 `--no-pause`，否则 CI 会卡死
- 退出码 0 = 成功，1 = 失败，CI 系统可据此判断构建结果
- 输出以 `[OK]` / `[ERR]` 前缀标识，方便日志解析

---

### 场景 2：批量编译多个工程

```bat
@echo off
chcp 65001 >nul

:: 批量编译目录下所有工程
set PROJECTS=D:\Projects\App1 D:\Projects\App2 D:\Projects\App3
set OUTPUT=D:\Release

for %%P in (%PROJECTS%) do (
    echo ========================================
    echo 正在编译: %%P
    echo ========================================
    aac build "%%P" --out="%OUTPUT%" --no-pause
    if %ERRORLEVEL% neq 0 (
        echo [ERR] 编译失败: %%P
        exit /b 1
    )
)

echo 全部编译完成!
```

---

### 场景 3：开发调试工作流

```bat
:: 1. 快速运行源码（不编译，直接执行，适合开发调试）
aac run "D:\myproject\main.aardio"

:: 2. 编译单文件检查语法
aac compile "D:\myproject\main.aardio" "D:\temp\main.dump" --no-pause

:: 3. 完整编译工程
aac build "D:\myproject" --no-pause

:: 4. 运行编译后的包验证
aac exec "D:\myproject\myproject.appkg" --no-pause

:: 5. 运行生成的独立 EXE
"D:\myproject\myproject.exe"
```

---

### 场景 4：发布带版本号的构建

```bat
:: 从命令行指定版本号
aac build "D:\myproject" --ver=2.5.0 --out="D:\release\MyApp_v2.5.0.exe" --no-pause

:: 配合 Git 标签自动获取版本号
for /f %%v in ('git describe --tags --abbrev^=0') do set VER=%%v
aac build "D:\myproject" --ver=%VER% --out="D:\release\MyApp_%VER%.exe" --no-pause
```

---

### 场景 5：源码保护分发

```bat
:: 方案 A：分发 .appkg 包（需要 aac.exe 才能运行）
aac build "D:\myproject" --no-pause
:: → 生成 myproject.appkg，分发给有 aac.exe 的用户
::   运行方式：aac exec myproject.appkg

:: 方案 B：分发独立 EXE（不需要任何依赖）
aac build "D:\myproject" --no-pause
:: → 生成 myproject.exe（需要 aardioHost.exe）
::   运行方式：双击即可

:: 方案 C：只分发字节码（单文件保护）
aac compile "D:\myproject\main.aardio" "D:\release\main.dump" --no-pause
:: → 生成 main.dump，源码无法还原
```

---

## 八、.aproj 工程文件格式

aac 使用**宽容的 XML 解析**读取 `.aproj` 文件，兼容以下格式：

### 标准格式（aardio IDE 生成）

```xml
<?xml version="1.0" encoding="utf-8"?>
<project ver="10" name="MyApp" libEmbed="true" output="MyApp.exe"
         ui="console" CompanyName="" FileDescription="我的应用"
         LegalCopyright="" ProductName="MyApp" InternalName="MyApp"
         FileVersion="1.0.0.0" ProductVersion="1.0.0.0"
         publishDir="/dist/" dstrip="false">
    <file name="main.aardio" path="main.aardio" comment="主程序"/>
    <folder name="lib" path="lib" embed="true"/>
</project>
```

### aac 提取的关键信息

| 字段 | 来源 | 说明 |
|------|------|------|
| 输出文件名 | `output` 属性 或 `<OutFileName>` 等子元素 | 用于命名输出文件 |
| 版本号 | `FileVersion` 属性 或 `<Version>` 子元素 | 注入到 `APP_VERSION` |
| 工程名 | `name` 属性 | 用于 `APP_NAME` 兜底 |

> 命令行参数 `--out` / `--ver` 优先级最高，会覆盖 `.aproj` 中的值。

---

## 九、退出码与输出约定

### 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `1` | 失败（语法错、路径不存在、未知子命令、未捕获异常等） |
| `n` | 独立 EXE：被打包程序的 `main.aardio` `return` 出来的数字 |

实测矩阵（`python run_tests.py` 覆盖）：

| 场景 | 退出码 |
|------|--------|
| `build` 成功 | 0 |
| 连续 build 两次 | 0 / 0 |
| 源码语法错 | 1 |
| 工程路径不存在 | 1 |
| 未知子命令 | 1 |
| `version` / `help` / `info` | 0 |
| 独立 EXE 正常运行 | 0 |
| `host-add` 全部已预埋 / `host-del` 本来就没有 | **0**（幂等命令的第二遍不算失败） |
| `host-add` 有库被安全策略拒绝、或库名不存在 | 1 |

> aardio 脚本的 `return` 值**不会**成为进程退出码，宿主 `loadcode` 执行完恒返回 0。
> 所以 aac 与宿主都在出口显式调用 `System.Environment.Exit(code)`。

### 输出标识

| 前缀 | 含义 | 示例 |
|------|------|------|
| `[OK]` | 成功操作 | `[OK] 编译成功: main.aardio (1234 字节)` |
| `[ERR]` | 错误 | `[ERR] 编译失败: main.aardio（请检查该文件语法）` |
| `[INFO]` | 信息提示 | `[INFO] 工程目录: D:/Projects/MyApp` |
| `[WARN]` | 警告 | `[WARN] 读取宿主失败` |

### `--log` 日志镜像（CI / AI 调用必读）

`console.log` 在 aardio 里是走 `WriteConsoleB` **直写控制台句柄**的，
把它重定向到文件或管道**什么都拿不到**（既看不到 `[OK]`，也看不到 `[ERR]`）。
因此 `aac` 与 `aardioHost` 都支持：

```bat
aac build . --out=app.exe --log=build.log --no-pause
```

加 `--log=<路径>` 后，所有 `console.log` 内容会同步**追加**写入该文件
（目录不存在会自动创建）。`--log` 会自动隐含 `--no-pause`，CI 友好。
宿主生成的独立 EXE **同样支持 `--log=`**，可用于排查运行期错误。

宿主专用参数会从参数表里剔除，被打包程序读 `APP_ARGS` 看到的是干净参数：

| 参数 | 作用 |
|------|------|
| `--log=<文件>` | 把宿主与载荷的全部输出镜像落盘 |
| `--pkg-info` | 只打印包信息并退出，不执行程序 |
| `--trace` | 配合 `--log` 打开**启动期旁路**诊断（默认关闭，详见下） |

#### `--trace`：产物"静默失败"时才开

诊断信息直接写文件、完全绕开 `console` —— 因为一旦 `console.log`
这条链路本身出问题，任何走 console 的诊断都不可信。代价是刷行，
所以默认关闭，避免把用户自己的输出淹掉：

```bat
myapp.exe --log=run.log            :: 只有应用自己的输出
myapp.exe --log=run.log --trace    :: 额外有 [TRACE] init: 逐阶段记录
```

`[TRACE]` 会依次记下：进入解包 → 自身路径 → 读入字节数 → 解析结果 →
字节码大小 → `loadcode` 结果 → 载荷是否执行、返回什么。
产物起不来且日志一个字都没有时，这一串能直接指出死在哪一步。

---

## 十、FAQ

**Q: 生成的 EXE 是真正独立的吗？**
A: 是。生成的 EXE 内嵌字节码，双击即运行，不需要安装 aardio，不需要任何外部文件。

**Q: 为什么需要先发布 aac.exe？**
A: `aardio.exe` 是 IDE 程序，不能直接执行脚本。`aac.exe` 是用 IDE 发布一次的命令行工具，发布后终身命令行使用。

**Q: 没有 aardioHost.exe 能用吗？**
A: 能。没有宿主时 `build` 只生成 `.appkg` 包，可通过 `aac exec` 运行。只是无法生成独立 EXE。

**Q: 升级 aac 之后旧 EXE 还能跑吗？**
A: 分两种情况。aac 2.0 产出的包是 v2 格式（多了元信息与 CRC），**必须搭配 2.0 版宿主**；
旧宿主解析 v2 包会把元信息行当成文件记录，导致字节错位。
反过来，2.0 宿主**可以**正常运行 v1 旧包（缺 CRC 字段时自动跳过校验）。
所以升级后请同时发布新宿主，并用新宿主重新 build 所有工程。

**Q: 被打包的程序怎么拿到自己的命令行参数？**
A: 优先读全局 `APP_ARGS`——它已被剔除宿主专用参数（`--log=` 等）。
`_ARGV` 是内核常量，宿主不能改写它（写了会抛
`Can't modify the constant : '_ARGV'`），所以里面仍会保留 `--log=`。
兼容写法：

```aardio
var argv = _ARGV;
if(APP_ARGS != null){ argv = APP_ARGS; }
```

**Q: 被打包的程序怎么控制退出码？**
A: 在 `main.aardio` 顶层 `return 数字`，宿主会把它原样作为进程退出码。
未捕获异常一律返回 1。

**Q: 编译时报 `Cannot include file:/res/xxx` 怎么办？**
A: 源码里用了 `$"/res/xxx"` 这种**编译期文件包含**。路径以 `/` `\` 或 `~/` 开头时，
IDE 按「当前工程目录」解析，而独立命令行程序按**应用基准目录**解析，两边不一样。
`aac build` 已在内存里把这类路径统一补成工程目录下的绝对路径，磁盘源码不动。
若仍报，请确认这个文件在工程目录下**真实存在**（有些仓库把二进制资源 gitignore 掉了，
IDE 里能发布只是因为作者本地有）。

**Q: 提示「宿主未预埋库」，一定要联网下载吗？**
A: **绝大多数不用**。报告分三类，只有 B 类需要联网：

```
【A类】本机 aardio 里就有，只是宿主没预埋  ->  aac host-add xxx --rebuild（离线）
【B类】官方库但本机没装                    ->  IDE 库管理器装一次（联网），再 host-add
【C类】官方清单里也没有                    ->  第三方库或拼错，只能改代码
```

标准库是随 aardio 装在本机的，"补库"只是把它们**重新嵌进宿主**而已。

**Q: 能不能索性把整个标准库都预埋进去？**
A: **不能，而且试过。** 一次性加到 275 个之后，每个产物 EXE 都起不来：
退出码 `-1`、日志一个字都没有 —— 因为混进了 `ide` 这种"给 IDE 用的库"，
导入时找不到 IDE 环境直接把进程干掉。要扩容就走
`python host_grow.py`（分批 + 真发布 + 打真实 EXE 跑一遍 + 失败自动二分定位），
别一次性塞。

**Q: 产物双击没反应、退出码 -1、日志为空，怎么查？**
A: 这类"静默失败"的特征是连 `[ERR]` 都没有，说明死在日志镜像建立之前。
用 `--log=run.log --trace` 跑一次，`[TRACE]` 会记到死在哪一步。
如果连 TRACE 都没写全，说明崩在宿主的 `import` 阶段 —— 十有八九是宿主里
混进了致命库，用 `aac host-del <库名> --rebuild` 剔掉重发。

**Q: `aac libs` 里同一个库出现多次是怎么回事？**
A: 早期 `host-add` 判断"是否已预埋"看的是**宿主 EXE 里的哨兵**，而预埋要等
IDE 发布成功才写进 EXE；一旦那次 `--rebuild` 静默失败，下次补同一个库就会被
再追加一条。现在判定依据换成了**源码里的 import 区块**，写入前还会整体去重。
已经存在重复项时执行 `aac host-add <其中任意一个库名>` 会自动清理，
`build.py` 在发布前也会把重复 import 报成 ERROR（见 13.5）。

**Q: `aac host-add x` 跑第二遍为什么有时返回 0、有时返回 1？**
A: 全部都属于"已预埋"返回 **0**（幂等命令的第二遍不算失败，否则 CI 会断）；
只要有任何一个库被安全策略拒绝、或名字在标准库里找不到，就返回 **1**。

---

## 十一、包格式 v2

```
[宿主原始字节] + "__AARDIO_PKG__" + [10位清单长度] + [清单] + [字节码流]
```

**清单**由若干条记录组成，单字符 `*` 分隔，每条形如 `<字段名>|<值>`：

| 记录 | 示例 | 说明 |
|------|------|------|
| 元信息 | `#crc\|812207111` | 字段名以 `#` 开头，不占字节码 |
| 文件 | `lib/utils.aardio\|567` | 相对路径 + 字节码长度 |

元信息字段：

| 字段 | 说明 |
|------|------|
| `fmt` | 包格式版本（当前 `2`） |
| `kernel` | 编译时的 aardio 内核指纹（`aac version` 可查本机值） |
| `app` / `ver` / `time` | 应用名、版本、构建时间 |
| `crc` | 字节码流的 CRC32，用于完整性校验 |

**为什么不用 `\r\n` 或 JSON 做分隔**（这两条都踩过）：

1. aardio 双引号串里 `"\r\n"` 只是 4 个字面字符，不是换行；
2. `string.split(s, sep)` 按**字符集**拆分，传多字符会被逐字符切开；
3. 竖线在 aardio 模式匹配里是分支符，所以一律用 `string.indexOf` 取子串，不用模式匹配。

**校验规则**（任一条不满足直接判坏包，不静默丢文件）：

- 清单声明的字节数必须**恰好**等于字节码流长度；
- 存在 `crc` 字段时必须与实算 CRC32 一致；
- 载荷标记 `__AARDIO_PKG__` 要**从最后一次出现往前逐个候选尝试**，取第一个能完整解析的
  （宿主自身内嵌的字节码里也有同名字串，见 13.1 第 4 条）。

> 为什么不是简单地取最后一次：`MARK` 这个字符串**本身也会出现在载荷里** ——
> 用 aac 编译 aac 自己时，源码里的 `MARK` 字面量就被打进了字节码，
> 于是最后一次命中的是载荷内部的假标记，报「清单长度无效或数据损坏」。
> 现在的做法是收集全部命中位置倒序尝试，靠「长度恰好用光 + CRC 匹配」
> 区分真假（详见 `lib/aacpkg.aardio` 的 `parseAt`）。

查看任意包的元信息：

```bat
aac info "D:\output\myapp.appkg" --no-pause
```

---

## 十二、回归测试

```bat
python run_tests.py                      :: 全部用例
python run_tests.py -k build             :: 只跑名字含 build 的用例
python run_tests.py --aac %AARDIO_HOME%\aac.exe
```

覆盖 52 个用例（`python run_tests.py` 最后一行会打印总数）：

| 用例 | 验证点 |
|------|--------|
| `version` / `help` | 基本可用，输出内核指纹 |
| `build_success` | 正常构建产出 EXE，日志含 `BUILD SUCCESS` |
| `source_not_polluted` | **构建后磁盘源码 md5 不变**、无注入残留 |
| `build_idempotent` | 连续构建两次都成功 |
| `exe_runs` | 生成的 EXE 能跑，输出 `RESULT:OK` 且退出码 0 |
| `exe_args_passthrough` | 参数（含中文）正确传到包内 |
| `build_badproj_rc1` | 语法错 → rc=1 |
| `build_missing_path_rc1` | 路径不存在 → rc=1 |
| `unknown_cmd_rc1` | 未知子命令 → rc=1 |
| `info` | 能读出格式版本与文件清单 |
| `no_exe_only_pkg` | `--no-exe` 只出 appkg |
| `build_out_dir` | `--out` 指向目录 |
| `exclude_dirs` | `dist/` `.build/` 被排除，`lib/` 保留 |
| `compile_and_run` | 单文件编译 + 字节码运行 |
| `include_root_relative_resolves` | `$"/res/x"` 工程根相对包含按工程目录解析 |
| `host_add_refuses_fatal_lib` | 实测会杀死产物的库（`ide`）默认拒绝 |
| `import_line_with_trailing_comment_agrees_with_build_py` | `import x; // 说明` 必须与 `build.py` 的判定完全一致（否则会制造死循环） |
| `host_add_is_idempotent` | 补同一个库两次只写一条 import；历史重复项自动清理；第二遍 rc=0 |
| `host_del_is_idempotent_and_tidy` | 剔除干净、删不存在的 rc=0、行尾格式不被破坏 |
| `missing_lib_blocked` | 缺库样本**运行时反选**，宿主扩容后不会假红 |
| `static_audit_clean` / `audit_detectors_really_work` / `mutation_test_catches_real_bugs` | 静态审计 + 检测器自检 + 变异测试 |

测试脚本全部通过 `--log=` 读输出，因为 `console.log` 直写控制台句柄，
`subprocess` 重定向 stdout 什么都拿不到。

---

## 十三、已修复的致命 BUG

### 13.1 第一轮（2026-10-12 上午）

> 这一节记录的是「跑不起来」级别的坑，全部由实测定位（探针 EXE + `aac run` + 字节级检查）。
> 修复前 `aac build` 对**任何**工程都返回退出码 `-1` 且零输出。

### 1. `dumpcode(源码字符串)` 根本不可用

```aardio
var bc, err = dumpcode(src);   // 抛: unable to dump given function
```

实测：传字符串必抛异常，只有传**函数对象**才成功（`dumpcode(fn)` → 122 字节）。
正确姿势是先 `loadcode` 编译成函数，再 `dumpcode`：

```aardio
var f, lerr = loadcode(src);
var bc, derr = dumpcode(f);
```

### 2. `string.match` / `string.find` 走模式匹配，`<` 是特殊结构

模式语法里 `<...>` 是**平衡匹配**结构，模式串里出现未闭合的 `<` 直接抛
`malformed pattern (missing '>')`。解析 `.aproj` 时第一步就炸。
**修复**：XML 解析一律改用 `string.indexOf`（纯子串查找，不走模式匹配）。

### 3. `_EXEFILE` 这个全局变量不存在

宿主里 `string.load(_EXEFILE)` 恒为 `null`（aardio 根本没有这个变量）→ 「无法读取自身文件」。
取自身路径要用 **`io._exepath`**（`io._exedir` 取目录）。

### 4. 宿主必须从「最后一次」出现处定位载荷

```aardio
var s, e = string.find(bin, MARK);        // 错: 命中宿主自己内嵌代码里的同名字符串
var s = string.lastIndexOf(bin, MARK);    // 当年迈出的第一步, 后来发现仍不够
```

宿主源码里也写了 `"__AARDIO_PKG__"`，发布后这段字符串就在 EXE 前段，
`string.find` 会命中它，随后按定长清单解析必然报「清单长度解析失败或数据损坏」。

> **后续（2026-10-13）**：`lastIndexOf` 也不够用。`MARK` 这个字符串会
> **出现在载荷内部** —— 用 aac 编译 aac 自己时，源码里的 MARK 字面量被
> 打进了字节码，最后一次命中的反而是假标记。现在的做法是收集全部命中位置
> 倒序尝试，靠「长度恰好用光 + CRC 匹配」区分真假，见第 11 节与
> `lib/aacpkg.aardio` 的 `parseAt`。

### 5. `string.split` 按「字符集」拆，且 `"\r\n"` 不是换行

实测：`"A" ++ "\r\n" ++ "B"` 长度是 **6**（`\r\n` 就是 4 个字面字符）；
`string.split(s, "\r\n")` 把 `A\r\nB` 拆成 **5** 段（逐字符切开）。
结果清单被切碎，`PKG["main.aardio"]` 永远取不到 → 「包内缺少 main.aardio」。

**修复**：清单行分隔符改成**单字符** `SEP = "*"`（`*` 在 Windows 路径里非法，不会与真实路径冲突），
行的字段解析也改用 `string.indexOf(line, "|")`，不用模式匹配（竖线在模式里是分支符）。

### 6. `string.save(path, null)` 非法

第二个参数必须是 string，删文件要用 `fsys.delete(path)`。

### 7. 构建信息被 `//` 整行注释掉

`"\r\n"` 不是真换行，`"//__BUILD_INFO_BEGIN__\r\nvar APP_NAME = ..."` 整块落在同一行，
`APP_NAME` / `APP_VERSION` / `BUILD_TIME` 全部被注释掉（工程里引用会报未定义）。
改为**块注释包成单行**，不依赖换行符：

```aardio
/*__BUILD_INFO_BEGIN__*/var APP_NAME="x";var APP_VERSION="1.0";/*__BUILD_INFO_END__*/
```

### 8. 宿主的 `console.pause()` 会让自动化永久挂起

宿主错误分支里的 `console.pause()` 在 stdin 非交互时（CI / subprocess）会一直等按键。
已从宿主全部移除，出错直接 `return 1`。

### 9. 双引号串里 `\"` 不是转义

`attr ++ "=\""` 会让字符串「跑飞」、括号不闭合（语法错误）。
含双引号的字面量一律用**反引号原义串**：`` attr ++ `="` ``。

### 附：宿主必须预埋工程用到的库

载荷是**运行时 `loadcode`** 的，里面的 `import` 只能命中宿主已嵌入的库。
宿主工程里需要 `import` 一份工程会用到的库（`libEmbed="true"` 会把它们一起打包），
否则运行期报「找不到库」。当前宿主预埋：
`console / fsys / time / key / dotNet / process / string.cmdline`。

### 附：静默发布脚本 `build.py`

工程根目录新增 `build.py`，可对任意 `.aproj` 静默发布（原理同 WM_COMMAND 0x8317）：

```bat
python build.py aac-runner        --out %AARDIO_HOME%\aac.exe
python build.py aardioHost-runner --out %AARDIO_HOME%\aardioHost.exe
```

相比手工按 F7：结束时只终止自己启动的那个 IDE 进程（不做 `taskkill /IM` 全杀），
并会打印 IDE 弹出的对话框标题，便于定位发布失败原因。

**Q: 字节码与 aardio 版本的关系？**
A: 字节码内含内核版本标识。升级 aardio 后需重新发布 `aac.exe`（和 `aardioHost.exe`），然后重新 `build`。

**Q: CI 中卡死不动？**
A: 确保所有调用都加了 `--no-pause` 参数。

**Q: 可以在 PowerShell 中使用吗？**
A: 可以。但 `console.log` 输出可能不被 PowerShell 捕获。建议在 cmd 中使用，或用生成的独立 EXE。

**Q: 杀毒软件误报？**
A: 自打包 EXE 的常见现象，对产物做代码签名或加白名单即可。

**Q: 如何保护源码？**
A: `dumpcode` 产出的字节码无法还原回源代码。无论是 `.appkg` 包还是独立 EXE，都无法提取出原始源码。

**Q: build 时提示 "bad code"？**
A: 字节码与 aardio 内核版本绑定。升级 aardio 后，需要用新版 `aac.exe` 重新编译。

**Q: `import` 和 `loadModule` 的区别？**
A: `import` 加载标准库和扩展库（从 aardio 库路径搜索）。`loadModule` 加载工程内自定义模块（从字节码包内搜索）。

---

### 13.2 第二轮（2026-10-12 下午：退出码 / 应用名 / 注入幂等）

第一轮修复后 aac 已能产出 EXE，但实测仍暴露 5 个问题，本轮全部修掉并回归通过。

### 1. 退出码恒为 0（最致命）

aardio 脚本的 `return` 值**不会**成为进程退出码，宿主 loadcode 执行完恒返回 0。
结果：编译失败时调用方（AI / CI）仍看到 `rc=0`，完全无法判定失败。

修法：显式调用 .NET 退出。注意 `dotNet.import` 的参数是**程序集名**而不是类名：

```aardio
// 错: 报 "加载程序集失败：System.Environment"
var env = dotNet.import("System.Environment");

// 对
var sys = dotNet.import("System");
sys.Environment.Exit(code);
```

所有 `exitErr` / 未捕获异常 / 主出口统一走 `hardExit(rc)`。
实测：成功 rc=0；语法错 / 工程不存在 / 未知子命令 rc=1。

### 2. `--out` 给文件路径时污染应用名

旧代码直接把 `--out` 的完整路径当成应用名，于是 `APP_NAME` 被注入成
`D:/Projects/.../dist/app`，写进双引号串后 `\t` `\d` `\s` 被当转义符，
main.aardio 直接语法崩掉。

修法：只取末段文件名，并去掉 `.exe` / `.appkg` 后缀。
现在 `--out=.../myapp.exe` → `APP_NAME="myapp"`。

### 3. 构建信息注入非幂等（曾把源码切掉 300 行）

旧代码用 `string.find(mainSrc, beginTag)` **全文搜索**标记。
只要源码注释或常量定义里出现同样的标记字样就会被命中，
于是标记之前的整段正文被当成"块"切掉，报出莫名其妙的
`Expected '=' near '";var APP_VERSION = "'`。

修法：构建信息块固定在文件最前面，改用 `string.startWith` + `string.indexOf`
精确定位首尾；备份保存的是**剥离后的干净源码**，保证失败回滚不留残留。
现在连续 build 任意次数都稳定通过。

### 4. `string.replace` 第二参数是模式串

`string.replace(s, string.char(92), "/")` 会抛 `malformed pattern`。
模式里要表示字面反斜杠必须写两个，常量改为 `string.char(92) ++ string.char(92)`。

### 5. 产物目录未被排除

判断目录末段时未规范末尾斜杠，`[^/\\]+$` 匹配到空串，
导致 `dist/` 下的临时文件也被当源码打进包。改为先 `normPath(dir)` 再取末段。

### 附：本轮踩到的三个调试陷阱

- **自举死锁**：`aac.exe` 里固化的是打包时的字节码，改了 `aac.aardio` 不会改变它的行为。
  用旧 aac 编译新源码时，旧注入逻辑会破坏新源码（见第 3 条），因此**无法自举**。
  正确做法：`python build.py aac-runner --out %AARDIO_HOME%\aac.exe`（IDE 静默发布）。
- **`aac run` 会无限递归**：run 模式下 `_ARGV` 仍包含 `run` 本身，
  脚本再次进入 run 分支 → `C stack overflow`。不要用它自举 aac 自己。
- **必须加 `--no-pause` 或 `--log`**：默认结尾 `console.pause()` 在无 stdin 时永久挂起，
  表现为进程卡死、只能靠超时杀掉。指定 `--log` 会自动禁用暂停（CI 友好）。

### 回归结果

| 场景 | 退出码 | 说明 |
|------|--------|------|
| 正常 build | 0 | 产出 .appkg + 独立 EXE |
| 连续 build 两次 | 0 / 0 | 注入幂等，无残留 |
| 源码语法错 | 1 | 自动回滚 main.aardio |
| 工程路径不存在 | 1 | |
| 未知子命令 | 1 | 附带打印帮助 |
| `--help` | 0 | |

真实场景：`aac build D:\Projects\WebexAuto\aardio --out=...\WebexAuto_aardio.exe`
→ rc=0，产出 1.70 MB 独立 EXE。

---

### 13.3 第三轮（2026-10-12 深夜：2.0 生产级重构）

这一轮不是补漏洞，而是把工具重构成可交付状态：单一源、有测试、有校验、退出码可信。

#### 修复（影响正确性）

| # | 问题 | 修法 |
|---|------|------|
| 1 | **构建会写脏磁盘源码**：注入块写回 `main.aardio`，失败/中断即污染，下次构建拼出嵌套注释 | 改为内存注入，磁盘零改动、零备份、零回滚 |
| 2 | **`--out` 指向 `.exe` 时，`.appkg` 也被写成同名 `.exe`** | 三态语义明确：目录 / `.exe` / `.appkg` |
| 3 | **独立 EXE 的退出码恒为 0**：宿主所有 `return 1` 都无效 | 宿主出口 `Environment.Exit`；`main` `return` 的数字原样作退出码 |
| 4 | 包无完整性校验，被截断时静默丢文件，运行期报莫名错误 | 清单字节数必须恰好用光 + CRC32 校验 |
| 5 | 排除目录只判断「直接父目录」，`dist/lib/x.aardio` 会被打包 | 按相对路径任意层级判断 + `--exclude` 可追加 |
| 6 | 编译遇到第一个错误就退出 | 汇总全部失败文件再退出 |
| 7 | 包内文件顺序随文件系统枚举而变，产物不可复现 | 按相对路径排序 |
| 8 | 日志镜像每次 `console.log` 都全量读回重写，O(n²) | 改为追加写，并自动创建日志目录 |
| 9 | 编解码逻辑在编译器与宿主里各写一份，必然漂移 | 抽 `lib/aacpkg.aardio` 作唯一源，`build.py` 内联进两边 |
| 10 | 手工 `cp` 源码进 runner 工程，忘了就发布旧代码 | `build.py sync` / `build.py all` 自动同步 |
| 11 | 没有任何回归测试 | `run_tests.py`，15 个用例 |

#### 本轮踩到的 aardio 语言级坑（写 aardio 一定记住）

1. **顶层 `var f = function(){}` 必须先定义后调用**。
   定义在调用它的函数**之后**时，编译期会绑定成 self 成员，运行时取到 `null`：
   `Attempt to call ... {Kind}:self(namespace) {Name}:'f' {Type}:null`。
   这一次是 `stripBuildInfo` 中招。
2. **`_ARGV` 是内核常量，不能赋值**。写 `_ARGV = t` 直接抛
   `Can't modify the constant : '_ARGV'`。要传参就新开一个全局（本项目用 `APP_ARGS`）。
3. **`tostring(null)` 会抛异常**（`Bad argument @1 Expected value`），
   而 `io.exist()` 对不存在的路径返回 `null`。任何对外输出都要先判 null。
4. **`io.exist()` 返回的是「找到的路径字符串」**，不是 `1` / `2`；不存在时返回 `null`。
   旧代码 `ret != nil && ret != 0` 碰巧能工作，但语义是错的。
5. **`catch` 块里的 `return 值` 不生效**（返回 `null`），需要用标志位或直接退出。
6. **条件 `import` 可以编译**（`if(flag){ import x; }`），但只有真正执行时才加载。
7. `string.save(path, str, true)` 第三参数为 `true` 表示**追加写**。
8. `string.replace` 的第二参数是**模式串**，字面反斜杠要写两个。

#### 当时的验收状态（已被 13.4 取代，保留作历史）

```
python run_tests.py    →    通过 15 / 失败 0      ← 现在 52 个用例
python build.py all    →    aac.exe 1.67MB + aardioHost.exe 1.67MB，约 17s
                            ← 现在 aac.exe 1.68MB + aardioHost.exe 6.41MB，约 33s（多了发布后冒烟）
aac build WebexAuto    →    rc=0，1.70MB 独立 EXE
```

---

### 13.4 第四轮（2026-10-13：真实开源语料压测 + 宿主扩容）

这一轮的判据不是"我自己写的用例过了"，而是 **126 个网上收集的真实开源 aardio
工程能不能编过去**（`%CORPUS_ROOT%`）。

```
python corpus_test.py --timeout 120 --keep --json corpus_v6.json
```

| 阶段 | OK | MISSING_LIB | COMPILE_ERR | FAIL |
|------|----|-------------|-------------|------|
| 本轮开始 | 50 | 50 | 25 | 2 |
| 本轮结束 | **64** | 49 | **11** | 2 |

底线项始终成立：**无挂死、无谎报成功**（返回 0 就一定有 EXE，失败一定非 0 且可诊断）。

#### 修复（按收益排序）

| # | 问题 | 证据 | 修法 |
|---|------|------|------|
| 1 | **`$"/res/x"` 这类工程根相对包含编不过**，25 个编译失败里 16 个栽在这 | `io.fullpath("/res/x")` → `%AARDIO_HOME%/res/x`（解析成 aac **自己**所在目录，IDE 解析成工程目录） | 编译前在**内存**里把 `$"/..."` `$"\..."` `$"~/..."` 前补上工程目录；磁盘源码一个字节不动 |
| 2 | 编译期当前目录是 aac 所在目录，源码里相对包含按错基准解析 | `web/import.js` 找不到 | 未给 `--cwd` 时，编译阶段 `setCurDir(工程目录)`，与 IDE 一致 |
| 3 | **宿主预埋 275 个库后，每个产物 EXE 都是 rc=-1、日志为空** | 真发布 + 真跑出来的 | 元凶是 `ide`：它是给 IDE 用的，导入时找不到 IDE 环境直接把进程干掉。已进 `HOST_FATAL_LIBS`，`host-add` 默认拒绝 |
| 4 | `dep_scan.py` 把 90 多个第三方库误报成"本机就有、能自动补" | 它靠匹配 aac 输出文案判定，文案一改正则全失效 | 改为**直接查文件系统**，并复用 `build.py` 里唯一的模块解析规则 |
| 5 | 缺库用例写死 `web.view` 当样本，宿主扩容后用例假红 | 扩容到 274 个库后必然发生 | 改为运行时从 `aac libs` 反选一个确实没预埋的库 |
| 6 | **`host-add --rebuild` 谎报成功**：返回 0 但宿主根本没重建，用户再 build 还是同样的缺库 | 端到端跑真实工程时才发现 | 退出码改为取自**事实**：重建后重读宿主 EXE 里的 `__HOST_LIBS__` 哨兵，库不在里面就返回 1 |
| 7 | 同上，连环两个坑：`python` 在这种子进程里 stdin 还是管道会崩在 `init_sys_streams`；命令以引号开头会被命令行的去引号规则切烂 | `Fatal Python error: init_sys_streams` / `'python" "D:' 不是内部或外部命令` | 三个标准句柄全重定向（`> log 2>&1 < nul`），命令不以引号开头，且不用 `cd /d`（在管道子进程里不生效） |
| 8 | 宿主的启动期 `[TRACE]` 诊断默认就写进 `--log`，把用户自己的输出淹掉 | 看一眼日志就知道 | 改为 `--trace` 才开 |

#### 三条新增的经验（写工具的人都该记住）

1. **"宿主自己能跑"证明不了预埋是安全的**。裸宿主不走 `loadcode`，
   所以它永远正常；真正的判据只有一个：打一个真实 EXE 并运行它。
   `build.py` 里 `smoke_test_host()` 就是这一关，冒烟不过自动回滚宿主。
2. **静态特征预测不了哪个库会杀死产物**。单独 import 正常、组合 import
   正常、全量 import 1.9s 正常 —— 崩的那一类只在"发布后的 EXE"里现形。
   所以扩容必须走 `加一批 → 发布 → 打真实 EXE 跑一遍` 的闭环。
3. **任何依赖另一条命令输出文案的判断都会在某次改文案后静默失效**。
   "本机有没有这个库"要查文件系统，"版本号对不对"要读字节，不要 grep 日志。

#### 宿主预埋库管理

```bat
aac libs                                  :: 宿主当前预埋了哪些库
aac host-add string.uuid,zlib.zip         :: 往宿主源码里补库
aac host-add <库名> --rebuild             :: 补完立刻重建宿主（会弹 IDE，随后自动关闭）
aac host-del <库名> --rebuild             :: 剔除
aac host-add <库名> --force               :: 强行加被拦下的库（后果自负）
python host_grow.py --batch 10            :: 按 pending_libs.txt 分批扩容，每批真发布 + 真冒烟
```

被拦下的库分三档，理由都写在源码注释里：

| 档 | 名单 | 依据 |
|----|------|------|
| `HOST_FATAL_LIBS` | `ide`、`java.jre.v8`、`inet.file` | **真发布 + 真跑**被刷下来的（产物 rc=-1 / 导入挂死 / 导入报错） |
| `RISKY_IMPORTS` | `winex.caret` 等拉 UIA / WinForms 的库 | 静态可疑：import 期起重依赖，会把可诊断的失败变成静默挂死 |
| 顶层改写 `loadcode`/`string` 等全局名 | 见 `HOST_CRITICAL_GLOBALS` | 宿主靠 `loadcode(字节码)` 跑载荷，被改写即全灭 |

#### 关于"能不能自动下载缺失的库"

缺库报告现在分三类，出路完全不同：

```
【A类】本机 aardio 里就有，只是宿主没预埋  ->  aac host-add xxx --rebuild（不用联网）
【B类】是 aardio 官方库，但本机还没装      ->  IDE 库管理器装一次（需联网），再 host-add
【C类】官方清单里也没有                    ->  第三方库或拼错，只能改代码
```

**A 类 aac 能全自动**；B/C 类做不到 —— aardio 官方库的分发走 IDE 的库管理器，
没有可调用的公开接口。aac 能做的是把名字、出处、下一步命令准确地摆出来，
而不是丢一句"编译失败"。

本机实测：126 个工程里仍缺的 85 种库**全部是 B/C 类**（`web.sciter`、`carl.mysql`、
`skin.sharp`、`reportRl`、`zbar`……），本机压根没装，不是预埋能解决的问题。

#### 第四轮的验收状态（其中一条已被 13.5 推翻，注意看注释）

```
python run_tests.py                        ->  通过 46 / 失败 0            （现在 49）
python corpus_test.py --timeout 120 --keep ->  OK 64 / MISSING_LIB 49 / COMPILE_ERR 11 / FAIL 2
                                              无挂死、无谎报成功（第五轮重跑复现，结论一致）
python build.py aardioHost-runner          ->  宿主 283 个预埋库  ← 错的：那是带重复的计数，
                                              去重后是 279 个。当时这组数字就在眼前却没人
                                              当成异常，见 13.5
```

---

### 13.5 第五轮（2026-10-13：补库链路的幂等性）

这一轮没有新功能，起因只是**更新文档前核对 `aac libs` 的实际输出**，
结果看到 `string.cmdline` 在清单里出现了 **5 次**。

#### 因果链

```
host-add 判断"是否已预埋"的根据 = 宿主 EXE 里的哨兵
        │
        ├─ 预埋是在「IDE 发布」那一刻才写进 EXE 的
        │
        └─ 早期 rebuild 是静默失败的（io.popen 丢输出就 return 0
           → python 崩在 init_sys_streams → 命令以引号开头被 cmd 切坏）
                    │
                    ▼
           EXE 没更新 → 哨兵里没有刚加的库
                    │
                    ▼
           下次再 host-add 同一个库 → "看起来还没预埋" → 又 append 一条
```

**把阶段性产物的快照当成真相，是这个 bug 的根。** 哨兵只反映
"上一次发布成功写进了什么"，源码才决定"下一次发布会预埋什么"。

#### 五处修复

| # | 位置 | 问题 | 修法 |
|---|------|------|------|
| 1 | `cmdHostAdd` 判定依据 | 只看 EXE 哨兵 | 改为**以源码 import 区块为准**（`hostSourceImports`），哨兵降级为参考 |
| 2 | 写入前的去重 | 完全没有 | `hostDedupeImports`：保留首次，其余按**整行 + 前一个换行**精修删除（从后往前删，保证下标不失效），因此行尾 CRLF、文件末尾换行都不会被破坏 |
| 3 | 哨兵同步方式 | 往旧串尾部 `append` | `hostSyncSentinel`：每次按去重后的 import 列表**整体重写**。append 天然会重复，重写天然不会 |
| 4 | 幂等命令的退出码 | "全部已预埋"返回 rc=1 | 改为 rc=0（`host-del` 删不存在的同理）。**幂等命令不能让 CI 断在执行第二遍**，何况"已预埋"正是这条命令要达到的状态 |
| 5 | `host-del` 重建 | 按 `\n` 切行再 join，把文件末尾那个换行吃掉了 | 显式记住并补回（`endsNl`）；顺带把 `string.trim(line)` 换成 `trim(line, WS)`，否则 CRLF 行尾的 `\r` 会让整行匹配失败、表现为"删了但没删掉" |

#### 为什么拖到现在才发现

```
build.py check_host_libs   ->  if name not in imports: append  ← 重复项被静默去重掉
aac libs                   ->  照常打印，功能不受影响
产物 EXE                   ->  重复 import 没有语义差别
```

**三条防线都做了"集合正确性"，没有一条检查"列表有没有重复"。**
凡是"用集合语义校验列表"的地方，都是漏 repeat 类 bug 的温床 —— 现在
`check_host_libs` 里加了 `Counter` 重复检测，发布前直接 ERROR：
报错文案会把修复命令（`aac host-add <其中任意一个库名>`）一并给出来。

#### 顺带记一个测试里的坑（写 Python 测试也一样）

```python
host.write_text("\r\n".join(body), encoding="utf-8")   # ✗ 行尾会变成 \r\r\n
open(host, "w", encoding="utf-8", newline="").write(...)  # ✓
```

`Path.write_text` 走的是 `newline=None`，写的时候会把 `\n` 再翻译成 `\r\n`。
新加的 `host_del_is_idempotent_and_tidy` 就因为这条先红了 —— 但它红的
**位置是对的**：断言检查的是"文件末尾行尾不能被工具偷偷改掉"。

#### 同一轮里第二次「隐秘降级」：变异测试的锚点腐化

把版本号 `2.2.0` 改成 `2.3.0` 之后，`mutation_test.py` 的结果从 `7 / 7`
变成了 **`6 / 0`**，退出码依旧是 0、"全部通过"。原因是 P2 那条变异用例的
植入锚点正好是 `var AAC_VERSION = "2.2.0";` 这行文本 —— **版本号一改，
毒药再也塞不进源码，用例被 `continue` 跳过，既不算成功也不算失败。**

```
修改前:  7 条全绿           ->  防线完好
修改后:  6 条全绿（1 条没了） ->  少了一盏灯，报表却更好看
```

这和 13.4 里 `dep_scan.py` 的教训是**同一个元模式**：
**一个东西是否在防守，不能看它说自己通过了没有，要看它到底参与没参与。**

两处都改了：

- 锚点换成语义恒定、几乎不可能被业务修改的 `import dotNet;`
- **`SKIP` 现在的下场是 `FAIL`**：不参与就等于失守；结尾额外校验
  `参与数 == 用例总数`，谁想装死都会当场报错

并且用"临时把 `import dotNet;` 改成 `dotNetX`"实测过这道新防线会真的响：
退出码 1、明确指出是锚点腐化，源码还原后 md5 一致。

#### 第三次「隐秘降级」：aac 侧与 build.py 的 import 规则分歧

上面那套去重/幂等设施有个前提条件：**两边对"什么算一条 import"的理解必须一致**。
复查时发现不一致：

```python
build.py :  ^\s*import\s+([\w.]+)\s*;      # 不锚行尾 → 认 `import x; // 说明`
aac 侧   :  trim 后必须 startWith("import ") and 以 ';' 结尾   # 不认上面那种行
```

后果是个死循环：

```
用户手工写了 import gamma; // 说明
      ↓
build.py 认它是 gamma，纳入清单，发布通过
      ↓
某天 aac host-add gamma —— aardio 侧"看不见"它 → 再追加一条
      ↓
源码里两条 → check_host_libs 报「重复 import」
      ↓
报错文案给出的修复命令恰恰是 `aac host-add gamma` —— 就是制造重复的那条
```

而且回退到旧逻辑实测出来的后果比"多一条"严重得多：
宿主源码被**写坏**（哨兵里丢库、import 行错位），不是简单的重复。

修法是让两边同语义：名字一律取到第一个 `;` 为止，并用 `isLibName` 校验字符集
（`[A-Za-z_][\w.]*`）。`host-del` 里那段整行比对也同步改了 —— 否则
`import delta; /* ... */` 这种行**永远删不掉**，表现为"删了却还在"。

新增的 `import_line_with_trailing_comment_agrees_with_build_py` 用例，
是用**回退了修复的版本跑红的**才算收工（见上一节的教训）。

#### 现在的验收状态（aac 2.3.1）

```
aac version                        ->  aac 2.4.0，内核指纹 2346298780
python run_tests.py                ->  通过 50 / 失败 0
python audit.py                    ->  ERROR 0 / WARN 0
python audit.py --selftest         ->  自检 12 条全过（喂已知坏样例必须报红）
python mutation_test.py            ->  通过 7 / 失败 0 / 共 7（**少一条就算失败**）
aac libs                           ->  279 个预埋库，无重复
aac host-add <已预埋的库>           ->  rc=0，源码一字不改（幂等）
aac host-del <不存在的库>            ->  rc=0，源码一字不改（幂等）
aac host-del X && aac host-add X   ->  rc=0，源码 md5 回到原值（中间不重建也行）
python build.py aardioHost-runner  ->  发布后自动冒烟 + 失败回滚，IDE 必定关闭
                                       且【同级孵出的子 IDE 也会被扫干净】
python corpus_test.py --timeout 120 --integrity
                                   ->  OK 64 / MISSING_LIB 49 / COMPILE_ERR 11 / FAIL 2
                                      无 HANG、无 BAD
                                      源码完整性：1489 个源文件，0 被改写
```

---

### 13.6 第六轮（2026-10-13：看似修完的漏洞，以及"我说关闭了"不等于"关干净了"）

这一轮是被连续两问催出来的：**「你确定没有任何问题了？」 / 「你要不要再检查检查？」**
两次都没有空手而归，一共挖出三件事。

#### 13.6.1 「改一半」的修复：EXE 哨兵仍在参与跳过判定

上一轮（13.5）把 host-add 的判定依据从 EXE 哨兵换成了源码 import 区块，
并且宣称"幂等问题已解决"。**这只修了一半。**

被剩下的那半是这样：

```
cmdHostAdd:
    if(isOneOf(declared, lib) or isOneOf(added, lib) or isOneOf(inSource, lib)){
                 ↑ EXE 哨兵还在参与"跳过"判定
        table.push(skipped, lib);
    }
```

`declared` 来自 **宿主 EXE 的字节流**（`extractHostLibs`），
而 `host-del` 只改**源码**、EXE 要等 `--rebuild` 才更新。于是必然存在这么一段窗口：

```
        ┌──────────────────────────────────────────────┐
        │ host-del gamma                               │
        │   源码: import gamma;  ← 删掉                │
        │   源码哨兵: 也重写成没有 gamma                │
        │   EXE 哨兵: 还是写着 gamma（没重建）          │  ← 两边不一致
        └──────────────────────────────────────────────┘
                              ↓
        ┌──────────────────────────────────────────────┐
        │ host-add gamma                               │
        │   declared 里有 gamma → 「已预埋，跳过」      │  ← BUG
        │   源码一个字没动                              │
        └──────────────────────────────────────────────┘
                              ↓
        ┌──────────────────────────────────────────────┐
        │ 下一次发布 → 产物里真的没有 gamma             │
        │ 用户看到「宿主未预埋库: gamma」               │
        │ 执行提示里的修复命令 host-add gamma           │
        │ → 还是「已预埋，跳过」→ 死循环                │
        └──────────────────────────────────────────────┘
```

**实测复现**（假 aardioHost.exe 里塞一条哨兵就够了，`extractHostLibs` 只按字节找串）：

```
$ aac host-add gamma
[INFO] 宿主已预埋，跳过: gamma
[OK] 全部已预埋，无事可做: gamma
源码里已有 import gamma; : False        ← 说有，其实没有
```

跟 13.5 那个"重复追加"是同一个根、方向相反：
那时哨兵比源码**少**（追加），现在哨兵比源码**多**（补不回来）。
上一轮只堵了一边。

**修法**：把 `declared` 从所有判定里彻底踢出去，只留作诊断。

```diff
-        if(isOneOf(declared, lib) or isOneOf(added, lib) or isOneOf(inSource, lib)){
+        // 注意: 这里【不能】再拿 declared（EXE 哨兵）判"已预埋" —— 哨兵是
+        // 上一次成功发布的快照，host-del 之后它比源码旧，用它跳过就补不回来
+        if(isOneOf(added, lib) or isOneOf(inSource, lib)){
```

修完的输出（同一场景）：

```
$ aac host-add gamma
[WARN] 这些库在【宿主 EXE 的哨兵清单】里有、但源码里没有 gamma
  说明两者没同步（典型情况：刚执行过 host-del 还没 --rebuild）。
  判定一律以源码为准，本次会当作新库补上；重新发布后两者即恢复一致。
[OK] 已更新宿主源码: .../aardioHost.aardio
[INFO] 新增库: gamma
```

#### 为什么这件事值得写这么长

因为它同时证明了三个层级的漏洞：

| 层 | 本以为 | 实际上 |
|----|--------|--------|
| 代码 | 改成"以源码为准"就没事了 | 跳过分支里还残留一份快照读数 |
| 测试 | 幂等用例已经覆盖 | 沙箱里从来没有宿主 EXE，`declared` 恒为空，**这条分支从未被执行** |
| 心智模型 | "不一致会导致重复追加" | 不一致**双向**都有害：多了补不回来，少了反复追加 |

其中最要命的是第二行：**一条从未被执行的分支，在测试报告里是"通过"的。**
这跟 13.5 里 `mutation_test.py` 锚点腐化导致 "7/7 实际只有 6 条" 是同一种病。

所以这次也得按规矩：**新用例 `host_add_ignores_stale_exe_sentinel`
必须在回退版上跑红才算数** —— 把旧逻辑重新发布成 `aac_buggy.exe` 验证：

```
FAIL  host_add_ignores_stale_exe_sentinel (0.4s)
      拿陈旧的 EXE 哨兵判了已预埋，gamma 永远补不回来:
      [INFO] 宿主源码已预埋，跳过: gamma
      [OK] 全部已预埋，无事可做: gamma
```

顺便，新用例对沙箱提了个新要求：**必须造一个带哨兵的假宿主 EXE**。
`extractHostLibs` 只按字节找哨兵串，所以一个纯文本文件就够了，
不必真去 IDE 发布一次 —— 这条也写进用例注释了，免得后人觉得难而跳过。

真实宿主文件上的往返实测（279 库那个真文件，中间刻意不重建）：

```
原始 md5            ec616ac9bc4c   279 条 import
host-del string.cmdline  →  [OK] 已从宿主源码剔除
host-add string.cmdline  →  [WARN] 哨兵与源码不同步 → [OK] 已更新
结果 md5            ec616ac9bc4c   279 条 import，逐字节一致
```

#### 13.6.2 build.py 说"IDE 已正常退出"，但 IDE 还在

用户的硬要求从第一轮就摆在那儿：**编译结束后必须关掉 aardio IDE，否则机器会卡死。**
`build.py` 用 `try/finally` + WM_CLOSE + 超时强杀做了两重保险，日志也每次都印
`IDE 已正常退出`。这一轮却在收尾检查 `tasklist` 时发现：

```
[build] 关闭 IDE PID=167864 ...
[build] IDE 已正常退出 (2.4s)
$ tasklist /FI "IMAGENAME eq aardio.exe"
aardio.exe                  142668 Console   1   27,264 K     ← 还有一个！
```

根因：`close_ide(my_pid)` 只照顾自己 spawn 的那个 PID，而 `kill_stale_ides`
**只在发布前**调用 —— IDE 发布过程中孵出的子进程要等"下一次"构建才被扫到，
最后那次构建泄漏的就一直躺在后台。用户正是在"最后一次"之后发现机器变卡的。

**修法**：调用前先给"用户自己开着的 IDE"记账，收尾时把其余全部清空。

```python
user_ide_pids = _ide_pids()          # 启动前先记账：这些多半是用户自己的编辑器
for p in kill_stale_ides(exe, keep_pids=user_ide_pids):
    log("清理残留 IDE 进程 PID=%d" % p)
proc = subprocess.Popen([exe, str(aproj)], startupinfo=si)
try:
    ...
finally:
    close_ide(my_pid)
    for p in kill_stale_ides(exe, keep_pids=user_ide_pids):   # ← 新增
        log("清理本轮孵出的 IDE PID=%d" % p)
```

改完实测：

```
[build] 关闭 IDE PID=202200 ...
[build] IDE 已正常退出 (3.6s)
[build] 清理本轮孵出的 IDE PID=11644      ← 以前会漏掉的就是它
$ tasklist /FI "IMAGENAME eq aardio.exe"
信息: 没有运行的任务匹配指定标准。
```

**顺带堵掉一个反向风险**：以前的 `kill_stale_ides` 不传 `keep_pids`，
也就是**你在 IDE 里好好开着工程的时候跑一次 `build.py`，你自己的 IDE 会被强杀**。
只有应用名字列宁 `"aardio.exe"` 就杀，没做区分。现在用假进程表验证过保护生效：

```
扫无保护: [4001, 4002, 5001]      ← 全是同名进程，用户的也被端了
带保护  : [5001]                  ← 只杀本轮引入的
```

#### 13.6.3 第一次在真实规模上验证"绝不改动磁盘源码"

这条保证从 2.0 起就写在注释里（"构建信息只在内存拼接，磁盘源码不动"），
但此前只在若干个合成用例里抽查过。**这一次给整个语料库做了前后校验和比对：**

```
before: 1489 个源文件（.aardio/.aproj/.bak/.alg）md5 快照
          ↓  126 个真实工程全量编译一遍
after : 被改写 0 / 新增 0 / 消失 0
```

同时把这项检查做成了开关，`corpus_test.py --integrity` 随时可复验：

```
── 源码完整性（aac 承诺不改磁盘源码）──
  快照文件 1489 个 / 被改写 0 / 新增 0 / 消失 0
  通过：零改动
```

#### 一句话教训

> **"通过了"和"被执行了"是两件事。**
> 一条没人走过的分支，在报告里永远显示通过 ——
> 所以每加一道防线都要先证明"它真的会拦"，而不是等到日志好看就收工。

#### 本轮改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `aac.aardio` | `declared`（EXE 哨兵）退出所有判定，只保留"两边不同步"的诊断输出 |
| 2 | `aac.aardio` | 版本 2.3.1 → **2.4.0**（CLI 行为变了，必须升号） |
| 3 | `run_tests.py` | 新增用例 `host_add_ignores_stale_exe_sentinel`（含假宿主 EXE 沙箱） |
| 4 | `build.py` | 记账用户自己的 IDE + 收尾兜底清扫同级孵出的 IDE 进程 |
| 5 | `corpus_test.py` | 新增 `--integrity`：运行前后对源码做 md5 比对 |

---

## 十四、工程内的辅助工具

这些脚本不是"顺手写的附件"，每一条都对应一次**只能靠它才能确诊**的事故。
按用途分三档：**日常发布**、**宿主维护**、**质量门禁**。

| 脚本 | 一句话 | 什么时候用 |
|------|--------|-----------|
| `build.py` | 同步源码 + 静默发布 + 发布后冒烟 | **每次改完 `*.aardio` 都要跑** |
| `run_tests.py` | 回归测试（52 用例） | 改完自查，交付前必跑 |
| `aac host-add / host-del` | 宿主预埋库增删（幂等） | 报"宿主没预埋 X"时 |
| `host_grow.py` | 宿主批量扩容，每批真发布 + 真跑 | 要一次性补很多库时 |
| `lib_probe.py` | 单库体检：import 会不会出事 | 怀疑某个库有毒时 |
| `host_import_bisect.py` | 复盘宿主启动期全量 import 并二分定位 | 产物 `rc=-1` 且日志为空时 |
| `corpus_test.py` | 真实开源工程压测 | 改了编译链路后的验收 |
| `dep_scan.py` | 扫描语料依赖，统计到底缺哪些库 | 决定该给宿主补什么 |
| `audit.py` | aardio 语言级陷阱静态审计 | 每次提交前 |
| `mutation_test.py` | 给 `audit.py` 做体检 | 改了 `audit.py` 之后 |

### 14.1 build.py —— 发布（唯一入口）

```bat
python build.py                     :: all = 同步 + 发布 aac.exe + 发布 aardioHost.exe
python build.py sync                :: 只做源码同步 + 宿主清单校验（不弹 IDE，最快）
python build.py aac-runner --out %AARDIO_HOME%\aac.exe
python build.py aardioHost-runner   :: 发布后自动冒烟 + 失败回滚保存在用的宿主
python build.py all --show          :: 不隐藏 IDE 窗口（调试用）
python build.py all --keep-ide      :: 发布完不关 IDE（**别滥用**，弹多了机器会卡）
```

- 会在 `try/finally` 里关闭 IDE —— 这是硬性要求，不是优化。
- `sync` 阶段会校验宿主源码的 import 列表与 `HOST_LIBS_DECL` 严格一致、
  每个库名真实存在、**没有重复 import**，任一条不满足直接报错终止发布。
- `aardioHost-runner` 发布后会先备份在用宿主，再打一个 hello-world EXE 真跑一遍；
  冒烟失败会回滚并退出码 6。

### 14.2 宿主预埋库维护

```bat
aac libs                            :: 宿主当前预埋了哪些库
aac host-add string.uuid,zlib.zip   :: 补库（写源码 import + 哨兵）
aac host-add <库名> --rebuild       :: 补完立刻重建宿主
aac host-del <库名> --rebuild       :: 剔除
aac host-add <库名> --force         :: 强行加被拦下的库（后果自负）
```

改源码不等于改宿主 —— 预埋是在「IDE 发布」那一刻才写进 EXE 的，
所以 `host-add` / `host-del` 之后**必须重建一次宿主**才会生效：
就地 `--rebuild`，或 `python build.py aardioHost-runner --out <宿主EXE路径>`。
补库的判定规则见 13.4、13.5、**13.6**，一共四条铁律：

1. **看源码，不看 EXE 里的哨兵快照** —— 快照只反映"上一次发布成功写进去了什么"。
2. 连"跳过"都不能看快照 —— 否则 `host-del` 之后就再也补不回来（见 13.6）。
3. **写入前先去重**，同一条 import 在源码里只留第一条。
4. **哨兵每次按源码整体重写**，不做追加；发现两边不同步时只给诊断提示。

要一次补很多库、又不想手工分批时用它：

```bat
python host_grow.py                 :: 从 pending_libs.txt 分批扩容
python host_grow.py --limit 30      :: 最多处理 30 个
python host_grow.py --only A,B,C    :: 只处理指定库
```

`host_grow.py` 的每一批都走「加进源码 → `build.py` 真发布 → 真打 EXE 真运行」，
批失败就二分到具体库名，写进 `blacklist.txt`；成功的写进 `added_libs.txt`。

### 14.3 两个"只能靠运行确诊"的排查工具

有些故障**任何静态特征都预测不了**（见 13.4 第 3 条经验）：

```bat
python lib_probe.py string.cmdline fsys.table --timeout 15 --slow 1.5
python lib_probe.py --file names.txt --json probe.json
python host_import_bisect.py --file _hostlibs.txt --timeout 25
```

- `lib_probe.py`：把每个库单独编一个小 EXE 真跑一遍，超过 `--slow` 秒就算
  "慢"，崩了/挂了直接标出来。用来回答"这个库能不能预埋"。
- `host_import_bisect.py`：复现宿主启动期的全量 import，用二分法定位到
  到底是哪一条把进程搞死了。产物 `rc=-1` 且日志一个字都没有时的唯一出路。

### 14.4 语料压测与依赖扫描

```bat
python corpus_test.py --corpus %CORPUS_ROOT% --timeout 120 --keep
python corpus_test.py --limit 20 --json corpus.json
python corpus_test.py --timeout 120 --integrity   ← 顺带验证「不改用户源码」
python dep_scan.py --json depscan_latest.json
```

- `corpus_test.py` 的结论分 7 类：`OK` / `MISSING_LIB` / `COMPILE_ERR` /
  `BAD_INPUT` / `FAIL` / `HANG` / `BAD`。
  - **`OK` 不是"返回 0"就算**：返回 0 却没产出 EXE 会被判成 `BAD`（谎报成功）；
    失败却一行日志都没有同样判 `BAD`（无法诊断）。**硬指标是 `BAD = 0`，
    而不是 OK 的数量** —— 工具可以不完美，但不能骗人。
  - `HANG`（超过 `--timeout` 未结束）**单独统计，不与 FAIL 混为一谈**：
    过去两个工程在 60 秒超时下偶发失败，放到 120 秒就过了，那是环境抖动不是缺陷。
- `dep_scan.py` 判断"本机有没有这个库"是**直接查文件系统**，
  不走任何命令的输出文案（见 13.4 第 2 条经验），也就不会因为改了输出措辞而集体误判。

### 14.5 质量门禁

```bat
python audit.py                     :: 审 aac.aardio / aardioHost.aardio / lib\aacpkg.aardio
python audit.py aac.aardio --json   :: 单文件 + JSON 输出
python audit.py --selftest          :: 跑内置样例自检（12 条，覆盖 P1~P10）
python mutation_test.py             :: 给源码植入 7 个已知 bug，audit 必须全部抓到
```

`audit.py` 的 10 条规则（都是踩过的）：

| 规则 | 拦什么 | 为什么致命 |
|------|--------|-----------|
| P1 | `try{}` 里 `return 值` | **既不返回也不生效**，错误分支被吞掉 |
| P2 | 顶层函数前向引用 | 运行时对象是 `null`，报 `Attempt to call ... {Type}:null` |
| P3 | 帮助写了但没实现的选项 | 一用就报"未知参数" |
| P4 | 多字符分隔符 | `string.split` 按字符集拆，会逐字符切开 |
| P5 | `for` 第二段写复合条件 | 解析直接失败 |
| P6 | 双引号串里用反斜杠转义 | 字符串跑飞，后面的代码全变串内容 |
| P7 | 不存在的 API | 运行时 nil 调用 |
| P8 | `tostring` 无保护 | 传入 `null` 直接抛异常 |
| P9 | 空 `catch` | 异常被静默吞掉 |
| P10 | 假转义换行（`"\r\n"` / `"\\"`） | 整份源码被当成一行，所有行级扫描全失效 |

确属刻意如此的地方写 `// audit:ok` 抑制即可，注释要说明理由。

> `mutation_test.py` 存在的意义：**没做过变异测试的静态审计等于没有审计** ——
> 你并不知道它到底拦住了什么。它会把源码复制一份、植入上面这些坑，
> 然后要求 `audit.py` 一条不落全报出来。改完 `audit.py` 必须跑它。

### 14.6 运行时数据文件

| 文件 | 内容 | 谁写 |
|------|------|------|
| `blacklist.txt` | 实测会杀死产物的库，永不预埋 | `host_grow.py` |
| `pending_libs.txt` | **待办**清单（`host_grow.py` 的输入）。处理完即清空 —— 里面有内容说明活没干完 | `dep_scan.py` / 手工 |
| `added_libs.txt` | 已补进去的库（历史留档，只增不删） | `host_grow.py` |
| `corpus_latest.json` | 最近一次语料压测结果 | `corpus_test.py` |
| `depscan_latest.json` | 最近一次依赖扫描结果 | `dep_scan.py` |
| `lib_probe.json` | 最近一次单库体检结果 | `lib_probe.py` |
| `.gate_cache.json` | 发布前库体检的结果缓存（**本机状态，已 gitignore**） | `build.py` |

---

## 十五、已知限制（做不到 / 没做的事）

这一节专门写"不要指望它"，免得踩进去才发现。

| 限制 | 说明 | 影响 / 绕法 |
|------|------|------------|
| **B/C 类库不能自动下载** | aardio 官方库的分发走 IDE 的库管理器，没有可调用的公开接口 | 只能精确告诉你库名和下一步命令；装完再 `host-add`。本机 126 个工程里缺的 85 种库**全是这一类**，不是 aac 偷懒 |
| **`.gate_cache.json` 永不过期** | 体检结论按库名缓存，`OK` 之后就不再重跑 | 换了机器、升级了 aardio、库文件被改过之后请**手工删掉它**，否则新引入的毒库会被当成已体检通过 |
| **aac 依赖自身所在位置** | 标准库只从 `<aac.exe 目录>\lib` 找；宿主源码靠 `findFileUpwards` 从「提示文件 → 当前目录 → EXE 目录」三个起点逐级上溯找 | 拷贝到别处单独用会找不到库/宿主源码。这是设计取舍（免配置），换机器重装时在 `%AARDIO_HOME%\aac.local.txt` 里写一行 `AAC_HOME=` 即可（见 16.2） |
| **`build.py` 会弹 IDE** | 发布这一步无法脱离 IDE —— 这是"独立 EXE 不可能运行时追加预埋库"的本质决定的 | 已由 `try/finally` 保证关闭。**不要**用 `--keep-ide` 图省事，累积的隐藏 IDE 会拖垮机器 |
| **`--deploy-dir` 装到别处会静默失灵** | aac 只从「自身所在目录 `\lib`」找标准库。换成自定义目录后缺库判定会把自带库误判成第三方库、致命库拦截随之失效，**全程不报错** | `build.py` 在检测到部署目录里没有 `lib\` 时会明确警告；要么装到 aardio 安装目录，要么把那个 `lib\` 复制/联接过去 |
| **PowerShell / CI 里相对路径要带 `--cwd`** | 自动找回当前目录靠的是 cmd 专有的 `<盘符>:=` 变量，别的宿主不维护 | **cmd 下无需任何写法**；其余环境见「二、相对路径与当前目录」的三种写法 |
| **多个盘符变量时不猜目录** | cmd 切过多个盘会留下多条记录，无从判断用户站在哪个盘 | 明确报错并给出 `--cwd` / 绝对路径 / `aac.cmd` 三种修法，不会挑一个就用 |
| **49 个工程仍报 MISSING_LIB** | 真实语料压测的剩余项，全是第三方库 | 无解（第三方库要各自下载），且**不应该**为了让数字好看把它们塞进宿主 |
| **多进程并发改宿主源码无锁** | 两个 `host-add` 同时跑会互相覆盖 | 串行执行即可（日常用法本来就是单条命令） |
| **Windows-only** | 发布与兜底路径都依赖 Windows | 无 Linux/macOS 支持计划 |
| **非 UTF-8 源码** | 按 UTF-8 读写 | GBK 编码的工程请先转码 |

> **`build.py all` 不会替你跑回归测试。** 改完源码的收尾顺序是
> `python run_tests.py` → `python build.py all`；顺序反了会把一个通过了
> 编译但行为不对的版本发布到 `%AARDIO_HOME%\` 下去。

---

## 十六、开源相关

这一节专门给刚 clone 下来的人看：怎么跑起来、本机路径藏在哪、
以及改代码之后**必须**按顺序过哪几道门禁。

### 流程：改代码后必跑的四道门禁

`build.py all` 只负责"把源码变成 EXE"，**它不会替你跑回归测试**。
四个检查各自盯不同的东西，缺一个都可能把坏版本放出去：

| # | 命令 | 检查什么 | 不跑的后果 |
|---|------|---------|-----------|
| 1 | `python audit.py --selftest` | 12 条静态规则（P1–P10）自身的检测器是否还灵 | 规则悄悄失效，后面的静态扫描全变成走过场 |
| 2 | `python audit.py` | 源码有没踩到 P1–P10（硬编码路径、全盘 wildcard、无 try/finally 等） | 把本机绝对路径写进公开发布的 EXE |
| 3 | `python mutation_test.py` | 把已知的坏写法塞回去，看审计器能不能报红 | 同上，但证明了那条规则**真的参与过**（详见 13.6 的教训） |
| 4 | `python run_tests.py` | 52 个功能用例的行为正确性 | 通过了编译但行为不对，直接发布到 `%AARDIO_HOME%\` |

四道全绿之后再 `python build.py all`。顺序不能反。

> 第 3 条不是凑数。这个工程栽过三次跟头，全都是同一个病：
> **某个防御从来没被任何测试执行过，却照样报"pass"**。
> 所以新增任何检查规则时，都要先把它对应的缺陷版本造出来、确认它**报红**，
> 再修好确认它由红转绿 —— 没见过红的规则等于没有。

### 16.2 本机路径是怎么解耦的

开源代码里不应该出现作者机器的绝对路径。这个工程用**三级解析**取代硬编码，
三个 Python 入口统一走 `aacpath.py`：

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | 环境变量 `AARDIO_EXE` / `AAC_EXE` / `AAC_CORPUS` | CI 和临时覆盖用 |
| 2 | 仓库根 `.local_paths.txt`（`KEY=VALUE`，`#` 开头是注释） | **不进版本库**，本机的长期配置 |
| 3 | 自动发现（常见安装位置、`PATH`、仓库内编译产物） | 零配置时的兜底 |

找不到时不会猜一个假路径继续跑，而是打印出该设哪个环境变量。

aardio 那一侧没有环境变量可读（`io.environ` / `process.environ` **不存在**，
实测调用直接抛错），所以 `findFileUpwards` 走的是「三个搜索起点 × 逐级上溯」：

```
%提示文件 AAC_HOME=%   →   aac.local.txt（build.py 发布时自动写在 EXE 旁边）
当前工作目录            →   便于在别的盘符下干活
EXE 所在目录            →   最后兜底
```

每条起点向上找 5 级，同时试 `<dir>/<file>` 和 `<dir>/AardioCompile/<file>`，
所以无论你把仓库 clone 到 `D:\proj\` 还是 `C:\Users\me\src\`，都能找到。

> 之前这里末尾还挂着一句写死的作者本机路径（形如 `<某台机器上的仓库绝对路径>`）。
> 那行有害：clone 到别人机器上既找不到，又把作者的目录结构带了出去。已删除。
> 现在想在换机器后仍精确到源码仓库，就让 `build.py` 的发布环节写 `aac.local.txt`。

### 16.3 许可证与第三方声明

本项目使用 **MIT 许可证**，见 [`LICENSE`](./LICENSE)。

关于 aardio 的第三方声明，这里说清楚边界：

- 本仓库**不包含 aardio 的任何源码**，也不重新分发它的运行时、库或 IDE。
- `aac` 的工作方式是**驱动本机已安装的 aardio IDE** 完成发布
  （见 `build.py` 里那条 `WM_COMMAND 0x8317`）。因此使用 `aac` 前提是
  你已经在本机安装过 aardio，并遵守 aardio 自己的许可条款。
- 仓库里所有 `%AARDIO_HOME%` 都指你本机 aardio 的安装目录，
  `%CORPUS_ROOT%` 指你自己下载的测试语料库。

演示录屏 [`aac.mp4`](./aac.mp4) 随仓库一并发布，
对应 README「一、工具概览」里的那一段演示。

---

## 版本

| 版本 | 变更 |
|------|------|
| **2.4.0** | cmd.exe 下**不再强制写 `--cwd`**：从 cmd 继承的 `<盘符>:=<当前目录>` 自动恢复调用方位置（多条记录时不猜，退回明确报错）；配套新增回归用例 `caller_cwd_recovered_and_never_guessed`，两条断言各自做了「变红」验证 |
| 2.3.0 | `host-add` / `host-del` 改为幂等（判定依据换成源码 import 区块、写入前去重、哨兵整体重写），"全部已预埋 / 删本来就没有" 由 rc=1 改为 rc=0（见 13.5） |
| 2.2.0 | `--trace` 启动期旁路诊断、`build.py` 发布后冒烟 + 失败回滚 |
| 2.1.0 | 缺库报告分 A/B/C 三类并给出命令、致命库默认拒绝 |
| 2.0 | 包格式 v2（元信息 + CRC）、磁盘源码零污染、`host-add` / `host-del` |

