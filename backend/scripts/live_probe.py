"""真实 API 连通性探针（只读、不落盘、不打印密钥）。

逐个实测「端点 x 模型」组合，用于确认用户安装目录里的 .env
（阿里云百炼 MaaS 专属实例）到底哪套配置能被当前代码用起来。

用法（在 backend/ 下）：
    .venv/Scripts/python.exe scripts/live_probe.py
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import websockets

DEFAULT_ENV_FILE = Path(
    r"C:\Users\ninoc\AppData\Local\Programs\RealTimeAIVideoCompanion\.env"
)
PUBLIC_HTTP = "https://dashscope.aliyuncs.com/compatible-mode/v1"
PUBLIC_WS = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        cleaned = value.strip().strip('"').strip("'")
        result[key.strip()] = cleaned
    return result


def scrub(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "<redacted>")
    return text.replace("\n", " ")[:260]


def build_ws_url(base: str, model: str) -> str:
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("model", model)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def probe_http(label: str, base: str, model: str, key: str) -> str:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                base.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                    "max_tokens": 12,
                    "temperature": 0,
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if response.status_code == 200:
            data = response.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()
            usage = data.get("usage") or {}
            return (
                f"OK    {elapsed_ms:7.0f} ms  reply={content[:36]!r}  "
                f"tokens={usage.get('total_tokens')}  model={data.get('model', model)}"
            )
        return (
            f"FAIL  {elapsed_ms:7.0f} ms  HTTP {response.status_code}  "
            f"{scrub(response.text, key)}"
        )
    except Exception as exc:  # noqa: BLE001 - probe must report, not crash
        elapsed_ms = (time.perf_counter() - started) * 1000
        return f"FAIL  {elapsed_ms:7.0f} ms  {type(exc).__name__}: {scrub(str(exc), key)}"


async def probe_ws(
    label: str,
    base_ws: str,
    model: str,
    key: str,
    language: str,
    sample_rate: int,
    vad_silence_ms: int,
) -> str:
    url = build_ws_url(base_ws, model)
    started = time.perf_counter()
    ws = None
    try:
        ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {key}",
                "OpenAI-Beta": "realtime=v1",
            },
            open_timeout=12,
            ping_interval=20,
            ping_timeout=20,
        )
        handshake_ms = (time.perf_counter() - started) * 1000
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "input_audio_format": "pcm",
                "sample_rate": sample_rate,
                "input_audio_transcription": {"model": model, "language": language},
                "turn_detection": {
                    "type": "server_vad",
                    "silence_duration_ms": vad_silence_ms,
                },
            },
        }))
        events: list[str] = []
        error_text = ""
        for _ in range(3):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
            except asyncio.TimeoutError:
                break
            data = json.loads(raw)
            header = data.get("header") if isinstance(data.get("header"), dict) else {}
            event_name = data.get("type") or header.get("event") or "unknown"
            events.append(str(event_name))
            if data.get("type") == "error" or header.get("event") == "task-failed":
                error_text = scrub(json.dumps(data, ensure_ascii=False), key)
                break
        total_ms = (time.perf_counter() - started) * 1000
        summary = (
            f"OK    handshake={handshake_ms:.0f} ms  total={total_ms:.0f} ms  "
            f"events={events or ['(none)']}"
        )
        if error_text:
            summary += f"  ERROR_EVENT={error_text}"
        return summary
    except Exception as exc:  # noqa: BLE001
        total_ms = (time.perf_counter() - started) * 1000
        return (
            f"FAIL  {total_ms:7.0f} ms  {type(exc).__name__}: "
            f"{scrub(str(exc), key)}"
        )
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass


async def main() -> None:
    env_path = Path(os.environ.get("LIVE_PROBE_ENV_FILE", str(DEFAULT_ENV_FILE)))
    if not env_path.exists():
        raise SystemExit(f"env file not found: {env_path}")
    env = load_env(env_path)
    key = env.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise SystemExit("DASHSCOPE_API_KEY missing")

    dedicated_http = env.get("DASHSCOPE_BASE_URL", "").rstrip("/")
    translated_model = env.get("QWEN_TRANSLATION_MODEL", "qwen-plus")
    asr_model = env.get("QWEN_ASR_MODEL", "qwen3-asr-flash-realtime")
    language = env.get("QWEN_ASR_LANGUAGE", "en")
    sample_rate = int(env.get("QWEN_ASR_SAMPLE_RATE", "16000"))
    vad_silence_ms = int(env.get("QWEN_VAD_SILENCE_MS", "400"))

    print("=== ENV (secrets redacted) ===")
    print(f"env_file           : {env_path}")
    print(f"key                : <redacted> (len={len(key)})")
    print(f"DASHSCOPE_BASE_URL : {dedicated_http or '(not set)'}")
    print(f"QWEN_TRANSLATION_MODEL : {translated_model}")
    print(f"QWEN_ASR_MODEL     : {asr_model}")
    print(f"language={language}  sample_rate={sample_rate}  vad={vad_silence_ms}ms")
    print()

    http_targets = [
        ("public    / qwen-plus", PUBLIC_HTTP, "qwen-plus"),
        ("public    / configured", PUBLIC_HTTP, translated_model),
        ("dedicated / configured", dedicated_http, translated_model),
        ("dedicated / qwen-plus", dedicated_http, "qwen-plus"),
    ]
    http_targets = [(n, b, m) for n, b, m in http_targets if b]

    print("=== HTTP chat/completions ===")
    http_results = await asyncio.gather(*(
        probe_http(name, base, model, key)
        for name, base, model in http_targets
    ))
    for (name, _, _), result in zip(http_targets, http_results):
        print(f"{name:26s} {result}")
    print()

    derived_ws = ""
    if dedicated_http:
        host = urlsplit(dedicated_http).netloc
        derived_ws = f"wss://{host}/api-ws/v1/realtime"

    ws_targets = [
        ("public    / configured", PUBLIC_WS, asr_model),
        ("public    / qwen3-asr-flash-realtime", PUBLIC_WS, "qwen3-asr-flash-realtime"),
        ("dedicated / configured", derived_ws, asr_model),
    ]
    ws_targets = [(n, b, m) for n, b, m in ws_targets if b]

    print("=== ASR realtime WebSocket ===")
    ws_results = await asyncio.gather(*(
        probe_ws(name, base, model, key, language, sample_rate, vad_silence_ms)
        for name, base, model in ws_targets
    ))
    for (name, _, _), result in zip(ws_targets, ws_results):
        print(f"{name:38s} {result}")
    print()

    ok_http = [name for (name, _, _), r in zip(http_targets, http_results) if r.startswith("OK")]
    ok_ws = [name for (name, _, _), r in zip(ws_targets, ws_results) if r.startswith("OK")]
    print("=== VERDICT ===")
    print("working HTTP combos:", ok_http or "NONE")
    print("working WS combos  :", ok_ws or "NONE")


if __name__ == "__main__":
    asyncio.run(main())
