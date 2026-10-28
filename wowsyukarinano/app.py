"""The program: the win rates of both teams beside the game's Tab team list.

Run:  python -m wowsyukarinano.app   (or wowsyukarinano.exe, built with build.bat)

The splash shows while the OCR models load, then the main window opens and the transparent overlay waits
on the game. Once a battle file is being written, the player list comes from the replay (livereplay.py,
replaydata.py) and the public win rates are fetched in the background (playerstats.py). While Tab is held,
the team list on screen is found, each row is matched to a player (roster.py) and the rates are drawn
beside it (overlay.py).
"""
import ctypes
import datetime
import json
import os
import queue
import signal
import sys
import threading
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from . import brand
from .livereplay import LiveReplay
from .modes import find_battle_file, replay_folder
from .paths import ASSETS, CONFIG, DATA, DEFAULT_CONFIG, FROZEN, rotate


def load_config():
    """config.json next to the exe; the bundled default when it is missing or broken.

    Returns (config, problem text or None)."""
    default = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")) if DEFAULT_CONFIG.exists() else None
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is None:
            raise
        return default, None
    except ValueError as error:
        if default is None:
            raise
        return default, f"config.json 格式有误，已使用默认配置（{error}）"
    if default:                         # keys added in newer versions
        for key, value in default.items():
            cfg.setdefault(key, value)
            if isinstance(value, dict) and isinstance(cfg[key], dict):
                for inner, inner_value in value.items():
                    cfg[key].setdefault(inner, inner_value)
    return cfg, None


class Bridge(QObject):
    notice = pyqtSignal(str, str, bool)   # -> the line under the main window's picture
    ready = pyqtSignal()
    info = pyqtSignal(object)             # -> main window, about once a second
    screen = pyqtSignal(object)           # the game changed monitor: (left, top, right, bottom)
    roster = pyqtSignal(object)           # -> overlay: roster.Roster, or None when the list is gone


