"""
mdpdf — builds documentation PDFs from Markdown, with a cover, a paginated
table of contents, running headers and vector Mermaid diagrams.

Pipeline:
  1. split the document header (title + metadata) off and assemble the cover;
  2. render the ```mermaid``` blocks to SVG (mermaid-cli over headless Chrome);
  3. convert the body to HTML with pandoc (GitHub-style anchors, so the links
     in the table of contents keep working);
  4. print with WeasyPrint, which resolves the table of contents page numbers,
     the running headers and the PDF's navigable outline.

Visual identity comes from a *theme* (~/.local/share/mdpdf/themes/<name>) and
from an optional mdpdf.toml next to the document. See `mdpdf --help` and the
README.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from html import escape, unescape
from pathlib import Path

HOME = Path(__file__).resolve().parent
THEMES = HOME / "themes"
CACHE_ROOT = Path.home() / ".cache" / "mdpdf"

BROWSER_CANDIDATES = [
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

DEFAULTS: dict = {
    "theme": "plain",
    "name": "",
    "logo": "",
    "lang": "pt-BR",
    "brand": "",
    "footer": "",
    "keywords": [],
    "toc_titles": ["Índice Analítico", "Índice", "Sumário",
                   "Table of Contents", "Contents"],
    "field_table_header": "Campo",
    "figure_label": "Figura",
    "diagram_lead_chars": 480,
    "diagram_layout": "page",
    "diagram_inline_min_ratio": 1.5,
    "cover_subtitle_field": "produto",
    "cover_kind_field": "documento",
    "cover_stamp_field": "classificação",
    "colors": {},
    "fonts": [],
    "mermaid": {},
}


def load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"syntax error in {path}: {exc}")


def resolve_theme_dir(name: str, relative_to: Path) -> Path:
    """Accept an installed theme name or the path to a theme folder."""
    candidate = THEMES / name
    if (candidate / "theme.toml").exists():
        return candidate
    as_path = (relative_to / name).resolve()
    if (as_path / "theme.toml").exists():
        return as_path
    installed = sorted(p.name for p in THEMES.iterdir() if (p / "theme.toml").exists())
    sys.exit(f"unknown theme: {name}\ninstalled themes: {', '.join(installed)}")


def merge(base: dict, extra: dict) -> dict:
    """Shallow merge, except for the token dicts, which merge key by key."""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def build_config(md_path: Path, theme_override: str | None) -> tuple[dict, Path]:
    project = load_toml(md_path.parent / "mdpdf.toml")
    theme_name = theme_override or project.get("theme") or DEFAULTS["theme"]
    theme_dir = resolve_theme_dir(theme_name, md_path.parent)

    cfg = merge(DEFAULTS, load_toml(theme_dir / "theme.toml"))
    cfg = merge(cfg, project)
    cfg["theme"] = theme_name
    return cfg, theme_dir


ILLEGAL_IN_NAME = re.compile(r"[/\\\x00-\x1f]")


def resolve_output(md_path: Path, output_flag: str | None, cfg: dict) -> Path:
    """Decide the PDF path: -o > `name` from mdpdf.toml > the .md's own name.

    `name` is a filename, not a path: separators and control characters are
    replaced with `-` so it cannot escape the document's folder. Parentheses,
    spaces and accents pass through untouched — that is the point of it.
    """
    if output_flag:
        return Path(output_flag).resolve()

    name = str(cfg.get("name") or "").strip()
    if not name:
        return md_path.with_suffix(".pdf")

    name = ILLEGAL_IN_NAME.sub("-", name).strip(" .")
    if not name:
        sys.exit("`name` in mdpdf.toml is empty once sanitised")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return md_path.parent / name


def resolve_logo(cfg: dict, theme_dir: Path, doc_dir: Path) -> Path | None:
    """Find the `logo` image, looking next to the document and in the theme.

    Keeping the file inside the theme folder is what makes a logo permanent:
    every document built with that theme inherits it, with nothing to redo.
    """
    logo = str(cfg.get("logo") or "").strip()
    if not logo:
        return None

    candidates = [Path(logo).expanduser()] if Path(logo).expanduser().is_absolute() else [
        doc_dir / logo,
        theme_dir / logo,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    searched = "\n".join(f"  {c}" for c in candidates)
    sys.exit(f"logo not found: {logo}\nlooked in:\n{searched}")


def split_front_matter(md: str) -> tuple[str, list[tuple[str, str]], str]:
    """Return (title, [(label, value)], remaining body).

    The identification block ends at the first `---` OR the first `##`, so a
    document without the separator does not lose its opening sections.
    """
    lines = md.splitlines()

    title = ""
    meta: list[tuple[str, str]] = []
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if title and stripped in ("---", "***", "___"):
            body_start = i + 1
            break
        if title and stripped.startswith("## "):
            body_start = i
            break
        m = re.match(r"^\*\*(.+?):\*\*\s*(.+?)\s*$", stripped)
        if m:
            meta.append((m.group(1), m.group(2)))

    body = "\n".join(lines[body_start:]).lstrip("\n")
    return title, meta, body


CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
EMPHASIS_RE = re.compile(r"\*{1,3}(.+?)\*{1,3}", re.S)


def inline_md_to_html(text: str) -> str:
    """Minimal code and emphasis conversion for the title and cover fields.

    Code spans are pulled out first and parked outside the text, so their
    content is not reinterpreted as emphasis (`*ptr` stays upright) and the
    backticks never reach the PDF as punctuation. The fence follows CommonMark:
    a run of backticks only closes on a run of the same length, so ``a ` b``
    keeps working.
    """
    spans: list[str] = []

    def stash(match: re.Match) -> str:
        spans.append(f"<code>{escape(match.group(2).strip())}</code>")
        return f"\x00{len(spans) - 1}\x00"

    out = escape(CODE_SPAN_RE.sub(stash, text))
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\*(.+?)\*", r"<em>\1</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], out)


def inline_md_to_text(text: str) -> str:
    """Plain-text reading of the same markup, for the PDF metadata."""
    out = CODE_SPAN_RE.sub(lambda m: m.group(2).strip(), text)
    return EMPHASIS_RE.sub(r"\1", out)


def build_cover(title: str, meta: list[tuple[str, str]], cfg: dict,
                logo: Path | None = None) -> str:
    """Assemble the cover section.

    A logo takes the place of the coloured rule: shown together they would
    compete for the same role as the mark at the top of the page.
    """
    lookup = {k.lower(): v for k, v in meta}

    subtitle = lookup.get(cfg["cover_subtitle_field"], "")
    document = lookup.get(cfg["cover_kind_field"], "")
    stamp = lookup.get(cfg["cover_stamp_field"], "")

    skip = {cfg["cover_subtitle_field"], cfg["cover_kind_field"],
            cfg["cover_stamp_field"]}
    fields = [(k, v) for k, v in meta if k.lower() not in skip]

    dl = "\n".join(
        f"      <div><dt>{escape(k)}</dt><dd>{inline_md_to_html(v)}</dd></div>"
        for k, v in fields
    )

    main, _, tail = title.partition("—")
    main = main.strip() or title
    tail = tail.strip()

    eyebrow = (f'\n    <p class="cover__eyebrow">{escape(cfg["brand"])}</p>'
               if cfg["brand"] else "")
    stamp_html = (f'\n    <div class="cover__stamp">{escape(inline_md_to_text(stamp))}</div>'
                  if stamp else "")

    logo_html = (f'\n    <img class="cover__logo" src="{logo.as_uri()}" alt="">'
                 if logo else "")
    cover_class = "cover cover--logo" if logo else "cover"

    return f"""<section class="{cover_class}">{logo_html}
    <div class="cover__rule"></div>{eyebrow}
    <h1 class="cover__title">{inline_md_to_html(main)}</h1>
    <p class="cover__subtitle">{inline_md_to_html(tail or document)}<br>{inline_md_to_html(subtitle)}</p>
    <div class="cover__spacer"></div>
    <dl class="cover__meta">
{dl}
    </dl>{stamp_html}
  </section>"""


def font_face_rules(cfg: dict, theme_dir: Path) -> str:
    rules = []
    for face in cfg.get("fonts", []):
        src = (theme_dir / face["file"]).resolve()
        if not src.exists():
            sys.exit(f"font file not found in the theme: {src}")
        rules.append(
            "@font-face {\n"
            f'  font-family: "{face["family"]}";\n'
            f'  src: url("{src.as_uri()}");\n'
            f'  font-weight: {face.get("weight", 400)};\n'
            f'  font-style: {face.get("style", "normal")};\n'
            "}"
        )
    return "\n".join(rules)


def token_rules(cfg: dict) -> str:
    tokens = "\n".join(f"  --{k}: {v};" for k, v in cfg["colors"].items())
    return f":root {{\n{tokens}\n}}" if tokens else ""


def footer_rule(cfg: dict) -> str:
    text = cfg.get("footer") or cfg.get("brand") or ""
    if not text:
        return "@page { @bottom-left { content: none; } }"
    return f'@page {{ @bottom-left {{ content: "{text}"; }} }}'


def build_stylesheet(cfg: dict, theme_dir: Path, cache: Path) -> Path:
    theme_css = theme_dir / "style.css"
    parts = [
        font_face_rules(cfg, theme_dir),
        token_rules(cfg),
        (HOME / "base.css").read_text(encoding="utf-8"),
        theme_css.read_text(encoding="utf-8") if theme_css.exists() else "",
        footer_rule(cfg),
    ]
    css = cache / "style.css"
    css.write_text("\n\n".join(p for p in parts if p), encoding="utf-8")
    return css


MERMAID_RE = re.compile(
    r"^```mermaid(?:[ \t]+\{layout=(?P<layout>auto|page|inline)\})?[ \t]*\n"
    r"(?P<source>.*?)^```[ \t]*$",
    re.S | re.M,
)


