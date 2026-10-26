"""Split extracted pages into retrieval chunks.

Chunks follow the page's own sections: a section is never mixed with another page,
small neighbouring sections (FAQ entries, short lists) are packed together, and long
sections are split at line boundaries so table rows and list items stay intact.
"""

from dataclasses import asdict, dataclass

from app.ingest.extractor import ExtractedPage

MAX_CHARS = 1600  # roughly 400 tokens
MIN_CHARS = 700  # keep packing small sections until a chunk reaches this size


@dataclass
class Chunk:
    id: str 
    page_id: str
    url: str
    page_title: str
    page_type: str
    section: str
    text: str

    @property
    def search_text(self) -> str:
        """What gets embedded and keyword-indexed: the text plus where it comes from.

        The page title matters: the three package pages share identical section
        headings and prices, and only the title says which cancer type a chunk is about.
        """
        return f"{self.page_title}\n{self.section}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


def chunk_pages(pages: list[ExtractedPage]) -> list[Chunk]:
    return [chunk for page in pages for chunk in chunk_page(page)]


def chunk_page(page: ExtractedPage) -> list[Chunk]:
    blocks = [
        (section.heading, piece)
        for section in page.sections
        for piece in _split_text(section.text, MAX_CHARS - len(section.heading) - 10)
    ]

    groups: list[list[tuple[str, str]]] = []
    size = 0
    for heading, text in blocks:
        block_size = len(heading) + len(text) + 6
        if groups and size < MIN_CHARS and size + block_size <= MAX_CHARS:
            groups[-1].append((heading, text))
            size += block_size
        else:
            groups.append([(heading, text)])
            size = block_size

    return [
        Chunk(
            id=f"{page.id}#{n}",
            page_id=page.id,
            url=page.url,
            page_title=page.title,
            page_type=page.page_type,
            section=group[0][0],
            text="\n\n".join(f"### {heading}\n{text}" for heading, text in group),
        )
        for n, group in enumerate(groups, start=1)
    ]


def _split_text(text: str, limit: int) -> list[str]:
    """Split text into pieces of at most `limit` characters, preferring line breaks."""
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    current = ""
    for line in _split_long_lines(text.splitlines(), limit):
        if current and len(current) + len(line) + 1 > limit:
            pieces.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


def _split_long_lines(lines: list[str], limit: int) -> list[str]:
    """Break any single line longer than `limit` at sentence boundaries."""
    out: list[str] = []
    for line in lines:
        while len(line) > limit:
            cut = max(line.rfind(". ", 0, limit), line.rfind(", ", 0, limit))
            cut = cut + 1 if cut > 0 else limit
            out.append(line[:cut].strip())
            line = line[cut:].strip()
        if line:
            out.append(line)
    return out
