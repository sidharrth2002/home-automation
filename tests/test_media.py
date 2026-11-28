"""The media setup's pieces that don't need the containers: where the library is, and qBittorrent's log.

Run: .venv/bin/python -m tests.test_media
"""
import os
import subprocess
from pathlib import Path
from unittest import mock

import media.__main__ as m


def run():
    with mock.patch.dict(os.environ, {"MEDIA_DIR": "/srv/media"}):
        assert m.media_dir() == Path("/srv/media")
    with mock.patch.dict(os.environ, {"MEDIA_DIR": "data/media"}):
        assert m.media_dir() == m.ROOT / "data" / "media", "relative to the repo, as compose reads it"
    with mock.patch.dict(os.environ, {}, clear=True):
        assert m.media_dir() == m.ROOT / "data" / "media"

    log = ("WebUI will be started shortly after internal preparations. Please wait...\n"
           "The WebUI administrator username is: admin\n"
           "The WebUI administrator password was not set. A temporary password is provided for this session: aB3dE6fG9\n"
           "...restart...\n"
           "The WebUI administrator password was not set. A temporary password is provided for this session: zZ1yY2xX3\n")
    with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, log, "")):
        assert m.temporary_password() == "zZ1yY2xX3", "the latest start's"
    with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "no password here", "")):
        assert m.temporary_password() is None

    assert set(m.CATEGORIES.values()) <= {f"/media/{f}" for f in m.FOLDERS}, "categories land in folders setup makes"
    assert all(p.startswith("/media/") and p[len("/media/"):] in m.FOLDERS for _, _, p in m.LIBRARIES)
    print("media OK")


if __name__ == "__main__":
    run()
