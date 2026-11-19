"""Tests for the incremental live-mode layer.

Pure offline tests: no microphone, no API key, no network. The end-to-end
websocket path is covered by scripts/live_smoke.py.
"""
from __future__ import annotations

import asyncio
import unittest

from app.live.caption import CaptionState, LiveConfig
from app.live.hub import LiveHub
from app.live.pcm import (
    FRAME_BYTES,
    EnergyVAD,
    FrameAssembler,
    FrameMailbox,
    mix_frames,
    normalize,
    resample,
    rms,
    to_mono,
    tone_frames,
)


class PcmTests(unittest.TestCase):
    def test_stereo_to_mono_averages_channels(self):
        raw = b'\x64\x00\xc8\x00' + b'\x00\x00\x00\x00'  # 100, 200 then 0, 0
        self.assertEqual(to_mono(raw, 2), b'\x96\x00\x00\x00')

    def test_resample_48k_to_16k_is_three_to_one(self):
        raw = b'\x00\x00' * 4800
        self.assertEqual(len(resample(raw, 48000)), 1600 * 2)

    def test_normalize_returns_16k_mono(self):
        raw = b'\x01\x00\x02\x00' * 4800
        self.assertEqual(len(normalize(raw, 2, 48000)), 1600 * 2)

    def test_frame_assembler_splits_20ms(self):
        assembler = FrameAssembler()
        frames = list(assembler.feed(b'\x00\x00' * 1000))
        self.assertEqual(len(frames), 3)
        self.assertTrue(all(len(frame) == FRAME_BYTES for frame in frames))

    def test_mix_frames_sums_and_clips(self):
        loud = b'\x00\x7f' * (FRAME_BYTES // 2)
        mixed = mix_frames([loud, loud, None])
        self.assertEqual(len(mixed), FRAME_BYTES)
        # 32512 + 32512 must be clipped to int16 max instead of wrapping.
        self.assertGreater(rms(mixed), 0.5)

    def test_vad_gates_silence_after_holdoff(self):
        vad = EnergyVAD(threshold=0.01, silence_frames=2)
        silent = b'\x00\x00' * (FRAME_BYTES // 2)
        self.assertTrue(vad.process(silent))
        self.assertTrue(vad.process(silent))
        self.assertFalse(vad.process(silent))
        self.assertFalse(vad.process(silent))
        self.assertEqual(vad.stats['gated'], 2)
        loud = next(iter(tone_frames(0.1)))
        self.assertTrue(vad.process(loud))
        self.assertTrue(vad.process(silent))  # hold-off restarts after speech

    def test_tone_frames_have_exact_size(self):
        frame = next(iter(tone_frames(0.1)))
        self.assertEqual(len(frame), FRAME_BYTES)

    def test_mailbox_is_bounded(self):
        box = FrameMailbox(maxlen=2)
        for _ in range(5):
            box.push(b'x')
        self.assertIsNotNone(box.pop())
        self.assertIsNotNone(box.pop())
        self.assertIsNone(box.pop())


def segment(text: str, source: str, *, status: str = 'final', at: float = 100.0):
    return {
        'id': 'seg-1',
        'source_text': source,
        'target_text': text,
        'status': status,
        'timestamp': at,
    }


class CaptionTests(unittest.TestCase):
    def test_only_final_translated_lines_pass(self):
        state = CaptionState()
        self.assertIsNone(state.submit(segment('他们包夹过来了', 'They collapse on us', status='translating'), now=100.0))
        self.assertIsNone(state.submit(segment('They collapse on us', 'They collapse on us'), now=100.0))
        self.assertIsNotNone(state.submit(segment('他们包夹过来了', 'They collapse on us'), now=100.0))

    def test_publish_delay_and_flush(self):
        config = LiveConfig(publish_delay_ms=500)
        state = CaptionState(config)
        state.submit(segment('转中路', 'Rotate mid'), now=100.0)
        self.assertEqual(state.flush(now=100.2), [])
        events = state.flush(now=100.6)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'caption.show')
        self.assertTrue(events[0]['ai_label'])
        self.assertEqual(events[0]['text'], '转中路')

    def test_zero_delay_is_not_overridden_by_default(self):
        config = LiveConfig(publish_delay_ms=0)
        state = CaptionState(config)
        state.submit(segment('小龙免费', 'Dragon is free'), now=10.0)
        self.assertEqual(len(state.flush(now=10.0)), 1)

    def test_dedupe_within_window(self):
        state = CaptionState(LiveConfig(dedupe_seconds=4))
        state.submit(segment('转中路', 'Rotate mid'), now=100.0)
        state.flush(now=100.0)
        state.submit(segment('转中路', 'Rotate mid'), now=101.0)
        self.assertEqual(state.stats['skipped'], 1)
        self.assertEqual(state.flush(now=101.0), [])

    def test_hide_recall_clear_and_resume(self):
        state = CaptionState()
        state.submit(segment('转中路', 'Rotate mid'), now=100.0)
        state.flush(now=100.0)
        self.assertEqual(len(state.recall()), 1)
        self.assertEqual(len(state.lines), 0)
        self.assertEqual(state.hide_all()['type'], 'caption.clear')
        state.submit(segment('小龙免费', 'Dragon is free'), now=101.0)
        self.assertEqual(state.flush(now=101.0), [])
        state.resume()
        self.assertFalse(state.hidden)
        state.submit(segment('我回城', 'I recall'), now=102.0)
        self.assertEqual(len(state.flush(now=102.0)), 1)

    def test_srt_has_bilingual_friendly_timings(self):
        state = CaptionState(LiveConfig(hold_ms=3000))
        state.submit(segment('转中路', 'Rotate mid'), now=100.0)
        state.submit(segment('小龙免费', 'Dragon is free', at=105.0), now=105.0)
        srt = state.srt()
        self.assertIn('00:00:00,000 --> 00:00:03,000', srt)
        self.assertIn('00:00:05,000', srt)
        self.assertIn('转中路', srt)

    def test_config_update_keeps_zero(self):
        config = LiveConfig()
        config.update({'publish_delay_ms': 0, 'max_lines': 99, 'ai_label': False})
        self.assertEqual(config.publish_delay_ms, 0)
        self.assertEqual(config.max_lines, 3)
        self.assertFalse(config.ai_label)


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.hub = LiveHub()
        self.overlay = FakeWebSocket()
        self.console = FakeWebSocket()
        self.hub.attach_overlay(self.overlay)
        self.hub.attach_console(self.console)

    async def asyncTearDown(self) -> None:
        await self.hub.stop()

    async def test_mock_mode_broadcasts_one_whole_line(self):
        await self.hub.start(mock=True)
        await self.hub.inject_demo('We should rotate mid.', '我们应该先转中路。')
        await asyncio.sleep(0.12)  # let the 40 ms flush loop publish
        shows = [event for event in self.overlay.sent if event.get('type') == 'caption.show']
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0]['text'], '我们应该先转中路。')
        self.assertEqual(shows[0]['source_text'], 'We should rotate mid.')
        self.assertTrue(shows[0]['ai_label'])
        self.assertEqual(self.hub.mode, 'mock')

    async def test_hide_stops_future_captions(self):
        await self.hub.start(mock=True)
        await self.hub.handle_console_message({'type': 'hide'})
        await self.hub.inject_demo('Dragon is free.', '小龙可以直接拿。')
        await asyncio.sleep(0.12)
        self.assertFalse(any(event.get('type') == 'caption.show' for event in self.overlay.sent))
        self.assertTrue(any(event.get('type') == 'caption.clear' for event in self.overlay.sent))
        await self.hub.handle_console_message({'type': 'resume'})
        self.assertFalse(self.hub.state.hidden)

    async def test_mock_chat_answer_uses_original_contract(self):
        await self.hub.start(mock=True)
        await self.hub.handle_console_message({
            'type': 'chat.ask', 'question': 'rotate 是什么意思？',
            'selected_text': 'We should rotate mid.', 'request_id': 'r1',
        })
        answers = [event for event in self.console.sent if event.get('type') == 'chat.answer']
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]['request_id'], 'r1')
        self.assertIn('We should rotate mid.', answers[0]['answer'])

    async def test_stop_clears_hidden_state(self):
        await self.hub.start(mock=True)
        await self.hub.handle_console_message({'type': 'hide'})
        self.assertTrue(self.hub.state.hidden)
        await self.hub.stop()
        self.assertFalse(self.hub.state.hidden)
        self.assertEqual(len(self.hub.state.lines), 0)
        self.assertTrue(any(event.get('type') == 'caption.clear' for event in self.overlay.sent))

    async def test_status_contains_overlay_url_and_config(self):
        await self.hub.start(mock=True)
        status = self.hub.status()
        self.assertIn('/live/overlay.html', status['overlay_url'])
        self.assertIn('source_microphone', status['config'])
        self.assertEqual(status['mode'], 'mock')


