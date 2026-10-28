"""A minimal PDF writer: text, lines, rectangles and QR codes, no new dependency.

PLAN.md decision 6 rules out a PDF library, and every document this platform prints
(degree certificate, student record, regulatory summary) only needs the base-14
Helvetica fonts, rules, boxes and a QR code. The QR is drawn as vector squares from the
``qrcode`` matrix, so it stays sharp at any print size.

Coordinates are PDF points (1/72 inch) with the origin at the TOP-left, which is how a
layout is naturally written; the conversion to PDF's bottom-left origin happens here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import qrcode

A4 = (595.28, 841.89)

# Advance widths (1/1000 em) for ASCII 32..126, from the standard Helvetica AFM files.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
_HELVETICA_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)
FONTS = {"regular": ("F1", "Helvetica", _HELVETICA), "bold": ("F2", "Helvetica-Bold", _HELVETICA_BOLD)}

Color = tuple[float, float, float]
BLACK: Color = (0.06, 0.09, 0.16)
MUTED: Color = (0.28, 0.33, 0.41)
LINE: Color = (0.80, 0.84, 0.88)


def _encode(text: str) -> bytes:
    """WinAnsi bytes for a PDF literal string, with the three special bytes escaped."""
    raw = str(text).encode("cp1252", errors="replace")
    out = bytearray()
    for byte in raw:
        if byte in b"\\()":
            out += b"\\" + bytes([byte])
        elif byte < 32 or byte > 126:
            out += f"\\{byte:03o}".encode("ascii")
        else:
            out.append(byte)
    return bytes(out)


def text_width(text: str, size: float, weight: str = "regular") -> float:
    widths = FONTS[weight][2]
    total = 0
    for char in str(text):
        code = ord(char)
        if 32 <= code <= 126:
            total += widths[code - 32]
        elif char in "—–":
            total += 1000 if char == "—" else 556
        else:
            total += 556
    return total * size / 1000.0


def wrap(text: str, width: float, size: float, weight: str = "regular") -> list[str]:
    """Greedy word wrap to ``width`` points."""
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and text_width(candidate, size, weight) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


@dataclass
class Page:
    width: float
    height: float
    ops: list[bytes] = field(default_factory=list)


class PdfDocument:
    """Accumulate pages of drawing operations, then serialise with ``to_bytes()``."""

    def __init__(self, *, title: str, size: tuple[float, float] = A4) -> None:
        self.title = title
        self.size = size
        self.pages: list[Page] = []
        self.new_page()

    @property
    def page(self) -> Page:
        return self.pages[-1]

    @property
    def width(self) -> float:
        return self.size[0]

    @property
    def height(self) -> float:
        return self.size[1]

    def new_page(self) -> Page:
        self.pages.append(Page(*self.size))
        return self.page

    def _y(self, y: float) -> float:
        return self.page.height - y

    # ------------------------------------------------------------------ drawing

    def text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        size: float = 10,
        weight: str = "regular",
        color: Color = BLACK,
        align: str = "left",
    ) -> None:
        """Draw one line with its baseline at ``y`` (top-origin)."""
        if align != "left":
            width = text_width(text, size, weight)
            x = x - width / 2 if align == "center" else x - width
        font = FONTS[weight][0]
        r, g, b = color
        self.page.ops.append(
            f"BT {_num(r)} {_num(g)} {_num(b)} rg /{font} {_num(size)} Tf "
            f"{_num(x)} {_num(self._y(y))} Td (".encode("ascii")
            + _encode(text)
            + b") Tj ET"
        )

    def paragraph(
        self,
        x: float,
        y: float,
        text: str,
        *,
        width: float,
        size: float = 10,
        weight: str = "regular",
        color: Color = BLACK,
        leading: float | None = None,
        align: str = "left",
    ) -> float:
        """Wrapped text; returns the y just below the last line."""
        leading = leading or size * 1.4
        anchor = x + width / 2 if align == "center" else x
        for line in wrap(text, width, size, weight):
            self.text(anchor, y, line, size=size, weight=weight, color=color, align=align)
            y += leading
        return y

    def line(
        self, x1: float, y1: float, x2: float, y2: float, *, width: float = 0.75, color: Color = LINE
    ) -> None:
        r, g, b = color
        self.page.ops.append(
            f"{_num(r)} {_num(g)} {_num(b)} RG {_num(width)} w "
            f"{_num(x1)} {_num(self._y(y1))} m {_num(x2)} {_num(self._y(y2))} l S".encode("ascii")
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: Color | None = None,
        stroke: Color | None = None,
        line_width: float = 0.75,
    ) -> None:
        """Rectangle whose top-left corner is (x, y)."""
        parts: list[str] = []
        if fill:
            parts.append(f"{_num(fill[0])} {_num(fill[1])} {_num(fill[2])} rg")
        if stroke:
            parts.append(f"{_num(stroke[0])} {_num(stroke[1])} {_num(stroke[2])} RG {_num(line_width)} w")
        parts.append(f"{_num(x)} {_num(self._y(y + h))} {_num(w)} {_num(h)} re")
        parts.append("B" if fill and stroke else ("f" if fill else "S"))
        self.page.ops.append(" ".join(parts).encode("ascii"))

    def qr(self, x: float, y: float, size: float, data: str, *, color: Color = (0, 0, 0)) -> None:
        """A QR code as vector squares, top-left at (x, y), ``size`` points square."""
        code = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
        code.add_data(data)
        code.make(fit=True)
        matrix = code.get_matrix()
        module = size / len(matrix)
        r, g, b = color
        ops = [f"{_num(r)} {_num(g)} {_num(b)} rg"]
        for row_index, row in enumerate(matrix):
            column = 0
            while column < len(row):
                if not row[column]:
                    column += 1
                    continue
                start = column
                while column < len(row) and row[column]:
                    column += 1
                # Merge a run of dark modules into one rectangle; overlap a hair so no
                # hairline gaps appear between rows in some viewers.
                ops.append(
                    f"{_num(x + start * module)} {_num(self._y(y + (row_index + 1) * module))} "
                    f"{_num((column - start) * module)} {_num(module + 0.05)} re"
                )
        ops.append("f")
        self.page.ops.append("\n".join(ops).encode("ascii"))

    # ------------------------------------------------------------------ output

    def to_bytes(self) -> bytes:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")  # placeholders, filled once the page ids are known
        pages_id = add(b"")
        font_ids = {
            name: add(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode()
            )
            for name, base, _ in FONTS.values()
        }
        fonts = " ".join(f"/{name} {obj} 0 R" for name, obj in font_ids.items())

        page_ids: list[int] = []
        for page in self.pages:
            stream = b"\n".join(page.ops)
            content_id = add(
                f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
            )
            page_ids.append(
                add(
                    f"<< /Type /Page /Parent {pages_id} 0 R "
                    f"/MediaBox [0 0 {_num(page.width)} {_num(page.height)}] "
                    f"/Resources << /Font << {fonts} >> >> /Contents {content_id} 0 R >>".encode()
                )
            )
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        info = add(
            b"<< /Title (" + _encode(self.title) + b") /Producer (APAAR platform prototype) >>"
        )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
        return bytes(out)
