"""Redistributable synthetic PDFs; no generator dependency or private documents."""

import zlib
from pathlib import Path


def create_pdf(
    path: Path,
    kinds: tuple[str, ...] = (
        "text",
        "mixed",
        "table",
        "scan",
        "empty",
        "logo",
        "columns",
        "rotated",
        "broken",
    ),
) -> Path:
    objects: list[bytes] = [
        b"",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    def add(value: bytes) -> int:
        objects.append(value)
        return len(objects)

    def stream(data: bytes, extra: bytes = b"") -> bytes:
        return (
            b"<< /Length "
            + str(len(data)).encode()
            + b" "
            + extra
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )

    # Real raster text on an image-only page, reusable small logo.
    from PIL import Image, ImageDraw, ImageFont

    with Image.new("RGB", (900, 1100), "white") as image:
        draw = ImageDraw.Draw(image)
        font = (
            ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
            if Path("C:/Windows/Fonts/arial.ttf").exists()
            else ImageFont.load_default(size=28)
        )
        for row in range(12):
            draw.text(
                (40, 70 + row * 55),
                f"Scanned evidence SCAN42 row {row}: revenue 120 units",
                font=font,
                fill="black",
            )
        image_id = add(
            stream(
                zlib.compress(image.tobytes()),
                b"/Type /XObject /Subtype /Image /Width 900 /Height 1100 "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode",
            )
        )
    pages = []
    for index, kind in enumerate(kinds):
        commands = []
        if kind not in ("scan", "empty"):
            commands.append("BT /F1 20 Tf 40 740 Td (Quarterly report) Tj ET")
            for row in range(15):
                value = (
                    f"Evidence row {row}: ALPHA42 revenue 120 units "
                    "and stable observations."
                )
                if kind == "columns":
                    value = "Left column observations."
                if kind == "broken":
                    value = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
                commands.append(f"BT /F1 11 Tf 40 {700 - row * 18} Td ({value}) Tj ET")
        if kind in ("mixed", "table"):
            for row in range(6):
                commands.append(f"40 {300 + row * 22} m 550 {300 + row * 22} l S")
            for col in range(5):
                commands.append(f"{40 + col * 125} 300 m {40 + col * 125} 410 l S")
        if kind == "columns":
            for row in range(12):
                commands.append(
                    f"BT /F1 10 Tf 330 {700 - row * 18} Td (Right column data.) Tj ET"
                )
        if kind == "logo":
            commands.append("q 20 0 0 20 560 750 cm /I1 Do Q")
        if kind == "scan":
            commands.append("q 600 0 0 780 0 0 cm /I1 Do Q")
        content = add(stream("\n".join(commands).encode()))
        rotation = " /Rotate 90" if kind == "rotated" else ""
        page = add(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
                f"/Resources << /Font << /F1 3 0 R >> "
                f"/XObject << /I1 {image_id} 0 R >> >> "
                f"/Contents {content} 0 R{rotation} >>"
            ).encode()
        )
        pages.append(page)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids ["
        + " ".join(f"{p} 0 R" for p in pages)
        + "] >>"
    ).encode()
    data = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
        ).encode()
    )
    path.write_bytes(data)
    return path
