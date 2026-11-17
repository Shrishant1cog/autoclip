from pathlib import Path

from autoclip import paths
from autoclip.config import IngestSettings
from autoclip.pipeline import ingest


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