class Worker(threading.Thread):
    """Follows the battle replay and, while Tab is held, the team list on screen."""

    def __init__(self, cfg, bridge):
        super().__init__(daemon=True)
        self.cfg, self.bridge = cfg, bridge
        self.cap = None
        from .playerstats import PlayerStats
        self.player_stats = PlayerStats()
        self._roster_t = 0.0              # last look at the team list
        self._roster_seen = 0             # frames since the list appeared
        self._roster_rows = None          # (BattleData, roster.RowFinder) of this battle
        self._roster_shown = False
        self._tab_since = None            # when Tab went down
        self._tab_clicked = False         # a mouse click ended the columns for this hold of Tab
        self._roster_last_ok = 0.0        # when the list was last found
        self._stats_asked = None
        self._warned_players = False
        self._screen_rect = None          # the monitor the game is on
        self._last_screen_check = 0.0
        self._updating = False            # the ship list is being rebuilt
        self.ocr = self.db = None
        self.folder = None                # replays folder, once the game is found
        self.game_dir = None
        self.live = None                  # livereplay.LiveReplay
        self._last_game_check = 0.0
        self._game_req = queue.Queue()
        self._live_path = None
        self._last_live_report = 0.0
        self._live_problem = None
        self._last_info = 0.0
        self.capturable = bool(cfg.get("overlay", {}).get("capturable", True))
        self.rates_rect = None            # -> overlay.rate_rects: where the columns were drawn last

    def set_game_dir(self, path):
        """A folder chosen by the user (from the GUI thread)."""
        self._game_req.put(path)

    def _check_game_dir(self, chosen=None, force=False):
        """Find the game; while running, follow the install the game is started from."""
        from . import settings
        from .gamedir import find_game_dir, running_game_dir
        now = time.perf_counter()
        if not force and now - self._last_game_check < 10.0:
            return
        self._last_game_check = now
        if force or self.game_dir is None:
            path, how = find_game_dir(self.cfg, chosen or settings.load().get("game_dir"))
        else:
            path, how = running_game_dir(), "running game"
            if path is None or path == self.game_dir:
                return
        if path is None or path == self.game_dir:
            return
        self.game_dir = path
        self.cfg["game_dir"] = str(path)
        self.folder = replay_folder(self.cfg)
        self.say(f"游戏目录：{path}（{how}）")
        self._start_data_update()
        self._follow_replays()

    def _follow_replays(self):
        """Tail the replays folder, a new one after the game was found or moved."""
        if self.live is not None:
            self.live.stop()
            self.live = None
        if self.folder:
            self.live = LiveReplay(self.folder)
            self.live.start()

    def _start_data_update(self):
        """After a game update the ship list is rebuilt from the client in the background."""
        if self._updating or self.game_dir is None:
            return
        self._updating = True

        def work():
            try:
                from . import shipdata
                if shipdata.update_if_needed(self.game_dir, self._data_say):
                    self._reload_data()
            except Exception as error:      # noqa: BLE001 - never let this stop the program
                self.say(f"船只数据更新出错：{error!r}")
                self.tell("船只数据更新失败，继续使用旧数据", "warn")
            finally:
                self._updating = False
        threading.Thread(target=work, daemon=True).start()

    def _reload_data(self):
        """Use the new ship list; the row matching reads ship names from it."""
        from .ships import ShipDB
        self.db = ShipDB()

    def say(self, text):
        """A line for the log (and the console when there is one)."""
        if sys.stdout is not None:
            print(f"[{datetime.datetime.now():%H:%M:%S}] {text}", flush=True)

    def tell(self, text, level="info", sticky=False):
        """A short line for the user under the picture; the details go to say()."""
        self.bridge.notice.emit(text, level, sticky)

    def _data_say(self, text):
        """shipdata's lines: all to the log, the gist to the user."""
        self.say(text)
        if "正在更新" in text:
            self.tell("游戏已更新，正在更新船只数据…", "info", sticky=True)
        elif "已更新：" in text:
            self.tell("船只数据已更新", "ok")
        elif "失败" in text:
            self.tell("船只数据更新失败，继续使用旧数据", "warn")

    def run(self):
        try:
            self._load()
        except Exception as error:          # noqa: BLE001 - show it in the window instead of dying silently
            import traceback
            traceback.print_exc()
            self.say(f"启动失败：{error!r}")
            self.tell("启动失败，请重启程序", "warn", sticky=True)
            self.bridge.ready.emit()
            return
        try:
            self._loop()
        except RuntimeError as error:       # the windows were closed under us, or a real error
            print(f"worker stopped: {error!r}", flush=True)

    def _load(self):
        from rapidocr_onnxruntime import RapidOCR
        from .capture import Capturer
        from .ships import ShipDB
        from .screen import ScreenGeometry
        self.ocr = RapidOCR()
        self.db = ShipDB()
        self.cap = Capturer(geometry=ScreenGeometry(*self.cfg.get("_screen_px", (1920, 1080))))
        self._check_game_dir(force=True)
        self.say("就绪：在游戏里按住 Tab 显示双方胜率")
        self.bridge.ready.emit()

    def _loop(self):
        while True:
            while not self._game_req.empty():
                self._check_game_dir(chosen=self._game_req.get(), force=True)
            self._check_game_dir()
            self._check_screen()
            self._report_live()
            self._report_info()
            self._roster_step()
            time.sleep(0.02)

    def _check_screen(self):
        """Every few seconds: which monitor the game is on. The capture follows it here, the overlay in
        the GUI thread (bridge.screen)."""
        now = time.time()
        if now - self._last_screen_check < 2.5:
            return
        self._last_screen_check = now
        from . import monitor
        rect = monitor.game_monitor()
        if rect is None or rect == self._screen_rect:
            return
        self._screen_rect = rect
        size = (rect[2] - rect[0], rect[3] - rect[1])
        self.cfg["_screen_px"] = size
        if self.cap is not None:
            from .screen import ScreenGeometry
            try:
                device, output = monitor.dxcam_output(rect)
                self.cap.retarget(device, output, ScreenGeometry(*size))
            except Exception as error:      # noqa: BLE001 - keep reading the old monitor rather than stop
                self.say(f"切换到游戏所在的显示器失败：{error!r}")
        self.bridge.screen.emit(rect)

    def _grab_frame(self, timeout=0.02):
        """One frame in the 1080p layout, or None when the desktop did not change."""
        cap = self.cap
        grabbed = cap.grab(timeout=timeout) if cap is not None else None
        return grabbed[1] if grabbed else None

    def stats_of(self, entity):
        """The win rates of the player in this Vehicle entity, or None."""
        stats, live = self.player_stats, self.live
        player = live.battle.players.get(entity) if (stats is not None and live is not None) else None
        return stats.get(player.account, player.params) if player is not None and player.account else None

    def _ask_stats(self):
        """Once the player list of a battle is in: both teams' win rates, in the background."""
        stats, live = self.player_stats, self.live
        if live is None or live.path is None:
            return
        battle = live.battle
        # A new battle is a new BattleData (LiveReplay._reset); the battle file itself is always the same
        # temp.wowsreplay, and player count and own team match in most battles, so neither tells one battle
        # from the next. Within a battle the count only says the list has grown.
        if self._stats_asked is None or self._stats_asked[0] is not battle:
            stats.clear()
        elif self._stats_asked[1:] == (len(battle.players), battle.own_team) or battle.own_team is None:
            return
        if battle.own_team is None:
            return
        self._stats_asked = (battle, len(battle.players), battle.own_team)
        stats.want([(player.account, player.params, player.realm)   # both teams: the Tab list
                    for player in battle.players.values() if player.account])

    def _hide_roster(self):
        if self._roster_shown:
            self._roster_shown = False
            self.bridge.roster.emit(None)

    def _roster_step(self):
        """While Tab is held: where the team list is and who each row is, for the win rates beside it.

        The key is read on every pass of the loop (20 ms), so the first look happens as soon as Tab goes
        down. The list is then looked for on every pass while it fades in, 10 times a second while it is up
        (the order changes as ships are sunk) and 5 times a second while Tab is held with no list (in port,
        say). A mouse click while Tab is held (a row picked, a context menu opened) ends the columns until
        the key is pressed again: the game's own menu would otherwise lie under them.
        """
        now = time.perf_counter()
        from .capture import _key_down, _mouse_clicked, game_in_front
        live = self.live
        if not (live is not None and live.path is not None and self.cap is not None
                and _key_down(0x09)                                          # VK_TAB
                and game_in_front(self.cfg)):
            _mouse_clicked()                # drop a click made before Tab went down
            self._tab_since = None
            self._tab_clicked = False
            self._roster_seen = 0
            self._hide_roster()
            return
        if self._tab_since is None:
            self._tab_since = now
        if not self._tab_clicked and _mouse_clicked():
            self._tab_clicked = True
        if self._tab_clicked:
            self._hide_roster()
            return
        if now - self._tab_since < 0.25:        # just pressed: the list is fading in
            interval = 0.0
        elif now - self._roster_last_ok < 0.5:  # the list is up
            interval = 0.1
        else:                                   # held with no list
            interval = 0.2
        if interval and now - self._roster_t < interval:
            return
        self._roster_t = now
        frame = self._grab_frame()
        if frame is None:
            return                              # no frame this time: keep what is shown
        if self.capturable and self.rates_rect is not None:
            # the window is in screenshots, so the frame holds the columns drawn last time: blank them out
            # (they lie beside the list) or the search would take them for a longer header bar
            for x0, y0, x1, y1 in self.rates_rect():
                frame[max(int(y0), 0):int(y1), max(int(x0), 0):int(x1)] = 0
        from . import roster
        table = roster.find_table(frame)
        if table is None:
            self._roster_seen = 0
            self._hide_roster()
            return
        self._roster_seen += 1
        self._roster_last_ok = now
        battle = live.battle

        def who(entity, player):
            ship = self.db.by_id(player.params) if self.db is not None and player.params else None
            return (entity, player.name, player.clan, ship["name"] if ship else "")

        players = list(battle.players.items())
        ours = [who(entity, player) for entity, player in players if player.team == battle.own_team]
        theirs = [who(entity, player) for entity, player in players if player.team != battle.own_team]
        if self._roster_rows is None or self._roster_rows[0] is not battle:   # a new battle
            self._roster_rows = (battle, roster.RowFinder(self.ocr))
        # (the rows are not read on the list's first frame: it fades in)
        rows_ours, rows_theirs, log = self._roster_rows[1].rows(
            frame, table, ours, theirs, may_read=self._roster_seen >= 2)
        if log:
            known = sum(entity is not None for entity in rows_ours + rows_theirs)
            print(f"team list: {len(log)} rows read, {known} of {len(ours) + len(theirs)} known", flush=True)
            for line in log:
                print(line, flush=True)
        self._roster_shown = True
        self.bridge.roster.emit(roster.Roster(table, rows_ours, rows_theirs,
                                              roster.colors(frame, table, len(rows_ours), len(rows_theirs))))

    def _report_live(self):
        """Once a second: battle file found or gone, or a file that cannot be read."""
        now = time.perf_counter()
        if self.live is None or now - self._last_live_report < 1.0:
            return
        self._last_live_report = now
        path = self.live.path
        if path != self._live_path:
            if path is not None:
                self.say("对局开始")
                self.tell("对局开始", "ok")
            elif self._live_path is not None:
                gaps = self.live.prev_gaps
                self.say(f"对局结束（回放数据最长间隔 {gaps[0]:.1f} 秒，超过 2 秒 {gaps[1]} 次）")
                self.tell("对局结束", "info")
            self._live_path = path
            self._warned_players = False
        if (path is not None and not self._warned_players and self.live.pos > 300000
                and not self.live.battle.players and not self.live.problem):
            self._warned_players = True     # the player list of this kind of battle was not understood
            self.say("没有读到这局的玩家名单（这个模式的格式可能没见过）：胜率显示用不了，请保留这局的回放文件")
            self.tell("这局读不到对局信息，胜率暂不可用", "warn", sticky=True)
        self._ask_stats()
        problem = self.live.problem
        if problem and problem != self._live_problem:
            self.say("读不到回放里的玩家名单，胜率暂不可用（游戏可能有更新）")
            self.tell("游戏可能已更新，胜率暂不可用", "warn", sticky=True)
        self._live_problem = problem

    def _report_info(self):
        now = time.perf_counter()
        if now - self._last_info < 1.0:
            return
        self._last_info = now
        self.bridge.info.emit({"battle": find_battle_file(self.folder) is not None,
                               "game_dir": str(self.game_dir) if self.game_dir else None})