class DesktopOverlayTests(unittest.IsolatedAsyncioTestCase):
    """Native caption window + audio fixes, without creating a real window."""

    def test_default_config_captures_both_sources(self):
        config = LiveConfig()
        self.assertTrue(config.source_microphone)
        self.assertTrue(config.source_system)

    def test_auto_gain_lifts_quiet_microphone(self):
        import struct

        from app.live.pcm import auto_gain

        quiet = struct.pack('<h', 1200) * (FRAME_BYTES // 2)
        boosted = auto_gain(quiet)
        self.assertGreater(rms(boosted), rms(quiet) * 3)
        loud = struct.pack('<h', 20000) * (FRAME_BYTES // 2)
        self.assertEqual(auto_gain(loud), loud)

    def test_overlay_applies_caption_events(self):
        import queue

        from launcher.caption_overlay import CaptionOverlay

        overlay = CaptionOverlay.__new__(CaptionOverlay)
        overlay.events = queue.Queue()
        overlay.lines = []
        overlay.levels = {}
        overlay.hwnd = 0
        overlay.visible = False
        overlay.hub = type('FakeHub', (), {'metrics': {'levels': {'microphone': 0.04, 'system': 0.1}}})()
        overlay.enqueue({'type': 'caption.show', 'id': 'a', 'text': '中路换线', 'source_text': 'Rotate mid'})
        overlay.enqueue({'type': 'caption.show', 'id': 'b', 'text': '稳住十秒', 'source_text': 'Play slow'})
        overlay.tick()
        self.assertEqual([line['text'] for line in overlay.lines], ['中路换线', '稳住十秒'])
        self.assertAlmostEqual(overlay.levels['system'], 0.1)
        overlay.enqueue({'type': 'caption.hide', 'id': 'a'})
        overlay.enqueue({'type': 'caption.clear'})
        overlay.tick()
        self.assertEqual(overlay.lines, [])

    async def test_local_overlay_sink_receives_broadcasts(self):
        received: list[dict] = []
        hub = LiveHub()
        hub.register_local_overlay_sink(received.append)
        await hub.broadcast_overlay({'type': 'caption.clear'})
        self.assertEqual(received, [{'type': 'caption.clear'}])
        await hub.stop()


class BridgeResilienceTests(unittest.IsolatedAsyncioTestCase):
    """A quiet room must not kill the ASR task, and a closed session must heal."""

    @staticmethod
    def _bridge():
        import threading
        from types import SimpleNamespace

        from app.live.bridge import LiveAudioBridge

        bridge = LiveAudioBridge.__new__(LiveAudioBridge)
        bridge.hub = SimpleNamespace(metrics={}, last_error='', session_id='')
        bridge._stop = threading.Event()
        bridge._outbox = asyncio.Queue(maxsize=200)
        bridge._vad = EnergyVAD()
        bridge._mailboxes = {'microphone': FrameMailbox(), 'system': FrameMailbox()}
        bridge._tasks = []
        bridge._session_tasks = []
        bridge._session_ready = asyncio.Event()
        bridge._first_error = None
        bridge._selected = [('microphone', 1)]
        bridge._ws = None
        bridge._send_lock = asyncio.Lock()
        return bridge

    async def test_silence_keepalive_feeds_upstream(self):
        from contextlib import suppress

        bridge = self._bridge()
        task = asyncio.create_task(bridge._mix_loop())
        await asyncio.sleep(0.5)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self.assertGreater(bridge.hub.metrics.get('frames_keepalive', 0), 0)
        frames = []
        while not bridge._outbox.empty():
            frames.append(bridge._outbox.get_nowait())
        self.assertTrue(frames)
        self.assertEqual(len(frames[0]), FRAME_BYTES)
        self.assertEqual(set(frames[0]), {0})
        self.assertAlmostEqual(bridge.hub.metrics['levels']['microphone'], 0.0)

    async def test_supervisor_reconnects_when_session_ends(self):
        from contextlib import suppress

        class FakeWS:
            async def close(self):
                return None

        bridge = self._bridge()
        opened: list[int] = []

        async def fake_open():
            opened.append(1)
            return FakeWS()

        async def fake_send(ws):
            return None

        async def fake_recv(ws):
            return None

        bridge._open_session = fake_open
        bridge._send_loop = fake_send
        bridge._recv_loop = fake_recv
        supervisor = asyncio.create_task(bridge._session_supervisor())
        await asyncio.sleep(1.1)
        supervisor.cancel()
        with suppress(asyncio.CancelledError):
            await supervisor
        self.assertGreaterEqual(len(opened), 2)
        self.assertGreaterEqual(bridge.hub.metrics.get('reconnects', 0), 1)
        self.assertTrue(bridge._session_ready.is_set())
        self.assertIsNone(bridge._first_error)


class CaptionCardThemeTests(unittest.TestCase):
    """The desktop card must keep the extension's light visual spec."""

    def _overlay(self, folder):
        from launcher.caption_overlay import CaptionOverlay

        return CaptionOverlay(folder, type('FakeHub', (), {'metrics': {}})())

    def test_defaults_match_extension_card(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as folder:
            overlay = self._overlay(folder)
            self.assertEqual(overlay.theme, 'light')
            self.assertEqual(overlay.font_size, 17)
            self.assertTrue(overlay._light())
            self.assertEqual(overlay._width(), 940)

    def test_legacy_config_resets_cinema_font_scale(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as folder:
            config = Path(folder) / 'data' / 'caption_overlay.json'
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(json.dumps({
                'x': 100, 'y': 200, 'font_size': 32,
                'minimal': False, 'chroma': False, 'show_english': True,
            }), encoding='utf-8')
            overlay = self._overlay(folder)
            self.assertEqual(overlay.font_size, 17)
            self.assertEqual(overlay.theme, 'light')


if __name__ == '__main__':
    unittest.main()
