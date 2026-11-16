import ctypes
from ctypes import wintypes
from pathlib import Path
from uuid import UUID


CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
RPC_E_CHANGED_MODE = -2147417850


class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> GUID:
    raw = UUID(value).bytes_le
    return GUID.from_buffer_copy(raw)


CLSID_SHELL_LINK = _guid('00021401-0000-0000-C000-000000000046')
IID_ISHELL_LINK_W = _guid('000214F9-0000-0000-C000-000000000046')
IID_IPERSIST_FILE = _guid('0000010B-0000-0000-C000-000000000046')


def _method(instance: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _check_hresult(result: int, action: str) -> None:
    if result < 0:
        raise OSError(f'{action}失败，Windows 错误代码：0x{result & 0xFFFFFFFF:08X}')


def create_shortcut(
    shortcut_path: Path,
    target_path: Path,
    *,
    arguments: str = '',
    working_directory: Path | None = None,
    description: str = 'Real-time AI Video Companion',
    icon_path: Path | None = None,
) -> None:
    """Create a Windows .lnk without PowerShell, scripts, or extra packages."""
    shortcut_path = shortcut_path.resolve()
    target_path = target_path.resolve()
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    initialized = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if initialized < 0 and initialized != RPC_E_CHANGED_MODE:
        _check_hresult(initialized, '初始化快捷方式组件')

    shell_link = ctypes.c_void_p()
    persist_file = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
        ]
        ole32.CoCreateInstance.restype = ctypes.c_long
        _check_hresult(
            ole32.CoCreateInstance(
                ctypes.byref(CLSID_SHELL_LINK), None, CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_ISHELL_LINK_W), ctypes.byref(shell_link),
            ),
            '创建快捷方式',
        )
        _check_hresult(_method(shell_link, 20, ctypes.c_long, wintypes.LPCWSTR)(shell_link, str(target_path)), '设置程序路径')
        if arguments:
            _check_hresult(_method(shell_link, 11, ctypes.c_long, wintypes.LPCWSTR)(shell_link, arguments), '设置启动参数')
        working = (working_directory or target_path.parent).resolve()
        _check_hresult(_method(shell_link, 9, ctypes.c_long, wintypes.LPCWSTR)(shell_link, str(working)), '设置工作目录')
        _check_hresult(_method(shell_link, 7, ctypes.c_long, wintypes.LPCWSTR)(shell_link, description), '设置快捷方式说明')
        icon = (icon_path or target_path).resolve()
        _check_hresult(_method(shell_link, 17, ctypes.c_long, wintypes.LPCWSTR, ctypes.c_int)(shell_link, str(icon), 0), '设置图标')

        _check_hresult(
            _method(shell_link, 0, ctypes.c_long, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                shell_link, ctypes.byref(IID_IPERSIST_FILE), ctypes.byref(persist_file),
            ),
            '保存快捷方式',
        )
        _check_hresult(
            _method(persist_file, 6, ctypes.c_long, wintypes.LPCWSTR, wintypes.BOOL)(
                persist_file, str(shortcut_path), True,
            ),
            '写入快捷方式文件',
        )
    finally:
        if persist_file:
            _method(persist_file, 2, ctypes.c_ulong)(persist_file)
        if shell_link:
            _method(shell_link, 2, ctypes.c_ulong)(shell_link)
        if initialized >= 0:
            ole32.CoUninitialize()


def remove_shortcut(shortcut_path: Path) -> None:
    shortcut_path.unlink(missing_ok=True)
