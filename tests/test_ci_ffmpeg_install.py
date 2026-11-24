"""The Windows CI leg must be able to install ffmpeg when Chocolatey's feed is down.

On CI run 44 the Windows leg failed with *"This ffmpeg has no 'ass' filter"*. The
real cause was that there was no ffmpeg at all: Chocolatey's **metadata** endpoint
was unreachable, `choco install ffmpeg-full` installed nothing and still exited 0,
and the step that checked the filter looked in a program that was never installed.

The fix is in the workflow's install step, not in the product: Chocolatey is still
tried first, and only if it produced no ffmpeg does the step fall back to
Chocolatey's own **package** URL — the path that kept answering 200 through the
outage. These tests are the guard: they fail on the workflow as it was before the
fix, and they hold the fallback to the behaviour it promises.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "install_ffmpeg_windows.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _load_script():
    """Import the install script by path — it is a script, not a package."""
    spec = importlib.util.spec_from_file_location("install_ffmpeg_windows", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _fake_ffmpeg(directory: Path) -> Path:
    """Create a file that `shutil.which` finds as ffmpeg."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    path = directory / name
    path.write_text("not a real ffmpeg", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _windows_install_step(text: str) -> str:
    """The body of the workflow's Windows ffmpeg install step."""
    marker = "- name: Install ffmpeg (Windows)"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    end = rest.find("\n      - name:")
    return rest[:end] if end != -1 else rest


class TestTheWorkflow:
    """The workflow must install ffmpeg through the script."""

    def test_the_windows_install_step_runs_the_script(self):
        step = _windows_install_step(WORKFLOW.read_text(encoding="utf-8"))
        assert "scripts/install_ffmpeg_windows.py" in step

    def test_the_step_still_installs_through_chocolatey_first(self):
        # The fallback is a fallback. Chocolatey stays the primary source, so
        # the ordinary case is exactly what it was before.
        source = SCRIPT.read_text(encoding="utf-8")
        assert '"choco", "install", "ffmpeg-full"' in source


class TestTheFallback:
    """The script's three outcomes."""

    def test_the_fallback_is_not_the_metadata_endpoint(self):
        # The metadata endpoint is the thing that goes down. The package URL is
        # a different path on the same host, and it is the one that answers.
        assert "/api/v2/package/" in script.PACKAGE_URL
        assert "Packages(" not in script.PACKAGE_URL

    def test_chocolatey_is_tried_first_and_the_fallback_is_not_used(self, tmp_path, monkeypatch):
        installed = tmp_path / "chocolatey-bin"
        installed.mkdir()
        _fake_ffmpeg(installed)
        monkeypatch.setenv("PATH", str(installed))
        calls: list[str] = []

        def record() -> tuple[int, str]:
            calls.append("choco")
            return 0, "Chocolatey installed 1/1 packages."

        def unexpected(url: str, destination: Path) -> None:
            raise AssertionError("the fallback must not run when chocolatey provided ffmpeg")

        monkeypatch.setattr(script, "run_choco", record)
        monkeypatch.setattr(script, "download", unexpected)
        assert script.main() == 0
        assert calls == ["choco"]

    def test_the_package_url_is_used_when_chocolatey_installed_nothing(
        self, tmp_path, monkeypatch, capsys
    ):
        binaries = tmp_path / "work" / "ffmpeg-9.1-full_build" / "bin"
        binaries.mkdir(parents=True)
        _fake_ffmpeg(binaries)
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        github_path = tmp_path / "github-path"
        monkeypatch.setenv("GITHUB_PATH", str(github_path))
        monkeypatch.setattr(script, "run_choco", lambda: (0, "Chocolatey installed 0/0 packages."))
        downloaded: list[str] = []

        def fake_download(url: str, destination: Path) -> None:
            downloaded.append(url)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"not a real package")

        monkeypatch.setattr(script, "download", fake_download)
        monkeypatch.setattr(script, "unpack_package", lambda package, work: binaries)
        assert script.main() == 0
        assert downloaded == [script.PACKAGE_URL]
        # The later CI steps must see it too, not only this process.
        assert str(binaries) in github_path.read_text(encoding="utf-8")
        # And the log must show why the fallback was needed.
        out = capsys.readouterr().out
        assert "Chocolatey installed 0/0 packages." in out

    def test_the_real_reason_is_reported_when_neither_way_works(
        self, tmp_path, monkeypatch, capsys
    ):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        monkeypatch.setenv("GITHUB_PATH", str(tmp_path / "github-path"))
        monkeypatch.setattr(
            script, "run_choco", lambda: (0, "Unable to find package 'ffmpeg-full'.")
        )

        def failing_download(url: str, destination: Path) -> None:
            raise OSError("the package URL timed out")

        monkeypatch.setattr(script, "download", failing_download)
        assert script.main() == 1
        out = capsys.readouterr().out
        # Chocolatey's own words, and the fallback's own failure — not the
        # filter check's wrong answer.
        assert "Unable to find package 'ffmpeg-full'" in out
        assert "the package URL timed out" in out
        assert "no 'ass' filter" not in out
