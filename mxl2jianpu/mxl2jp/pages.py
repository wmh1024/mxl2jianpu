"""Render PDF pages to images so a vision model can read the printed score.

The whole point of the review loop is comparing the printed score against the
machine's understanding of it, so the agent needs to *see* the pages. These
helpers turn a PDF into PNGs at a chosen resolution and crop regions for a
closer look, using whichever PDF renderer is installed.
"""
from __future__ import annotations

from pathlib import Path


def _renderer():
    """Return (name, module) for an available PDF renderer."""
    try:
        import pymupdf  # noqa: F401
        return 'pymupdf', pymupdf
    except ImportError:
        pass
    try:
        import pypdfium2
        return 'pypdfium2', pypdfium2
    except ImportError:
        pass
    raise RuntimeError(
        'no PDF renderer found; install pymupdf (pip install pymupdf) '
        'or pypdfium2 — a vision model needs page images to compare against')


def page_count(pdf: str | Path) -> int:
    name, mod = _renderer()
    if name == 'pymupdf':
        with mod.open(str(pdf)) as doc:
            return len(doc)
    return len(mod.PdfDocument(str(pdf)))


def render_pages(pdf: str | Path, out_dir: str | Path, dpi: int = 150,
                 pages: str | None = None, prefix: str | None = None) -> list[Path]:
    """Write one PNG per page. `pages` is 'all', a number, or '2-4'.

    Returns the written paths in page order. Raises when the input is not a PDF
    or when no page was selected — silently writing nothing would let a caller
    believe it had inspected a score it never saw.
    """
    pdf, out_dir = Path(pdf), Path(out_dir)
    if not pdf.exists():
        raise FileNotFoundError(f'{pdf} does not exist')
    with open(pdf, 'rb') as fh:
        head = fh.read(5)
    if head != b'%PDF-':
        raise ValueError(
            f'{pdf} is not a PDF (starts with {head[:4]!r}); `pages` renders the '
            f'printed score. Pass the source PDF, not the MusicXML.')
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = prefix or pdf.stem

    name, mod = _renderer()
    written: list[Path] = []

    def wanted(i: int) -> bool:
        if not pages or pages == 'all':
            return True
        return i in _parse_pages(pages)

    if name == 'pymupdf':
        with mod.open(str(pdf)) as doc:
            for i in range(len(doc)):
                if not wanted(i + 1):
                    continue
                out = out_dir / f'{prefix}-p{i + 1}.png'
                doc[i].get_pixmap(dpi=dpi).save(str(out))
                written.append(out)
    else:
        doc = mod.PdfDocument(str(pdf))
        for i in range(len(doc)):
            if not wanted(i + 1):
                continue
            out = out_dir / f'{prefix}-p{i + 1}.png'
            doc[i].render(scale=dpi / 72).to_pil().save(str(out))
            written.append(out)

    if not written:
        raise ValueError(
            f'no page rendered from {pdf} with --pages {pages!r}; '
            f'the document has {page_count(pdf)} page(s)')
    return written


def _parse_pages(spec: str) -> set[int]:
    """'1,3-5' -> {1,3,4,5} (1-based)."""
    out: set[int] = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def crop_region(pdf: str | Path, page: int, box: tuple[float, float, float, float],
                out_path: str | Path, zoom: float = 3.0) -> Path:
    """Crop one region of one page and save it, enlarged.

    `box` is (x0, y0, x1, y1) as fractions of the page, measured from the
    top-left, which is how a person describes a spot on a page. Zooming is
    what makes a bar line, a time signature or an accidental legible.
    """
    pdf, out_path = Path(pdf), Path(out_path)
    if not pdf.exists():
        raise FileNotFoundError(f'{pdf} does not exist')
    with open(pdf, 'rb') as fh:
        head = fh.read(5)
    if head != b'%PDF-':
        raise ValueError(
            f'{pdf} is not a PDF; `crop` works on the printed score '
            f'(.pdf), not on the MusicXML')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = box
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f'box must be fractions within the page, got {box}')

    name, mod = _renderer()
    if name == 'pymupdf':
        with mod.open(str(pdf)) as doc:
            p = doc[page - 1]
            w, h = p.rect.width, p.rect.height
            clip = mod.Rect(x0 * w, y0 * h, x1 * w, y1 * h)
            pix = p.get_pixmap(matrix=mod.Matrix(zoom, zoom), clip=clip)
            pix.save(str(out_path))
    else:
        doc = mod.PdfDocument(str(pdf))
        p = doc[page - 1]
        w, h = p.get_size()
        bmp = p.render(scale=zoom,
                       crop=(x0 * w, y0 * h, x1 * w, y1 * h))
        bmp.to_pil().save(str(out_path))
    return out_path


def section_of_page(page: int, systems_per_page: int = 9,
                    system: int | None = None) -> tuple[float, float]:
    """Vertical band (y0, y1) of one system on a page, as fractions.

    Scores are laid out in systems stacked down the page; this gives a band
    that covers roughly one of them, so an agent can crop the system it needs
    instead of guessing coordinates from scratch.
    """
    if system is None:
        return 0.0, 1.0
    top, bottom = 0.08, 0.94
    height = (bottom - top) / systems_per_page
    y0 = top + (system - 1) * height
    return round(y0, 4), round(min(bottom, y0 + height * 1.15), 4)
