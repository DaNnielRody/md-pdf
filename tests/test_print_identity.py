"""Styles a theme's identity and legibility depend on, read from real WeasyPrint layout."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import mdpdf
from weasyprint import HTML


def layout(body: str, theme: str = "cobalt") -> dict[str, list]:
    cfg = mdpdf.merge(mdpdf.DEFAULTS, mdpdf.load_toml(mdpdf.THEMES / theme / "theme.toml"))
    with tempfile.TemporaryDirectory() as tmp:
        css = mdpdf.build_stylesheet(cfg, mdpdf.THEMES / theme, Path(tmp))
        html = mdpdf.compose("Doc", "", mdpdf.postprocess(body, cfg), [], cfg, css)
        doc = HTML(string=html, base_url=Path(tmp).as_uri() + "/").render()
    found: dict[str, list] = {}

    def walk(box, parents=()):
        tag = getattr(box, "element_tag", None)
        if tag:
            key = "/".join([*parents[-1:], tag])
            found.setdefault(key, []).append(box)
            parents = (*parents, tag)
        for child in getattr(box, "children", []):
            walk(child, parents)

    for page in doc.pages:
        walk(page._page_box)
    return found


def rgba(color) -> tuple:
    return tuple(round(c, 3) for c in color)


def hex_rgba(value: str) -> tuple:
    value = value.lstrip("#")
    return tuple(round(int(value[i:i + 2], 16) / 255, 3) for i in (0, 2, 4)) + (1.0,)


COBALT = mdpdf.load_toml(mdpdf.THEMES / "cobalt" / "theme.toml")["colors"]
TABLE = (
    "<table><thead><tr><th>Região</th><th><code>eastus</code></th></tr></thead>"
    "<tbody><tr><td>a</td><td><code>vm-01</code></td></tr>"
    "<tr><td>b</td><td><code>vm-02</code></td></tr></tbody></table>"
)


class TableIdentityTests(unittest.TestCase):
    def test_header_keeps_the_theme_accent_fill(self) -> None:
        th = layout(TABLE)["tr/th"][0]
        self.assertEqual(hex_rgba(COBALT["accent"]), rgba(th.style["background_color"]))

    def test_alternate_rows_keep_their_tint(self) -> None:
        cells = layout(TABLE)["tr/td"]
        self.assertEqual(hex_rgba(COBALT["paper-alt"]), rgba(cells[2].style["background_color"]))

    def test_code_in_header_uses_the_header_ink_on_a_translucent_box(self) -> None:
        boxes = layout(TABLE)
        th = boxes["tr/th"][1]
        code = boxes["th/code"][0]
        self.assertEqual(rgba(th.style["color"]), rgba(code.style["color"]))
        self.assertLess(code.style["background_color"][3], 0.5)

    def test_code_only_body_cell_keeps_the_code_box(self) -> None:
        code = layout(TABLE)["td/code"][0]
        self.assertEqual(hex_rgba(COBALT["paper-alt"]), rgba(code.style["background_color"]))


class SectionTitleIdentityTests(unittest.TestCase):
    def test_numbered_title_and_its_rule_use_the_theme_accent(self) -> None:
        h2 = layout('<h2 id="x">3. Resultados</h2><p>t</p>')["body/h2"][0]
        self.assertEqual(hex_rgba(COBALT["accent"]), rgba(h2.style["color"]))
        self.assertEqual(hex_rgba(COBALT["accent"]), rgba(h2.style["border_top_color"]))


class BlockLabelLegibilityTests(unittest.TestCase):
    def test_small_labels_are_at_least_eight_points(self) -> None:
        boxes = layout(
            '<div class="note"><div class="title"><p>Note</p></div><p>x</p></div>'
            '<div class="stats"><ul><li><strong>3</strong> pontos</li></ul></div>'
        )
        eight_points = 8 * 96 / 72
        seen = set()
        for key in ("div/p", "div/span"):
            for box in boxes.get(key, []):
                classes = box.element.get("class") or ""
                if classes in ("alert__title", "stat__label"):
                    seen.add(classes)
                    self.assertGreaterEqual(box.style["font_size"], eight_points - 0.01, classes)
        self.assertEqual({"alert__title", "stat__label"}, seen)


if __name__ == "__main__":
    unittest.main()
