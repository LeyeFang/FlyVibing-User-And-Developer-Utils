# 扩展依赖契约（`python.runtime`）

> **读者**：需要第三方 Python 包（`h5py` / `scipy` 之外的东西 / 品牌 SDK）的扩展作者。
> **强制**：导出成品时校验；不合法 = 导出失败（不是警告）。
> **规范实现（唯一）**：`Application/Core/Extension/ExtensionRuntimeDeps.py`
> —— 导出器、成品启动器、离线检查工具、静态审查器全部对齐它。

---

## 0. 一句话

**扩展必须在一个固定的 JSON 字段里说清楚"成品里这些包从哪来"**，二选一：

- `engine` —— 装进**产物自带的运行时镜像**（节点代码在引擎进程里直接 `import`）；
- `bundle` —— 把**整个解释器环境**拷进产物（只给子进程用；三方包与引擎版本/ABI 冲突时不可避免）。

---

## 1. 为什么必须显式声明（2026-11-14 事故）

Gtec 把落盘默认格式改成 HDF5（需要 `h5py`）。PIE 里一切正常，**导出的成品**在
`StopRecord` 落盘那一刻才报：

```
[Device] ERROR: hdf5 export failed: h5py is not installed in the engine interpreter
```

失败的形态是最糟的那种：能开、能录、实验跑完、**数据要落盘时才炸**。

根因不在扩展，也不在引擎运行时清单：

| 环节 | 事实 |
|---|---|
| 编辑器 | 用引擎 venv，`h5py` 装得好好的 |
| 成品 | 用 `Resource/runtime` 这份**独立镜像**（按手写清单烘焙），扩展的包从来不在里面 |
| manifest | 只有 `python.mode/path/probe` —— 全都描述"**编辑器里**用哪个解释器"，**没有一个字段描述成品** |

所以语言里必须有第二条轴。它不是"锦上添花"的元数据：**沉默 = 成品必然缺包**。

---

## 2. 完整语法

`extension.json`：

```json
"python": {
  "mode": "engine",
  "path": "%EXT_DATA%/venv",
  "requirements": "requirements.txt",
  "probe": ["numpy", "h5py"],

  "runtime": {
    "mode": "engine",
    "requires": ["h5py>=3.16"],
    "probe": ["h5py"],
    "optional": false,
    "note": "g.tec g.Recorder layout export needs h5py"
  }
}
```

### 2.1 开发期字段（`python.*`，编辑器 → 扩展代码）

| 键 | 类型 | 说明 |
|---|---|---|
| `mode` | `"engine"` \| `"venv"` \| `"path"` | 编辑器里扩展代码跑在哪个解释器。缺省 `engine` |
| `path` | string | `venv` 目录（或 exe）/ `path` 可执行文件。支持 `%EXT_DIR%` `%EXT_DATA%` `%ENGINE_ROOT%` |
| `requirements` | string | 开发期安装清单（只用于生成可复制的 `install_hint()`，引擎不会替你装） |
| `probe` | string[] | 启动自检的 **import 名** |

### 2.2 产物字段（`python.runtime.*`，成品 → 节点/服务）

| 键 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `mode` | `"engine"` \| `"bundle"` \| `"none"` | ✅ | 见 §3 |
| `requires` | string[] | `engine` | PEP 508 需求串（`h5py>=3.16`、`pyserial>=3.5`） |
| `probe` | string[] | — | 产物里必须 `import` 成功的模块名。**与 `requires` 等长时按位置对应**（`pyserial` → `serial` 这种推导不出来的别名必须这样写） |
| `optional` | bool | — | `true` = 缺包只降级告警，不阻断。默认 `false` |
| `path` | string | `bundle` | 环境目录。省略则回退外层 `python.path` |
| `env` | `{str: str}` | — | `bundle` 子进程附加环境变量 |
| `note` | string | — | 为什么需要。写进导出清单，方便审计 |

**未知键 = 错误**。拼错 `requires` 不会被静默忽略 —— 这正是本契约存在的意义。

### 2.3 ★ `probe` 要列全"成品里会用到的三方模块"，不只是 `requires`

`requires` 描述"**我要装什么**"，`probe` 描述"**成品运行时必须能 import 什么**"。两者不等长时很容易漏：

```json
"requires": ["h5py>=3.16"],                 // 只装 h5py
"probe":    ["h5py", "numpy", "scipy"]      // 但节点求值里还用着 numpy/scipy
```

numpy / scipy 由基础镜像 `Resource/runtime` 提供，**不需要 `requires`**，但**必须进 `probe`**：
成品启动只逐个 `import` probe 列表，漏掉的包不会在启动时报，而是在**第一次真正用到它的地方**
（落盘 / 第一次画图）才 `ModuleNotFoundError`。

