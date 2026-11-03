"""LaTeX math: every common delimiter becomes typeset SVG, code stays verbatim."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from contextlib import redirect_stderr
import unittest
from pathlib import Path
from unittest.mock import patch

import mdpdf


def cfg() -> dict:
    return mdpdf.merge(
        mdpdf.DEFAULTS,
        mdpdf.load_toml(mdpdf.THEMES / "plain" / "theme.toml"),
    )


def to_html(md: str) -> str:
    return mdpdf.markdown_to_html(mdpdf.preprocess_markdown(md, cfg()))


def fake_svg(items: list[tuple[str, bool]], cache: Path) -> list[str | None]:
    """Stand-in renderer: echoes the TeX it was asked for, fails on `\\bad`."""
    return [None if "\\bad" in tex else f'<svg data-tex="{tex}" data-display="{display}"></svg>'
            for tex, display in items]


class MathDelimiterTests(unittest.TestCase):
    def test_dollar_delimiters_keep_their_tex_source(self) -> None:
        html = to_html("Energia $E=mc^2$ e\n\n$$\\int_0^1 x\\,dx$$\n")

        self.assertIn('<span class="math inline">\\(E=mc^2\\)</span>', html)
        self.assertIn('<span class="math display">\\[\\int_0^1 x\\,dx\\]</span>', html)

    def test_backslash_paren_is_inline_math(self) -> None:
        html = to_html("Soma \\( a + b \\) aqui.\n")

        self.assertIn('<span class="math inline">\\(a + b\\)</span>', html)

    def test_backslash_bracket_block_is_display_math(self) -> None:
        html = to_html("Antes:\n\n\\[\n\\frac{a}{b}\n\\]\n\nDepois.\n")

        self.assertIn('<span class="math display">', html)
        self.assertIn("\\frac{a}{b}", html)

    def test_code_keeps_backslash_delimiters_verbatim(self) -> None:
        md = "Use `\\(x\\)` inline.\n\n```\n\\[ y \\]\n\\(z\\)\n```\n"

        html = to_html(md)

        self.assertNotIn("math", html)
        self.assertIn("<code>\\(x\\)</code>", html)
        self.assertIn("\\[ y \\]", html)

    def test_stray_backslash_paren_does_not_reach_into_the_next_paragraph(self) -> None:
        html = to_html("Um \\( solto.\n\nOutro \\) depois.\n")

        self.assertNotIn("math", html)
        self.assertNotIn("$", html)
        self.assertIn("Um ( solto.", html)

    def test_inline_math_does_not_swallow_a_code_span(self) -> None:
        html = to_html("Abre \\( e `codigo \\)` fecha.\n")

        self.assertNotIn("math", html)
        self.assertIn("<code>codigo \\)</code>", html)

    def test_math_in_a_table_cell_stays_math(self) -> None:
        html = to_html("| Grandeza | Fórmula |\n|---|---|\n| Área | \\( \\pi r^2 \\) |\n")

        self.assertRegex(html, r'<td[^>]*><span class="math inline">\\\(\\pi r\^2\\\)</span></td>')

    def test_escaped_bracket_inside_a_sentence_stays_text(self) -> None:
        html = to_html("Veja a referência \\[1\\] no fim.\n")

        self.assertNotIn("math", html)
        self.assertIn("[1]", html)


class RenderMathTests(unittest.TestCase):
    def test_inline_and_display_spans_become_svg(self) -> None:
        html = ('<p>a <span class="math inline">\\(x&lt;y\\)</span></p>'
                '<p><span class="math display">\\[\\sum_i a_i\\]</span></p>')

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mdpdf, "tex_to_svg", side_effect=fake_svg):
            out = mdpdf.render_math(html, Path(tmp))

        self.assertIn('<span class="math math--inline" data-tex="x&lt;y"><svg data-tex="x<y" data-display="False">', out)
        self.assertIn('<span class="math math--display" data-tex="\\sum_i a_i"><svg data-tex="\\sum_i a_i" data-display="True">', out)
        self.assertNotIn("\\(", out)

    def test_failed_formula_falls_back_to_its_source(self) -> None:
        html = '<p><span class="math inline">\\(\\bad{x}\\)</span></p>'

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mdpdf, "tex_to_svg", side_effect=fake_svg):
            out = mdpdf.render_math(html, Path(tmp))

        self.assertIn('<code class="math math--error">\\bad{x}</code>', out)

    def test_failed_display_formula_keeps_its_own_line(self) -> None:
        html = '<p><span class="math display">\\[\\bad{x}\\]</span></p>'

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mdpdf, "tex_to_svg", side_effect=fake_svg):
            out = mdpdf.render_math(html, Path(tmp))

        self.assertIn('<code class="math math--display math--error">\\bad{x}</code>', out)

    def test_html_without_math_skips_the_renderer(self) -> None:
        with patch.object(mdpdf, "tex_to_svg") as renderer:
            out = mdpdf.render_math("<p>R$ 10</p>", Path("/nonexistent"))

        renderer.assert_not_called()
        self.assertEqual("<p>R$ 10</p>", out)

    def test_running_header_of_a_math_heading_keeps_the_formula_as_tex(self) -> None:
        html = '<h2 id="2-lei">2. A lei <span class="math inline">\\(E=mc^2\\)</span></h2>'

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mdpdf, "tex_to_svg", side_effect=fake_svg):
            out = mdpdf.rich_blocks(mdpdf.render_math(html, Path(tmp)), cfg())

        self.assertIn('data-section="2. A lei E=mc^2"', out)

    def test_unnumbered_heading_bookmark_keeps_the_formula_as_tex(self) -> None:
        html = '<h3 id="lei">A lei <span class="math inline">\\(E=mc^2\\)</span></h3>'

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(mdpdf, "tex_to_svg", side_effect=fake_svg):
            out = mdpdf.rich_blocks(mdpdf.render_math(html, Path(tmp)), cfg())

        self.assertIn('<h3 id="lei" data-bookmark="A lei E=mc^2">', out)
        css = (mdpdf.HOME / "base.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\[data-bookmark\]\s*\{[^}]*bookmark-label:\s*attr\(data-bookmark\)")

    def test_wide_display_math_is_capped_to_the_text_width(self) -> None:
        css = (mdpdf.HOME / "base.css").read_text(encoding="utf-8")

        self.assertRegex(css, r"\.math--display svg\s*\{[^}]*max-width:\s*100%")


class MathRendererFailureTests(unittest.TestCase):
    """The build never fails on math: every renderer failure falls back to TeX."""

    def run_with(self, outcome) -> tuple[list, str]:
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(err), \
                patch.object(mdpdf, "ensure_mathjax", return_value=Path(tmp) / "tex2svg.js"), \
                patch.object(mdpdf.subprocess, "run", side_effect=outcome):
            return mdpdf.tex_to_svg([("x", False)], Path(tmp)), err.getvalue()

    def test_node_timeout_falls_back(self) -> None:
        svgs, err = self.run_with(subprocess.TimeoutExpired(["node"], 1))
        self.assertEqual([None], svgs)
        self.assertIn("TeX source", err)

    def test_missing_node_binary_falls_back(self) -> None:
        svgs, _ = self.run_with(OSError("exec format error"))
        self.assertEqual([None], svgs)

    def test_garbled_renderer_output_falls_back(self) -> None:
        svgs, _ = self.run_with(lambda *a, **k: subprocess.CompletedProcess(a, 0, "not json", ""))
        self.assertEqual([None], svgs)

    def test_renderer_call_is_bounded_by_a_timeout(self) -> None:
        calls = []

        def ok(*a, **k):
            calls.append(k)
            return subprocess.CompletedProcess(a, 0, '["<svg></svg>"]', "")

        svgs, _ = self.run_with(ok)
        self.assertEqual(["<svg></svg>"], svgs)
        self.assertGreater(calls[0].get("timeout") or 0, 0)

    def test_corrupt_cached_svg_is_rendered_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            mdpdf.math_cache_path(cache, "x", False).write_text("garbage", encoding="utf-8")
            with patch.object(mdpdf, "ensure_mathjax", return_value=cache / "tex2svg.js"), \
                    patch.object(mdpdf.subprocess, "run",
                                 return_value=subprocess.CompletedProcess([], 0, '["<svg>ok</svg>"]', "")):
                svgs = mdpdf.tex_to_svg([("x", False)], cache)

        self.assertEqual(["<svg>ok</svg>"], svgs)

    def test_cache_key_changes_with_the_renderer_script(self) -> None:
        cache = Path("/c")
        before = mdpdf.math_cache_path(cache, "x", False)
        with patch.object(mdpdf, "MATHJAX_SCRIPT", mdpdf.MATHJAX_SCRIPT + "// v2"):
            after = mdpdf.math_cache_path(cache, "x", False)

        self.assertNotEqual(before, after)

    def test_npm_install_failure_shows_npm_error(self) -> None:
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(err), \
                patch.object(mdpdf, "MATHJAX_DIR", Path(tmp) / "mathjax"), \
                patch.object(mdpdf.shutil, "which", return_value="/usr/bin/x"), \
                patch.object(mdpdf.subprocess, "run",
                             return_value=subprocess.CompletedProcess([], 1, "", "npm ERR! E404 boom")):
            self.assertIsNone(mdpdf.ensure_mathjax())

        self.assertIn("E404 boom", err.getvalue())


@unittest.skipUnless(
    shutil.which("node") and (mdpdf.MATHJAX_DIR / "node_modules" / "mathjax-full").exists(),
    "MathJax not installed in the cache",
)
class MathJaxEndToEndTests(unittest.TestCase):
    def test_real_mathjax_renders_svg_and_reports_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svgs = mdpdf.tex_to_svg([("\\frac{a}{b}", False), ("\\frac{", True)], Path(tmp))

        self.assertTrue(svgs[0].startswith("<svg"))
        self.assertIn("viewBox", svgs[0])
        self.assertIsNone(svgs[1])


if __name__ == "__main__":
    unittest.main()
