from app.chat import messages
from app.chat.schemas import GroundedAnswer, QueryAnalysis
from app.chat.service import ChatService
from app.storage import Storage
from tests.conftest import FakeKB, FakeLLM, make_chunk

CHUNK = make_chunk("price-list", "Out-Patient Program | 3 Weeks | $18,995", title="ITC Price List")


def analysis(intent="question", language="en", disclaimer=False, question="How much is it?"):
    return QueryAnalysis(intent=intent, standalone_question=question, language=language,
                         needs_medical_disclaimer=disclaimer)


def answer(text, answerable=True, cited=("price-list#1",)):
    return GroundedAnswer(answerable=answerable, answer=text, cited_chunk_ids=list(cited))


def make_service(llm, tmp_path, chunks=(CHUNK,)):
    kb = FakeKB(list(chunks))
    return ChatService(llm, kb, Storage(tmp_path / "test.db")), kb


def test_grounded_answer_is_returned_with_its_source(tmp_path):
    service, _ = make_service(FakeLLM(analysis(), answer("It starts at $18,995 USD.")), tmp_path)
    reply = service.reply("How much is it?", [])
    assert reply.answer == "It starts at $18,995 USD."
    assert [s.url for s in reply.sources] == [CHUNK.url]
    assert reply.answerable and not reply.show_quote_cta


def test_booking_gets_fixed_reply_without_retrieval(tmp_path):
    service, kb = make_service(FakeLLM(analysis(intent="booking")), tmp_path)
    reply = service.reply("Book me for tomorrow", [])
    assert reply.answer == messages.BOOKING
    assert reply.show_quote_cta
    assert kb.queries == []


def test_medical_advice_gets_fixed_reply(tmp_path):
    service, _ = make_service(FakeLLM(analysis(intent="medical_advice")), tmp_path)
    reply = service.reply("Is this safe for my diabetes?", [])
    assert reply.answer == messages.MEDICAL_ADVICE and reply.show_quote_cta


def test_invented_price_becomes_i_dont_know_and_is_logged(tmp_path):
    service, _ = make_service(FakeLLM(analysis(), answer("It costs $9,999.")), tmp_path)
    reply = service.reply("How much is it?", [])
    assert reply.answer == messages.NOT_FOUND and not reply.answerable
    logged = service.storage.list_unanswered()
    assert logged[0]["question"] == "How much is it?" and "guardrail" in logged[0]["reason"]


def test_no_relevant_content_means_i_dont_know(tmp_path):
    service, _ = make_service(FakeLLM(analysis()), tmp_path, chunks=())
    reply = service.reply("Dental implants in Mexico?", [])
    assert reply.answer == messages.NOT_FOUND and reply.show_quote_cta


def test_unanswerable_answers_are_logged_as_content_gaps(tmp_path):
    llm = FakeLLM(analysis(), answer("The pages don't list a recovery time.", answerable=False, cited=()))
    service, _ = make_service(llm, tmp_path)
    reply = service.reply("Recovery time?", [])
    assert reply.show_quote_cta
    assert service.storage.list_unanswered()[0]["reason"] == "not covered by the pages"


def test_disclaimer_is_shown_once(tmp_path):
    llm = FakeLLM(analysis(disclaimer=True), answer("It starts at $18,995."),
                  analysis(disclaimer=True), answer("It starts at $18,995."))
    service, _ = make_service(llm, tmp_path)
    assert service.reply("Risks?", [], disclaimer_shown=False).disclaimer == messages.DISCLAIMER
    assert service.reply("Risks?", [], disclaimer_shown=True).disclaimer is None


def test_llm_outage_returns_friendly_message(tmp_path, llm_error):
    service, _ = make_service(FakeLLM(llm_error), tmp_path)
    reply = service.reply("Hello?", [])
    assert reply.answer == messages.UNAVAILABLE and reply.intent == "error"


def test_fixed_replies_are_translated_once_per_language(tmp_path):
    llm = FakeLLM(analysis(intent="out_of_scope", language="es"),
                  analysis(intent="out_of_scope", language="es"))
    service, _ = make_service(llm, tmp_path)
    first = service.reply("¿Qué tiempo hace en Cancún?", [])
    second = service.reply("¿Y mañana?", [])
    assert first.answer == second.answer == f"[translated] {messages.OUT_OF_SCOPE}"
    assert llm.translations == 1
