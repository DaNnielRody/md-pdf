"""Regression coverage for cover inline markup and the `name` output option."""

from __future__ import annotations

import unittest
from pathlib import Path

import mdpdf


class CoverInlineMarkupTests(unittest.TestCase):
    """Cover fields used to be escaped verbatim, so backticks reached the PDF."""

    def test_code_span_becomes_code_element(self) -> None:
        self.assertEqual(
            "<code>volatile</code> e <code>Interlocked</code>",
            mdpdf.inline_md_to_html("`volatile` e `Interlocked`"),
        )

    def test_emphasis_inside_code_span_is_left_alone(self) -> None:
        self.assertEqual("<code>*ptr</code>", mdpdf.inline_md_to_html("`*ptr`"))

    def test_emphasis_outside_code_span_still_works(self) -> None:
        self.assertEqual(
            "<strong>a</strong> <em>b</em> <code>c</code>",
            mdpdf.inline_md_to_html("**a** *b* `c`"),
        )

    def test_html_inside_code_span_is_escaped(self) -> None:
        self.assertEqual(
            "<code>&lt;script&gt;</code>",
            mdpdf.inline_md_to_html("`<script>`"),
        )

    def test_double_fence_carries_a_literal_backtick(self) -> None:
        self.assertEqual("<code>a ` b</code>", mdpdf.inline_md_to_html("``a ` b``"))

    def test_plain_text_reading_drops_the_markup(self) -> None:
        self.assertEqual(
            "volatile e Interlocked: baixo nível",
            mdpdf.inline_md_to_text("`volatile` e **Interlocked**: baixo nível"),
        )

    def test_cover_title_carries_no_backtick(self) -> None:
        cfg = mdpdf.merge(
            mdpdf.DEFAULTS,
            mdpdf.load_toml(mdpdf.THEMES / "plain" / "theme.toml"),
        )

        cover = mdpdf.build_cover("`volatile` e `Interlocked`", [], cfg)

        self.assertIn("<code>volatile</code>", cover)
        self.assertNotIn("`", cover)


class OutputNamingTests(unittest.TestCase):
    MD = Path("/docs/lecture-notes.md")

    def resolve(self, name: str | None, flag: str | None = None) -> Path:
        cfg = {} if name is None else {"name": name}
        return mdpdf.resolve_output(self.MD, flag, cfg)

    def test_absent_name_keeps_the_markdown_name(self) -> None:
        self.assertEqual(Path("/docs/lecture-notes.pdf"), self.resolve(None))

    def test_empty_name_keeps_the_markdown_name(self) -> None:
        self.assertEqual(Path("/docs/lecture-notes.pdf"), self.resolve("   "))

    def test_name_is_used_verbatim_with_the_extension_appended(self) -> None:
        self.assertEqual(
            Path("/docs/SaintThomas(Laboratório S07 - Arch3).pdf"),
            self.resolve("SaintThomas(Laboratório S07 - Arch3)"),
        )

    def test_extension_is_not_duplicated(self) -> None:
        self.assertEqual(Path("/docs/Relatório.PDF"), self.resolve("Relatório.PDF"))

    def test_name_cannot_escape_the_document_folder(self) -> None:
        self.assertEqual(
            Path("/docs"), self.resolve("../../etc/passwd").parent
        )

    def test_output_flag_wins_over_name(self) -> None:
        self.assertEqual(
            Path("/tmp/explicit.pdf"),
            self.resolve("ignored", "/tmp/explicit.pdf"),
        )


if __name__ == "__main__":
    unittest.main()
