from pathlib import Path

import pytest
from autoclip import paths
from autoclip.config import IngestSettings
from autoclip.pipeline import ingest
from autoclip.security.egress import Permit


class _StopDownload(Exception):
    """Raised to end a download at the moment yt-dlp would have been launched."""


def _captured_ytdlp_command(monkeypatch: pytest.MonkeyPatch, settings: IngestSettings) -> list[str]:
    """Run the download far enough to capture the yt-dlp command line.

    The egress check is stubbed out so the test never resolves a real hostname,
    and the process launch is stopped so nothing is downloaded.
    """
    captured: dict[str, list[str]] = {}

    def fake_popen(command: list[str], **kwargs: object) -> None:
        captured["command"] = command
        raise _StopDownload

    monkeypatch.setattr(
        ingest.gateway,
        "authorize",
        lambda transfer: Permit(transfer, destination_class="public", allowed=True, reason="test"),
    )
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    source = ingest.new_youtube_source("https://www.youtube.com/watch?v=abc123")
    with pytest.raises(_StopDownload):
        ingest.download_youtube(source, settings)

    return captured["command"]


def test_download_target_dir_defaults_to_raw(autoclip_home: Path) -> None:
    settings = IngestSettings()

    assert ingest.download_target_dir("src123", settings) == paths.raw_dir() / "src123"


def test_download_target_dir_honours_configured_folder(tmp_path: Path) -> None:
    folder = tmp_path / "materials" / "input"
    settings = IngestSettings(download_dir=str(folder))

    assert ingest.download_target_dir("src123", settings) == folder / "src123"


def test_download_target_dir_gives_each_link_its_own_folder(tmp_path: Path) -> None:
    settings = IngestSettings(download_dir=str(tmp_path))

    first = ingest.download_target_dir("aaa", settings)
    second = ingest.download_target_dir("bbb", settings)

    assert first != second
    assert first.parent == second.parent == tmp_path


def test_the_download_uses_the_configured_format_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ingest.ytdlp_format` must reach yt-dlp, not just sit in the config file."""
    settings = IngestSettings(ytdlp_format="best[height<=720]")

    command = _captured_ytdlp_command(monkeypatch, settings)

    index = command.index("--format")
    assert command[index + 1] == "best[height<=720]"


def test_the_default_download_caps_the_video_at_1080p(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default must not pull the largest stream YouTube happens to offer."""
    command = _captured_ytdlp_command(monkeypatch, IngestSettings())

    selector = command[command.index("--format") + 1]
    assert "height<=1080" in selector
    assert "bestvideo*+bestaudio/best" not in selector


def test_the_download_asks_for_english_captions_when_preferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = IngestSettings(prefer_youtube_captions=True)

    command = _captured_ytdlp_command(monkeypatch, settings)

    assert "--write-auto-subs" in command
    assert command[command.index("--sub-langs") + 1] == "en.*"
