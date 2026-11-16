import os
import unittest
from uuid import uuid4

from launcher.backend_probe import BackendProbeStatus, classify_health_payload
from launcher.single_instance import SingleInstance


class BackendProbeTests(unittest.TestCase):
    def test_recognizes_video_companion_health_payload(self) -> None:
        status = classify_health_payload({
            'ok': True,
            'asr_provider': 'qwen-realtime',
            'translation_provider': 'qwen',
        })
        self.assertEqual(status, BackendProbeStatus.PROJECT_RUNNING)

    def test_rejects_unrelated_health_payload(self) -> None:
        status = classify_health_payload({'ok': True, 'service': 'another-app'})
        self.assertEqual(status, BackendProbeStatus.PORT_OCCUPIED)


@unittest.skipUnless(os.name == 'nt', 'Windows named mutex test')
class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_is_rejected_until_first_releases(self) -> None:
        name = f'Local\\VideoCompanionTest-{uuid4()}'
        first = SingleInstance(name)
        second = SingleInstance(name)
        third = SingleInstance(name)

        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(third.acquire())
        third.release()


if __name__ == '__main__':
    unittest.main()
