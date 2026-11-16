import unittest

from launcher.server_controller import ServerState
from launcher.view_model import LauncherViewModel


class LauncherViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.view_model = LauncherViewModel()

    def test_ready_state_uses_successful_user_message(self) -> None:
        view = self.view_model.present(ServerState.READY, '')
        self.assertEqual(view.title, '服务已就绪')
        self.assertIn('YouTube', view.detail)
        self.assertEqual(view.color, '#22c55e')

    def test_error_message_redacts_api_key(self) -> None:
        secret = 'sk-test-secret-value'
        view = self.view_model.present(
            ServerState.FAILED,
            f'连接失败，credential={secret}',
            secrets=[secret],
        )
        self.assertNotIn(secret, view.detail)
        self.assertIn('****', view.detail)


if __name__ == '__main__':
    unittest.main()
