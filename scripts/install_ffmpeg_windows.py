"""Put a working ffmpeg on a Windows CI runner.

Chocolatey's **metadata** endpoint is a single point of failure. When it answers
503 or 504, `choco install ffmpeg-full` installs **nothing** and still exits
**0**, so a workflow that installs ffmpeg with it and then checks for ffmpeg
reports the wrong thing: it says the build has no `ass` filter, when in truth
there is no build at all. That is what happened to this repository's Windows
leg on CI run 44.

This script tries Chocolatey first, exactly as the workflow always did. Only
if that produced no ffmpeg does it fall back to Chocolatey's **package** URL —
the path that kept answering 200 through the outage — and unpack the package.
The package carries the build inside itself, so the fallback needs no metadata
endpoint, no second host and no new dependency: the same package, the same
version, the same binaries.

    python scripts/install_ffmpeg_windows.py

Exit code 0 when an ffmpeg is on PATH, 1 when there is none — and the error
then names what actually failed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

#: The package's own download URL. This is *not* the metadata endpoint that
#: goes down: the nupkg is a zip that carries the build inside it.
PACKAGE_URL = "https://community.chocolatey.org/api/v2/package/ffmpeg-full/9.1.0"

#: The version the metadata endpoint was resolving to when it failed.
PACKAGE_VERSION = "9.1.0"

#: The archive inside the package that holds the build.
INNER_ARCHIVE = "ffmpeg-release-full.7z"

#: Where 7-Zip usually lives on a Windows runner.
SEVEN_ZIP_PATHS = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\ProgramData\chocolatey\bin\7z.exe",
)


def run_choco() -> tuple[int, str]:
    """Install ffmpeg through Chocolatey, and say what it did.

    Chocolatey exits 0 when it installs nothing, so the exit code alone says
    nothing; the output is returned as well.
    """
    try:
        finished = subprocess.run(
            ["choco", "install", "ffmpeg-full", "-y", "--no-progress"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (FileNotFoundError, OSError) as error:
        return 127, f"choco could not be run: {error}"
    return finished.returncode, (finished.stdout or "") + (finished.stderr or "")


def find_ffmpeg() -> str | None:
    """The ffmpeg on PATH, if there is one."""
    return shutil.which("ffmpeg")


def seven_zip() -> str | None:
    """The 7-Zip executable, if there is one."""
    found = shutil.which("7z") or shutil.which("7z.exe")
    if found:
        return found
    for candidate in SEVEN_ZIP_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def download(url: str, destination: Path) -> None:
    """Fetch a URL to a file."""
    request = urllib.request.Request(url, headers={"User-Agent": "autoclip-ci"})
    with (
        urllib.request.urlopen(request, timeout=300) as response,
        destination.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle)


def unpack_package(package: Path, workdir: Path) -> Path:
    """Unpack the nupkg and the archive inside it; return ffmpeg's bin directory."""
    extracted = workdir / "package"
    with zipfile.ZipFile(package) as archive:
        archive.extractall(extracted)
    inner = extracted / "tools" / INNER_ARCHIVE
    if not inner.exists():
        raise FileNotFoundError(f"{INNER_ARCHIVE} is not in the package")
    seven = seven_zip()
    if seven is None:
        raise FileNotFoundError("7-Zip is not installed, so the archive cannot be unpacked")
    subprocess.run(
        [seven, "x", "-y", f"-o{extracted / 'tools'}", str(inner)],
        check=True,
        capture_output=True,
    )
    binaries = sorted((extracted / "tools").glob("ffmpeg-*/bin/ffmpeg.exe"))
    if not binaries:
        raise FileNotFoundError("the package contains no ffmpeg")
    return binaries[0].parent


def add_to_path(directory: Path) -> None:
    """Put a directory on PATH for this process and for the later CI steps."""
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with open(github_path, "a", encoding="utf-8") as handle:
            handle.write(str(directory) + "\n")


def main() -> int:
    code, output = run_choco()
    source = "chocolatey"
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print(f"Chocolatey installed nothing (exit {code}); falling back to the package URL.")
        print("--- what chocolatey said ---")
        print(output.strip() or "(nothing)")
        workdir = Path(tempfile.mkdtemp(prefix="autoclip-ffmpeg-"))
        try:
            package = workdir / f"ffmpeg-full.{PACKAGE_VERSION}.nupkg"
            download(PACKAGE_URL, package)
            add_to_path(unpack_package(package, workdir))
            ffmpeg = find_ffmpeg()
            source = "the package URL"
        except Exception as error:
            # Any failure here is a failure to install ffmpeg, and the reason
            # it failed is what the next step would otherwise get wrong.
            print(f"::error::The fallback install failed: {error}")
            ffmpeg = None
    if ffmpeg is None:
        print("::error::No ffmpeg on this runner.")
        print("--- what chocolatey said ---")
        print(output.strip() or "(nothing)")
        print(f"--- the fallback's package URL is {PACKAGE_URL} ---")
        return 1
    print(f"ffmpeg from {source}: {ffmpeg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
