"""Run one opt-in live caption/translation/chat smoke test against the local EXE."""

import asyncio
import json

import httpx
import websockets


BASE_URL = 'http://127.0.0.1:8000'


async def main() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f'{BASE_URL}/api/sessions',
            json={
                'video_url': 'https://www.youtube.com/watch?v=function-test',
                'video_title': 'Functional smoke test',
                'input_mode': 'captions',
                'subtitle_source': 'youtube-manual',
            },
        )
        response.raise_for_status()
        session_id = response.json()['session_id']
        try:
            async with websockets.connect(f'ws://127.0.0.1:8000/ws/sessions/{session_id}') as socket:
                ready = json.loads(await asyncio.wait_for(socket.recv(), 10))
                assert ready['type'] == 'session.ready'
                assert ready['input_mode'] == 'captions'
                print('READY captions youtube-manual')

                await socket.send(json.dumps({
                    'type': 'caption.segment',
                    'id': 'test-caption-1',
                    'text': 'Artificial intelligence products should solve real user problems.',
                    'start_ms': 65000,
                    'end_ms': 69000,
                    'source': 'youtube-manual',
                }))
                translation = ''
                for _ in range(5):
                    event = json.loads(await asyncio.wait_for(socket.recv(), 20))
                    print('EVENT', event.get('type'))
                    if event.get('type') == 'transcript.translation':
                        translation = event['payload'].get('target_text', '')
                        break
                assert translation, 'Translation was not returned.'

                await socket.send(json.dumps({
                    'type': 'chat.ask',
                    'request_id': 'test-question-1',
                    'question': 'What is the main point of this sentence?',
                    'selected_segment_id': 'test-caption-1',
                    'selected_text': '',
                }))
                answer = ''
                for _ in range(5):
                    event = json.loads(await asyncio.wait_for(socket.recv(), 30))
                    print('EVENT', event.get('type'))
                    if event.get('type') == 'chat.answer':
                        answer = event.get('answer', '')
                        break
                assert answer and '[01:05]' in answer, 'The answer did not contain its timestamp citation.'
                print('TRANSLATION_OK true')
                print('CHAT_CITATION_OK true')

            detail_response = await client.get(f'{BASE_URL}/api/history/{session_id}')
            detail_response.raise_for_status()
            detail = detail_response.json()
            assert len(detail['segments']) == 1
            assert len(detail['questions']) == 1
            print('HISTORY_OK 1 1')
        finally:
            await client.delete(f'{BASE_URL}/api/sessions/{session_id}')


if __name__ == '__main__':
    asyncio.run(main())
