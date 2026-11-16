import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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

    def test_question_context_retrieves_older_relevant_segment_with_timestamp(self) -> None:
        store = SessionStore(max_segments=50)
        session = store.create('')
        store.add_segment(session.session_id, SubtitleSegment(
            id='old', source_text='The battery lasts eighteen hours.', target_text='电池续航十八小时。',
            timestamp=1, start_ms=125000, end_ms=128000,
        ))
        for index in range(20):
            store.add_segment(session.session_id, SubtitleSegment(
                id=f'new-{index}', source_text=f'Other topic {index}.', target_text=f'其他内容{index}。',
                timestamp=index + 2, start_ms=200000 + index * 1000,
            ))
        context = store.question_context(session.session_id, '电池续航多久？', recent_limit=3)
        self.assertIn('[02:05]', context)
        self.assertIn('battery lasts eighteen hours', context)

    def test_sqlite_persists_session_segments_summaries_and_questions(self) -> None:
        with TemporaryDirectory() as directory:
            database_path = Path(directory) / 'history.db'
            store = SessionStore(max_segments=10, database_path=database_path)
            session = store.create('https://youtube.test/video', video_title='Test', input_mode='captions')
            store.add_segment(session.session_id, SubtitleSegment(
                id='one', source_text='Context matters.', target_text='上下文很重要。', timestamp=1,
                start_ms=1000, end_ms=2500, source='youtube-caption',
            ))
            store.add_summary(session.session_id, 1000, 2500, '视频强调上下文。')
            store.add_question(session.session_id, 'question-one', '重点是什么？', '', '上下文很重要。[00:01]')
            history = store.list_history()
            detail = store.get_history(session.session_id)
            self.assertEqual(history[0].video_title, 'Test')
            self.assertEqual(history[0].segment_count, 1)
            self.assertEqual(history[0].question_count, 1)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail.segments[0].target_text, '上下文很重要。')
            self.assertEqual(detail.summaries[0].content, '视频强调上下文。')
            self.assertEqual(detail.questions[0].answer, '上下文很重要。[00:01]')
            store.delete(session.session_id)
            store.close()

            connection = __import__('sqlite3').connect(database_path)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT source FROM segments').fetchone()[0], 'youtube-caption')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM summaries').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM questions').fetchone()[0], 1)
            self.assertIsNotNone(connection.execute('SELECT ended_at FROM sessions').fetchone()[0])
            connection.close()


if __name__ == '__main__':
    unittest.main()
