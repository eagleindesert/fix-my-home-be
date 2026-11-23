"""사진과 한글 본문을 픽셀로 평탄화한 PDF. 숨은 텍스트·EXIF를 남기지 않는다."""

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.errors import require


def render_pdf(content, images, font_path):
    require(Path(font_path).is_file(), "PDF_FONT_UNAVAILABLE", "한글 PDF 글꼴이 설치되지 않았습니다.")
    font = ImageFont.truetype(str(font_path), 26)
    pages, page = [], Image.new("RGB", (1240, 1754), "white")
    draw, y = ImageDraw.Draw(page), 70

    def next_page():
        nonlocal page, draw, y
        pages.append(page)
        page = Image.new("RGB", (1240, 1754), "white")
        draw, y = ImageDraw.Draw(page), 70

    def paragraph(value):
        nonlocal y
        for source_line in value.splitlines():
            if source_line.startswith("```"):
                continue
            heading = re.match(r"^(#{1,6})\s+(.*)", source_line)
            line_font = ImageFont.truetype(str(font_path), 40 if heading and len(heading[1]) == 1 else 32) if heading else font
            line_height = 54 if heading else 38
            if heading:
                source_line = heading[2]
            source_line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", source_line)
            source_line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", source_line)
            source_line = re.sub(r"(?:\*\*|__|`)", "", source_line)
            source_line = re.sub(r"^\s*[-*+]\s+", "• ", source_line)
            line = ""
            for character in source_line:
                if draw.textlength(line+character, font=line_font) > 1100:
                    if y > 1640:
                        next_page()
                    draw.text((70, y), line, font=line_font, fill="black")
                    y += line_height
                    line = ""
                line += character
            if y > 1640:
                next_page()
            draw.text((70, y), line, font=line_font, fill="black")
            y += line_height

    report = content.get("report")
    require(report, "PDF_CONTENT_REQUIRED", "확인된 보고서가 필요합니다.")
    paragraph(report["content"]["markdown"])
    for photo in report["photos"]:
        data = images[photo["media"]["mediaId"]]
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGB")
            image.thumbnail((1100, 900))
        regions = photo.get("regions") or []
        if regions:
            overlay = ImageDraw.Draw(image)
            width, height = image.size
            for index, region in enumerate(regions, 1):
                x1, y1, x2, y2 = region["box"]
                rect = (
                    int(x1 * width),
                    int(y1 * height),
                    int(x2 * width),
                    int(y2 * height),
                )
                overlay.rectangle(rect, outline=(206, 80, 64), width=4)
                overlay.text((rect[0] + 6, max(2, rect[1] - 28)), f"#{index}", font=font, fill=(206, 80, 64))
        if y+image.height+100 > 1684:
            next_page()
        paragraph(f"촬영일: {photo['capturedOn'] or '미확인'}")
        page.paste(image, (70, y))
        y += image.height+15
        if photo.get("observation"):
            paragraph(photo["observation"])
        for index, region in enumerate(regions, 1):
            if region.get("description"):
                paragraph(f"관찰 영역 #{index}: {region['description']}")
    pages.append(page)
    output = io.BytesIO()
    pages[0].save(output, format="PDF", save_all=True, append_images=pages[1:], resolution=150,
                  title="고쳐야집 확인 보고서", author="", subject="", keywords="")
    return output.getvalue()
