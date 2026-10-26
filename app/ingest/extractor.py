"""Turn a raw PlacidWay HTML page into clean text sections.

Strategy: keep only the page's own content areas (title/price header, main column,
"about" box), drop site chrome and widgets, render tables as pipe-separated rows,
then split the text into sections at each heading.
"""

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from app.config import Source

# Areas of the page template that hold the page's own content, in reading order.
CONTENT_SELECTORS = ["div.pack-title-price-header", "main.article-dt-desc", "div.pack-about-aside"]

DROP_TAGS = [
    "script", "style", "noscript", "svg", "template", "iframe", "form", "button",
    "input", "select", "textarea", "nav", "footer", "img", "picture", "video",
]

DROP_SELECTORS = [
    "[class*=popup]", "[id*=popup]", "[class*=modal]",
    "[class*=related-]", "[class*=splide]",
    "[class*=pw-footer]", ".pw-stats-section", ".pw-accreditations",
    "#cta-form", "[class*=cta-form]", "[class*=breadcrumb]",
    ".social-btn", ".social-count", ".ctm-view-count", ".reviews-main-block",
]

# On the clinic videos page the "related videos" grid is the page's own content.
VIDEO_GRID_SELECTOR = ".center-videos-page .related-videos-sec"

# About-box rows that only repeat content found elsewhere (the full video list).
DROP_ABOUT_ROWS = ("medical center videos",)

# Unrendered server-side template tags that leak into some pages, e.g. "=$priceRange?>".
TEMPLATE_ARTIFACT = re.compile(r"<?\??=?\s*\$[A-Za-z_]\w*\s*\??>")

HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "aside", "header", "ul", "ol", "li",
    "dl", "dt", "dd", "blockquote", "figure", "figcaption", "tr", "br", "hr",
}
HEADING_MARK = "\u0000H"  # internal marker placed in front of heading lines


@dataclass
class Section:
    heading: str  # heading path, e.g. "FAQs > 3. How do I decide ...?"
    text: str


@dataclass
class ExtractedPage:
    id: str
    url: str
    page_type: str
    title: str
    sections: list[Section]

    @property
    def content_hash(self) -> str:
        body = self.title + "".join(s.heading + s.text for s in self.sections)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def to_markdown(self) -> str:
        parts = [f"# {self.title}", f"Source: {self.url}", ""]
        for section in self.sections:
            parts += [f"## {section.heading}", section.text, ""]
        return "\n".join(parts)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["content_hash"] = self.content_hash
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractedPage":
        return cls(
            id=data["id"],
            url=data["url"],
            page_type=data["page_type"],
            title=data["title"],
            sections=[Section(**s) for s in data["sections"]],
        )


def extract_page(html: str, source: Source) -> ExtractedPage:
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.h1.get_text(" ")) if soup.h1 else _clean(soup.title.get_text())

    roots = _content_roots(soup)
    for root in roots:
        _render_video_grid(root)
        _strip_boilerplate(root)
        _mark_structure(root)
    text = "\n".join(root.get_text() for root in roots)

    return ExtractedPage(
        id=source.id,
        url=source.url,
        page_type=source.page_type,
        title=title,
        sections=_split_sections(text, title),
    )


def _content_roots(soup: BeautifulSoup) -> list[Tag]:
    """Content areas in document order, skipping any nested inside another."""
    found = [el for selector in CONTENT_SELECTORS for el in soup.select(selector)]
    roots = [el for el in found if not any(p in found for p in el.parents)]
    if not roots:
        return [soup.body or soup]
    order = {id(el): i for i, el in enumerate(soup.find_all(True))}
    return sorted(roots, key=lambda el: order[id(el)])


