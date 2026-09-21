"""Read image dimensions without resizing or re-encoding the image payload."""

from io import BytesIO

from PIL import Image


def image_dimensions(data: bytes, media_type: str = "") -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return 0, 0


def image_payload_score(data: bytes, media_type: str = "") -> tuple[int, int]:
    width, height = image_dimensions(data, media_type)
    return width * height, len(data)
