"""Pinned installation of external tools into ``work/tools`` (``tools/pins.toml``, BD-011).

The archive is downloaded into its own new directory, checked against the pinned size and
SHA-256 before anything is extracted, and extracted member by member with every path checked to
stay inside the target directory. A failed check leaves no installed tool behind.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from kbench.process import run_captured

_CHUNK_BYTES = 1 << 20
# Bounds a stalled connection; a 100 MB archive downloads in far less on any usable link.
DOWNLOAD_TIMEOUT_S = 600.0


class InstallError(RuntimeError):
    """The tool could not be installed as pinned."""


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    url: str
    sha256: str
    size_bytes: int
    archive: str
    executable: str
    platform: str


def default_pins_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "pins.toml"


def load_pins(path: Path) -> dict[str, Pin]:
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    pins = {}
    for name, entry in document.items():
        try:
            pins[name] = Pin(
                name=name,
                version=str(entry["version"]),
                url=str(entry["url"]),
                sha256=str(entry["sha256"]).lower(),
                size_bytes=int(entry["size_bytes"]),
                archive=str(entry["archive"]),
                executable=str(entry["executable"]),
                platform=str(entry["platform"]),
            )
        except KeyError as missing:
            raise InstallError(f"pin {name!r} lacks {missing}") from None
    return pins


def install_directory(work: Path, pin: Pin) -> Path:
    return work / "tools" / pin.name / pin.version


def installed_executable(work: Path, pin: Pin) -> Path:
    return install_directory(work, pin) / pin.executable


def install(pin: Pin, work: Path, *, archive: Path | None = None) -> Path:
    """Install ``pin`` under ``work`` and return its executable.

    ``archive`` uses an already downloaded file instead of the network; it is checked the same
    way. An existing installation is kept when its executable is present.
    """
    target = install_directory(work, pin)
    executable = target / pin.executable
    if executable.is_file():
        return executable
    if pin.archive not in ("zip", "appimage"):
        raise InstallError(f"{pin.name}: unsupported archive type {pin.archive!r}")

    if archive is None:
        download_dir = work / "downloads" / f"{pin.name}-{pin.version}"
        download_dir.mkdir(parents=True, exist_ok=True)
        archive = download_dir / PurePosixPath(pin.url).name
        if not archive.is_file():
            _download(pin.url, archive)
    _verify(archive, pin)

    staging = target.with_name(target.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        if pin.archive == "zip":
            _extract_zip(archive, staging)
        else:
            _extract_appimage(archive, staging)
        if not (staging / pin.executable).is_file():
            raise InstallError(f"{pin.name}: the archive holds no {pin.executable}")
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return executable


def _download(url: str, destination: Path) -> None:
    partial = destination.with_name(destination.name + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "kbench-installer"})
    try:
        with (
            urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response,
            partial.open("wb") as out,
        ):
            shutil.copyfileobj(response, out, _CHUNK_BYTES)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise InstallError(f"download of {url} failed: {error}") from error
    partial.rename(destination)


def _verify(archive: Path, pin: Pin) -> None:
    size = archive.stat().st_size
    if size != pin.size_bytes:
        raise InstallError(f"{archive.name}: {size} bytes, pinned {pin.size_bytes}")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    if digest.hexdigest() != pin.sha256:
        raise InstallError(f"{archive.name}: SHA-256 {digest.hexdigest()}, pinned {pin.sha256}")


def _extract_appimage(archive: Path, target: Path) -> None:
    """Unpack an AppImage with its own ``--appimage-extract`` into ``target/squashfs-root``.

    Running the unpacked ``AppRun`` needs no FUSE mount, and timed runs do not include mounting
    the image.
    """
    copy = target / archive.name
    shutil.copyfile(archive, copy)
    copy.chmod(0o755)
    result = run_captured([str(copy), "--appimage-extract"], DOWNLOAD_TIMEOUT_S, cwd=target)
    copy.unlink()
    if result.exit_status != 0:
        raise InstallError(
            f"{archive.name}: --appimage-extract failed: {result.stderr.strip()[-500:]}"
        )


def _extract_zip(archive: Path, target: Path) -> None:
    root = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise InstallError(f"{archive.name}: unsafe member path {member.filename!r}")
            destination = (target / Path(*path.parts)).resolve()
            if not destination.is_relative_to(root):
                raise InstallError(f"{archive.name}: member {member.filename!r} leaves the target")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise InstallError(f"{archive.name}: symbolic link {member.filename!r} refused")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out, _CHUNK_BYTES)
            if mode & 0o111:
                destination.chmod(0o755)
