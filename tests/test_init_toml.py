"""`mdpdf init` must write an mdpdf.toml that the next build can read."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

import mdpdf


class InitWritesValidTomlTests(unittest.TestCase):
    """The brand used to be pasted between quotes verbatim, so a quote or a
    backslash in it produced a file `mdpdf` itself refused to parse."""

    def init(self, brand: str, theme: str = "plain") -> dict:
        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            os.chdir(folder)
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = mdpdf.cmd_init(argparse.Namespace(theme=theme, brand=brand, force=False))
                self.assertEqual(0, code)
                with (Path(folder) / "mdpdf.toml").open("rb") as fh:
                    return tomllib.load(fh)
            finally:
                os.chdir(previous)

    def test_plain_brand_round_trips(self) -> None:
        cfg = self.init("Acme")
        self.assertEqual(("plain", "Acme", "Acme"), (cfg["theme"], cfg["brand"], cfg["footer"]))

    def test_brand_with_quotes_round_trips(self) -> None:
        cfg = self.init('ACME "Labs"')
        self.assertEqual('ACME "Labs"', cfg["brand"])
        self.assertEqual('ACME "Labs"', cfg["footer"])

    def test_brand_with_backslash_round_trips(self) -> None:
        self.assertEqual(r"R&D \ Ops", self.init(r"R&D \ Ops")["brand"])

    def test_theme_path_with_quote_round_trips(self) -> None:
        self.assertEqual('themes/o"neil', self.init("Acme", theme='themes/o"neil')["theme"])


if __name__ == "__main__":
    unittest.main()
