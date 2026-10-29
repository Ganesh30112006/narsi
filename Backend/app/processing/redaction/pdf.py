"""True PDF redaction: content under each target is removed, not merely covered.

PyMuPDF's apply_redactions() deletes the text, and (with PDF_REDACT_IMAGE_PIXELS) blanks the image
pixels, beneath each redaction rectangle. Metadata, embedded files and annotations are also removed.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.core.enums import RedactionAction
from app.core.exceptions import RedactionError
from app.processing.redaction.targets import RedactionTarget

_BLACK = (0.0, 0.0, 0.0)
_WHITE = (1.0, 1.0, 1.0)


#: A blacked-out region renders almost entirely dark; anti-aliasing at its edges is allowed for.
OPAQUE_SHARE = 0.97
_DARK = 48


def opaque_share(samples: bytes) -> float:
    if not samples:
        return 1.0
    return sum(samples.count(bytes([value])) for value in range(_DARK)) / len(samples)


def uncovered_pdf_regions(sanitized: Path, targets: list[RedactionTarget]) -> list[str]:
    """Finding ids whose region in the sanitized PDF isn't an opaque block (for photos, QR codes, signatures)."""
    document = pymupdf.open(str(sanitized), filetype="pdf")
    leaked: list[str] = []
    try:
        for target in targets:
            if not 1 <= target.page_number <= document.page_count:
                leaked.append(target.finding_id)
                continue
            page = document[target.page_number - 1]
            for rect in target.rects:
                # Inset by a point so the edge of the block isn't sampled together with what surrounds it.
                clip = pymupdf.Rect(rect.x0 + 1, rect.y0 + 1, rect.x1 - 1, rect.y1 - 1) & page.rect
                if clip.is_empty:
                    continue
                pixmap = page.get_pixmap(clip=clip, dpi=72, colorspace=pymupdf.csGRAY, alpha=False)
                if opaque_share(pixmap.samples) < OPAQUE_SHARE:
                    leaked.append(target.finding_id)
                    break
    finally:
        document.close()
    return leaked


def redact_pdf(source: Path, destination: Path, targets: list[RedactionTarget]) -> None:
    try:
        document = pymupdf.open(str(source), filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise RedactionError("The original PDF could not be opened.") from exc
    try:
        # Value-based: every text-layer occurrence of a selected value is redacted, not only the detected one.
        raws = {target.raw for target in targets if target.raw}
        for index in range(document.page_count):
            page = document[index]
            pending: list[tuple[pymupdf.Rect, RedactionTarget]] = []
            for target in targets:
                if target.page_number == page.number + 1:
                    pending.extend((pymupdf.Rect(r.x0, r.y0, r.x1, r.y1), target) for r in target.rects)
            for raw in raws:
                owner = next(target for target in targets if target.raw == raw)
                for rect in page.search_for(raw):
                    # Skip occurrences already covered by a detected location.
                    if not any((existing & rect).get_area() > 0.5 * rect.get_area() for existing, _ in pending):
                        pending.append((rect, owner))
            for rect, target in pending:
                padded = rect + (-1, -1, 1, 1)  # noqa: RUF005 (PyMuPDF Rect padding, not concatenation)
                if target.action is RedactionAction.MASK and not target.visual:
                    size = max(4.0, min(11.0, padded.height * 0.7))
                    page.add_redact_annot(
                        padded, text=target.masked, fontname="helv", fontsize=size, fill=_WHITE, text_color=_BLACK
                    )
                else:
                    page.add_redact_annot(padded, fill=_BLACK)
            if pending:
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)  # type: ignore[attr-defined]
            for annot in list(page.annots() or []):
                page.delete_annot(annot)

        document.set_metadata({})
        document.del_xml_metadata()
        for name in document.embfile_names():
            document.embfile_del(name)
        document.save(str(destination), garbage=4, deflate=True, clean=True)
    except (RuntimeError, ValueError) as exc:
        raise RedactionError() from exc
    finally:
        document.close()