def _single_instance():
    """True if no other copy is running (two overlays would draw over each other)."""
    kernel32 = ctypes.windll.kernel32
    # the handle is kept on the function so the mutex lives as long as the process
    _single_instance.handle = kernel32.CreateMutexW(None, False, f"Local\\{brand.APP_ID}-overlay")
    return kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS


def main():
    DATA.mkdir(exist_ok=True)
    if FROZEN and sys.stdout is None:
        # windowed exe: no console, keep tracebacks and library output in a file
        rotate(DATA / f"{brand.APP_ID}.log", 1_000_000)
        sys.stdout = sys.stderr = open(DATA / f"{brand.APP_ID}.log", "a", encoding="utf-8", buffering=1)
        print(f"--- start {datetime.datetime.now().isoformat(timespec='seconds')}")
    elif sys.stdout is not None:
        # a console whose code page cannot write Chinese (a Japanese Windows, say) must not stop the program
        try:
            sys.stdout.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(brand.APP_ID)   # own taskbar icon
    import traceback

    def log_exception(kind, exc_type, exc, tb):
        print(f"{kind}: " + "".join(traceback.format_exception(exc_type, exc, tb)), flush=True)
    sys.excepthook = lambda t, e, tb: log_exception("error in the GUI", t, e, tb)
    threading.excepthook = lambda args: log_exception(
        f"error in thread {args.thread.name if args.thread else '?'}",
        args.exc_type, args.exc_value, args.exc_traceback)
    if FROZEN:
        built = datetime.datetime.fromtimestamp(os.path.getmtime(sys.executable)).isoformat(timespec="minutes")
        print(f"program built {built}", flush=True)
    print(f"version {brand.VERSION}", flush=True)
    application = QApplication(sys.argv)
    application.setWindowIcon(QIcon(str(ASSETS / "icon.ico")))
    if not _single_instance():
        QMessageBox.information(None, brand.TASKBAR, f"{brand.TASKBAR} 已经在运行。")
        return
    splash = QSplashScreen(QPixmap(str(ASSETS / "loading.png")))
    splash.show()
    application.processEvents()
    try:
        cfg, cfg_problem = load_config()
    except (OSError, ValueError) as error:
        splash.close()
        QMessageBox.critical(None, brand.TITLE, f"读取 config.json 失败：\n{CONFIG}\n\n{error}")
        return
    screen = application.primaryScreen()
    screen_px = (round(screen.geometry().width() * screen.devicePixelRatio()),
                 round(screen.geometry().height() * screen.devicePixelRatio()))

    from .mainwindow import MainWindow
    from .overlay import GAME_FONTS, Overlay
    from .screen import ScreenGeometry
    overlay = Overlay(application.primaryScreen().geometry())
    overlay.geo = ScreenGeometry(*screen_px)
    overlay.setWindowTitle(brand.TASKBAR)
    # the client's fonts come with the program, so the columns use the game's own letters
    overlay.add_game_fonts([ASSETS / "fonts" / name for name in GAME_FONTS
                            if (ASSETS / "fonts" / name).exists()])
    bridge = Bridge()
    cfg["_screen_px"] = screen_px
    worker = Worker(cfg, bridge)
    worker.rates_rect = lambda: overlay.rate_rects
    overlay.set_player_stats(worker.stats_of)
    overlay.set_capturable(worker.capturable)
    window = MainWindow(worker)

    def on_screen(rect):
        """The game runs on another monitor: the overlay goes there and is laid out for its size."""
        nonlocal screen_px
        from . import monitor
        size = (rect[2] - rect[0], rect[3] - rect[1])
        target = monitor.pick_screen(application, rect)
        if target is not None:
            if overlay.windowHandle() is not None:
                overlay.windowHandle().setScreen(target)
            overlay.setGeometry(target.geometry())
        if size != screen_px:
            screen_px = size
            overlay.geo = ScreenGeometry(*size)
            worker.say(f"游戏所在的显示器：{size[0]}×{size[1]}")
        overlay.update()

    bridge.screen.connect(on_screen)
    bridge.roster.connect(overlay.set_roster)
    bridge.notice.connect(window.tell)
    bridge.info.connect(window.set_info)

    def on_ready():
        window.start()
        splash.finish(window)
        if screen_px != (1920, 1080):
            worker.say(f"屏幕分辨率 {screen_px[0]}×{screen_px[1]}：已自动适配")
            worker.tell(f"已适配 {screen_px[0]}×{screen_px[1]} 分辨率", "ok")
        if not worker.game_dir:
            worker.tell("没有找到游戏目录，胜率显示暂不可用", "warn", sticky=True)
        if cfg_problem:
            worker.say(cfg_problem)
            worker.tell("配置文件有误，已使用默认设置", "warn", sticky=True)

    bridge.ready.connect(on_ready)
    worker.start()
    overlay.show()
    # let Ctrl+C in a console stop the program (the timer gives Python a chance to see it)
    signal.signal(signal.SIGINT, lambda *_: application.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)
    application.exec()


if __name__ == "__main__":
    main()