def find_browser() -> str | None:
    for path in BROWSER_CANDIDATES:
        if Path(path).exists():
            return path
    return shutil.which("chromium") or shutil.which("google-chrome")


def tint(color: str, amount: float, toward: str = "#ffffff") -> str:
    """Blend `color` towards `toward`.

    Used to derive the light gantt bars from the theme's strong colours, so the
    dark text inside a bar stays legible in any palette.
    """
    def parse(h: str) -> tuple[int, int, int]:
        h = h.strip().lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return (0, 0, 0)

    r1, g1, b1 = parse(color)
    r2, g2, b2 = parse(toward)
    mix = lambda a, b: round(a + (b - a) * amount)
    return f"#{mix(r1, r2):02x}{mix(g1, g2):02x}{mix(b1, b2):02x}"


def mermaid_theme(cfg: dict) -> dict:
    """Derive the Mermaid theme from the same tokens the CSS uses.

    The gantt chart has its own family of variables: without them it ignores
    the theme palette and comes out in Mermaid's default red and grey. Its
    canvas is fixed, so the geometry below preserves the usable width of the
    timeline and makes better use of the height of a landscape sheet.
    """
    c = cfg["colors"]
    variables = {
        "fontFamily": c.get("sans", "sans-serif").replace('"', ""),
        "fontSize": "15px",
        "primaryColor": c.get("paper-alt", "#f5f5f5"),
        "primaryTextColor": c.get("ink", "#222222"),
        "primaryBorderColor": c.get("accent", "#333333"),
        "lineColor": c.get("ink-soft", "#555555"),
        "tertiaryColor": c.get("paper", "#ffffff"),
        "clusterBkg": c.get("paper", "#ffffff"),
        "clusterBorder": c.get("accent-2", c.get("accent", "#999999")),
    }

    accent = c.get("accent", "#333333")
    accent_deep = c.get("accent-deep", accent)
    accent_2 = c.get("accent-2-ink", c.get("accent-2", accent))
    paper = c.get("paper", "#ffffff")
    paper_alt = c.get("paper-alt", "#f5f5f5")
    hairline = c.get("hairline", "#dddddd")
    ink = c.get("ink", "#222222")
    ink_soft = c.get("ink-soft", "#555555")
    variables.update({
        "titleColor": ink,
        "sectionBkgColor": paper,
        "altSectionBkgColor": paper_alt,
        "sectionBkgColor2": paper,
        "gridColor": hairline,
        "todayLineColor": accent,
        "taskBkgColor": paper_alt,
        "taskBorderColor": hairline,
        "taskTextColor": ink,
        "taskTextDarkColor": ink,
        "taskTextLightColor": paper,
        "taskTextOutsideColor": ink_soft,
        "taskTextClickableColor": accent,
        "activeTaskBkgColor": tint(accent_2, 0.84),
        "activeTaskBorderColor": accent_2,
        "doneTaskBkgColor": paper_alt,
        "doneTaskBorderColor": hairline,
        "critBkgColor": tint(accent, 0.80),
        "critBorderColor": accent_deep,
    })

    variables.update(cfg.get("mermaid", {}))
    return {
        "theme": "base",
        "htmlLabels": False,
        "themeVariables": variables,
        "flowchart": {
            "htmlLabels": False,
            "curve": "basis",
            "padding": 14,
            "nodeSpacing": 34,
            "rankSpacing": 62,
            "useMaxWidth": False,
        },
        "gantt": {
            "useMaxWidth": False,
            "useWidth": 800,
            "barHeight": 30,
            "barGap": 9,
            "topPadding": 62,
            "leftPadding": 150,
            "rightPadding": 32,
            "gridLineStartPadding": 34,
            "fontSize": 13,
            "sectionFontSize": 13,
        },
    }


