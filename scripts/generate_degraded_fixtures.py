import random
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "test-images"
OUTPUT = SOURCE / "degraded"
OUTPUT.mkdir(exist_ok=True)


def open_rgb(name: str) -> Image.Image:
    with Image.open(SOURCE / name) as image:
        return image.convert("RGB")


def save(image: Image.Image, name: str, quality: int = 72) -> None:
    image.save(OUTPUT / name, "JPEG", quality=quality, optimize=True)


eye_chart = open_rgb("english-eye-chart.jpg")
save(eye_chart.rotate(17, expand=True, fillcolor="white"), "english-rotated-17deg.jpg")
save(eye_chart.filter(ImageFilter.GaussianBlur(2.2)), "english-heavy-blur.jpg", 55)
save(ImageEnhance.Contrast(eye_chart).enhance(0.22), "english-low-contrast.jpg", 45)
save(eye_chart.resize((164, 204)).resize(eye_chart.size), "english-low-resolution.jpg", 35)

handwriting = open_rgb("english-handwriting.jpg")
quad = handwriting.transform(
    handwriting.size,
    Image.Transform.QUAD,
    (35, 0, handwriting.width - 5, 20, handwriting.width - 45, handwriting.height, 0, 70),
    resample=Image.Resampling.BICUBIC,
)
save(quad, "english-perspective-skew.jpg", 60)

gradient = Image.linear_gradient("L").rotate(90).resize(eye_chart.size)
gradient = gradient.point(lambda value: 70 + 185 * value // 255)
lighting = ImageChops.multiply(eye_chart, Image.merge("RGB", (gradient, gradient, gradient)))
save(lighting, "english-uneven-lighting.jpg", 58)

cropped = eye_chart.crop((35, 70, eye_chart.width - 20, eye_chart.height - 55))
save(ImageOps.expand(cropped, border=(0, 25, 65, 0), fill="white"), "english-partial-crop.jpg", 48)

oblique = handwriting.rotate(-31, expand=True, fillcolor="white")
save(ImageEnhance.Contrast(oblique).enhance(0.55), "english-oblique-handwriting.jpg", 42)

rng = random.Random(20260821)
noisy = handwriting.copy()
pixels = noisy.load()
for y in range(noisy.height):
    for x in range(noisy.width):
        if rng.random() < 0.07:
            value = rng.randrange(40, 220)
            pixels[x, y] = (value, value, value)
save(noisy, "english-scan-noise.jpg", 28)
