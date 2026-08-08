"""
Engine de design: lê um DESIGN.md e deduz a paleta e a tipografia de impressão.

Um documento de design descreve, quase sempre, uma interface — fundo escuro,
muitos tons de superfície, estados de hover. Um PDF é o contrário: tinta escura
sobre papel branco. Então esta engine não copia cores, ela **classifica**:
separa o que é identidade (marca, destaque, tipografia) do que é circunstância
da tela (superfícies, hovers, bordas), e reconstrói os tons de apoio a partir da
dupla tinta/papel.

O que sai daqui é sempre um palpite explicado: `mdpdf design` imprime a
justificativa de cada escolha para você conferir antes de aceitar.
"""

from __future__ import annotations

import re
from pathlib import Path

HEX_RE = re.compile(r"#([0-9a-fA-F]{6})\b")

KEYWORDS: dict[str, list[str]] = {
    "accent": [
        "brand", "marca", "primary", "primária", "primaria", "principal",
        "accent", "destaque principal", "indigo", "índigo", "azul escuro",
    ],
    "accent-2": [
        "secondary", "secundária", "secundaria", "accent 2", "accent-2",
        "cyan", "ciano", "turquoise", "turquesa", "highlight", "destaque",
        "focus", "foco", "live",
    ],
    "ink": [
        "text primary", "texto primário", "texto primario", "ink", "tinta",
        "charcoal", "carvão", "carvao", "canvas", "foreground", "corpo",
        "preto", "black",
    ],
    "cover-ink": [
        "off-white", "off white", "branco", "white", "text on", "texto sobre",
        "invers", "light",
    ],
    "paper": [
        "paper", "papel", "página", "pagina", "print", "impress",
    ],
}

NOISE_SECTIONS = (
    "surface", "superfície", "superficie", "elevation", "elevação", "elevacao",
    "hover", "state", "estado", "semantic", "semântic", "semantic",
    "shadow", "sombra", "overlay", "border radius", "spacing",
)

STATE_LABELS = (
    "hover", "pressed", "active", "disabled", "focus ring", "selected",
    "wash", "raised", "overlay", "shadow", "sombra",
)

STRUCTURE_LABELS = (
    "hairline", "border", "borda", "divider", "success", "warning", "error",
    "danger", "info", "sucesso", "erro", "aviso", "alerta",
    "surface", "superfície", "superficie",
)


def to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def luminance(hex_color: str) -> float:
    """WCAG relative luminance."""
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def saturation(hex_color: str) -> float:
    r, g, b = to_rgb(hex_color)
    hi, lo = max(r, g, b), min(r, g, b)
    if hi == 0:
        return 0.0
    return (hi - lo) / hi


def mix(a: str, b: str, ratio: float) -> str:
    """ratio = how much of `a` goes into `b`."""
    ra, rb = to_rgb(a), to_rgb(b)
    return to_hex(tuple(ra[i] * ratio + rb[i] * (1 - ratio) for i in range(3)))


def darken_until(color: str, over: str, target: float) -> str:
    """Darken the colour until it reaches the target contrast over `over`."""
    out = color
    for step in range(1, 21):
        if contrast(out, over) >= target:
            break
        out = mix("#000000", color, step * 0.05)
    return out


class Candidate:
    def __init__(self, hex_color: str, label: str, section: str, order: int):
        self.hex = hex_color.lower()
        self.label = label.strip()
        self.section = section.strip()
        self.order = order

    @property
    def context(self) -> str:
        return f"{self.section} {self.label}".lower()

    @property
    def penalty(self) -> int:
        label, section = self.label.lower(), self.section.lower()
        if any(n in label for n in STATE_LABELS):
            return 4
        if (any(n in label for n in STRUCTURE_LABELS)
                or any(n in section for n in NOISE_SECTIONS)):
            return 2
        return 0

    @property
    def is_noise(self) -> bool:
        return self.penalty > 0

    def __repr__(self) -> str:
        return f"<{self.hex} {self.label!r} @ {self.section!r}>"


def collect_colors(text: str) -> list[Candidate]:
    """Walk the document, keeping each hex with its label and surrounding section."""
    section = ""
    out: list[Candidate] = []
    order = 0

    for line in text.splitlines():
        heading = re.match(r"^#{2,4}\s+(.*)", line)
        if heading:
            section = re.sub(r"^\d+[.\d]*\s*", "", heading.group(1)).strip()
            continue

        hits = HEX_RE.findall(line)
        if not hits:
            continue

        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            label = next((c for c in cells if c and not HEX_RE.search(c)), "")
        else:
            label = HEX_RE.sub("", line).strip(" -—*`:|")

        label = re.sub(r"[*`{}]", "", label)
        label = re.sub(r"\s+", " ", label)[:80]

        for hit in hits:
            order += 1
            out.append(Candidate("#" + hit, label, section, order))

    return out


def score(cand: Candidate, role: str) -> int:
    """A label counts for more than a section; state/surface colours are penalised.

    A penalidade é um desempate, não um veto: num design de tela escura a tinta
    do documento costuma estar justamente na seção "Surface", e vetá-la faria a
    engine eleger a cor de marca como tinta do corpo de texto.
    """
    label, section = cand.label.lower(), cand.section.lower()
    points = 0
    for kw in KEYWORDS[role]:
        if kw in label:
            points += 3
        elif kw in section:
            points += 1
    return points - cand.penalty


