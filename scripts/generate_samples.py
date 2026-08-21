from pathlib import Path

from PIL import Image, ImageDraw

SAMPLES = Path(__file__).parent.parent / "samples"
SAMPLES.mkdir(exist_ok=True)


def text_image(text: str, foreground: str = "black", background: str = "white") -> Image.Image:
    image = Image.new("RGB", (640, 180), background)
    ImageDraw.Draw(image).text((40, 70), text, fill=foreground, font_size=32)
    return image


text_image("Flexbone OCR sample 123").save(SAMPLES / "normal.jpg", quality=90)
text_image("Rotated OCR sample").rotate(90, expand=True).save(SAMPLES / "rotated.jpg", quality=90)
text_image("Low contrast sample", "#aaaaaa", "#dddddd").save(
    SAMPLES / "low-contrast.jpg", quality=85
)
Image.new("RGB", (640, 180), "white").save(SAMPLES / "blank.jpg", quality=90)
text_image("Unsupported PNG").save(SAMPLES / "unsupported.png")
(SAMPLES / "corrupt.jpg").write_bytes(b"\xff\xd8\xfftruncated")
