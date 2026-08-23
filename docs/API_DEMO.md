# API demo

Base URL: `https://api.ocr.lelbaba.top`

---

## 1. Clean printed text

```bash
curl -X POST -F 'image=@samples/normal.jpg;type=image/jpeg' \
  https://api.ocr.lelbaba.top/extract-text | jq
```

Input — `samples/normal.jpg`

![samples/normal.jpg](../samples/normal.jpg)

`200`

```json
{
    "success": true,
    "text": "Flexbone OCR sample 123",
    "confidence": 0.9874678403139114,
    "processing_time_ms": 468
}
```

---

## 2. Metadata and normalized text

```bash
curl -X POST -F 'image=@test-images/english-eye-chart.jpg;type=image/jpeg' \
  'https://api.ocr.lelbaba.top/extract-text?metadata=true&normalize=true' | jq
```

Input — `test-images/english-eye-chart.jpg`

![test-images/english-eye-chart.jpg](../test-images/english-eye-chart.jpg)

`200`

```json
{
    "success": true,
    "text": "22\n10\n50\nZSHC\nHSKRN\n*CHKRVD\nנו\n25\n의원\n15\nHON SDC V\nOKHDNRCS\nV HD NKUOSRC\nBDCLK Z VHS ROA\nHKGB CANOM PVESR\nPKUE OBTV XRM JHCAZDI\nDKNT WUL JSP XV MRAHCFOYZ G",
    "confidence": 0.9301613588963659,
    "processing_time_ms": 549,
    "normalized_text": "22\n10\n50\nZSHC\nHSKRN\n*CHKRVD\nנו\n25\n의원\n15\nHON SDC V\nOKHDNRCS\nV HD NKUOSRC\nBDCLK Z VHS ROA\nHKGB CANOM PVESR\nPKUE OBTV XRM JHCAZDI\nDKNT WUL JSP XV MRAHCFOYZ G",
    "metadata": {
        "width": 328,
        "height": 409,
        "byte_size": 36294,
        "color_mode": "RGB",
        "format": "JPEG"
    }
}
```

---

## 3. Handwriting

```bash
curl -X POST -F 'image=@test-images/english-handwriting.jpg;type=image/jpeg' \
  'https://api.ocr.lelbaba.top/extract-text?normalize=true' | jq
```

Input — `test-images/english-handwriting.jpg`

![test-images/english-handwriting.jpg](../test-images/english-handwriting.jpg)

`200`

```json
{
    "success": true,
    "text": "Miss Austin's.",
    "confidence": 0.738329543517186,
    "processing_time_ms": 500,
    "normalized_text": "Miss Austin's."
}
```

---

## 4. Image with no text

```bash
curl -X POST -F 'image=@samples/blank.jpg;type=image/jpeg' \
  https://api.ocr.lelbaba.top/extract-text | jq
```

Input — `samples/blank.jpg`

![samples/blank.jpg](../samples/blank.jpg)

`200`

```json
{
    "success": true,
    "text": "",
    "confidence": 0.0,
    "processing_time_ms": 157
}
```

---

## 5. Unsupported format

```bash
curl -X POST -F 'image=@samples/unsupported.bmp;type=image/bmp' \
  https://api.ocr.lelbaba.top/extract-text | jq
```

Input — `samples/unsupported.bmp` (BMP, 640×180, 345,654 bytes)

`415`

```json
{
    "success": false,
    "error": {
        "code": "unsupported_image_format",
        "message": "Only JPG/JPEG, PNG, and GIF images are supported."
    },
    "processing_time_ms": 3
}
```

---

## 6. Corrupt file

```bash
curl -X POST -F 'image=@samples/corrupt.jpg;type=image/jpeg' \
  https://api.ocr.lelbaba.top/extract-text | jq
```

Input — `samples/corrupt.jpg` (12 bytes, not a decodable image)

`422`

```json
{
    "success": false,
    "error": {
        "code": "corrupt_image",
        "message": "The image is corrupt or unreadable."
    },
    "processing_time_ms": 2
}
```

---

## 7. Missing image field

```bash
curl -X POST https://api.ocr.lelbaba.top/extract-text | jq
```

Input — none

`400`

```json
{
    "success": false,
    "error": {
        "code": "malformed_request",
        "message": "A valid multipart request with one 'image' field is required."
    },
    "processing_time_ms": 1
}
```

---

## 8. Image too large

```bash
curl -X POST -F 'image=@samples/too-large.jpg;type=image/jpeg' \
  https://api.ocr.lelbaba.top/extract-text | jq
```

Input — `samples/too-large.jpg` (JPEG, 5472×3648, 17,315,594 bytes)

`413`

