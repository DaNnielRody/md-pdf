"""Contracts for the block vocabulary layered on top of plain Markdown.

Each test drives the real Markdown → HTML path (preprocess, pandoc,
postprocess), because the syntax is only meaningful once pandoc has parsed it.
"""

from __future__ import annotations

import re
import unittest

import mdpdf


def build(md: str, **overrides) -> str:
    cfg = mdpdf.merge(mdpdf.DEFAULTS, overrides)
    return mdpdf.postprocess(
        mdpdf.markdown_to_html(mdpdf.preprocess_markdown(md, cfg)), cfg
    )


class SectionEyebrowTests(unittest.TestCase):
    def test_numbered_h2_gets_padded_number_and_keeps_full_title_for_header(self) -> None:
        html = build("## 3. Onde entra o LLM\n\nTexto.\n")

        h2 = re.search(r"<h2\b[^>]*>.*?</h2>", html, re.S).group(0)
        self.assertIn('class="section--numbered"', h2)
        self.assertIn('data-section="3. Onde entra o LLM"', h2)
        self.assertIn('<span class="section-num">03</span>', h2)
        self.assertNotIn("3. Onde", re.sub(r"<[^>]+>", "", h2).replace("03", "", 1))

    def test_unnumbered_h2_is_left_alone(self) -> None:
        html = build("## Sumário\n\n1. [A](#a)\n")
        self.assertNotIn("section--numbered", html)

    def test_number_only_counts_the_leading_integer(self) -> None:
        html = build("## 12 Apêndice\n")
        self.assertIn('<span class="section-num">12</span>', html)


class AlertTests(unittest.TestCase):
    def test_gfm_alert_becomes_labelled_callout_in_document_language(self) -> None:
        html = build("> [!WARNING]\n> Divergência bloqueia as regras.\n")

        self.assertIn('<div class="alert alert--warning">', html)
        self.assertIn('<p class="alert__title">Atenção</p>', html)
        self.assertIn("<p>Divergência bloqueia as regras.</p>", html)
        self.assertNotIn('class="title"', html)

    def test_custom_title_replaces_the_default_label(self) -> None:
        html = build("> [!NOTE] No ADS-24-0090\n> Se os dois métodos discordarem.\n")

        self.assertIn('<p class="alert__title">No ADS-24-0090</p>', html)
        self.assertIn("<p>Se os dois métodos discordarem.</p>", html)
        self.assertNotIn("alert-title", html)

    def test_labels_are_configurable(self) -> None:
        html = build("> [!TIP]\n> x\n", alert_labels={"tip": "Tip"})
        self.assertIn('<p class="alert__title">Tip</p>', html)

    def test_alert_syntax_inside_code_fence_stays_literal(self) -> None:
        html = build("```\n> [!NOTE] Título\n```\n")
        self.assertIn("[!NOTE] Título", html)
        self.assertNotIn("alert", html)

    def test_plain_blockquote_is_untouched(self) -> None:
        html = build("> Só uma citação.\n")
        self.assertIn("<blockquote>", html)
        self.assertNotIn("alert", html)


class ContainerTests(unittest.TestCase):
    def test_cards_split_on_h3_and_pick_column_count(self) -> None:
        html = build(
            "::: cards\n"
            "### Código\nMesma entrada.\n\n"
            "### IA\nLinguagem livre.\n\n"
            "### Pessoas\nDecidem.\n"
            ":::\n"
        )

        self.assertIn('<div class="cards cards--3">', html)
        self.assertEqual(3, html.count('<div class="card">'))
        self.assertRegex(html, r'<div class="card"><h3 id="código">Código</h3>')

    def test_four_cards_wrap_two_by_two(self) -> None:
        html = build(
            "::: cards\n" + "".join(f"### C{i}\nx\n\n" for i in range(4)) + ":::\n"
        )
        self.assertIn('<div class="cards cards--2">', html)

    def test_h5_before_card_title_is_its_eyebrow(self) -> None:
        html = build("::: cards\n##### 1 · catálogo\n### O que verificar\nTexto.\n:::\n")
        self.assertIn('<p class="card__eyebrow">1 · catálogo</p><h3', html)

    def test_compare_renders_two_panels(self) -> None:
        html = build(
            "::: compare\n### Entra\n- a\n\n### Não entra\n- b\n:::\n"
        )
        self.assertIn('<div class="cards cards--2 cards--compare">', html)
        self.assertEqual(2, html.count('<div class="card">'))

    def test_bold_label_list_inside_card_becomes_field_rows(self) -> None:
        html = build(
            "::: cards\n### Etapa\n- **Entra:** Páginas\n- **Sai:** Células\n:::\n"
        )
        self.assertIn('<ul class="fields">', html)
        self.assertIn(
            '<li><span class="fields__label">Entra</span>'
            '<span class="fields__value">Páginas</span></li>',
            html,
        )

    def test_stats_strip_puts_label_above_value(self) -> None:
        html = build(
            "::: stats\n- **3** pontos fixos\n- **2** pontos opcionais\n- **0** gravações\n:::\n"
        )

        self.assertIn('<div class="stats stats--3">', html)
        self.assertIn(
            '<div class="stat"><span class="stat__label">pontos fixos</span>'
            '<span class="stat__value">3</span></div>',
            html,
        )
        self.assertNotIn("<ul>", html)

    def test_unknown_div_class_is_left_alone(self) -> None:
        html = build("::: aside\nTexto.\n:::\n")
        self.assertIn('<div class="aside">', html)


