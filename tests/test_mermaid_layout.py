"""Regression contracts for the page a Mermaid diagram shares with its text."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import mdpdf
from weasyprint import HTML

FIGURE = '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'


class MermaidLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = mdpdf.DEFAULTS

    def test_groups_the_directly_adjacent_heading_with_its_diagram(self) -> None:
        html = (
            '<h2 id="event-loop" class="section-title">4. Event loop</h2>\n \t\n' + FIGURE
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertRegex(
            rendered,
            r'<div class="diagram-block"><div class="diagram-block__lead">'
            r'<h2 id="event-loop" class="section-title">4\. Event loop</h2>\s*</div>'
            r'<figure class="figure--diagram diagram-page">.*?</figure></div>',
        )

    def test_groups_the_whole_run_of_headings_and_the_lead_in(self) -> None:
        html = (
            '<h2 id="parte">4. Parte 3</h2>\n<h3 id="cadeia">4.1 Cadeia</h3>\n'
            "<p>A corrente de prompts:</p>\n" + FIGURE
        )

        rendered = mdpdf.postprocess(html, self.cfg)
        block = self._block(rendered)

        self.assertIn("4. Parte 3", block)
        self.assertIn("4.1 Cadeia", block)
        self.assertIn('class="diagram-lead"', block)
        self.assertEqual(1, rendered.count('<div class="diagram-block">'))

    def test_grouping_is_idempotent(self) -> None:
        html = (
            '<h2 id="event-loop">4. Event loop</h2>\n\n'
            "<p>O diagrama seguinte:</p>\n" + FIGURE
        )

        once = mdpdf.postprocess(html, self.cfg)
        twice = mdpdf.postprocess(once, self.cfg)

        self.assertEqual(once, twice)
        self.assertEqual(1, twice.count('<div class="diagram-block">'))

    def test_a_few_lines_of_prose_travel_with_the_diagram(self) -> None:
        html = (
            '<h2 id="laco">4. O laço de controle</h2>'
            "<p>O desenho abaixo isola o laço da topologia da figura 1.</p>" + FIGURE
        )

        block = self._block(mdpdf.postprocess(html, self.cfg))

        self.assertIn("4. O laço de controle", block)
        self.assertIn("isola o laço", block)

    def test_prose_above_the_headings_stays_with_the_section_that_ended(self) -> None:
        html = (
            "<p>Fecho da secção anterior.</p>"
            '<h3 id="atual">1.1 O estado atual</h3>'
            "<p>O diagrama seguinte:</p>" + FIGURE
        )

        block = self._block(mdpdf.postprocess(html, self.cfg))

        self.assertNotIn("Fecho da secção anterior", block)
        self.assertIn("1.1 O estado atual", block)
        self.assertIn("O diagrama seguinte", block)

    def test_long_prose_and_what_precedes_it_stay_off_the_diagram_page(self) -> None:
        prose = "Texto longo desta seção. " * 30
        html = (
            f'<h2 id="antes">1. Antes</h2><p>{prose}</p>'
            '<h2 id="diagrama">2. Diagrama</h2>\n' + FIGURE
        )

        rendered = mdpdf.postprocess(html, self.cfg)
        block = self._block(rendered)

        self.assertNotIn("1. Antes", block)
        self.assertNotIn("Texto longo", block)
        self.assertIn("2. Diagrama", block)
        self.assertIn("1. Antes", rendered)
        self.assertIn("Texto longo", rendered)

    def test_the_prose_budget_is_configurable(self) -> None:
        html = "<p>Texto desta seção.</p>" + FIGURE

        strict = mdpdf.postprocess(html, {**self.cfg, "diagram_lead_chars": 0})

        self.assertNotIn("Texto desta seção", self._block(strict))
        self.assertIn("Texto desta seção", self._block(mdpdf.postprocess(html, self.cfg)))

    def test_leaves_ordinary_figures_ungrouped(self) -> None:
        cases = (
            '<h2 id="image">4. Image</h2><figure class="figure"><img src="photo.png"></figure>',
            '<h2 id="event-loop">4. Event loop</h2>'
            '<figure data-class="figure--diagram diagram-page"><img src="diagram.svg"></figure>',
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertNotIn("diagram-block", mdpdf.postprocess(html, self.cfg))

    def test_preserves_single_quoted_classes_in_any_attribute_order(self) -> None:
        html = (
            "<h2 class='section-title' data-kind=\"chapter\" id='event-loop'>4. Event loop</h2>"
            "<p data-class='keep'>Diagrama:</p>"
            "<figure id='diagram' class='diagram-page figure--diagram'><img src='diagram.svg'></figure>"
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn("data-kind=\"chapter\" id='event-loop'", rendered)
        self.assertIn("data-class='keep' class=\"diagram-lead\"", rendered)
        self.assertEqual(rendered, mdpdf.postprocess(rendered, self.cfg))

    def test_marks_colon_lead_in_directly_adjacent_to_mermaid_figure(self) -> None:
        html = (
            '<p id="lead" data-class="keep" class="intro">Diagrama (<em>corrida</em>):</p>\n'
            + FIGURE
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn('data-class="keep"', rendered)
        self.assertIn('class="intro diagram-lead"', rendered)
        self.assertEqual(rendered, mdpdf.postprocess(rendered, self.cfg))

    def test_does_not_mark_ordinary_prose_or_non_mermaid_figure_as_lead_in(self) -> None:
        cases = (
            "<p>Prosa comum antes da figura.</p>"
            '<figure class="figure--diagram diagram-page"></figure>',
            '<p>Legenda introdutória:</p><figure class="figure"></figure>',
            '<p>Legenda introdutória:</p><span>intermediário</span>'
            '<figure class="figure--diagram diagram-page"></figure>',
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertNotIn("diagram-lead", mdpdf.postprocess(html, self.cfg))

    def test_heading_lead_in_and_caption_render_on_the_same_pdf_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            svg = work / "diagram.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="1400">'
                '<text x="20" y="80">CONTEUDO-DO-DIAGRAMA</text></svg>',
                encoding="utf-8",
            )
            cfg, theme_dir = mdpdf.build_config(work / "fixture.md", "cobalt")
            css = mdpdf.build_stylesheet(cfg, theme_dir, work)
            body = mdpdf.postprocess(
                '<h2 id="secao">1. Seção</h2><p>Texto anterior.</p>'
                '<h2 id="parte">2. Parte</h2><h3 id="sub">2.1 Subsecção</h3>'
                "<p>Diagrama (este texto precisa acompanhar a figura):</p>"
                f'<figure class="figure--diagram diagram-page"><img src="{svg.as_uri()}">'
                "<figcaption>Figura 1 — Seção</figcaption></figure><p>Texto posterior.</p>",
                cfg,
            )
            html = (
                '<!doctype html><html><head><meta charset="utf-8">'
                f'<link rel="stylesheet" href="{css.as_uri()}"></head><body>{body}</body></html>'
            )
            pdf = work / "fixture.pdf"
            document = HTML(string=html, base_url=str(work)).render()
            document.write_pdf(pdf)

            heading_page = self._page_containing(pdf, "2.1 Subsecção")
            lead_page = self._page_containing(pdf, "este texto precisa")
            figure_page = self._page_containing(pdf, "Figura 1")
            following_page = self._page_containing(pdf, "Texto posterior")

            self.assertEqual(figure_page, heading_page)
            self.assertEqual(figure_page, lead_page)
            self.assertEqual(figure_page + 1, following_page)
            self.assertLess(
                document.pages[figure_page - 1].width,
                document.pages[figure_page - 1].height,
            )

    def test_base_css_keeps_diagram_pages_in_the_standard_portrait_format(self) -> None:
        css = (mdpdf.HOME / "base.css").read_text(encoding="utf-8")

        block = self._rule(css, ".diagram-block")
        figure = self._rule(css, ".diagram-page")
        image = self._rule(css, "figure.figure--diagram img")
        lead = self._rule(css, "p.diagram-lead")
        diagram_page = self._at_page_rule(css, "diagram")
        top_left = self._rule(diagram_page, "@top-left")
        top_right = self._rule(diagram_page, "@top-right")

        self.assertRegex(block, r"\bpage\s*:\s*diagram\s*;")
        self.assertRegex(block, r"\bbreak-before\s*:\s*page\s*;")
        self.assertRegex(block, r"\bbreak-after\s*:\s*page\s*;")
        self.assertRegex(block, r"\bdisplay\s*:\s*grid\s*;")
        self.assertRegex(block, r"\bgrid-template-rows\s*:\s*auto\s+1fr\s*;")
        self.assertEqual(253, self._millimetres(block, "height"))
        self.assertRegex(figure, r"\bheight\s*:\s*100%\s*;")
        self.assertRegex(figure, r"\bbox-sizing\s*:\s*border-box\s*;")
        self.assertEqual(9, self._millimetres(figure, "padding-bottom"))
        self.assertRegex(image, r"\bmax-height\s*:\s*100%\s*;")
        self.assertRegex(lead, r"\bbreak-after\s*:\s*avoid\s*;")
        self.assertEqual(88, self._millimetres(top_left, "width"))
        self.assertEqual(82, self._millimetres(top_right, "width"))
        self.assertEqual(
            170,
            self._millimetres(top_left, "width") + self._millimetres(top_right, "width"),
        )
        self.assertRegex(diagram_page, r"\bsize\s*:\s*A4\s*;")
        self.assertNotRegex(diagram_page, r"\blandscape\b")

    @staticmethod
    def _block(html: str) -> str:
        match = re.search(r'<div class="diagram-block">[\s\S]*?</figure></div>', html)
        if not match:
            raise AssertionError(f"no diagram block in {html!r}")
        return match.group(0)

    @staticmethod
    def _rule(css: str, selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\}}", css, re.S)
        if not match:
            raise AssertionError(f"missing CSS rule for {selector}")
        return match.group("body")

    @staticmethod
    def _at_page_rule(css: str, name: str) -> str:
        match = re.search(rf"@page\s+{re.escape(name)}\s*\{{", css)
        if not match:
            raise AssertionError(f"missing @page rule for {name}")

        depth = 1
        for position, character in enumerate(css[match.end():], start=match.end()):
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return css[match.end():position]
        raise AssertionError(f"unterminated @page rule for {name}")

    @staticmethod
    def _millimetres(rule: str, property_name: str) -> float:
        match = re.search(rf"\b{re.escape(property_name)}\s*:\s*(\d+(?:\.\d+)?)mm\s*;", rule)
        if not match:
            raise AssertionError(f"missing {property_name} in CSS rule")
        return float(match.group(1))

    @staticmethod
    def _page_containing(pdf: Path, needle: str) -> int:
        pages = subprocess.run(
            ["pdfinfo", str(pdf)], check=True, capture_output=True, text=True
        ).stdout
        count = int(re.search(r"^Pages:\s+(\d+)$", pages, re.M).group(1))
        for page in range(1, count + 1):
            text = subprocess.run(
                ["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            if needle in text:
                return page
        raise AssertionError(f"{needle!r} not found in {pdf}")


if __name__ == "__main__":
    unittest.main()
