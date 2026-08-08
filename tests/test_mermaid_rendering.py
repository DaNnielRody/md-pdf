"""Regression coverage for Mermaid rendering without invoking Mermaid CLI."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mdpdf


class MermaidRenderingTests(unittest.TestCase):
    def test_mermaid_theme_uses_compact_gantt_geometry(self) -> None:
        cfg = mdpdf.merge(
            mdpdf.DEFAULTS,
            mdpdf.load_toml(mdpdf.THEMES / "plain" / "theme.toml"),
        )

        gantt = mdpdf.mermaid_theme(cfg)["gantt"]

        self.assertEqual(800, gantt["useWidth"])
        self.assertEqual(150, gantt["leftPadding"])
        self.assertEqual(32, gantt["rightPadding"])

    def test_two_cached_blocks_share_heading_caption_but_have_ordinals(self) -> None:
        cfg = mdpdf.merge(
            mdpdf.DEFAULTS,
            mdpdf.load_toml(mdpdf.THEMES / "plain" / "theme.toml"),
        )
        first = "flowchart LR\n  A[Início] --> B[Fim]\n"
        second = "flowchart LR\n  C[Entrada] --> D[Saída]\n"
        markdown = (
            "## 4. Concorrência\n\n"
            "```mermaid\n" + first + "```\n\n"
            "```mermaid\n" + second + "```\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            fingerprint = json.dumps(mdpdf.mermaid_theme(cfg), sort_keys=True)
            for index, source in enumerate((first, second), start=1):
                digest = hashlib.sha1((source + fingerprint).encode("utf-8")).hexdigest()[:12]
                (cache / f"diagram-{index}-{digest}.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
                    'width="10" height="10"/>',
                    encoding="utf-8",
                )

            with patch("mdpdf.subprocess.run", side_effect=AssertionError("npx must not run")) as run:
                rendered = mdpdf.render_mermaid(markdown, cfg, mdpdf.THEMES / "plain", cache)

        run.assert_not_called()
        self.assertNotIn("```mermaid", rendered)
        self.assertEqual(2, rendered.count('class="figure--diagram diagram-page"'))
        self.assertIn("Figura 1 — Concorrência", rendered)
        self.assertIn("Figura 2 — Concorrência", rendered)


if __name__ == "__main__":
    unittest.main()
