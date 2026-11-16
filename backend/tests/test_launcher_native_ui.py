import unittest

from launcher.native_ui import ApiKeyPrompt, ES_AUTOHSCROLL, NativeLauncherWindow, WM_CREATE


class NativeWindowCreationTests(unittest.TestCase):
    def test_api_key_controls_use_create_message_window_handle(self) -> None:
        prompt = ApiKeyPrompt.__new__(ApiKeyPrompt)
        prompt.hwnd = 0
        prompt.edit = 0
        observed_parents: list[int] = []
        edit_styles: list[int] = []

        def fake_control(kind: str, _text: str, style: int, *_args, **_kwargs) -> int:
            observed_parents.append(prompt.hwnd)
            if kind == 'EDIT':
                edit_styles.append(style)
            return 1

        prompt._control = fake_control
        prompt._proc(4321, WM_CREATE, 0, 0)

        self.assertTrue(observed_parents)
        self.assertEqual({4321}, set(observed_parents))
        self.assertTrue(edit_styles)
        self.assertTrue(edit_styles[0] & ES_AUTOHSCROLL)

    def test_main_window_controls_use_create_message_window_handle(self) -> None:
        window = NativeLauncherWindow.__new__(NativeLauncherWindow)
        window.hwnd = 0
        window.font = 0
        window.buttons = {}
        observed_parents: list[int] = []

        def fake_control(*_args, **_kwargs) -> int:
            observed_parents.append(window.hwnd)
            return 1

        window._control = fake_control
        window._proc(9876, WM_CREATE, 0, 0)

        self.assertTrue(observed_parents)
        self.assertEqual({9876}, set(observed_parents))


if __name__ == '__main__':
    unittest.main()