TITLE_RE = re.compile(r'<text[^>]*class="titleText"[^>]*>([^<]*)</text>')
SVG_TAG_RE = re.compile(r"<svg\b[^>]*>")


def fit_svg_viewbox(svg: Path, font_size: float = 15.0) -> None:
    """Widen the viewBox when the diagram title is wider than the diagram.

    Mermaid sizes the viewBox from the graph content and ignores the title,
    which is centred and gets clipped at both ends when it is long. With no
    text engine here, the width is estimated from the character count — enough
    to decide how much to widen by.
    """
    try:
        content = svg.read_text(encoding="utf-8")
    except OSError:
        return

    titles = TITLE_RE.findall(content)
    tag = SVG_TAG_RE.search(content)
    if not titles or not tag:
        return

    box = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', tag.group(0))
    width_attr = re.search(r'width="([\d.]+)"', tag.group(0))
    if not box or not width_attr:
        return

    x, y, w, h = (float(v) for v in box.groups())
    needed = max(len(t) for t in titles) * font_size * 0.56 + 48
    if needed <= w:
        return

    new_tag = (tag.group(0)
               .replace(box.group(0), f'viewBox="{x - (needed - w) / 2:.2f} {y} {needed:.2f} {h}"')
               .replace(width_attr.group(0), f'width="{needed:.2f}"'))
    svg.write_text(content.replace(tag.group(0), new_tag, 1), encoding="utf-8")


