from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUTPUT = Path(__file__).resolve().parents[1] / "build" / "app.ico"
SCALE = 4
SIZE = 512


def rounded_rectangle(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def make_icon():
    canvas = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    rounded_rectangle(
        draw,
        (10 * SCALE, 10 * SCALE, 502 * SCALE, 502 * SCALE),
        112 * SCALE,
        (31, 111, 235, 255),
    )
    rounded_rectangle(
        draw,
        (50 * SCALE, 70 * SCALE, 462 * SCALE, 442 * SCALE),
        48 * SCALE,
        (255, 255, 255, 255),
    )

    draw.rounded_rectangle(
        (122 * SCALE, 54 * SCALE, 250 * SCALE, 105 * SCALE),
        radius=18 * SCALE,
        fill=(28, 39, 57, 255),
    )
    draw.rounded_rectangle(
        (94 * SCALE, 174 * SCALE, 418 * SCALE, 454 * SCALE),
        radius=45 * SCALE,
        fill=(28, 39, 57, 255),
    )

    for radius, width, color in (
        (104, 20, (232, 238, 249, 255)),
        (60, 18, (106, 156, 240, 255)),
        (25, 14, (232, 238, 249, 255)),
    ):
        box = (
            (256 - radius) * SCALE,
            (310 - radius) * SCALE,
            (256 + radius) * SCALE,
            (310 + radius) * SCALE,
        )
        draw.ellipse(box, outline=color, width=width * SCALE)

    font_path = Path(r"C:\Windows\Fonts\segoeuib.ttf")
    font = ImageFont.truetype(str(font_path), 78 * SCALE)
    label = "JPG"
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    text_width = right - left
    text_height = bottom - top
    text_x = (SIZE * SCALE - text_width) / 2
    text_y = 409 * SCALE - text_height / 2

    draw.rounded_rectangle(
        (
            text_x - 22 * SCALE,
            text_y - 15 * SCALE,
            text_x + text_width + 22 * SCALE,
            text_y + text_height + 18 * SCALE,
        ),
        radius=20 * SCALE,
        fill=(242, 148, 56, 255),
    )
    draw.text((text_x, text_y), label, font=font, fill=(255, 255, 255, 255))

    icon = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    icon.save(OUTPUT.with_suffix(".png"), format="PNG")
    print(OUTPUT)


if __name__ == "__main__":
    make_icon()
