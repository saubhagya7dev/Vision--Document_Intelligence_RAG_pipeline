"""Frozen fictional document families, with disjoint development/held-out groups."""

import json
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FAMILIES = [
    ("train", "orion", "rotor", "AX17", 73, "newtons"),
    ("train", "kepler", "freight", "FX52", 240, "crates"),
    ("train", "cedar", "inventory", "LT29", 42, "units"),
    ("train", "morrow", "contract", "VX31", 15, "days"),
    ("test", "selene", "solar", "PV86", 19, "volts"),
    ("test", "harbor", "archive", "RA64", 9, "years"),
    ("test", "delta", "reservoir", "WL58", 27, "centimeters"),
    ("test", "tundra", "sensor", "TS92", 64, "degrees"),
]


def pdf(path: Path, texts: list[list[str]], scan: list[str] | None = None) -> None:
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]

    def add(value):
        objects.append(value)
        return len(objects)

    def stream(value, extra=b""):
        return (
            b"<< /Length "
            + str(len(value)).encode()
            + b" "
            + extra
            + b" >>\nstream\n"
            + value
            + b"\nendstream"
        )

    image_id = None
    if scan:
        with Image.new("RGB", (1000, 1200), "white") as image:
            draw = ImageDraw.Draw(image)
            font = (
                ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 32)
                if Path("C:/Windows/Fonts/arial.ttf").exists()
                else ImageFont.load_default(size=28)
            )
            for row, line in enumerate(scan):
                draw.text((60, 100 + row * 70), line, font=font, fill="black")
            image_id = add(
                stream(
                    zlib.compress(image.tobytes()),
                    b"/Type /XObject /Subtype /Image /Width 1000 /Height 1200 "
                    b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode",
                )
            )
    pages = []
    for number, lines in enumerate(texts):
        commands = []
        for row, line in enumerate(lines):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(
                f"BT /F1 {20 if row == 0 else 13} Tf 45 "
                f"{740 - row * 30} Td ({safe}) Tj ET"
            )
        if len(texts) > 1 and number == 1:
            for y in range(380, 651, 45):
                commands.append(f"40 {y} m 550 {y} l S")
            for x in (40, 270, 550):
                commands.append(f"{x} 380 m {x} 650 l S")
        if len(texts) > 1 and number == 2:
            commands.extend(
                ["0 0 1 rg 120 250 110 300 re f", "1 0 0 rg 340 250 110 120 re f"]
            )
        if not lines and image_id:
            commands.append("q 600 0 0 780 0 0 cm /I1 Do Q")
        content = add(stream("\n".join(commands).encode()))
        xobject = f"/XObject << /I1 {image_id} 0 R >>" if image_id else ""
        pages.append(
            add(
                (
                    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
                    f"/Resources << /Font << /F1 3 0 R >> {xobject} >> "
                    f"/Contents {content} 0 R >>"
                ).encode()
            )
        )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        f"<< /Type /Pages /Count {len(pages)} /Kids ["
        + " ".join(f"{n} 0 R" for n in pages)
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


def create(root: Path) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    questions = []
    for split, family, subject, code, value, unit in FAMILIES:
        main, annex = f"{family}-report.pdf", f"{family}-annex.pdf"
        pdf(
            root / main,
            [
                [
                    f"{family.title()} {subject} report",
                    f"Equipment identifier {code}.",
                    f"The approved operating limit is {value} {unit}.",
                    "This is fictional evaluation evidence, not operational guidance.",
                ],
                [
                    f"{family.title()} parts table",
                    f"Item {code} has replacement interval 18 months.",
                    "Table heading: item identifier and replacement interval.",
                ],
                [
                    f"{family.title()} comparison chart",
                    "Observed output: blue series and red series.",
                    "The two colored bars show the measured comparison.",
                ],
                [],
            ],
            [
                f"{family.title()} scanned registration",
                f"Equipment {code}",
                f"Registration code {code}ZX9",
                "Signature: Inspector Vale",
            ],
        )
        pdf(
            root / annex,
            [
                [
                    f"{family.title()} {subject} annex",
                    f"Equipment identifier {code}.",
                    f"The revised operating limit is {value + 2} {unit}.",
                    "This is a separate report, not a replacement version.",
                ]
            ],
        )
        samples = [
            (
                f"What is the approved operating limit of {family} {code}?",
                [[main, 1]],
                str(value),
            ),
            (
                f"For item {code}, what is the replacement interval "
                f"in the {family} parts table?",
                [[main, 2]],
                "18",
            ),
            (
                f"In the {family} comparison chart, is the blue bar or red bar taller?",
                [[main, 3]],
                "blue",
            ),
            (
                f"Read the registration code for {code} "
                f"on the {family} scanned registration.",
                [[main, 4]],
                code + "ZX9",
            ),
            (
                f"Compare the approved limit in {family} report "
                "with its annex; cite both documents.",
                [[main, 1], [annex, 1]],
                f"{value},{value + 2}",
            ),
            (
                f"What is the private passport number of the {family} inspector?",
                [],
                "abstain",
            ),
        ]
        for index, (query, gold, expected) in enumerate(samples):
            questions.append(
                {
                    "id": f"{family}-{index}",
                    "split": split,
                    "family": family,
                    "query": query,
                    "gold": gold,
                    "expected": expected,
                    "documents": [main, annex] if index == 4 else [main],
                }
            )
    return questions


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = create(args.output)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
