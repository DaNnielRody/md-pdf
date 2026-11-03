"""Clickable Mermaid nodes: link map capture and placement over the printed image."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mdpdf
from weasyprint import HTML

CLICK_SOURCE = (
    "flowchart TD\n"
    "  A[Envio] --> B[Recepção]\n"
    '  click A href "#envio"\n'
    '  click B href "#recep%C3%A7%C3%A3o"\n'
)
# A tall diagram: on a diagram page it is height-limited, so `object-fit:
# contain` letterboxes it horizontally — the case naive percentages get wrong.
TALL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 800" width="200" height="800">'
    '<rect x="50" y="100" width="100" height="100" fill="#ccc"/></svg>'
)
MAP = [{"href": "#envio", "x": 0.25, "y": 0.125, "w": 0.5, "h": 0.125},
       {"href": "#recep%C3%A7%C3%A3o", "x": 0.25, "y": 0.5, "w": 0.5, "h": 0.125}]


def plain_cfg() -> dict:
    return mdpdf.merge(mdpdf.DEFAULTS, mdpdf.load_toml(mdpdf.THEMES / "plain" / "theme.toml"))


def cached_svg(cache: Path, cfg: dict, source: str, index: int = 1) -> Path:
    fingerprint = json.dumps(mdpdf.mermaid_theme(cfg), sort_keys=True)
    digest = hashlib.sha1((source + fingerprint).encode("utf-8")).hexdigest()[:12]
    svg = cache / f"diagram-{index}-{digest}.svg"
    svg.write_text(TALL_SVG, encoding="utf-8")
    return svg


class HotspotCaptureTests(unittest.TestCase):
    def test_clickable_nodes_become_hidden_anchors_with_their_boxes(self) -> None:
        cfg = plain_cfg()
        md = "## 1. Fluxo\n\n```mermaid\n" + CLICK_SOURCE + "```\n"
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cached_svg(cache, cfg, CLICK_SOURCE)
            with patch("mdpdf.subprocess.run", side_effect=AssertionError("no mmdc")), \
                 patch("mdpdf.measure_svg_links", return_value=MAP) as measure:
                rendered = mdpdf.render_mermaid(md, cfg, mdpdf.THEMES / "plain", cache)
                again = mdpdf.render_mermaid(md, cfg, mdpdf.THEMES / "plain", cache)

        measure.assert_called_once()  # the map is cached next to the SVG
        self.assertEqual(rendered, again)
        self.assertIn('id="figura-1" data-ratio="0.25"', rendered)
        self.assertIn(
            '<a class="diagram-hotspot" href="#envio" data-box="0.25 0.125 0.5 0.125"></a>',
            rendered,
        )
        self.assertIn('href="#recepção"', rendered)

    def test_diagram_without_click_never_measures(self) -> None:
        cfg = plain_cfg()
        source = "flowchart TD\n  A --> B\n"
        md = "```mermaid\n" + source + "```\n"
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            cached_svg(cache, cfg, source)
            with patch("mdpdf.measure_svg_links", side_effect=AssertionError("no measure")):
                rendered = mdpdf.render_mermaid(md, cfg, mdpdf.THEMES / "plain", cache)

        self.assertIn('id="figura-1"', rendered)
        self.assertNotIn("diagram-hotspot", rendered)


class HotspotPlacementTests(unittest.TestCase):
    def _document(self, cache: Path) -> str:
        cfg = plain_cfg()
        css = mdpdf.build_stylesheet(cfg, mdpdf.THEMES / "plain", cache)
        svg = cache / "tall.svg"
        svg.write_text(TALL_SVG, encoding="utf-8")
        anchors = "".join(
            f'<a class="diagram-hotspot" href="{m["href"]}" '
            f'data-box="{m["x"]} {m["y"]} {m["w"]} {m["h"]}"></a>'
            for m in [MAP[0], {**MAP[1], "href": "#recepção"}]
        )
        body = mdpdf.postprocess(
            '<h2 id="fluxo">1. Fluxo</h2>'
            f'<figure class="figure--diagram diagram-page" id="figura-1" data-ratio="0.25">'
            f'<img src="{svg.as_uri()}" alt="">{anchors}'
            "<figcaption>Figura 1 — Fluxo</figcaption></figure>"
            '<h2 id="detalhe">2. Detalhe</h2><h3 id="envio">Envio</h3><p>a</p>'
            '<h3 id="recepção">Recepção</h3><p>b</p>',
            cfg,
        )
        return mdpdf.compose("Doc", "", body, [], cfg, css)

    def test_links_cover_the_drawn_node_not_the_letterboxed_box(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            html = mdpdf.place_diagram_hotspots(self._document(cache), cache.as_uri() + "/")
            doc = HTML(string=html, base_url=cache.as_uri() + "/").render()

            images = []

            def walk(box):
                if getattr(box, "element_tag", None) == "img":
                    images.append(box)
                for child in getattr(box, "children", []):
                    walk(child)

            page = doc.pages[0]
            walk(page._page_box)
            img = images[0]
            # contain-fit: drawn width = box height × (200 / 800), centred.
            drawn_w = img.height * 0.25
            drawn_x = img.content_box_x() + (img.width - drawn_w) / 2
            links = {link[1]: link[2] for link in page.links if link[0] == "internal"}

        self.assertIn("envio", links)
        self.assertIn("recepção", links)
        x0, y0, x1, y1 = links["envio"]
        self.assertAlmostEqual(drawn_x + 0.25 * drawn_w, x0, delta=1.0)
        self.assertAlmostEqual(drawn_x + 0.75 * drawn_w, x1, delta=1.0)
        self.assertAlmostEqual(img.content_box_y() + 0.125 * img.height, y0, delta=1.0)
        self.assertAlmostEqual(img.content_box_y() + 0.25 * img.height, y1, delta=1.0)

    def test_placement_keeps_the_page_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            html = self._document(cache)
            placed = mdpdf.place_diagram_hotspots(html, cache.as_uri() + "/")
            before = HTML(string=html, base_url=cache.as_uri() + "/").render()
            after = HTML(string=placed, base_url=cache.as_uri() + "/").render()
        self.assertEqual(len(before.pages), len(after.pages))

    def test_document_without_hotspots_is_returned_unchanged(self) -> None:
        html = "<html><body><p>x</p></body></html>"
        with patch("weasyprint.HTML", side_effect=AssertionError("no layout pass")):
            self.assertIs(html, mdpdf.place_diagram_hotspots(html, "file:///"))


if __name__ == "__main__":
    unittest.main()
