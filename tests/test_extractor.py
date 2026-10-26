import re

from app.config import Source
from app.ingest.extractor import extract_page

SOURCE = Source(id="test-package", page_type="treatment package", url="https://example.com/p")

HTML = """<html><head><title>Ignored title</title></head><body>
<div class="pack-title-price-header">
  <h1>Test Cancer Treatment Package in Tijuana</h1>
  <div class="pack-price-block">
    <h2 style="display:none">Package Price</h2>
    <div class="reviews-main-block"><h2>Medical Center Reviews</h2>6 Reviews</div>
    <div class="price-social-block-ctm">
      <button class="social-btn">Share</button>
      <div class="actual-price"><span>$18,995</span> <span>Price starting from</span></div>
    </div>
  </div>
</div>
<main class="article-dt-desc">
  <section id="about">
    <h2>Cost of Treatment</h2>
    <table>
      <tr><th>Program</th><th>Price</th><th>Actions</th></tr>
      <tr><td>Out-Patient Program</td><td>$18,995</td><td><button>Chat</button></td></tr>
      <tr><td></td><td>$1</td><td></td></tr>
    </table>
    <p>Prices range between =$priceRange?> in Tijuana.</p>
    <h3>Related Experiences:</h3>
    <a class="custom_link" href="/x">All on 6 Dental Implants in Tijuana</a>
    <h2>FAQs</h2>
    <h3>1. Is English spoken?</h3>
    <p>Yes,&nbsp;all staff speak English.</p>
    <ul><li><span>Location:</span> <span>Blvd. Padre Kino 10133</span></li></ul>
  </section>
  <section class="related-centers-sec"><h2>Other clinics</h2><p>Some Other Clinic $500</p></section>
  <div id="book_consultation_popup"><h2>Book now</h2></div>
</main>
<footer>Footer links</footer>
</body></html>"""


def page_text(page):
    return "\n".join(f"{s.heading}\n{s.text}" for s in page.sections)


def test_title_comes_from_h1():
    assert extract_page(HTML, SOURCE).title == "Test Cancer Treatment Package in Tijuana"


def test_price_box_is_kept():
    text = page_text(extract_page(HTML, SOURCE))
    assert "$18,995" in text and "Price starting from" in text


def test_tables_become_rows_without_empty_columns_or_unnamed_rows():
    text = page_text(extract_page(HTML, SOURCE))
    assert "Program | Price" in text
    assert "Out-Patient Program | $18,995" in text
    assert "Actions" not in text
    assert not re.search(r"\$1\b", text)  # the row with a price but no name is dropped


def test_boilerplate_and_unrelated_listings_are_removed():
    text = page_text(extract_page(HTML, SOURCE))
    for unwanted in ("Dental Implants", "Other Clinic", "Book now", "Footer", "Share", "Reviews"):
        assert unwanted not in text


def test_template_artifacts_and_nbsp_are_cleaned():
    text = page_text(extract_page(HTML, SOURCE))
    assert "$priceRange" not in text
    assert "Yes, all staff speak English." in text


def test_sections_keep_their_heading_path():
    page = extract_page(HTML, SOURCE)
    faq = next(s for s in page.sections if "English spoken" in s.heading)
    assert faq.heading == "FAQs > 1. Is English spoken?"
    assert "- Location: Blvd. Padre Kino 10133" in faq.text


def test_content_hash_changes_with_content():
    first = extract_page(HTML, SOURCE)
    second = extract_page(HTML.replace("$18,995", "$19,500"), SOURCE)
    assert first.content_hash != second.content_hash