> 真实案例（2026-11-17）：某扩展只 probed `h5py`。引擎侧一次导出缺陷让基础镜像的
> `Lib/site-packages` 整层丢失 → 启动 probe 全绿、导出成功、节点第一次落盘才炸。
> 若 probe 里有 `numpy`，启动就会打 `[Player] ERROR:` 并直接指名缺哪个模块。

`check_extension_python.py` 的 **D7** 会扫扩展源码里的三方 import，与 probe 对照给出 WARN。

### 2.4 开发期环境怎么建（推荐配方）

推荐形态是**扩展独立持有自己的环境，但以引擎环境为基座** —— 既能装与引擎冲突的版本，
又不必复制 numpy/scipy 那几百 MB：

```powershell
# 1) 用引擎的解释器建 venv（不要用系统 python：ABI/版本可能与引擎不一致）
.\.venv-py314t\Scripts\python.exe -m venv "%APPDATA%\FlyVibingEngine\extensions\<id>\venv"

# 2) （可选）让这个 venv 能看见引擎已装的包 —— 只装增量依赖
#    Windows 上把引擎 venv 的 site-packages 写进 .pth，比 --system-site-packages 更可控
"$PWD\.venv-py314t\Lib\site-packages" | Set-Content `
  "$env:APPDATA\FlyVibingEngine\extensions\<id>\venv\Lib\site-packages\_engine.pth"

# 3) 装你自己的增量依赖
& "$env:APPDATA\FlyVibingEngine\extensions\<id>\venv\Scripts\python.exe" -m pip install -r requirements.txt
```

manifest 对应写：

```json
"python": {
  "mode": "venv",
  "path": "%EXT_DATA%/venv",
  "requirements": "requirements.txt",
  "probe": ["pygds"],
  "runtime": { "mode": "engine", "requires": ["h5py>=3.16"], "probe": ["h5py", "numpy"] }
}
```

**不要**把 venv 建在扩展源码目录里（`.venv-<id>`）：工具链虽然会把它当第三方目录跳过，
但它会让扩展目录膨胀数百 MB、被 git/备份整棵搬运、换机后路径失效。`%EXT_DATA%`
（`%APPDATA%/FlyVibingEngine/extensions/<id>/`）才是协议位置。

---

## 3. 两种 mode 的语义差别（不要混）

| `runtime.mode` | 落地位置 | 谁用它 | 代价 |
|---|---|---|---|
| `engine` | `<产物>/runtime/Lib/site-packages` | **节点代码**（进程内 `import`） | 产物 +几 MB |
| `bundle` | `<产物>/extensions/<id>/env/` | **只有子进程**（`ctx.python.spawn` 之类） | 产物 +几百 MB（不可避免） |
| `none` | — | 不依赖三方包 | 无 |

> ★ **`bundle` 不能让进程内节点用上那个环境。** 节点求值发生在引擎进程里，
> 一个进程只有一个解释器。需要钉死版本的扩展必须把重活搬进子进程，节点只做 IPC。
> 反过来，只在子进程里用的包**不要**写 `engine` —— 那会把几十 MB 塞进每个产物。

`engine` 的安装顺序（**全部离线**）：

1. `<扩展>/wheels/` 里自带的 wheel；
2. `<引擎>/Resource/wheels/`（`collect_wheels.py` 产出）；
3. 引擎 venv 里**已安装的同一个包**（开发期实测过的版本，直接复制目录）。

三者都没有 → 导出报错（`optional: true` 时降级为告警）。

> ★ 安装一律 `pip install --no-index --no-deps --target …`。`--no-deps` 不是省事：
> `--target` 无视已安装包，会把 `numpy` 之类**再装一份**到产物里，覆盖基础镜像的版本。
> 基础镜像由 `Utils/Dev/prepare_runtime.py` 负责，缺什么由 probe 报错。

---

## 4. 强制点（导出会挡下来）

| # | 规则 | 违反 |
|---|---|---|
| 1 | `runtime` 必须是对象，键集合固定 | 导出失败 |
| 2 | `mode` ∈ `engine/bundle/none` | 导出失败 |
| 3 | `bundle` 必须有可解析且**存在**的环境目录 | 导出失败 |
| 4 | `none` 不得带 `requires` | 导出失败 |
| 5 | **随产物分发的扩展必须显式声明 `runtime`** | 导出失败 |
| 6 | 声明的包必须能**装进产物**（wheel / venv / 已存在） | 导出失败（`optional` 时告警） |
| 7 | 产物启动时 probe 失败 | 启动日志 `[Player] ERROR:`（继续跑，但原因一眼可见） |

第 5 条的含义：**不写不等于没有依赖**。无三方依赖也要写：

```json
"python": { "mode": "engine", "runtime": { "mode": "none" } }
```

---

## 5. 自检工具

```powershell
# 全部扩展（CI / 提交前）
python Utils/Dev/check_extension_python.py --all
python Utils/Dev/check_extension_python.py --all --json      # agent / CI
python Utils/Dev/check_extension_python.py --all --strict    # 告警也算失败（发布前）

