import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher.backend_probe import BackendProbe, BackendProbeStatus
from launcher.config_store import ConfigStore
from launcher.server_controller import ServerController, ServerState, create_uvicorn_server


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.started = threading.Event()

    def run(self) -> None:
        self.started.set()
        while not self.should_exit:
            time.sleep(0.005)


class ServerControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        env_file = root / '.env'
        template = root / '.env.example'
        template.write_text('DASHSCOPE_API_KEY=\n', encoding='utf-8')
        self.store = ConfigStore(env_file, template)
        self.store.ensure_exists()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_key_fails_without_starting_server(self) -> None:
        created: list[FakeServer] = []
        controller = ServerController(
            config_store=self.store,
            server_factory=lambda: created.append(FakeServer()) or created[-1],
            probe=lambda: BackendProbe(BackendProbeStatus.FREE),
            ready_timeout=0.1,
        )
        self.assertFalse(controller.start())
        self.assertEqual(controller.state, ServerState.FAILED)
        self.assertEqual(created, [])

    def test_start_and_stop_manage_one_server_thread(self) -> None:
        self.store.save_api_key('sk-test-secret-value')
        server = FakeServer()
        probes = iter([
            BackendProbe(BackendProbeStatus.FREE),
            BackendProbe(BackendProbeStatus.PROJECT_RUNNING, health={'ok': True}),
        ])
        controller = ServerController(
            config_store=self.store,
            server_factory=lambda: server,
            probe=lambda: next(probes),
            ready_timeout=0.5,
            poll_interval=0.01,
        )

        self.assertTrue(controller.start())
        self.assertEqual(controller.state, ServerState.READY)
        self.assertTrue(server.started.is_set())
        self.assertTrue(controller.stop())
        self.assertEqual(controller.state, ServerState.STOPPED)
        self.assertTrue(server.should_exit)

    def test_unknown_port_owner_is_not_terminated(self) -> None:
        self.store.save_api_key('sk-test-secret-value')
        controller = ServerController(
            config_store=self.store,
            server_factory=FakeServer,
            probe=lambda: BackendProbe(BackendProbeStatus.PORT_OCCUPIED),
            ready_timeout=0.1,
        )
        self.assertFalse(controller.start())
        self.assertEqual(controller.state, ServerState.FAILED)
        self.assertIn('8000', controller.last_error)

    def test_windowed_launcher_disables_console_logging(self) -> None:
        with patch('launcher.server_controller.uvicorn.Config') as config, patch(
            'launcher.server_controller.uvicorn.Server'
        ):
            create_uvicorn_server()

        self.assertIsNone(config.call_args.kwargs['log_config'])
        self.assertFalse(config.call_args.kwargs['access_log'])


if __name__ == '__main__':
    unittest.main()
