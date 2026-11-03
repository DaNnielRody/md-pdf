# Tickets — Rich print blocks

Git mode, single PR (user request). Branch `feat/rich-print-blocks` from `main`.

| ID | Slice | Blocking | Files | Tests | Roles |
|---|---|---|---|---|---|
| LOCAL-1 | Section eyebrow + heavy rule | — | mdpdf.py, base.css | tests/test_rich_blocks.py | testing, backend |
| LOCAL-2 | GFM alerts with labels/custom title | — | mdpdf.py, base.css | tests/test_rich_blocks.py | testing, backend |
| LOCAL-3 | cards / compare / stats containers | LOCAL-2 (pandoc flags) | mdpdf.py, base.css | tests/test_rich_blocks.py | testing, backend |
| LOCAL-4 | Technical tables, chips, code captions | — | mdpdf.py, base.css | tests/test_rich_blocks.py | testing, backend |
| LOCAL-5 | Steps cards with prev/next/back links | LOCAL-3 | mdpdf.py, base.css | tests/test_rich_blocks.py | testing, backend |
| LOCAL-6 | Mermaid click hotspots (bbox map + placement pass) | LOCAL-5 | mdpdf.py, base.css | tests/test_diagram_hotspots.py | architecture, testing, backend |
| LOCAL-7 | Showcase document + README | LOCAL-1..6 | examples/showcase.md, README.md | conclave | backend |
