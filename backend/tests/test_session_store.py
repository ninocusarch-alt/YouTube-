import unittest

from app.models import SubtitleSegment
from app.services.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_translation_updates_existing_record_in_place(self) -> None:
        store = SessionStore(max_segments=10)
        session = store.create('https://www.youtube.com/watch?v=test')
        pending = SubtitleSegment(
            id='one', source_text='Hello world.', target_text='', timestamp=1, status='translating'
        )
        translated = pending.model_copy(update={'target_text': '你好，世界。', 'status': 'final'})
        store.add_segment(session.session_id, pending)
        store.add_segment(session.session_id, translated)
        self.assertEqual(len(session.segments), 1)
        self.assertEqual(session.segments[0].target_text, '你好，世界。')

    def test_context_contains_recent_bilingual_records(self) -> None:
        store = SessionStore(max_segments=10)
        session = store.create('')
        store.add_segment(session.session_id, SubtitleSegment(
            id='one', source_text='Latency matters.', target_text='延迟很重要。', timestamp=1
        ))
        self.assertIn('EN: Latency matters.', store.context(session.session_id))
        self.assertIn('ZH: 延迟很重要。', store.context(session.session_id))


if __name__ == '__main__':
    unittest.main()
