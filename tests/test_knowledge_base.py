import numpy as np

from app.retrieval.knowledge_base import KnowledgeBase, save_index, tokenize
from tests.conftest import fake_embed, make_chunk, make_kb

CHUNKS = [
    make_chunk("package-anal", "Included in the program: weekly lab work, meals.",
               title="Alternative Anal Cancer Treatment Package"),
    make_chunk("package-adrenal", "Included in the program: weekly lab work, meals.",
               title="Alternative Adrenal Cancer Treatment Package"),
    make_chunk("price-comparison", "Fizikon Medical Center, Konya, Turkey | $110 | Ozone Therapy",
               title="Alternative Medicine Cost Abroad"),
]


def test_keyword_signal_separates_near_identical_pages():
    hits = make_kb(CHUNKS).search("What is included in the adrenal cancer package?", top_k=2)
    assert hits[0].chunk.page_id == "package-adrenal"


def test_one_page_cannot_take_every_slot():
    chunks = [make_chunk("package-anal", f"Anal cancer program detail {i}", n=i) for i in range(1, 6)]
    chunks.append(make_chunk("clinic-profile", "Risks and medical considerations"))
    hits = make_kb(chunks).search("anal cancer program risks", top_k=3, max_per_page=2)
    assert [h.chunk.page_id for h in hits].count("package-anal") == 2
    assert any(h.chunk.page_id == "clinic-profile" for h in hits)


def test_relevance_gate_returns_nothing_for_unrelated_queries():
    assert make_kb(CHUNKS).search("weather forecast", min_similarity=0.5) == []


def test_tokenize_joins_thousands_and_drops_stopwords():
    assert tokenize("What is the price of $18,995?") == ["price", "18995"]


def test_tokenize_matches_word_forms():
    assert tokenize("located includes") == tokenize("location included")
    assert tokenize("anal adrenal") == ["anal", "adrenal"]


def test_index_round_trip(tmp_path):
    vectors = np.stack([fake_embed(c.search_text) for c in CHUNKS])
    save_index(tmp_path, CHUNKS, vectors, {"embedding_model": "fake"})
    kb = KnowledgeBase.load(tmp_path, fake_embed)
    assert [c.id for c in kb.chunks] == [c.id for c in CHUNKS]
    assert kb.embedding_model == "fake" and kb.built_at
