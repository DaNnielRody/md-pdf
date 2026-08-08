"""Regression contracts for headings adjacent to Mermaid diagram figures."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import mdpdf
from weasyprint import HTML


class MermaidLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = mdpdf.DEFAULTS

    def test_marks_direct_diagram_heading_preserving_attributes_and_whitespace(self) -> None:
        html = (
            '<h2 id="event-loop" class="section-title">4. Event loop</h2>\n \t\n'
            '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertRegex(
            rendered,
            r'<h2(?=[^>]*\bid="event-loop")'
            r'(?=[^>]*\bclass="[^"]*\bsection-title\b[^"]*\bheading--diagram\b[^"]*")[^>]*>',
        )

    def test_direct_diagram_heading_marking_is_idempotent(self) -> None:
        html = (
            '<h2 id="event-loop" class="section-title">4. Event loop</h2>\n\n'
            '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        once = mdpdf.postprocess(html, self.cfg)
        twice = mdpdf.postprocess(once, self.cfg)

        self.assertEqual(once, twice)
        self.assertEqual(1, twice.count("heading--diagram"))

    def test_marks_only_second_heading_when_prose_precedes_its_direct_diagram(self) -> None:
        html = (
            '<h2 id="antes">1. Antes</h2><p>Texto desta seção.</p>'
            '<h2 id="diagrama">2. Diagrama</h2>\n'
            '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        rendered = mdpdf.postprocess(html, self.cfg)
        headings = re.findall(r"<h2\b[^>]*>", rendered)

        self.assertEqual(2, len(headings))
        self.assertNotIn("heading--diagram", headings[0])
        self.assertIn("heading--diagram", headings[1])

    def test_preserves_single_quoted_classes_in_any_attribute_order(self) -> None:
        html = (
            "<h2 class='section-title' data-kind=\"chapter\" id='event-loop'>4. Event loop</h2>"
            "<figure id='diagram' class='diagram-page figure--diagram'><img src='diagram.svg'></figure>"
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn("class='section-title heading--diagram'", rendered)
        self.assertIn("data-kind=\"chapter\" id='event-loop'", rendered)
        self.assertEqual(rendered, mdpdf.postprocess(rendered, self.cfg))

    def test_heading_data_class_is_preserved_when_a_real_class_is_added(self) -> None:
        html = (
            '<h2 id="event-loop" data-class="keep-this">4. Event loop</h2>'
            '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn('data-class="keep-this"', rendered)
        self.assertIn('class="heading--diagram"', rendered)

    def test_data_class_on_figure_is_not_a_mermaid_class(self) -> None:
        html = (
            '<h2 id="event-loop">4. Event loop</h2>'
            '<figure data-class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        self.assertNotIn("heading--diagram", mdpdf.postprocess(html, self.cfg))

    def test_real_class_after_data_class_is_the_only_class_modified(self) -> None:
        html = (
            '<h2 data-class="keep-this" class="section-title" id="event-loop">4. Event loop</h2>'
            '<figure data-class="ignore" class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn('data-class="keep-this"', rendered)
        self.assertIn('class="section-title heading--diagram"', rendered)
        self.assertIn('data-class="ignore" class="figure--diagram diagram-page"', rendered)

    def test_does_not_mark_heading_with_intermediate_node_or_non_diagram_figure(self) -> None:
        cases = (
            (
                '<h2 id="prose">4. Prose</h2><p>Texto entre os elementos.</p>'
                '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
            ),
            (
                '<h2 id="image">4. Image</h2>'
                '<figure class="figure"><img src="photo.png"></figure>'
            ),
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertNotIn("heading--diagram", mdpdf.postprocess(html, self.cfg))

    def test_marks_colon_lead_in_directly_adjacent_to_mermaid_figure(self) -> None:
        html = (
            '<p id="lead" data-class="keep" class="intro">Diagrama (<em>corrida</em>):</p>\n'
            '<figure class="figure--diagram diagram-page"><img src="diagram.svg"></figure>'
        )

        rendered = mdpdf.postprocess(html, self.cfg)

        self.assertIn('data-class="keep"', rendered)
        self.assertIn('class="intro diagram-lead"', rendered)
        self.assertEqual(rendered, mdpdf.postprocess(rendered, self.cfg))

    def test_does_not_mark_ordinary_prose_or_non_mermaid_figure_as_lead_in(self) -> None:
        cases = (
            '<p>Prosa comum antes da figura.</p>'
            '<figure class="figure--diagram diagram-page"></figure>',
            '<p>Legenda introdutória:</p><figure class="figure"></figure>',
            '<p>Legenda introdutória:</p><span>intermediário</span>'
            '<figure class="figure--diagram diagram-page"></figure>',
        )

        for html in cases:
            with self.subTest(html=html):
                self.assertNotIn("diagram-lead", mdpdf.postprocess(html, self.cfg))

    def test_colon_lead_in_and_caption_render_on_the_same_pdf_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            svg = work / "diagram.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240">'
                '<text x="20" y="80">CONTEUDO-DO-DIAGRAMA</text></svg>',
                encoding="utf-8",
            )
            cfg, theme_dir = mdpdf.build_config(work / "fixture.md", "cobalt")
            css = mdpdf.build_stylesheet(cfg, theme_dir, work)
            body = mdpdf.postprocess(
                '<h2 id="secao">1. Seção</h2><p>Texto anterior.</p>'
                '<p>Diagrama (este texto precisa acompanhar a figura):</p>'
                f'<figure class="figure--diagram diagram-page"><img src="{svg.as_uri()}">'
                '<figcaption>Figura 1 — Seção</figcaption></figure><p>Texto posterior.</p>',
                cfg,
            )
            html = (
                '<!doctype html><html><head><meta charset="utf-8">'
                f'<link rel="stylesheet" href="{css.as_uri()}"></head><body>{body}</body></html>'
            )
            pdf = work / "fixture.pdf"
            document = HTML(string=html, base_url=str(work)).render()
            document.write_pdf(pdf)

            lead_page = self._page_containing(pdf, "este texto precisa")
            figure_page = self._page_containing(pdf, "Figura 1")
            following_page = self._page_containing(pdf, "Texto posterior")

            self.assertEqual(figure_page, lead_page)
            self.assertLess(
                document.pages[lead_page - 1].width,
                document.pages[lead_page - 1].height,
            )
            self.assertLess(
                document.pages[following_page - 1].width,
                document.pages[following_page - 1].height,
            )

    def test_base_css_keeps_diagram_pages_in_the_standard_portrait_format(self) -> None:
        css = (mdpdf.HOME / "base.css").read_text(encoding="utf-8")

        heading = self._rule(css, "h2.heading--diagram")
        diagram = self._rule(css, ".diagram-page")
        diagram_image = self._rule(css, "figure.figure--diagram img")
        sibling = self._rule(css, "h2.heading--diagram + .diagram-page")
        image = self._rule(css, "h2.heading--diagram + .diagram-page img")
        lead = self._rule(css, "p.diagram-lead")
        lead_sibling = self._rule(css, "p.diagram-lead + .diagram-page")
        lead_image = self._rule(css, "p.diagram-lead + .diagram-page img")
        diagram_page = self._at_page_rule(css, "diagram")
        top_left = self._rule(diagram_page, "@top-left")
        top_right = self._rule(diagram_page, "@top-right")

        self.assertRegex(heading, r"\bpage\s*:\s*diagram\s*;")
        self.assertRegex(sibling, r"\bbreak-before\s*:\s*auto\s*;")
        self.assertEqual(253, self._millimetres(diagram, "height"))
        self.assertEqual(237, self._millimetres(diagram_image, "max-height"))
        self.assertEqual(220, self._millimetres(sibling, "height"))
        self.assertEqual(204, self._millimetres(image, "max-height"))
        self.assertRegex(lead, r"\bpage\s*:\s*diagram\s*;")
        self.assertRegex(lead_sibling, r"\bbreak-before\s*:\s*auto\s*;")
        self.assertEqual(238, self._millimetres(lead_sibling, "height"))
        self.assertEqual(222, self._millimetres(lead_image, "max-height"))
        self.assertEqual(88, self._millimetres(top_left, "width"))
        self.assertEqual(82, self._millimetres(top_right, "width"))
        self.assertEqual(
            170,
            self._millimetres(top_left, "width") + self._millimetres(top_right, "width"),
        )
        self.assertRegex(diagram_page, r"\bsize\s*:\s*A4\s*;")
        self.assertNotRegex(diagram_page, r"\blandscape\b")

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
