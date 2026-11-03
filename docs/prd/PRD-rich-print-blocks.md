# PRD — Rich print blocks

## Problem
Reference `zap-pipeline.pdf` (a browser print of an interactive HTML page) has
formatting worth adopting: numbered section openers, labelled callouts, card
grids, KPI strips, comparison panels, technical tables, tag chips, code
captions and a diagram whose boxes open a detail panel. Printed from a browser
it also shows what to avoid: content cropped at the right edge, printed scroll
bars and controls that do nothing in a PDF.

Root cause: mdpdf only styles plain Markdown elements; it has no block-level
vocabulary beyond headings, lists, tables, quotes and figures, and Mermaid SVGs
are embedded as `<img>`, where links are inert.

## In scope
1. Section number eyebrow (`01`) before numbered `h2` + heavy top rule.
2. GFM alerts (`> [!NOTE]` … `[!CAUTION]`) with localized labels and an optional custom title.
3. `::: cards` grid (1–3 columns) with coloured top border and optional eyebrow.
4. `::: stats` KPI strip.
5. `::: compare` two-column comparison panels.
6. Technical tables: small uppercase headers, code cells in mono, numeric columns right-aligned.
7. Paragraphs made only of inline code render as chips.
8. An italic-only paragraph right after a code block becomes its caption.
9. Mermaid `click X href "#id"` turns the node into a working PDF link; `::: steps`
   cards get working Previous / Next / Back-to-diagram links.
10. Showcase Markdown exercising every feature.

## Out of scope
Interactive HTML output, PDF JavaScript, optional content groups, new dependencies.

## Acceptance criteria
- Every feature renders through the real pipeline (`mdpdf.py` → pandoc → WeasyPrint).
- A clicked hotspot lands on the step card; the card's links land on neighbour cards and on the figure.
- No navigation control without a destination is printed.
- Wide tables and long code wrap inside the text block (no clipping).
- Documents that use none of the new syntax keep page count and section-opening behaviour.

## Invariants
- Markdown remains the single source of truth; GFM-valid syntax wherever GFM has one.
- Diagram page fitting (`diagram-block` geometry) is unchanged; hotspots are out-of-flow.
- Running header keeps the full numbered section title.

## Risks
- Fenced-div syntax `:::` changes the meaning of a bare `:::` line (rare).
- Hotspots need the WeasyPrint module importable in mdpdf's interpreter and a Chromium; otherwise they are skipped with a warning.
- One extra layout pass for documents with linked diagrams.

## Evidence
Unit tests over `postprocess()`/preprocessing, real-WeasyPrint tests for hotspot
geometry and link targets, and a visual conclave of the showcase PDF before/after.