def pick(cands: list[Candidate], role: str, predicate,
         taken: set[str], fallback, fallback_reason: str
         ) -> tuple[Candidate | None, str]:
    """Pick the candidate for a role; returns (candidate, reason)."""
    pool = [c for c in cands if c.hex not in taken and predicate(c)]
    if not pool:
        return None, ""

    best = max(pool, key=lambda c: (score(c, role), -c.order))
    if score(best, role) > 0:
        return best, f"rótulo “{best.label}” em “{best.section}”"

    quiet = [c for c in pool if not c.is_noise] or pool
    return fallback(quiet), fallback_reason


def extract_fonts(text: str) -> dict[str, str]:
    """Look for font stacks declared in the document."""
    stacks: list[str] = []
    for match in re.finditer(r"(?:stack|pilha|font-family)\s*:?\s*`([^`]+)`",
                             text, re.I):
        stacks.append(match.group(1).strip())
    if not stacks:
        for match in re.finditer(r"`((?:'|\")[^`]*(?:sans-serif|monospace))`", text):
            stacks.append(match.group(1).strip())

    out: dict[str, str] = {}
    for stack in stacks:
        normalized = stack.replace("'", '"')
        if re.search(r"mono", stack, re.I):
            out.setdefault("mono", normalized)
        elif re.search(r"sans|serif", stack, re.I):
            out.setdefault("sans", normalized)
    return out


def extract_brand(text: str) -> str:
    """Brand: the parenthesis in the H1, or a Cliente/Marca field."""
    h1 = re.search(r"^#\s+(.*)$", text, re.M)
    if h1:
        paren = re.search(r"\(([^)]+)\)\s*$", h1.group(1))
        if paren:
            return paren.group(1).strip()
    field = re.search(r"^\*\*(?:Cliente|Marca|Brand|Client):\*\*\s*(.+?)\s*$",
                      text, re.M | re.I)
    if field:
        return re.sub(r"\s*—.*$", "", field.group(1)).strip()
    return ""


def build_palette(text: str) -> tuple[dict[str, str], list[str]]:
    """Return (tokens, notes explaining each decision)."""
    cands = collect_colors(text)
    notes: list[str] = []
    taken: set[str] = set()

    if not cands:
        raise ValueError("nenhuma cor #rrggbb encontrada no documento de design")

    def take(cand: Candidate | None, role: str, reason: str) -> str | None:
        if cand is None:
            return None
        taken.add(cand.hex)
        notes.append(f"{role:14} {cand.hex}  ← {reason}")
        return cand.hex

    dark = lambda c: luminance(c.hex) < 0.35
    ink = take(*_resolve(cands, "ink", dark, taken,
                         fallback=lambda p: min(p, key=lambda c: luminance(c.hex)),
                         fallback_reason="cor mais escura do documento"))
    ink = ink or "#242828"

    branded = lambda c: saturation(c.hex) > 0.18 and 0.02 < luminance(c.hex) < 0.75
    accent = take(*_resolve(cands, "accent", branded, taken,
                            fallback=lambda p: max(p, key=lambda c: saturation(c.hex)),
                            fallback_reason="cor mais saturada do documento"))
    accent = accent or ink

    accent_2 = take(*_resolve(cands, "accent-2", branded, taken,
                              fallback=lambda p: max(p, key=lambda c: saturation(c.hex)),
                              fallback_reason="segunda cor mais saturada"))
    accent_2 = accent_2 or mix("#ffffff", accent, 0.45)

    light = lambda c: luminance(c.hex) > 0.75
    cover_ink = take(*_resolve(cands, "cover-ink", light, taken,
                               fallback=lambda p: max(p, key=lambda c: luminance(c.hex)),
                               fallback_reason="cor mais clara do documento"))
    cover_ink = cover_ink or "#ffffff"

    paper = "#ffffff"
    notes.append(f"{'paper':14} {paper}  ← fixo: impressão sobre papel branco")

    palette = {
        "ink": ink,
        "ink-soft": mix(ink, paper, 0.78),
        "ink-muted": mix(ink, paper, 0.55),
        "accent": accent,
        "accent-deep": mix("#000000", accent, 0.22),
        "accent-2": accent_2,
        "accent-2-ink": darken_until(accent_2, paper, 4.5),
        "paper": paper,
        "paper-alt": mix(ink, paper, 0.05),
        "hairline": mix(ink, paper, 0.18),
        "hairline-soft": mix(ink, paper, 0.10),
        "cover-ink": cover_ink,
        "cover-ink-soft": mix(cover_ink, accent, 0.74),
    }

    derived = ["ink-soft", "ink-muted", "accent-deep", "accent-2-ink",
               "paper-alt", "hairline", "hairline-soft", "cover-ink-soft"]
    notes.append("derivados da dupla tinta/papel: " + ", ".join(derived))

    ratio = contrast(palette["accent-2-ink"], paper)
    notes.append(f"accent-2-ink escurecido até {ratio:.1f}:1 sobre o papel (mín. 4.5)")

    return palette, notes


def _resolve(cands, role, predicate, taken, fallback, fallback_reason):
    chosen, reason = pick(cands, role, predicate, taken, fallback, fallback_reason)
    return chosen, role, reason


def analyse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    palette, notes = build_palette(text)
    fonts = extract_fonts(text)
    palette.update(fonts)
    for kind, stack in fonts.items():
        notes.append(f"{kind:14} {stack}")
    return {"colors": palette, "brand": extract_brand(text), "notes": notes}
