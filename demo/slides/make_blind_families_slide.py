"""Compose one demo slide from the 13 Sep closed-set recovery results."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SLIDES = Path(__file__).resolve().parent
OUT = SLIDES / "blind_families_results.png"


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\consola.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def panel_frame(draw: ImageDraw.ImageDraw, xy: tuple[int, int], size: tuple[int, int]) -> None:
    x, y = xy
    pw, ph = size
    draw.rectangle([x, y, x + pw, y + ph], fill="#121722", outline="#1c2433")
    tick = 10
    c = "#2b3850"
    draw.line([x, y, x + tick, y], fill=c, width=2)
    draw.line([x, y, x, y + tick], fill=c, width=2)
    draw.line([x + pw, y + ph, x + pw - tick, y + ph], fill=c, width=2)
    draw.line([x + pw, y + ph, x + pw, y + ph - tick], fill=c, width=2)


def badge(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fg: str,
    bg: str,
) -> None:
    x, y = xy
    tw = draw.textlength(text, font=font) + 16
    draw.rounded_rectangle([x, y, x + tw, y + 22], radius=3, fill=bg, outline=fg)
    draw.text((x + 8, y + 3), text, fill=fg, font=font)


def row(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    fonts: dict,
    value_color: str = "#3ecf8e",
    width: int = 520,
) -> None:
    draw.text((x, y), label, fill="#97a3b6", font=fonts["small"])
    draw.text((x + width - 8, y), value, fill=value_color, font=fonts["stat"], anchor="ra")
    draw.line([x, y + 28, x + width - 8, y + 28], fill="#1c2433", width=1)


def main() -> None:
    w, h = 1920, 1080
    canvas = Image.new("RGB", (w, h), "#0b0f14")
    draw = ImageDraw.Draw(canvas)

    fonts = {
        "title": load_font(34, bold=True),
        "label": load_font(14, bold=True),
        "kicker": load_font(13, bold=True),
        "body": load_font(16),
        "small": load_font(15),
        "stat": load_font(18, bold=True),
        "headline": load_font(22, bold=True),
        "footer": load_font(13),
    }

    draw.rectangle([0, 0, w, 88], fill="#121722")
    draw.rectangle([0, 86, w, 88], fill="#2b3850")
    draw.text((40, 18), "RAAYA", fill="#e8edf4", font=fonts["title"])
    draw.text((160, 28), "CLOSED, WITH NUMBERS", fill="#4db8d8", font=fonts["label"])
    draw.text(
        (40, 56),
        "The three SIH26147 items a judge could still attack  ·  "
        "recovered where they are algebraic, labelled where they are not",
        fill="#97a3b6",
        font=fonts["footer"],
    )
    draw.text((w - 40, 28), "SIH26147", fill="#5d6b80", font=fonts["label"], anchor="ra")

    margin = 36
    gap = 18
    content_top = 108
    strip_h = 118
    footer_h = 48
    card_h = h - footer_h - 18 - strip_h - gap - content_top
    card_w = (w - 2 * margin - 2 * gap) // 3

    cards = [
        {
            "kicker": "S4  ·  INTERLEAVERS",
            "title": "Pseudo-random",
            "lede": "A keyed permutation is not invertible from rank. Deployed “pseudo-random” tables are QPP, and that space is searchable.",
            "rows": [
                ("LTE table triples, K = 40..288", "16 / 16", "#3ecf8e"),
                ("Relative-prime  f2 = 0", "12 / 12", "#3ecf8e"),
                ("Off-table QPP coefficients", "12 / 12", "#3ecf8e"),
                ("Keyed random permutation", "period only  8 / 8", "#4db8d8"),
            ],
            "note": "From a QPSK WAV: qpp {period 96, f1 11, f2 24} in 2.4 s. Unstructured keys report the period and the key-space bound, then stop.",
        },
        {
            "kicker": "S5  ·  CODES",
            "title": "Blind LDPC",
            "lede": "Open-set H is still refused. Closed-set identification — which published matrix, at which offset — is the SIGINT problem, and it now runs from an upload.",
            "rows": [
                ("Catalogue ID, offset 37", "7 / 7", "#3ecf8e"),
                ("Junk streams refused", "7 / 7", "#3ecf8e"),
                ("WAV upload, named the code", "235 / 235 blocks", "#3ecf8e"),
                ("Upload path before this", "LDPC unreachable", "#e8a54b"),
            ],
            "note": "S5 now asks every registered decoder. A code not in the catalogue is “no catalogue match”, never the nearest entry.",
        },
        {
            "kicker": "S0 / S1  ·  SAMPLING",
            "title": "Where fs came from",
            "lede": "fs is a label on the time axis, not a property of the numbers. Relabel 200 kHz as 400 kHz and every dimensionless statistic stays put.",
            "rows": [
                ("WAV header / caller hint / default", "labelled", "#3ecf8e"),
                ("Waterfall tab", "renders", "#3ecf8e"),
                ("Absolute fs from samples", "not estimated", "#4db8d8"),
                ("Aliasing detector", "measured, not shipped", "#e8a54b"),
            ],
            "note": "Edge-power on 42 correctly sampled vs 12 aliased captures overlapped completely. A detector that says “consistent” on every aliased input is worse than none.",
        },
    ]

    for i, card in enumerate(cards):
        x = margin + i * (card_w + gap)
        y = content_top
        panel_frame(draw, (x, y), (card_w, card_h))
        draw.text((x + 24, y + 18), card["kicker"], fill="#4db8d8", font=fonts["kicker"])
        draw.text((x + 24, y + 42), card["title"], fill="#e8edf4", font=fonts["headline"])

        lede = card["lede"]
        words = lede.split()
        lines: list[str] = []
        cur = ""
        max_w = card_w - 48
        for word in words:
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=fonts["body"]) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        ty = y + 84
        for line in lines:
            draw.text((x + 24, ty), line, fill="#97a3b6", font=fonts["body"])
            ty += 22

        ry = y + 204
        row_bottom = y + card_h - 140
        row_step = (row_bottom - ry) // len(card["rows"])
        for label, value, color in card["rows"]:
            row(draw, x + 24, ry, label, value, fonts, value_color=color, width=card_w - 40)
            ry += row_step

        note_box = [x + 16, y + card_h - 118, x + card_w - 16, y + card_h - 16]
        draw.rounded_rectangle(note_box, radius=4, fill="#0b0f16", outline="#1c2433")
        nwords = card["note"].split()
        nlines: list[str] = []
        cur = ""
        nmax = card_w - 56
        for word in nwords:
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=fonts["footer"]) <= nmax:
                cur = trial
            else:
                if cur:
                    nlines.append(cur)
                cur = word
        if cur:
            nlines.append(cur)
        ny = y + card_h - 106
        for line in nlines[:5]:
            draw.text((x + 28, ny), line, fill="#97a3b6", font=fonts["footer"])
            ny += 18

    strip_y = content_top + card_h + gap
    panel_frame(draw, (margin, strip_y), (w - 2 * margin, strip_h))
    draw.text(
        (margin + 24, strip_y + 14),
        "THROUGH THE UPLOAD PATH, NO TRUTH FED IN",
        fill="#97a3b6",
        font=fonts["label"],
    )
    badge(draw, (margin + 360, strip_y + 12), "QPSK WAV  ·  20 dB", fonts["footer"], "#4db8d8", "#16303a")
    badge(draw, (margin + 530, strip_y + 12), "356 tests, 0 failures", fonts["footer"], "#3ecf8e", "#1a3a2a")

    draw.text(
        (margin + 24, strip_y + 48),
        "S4 recovered the LTE-style QPP  ·  S5 named gallager-n96-r1_2-963 and decoded every block  ·  "
        "S5 now tries every registered decoder, so Reed-Solomon is reachable too  ·  "
        "first-upload JIT compile (4.6 s) moved to startup",
        fill="#e8edf4",
        font=fonts["body"],
    )

    draw.rectangle([0, h - 48, w, h], fill="#121722")
    draw.text(
        (40, h - 32),
        "Limits, said out loud: unstructured keys are a theorem, not a missing feature  ·  "
        "LDPC is closed-set only  ·  absolute fs is not estimated  ·  synthetic streams",
        fill="#5d6b80",
        font=fonts["footer"],
    )
    draw.text(
        (w - 40, h - 32),
        "reports/pseudorandom_interleavers.md  ·  blind_ldpc.md  ·  sampling_rate.md",
        fill="#3ecf8e",
        font=fonts["footer"],
        anchor="ra",
    )

    canvas.save(OUT, "PNG", optimize=True)
    print(f"saved {OUT} ({OUT.stat().st_size} bytes) {canvas.size}")


if __name__ == "__main__":
    main()
