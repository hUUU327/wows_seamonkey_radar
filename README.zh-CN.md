# wowsyukari-nano

[English](README.md) | **简体中文**

按住 **Tab** 时，在《战舰世界》的团队列表两侧显示双方玩家的胜率。

![战绩面板预览](docs/preview.png)

## 功能

- 按住 Tab，在队伍列表两侧多画四列：**本船胜率 / 场数**、**账号胜率 / 场数**；表头颜色、行底色、行距和字体都取自游戏自己的列表，看起来像列表的一部分。
- 双方玩家的账号与船只来自游戏正在写入的对局回放（只读），战绩来自官方战绩页的公开数据（随机战），每局开始时在后台查询。
- 鼠标点一下（点选玩家、弹出右键菜单）立刻隐藏，松开 Tab 再按一次恢复。
- 面板可以被截图、录屏（`overlay.capturable`）；关掉它则完全不参与任何屏幕捕获。

## 使用

**打包版**：从 [Releases](https://github.com/hUUU327/wows_seamonkey_radar/releases) 下载
`wowsyukarinano_v1.0.zip`，解压后双击 `wowsyukarinano.exe`。（若尚未发布，请用下面的源码方式构建。）

**源码**：Python 3.12 + Windows 10/11

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
wowsyukarinano.bat
```

### 游戏设置

- 客户端须设为 **窗口化全屏幕**（独占全屏会盖住所有叠加层）。
- 客户端须 **开启回放录制**（设置 → 其它 → 回放）：玩家列表来自对局回放。

## 配置

`config.json` 在程序旁边，修改后重启生效。

| 键 | 说明 |
| --- | --- |
| `game_dir` | 游戏安装目录；留空则自动查找（运行中的游戏、注册表、Steam 库、常见目录） |
| `trigger.window_title` / `trigger.game_exe` | 判断游戏是否在前台 |
| `live_replay.folder` | 回放目录；留空则用 `<游戏目录>\replays` |
| `overlay.capturable` | 胜率面板是否出现在截图/录屏里，默认 `true` |

## 构建

```
build.bat
```

产物在 `local\dist\wowsyukarinano\wowsyukarinano.exe`（PyInstaller，单目录、无控制台）。

## 目录

| 路径 | 内容 |
| --- | --- |
| `wowsyukarinano\app.py` | 入口、工作线程、主循环 |
| `wowsyukarinano\livereplay.py`、`replaydata.py` | 跟随对局回放，解出玩家列表 |
| `wowsyukarinano\roster.py` | 在屏幕上找到队伍列表，匹配每一行 |
| `wowsyukarinano\playerstats.py` | 查询公开战绩 |
| `wowsyukarinano\overlay.py` | 透明叠加层：画出四列 |
| `wowsyukarinano\mainwindow.py`、`vista.py` | 主窗口与窗口外观 |
| `wowsyukarinano\capture.py`、`screen.py`、`monitor.py` | 屏幕捕获、分辨率映射、显示器切换 |
| `wowsyukarinano\gamedir.py`、`gamefiles.py`、`shipdata.py`、`ships.py` | 找游戏、读客户端文件、船名表 |
| `local\assets` | 图片、图标、字体、船名表 |

## 说明与限制

- 只支持 Windows；需要联网。
- 只有**随机战**的战绩（官方战绩页对随机战公开）；其它模式显示 `—`，账号隐藏战绩显示"战绩已隐藏"。
- 只读取回放文件与公开网页，不修改游戏、不读写游戏内存、不注入。
- 游戏更新后船名表会自动重建；若回放格式变化，界面提示"这局读不到对局信息"，此时胜率不可用。
- 使用第三方叠加层可能违反游戏服务条款，风险由使用者承担。

## 许可

本仓库的代码以 [Unlicense](LICENSE) 发布：放弃全部版权，进入公有领域，可任意使用、修改、分发、商用，
不要求署名，也不提供任何担保。

`local/assets/fonts` 与 `local/assets/ships.json` 取自游戏客户端，版权归 Wargaming 所有，
仅用于让界面与游戏保持一致。