# 单个扩展 + 用引擎解释器实跑 import
python Utils/Dev/check_extension_python.py Application/Functions/Gtec --probe

# 静态审查（manifest/代码/完备性，含 M8 = 本契约）
python FlyVibing-User-And-Developer-Utils/packages/extension-kit/review_extension.py <扩展目录>
```

检查项：

| 码 | 内容 |
|---|---|
| `D1` | `extension.json` 合法 |
| `D2` | `python.runtime` 结构合法 |
| `D3` | 随产物分发的扩展已声明契约 |
| `D4` | `bundle` 环境存在且含解释器 |
| `D5` | `engine` 的每个 require 能在 wheelhouse / 引擎 venv 找到来源 |
| `D6` | `--probe`：用引擎解释器实跑 import |

---

## 6. 成品侧行为（`PlayerBootstrap`）

启动最早处（早于任何扩展代码）：

1. 读 `<产物>/extensions/python_envs.json` → `bundle` 出去的环境设为
   `FVE_EXT_PYTHON_<ID>`。所以遵守协议的代码在成品与编辑器里选到**同一个**解释器，
   不需要在产品里也装一个扩展管理器。
2. 读 `<产物>/extensions/python_contracts.json` → 逐个 `probe`：

```
[Player] extension deps ok: device (engine)
[Player] ERROR: extension 'gtec' (engine) missing module(s): h5py
[Player] ERROR:   re-export with the dependency available, or add it to
                  `python.runtime.requires` in the extension manifest
```

启动就报，而不是等第一次落盘。`optional: true` 的扩展降级为 `WARNING`。

---

## 7. 导出清单里的样子

`export_manifest.json`：

```json
"extensions": {
  "python": {
    "gtec": {
      "version": 1, "id": "gtec", "declared": true, "mode": "engine",
      "requires": ["h5py>=3.16"], "probe": ["h5py"], "optional": false,
      "path": "", "env": {}, "note": "…", "problems": []
    }
  },
  "python_problems": []
},
"game": {
  "extension_python": {
    "extensions": {
      "gtec": {"mode": "engine", "installed": [{"requirement": "h5py>=3.16",
                "source": "engine_venv", "detail": "copied from engine venv (…)"}],
               "present": [], "failed": []}
    },
    "summary": "gtec:1 new + 0 present"
  }
}
```

`source` ∈ `wheelhouse` / `engine_venv`，让"这个包到底哪来的"可审计。

---

## 8. 导出瘦身（同批）

随包扩展目录里的 **`Test/` `Doc/` `Docs/` `tests/` `Examples/` `wheels/`** 在导出时删除：

- 示例菜单在成品里不存在，`Examples/` 只有编辑期价值；
- `Test/`/`Doc/` 会把开发期脚本和内部文档暴露给终端用户；
- 扩展自带的 `wheels/` 已在顶部 `wheelhouse/` 统一分发。

被删的目录会写进 `export_manifest.json` 的 `extensions.pruned_subdirs`。

---

## 9. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 导出报 "扩展 'x' 随产物分发，但 manifest 没有 python.runtime 段" | 补 `"runtime": {"mode": "none"}` 或真正的 `requires` |
| 导出报 "wheelhouse 与引擎 venv 都拿不到" | `python Utils/Dev/collect_wheels.py`，或把 wheel 放进 `<扩展>/wheels/` |
| 成品能开但落盘失败 | 检查启动日志 `[Player] ERROR:`；确认 `requires` 写全、`probe` 名字对 |
| 启动 probe 全绿，但节点跑到一半报 `ModuleNotFoundError: numpy` | `probe` 漏了"以为基础镜像一定有"的包（§2.3）。把成品会用到的三方 import 全列进 `probe`；`check_extension_python.py` 的 D7 会提示 |
| 扩展目录几百 MB / git 状态卡 | venv 建在源码目录里了。迁到 `%EXT_DATA%/venv`（§2.4） |
| 包明明装了却 import 不了 | 名字推导不出来（`pyserial` → `serial`）：显式写 `probe` |
| 想钉死版本 | `runtime.mode: "bundle"`（整包环境），并把重活放子进程 |
| 产物忽然大了几百 MB | 有人用了 `bundle`；确认是版本冲突必需，否则换 `engine` |
