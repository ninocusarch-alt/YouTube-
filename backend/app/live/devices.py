"""Windows WASAPI device discovery and capture.

Two audio sources matter for cross-border streaming:

* ``microphone``  - the streamer's own English speech (primary source here)
* ``system``      - WASAPI loopback: game sound / Discord teammates (optional)

M0 uses a normal loopback device (or a virtual cable such as VB-Cable /
VoiceMeeter). Per-process loopback can be added later without changing this
interface. On non-Windows or when PyAudioWPatch is missing, discovery returns
``available=False`` and the caller falls back to demo mode.
"""
from __future__ import annotations

import platform
import threading
from typing import Any, Iterator


# PortAudio does not reference-count Pa_Initialize / Pa_Terminate in a
# thread-safe way.  A single launcher click used to start the backend and then
# immediately open a capture stream, so device discovery (uvicorn thread) and
# capture (worker thread) initialised / terminated separate PyAudio handles at
# the same time.  On the frozen EXE that corrupted the native heap
# (0xc0000374, ntdll.dll) and killed the whole window without any traceback.
# Share ONE process-wide handle and never terminate it while the app is alive.
_AUDIO_LOCK = threading.RLock()
_PYAUDIO: Any = None
_MANAGER: Any = None


def _manager():
    global _PYAUDIO, _MANAGER
    with _AUDIO_LOCK:
        if _MANAGER is None:
            import pyaudiowpatch as pyaudio  # noqa: PLC0415 - optional Windows dependency

            _PYAUDIO = pyaudio
            _MANAGER = pyaudio.PyAudio()
        return _PYAUDIO, _MANAGER


def list_devices() -> dict[str, Any]:
    result: dict[str, Any] = {
        'platform': platform.system(),
        'available': False,
        'backend': 'none',
        'microphones': [],
        'loopbacks': [],
        'hint': '',
    }
    if platform.system() != 'Windows':
        result['hint'] = '当前不是 Windows，无法使用 WASAPI 采集；可改用演示模式验证界面链路。'
        return result
    try:
        import pyaudiowpatch  # noqa: F401, PLC0415
    except ImportError:
        result['hint'] = '未安装 PyAudioWPatch，执行 pip install PyAudioWPatch 后即可采集本机音频。'
        return result

    try:
        pyaudio, manager = _manager()
        with _AUDIO_LOCK:
            loopbacks = []
            for info in manager.get_loopback_device_info_generator():
                loopbacks.append({
                    'index': int(info['index']),
                    'name': str(info.get('name', '')),
                    'sample_rate': int(float(info.get('defaultSampleRate', 48000))),
                    'channels': int(info.get('maxInputChannels', 2) or 2),
                })
            microphones = []
            for index in range(manager.get_device_count()):
                info = manager.get_device_info_by_index(index)
                if int(info.get('maxInputChannels', 0) or 0) < 1:
                    continue
                if any(int(item['index']) == index for item in loopbacks):
                    continue
                if 'loopback' in str(info.get('name', '')).lower():
                    continue
                microphones.append({
                    'index': index,
                    'name': str(info.get('name', '')),
                    'sample_rate': int(float(info.get('defaultSampleRate', 48000))),
                    'channels': min(2, int(info.get('maxInputChannels', 1) or 1)),
                })
            default_loopback = None
            try:
                default = manager.get_default_wasapi_loopback()
                default_loopback = int(default['index']) if default else None
            except Exception:
                pass
            default_mic = None
            try:
                default = manager.get_default_input_device_info()
                default_mic = int(default['index']) if default else None
            except Exception:
                pass
            result.update({
                'available': True,
                'backend': 'pyaudiowpatch',
                'microphones': microphones,
                'loopbacks': loopbacks,
                'default_microphone': default_mic,
                'default_loopback': default_loopback,
                'hint': '建议麦克风只收主播英语；系统声音若开启，避免把中文解说或浏览器声音一起送进识别。',
            })
    except Exception as exc:  # pragma: no cover - depends on local audio stack
        result['hint'] = f'设备枚举失败：{type(exc).__name__}: {exc}'
    return result


def device_info(device_index: int) -> dict[str, Any]:
    _pyaudio, manager = _manager()
    with _AUDIO_LOCK:
        info = manager.get_device_info_by_index(int(device_index))
    return {
        'index': int(info['index']),
        'name': str(info.get('name', '')),
        'sample_rate': int(float(info.get('defaultSampleRate', 48000))),
        'channels': max(1, min(2, int(info.get('maxInputChannels', 2) or 2))),
    }


def capture_frames(
    device_index: int,
    *,
    rate: int | None = None,
    channels: int | None = None,
    frames_per_buffer: int = 960,
) -> Iterator[tuple[bytes, int, int]]:
    """Yield ``(raw_pcm, sample_rate, channels)`` until the consumer stops."""
    pyaudio, manager = _manager()
    with _AUDIO_LOCK:
        info = manager.get_device_info_by_index(int(device_index))
        actual_rate = int(rate or float(info.get('defaultSampleRate', 48000)) or 48000)
        actual_channels = int(channels or min(2, max(1, int(info.get('maxInputChannels', 2) or 2))))
        stream = manager.open(
            format=pyaudio.paInt16,
            channels=actual_channels,
            rate=actual_rate,
            input=True,
            input_device_index=int(device_index),
            frames_per_buffer=frames_per_buffer,
        )
    try:
        while True:
            yield stream.read(frames_per_buffer, exception_on_overflow=False), actual_rate, actual_channels
    finally:
        # Only release this stream.  The shared manager belongs to the process,
        # terminating it here is what used to corrupt PortAudio's heap.
        with _AUDIO_LOCK:
            try:
                stream.stop_stream()
            finally:
                stream.close()
