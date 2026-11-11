# 路径与宏（Paths & Macros）

> 适用：节点里的 `PathVar` / `TextFileWrite` / `SaveData`、扩展写数据、
> Example 配置、以及任何"这个文件到底会落到哪"的疑问。
> 单一实现在引擎 `Application/Core/FileSystem/DataPaths.py`；
> 本文是**对外可读**的语义说明（扩展作者不必读引擎内部文档）。

---

## 1. 为什么需要它

写文件的痛点从来不是"怎么拼路径"，而是**"我看不出它会落在哪，换台机器还对不对"**。
历史上有三个具体事故：

| 事故 | 原因 |
|---|---|
| 成品里凭空长出 `Test/TestProject/...` 深目录 | 节点按进程 CWD 解析相对路径 |
| 成品装到只读位置，写文件直接失败 | 同上（CWD = 安装目录） |
| 换机器后数据"消失了" | 扩展把开发机绝对路径写进了场景 prop |

后两者的共同点：**不会报错**。文件去了别处，比写失败难查一百倍。

---

## 2. 三种写法，一条求值链

| 写法 | 例 | 可移植 | 什么时候用 |
|---|---|---|---|
| **宏** | `<OutputRoot>/seed/x.txt` | ✅ | **推荐** —— 明确说出是哪个根 |
| **相对** | `seed/x.txt`（配 `relative_to=output`） | ✅ | 日常 90%；等价于 `相对路径落在 output 根` |
| **绝对** | `D:/data/x.npz` | ❌ | 仅调试/本机覆盖；导出会告警 |

```
spec ──展开宏──► text ──绝对?──► 原样（规范化）
                       └─相对?──► join(relative_to 基准, text)
```

**保存时绝不展开**：`.scene` 里存的永远是字面量（`<OutputRoot>/seed`）。
一旦保存时展开，就变回绝对路径，整个机制归零。

---

## 3. 宏一览

| 宏 | 别名 | 含义 | 编辑器 | PIE | 成品 |
|---|---|---|---|---|---|
| `<EngineRoot>` | `<EditorRoot>` | 引擎根（含 `Application/`） | 引擎仓 | 引擎仓 | **成品根** |
| `<ProjectRoot>` | — | `.myproj` 所在目录 | 工程目录 | 工程目录 | **成品根** |
| `<GameRoot>` | — | 游戏根（`game.json` 所在） | 工程目录 | 工程目录 | **成品根** |
| `<OutputRoot>` | — | 写数据的地方 | `<工程>/output` | `<工程>/output` | `<成品>/output` |
| `<Cwd>` | — | 进程工作目录 | 逃生口，**不要**用作默认 | | |

两条容易踩的：

1. **`<GameRoot>` 与 `<ProjectRoot>` 目前恒同值**（成品里 myproj 与 game.json 并存，
   PIE 里游戏读的就是工程）。分成两个名字是为了**语义**：将来两者真分离时，
   用 `<GameRoot>` 的图自动正确。
2. **`<EditorRoot>` 是 `<EngineRoot>` 的别名** —— 成品里没有编辑器，但**有引擎**（冻结副本）。
   两个名字都认，老习惯不用改。

### 语法为什么是 `<Name>`

`<` `>` 在 Windows 上**是非法文件名字符** → 磁盘上不可能存在与宏同名的真实目录，
"这是宏还是文件夹"的歧义从根上消失。

对比：`$(Name)` 和 `%NAME%` 都是**合法文件名字符**，真会撞上同名目录；
`%NAME%` 还会与 Windows 环境变量语法混淆（我们不展开环境变量）。

宏名**大小写不敏感**（`<gameroot>` == `<GameRoot>`）。

### 未知宏 = 报错，不是猜

```
<Nope>/x            → PathMacroError（节点打 error 日志并**跳过写入**）
<GameRoot>typo.txt  → 不报错：没有闭合 `>`，按普通文件名处理
```

写错地方比写失败难查，所以这里选择"大声失败"。

---

## 4. 在节点里用

`PathVar` / `TextFileWrite` / `SaveData` 都有：

| prop | 取值 | 说明 |
|---|---|---|
| `path` / `file_path` | 任意 spec | 支持宏 |
| `relative_to` | `output`（默认）/ `project` / `cwd` | **只在没有宏**且路径是相对时生效 |

```
PathVar(path="<OutputRoot>/seed")  → TextFileWrite(FileName=<date>) 
落点: <output 根>/seed/MI-SSSEP-Seed-2026-11-11-19-40.txt
```

