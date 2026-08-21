# Online OCR test images

These images are redistribution-safe OCR fixtures downloaded from Wikimedia Commons. Each source page describes the work as public domain.

| File | Test case | Source |
|---|---|---|
| `english-eye-chart.jpg` | Clean, progressively smaller Latin letters | [Eye-chart.jpg](https://commons.wikimedia.org/wiki/File:Eye-chart.jpg) |
| `english-handwriting.jpg` | Historical English handwriting | [Charlotte Brontë letter sample](https://commons.wikimedia.org/wiki/File:Example_of_handwritten_%C5%BF_in_a_letter_from_Charlotte_Bront%C3%AB.jpg) |

The original files are kept unchanged. The API accepts them because both are JPEG images under the 10 MiB limit.

## Degraded variants

The `degraded/` folder contains deterministic derivatives for difficult OCR cases:

- 17-degree rotation
- heavy blur
- low contrast
- low resolution and JPEG artifacts
- perspective skew
- uneven lighting
- partial crop
- scan noise

Regenerate them with `uv run python scripts/generate_degraded_fixtures.py`. They inherit the public-domain status of their source images.
