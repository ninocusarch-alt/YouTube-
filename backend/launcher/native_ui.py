import ctypes
import queue
import threading
import webbrowser
from ctypes import wintypes
from pathlib import Path

from app.config import get_settings
from launcher.backend_probe import BackendProbeStatus, probe_backend
from launcher.config_store import ConfigStore, MAX_API_KEY_LENGTH
from launcher.key_validator import validate_api_key_sync
from launcher.server_controller import ServerController, ServerState
from launcher.startup_manager import StartupManager
from launcher.view_model import LauncherViewModel


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_CREATE, WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER = 1, 2, 0x10, 0x111, 0x113
WM_SETFONT, EM_SETSEL, EM_REPLACESEL, EM_SETLIMITTEXT = 0x30, 0xB1, 0xC2, 0xC5
WS_CHILD, WS_VISIBLE, WS_BORDER, WS_TABSTOP = 0x40000000, 0x10000000, 0x00800000, 0x00010000
WS_OVERLAPPEDWINDOW = 0x00CF0000
ES_PASSWORD, ES_MULTILINE, ES_AUTOVSCROLL, ES_AUTOHSCROLL, ES_READONLY = 0x20, 4, 0x40, 0x80, 0x800
SW_SHOW, SW_SHOWMINIMIZED, CW_USEDEFAULT, COLOR_WINDOW, IDC_ARROW = 5, 2, -2147483648, 5, 32512
MB_OK, MB_ICONWARNING, MB_ICONERROR, MB_YESNO, IDYES = 0, 0x30, 0x10, 4, 6
ID_START, ID_STOP, ID_RESTART, ID_CONFIGURE, ID_HEALTH, ID_AUTOSTART, ID_EXTENSION = 101, 102, 103, 104, 105, 106, 107
ID_KEY_SAVE, ID_KEY_CANCEL, ID_KEY_EDIT = 201, 202, 203
EN_CHANGE = 0x0300


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HICON),
    ]


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
        self.busy = False
        self.hwnd = self.status = self.detail = self.key_status = self.log = 0
        self.buttons: dict[int, int] = {}
        self.font = 0
        self.callback = WNDPROC(self._proc)
        self.controller = ServerController(store, state_listener=lambda state, text: self.events.put((state, text)))
        self.startup_manager = startup_manager
        self.start_minimized = start_minimized
        self.runtime_dir = (runtime_dir or store.env_file.parent).resolve()
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
            self._control('STATIC', '双击启动一次，之后直接打开 YouTube 插件使用。', 0, 28, 58, 620, 25)
            self.status = self._control('STATIC', '', 0, 28, 100, 620, 28)
            self.detail = self._control('STATIC', '', 0, 28, 132, 620, 44)
            self.key_status = self._control('STATIC', '', 0, 28, 180, 620, 25)
            for item, label, x, width in ((ID_START, '启动服务', 28, 100), (ID_STOP, '停止服务', 138, 100),
                                          (ID_RESTART, '重新启动', 248, 100), (ID_AUTOSTART, '开机启动：关闭', 358, 117),
                                          (ID_CONFIGURE, '配置 API Key', 485, 145)):
                self.buttons[item] = self._control('BUTTON', label, WS_TABSTOP, x, 218, width, 34, item)
            self.buttons[ID_HEALTH] = self._control('BUTTON', '打开健康检查', WS_TABSTOP, 28, 267, 140, 32, ID_HEALTH)
            self.buttons[ID_EXTENSION] = self._control('BUTTON', '安装 / 更新 Chrome 插件', WS_TABSTOP, 178, 267, 190, 32, ID_EXTENSION)
            self._control('STATIC', '运行记录', 0, 28, 315, 620, 25)
            self.log = self._control('EDIT', '', WS_BORDER | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
                                     28, 343, 602, 170)
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
                    webbrowser.open('http://127.0.0.1:8000/api/health')
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
            return 0
        if msg == WM_CLOSE:
            if self.controller.state in {ServerState.STARTING, ServerState.READY, ServerState.STOPPING}:
                if message_box(hwnd, '关闭本地服务？', '关闭后 Chrome 插件将暂时无法使用。确定退出吗？', MB_YESNO | MB_ICONWARNING) != IDYES:
                    return 0
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
                                           WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 690, 580,
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
