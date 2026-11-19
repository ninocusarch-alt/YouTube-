import os
import threading
import time
from enum import Enum
from typing import Callable, Protocol

import uvicorn

from launcher.backend_probe import BackendProbe, BackendProbeStatus, probe_backend
from launcher.config_store import ConfigStore
from launcher.runtime_paths import ENV_FILE_VARIABLE


class ServerState(str, Enum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    READY = 'ready'
    STOPPING = 'stopping'
    FAILED = 'failed'


class ManagedServer(Protocol):
    should_exit: bool

    def run(self) -> None: ...


def create_uvicorn_server() -> ManagedServer:
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    config = uvicorn.Config(
        app=app,
        host='127.0.0.1',
        port=int(os.environ.get('VIDEO_COMPANION_PORT', '8000')),
        log_level='info',
        log_config=None,
        access_log=False,
    )
    return uvicorn.Server(config)


class ServerController:
    def __init__(
        self,
        config_store: ConfigStore,
        server_factory: Callable[[], ManagedServer] = create_uvicorn_server,
        probe: Callable[[], BackendProbe] = probe_backend,
        ready_timeout: float = 10.0,
        poll_interval: float = 0.1,
        state_listener: Callable[[ServerState, str], None] | None = None,
    ) -> None:
        self.config_store = config_store
        self.server_factory = server_factory
        self.probe = probe
        self.port = int(os.environ.get('VIDEO_COMPANION_PORT', '8000'))
        self.ready_timeout = ready_timeout
        self.poll_interval = poll_interval
        self.state_listener = state_listener
        self.state = ServerState.STOPPED
        self.last_error = ''
        self._server: ManagedServer | None = None
        self._thread: threading.Thread | None = None
        self._owns_server = False
        self._lock = threading.RLock()

    def _set_state(self, state: ServerState, message: str = '') -> None:
        self.state = state
        if state == ServerState.FAILED:
            self.last_error = message
        elif state != ServerState.FAILED:
            self.last_error = ''
        if self.state_listener:
            self.state_listener(state, message)

    def start(self) -> bool:
        with self._lock:
            if self.state in {ServerState.STARTING, ServerState.READY, ServerState.STOPPING}:
                return self.state == ServerState.READY

            current = self.probe()
            if current.status == BackendProbeStatus.PROJECT_RUNNING:
                self._owns_server = False
                self._set_state(ServerState.READY, '本地服务已经运行。')
                return True
            if current.status == BackendProbeStatus.PORT_OCCUPIED:
                self._set_state(ServerState.FAILED, f'{self.port} 端口被其他程序占用，请关闭占用程序后重试。')
                return False

            self.config_store.ensure_exists()
            if not self.config_store.is_configured():
                self._set_state(ServerState.FAILED, '尚未配置千问 API Key。')
                return False

            os.environ[ENV_FILE_VARIABLE] = str(self.config_store.env_file)
            self._set_state(ServerState.STARTING, '正在启动本地服务…')
            self._server = self.server_factory()
            self._owns_server = True
            self._thread = threading.Thread(
                target=self._run_server,
                name='VideoCompanionUvicorn',
                daemon=True,
            )
            self._thread.start()

        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if self._thread and not self._thread.is_alive():
                if self.state != ServerState.FAILED:
                    self._set_state(ServerState.FAILED, '本地服务启动后意外退出。')
                return False
            if self.probe().status == BackendProbeStatus.PROJECT_RUNNING:
                self._set_state(ServerState.READY, '服务已就绪，可以打开 YouTube 插件。')
                return True
            time.sleep(self.poll_interval)

        self._set_state(ServerState.FAILED, '本地服务启动超时。')
        self._stop_owned_server()
        return False

    def _run_server(self) -> None:
        try:
            if self._server:
                self._server.run()
        except Exception as exc:
            self._set_state(ServerState.FAILED, f'本地服务启动失败：{type(exc).__name__}: {exc}')
        finally:
            if self.state not in {ServerState.STOPPING, ServerState.STOPPED, ServerState.FAILED}:
                self._set_state(ServerState.FAILED, '本地服务意外停止。')

    def stop(self) -> bool:
        with self._lock:
            if self.state == ServerState.STOPPED:
                return True
            if not self._owns_server:
                self._set_state(ServerState.STOPPED, '启动器没有停止外部服务。')
                return True
            self._set_state(ServerState.STOPPING, '正在停止本地服务…')
        return self._stop_owned_server()

    def _stop_owned_server(self) -> bool:
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and self._thread.is_alive():
            self._set_state(ServerState.FAILED, '本地服务未能正常停止。')
            return False
        self._server = None
        self._thread = None
        self._owns_server = False
        self._set_state(ServerState.STOPPED, '本地服务已停止。')
        return True

    def restart(self) -> bool:
        if not self.stop():
            return False
        from app.config import get_settings

        get_settings.cache_clear()
        return self.start()
