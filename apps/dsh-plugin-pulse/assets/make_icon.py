"""生成安装面板的图标 assets/icon.ico（需要 Pillow，DSH 自带运行时已包含）。"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "icon.ico"
SIZE = 256


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 背景：深蓝圆角方块
    rounded(d, (8, 8, SIZE - 8, SIZE - 8), 48, (16, 24, 42, 255))
    # 顶部渐变条
    rounded(d, (8, 8, SIZE - 8, 92), 48, (75, 111, 255, 255))
    # 三张卡片的抽象图形
    for i, (x, y) in enumerate(((44, 108), (104, 108), (164, 108))):
        rounded(d, (x, y, x + 52, y + 52), 14, (28, 38, 62, 255))
        rounded(d, (x, y, x + 52, y + 52), 14, None)
        d.rounded_rectangle((x, y, x + 52, y + 52), radius=14, outline=(75, 111, 255, 255), width=3)
    # 底部箭头（安装）
    d.polygon([(128, 176), (176, 176), (152, 210)], fill=(111, 140, 255, 255))
    d.rectangle((144, 168, 160, 190), fill=(111, 140, 255, 255))

    font = None
    for name in ("seguisb.ttf", "segoeui.ttf", "arialbd.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            try:
                font = ImageFont.truetype(str(p), 64)
                break
            except Exception:
                pass
    if font:
        d.text((SIZE / 2, 62), "DSH", font=font, fill=(255, 255, 255, 255), anchor="mm")

    out = OUT.with_suffix(".png")
    img.save(out)
    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"icon -> {OUT}  (preview: {out})")


if __name__ == "__main__":
    main()
