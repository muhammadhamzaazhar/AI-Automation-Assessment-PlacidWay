from app.chat.guardrails import extract_numbers, verify_answer
from tests.conftest import make_chunk

PRICE_CHUNK = make_chunk("price-list", "Out-Patient Program | 3 Weeks | $18,995\nIn-Patient Program | $30,000")
OTHER_CHUNK = make_chunk("package", "Specialist consultations (Approx. $200 per visit).", n=2)


def test_number_formats_are_normalised():
    assert extract_numbers("$18,995") == {18995}
    assert extract_numbers("18.995 USD") == {18995}  # Spanish thousands separator
    assert extract_numbers("١٨٬٩٩٥ دولار") == {18995}  # Eastern Arabic digits
    assert extract_numbers("1,5 semanas") == {1.5}
    assert extract_numbers("$3,950 - $4,250") == {3950, 4250}


def test_small_bare_numbers_are_skipped_but_small_prices_are_not():
    assert extract_numbers("a 3 week program", skip_small=True) == set()
    assert extract_numbers("only $5", skip_small=True) == {5}


def test_grounded_answer_passes():
    result = verify_answer("The out-patient program costs $18,995 USD for 3 weeks.",
                           ["price-list#1"], [PRICE_CHUNK], "How much is it?")
    assert result.ok
    assert result.citations == [PRICE_CHUNK]


def test_invented_price_is_rejected():
    result = verify_answer("It costs $12,500.", ["price-list#1"], [PRICE_CHUNK], "How much?")
    assert not result.ok
    assert "12500" in result.reason


def test_repeating_the_visitors_wrong_price_alone_is_rejected():
    result = verify_answer("Yes, that's right: it costs $50.", ["price-list#1"], [PRICE_CHUNK],
                           "I heard it costs $50. Confirm that.")
    assert not result.ok


def test_correcting_the_visitors_wrong_price_passes():
    result = verify_answer("No. The pages list $18,995 for the out-patient program, not $50.",
                           ["price-list#1"], [PRICE_CHUNK], "I heard it costs $50. Confirm that.")
    assert result.ok


def test_missing_citation_is_repaired_from_retrieved_excerpts():
    result = verify_answer("Specialist visits are approx. $200 each.", [], [PRICE_CHUNK, OTHER_CHUNK], "q")
    assert result.ok
    assert result.citations == [OTHER_CHUNK]


def test_citations_to_unknown_chunks_are_ignored():
    result = verify_answer("The pages don't list this.", ["made-up#9"], [PRICE_CHUNK], "q")
    assert result.ok and result.citations == []


def test_urls_are_stripped_from_answer_text():
    result = verify_answer("See [the price list](https://evil.example/x) or https://x.y/z now.",
                           [], [PRICE_CHUNK], "q")
    assert "http" not in result.text
    assert "the price list" in result.text