`PathVar` 输出的是**解析后的绝对路径**，所以下游节点不会与它产生分歧
（两个节点各自解释相对路径，是早期一个静默 bug 的来源）。

> `relative_to=cwd` 保留给明确知道自己要 CWD 的场景；导出时这类写法不会告警，
> 但换机器仍然可能落错地方。

---

## 5. 在扩展里用（`ctx.paths`）

```python
ctx.paths.engine_root          # 绝对路径
ctx.paths.project_root
ctx.paths.game_root
ctx.paths.output_root

ctx.paths.resolve("<ProjectRoot>/assets/x.npy")   # 纯函数（不建目录）
ctx.paths.ensure("<OutputRoot>/gtec")             # 解析 + makedirs
ctx.paths.expand("<OutputRoot>/x")               # 只展开宏
ctx.paths.macros()                               # {"<EngineRoot>": ..., ...}
ctx.paths.describe()                             # 一行摘要（启动日志打一条最有用）
```

规则：

1. **不要 `os.getcwd()`**。成品里 CWD 就是安装目录，可能是只读的。
2. **不要把本机绝对路径存进节点 prop**。导出器会把它列进 `export_manifest.json`
   的 `absolute_paths` 并打 `PORTABILITY` 告警 —— 因为它换机器就断。
3. 推荐三态（以设备录制目录为例）：
   `空` → `<OutputRoot>/<ext>/`（推荐默认）/ `相对路径` → `<OutputRoot>/<相对>` /
   `绝对路径` → 原样（显式覆盖）。
4. `save_data(..., roots=ctx.paths._roots())` 或直接 `ctx.paths.resolve()` 后再传
   绝对路径 —— 两条都行，别自己拼。

---

## 6. 查当前落点（CLI / MCP）

```powershell
# 当前形态的四个根 + 宏表
engine-editor-cli call path.roots

# 问"这个 spec 会落在哪"（含人读摘要）
engine-editor-cli call path.roots resolve="<OutputRoot>/seed/x.txt" text=true
```

返回：

```jsonc
{
  "roots":   {"engine": "...", "project": "...", "game": "...", "output": "...", "cwd": "..."},
  "macros":  {"<EngineRoot>": "...", "<OutputRoot>": "...", ...},
  "aliases": {"<EditorRoot>": "<EngineRoot>"},
  "resolve": {"spec": "<OutputRoot>/seed/x.txt",
              "expanded": "...output/seed/x.txt",     // 只展开宏
              "absolute": "...output\\seed\\x.txt"}   // 最终落点
}
```

未知宏时 `resolve` 里给 `error` 字段（不是静默给个路径）。

---

## 7. 导出时的三条行为

| 项 | 行为 |
|---|---|
| 含宏的路径 | ✅ 不告警（正确答案存在，就不需要骂人） |
| 纯相对路径 | ✅ 不告警 |
| **绝对路径** | ⚠️ `[Export] PORTABILITY:` + `export_manifest.json` 的 `absolute_paths` |
| `output/` | 成品自带；所有默认写入都进这里 |

导出器**不会**替你改写场景里的绝对路径 —— 只报出来。改写是"静默魔法"，
比报错更难查。

---

## 8. 常见问题

**Q: 我在编辑器里跑，数据落在 `<工程>/output`；导出后在成品里跑，落在哪？**
A: `<成品>/output`。同一个图、同一份场景，不用改任何东西 —— 这正是宏的价值。

**Q: 工程还没保存（Untitled）时 `<ProjectRoot>` 是什么？**
A: 尚未设置 → 回退到引擎根。保存/另存之后会自动跟着变（`ProjectManager` 在
open/create/save-as 三处同步根）。

**Q: 我能加自定义宏吗？**
A: 不能。宏是引擎维护的**封闭集合** —— 可扩展的"根"会让"同一份场景在别人机器上
指向不同目录"，正是我们要消除的问题。需要新的根请提需求。

**Q: `MGE_OUTPUT_DIR` 是干嘛的？**
A: 把 `<OutputRoot>` 整体改道（部署到只读盘、多用户机器、批量跑时很有用）。
它优先于派生值，但**不改变** `<ProjectRoot>` 等其它根。

**Q: 干跑（`--dry-run`）会建目录吗？**
A: 不会。解析是纯函数，创建目录只发生在真正写入时。早期实现在 dry-run 里也
`makedirs`，已修并纳入守卫。
