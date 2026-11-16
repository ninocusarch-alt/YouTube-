from dataclasses import dataclass
from typing import Iterable

from launcher.server_controller import ServerState


@dataclass(frozen=True)
class StatusView:
    title: str
    detail: str
    color: str


class LauncherViewModel:
    _defaults = {
        ServerState.STOPPED: StatusView('服务未启动', '点击“启动服务”后即可使用插件。', '#94a3b8'),
        ServerState.STARTING: StatusView('正在启动', '正在准备本地 AI 服务，请稍候…', '#f59e0b'),
        ServerState.READY: StatusView('服务已就绪', '现在可以打开 YouTube 并点击插件。', '#22c55e'),
        ServerState.STOPPING: StatusView('正在停止', '正在安全关闭本地服务…', '#f59e0b'),
        ServerState.FAILED: StatusView('出现问题', '本地服务未能启动，请查看下方提示。', '#ef4444'),
    }

    def present(
        self,
        state: ServerState,
        message: str,
        *,
        secrets: Iterable[str] = (),
    ) -> StatusView:
        base = self._defaults[state]
        detail = message.strip() or base.detail
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, '****')
        return StatusView(base.title, detail, base.color)
