from app.ingest.chunker import MAX_CHARS, chunk_page
from app.ingest.extractor import ExtractedPage, Section


def make_page(sections):
    return ExtractedPage(id="pkg", url="https://example.com/pkg", page_type="treatment package",
                         title="Alternative Adrenal Cancer Treatment Package", sections=sections)


def test_small_sections_are_packed_together():
    sections = [Section(f"FAQs > Question {i}", "A short answer. " * 5) for i in range(6)]
    chunks = chunk_page(make_page(sections))
    assert len(chunks) < len(sections)
    assert "### FAQs > Question 0" in chunks[0].text and "### FAQs > Question 1" in chunks[0].text


def test_long_sections_are_split_on_line_boundaries():
    lines = [f"Row {i} | $1,{i:03d} USD" for i in range(200)]
    chunks = chunk_page(make_page([Section("Price table", "\n".join(lines))]))
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHARS
        body = chunk.text.split("\n", 1)[1]  # drop the "### heading" line
        assert all(line in lines for line in body.splitlines())


def test_chunk_ids_and_search_text_identify_the_page():
    cost_table = "Out-Patient | $18,995\n" + "Included item line\n" * 45  # large enough to stand alone
    chunks = chunk_page(make_page([Section("Cost", cost_table), Section("Itinerary", "Week 1 ...")]))
    assert [c.id for c in chunks] == ["pkg#1", "pkg#2"]
    assert chunks[0].search_text.startswith("Alternative Adrenal Cancer Treatment Package\nCost")
