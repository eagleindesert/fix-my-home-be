"""이미지 실형식 검사, 방향 정규화, 메타데이터 제거 및 비가역 마스킹."""

import io
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from app.errors import DomainError, require

MAX_BYTES = 10_000_000
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def normalize_image(data):
    require(len(data) <= MAX_BYTES, "FILE_TOO_LARGE", "사진은 10,000,000바이트 이하여야 합니다.", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                require(source.format in ("JPEG", "PNG"), "UNSUPPORTED_MEDIA_TYPE", "JPEG·PNG만 지원합니다.", 415)
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                require(source.width * source.height <= MAX_PIXELS, "UPLOAD_BATCH_REJECTED", "사진 해상도가 너무 큽니다.", 422)
                suggested = None
                raw_date = source.getexif().get(36867)
                if raw_date:
                    try:
                        from datetime import datetime
                        suggested = datetime.strptime(raw_date, "%Y:%m:%d %H:%M:%S").date().isoformat()
                    except (TypeError, ValueError):
                        pass
                pixels = ImageOps.exif_transpose(source).convert("RGB")
                clean = Image.new("RGB", pixels.size)
                clean.paste(pixels)
                output = io.BytesIO()
                clean.save(output, "JPEG", quality=92)
                return output.getvalue(), clean.width, clean.height, suggested
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise DomainError("UPLOAD_BATCH_REJECTED", "읽을 수 없는 이미지입니다.", 422)


def mask_image(data, boxes):
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        for box in boxes:
            validate_box(box)
            draw.rectangle((box[0] * image.width, box[1] * image.height,
                            box[2] * image.width, box[3] * image.height), fill="black")
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue(), image.width, image.height


def validate_box(box):
    require(isinstance(box, list) and len(box) == 4 and
            all(type(x) in (int, float) and 0 <= x <= 1 for x in box) and
            box[0] < box[2] and box[1] < box[3],
            "VALIDATION_ERROR", "사각형은 유효한 정규 좌표 4개여야 합니다.", 422)


class FileStore:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, key):
        require(isinstance(key, str) and key and key.replace("-", "").isalnum(),
                "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
        return self.root / key

    def write(self, content):
        if not isinstance(content, bytes):
            raise TypeError("저장할 파일은 bytes여야 합니다.")
        self.root.mkdir(parents=True, exist_ok=True)
        key = str(uuid4())
        target = self.path(key)
        try:
            with target.open("xb") as file:
                target.chmod(0o600)
                file.write(content)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return key

    def read(self, key):
        try:
            return self.path(key).read_bytes()
        except FileNotFoundError:
            raise DomainError("RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)
