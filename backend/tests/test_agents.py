import unittest

from app.services.agents import ASRTranscriptEvent, parse_qwen_asr_event


class ParseQwenASREventTests(unittest.TestCase):
    def test_realtime_delta(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.delta',
            'delta': 'Hello',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'Hello', is_delta=True))

    def test_realtime_delta_preserves_leading_space(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.delta',
            'delta': ' world',
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', ' world', is_delta=True))

    def test_realtime_completed(self) -> None:
        event = parse_qwen_asr_event({
            'type': 'conversation.item.input_audio_transcription.completed',
            'transcript': 'Hello world.',
        })
        self.assertEqual(event, ASRTranscriptEvent('final', 'Hello world.'))

    def test_dashscope_sentence_partial(self) -> None:
        event = parse_qwen_asr_event({
            'output': {'sentence': {'text': 'Hello', 'sentence_end': False}},
        })
        self.assertEqual(event, ASRTranscriptEvent('partial', 'Hello'))

    def test_dashscope_sentence_final(self) -> None:
        event = parse_qwen_asr_event({
            'output': {'sentence': {'text': 'Hello world.', 'sentence_end': True}},
        })
        self.assertEqual(event, ASRTranscriptEvent('final', 'Hello world.'))

    def test_ignores_non_transcript_event(self) -> None:
        self.assertIsNone(parse_qwen_asr_event({'type': 'session.updated'}))


if __name__ == '__main__':
    unittest.main()
