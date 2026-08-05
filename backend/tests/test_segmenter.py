import unittest

from app.services.segmenter import StreamingSegmenter


class StreamingSegmenterTests(unittest.TestCase):
    def test_punctuation_emits_short_phrase_before_final(self) -> None:
        segmenter = StreamingSegmenter(min_words=2, max_words=18, max_wait_seconds=2)
        result = segmenter.feed('Although the results were unexpected,', is_final=False, now=0)
        self.assertEqual(result.phrases, ['Although the results were unexpected,'])
        self.assertEqual(result.live_text, '')

    def test_max_words_prevents_long_sentence_stall(self) -> None:
        segmenter = StreamingSegmenter(min_words=2, max_words=4, max_wait_seconds=10)
        result = segmenter.feed('one two three four five six', is_final=False, now=0)
        self.assertEqual(result.phrases, ['one two three four'])
        self.assertEqual(result.live_text, 'five six')

    def test_max_wait_emits_without_punctuation(self) -> None:
        segmenter = StreamingSegmenter(min_words=3, max_words=18, max_wait_seconds=1.5)
        segmenter.feed('we need to', is_final=False, now=0)
        result = segmenter.feed('we need to keep moving forward', is_final=False, now=1.6)
        self.assertEqual(result.phrases, ['we need to keep moving forward'])

    def test_final_flushes_short_tail_and_resets(self) -> None:
        segmenter = StreamingSegmenter(min_words=4, max_words=18, max_wait_seconds=3)
        segmenter.feed('this is a', is_final=False, now=0)
        result = segmenter.feed('this is a test', is_final=True, now=0.5)
        self.assertEqual(result.phrases, ['this is a test'])
        next_result = segmenter.feed('new phrase', is_final=True, now=1)
        self.assertEqual(next_result.phrases, ['new phrase'])


if __name__ == '__main__':
    unittest.main()
