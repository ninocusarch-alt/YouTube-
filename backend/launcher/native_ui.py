import ctypes
import json
import os
import queue
import threading
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

from app.config import get_settings
from app.live.hub import hub
from launcher.backend_probe import BackendProbeStatus, probe_backend
from launcher.caption_overlay import CaptionOverlay
from launcher.config_store import ConfigStore, MAX_API_KEY_LENGTH
from launcher.key_validator import validate_api_key_sync
from launcher.server_controller import ServerController, ServerState
from launcher.startup_manager import StartupManager
from launcher.view_model import LauncherViewModel
from launcher.win32_types import LRESULT, WNDPROC, WNDCLASSEXW


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WM_CREATE, WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER = 1, 2, 0x10, 0x111, 0x113
WM_SETFONT, EM_SETSEL, EM_REPLACESEL, EM_SETLIMITTEXT = 0x30, 0xB1, 0xC2, 0xC5
WS_CHILD, WS_VISIBLE, WS_BORDER, WS_TABSTOP = 0x40000000, 0x10000000, 0x00800000, 0x00010000
WS_OVERLAPPEDWINDOW = 0x00CF0000
ES_PASSWORD, ES_MULTILINE, ES_AUTOVSCROLL, ES_AUTOHSCROLL, ES_READONLY = 0x20, 4, 0x40, 0x80, 0x800
SW_SHOW, SW_SHOWMINIMIZED, CW_USEDEFAULT, COLOR_WINDOW, IDC_ARROW = 5, 2, -2147483648, 5, 32512
MB_OK, MB_ICONWARNING, MB_ICONERROR, MB_YESNO, IDYES = 0, 0x30, 0x10, 4, 6
ID_START, ID_STOP, ID_RESTART, ID_CONFIGURE, ID_HEALTH, ID_AUTOSTART, ID_EXTENSION = 101, 102, 103, 104, 105, 106, 107
ID_LIVE = 108
ID_LIVE_MIC, ID_LIVE_SYSTEM, ID_LIVE_OVERLAY = 109, 110, 111
BS_AUTOCHECKBOX, BM_GETCHECK, BM_SETCHECK = 0x0003, 0x00F0, 0x00F1
ID_KEY_SAVE, ID_KEY_CANCEL, ID_KEY_EDIT = 201, 202, 203
EN_CHANGE = 0x0300
BACKEND_PORT = int(os.environ.get('VIDEO_COMPANION_PORT', '8000'))
LIVE_API = f'http://127.0.0.1:{BACKEND_PORT}/api/live'
LIVE_CONSOLE_URL = f'http://127.0.0.1:{BACKEND_PORT}/live/console.html'
LIVE_OVERLAY_URL = f'http://127.0.0.1:{BACKEND_PORT}/live/overlay.html'


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def message_box(parent: int, title: str, message: str, flags: int = MB_OK) -> int:
    return user32.MessageBoxW(parent, message, title, flags)


def _register(name: str, callback: WNDPROC) -> None:
    window_class = WNDCLASSEXW(
        ctypes.sizeof(WNDCLASSEXW), 0, callback, 0, 0, kernel32.GetModuleHandleW(None),
        None, user32.LoadCursorW(None, IDC_ARROW), COLOR_WINDOW + 1, None, name, None,
    )
    user32.RegisterClassExW(ctypes.byref(window_class))


def _command_id(wparam: int) -> int:
    return wparam & 0xFFFF


