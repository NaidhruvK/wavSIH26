"""Compose one submission slide from the three textpayload plots + recovered message."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SLIDES = Path(__file__).resolve().parent
OUT = SLIDES / "working_prototype_textpayload.png"

MESSAGE = (
    "RAAYA SIH26147 -- BLIND SIGNAL RECOVERY. This capture was demodulated, "
    "de-interleaved and decoded with no prior knowledge: the modulation, the "
    "interleaver depth and width, the code rate and both generator polynomials "
    "were all recovered from the waveform alone."
)


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


def fit(img: Image.Image, box_w: int, box_h: int, bg: str = "#171e2b") -> Image.Image:
    panel = Image.new("RGB", (box_w, box_h), bg)
    scale = min(box_w / img.width, box_h / img.height)
    nw = max(1, int(img.width * scale))
    nh = max(1, int(img.height * scale))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    panel.paste(resized, ((box_w - nw) // 2, (box_h - nh) // 2))
    return panel


def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    spectrum = Image.open(SLIDES / "textpayload_1_spectrum.png").convert("RGB")
    constel = Image.open(SLIDES / "textpayload_2_constellation.png").convert("RGB")
    rank = Image.open(SLIDES / "textpayload_3_rank_profile.png").convert("RGB")

    w, h = 1920, 1080
    canvas = Image.new("RGB", (w, h), "#0b0f14")
    draw = ImageDraw.Draw(canvas)

    font_title = load_font(34, bold=True)
    font_label = load_font(14, bold=True)
    font_payload = load_font(17)
    font_small = load_font(13)

    # Header
    draw.rectangle([0, 0, w, 88], fill="#121722")
    draw.rectangle([0, 86, w, 88], fill="#2b3850")
    draw.text((40, 18), "RAAYA", fill="#e8edf4", font=font_title)
    draw.text((160, 28), "WORKING PROTOTYPE", fill="#4db8d8", font=font_label)
    draw.text(
        (40, 56),
        "Blind RF demodulation  ·  rank-collapse coding recovery  ·  "
        "readable telemetry from the waveform alone",
        fill="#97a3b6",
        font=font_small,
    )
    draw.text((w - 40, 28), "SIH26147", fill="#5d6b80", font=font_label, anchor="ra")

    margin = 36
    gap = 18
    content_top = 104
    content_bottom = h - 56
    usable_h = content_bottom - content_top
    content_w = w - 2 * margin

    spec_h = int(usable_h * 0.36)
    mid_h = int(usable_h * 0.34)
    pay_h = usable_h - spec_h - mid_h - 2 * gap

    def panel_frame(xy: tuple[int, int], size: tuple[int, int]) -> None:
        x, y = xy
        pw, ph = size
        draw.rectangle([x, y, x + pw, y + ph], fill="#121722", outline="#1c2433")
        tick = 10
        c = "#2b3850"
        draw.line([x, y, x + tick, y], fill=c, width=2)
        draw.line([x, y, x, y + tick], fill=c, width=2)
        draw.line([x + pw, y + ph, x + pw - tick, y + ph], fill=c, width=2)
        draw.line([x + pw, y + ph, x + pw, y + ph - tick], fill=c, width=2)

    # Spectrum
    sx, sy = margin, content_top
    panel_frame((sx, sy), (content_w, spec_h))
    canvas.paste(fit(spectrum, content_w - 16, spec_h - 16), (sx + 8, sy + 8))

    # Constellation + rank
    half_w = (content_w - gap) // 2
    mx, my = margin, sy + spec_h + gap
    panel_frame((mx, my), (half_w, mid_h))
    canvas.paste(fit(constel, half_w - 16, mid_h - 16), (mx + 8, my + 8))

    rx = mx + half_w + gap
    panel_frame((rx, my), (half_w, mid_h))
    canvas.paste(fit(rank, half_w - 16, mid_h - 16), (rx + 8, my + 8))

    # Payload
    px, py = margin, my + mid_h + gap
    panel_frame((px, py), (content_w, pay_h))
    draw.text((px + 24, py + 14), "RECOVERED TELEMETRY PAYLOAD", fill="#97a3b6", font=font_label)

    badges = [
        (px + 280, "VALID TEXT LOCK", "#3ecf8e", "#1a3a2a"),
        (px + 440, "PRINTABLE 99.87%", "#4db8d8", "#16303a"),
        (px + 620, "QPSK · 20 dB · period 96 · 8×12 · rate ½ K=7", "#e8edf4", "#1c2433"),
    ]
    for bx, text, fg, bg in badges:
        tw = draw.textlength(text, font=font_small) + 16
        draw.rounded_rectangle(
            [bx, py + 12, bx + tw, py + 34], radius=3, fill=bg, outline=fg
        )
        draw.text((bx + 8, py + 15), text, fill=fg, font=font_small)

    msg_box = [px + 20, py + 48, px + content_w - 20, py + pay_h - 16]
    draw.rounded_rectangle(msg_box, radius=4, fill="#0b0f16", outline="#1c2433")

    lines = wrap(draw, MESSAGE, font_payload, content_w - 72)
    ty = py + 62
    for line in lines:
        draw.text((px + 36, ty), line, fill="#e8edf4", font=font_payload)
        ty += 26

    # Footer
    draw.rectangle([0, h - 48, w, h], fill="#121722")
    draw.text(
        (40, h - 32),
        "Capture: qpsk_20dB_textpayload.wav  ·  blind S0→S6 pipeline  ·  "
        "no prior knowledge of modulation, interleaver, or code",
        fill="#5d6b80",
        font=font_small,
    )
    draw.text(
        (w - 40, h - 32),
        "reproducible on a laptop CPU",
        fill="#3ecf8e",
        font=font_small,
        anchor="ra",
    )

    canvas.save(OUT, "PNG", optimize=True)
    print(f"saved {OUT} ({OUT.stat().st_size} bytes) {canvas.size}")


if __name__ == "__main__":
    main()
