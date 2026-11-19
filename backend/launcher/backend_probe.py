import os
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx


class BackendProbeStatus(str, Enum):
    FREE = 'free'
    PROJECT_RUNNING = 'project_running'
    PORT_OCCUPIED = 'port_occupied'


PROJECT_ASR_PROVIDERS = frozenset({'qwen-realtime', 'qwen-streaming'})


@dataclass(frozen=True)
class BackendProbe:
    status: BackendProbeStatus
    health: dict[str, Any] | None = None
    detail: str = ''


def classify_health_payload(payload: object) -> BackendProbeStatus:
    if not isinstance(payload, dict):
        return BackendProbeStatus.PORT_OCCUPIED
    if (
        payload.get('ok') is True
        and payload.get('asr_provider') in PROJECT_ASR_PROVIDERS
        and payload.get('translation_provider') == 'qwen'
    ):
        return BackendProbeStatus.PROJECT_RUNNING
    return BackendProbeStatus.PORT_OCCUPIED


def probe_backend(
    host: str = '127.0.0.1',
    port: int | None = None,
    timeout: float = 0.5,
) -> BackendProbe:
    port = port if port is not None else int(os.environ.get('VIDEO_COMPANION_PORT', '8000'))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return BackendProbe(BackendProbeStatus.FREE)

    try:
        response = httpx.get(f'http://{host}:{port}/api/health', timeout=timeout)
        payload = response.json()
    except Exception as exc:
        return BackendProbe(
            BackendProbeStatus.PORT_OCCUPIED,
            detail=f'端口可以连接，但不是可识别的本项目后端：{type(exc).__name__}',
        )

    status = classify_health_payload(payload)
    health = payload if isinstance(payload, dict) else None
    return BackendProbe(status, health=health)