class ApiKeyPrompt:
    def __init__(self, parent: int) -> None:
        self.parent = parent
        self.hwnd = 0
        self.edit = 0
        self.counter = 0
        self.result: str | None = None
        self.callback = WNDPROC(self._proc)
        _register('VideoCompanionKeyPrompt', self.callback)

    def _control(self, kind: str, text: str, style: int, x: int, y: int, w: int, h: int, item: int = 0) -> int:
        return user32.CreateWindowExW(0, kind, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h,
                                     self.hwnd, item, kernel32.GetModuleHandleW(None), None)

    def _proc(self, hwnd: int, msg: int, wp: int, lp: int) -> int:
        if msg == WM_CREATE:
            self.hwnd = hwnd
            self._control('STATIC', '请将千问（DashScope）API Key 粘贴到下方。', 0, 25, 22, 490, 24)
            self._control('STATIC', 'Key 只保存在本机 .env 文件，不会写入插件。', 0, 25, 50, 490, 24)
            self.edit = self._control(
                'EDIT', '', WS_BORDER | WS_TABSTOP | ES_PASSWORD | ES_AUTOHSCROLL,
                25, 83, 490, 30, ID_KEY_EDIT,
            )
            user32.SendMessageW(self.edit, EM_SETLIMITTEXT, MAX_API_KEY_LENGTH, 0)
            self.counter = self._control('STATIC', f'已输入 0 / {MAX_API_KEY_LENGTH} 个字符', 0, 25, 119, 250, 22)
            self._control('BUTTON', '保存并验证', WS_TABSTOP, 300, 151, 115, 32, ID_KEY_SAVE)
            self._control('BUTTON', '取消', WS_TABSTOP, 423, 151, 92, 32, ID_KEY_CANCEL)
            user32.SetFocus(self.edit)
            return 0
        if msg == WM_COMMAND:
            item = _command_id(wp)
            notification = (wp >> 16) & 0xFFFF
            if item == ID_KEY_EDIT and notification == EN_CHANGE:
                length = user32.GetWindowTextLengthW(self.edit)
                user32.SetWindowTextW(self.counter, f'已输入 {length} / {MAX_API_KEY_LENGTH} 个字符')
                return 0
            if item == ID_KEY_SAVE:
                length = user32.GetWindowTextLengthW(self.edit)
                value = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(self.edit, value, length + 1)
                if not value.value.strip():
                    message_box(hwnd, '尚未填写', '请先粘贴千问 API Key。', MB_ICONWARNING)
                    return 0
                self.result = value.value.strip()
                user32.DestroyWindow(hwnd)
                return 0
            if item == ID_KEY_CANCEL:
                user32.DestroyWindow(hwnd)
                return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def show(self) -> str | None:
        user32.EnableWindow(self.parent, False)
        self.hwnd = user32.CreateWindowExW(
            0, 'VideoCompanionKeyPrompt', '配置千问 API Key', WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT, CW_USEDEFAULT, 555, 255, self.parent, None, kernel32.GetModuleHandleW(None), None,
        )
        user32.ShowWindow(self.hwnd, SW_SHOW)
        message = wintypes.MSG()
        while user32.IsWindow(self.hwnd) and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.EnableWindow(self.parent, True)
        user32.SetForegroundWindow(self.parent)
        return self.result


