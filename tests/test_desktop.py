import subprocess
import tempfile
import unittest
from pathlib import Path

from codex_switch.desktop import restart_codex_desktop
from codex_switch.store import CodexSwitchError


class DesktopRestartTest(unittest.TestCase):
    def completed(self, args, code=0):
        return subprocess.CompletedProcess(args=args, returncode=code, stdout="", stderr="")

    def test_windows_restarts_from_local_app_data_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Programs" / "Codex" / "Codex.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
            run_calls = []
            popen_calls = []

            def runner(args, **kwargs):
                run_calls.append(args)
                return self.completed(args)

            def popener(args, **kwargs):
                popen_calls.append(args)
                return object()

            result = restart_codex_desktop(
                system="Windows",
                runner=runner,
                popener=popener,
                sleeper=lambda seconds: None,
                environ={"LOCALAPPDATA": tmp},
            )

            self.assertEqual(result, "restarted Codex Desktop")
            self.assertEqual(run_calls[0], ["taskkill", "/IM", "Codex.exe", "/F", "/T"])
            self.assertEqual(popen_calls, [[str(exe)]])

    def test_windows_restarts_from_configured_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Custom Codex" / "Codex.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
            popen_calls = []

            def runner(args, **kwargs):
                return self.completed(args)

            def popener(args, **kwargs):
                popen_calls.append(args)
                return object()

            result = restart_codex_desktop(
                system="Windows",
                runner=runner,
                popener=popener,
                sleeper=lambda seconds: None,
                environ={"CODEX_DESKTOP_EXE": str(exe)},
            )

            self.assertEqual(result, "restarted Codex Desktop")
            self.assertEqual(popen_calls, [[str(exe)]])

    def test_windows_falls_back_to_start_command(self):
        run_calls = []
        popen_calls = []

        def runner(args, **kwargs):
            run_calls.append(args)
            return self.completed(args)

        def popener(args, **kwargs):
            popen_calls.append(args)
            return object()

        result = restart_codex_desktop(
            system="Windows",
            runner=runner,
            popener=popener,
            sleeper=lambda seconds: None,
            environ={},
        )

        self.assertEqual(result, "restarted Codex Desktop")
        self.assertEqual(run_calls[0], ["taskkill", "/IM", "Codex.exe", "/F", "/T"])
        self.assertEqual(popen_calls, [["cmd", "/c", "start", "", "Codex"]])

    def test_macos_kills_app_server_before_reopening(self):
        run_calls = []

        def runner(args, **kwargs):
            run_calls.append(args)
            return self.completed(args)

        result = restart_codex_desktop(
            system="Darwin",
            runner=runner,
            sleeper=lambda seconds: None,
        )

        self.assertEqual(result, "restarted Codex Desktop")
        self.assertIn(["pkill", "-x", "Codex"], run_calls)
        self.assertIn(
            ["pkill", "-f", "/Applications/Codex.app/Contents/Resources/codex app-server"],
            run_calls,
        )
        self.assertEqual(run_calls[-1], ["open", "-a", "Codex"])

    def test_unsupported_platform_reports_error(self):
        with self.assertRaises(CodexSwitchError):
            restart_codex_desktop(system="Linux")


if __name__ == "__main__":
    unittest.main()
