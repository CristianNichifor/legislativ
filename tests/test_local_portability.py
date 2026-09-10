"""Exercise Windows file-access and newline rules on every test host."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import cellar, date_locale, date_personale, launcher
from tests.test_local_runtime import CHANNEL, Transport, fixture_release


class PortabilityTests(unittest.TestCase):
    def test_explicit_posix_platform_does_not_use_host_path_flavour(self):
        with patch.object(launcher, "Path", side_effect=AssertionError("host path used")):
            self.assertEqual(
                launcher.default_data_home("linux", {}, "/home/person"),
                "/home/person/.local/share/legislativ",
            )
            self.assertEqual(
                launcher.default_data_home("darwin", {}, "/Users/person"),
                "/Users/person/Library/Application Support/legislativ",
            )

    def test_flushes_have_write_access_without_changing_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public.db"
            with cellar.deschide(public):
                pass
            before = public.read_bytes()
            real_fsync = os.fsync

            def writable_fsync(fd):
                # Windows FlushFileBuffers requires write access. A zero-byte write
                # enforces that access check on POSIX too, without changing content.
                os.write(fd, b"")
                real_fsync(fd)

            with patch.object(os, "fsync", side_effect=writable_fsync):
                date_locale.sync_file(public)
                target = date_personale.prepare_eu(public, None, root / "private.db")
            self.assertTrue(target.is_file())
            self.assertEqual(public.read_bytes(), before)

    def test_download_preserves_manifest_bytes_with_windows_newline_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = Transport()
            fingerprint = fixture_release(root / "source", transport, "2026-09-10", "First")
            manager = date_locale.DatasetManager(root / "home", CHANNEL, transport=transport)
            manager.check()
            original = transport.payloads[manager.offer["url"]]
            self.assertIn(b"\n", original)
            real_write_text = Path.write_text

            def windows_write_text(path, text, encoding=None, errors=None, newline=None):
                if path.name == "dataset-release.json" and newline is None:
                    newline = "\r\n"
                return real_write_text(
                    path, text, encoding=encoding, errors=errors, newline=newline
                )

            with patch.object(Path, "write_text", windows_write_text):
                manager.start(fingerprint)
                manager.thread.join(timeout=10)
            status = manager.status()
            self.assertEqual(status["progress"]["state"], "ready", status)
            saved = manager.home / "datasets" / fingerprint / "dataset-release.json"
            self.assertEqual(saved.read_bytes(), original)
