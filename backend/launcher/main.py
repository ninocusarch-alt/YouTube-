import os
import sys

from launcher.config_store import ConfigStore
from launcher.native_ui import MB_ICONERROR, MB_OK, NativeLauncherWindow, message_box
from launcher.runtime_paths import ENV_FILE_VARIABLE, resolve_env_file, resolve_env_template, resolve_runtime_dir
from launcher.single_instance import SingleInstance
from launcher.startup_manager import current_startup_manager


def main() -> None:
    print('launcher: resolving runtime paths', flush=True)
    runtime_dir = resolve_runtime_dir()
    env_file = resolve_env_file(runtime_dir)
    os.environ[ENV_FILE_VARIABLE] = str(env_file)

    instance = SingleInstance()
    print('launcher: acquiring single-instance mutex', flush=True)
    if not instance.acquire():
        message_box(0, '程序已经运行', 'Video Companion 本地服务窗口已经打开。')
        return

    try:
        print('launcher: preparing config', flush=True)
        store = ConfigStore(env_file, resolve_env_template(runtime_dir))
        store.ensure_exists()
        print('launcher: creating native UI', flush=True)
        NativeLauncherWindow(
            store,
            startup_manager=current_startup_manager(),
            start_minimized='--minimized' in sys.argv[1:],
            runtime_dir=runtime_dir,
        ).run()
    except Exception as exc:
        message_box(0, '启动失败', f'启动器无法运行：{type(exc).__name__}: {exc}', MB_OK | MB_ICONERROR)
        raise
    finally:
        instance.release()


if __name__ == '__main__':
    main()