def _render_video_grid(root: Tag) -> None:
    """Replace the videos page's card grid with one line per video."""
    for grid in root.select(VIDEO_GRID_SELECTOR):
        lines = []
        for card in grid.select(".related-videos-card"):
            title, category, place = (
                _clean(el.get_text(" ")) if el else ""
                for el in (card.select_one(".title"), card.select_one(".provider-name"),
                           card.select_one(".exp-loc"))
            )
            details = ", ".join(part for part in (category, place) if part)
            lines.append(f"- {title} ({details})" if details else f"- {title}")
        grid.replace_with(NavigableString(f"\n{HEADING_MARK}2 Videos\n" + "\n".join(lines) + "\n"))


def _strip_boilerplate(root: Tag) -> None:
    for tag in root.find_all(DROP_TAGS):
        tag.decompose()
    for selector in DROP_SELECTORS:
        for tag in root.select(selector):
            tag.decompose()
    for row in root.select(".pack-about-items li"):
        if row.get_text(" ", strip=True).lower().startswith(DROP_ABOUT_ROWS):
            row.decompose()
    # "Related experiences:" style link lists name unrelated treatments (e.g. dental
    # implants); drop the heading and everything after it up to the next heading.
    for heading in root.find_all(list(HEADING_TAGS)):
        if heading.get_text(strip=True).lower().startswith("related"):
            for sibling in heading.find_next_siblings():
                if sibling.name in HEADING_TAGS:
                    break
                sibling.decompose()
            heading.decompose()


def _table_to_text(table: Tag) -> str:
    """Render a table as pipe-separated rows, without empty columns or unnamed rows."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
        is_data_row = tr.find("td") is not None
        if not any(cells) or (is_data_row and not cells[0]):
            continue  # a price with no item name next to it would be misleading
        rows.append(cells)

    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in rows[1:])] if len(rows) > 1 else range(width)
    return "\n".join(" | ".join(r[i] for i in keep) for r in rows)


def _mark_structure(root: Tag) -> None:
    """Rewrite the tree so that get_text() keeps headings, list items, rows and blocks apart."""
    for table in reversed(root.find_all("table")):  # innermost tables first
        table.replace_with(NavigableString("\n" + _table_to_text(table) + "\n"))

    for tag in root.find_all(list(HEADING_TAGS)):
        level = HEADING_TAGS[tag.name]
        heading = _clean(tag.get_text(" "))
        tag.replace_with(NavigableString(f"\n{HEADING_MARK}{level} {heading}\n" if heading else "\n"))

    # Simple list items (e.g. "Location: <address>" rows) become one line each.
    for li in reversed(root.find_all("li")):
        if not li.find(list(BLOCK_TAGS - {"br"})):
            li.replace_with(NavigableString(f"\n- {_clean(li.get_text(' '))}\n"))

    for tag in root.find_all(BLOCK_TAGS):
        if tag.name == "li":
            tag.insert(0, NavigableString("\n- "))
        tag.insert_after(NavigableString("\n"))


def _split_sections(text: str, title: str) -> list[Section]:
    sections: list[Section] = []
    path: dict[int, str] = {}  # heading level -> heading text
    lines: list[str] = []
    seen: set[str] = set()

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            heading = " > ".join(path[k] for k in sorted(path)) or title
            sections.append(Section(heading=heading, text=body))
        lines.clear()

    for raw in text.splitlines():
        if raw.startswith(HEADING_MARK):
            flush()
            level, heading = int(raw[len(HEADING_MARK)]), raw[len(HEADING_MARK) + 2:]
            path = {k: v for k, v in path.items() if k < level}
            if level > 1:  # the page title (h1) is stored separately
                path[level] = heading
            continue

        line = _clean(raw)
        if not re.search(r"\w", line):  # empty, or punctuation left over from removed links
            continue
        # Templates often repeat the same sentence (desktop + mobile copies); keep the first.
        if len(line) > 30:
            if line in seen:
                continue
            seen.add(line)
        lines.append(line)
    flush()
    return sections


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # also turns non-breaking spaces into spaces
    text = TEMPLATE_ARTIFACT.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