class StepTests(unittest.TestCase):
    MD = (
        '<figure class="figure--diagram diagram-page" id="figura-1"><img src="x.svg"></figure>\n\n'
        "::: steps\n"
        "##### Pessoas | Sem LLM\n"
        "### Envio autorizado\nUma pessoa envia.\n\n"
        "### Recepção\nRegistra.\n\n"
        "### Classificação\nClassifica.\n"
        ":::\n"
    )

    def test_each_step_has_working_neighbour_links_and_no_dead_controls(self) -> None:
        html = build(self.MD)
        steps = re.findall(r'<article class="step"[\s\S]*?</article>', html)
        self.assertEqual(3, len(steps))

        first, middle, last = steps
        self.assertNotIn("step__prev", first)
        self.assertIn('<a class="step__next" href="#recepção">Próxima ▶</a>', first)
        self.assertIn('<a class="step__prev" href="#envio-autorizado">◀ Anterior</a>', middle)
        self.assertIn('<a class="step__next" href="#classificação">Próxima ▶</a>', middle)
        self.assertNotIn("step__next", last)
        self.assertIn('<span class="step__count">2 de 3</span>', middle)

    def test_step_links_back_to_the_diagram_above(self) -> None:
        html = build(self.MD)
        self.assertEqual(3, html.count('<a class="step__back" href="#figura-1">↑ Voltar ao diagrama</a>'))

    def test_every_step_target_exists(self) -> None:
        html = build(self.MD)
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for target in re.findall(r'class="step__(?:prev|next|back)" href="#([^"]+)"', html):
            self.assertIn(target, ids)

    def test_eyebrow_splits_category_and_badge(self) -> None:
        html = build(self.MD)
        self.assertIn(
            '<p class="step__eyebrow"><span>Pessoas</span>'
            '<span class="step__badge">Sem LLM</span></p>',
            html,
        )

    def test_steps_without_a_diagram_omit_the_back_link(self) -> None:
        html = build("::: steps\n### A\nx\n\n### B\ny\n:::\n")
        self.assertNotIn("step__back", html)


class TableAndCodeTests(unittest.TestCase):
    def test_numeric_column_is_marked_on_header_and_cells(self) -> None:
        html = build(
            "| Regra | Valor |\n|---|---|\n| QTD-01a | 13.537,30 |\n| VLR-01 | R$ 2.559,94 |\n"
            "| PCT-01 | 73,93% |\n"
        )
        self.assertIn('<th class="num">Valor</th>', html)
        self.assertEqual(3, html.count('<td class="num">'))
        self.assertIn("<th>Regra</th>", html)

    def test_mixed_text_column_is_not_numeric(self) -> None:
        html = build("| A |\n|---|\n| 12 |\n| doze |\n")
        self.assertNotIn('class="num"', html)

    def test_paragraph_of_only_code_spans_becomes_chips(self) -> None:
        html = build("`Docling` `Camelot`\n\nTexto com `código` no meio.\n")
        self.assertIn('<p class="chips"><code>Docling</code> <code>Camelot</code></p>', html)
        self.assertIn("<p>Texto com <code>código</code> no meio.</p>", html)

    def test_italic_paragraph_after_code_block_is_its_caption(self) -> None:
        html = build("```python\nx = 1\n```\n\n*Trecho ilustrativo.*\n\nDepois.\n")
        self.assertRegex(
            html,
            r'<figure class="listing">(?:<div class="sourceCode"[^>]*>)?<pre[\s\S]*?</pre>'
            r'(?:</div>)?<figcaption>Trecho ilustrativo\.</figcaption></figure>',
        )
        self.assertIn("<p>Depois.</p>", html)

    def test_italic_paragraph_elsewhere_is_not_a_caption(self) -> None:
        html = build("Texto.\n\n*Ênfase solta.*\n")
        self.assertNotIn("listing", html)


class PostprocessIdempotenceTests(unittest.TestCase):
    def test_second_pass_changes_nothing(self) -> None:
        cfg = mdpdf.DEFAULTS
        md = (
            "## 1. Seção\n\n> [!TIP]\n> x\n\n::: cards\n### A\nx\n:::\n\n"
            "::: steps\n### S1\nx\n\n### S2\ny\n:::\n\n`a` `b`\n"
        )
        once = mdpdf.postprocess(mdpdf.markdown_to_html(mdpdf.preprocess_markdown(md, cfg)), cfg)
        self.assertEqual(once, mdpdf.postprocess(once, cfg))


if __name__ == "__main__":
    unittest.main()