```json
{
    "success": false,
    "error": {
        "code": "request_too_large",
        "message": "The request body is too large."
    },
    "processing_time_ms": 0
}
```

At 16.5 MiB the upload is over the 11 MiB body limit for `/extract-text`
(10 MiB per image plus 1 MiB of multipart overhead), so it is rejected on the
`Content-Length` header before any bytes are read or decoded. An image that
clears the body limit but still exceeds 10 MiB of image data comes back as
`image_too_large`, and one that decodes to more than 40 MP as
`image_dimensions_too_large` — both also `413`.

---

## 9. Batch of four images, including a PNG and a GIF

```bash
curl -X POST \
  -F 'images=@samples/normal.jpg;type=image/jpeg' \
  -F 'images=@samples/rotated.jpg;type=image/jpeg' \
  -F 'images=@samples/supported.png;type=image/png' \
  -F 'images=@samples/animated.gif;type=image/gif' \
  'https://api.ocr.lelbaba.top/extract-text/batch?metadata=true&normalize=true' | jq
```

Input — `samples/normal.jpg`

![samples/normal.jpg](../samples/normal.jpg)

Input — `samples/rotated.jpg`

![samples/rotated.jpg](../samples/rotated.jpg)

Input — `samples/supported.png`

![samples/supported.png](../samples/supported.png)

Input — `samples/animated.gif`

![samples/animated.gif](../samples/animated.gif)

`200`

```json
{
  "success": true,
  "results": [
    {
      "index": 0,
      "status_code": 200,
      "success": true,
      "processing_time_ms": 452,
      "text": "Flexbone OCR sample 123",
      "confidence": 0.9875559538602829,
      "normalized_text": "Flexbone OCR sample 123",
      "metadata": {
        "width": 640,
        "height": 180,
        "byte_size": 9212,
        "color_mode": "RGB",
        "format": "JPEG"
      }
    },
    {
      "index": 1,
      "status_code": 200,
      "success": true,
      "processing_time_ms": 447,
      "text": "Rotated OCR sample",
      "confidence": 0.9836493544280529,
      "normalized_text": "Rotated OCR sample",
      "metadata": {
        "width": 180,
        "height": 640,
        "byte_size": 7719,
        "color_mode": "RGB",
        "format": "JPEG"
      }
    },
    {
      "index": 2,
      "status_code": 200,
      "success": true,
      "processing_time_ms": 919,
      "text": "Supported PNG sample",
      "confidence": 0.9805325170358022,
      "normalized_text": "Supported PNG sample",
      "metadata": {
        "width": 640,
        "height": 180,
        "byte_size": 5898,
        "color_mode": "RGB",
        "format": "PNG"
      }
    },
    {
      "index": 3,
      "status_code": 200,
      "success": true,
      "processing_time_ms": 927,
      "text": "Animated GIF first frame",
      "confidence": 0.9779800318536305,
      "normalized_text": "Animated GIF first frame",
      "metadata": {
        "width": 640,
        "height": 180,
        "byte_size": 7952,
        "color_mode": "P",
        "format": "GIF"
      }
    }
  ],
  "processing_time_ms": 929
}
```

---

## 10. Batch with partial failure

```bash
curl -X POST \
  -F 'images=@samples/normal.jpg;type=image/jpeg' \
  -F 'images=@samples/corrupt.jpg;type=image/jpeg' \
  -F 'images=@samples/unsupported.bmp;type=image/bmp' \
  https://api.ocr.lelbaba.top/extract-text/batch | jq
```

Input — `samples/normal.jpg`

![samples/normal.jpg](../samples/normal.jpg)

Input — `samples/corrupt.jpg` (12 bytes, not a decodable image)

Input — `samples/unsupported.bmp` (BMP, 640×180, 345,654 bytes)

`200`

```json
{
    "success": true,
    "results": [
        {
            "index": 0,
            "status_code": 200,
            "success": true,
            "processing_time_ms": 251,
            "text": "Flexbone OCR sample 123",
            "confidence": 0.9875559538602829
        },
        {
            "index": 1,
            "status_code": 422,
            "success": false,
            "processing_time_ms": 2,
            "error": {
                "code": "corrupt_image",
                "message": "The image is corrupt or unreadable."
            }
        },
        {
            "index": 2,
            "status_code": 415,
            "success": false,
            "processing_time_ms": 1,
            "error": {
                "code": "unsupported_image_format",
                "message": "Only JPG/JPEG, PNG, and GIF images are supported."
            }
        }
    ],
    "processing_time_ms": 253
}
```

---

## 11. Health check

```bash
curl https://api.ocr.lelbaba.top/health
```

Input — none

`200`

```json
{
    "status": "ok"
}
```