def diagram_layout(svg: Path, cfg: dict, requested: str | None = None) -> str:
    """Choose whether a Mermaid figure owns a page or flows with the prose."""
    layout = requested or str(cfg.get("diagram_layout", "page"))
    if layout in {"page", "inline"}:
        return layout
    if layout != "auto":
        sys.exit(f"invalid diagram_layout: {layout} (expected auto, page or inline)")

    try:
        content = svg.read_text(encoding="utf-8")
    except OSError:
        return "page"
    tag = SVG_TAG_RE.search(content)
    box = re.search(
        r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"',
        tag.group(0) if tag else "",
    )
    if not box:
        return "page"
    width, height = (float(value) for value in box.groups())
    if height <= 0:
        return "page"
    threshold = float(cfg.get("diagram_inline_min_ratio", 1.5))
    return "inline" if width / height >= threshold else "page"


def render_mermaid(md: str, cfg: dict, theme_dir: Path, cache: Path) -> str:
    blocks = list(MERMAID_RE.finditer(md))
    if not blocks:
        return md

    browser = find_browser()
    puppeteer_cfg = cache / "puppeteer.json"
    launch: dict = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if browser:
        launch["executablePath"] = browser
    puppeteer_cfg.write_text(json.dumps(launch), encoding="utf-8")

    conf = mermaid_theme(cfg)
    mermaid_cfg = cache / "mermaid-config.json"
    mermaid_cfg.write_text(json.dumps(conf), encoding="utf-8")

    sans = conf["themeVariables"]["fontFamily"]
    mermaid_css = cache / "mermaid.css"
    mermaid_css.write_text(
        font_face_rules(cfg, theme_dir)
        + f"\n.node .label, .edgeLabel, .cluster-label {{ font-family: {sans}; }}\n"
        + f".edgeLabel {{ font-size: 12px; fill: {cfg['colors'].get('ink-soft', '#555')}; }}\n"
        + f".titleText {{ font-family: {sans}; font-size: 15px; "
          f"fill: {cfg['colors'].get('ink', '#222')}; }}\n"
        + f".sectionTitle, .taskText, .taskTextOutsideRight, .taskTextOutsideLeft, "
          f"text.exclude-range {{ font-family: {sans}; }}\n"
        + f".grid .tick text {{ font-family: {sans}; font-size: 11px; "
          f"fill: {cfg['colors'].get('ink-muted', '#777')}; }}\n"
        + ".grid path { stroke-width: 0; }\n",
        encoding="utf-8",
    )

    out: list[str] = []
    last = 0
    fingerprint = json.dumps(conf, sort_keys=True)
    for idx, block in enumerate(blocks, start=1):
        source = block.group("source")
        digest = hashlib.sha1((source + fingerprint).encode("utf-8")).hexdigest()[:12]
        svg = cache / f"diagram-{idx}-{digest}.svg"

        if not svg.exists():
            src = cache / f"diagram-{idx}-{digest}.mmd"
            src.write_text(source, encoding="utf-8")
            print(f"  · rendering diagram {idx} …", file=sys.stderr)
            subprocess.run(
                ["npx", "-y", "@mermaid-js/mermaid-cli",
                 "-i", str(src), "-o", str(svg),
                 "-p", str(puppeteer_cfg),
                 "-c", str(mermaid_cfg),
                 "-C", str(mermaid_css),
                 "-b", "transparent"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            fit_svg_viewbox(svg)

        out.append(md[last:block.start()])

        headings = re.findall(r"^#{2,4}\s+([\d.]+)\s+(.+)$", md[:block.start()], re.M)
        caption = headings[-1][1] if headings else "Diagrama"
        layout = diagram_layout(svg, cfg, block.group("layout"))
        layout_class = "diagram-inline" if layout == "inline" else "diagram-page"

        out.append(
            f'<figure class="figure--diagram {layout_class}">'
            f'<img src="{svg.as_uri()}" alt="{escape(caption)}">'
            f'<figcaption>{escape(cfg["figure_label"])} {idx} — {escape(caption)}</figcaption>'
            "</figure>"
        )
        last = block.end()

    out.append(md[last:])
    return "".join(out)


def markdown_to_html(md: str) -> str:
    result = subprocess.run(
        ["pandoc", "-f", "gfm+raw_html", "-t", "html5", "--wrap=none"],
        input=md, text=True, capture_output=True, check=True,
    )
    return result.stdout


# A diagram already wrapped in its block, or a bare figure — matched in that
# order so a second postprocess() pass leaves an existing block alone.
DIAGRAM_ELEMENT_RE = re.compile(
    r'<div class="diagram-block(?: [^"]+)*">[\s\S]*?</figure></div>'
    r'|(?P<open><figure\b[^>]*>)(?:(?!</figure>)[\s\S])*</figure>'
)

# The heading or paragraph immediately above a given point in the document.
COMPANION_RE = re.compile(
    r"<(?P<tag>p|h[2-6])\b[^>]*>(?:(?!</(?P=tag)>)[\s\S])*</(?P=tag)>\s*\Z"
)


def visible_text(html: str) -> str:
    """The text a reader sees, without the markup or the surrounding blanks."""
    return unescape(re.sub(r"<[^>]+>", "", html)).strip(
        " \t\r\n\f\v\u00a0\u200b"
    )


def postprocess(html: str, cfg: dict) -> str:
    """Mark the table of contents and turn images into captioned figures."""
    titles = "|".join(re.escape(t) for t in cfg["toc_titles"])
    html = re.sub(
        rf'(<h2 id="[^"]*">\s*(?:{titles})\s*</h2>\s*)(<ol[^>]*>.*?</ol>)',
        lambda m: m.group(1) + '<nav class="toc">' + m.group(2) + "</nav>",
        html,
        flags=re.S | re.I,
    )

    html = re.sub(
        r"(<a href=\"#[^\"]*\">)([^<]*)(</a>)\s*(<em>[^<]*</em>)",
        r"\1\2 \4\3",
        html,
    )

    label = re.escape(cfg["field_table_header"])
    html = re.sub(
        rf"<table>(\s*<thead>\s*<tr[^>]*>\s*<th[^>]*>{label}</th>)",
        r'<table class="table--fields">\1',
        html,
    )

    def class_value(tag: str) -> str | None:
        """Read the value of a quoted class attribute, if there is one."""
        match = re.search(r'(?<!\S)class\s*=\s*(["\'])(.*?)\1', tag, re.I | re.S)
        return match.group(2) if match else None

    def add_class(tag: str, name: str) -> str:
        """Append a real class without touching data-class/aria-class."""
        classes = class_value(tag)
        if classes is not None:
            if name in classes.split():
                return tag
            return re.sub(
                r'((?<!\S)class\s*=\s*)(["\'])(.*?)\2',
                lambda attr: f"{attr.group(1)}{attr.group(2)}{attr.group(3)} {name}{attr.group(2)}",
                tag,
                count=1,
                flags=re.I | re.S,
            )
        return tag[:-1] + f' class="{name}">'

    def is_diagram_figure(tag: str) -> bool:
        classes = class_value(tag)
        return bool(
            classes
            and "figure--diagram" in classes.split()
            and {"diagram-page", "diagram-inline"}.intersection(classes.split())
        )

    def diagram_is_inline(tag: str) -> bool:
        classes = class_value(tag)
        return bool(classes and "diagram-inline" in classes.split())

    def mark_diagram_lead(match: re.Match) -> str:
        opening, content, closing, whitespace, figure = match.groups()
        if not visible_text(content).endswith(":") or not is_diagram_figure(figure):
            return opening + content + closing + whitespace + figure
        return add_class(opening, "diagram-lead") + content + closing + whitespace + figure

    html = re.sub(
        r'(<p\b[^>]*>)((?:(?!<p\b)[\s\S])*?)(</p>)(\s*)(<figure\b[^>]*>)',
        mark_diagram_lead,
        html,
    )

    def companion_start(html: str, figure_start: int, floor: int) -> int:
        """Walk back over the headings and short prose that introduce a diagram.

        A section that opens with a heading and a few lines and then shows its
        diagram reads as one unit, so it is printed as one: the group is the run
        of headings, then the paragraphs under them, then the figure. Paragraphs
        travel only while their combined text stays within `diagram_lead_chars`,
        which is what keeps a long section from being dragged onto the diagram
        page and shrinking the figure; and nothing above the headings travels,
        since that text belongs to the section that just ended.
        """
        budget = int(cfg["diagram_lead_chars"])
        cursor = figure_start
        heading_reached = False
        while (element := COMPANION_RE.search(html, floor, cursor)) is not None:
            if element.group("tag") != "p":
                heading_reached = True
                cursor = element.start()
                continue
            budget -= len(visible_text(element.group(0)))
            if heading_reached or budget < 0:
                break
            cursor = element.start()
        return cursor

    blocks: list[str] = []
    last = 0
    for element in DIAGRAM_ELEMENT_RE.finditer(html):
        figure = element.group(0)
        if not element.group("open") or not is_diagram_figure(element.group("open")):
            continue

        start = companion_start(html, element.start(), last)
        blocks.append(html[last:start])
        lead_html = html[start:element.start()]
        block_classes = ["diagram-block"]
        if diagram_is_inline(element.group("open")):
            block_classes.append("diagram-block--inline")
            if re.search(r"<h2\b", lead_html):
                block_classes.append("diagram-block--section")
        block_class = " ".join(block_classes)
        blocks.append(f'<div class="{block_class}"><div class="diagram-block__lead">')
        blocks.append(lead_html)
        blocks.append(f"</div>{figure}</div>")
        last = element.end()

    blocks.append(html[last:])
    html = "".join(blocks)

    html = re.sub(r'<p>(<img src="[^"]*"[^>]*/?>)</p>', r"<figure>\1</figure>", html)
    return html


def compose(title: str, cover: str, body: str, meta: list[tuple[str, str]],
            cfg: dict, css: Path) -> str:
    lookup = {k.lower(): v for k, v in meta}
    author = inline_md_to_text(lookup.get("autor(es)", lookup.get("autor", "")))
    subject = "{} — versão {} ({})".format(
        inline_md_to_text(lookup.get(cfg["cover_kind_field"], "")),
        lookup.get("versão", lookup.get("version", "")),
        lookup.get("data", lookup.get("date", "")),
    ).strip(" —()")
    keywords = ", ".join(cfg["keywords"])
    return f"""<!doctype html>
<html lang="{escape(cfg['lang'])}">
<head>
  <meta charset="utf-8">
  <title>{escape(inline_md_to_text(title))}</title>
  <meta name="author" content="{escape(author)}">
  <meta name="description" content="{escape(subject)}">
  <meta name="keywords" content="{escape(keywords)}">
  <link rel="stylesheet" href="{css.as_uri()}">
</head>
<body>
{cover}
{body}
</body>
</html>
"""


def cmd_build(args: argparse.Namespace) -> int:
    md_path = Path(args.markdown).resolve()
    if not md_path.exists():
        print(f"file not found: {md_path}", file=sys.stderr)
        return 1

    cfg, theme_dir = build_config(md_path, args.theme)
    out_path = resolve_output(md_path, args.output, cfg)

    key = hashlib.sha1(str(md_path).encode("utf-8")).hexdigest()[:12]
    cache = CACHE_ROOT / f"{md_path.stem[:40]}-{key}"
    cache.mkdir(parents=True, exist_ok=True)

    print(f"→ reading {md_path.name}  (theme: {cfg['theme']})", file=sys.stderr)
    md = md_path.read_text(encoding="utf-8")

    title, meta, body_md = split_front_matter(md)
    if not title:
        print("could not find the title (a '# …' line)", file=sys.stderr)
        return 1

    body_md = render_mermaid(body_md, cfg, theme_dir, cache)

    print("→ converting markdown", file=sys.stderr)
    css = build_stylesheet(cfg, theme_dir, cache)
    body_html = postprocess(markdown_to_html(body_md), cfg)
    logo = resolve_logo(cfg, theme_dir, md_path.parent)
    html = compose(title, build_cover(title, meta, cfg, logo),
                   body_html, meta, cfg, css)

    html_path = cache / "document.html"
    html_path.write_text(html, encoding="utf-8")

    print(f"→ printing {out_path.name}", file=sys.stderr)
    subprocess.run(
        ["weasyprint", "-e", "utf-8", "-u", md_path.parent.as_uri() + "/",
         str(html_path), str(out_path)],
        check=True,
    )

    if args.keep_html:
        print(f"  html at {html_path}", file=sys.stderr)
    else:
        html_path.unlink(missing_ok=True)

    size = out_path.stat().st_size / 1024
    print(f"✓ {out_path}  ({size:.0f} kB)", file=sys.stderr)
    return 0


def cmd_themes(_: argparse.Namespace) -> int:
    for theme in sorted(THEMES.iterdir()):
        manifest = theme / "theme.toml"
        if not manifest.exists():
            continue
        meta = load_toml(manifest)
        print(f"{theme.name:16} {meta.get('description', '')}")
    return 0


TOML_ORDER = ["theme", "name", "logo", "brand", "footer", "lang", "keywords",
              "toc_titles", "field_table_header", "figure_label",
              "diagram_layout", "diagram_inline_min_ratio", "diagram_lead_chars",
              "cover_subtitle_field", "cover_kind_field", "cover_stamp_field"]


def toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def dump_toml(cfg: dict, header: str = "") -> str:
    lines = [header.rstrip(), ""] if header else []

    for key in TOML_ORDER:
        if key in cfg and not isinstance(cfg[key], (dict, list)) or (
            key in cfg and isinstance(cfg[key], list)
        ):
            lines.append(f"{key} = {toml_value(cfg[key])}")

    for key, value in cfg.items():
        if key in TOML_ORDER or isinstance(value, (dict, list)):
            continue
        lines.append(f"{key} = {toml_value(value)}")

    for key, value in cfg.items():
        if isinstance(value, dict):
            lines += ["", f"[{key}]"]
            lines += [f"{k} = {toml_value(v)}" for k, v in value.items()]

    for key, value in cfg.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                lines += ["", f"[[{key}]]"]
                lines += [f"{k} = {toml_value(v)}" for k, v in item.items()]

    return "\n".join(lines).strip() + "\n"


def cmd_design(args: argparse.Namespace) -> int:
    import design as design_engine

    src = Path(args.design).resolve()
    if not src.exists():
        print(f"design document not found: {src}", file=sys.stderr)
        return 1

    try:
        result = design_engine.analyse(src)
    except ValueError as exc:
        print(f"could not read the design: {exc}", file=sys.stderr)
        return 1

    target = Path(args.output).resolve() if args.output else Path.cwd() / "mdpdf.toml"
    cfg = load_toml(target)

    print(f"→ reading {src.name}\n", file=sys.stderr)
    for note in result["notes"]:
        print(f"  {note}", file=sys.stderr)

    cfg["colors"] = {**cfg.get("colors", {}), **result["colors"]}
    if result["brand"] and not cfg.get("brand"):
        cfg["brand"] = result["brand"]
        print(f"\n  {'brand':14} {result['brand']}", file=sys.stderr)
    if args.theme:
        cfg["theme"] = args.theme
    cfg.setdefault("theme", DEFAULTS["theme"])

    theme_dir = resolve_theme_dir(cfg["theme"], target.parent)
    packaged = {f["family"].lower()
                for f in load_toml(theme_dir / "theme.toml").get("fonts", [])}
    for kind in ("sans", "mono"):
        stack = result["colors"].get(kind)
        if not stack:
            continue
        first = stack.split(",")[0].strip().strip('"\'').lower()
        if first not in packaged:
            print(f"\n  ! “{first}” is not packaged in the “{cfg['theme']}” theme: "
                  f"the PDF will fall through to the next family in the stack.\n"
                  f"    To embed it, drop the .ttf in a theme and declare [[fonts]].",
                  file=sys.stderr)

    if args.dry_run:
        print("\n--- mdpdf.toml (dry run, nothing was written) ---\n", file=sys.stderr)
        print(dump_toml(cfg, f"# generated by: mdpdf design {src.name}"))
        return 0

    if target.exists():
        backup = target.with_suffix(".toml.bak")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"\n  previous version copied to {backup.name}", file=sys.stderr)

    target.write_text(
        dump_toml(cfg, f"# generated by: mdpdf design {src.name}\n"
                       "# the comments from the previous version are in the .bak"),
        encoding="utf-8",
    )
    print(f"✓ {target}", file=sys.stderr)
    return 0


INIT_TEMPLATE = """# mdpdf configuration for this folder
theme = "{theme}"

# output PDF filename, so -o is not needed (".pdf" is appended when missing);
# empty = the PDF inherits the name of the .md
# example: name = "SaintThomas(Laboratório S07 - Arch3)"
name = ""

# image at the top of the cover; path relative to this folder or to the theme
# folder. Copy the file into the theme and every document using that theme
# inherits it.
# example: logo = "logo.png"
logo = ""

# mark printed on the cover and in the page footer
brand = "{brand}"
footer = "{brand}"

lang = "pt-BR"
keywords = []

# override theme tokens here if you want to
# [colors]
# accent = "#0b3fd4"
# accent-2 = "#5aa2f0"
"""


def cmd_init(args: argparse.Namespace) -> int:
    target = Path.cwd() / "mdpdf.toml"
    if target.exists() and not args.force:
        print(f"{target} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    target.write_text(
        INIT_TEMPLATE.format(theme=args.theme, brand=args.brand), encoding="utf-8"
    )
    print(f"✓ {target}", file=sys.stderr)
    return 0


def main() -> int:
    verb = sys.argv[1] if len(sys.argv) > 1 else ""

    if verb == "themes":
        ap = argparse.ArgumentParser(prog="mdpdf themes",
                                     description="List the installed themes.")
        return cmd_themes(ap.parse_args(sys.argv[2:]))

    if verb == "init":
        ap = argparse.ArgumentParser(prog="mdpdf init",
                                     description="Create an mdpdf.toml in the current folder.")
        ap.add_argument("-t", "--theme", default="plain")
        ap.add_argument("-b", "--brand", default="")
        ap.add_argument("--force", action="store_true")
        return cmd_init(ap.parse_args(sys.argv[2:]))

    if verb in ("design", "--design"):
        rest = sys.argv[2:]
        ap = argparse.ArgumentParser(
            prog="mdpdf design",
            description="Read a DESIGN.md, work out the print palette and "
                        "update the folder's mdpdf.toml.",
        )
        ap.add_argument("design", help="design document (.md)")
        ap.add_argument("-o", "--output", default=None,
                        help="target toml (default: ./mdpdf.toml)")
        ap.add_argument("-t", "--theme", default=None, help="set the base theme")
        ap.add_argument("-n", "--dry-run", action="store_true",
                        help="show the result without writing")
        return cmd_design(ap.parse_args(rest))

    ap = argparse.ArgumentParser(
        prog="mdpdf",
        description="Build a documentation PDF from Markdown.",
        epilog="subcommands: mdpdf themes · mdpdf init",
    )
    ap.add_argument("markdown", nargs="?", help=".md file (default: the only .md in the folder)")
    ap.add_argument("-o", "--output", default=None, help="output PDF path")
    ap.add_argument("-t", "--theme", default=None, help="theme to use for this run")
    ap.add_argument("--keep-html", action="store_true", help="keep the intermediate HTML")

    args = ap.parse_args()

    if not args.markdown:
        found = sorted(Path.cwd().glob("*.md"))
        found = [p for p in found if p.name.lower() not in ("readme.md", "changelog.md")]
        if len(found) != 1:
            ap.error("name the .md file (the folder has %d candidates)" % len(found))
        args.markdown = str(found[0])

    return cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
