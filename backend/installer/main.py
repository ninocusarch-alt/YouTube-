import ctypes
import os
import shutil
import subprocess
import sys
import urllib.request
import webbrowser
import winreg
from ctypes import wintypes
from pathlib import Path

from installer.install_engine import install_payload
from launcher.startup_manager import StartupManager
from launcher.windows_shortcut import create_shortcut, remove_shortcut


PRODUCT_NAME = 'Real-time AI Video Companion'
PRODUCT_VERSION = '0.4.0'
INSTALL_FOLDER_NAME = 'RealTimeAIVideoCompanion'
UNINSTALL_KEY = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{INSTALL_FOLDER_NAME}'
MB_OK, MB_ICONINFORMATION, MB_ICONWARNING, MB_ICONERROR = 0, 0x40, 0x30, 0x10
MB_YESNOCANCEL, MB_YESNO, IDYES, IDNO = 3, 4, 6, 7
MB_DEFBUTTON2 = 0x100
MOVEFILE_DELAY_UNTIL_REBOOT = 4
CSIDL_DESKTOPDIRECTORY, CSIDL_PROGRAMS, CSIDL_LOCAL_APPDATA = 0x10, 0x02, 0x1C


def message(title: str, body: str, flags: int = MB_OK) -> int:
    return ctypes.windll.user32.MessageBoxW(None, body, title, flags)


def system_folder(csidl: int) -> Path:
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer)
    if result != 0:
        raise OSError(f'无法读取 Windows 用户目录：0x{result & 0xFFFFFFFF:08X}')
    return Path(buffer.value)


def install_directory() -> Path:
    return system_folder(CSIDL_LOCAL_APPDATA) / 'Programs' / INSTALL_FOLDER_NAME


def payload_directory() -> Path:
    bundle_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    return bundle_root / 'payload'


def backend_is_running() -> bool:
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=1) as response:
            return b'Real-time AI Subtitle Agent API' in response.read() or response.status == 200
    except Exception:
        return False


def shortcut_paths() -> tuple[Path, Path, Path]:
    desktop = system_folder(CSIDL_DESKTOPDIRECTORY) / f'{PRODUCT_NAME}.lnk'
    menu = system_folder(CSIDL_PROGRAMS) / PRODUCT_NAME
    return desktop, menu / f'{PRODUCT_NAME}.lnk', menu / '卸载.lnk'


def register_uninstaller(target: Path) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        values = {
            'DisplayName': PRODUCT_NAME,
            'DisplayVersion': PRODUCT_VERSION,
            'Publisher': 'NinoC AI Product Lab',
            'InstallLocation': str(target),
            'DisplayIcon': str(target / 'VideoCompanionBackend.exe'),
            'UninstallString': f'"{target / "Uninstall.exe"}" --uninstall',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)


def unregister_uninstaller() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass


def create_product_shortcuts(target: Path, enable_autostart: bool) -> None:
    executable = target / 'VideoCompanionBackend.exe'
    desktop, start_menu, uninstall = shortcut_paths()
    create_shortcut(desktop, executable, description=PRODUCT_NAME)
    create_shortcut(start_menu, executable, description=PRODUCT_NAME)
    create_shortcut(uninstall, target / 'Uninstall.exe', arguments='--uninstall', description=f'卸载 {PRODUCT_NAME}')
    startup = StartupManager(executable)
    if enable_autostart:
        startup.enable()
    else:
        startup.disable()


def remove_product_shortcuts(target: Path) -> None:
    desktop, start_menu, uninstall = shortcut_paths()
    for shortcut in (desktop, start_menu, uninstall):
        remove_shortcut(shortcut)
    menu = start_menu.parent
    if menu.exists() and not any(menu.iterdir()):
        menu.rmdir()
    StartupManager(target / 'VideoCompanionBackend.exe').disable()


def run_install() -> int:
    choice = message(
        '安装 Real-time AI Video Companion',
        '程序将安装到当前 Windows 用户，不需要管理员权限。\n\n'
        '“是”：安装并开启开机自动启动\n'
        '“否”：安装但不开启开机自动启动\n'
        '“取消”：退出安装',
        MB_YESNOCANCEL | MB_ICONINFORMATION | MB_DEFBUTTON2,
    )
    if choice not in {IDYES, IDNO}:
        return 0
    if backend_is_running():
        message('请先关闭程序', '检测到本地服务正在运行。请先关闭 Video Companion 窗口，再重新运行安装器。', MB_ICONWARNING)
        return 2

    target = install_directory()
    try:
        install_payload(payload_directory(), target)
        shutil.copy2(Path(sys.executable), target / 'Uninstall.exe')
        create_product_shortcuts(target, enable_autostart=choice == IDYES)
        register_uninstaller(target)
        subprocess.Popen([str(target / 'VideoCompanionBackend.exe')], cwd=target)
        guide = target / 'INSTALL_CHROME_EXTENSION.html'
        if guide.exists():
            webbrowser.open(guide.as_uri())
        message(
            '安装完成',
            '主程序已经启动。\n\n请按浏览器中的引导加载 Chrome 插件；以后可从桌面或开始菜单直接启动。',
            MB_ICONINFORMATION,
        )
        return 0
    except Exception as exc:
        message('安装失败', f'安装没有完成：{type(exc).__name__}: {exc}', MB_ICONERROR)
        return 1


def run_uninstall() -> int:
    if backend_is_running():
        message('请先关闭程序', '请先关闭 Video Companion 主窗口，再重新点击卸载。', MB_ICONWARNING)
        return 2
    if message(
        '卸载 Real-time AI Video Companion',
        '这会删除程序、本机 API Key 和历史记录。确定继续吗？',
        MB_YESNO | MB_ICONWARNING,
    ) != IDYES:
        return 0
    target = Path(sys.executable).resolve().parent
    try:
        remove_product_shortcuts(target)
        unregister_uninstaller()
        for child in target.iterdir():
            if child.resolve() == Path(sys.executable).resolve():
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        ctypes.windll.kernel32.MoveFileExW(str(Path(sys.executable).resolve()), None, MOVEFILE_DELAY_UNTIL_REBOOT)
        ctypes.windll.kernel32.MoveFileExW(str(target), None, MOVEFILE_DELAY_UNTIL_REBOOT)
        message('卸载完成', '程序已卸载。卸载器自身会在下次 Windows 重启时清理。', MB_ICONINFORMATION)
        return 0
    except Exception as exc:
        message('卸载失败', f'卸载没有完成：{type(exc).__name__}: {exc}', MB_ICONERROR)
        return 1


def run_self_test() -> int:
    payload = payload_directory()
    required = [
        payload / 'VideoCompanionBackend.exe',
        payload / '.env.example',
        payload / 'extension' / 'dist' / 'manifest.json',
        payload / 'INSTALL_CHROME_EXTENSION.html',
    ]
    return 0 if all(path.exists() for path in required) and not (payload / '.env').exists() else 1


def main() -> int:
    if '--self-test' in sys.argv:
        return run_self_test()
    if '--uninstall' in sys.argv:
        return run_uninstall()
    return run_install()


if __name__ == '__main__':
    raise SystemExit(main())