class NativeLauncherWindow:
    def __init__(
        self,
        store: ConfigStore,
        *,
        startup_manager: StartupManager | None = None,
        start_minimized: bool = False,
        runtime_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.view_model = LauncherViewModel()
        self.events: queue.Queue[tuple[ServerState, str]] = queue.Queue()
        self.live_events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.live_running = False
        self.live_pending = False
        self.live_queued = False
        self.busy = False
        self.hwnd = self.status = self.detail = self.key_status = self.log = 0
        self.buttons: dict[int, int] = {}
        self.font = 0
        self.callback = WNDPROC(self._proc)
        self.controller = ServerController(store, state_listener=lambda state, text: self.events.put((state, text)))
        self.startup_manager = startup_manager
        self.start_minimized = start_minimized
        self.runtime_dir = (runtime_dir or store.env_file.parent).resolve()
        self.overlay = CaptionOverlay(self.runtime_dir, hub)
        self.level_label = 0
        _register('VideoCompanionLauncher', self.callback)

    def _control(self, kind: str, text: str, style: int, x: int, y: int, w: int, h: int, item: int = 0) -> int:
        handle = user32.CreateWindowExW(0, kind, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h,
                                       self.hwnd, item, kernel32.GetModuleHandleW(None), None)
        if self.font:
            user32.SendMessageW(handle, WM_SETFONT, self.font, True)
        return handle

    def _proc(self, hwnd: int, msg: int, wp: int, lp: int) -> int:
        if msg == WM_CREATE:
            self.hwnd = hwnd
            self.font = gdi32.CreateFontW(-17, 0, 0, 0, 400, 0, 0, 0, 134, 0, 0, 0, 0, 'Microsoft YaHei UI')
            self._control('STATIC', 'Real-time AI Video Companion', 0, 28, 20, 620, 34)
            self._control('STATIC', '两种模式：YouTube + Chrome 插件，或「跨境直播」采本机音频 → 桌面悬浮中文字幕。', 0, 28, 58, 620, 25)
            self.status = self._control('STATIC', '', 0, 28, 100, 620, 28)
            self.detail = self._control('STATIC', '', 0, 28, 132, 620, 44)
            self.key_status = self._control('STATIC', '', 0, 28, 180, 620, 25)
            for item, label, x, width in ((ID_START, '启动服务', 28, 100), (ID_STOP, '停止服务', 138, 100),
                                          (ID_RESTART, '重新启动', 248, 100), (ID_AUTOSTART, '开机启动：关闭', 358, 117),
                                          (ID_CONFIGURE, '配置 API Key', 485, 145)):
                self.buttons[item] = self._control('BUTTON', label, WS_TABSTOP, x, 218, width, 34, item)
            self.buttons[ID_HEALTH] = self._control('BUTTON', '打开健康检查', WS_TABSTOP, 28, 267, 140, 32, ID_HEALTH)
            self.buttons[ID_EXTENSION] = self._control('BUTTON', '安装 / 更新 Chrome 插件', WS_TABSTOP, 178, 267, 190, 32, ID_EXTENSION)
            self.buttons[ID_LIVE] = self._control('BUTTON', '▶ 开启跨境直播模式', WS_TABSTOP, 378, 267, 250, 32, ID_LIVE)
            self.buttons[ID_LIVE_MIC] = self._control(
                'BUTTON', '麦克风', WS_TABSTOP | BS_AUTOCHECKBOX, 28, 305, 96, 26, ID_LIVE_MIC,
            )
            self.buttons[ID_LIVE_SYSTEM] = self._control(
                'BUTTON', '系统声音', WS_TABSTOP | BS_AUTOCHECKBOX, 132, 305, 110, 26, ID_LIVE_SYSTEM,
            )
            self.buttons[ID_LIVE_OVERLAY] = self._control(
                'BUTTON', '桌面字幕浮层', WS_TABSTOP | BS_AUTOCHECKBOX, 250, 305, 150, 26, ID_LIVE_OVERLAY,
            )
            self.level_label = self._control('STATIC', '输入电平：—', 0, 410, 305, 250, 26)
            user32.SendMessageW(self.buttons[ID_LIVE_MIC], BM_SETCHECK, int(hub.config.source_microphone), 0)
            user32.SendMessageW(self.buttons[ID_LIVE_SYSTEM], BM_SETCHECK, int(hub.config.source_system), 0)
            user32.SendMessageW(self.buttons[ID_LIVE_OVERLAY], BM_SETCHECK, 1, 0)
            overlay = getattr(self, 'overlay', None)
            if overlay is not None:
                overlay.create()
            self._control('STATIC', '运行记录', 0, 28, 340, 620, 25)
            self.log = self._control('EDIT', '', WS_BORDER | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
                                     28, 365, 602, 170)
            return 0
        if msg == WM_TIMER:
            self._drain_events()
            return 0
        if msg == WM_COMMAND:
            item = _command_id(wp)
            actions = {ID_START: self.controller.start, ID_STOP: self.controller.stop, ID_RESTART: self.controller.restart}
            if item in actions:
                self._run_task(actions[item])
            elif item == ID_CONFIGURE:
                self._configure_key()
            elif item == ID_HEALTH:
                if probe_backend().status == BackendProbeStatus.PROJECT_RUNNING:
                    webbrowser.open(f'http://127.0.0.1:{BACKEND_PORT}/api/health')
                else:
                    message_box(hwnd, '服务尚未就绪', '请先启动本地服务。', MB_ICONWARNING)
            elif item == ID_AUTOSTART:
                self._toggle_autostart()
            elif item == ID_EXTENSION:
                guide = self.runtime_dir / 'INSTALL_CHROME_EXTENSION.html'
                if guide.exists():
                    webbrowser.open(guide.as_uri())
                else:
                    message_box(hwnd, '未找到安装引导', f'请在 Chrome 中加载：\n{self.runtime_dir / "extension" / "dist"}', MB_ICONWARNING)
            elif item == ID_LIVE:
                self._toggle_live()
            elif item in (ID_LIVE_MIC, ID_LIVE_SYSTEM, ID_LIVE_OVERLAY):
                self._toggle_source(item)
            return 0
        if msg == WM_CLOSE:
            if self.controller.state in {ServerState.STARTING, ServerState.READY, ServerState.STOPPING}:
                if message_box(hwnd, '关闭本地服务？', '关闭后 Chrome 插件与直播字幕都会停止。确定退出吗？', MB_YESNO | MB_ICONWARNING) != IDYES:
                    return 0
            overlay = getattr(self, 'overlay', None)
            if overlay is not None:
                overlay.destroy()
            self.controller.stop()
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def run(self) -> None:
        print('launcher: creating main window', flush=True)
        self.hwnd = user32.CreateWindowExW(0, 'VideoCompanionLauncher', 'Real-time AI Video Companion',
                                           WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 690, 600,
                                           None, None, kernel32.GetModuleHandleW(None), None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        print('launcher: main window created', flush=True)
        user32.ShowWindow(self.hwnd, SW_SHOWMINIMIZED if self.start_minimized else SW_SHOW)
        user32.SetTimer(self.hwnd, 1, 200, None)
        self._apply_state(ServerState.STOPPED, '')
        threading.Timer(0.4, self._initial_action).start()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _initial_action(self) -> None:
        if self.store.is_configured():
            self._run_task(self.controller.start)
        else:
            self.events.put((ServerState.STOPPED, '首次运行：请先配置千问 API Key。'))
            user32.PostMessageW(self.hwnd, WM_COMMAND, ID_CONFIGURE, 0)

    def _run_task(self, action) -> None:
        if self.busy:
            return
        self.busy = True

        def worker() -> None:
            try:
                action()
            except Exception as exc:
                self.events.put((ServerState.FAILED, f'操作失败：{type(exc).__name__}: {exc}'))
            finally:
                self.busy = False
        threading.Thread(target=worker, name='LauncherAction', daemon=True).start()

    def _drain_events(self) -> None:
        self._drain_live_events()
        overlay = getattr(self, 'overlay', None)
        if overlay is not None:
            overlay.tick()
        self._update_level_label()
        while True:
            try:
                state, text = self.events.get_nowait()
            except queue.Empty:
                break
            self._apply_state(state, text)
        ready = self.controller.state
        user32.EnableWindow(self.buttons.get(ID_START, 0), not self.busy and ready not in {ServerState.STARTING, ServerState.READY})
        user32.EnableWindow(self.buttons.get(ID_STOP, 0), not self.busy and ready not in {ServerState.STOPPED, ServerState.STOPPING})
        manager = getattr(self, 'startup_manager', None)
        if manager and self.buttons.get(ID_AUTOSTART):
            label = '开机启动：开启' if manager.is_enabled() else '开机启动：关闭'
            user32.SetWindowTextW(self.buttons[ID_AUTOSTART], label)
        # A click that arrived while the service was still starting used to be
        # dropped silently ("no reaction at all").  Replay it once the backend
        # action has finished.
        if not self.busy and self.live_queued and not self.live_pending:
            self.live_queued = False
            self._toggle_live()

    def _update_level_label(self) -> None:
        """Live input meters - the fastest way to see whether audio is captured."""
        if not getattr(self, 'level_label', 0):
            return
        levels = hub.metrics.get('levels') or {}

        def bar(value: object) -> str:
            try:
                filled = max(0, min(5, int(float(value or 0) * 25)))
            except (TypeError, ValueError):
                filled = 0
            return '▮' * filled + '▯' * (5 - filled)

        user32.SetWindowTextW(
            self.level_label,
            f'输入电平  麦:{bar(levels.get("microphone"))}  系:{bar(levels.get("system"))}',
        )

    def _toggle_source(self, item: int) -> None:
        checked = user32.SendMessageW(self.buttons[item], BM_GETCHECK, 0, 0) == 1
        if item == ID_LIVE_OVERLAY:
            if checked:
                self.overlay.show()
                note = '桌面字幕浮层已显示：可拖动，右键切换极简 / OBS 色键黑底。'
            else:
                self.overlay.hide()
                note = '桌面字幕浮层已隐藏。'
            self.events.put((self.controller.state, note))
            return
        key = 'source_microphone' if item == ID_LIVE_MIC else 'source_system'
        setattr(hub.config, key, checked)
        note = (f'音源已设为：麦克风={hub.config.source_microphone}，'
                f'系统声音={hub.config.source_system}')
        if hub.mode != 'idle':
            note += '；正在直播，停止后重新开启才会生效。'
        self.events.put((self.controller.state, note))

    def _live_request(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            LIVE_API + path,
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode('utf-8'))

    def _toggle_live(self) -> None:
        # Give immediate visual feedback: the old code silently ignored clicks
        # while another action (usually the initial service start) was running.
        if self.live_pending:
            return
        if self.busy:
            self.live_queued = True
            user32.SetWindowTextW(self.buttons[ID_LIVE], '⏳ 等待服务就绪…')
            self.events.put((self.controller.state, '已收到开启跨境直播的请求，服务就绪后会自动继续。'))
            return
        self.live_pending = True
        user32.EnableWindow(self.buttons[ID_LIVE], False)
        user32.SetWindowTextW(
            self.buttons[ID_LIVE],
            '⏳ 正在停止…' if self.live_running else '⏳ 正在启动跨境直播…',
        )
        self.events.put((self.controller.state, '正在准备跨境直播：本机音频采集 → 英文识别 → 中文字幕。'))
        self._run_task(self._live_toggle_worker)

    def _live_toggle_worker(self) -> None:
        """Start/stop live mode over the local REST API, off the UI thread."""
        try:
            if self.controller.state != ServerState.READY:
                self.controller.start()
            if self.controller.state != ServerState.READY:
                self.live_events.put(('failed', '本地服务未就绪，请先点击「启动服务」。'))
                return
            if self.live_running:
                self._live_request('/stop', {})
                self.live_events.put(('stopped', '跨境直播模式已停止。'))
            else:
                self._live_request('/start', {'mock': False})
                self.live_events.put(('started', ''))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'ignore')
            try:
                detail = str(json.loads(detail).get('detail', detail))
            except (ValueError, AttributeError):
                pass
            self.live_events.put(('demo_prompt', detail))
        except Exception as exc:
            self.live_events.put(('failed', f'{type(exc).__name__}: {exc}'))

    def _start_demo_worker(self) -> None:
        try:
            self._live_request('/start', {'mock': True})
            self.live_events.put(('started', 'demo'))
        except Exception as exc:
            self.live_events.put(('failed', f'{type(exc).__name__}: {exc}'))

    def _drain_live_events(self) -> None:
        """Apply live-mode results on the UI thread (message boxes must be here)."""
        while True:
            try:
                kind, text = self.live_events.get_nowait()
            except queue.Empty:
                break
            # Restore the control BEFORE any modal message box, otherwise the
            # button stays stuck on "正在启动…" while the dialog is open.
            self.live_pending = False
            user32.EnableWindow(self.buttons[ID_LIVE], True)
            user32.SetWindowTextW(
                self.buttons[ID_LIVE],
                '■ 停止跨境直播模式' if self.live_running else '▶ 开启跨境直播模式',
            )
            if kind == 'started':
                self.live_running = True
                user32.SetWindowTextW(self.buttons[ID_LIVE], '■ 停止跨境直播模式')
                if text == 'demo':
                    detail = '演示模式已启动（不调用千问 API），桌面字幕浮层可直接看到示例字幕。'
                else:
                    detail = ('跨境直播已启动：本机麦克风 / 系统声音 → 英文识别 → 中文桌面悬浮字幕。'
                              '浮层可拖动；OBS 用「显示器采集」捕获，或右键切到色键黑底。')
                self.events.put((ServerState.READY, detail))
                if (self.buttons.get(ID_LIVE_OVERLAY)
                        and user32.SendMessageW(self.buttons[ID_LIVE_OVERLAY], BM_GETCHECK, 0, 0) == 1):
                    overlay = getattr(self, 'overlay', None)
                    if overlay is not None:
                        overlay.show()
            elif kind == 'stopped':
                self.live_running = False
                overlay = getattr(self, 'overlay', None)
                if overlay is not None:
                    overlay.hide()
                user32.SetWindowTextW(self.buttons[ID_LIVE], '▶ 开启跨境直播模式')
                self.events.put((ServerState.READY, text))
            elif kind == 'failed':
                message_box(self.hwnd, '跨境直播模式', text, MB_ICONWARNING)
            elif kind == 'demo_prompt':
                answer = message_box(
                    self.hwnd,
                    '真实音频采集未启动',
                    f'{text}\n\n是否改用「演示模式」？它不调用千问 API，可验证 OBS 叠层与控制台链路。',
                    MB_YESNO | MB_ICONWARNING,
                )
                if answer == IDYES:
                    # Direct thread: _run_task's busy flag may not be cleared yet.
                    threading.Thread(target=self._start_demo_worker, daemon=True).start()

    def _toggle_autostart(self) -> None:
        if not self.startup_manager:
            message_box(self.hwnd, '暂不可用', '源码运行模式下无法设置开机启动。', MB_ICONWARNING)
            return
        try:
            enabled = self.startup_manager.toggle()
            message_box(
                self.hwnd,
                '开机启动已更新',
                '已开启。下次登录 Windows 后会最小化启动。' if enabled else '已关闭。',
            )
            self._drain_events()
        except Exception as exc:
            message_box(self.hwnd, '设置失败', f'无法修改开机启动：{exc}', MB_ICONERROR)

    def _apply_state(self, state: ServerState, message: str) -> None:
        secret = self.store.read_value('DASHSCOPE_API_KEY')
        view = self.view_model.present(state, message, secrets=[secret])
        user32.SetWindowTextW(self.status, view.title)
        user32.SetWindowTextW(self.detail, view.detail)
        user32.SetWindowTextW(self.key_status, f'API Key：{self.store.masked_api_key()}')
        end = user32.GetWindowTextLengthW(self.log)
        user32.SendMessageW(self.log, EM_SETSEL, end, end)
        line = ctypes.create_unicode_buffer(f'{view.title}：{view.detail}\r\n')
        user32.SendMessageW(self.log, EM_REPLACESEL, False, ctypes.addressof(line))

    def _configure_key(self) -> None:
        value = ApiKeyPrompt(self.hwnd).show()
        if value is None:
            return

        def validate_save_and_restart() -> None:
            self.events.put((ServerState.STARTING, '正在验证 API Key，请稍候…'))
            validate_api_key_sync(value)
            self.store.save_api_key(value)
            get_settings.cache_clear()
            self.events.put((ServerState.STOPPED, 'API Key 验证成功，已保存到本机配置。'))
            self.controller.restart()

        self._run_task(validate_save_and_restart)
