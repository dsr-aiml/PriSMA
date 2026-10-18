"""Offline regressions for conversational depth, topic changes and intact answers."""
import json

import pytest
from pydantic import ValidationError
from test_baseline import register
from test_saved_sources import imported

from app import jobs
from app import model_gateway as gateway
from app.answer_support import format_statements, response_preferences
from app.intelligence import AnchoredAnswer
from app.research_context import conversation_query, format_request


@pytest.mark.parametrize("question,target,maximum", [
    ("Explain this in 100 words", 100, 100),
    ("Give 100 words about the API", 100, 100),
    ("Explain this in at most 100 words", 100, 100),
    ("Explain the architecture", 180, 400),
    ("Explain the architecture in detail", 350, 600),
    ("Explain it briefly", 80, 400),
    ("Answer in 10 words", 10, 10),
])
def test_length_target_is_distinct_from_a_ceiling(question, target, maximum):
    value = response_preferences(question)
    assert value["target_words"] == target
    assert value["maximum_words"] == maximum
    if "at most" in question:
        assert value["length_policy"] == "A ceiling only"


def test_format_changes_resolve_the_topic_and_new_subjects_keep_their_own():
    history = [{"question": "Explain the editor."}, {"question": "Make it shorter."}]
    for question in ("give it in 100 words pointers", "elaborate", "more details please"):
        assert format_request(question)
        assert conversation_query(question, history) == "Explain the editor."
    for question in ("Explain Google in 100 words", "Explain pricing", "Summarize subscriptions in 100 words"):
        assert not format_request(question)
        assert conversation_query(question, history) == question
    assert "Previous topic: Explain the editor." in conversation_query("Why does it do that?", history)


def test_long_direct_answer_is_not_silently_replaced_by_a_later_paragraph():
    text = "This specification documents " + "project " * 105 + "operations."
    result = format_statements([{"text": text, "citations": ["source"]}, {"text": "A later observation.", "citations": ["later"]}], "Explain in 100 words")
    assert result[0]["text"] == text
    assert result[0]["citations"] == ["source"]
    assert len(result) == 1


def test_sentence_bounding_and_bullets_preserve_supported_content():
    text = "The specification declares projects. " + "Additional project descriptions " * 40 + "follow."
    result = format_statements([{"text": text, "citations": ["source"]}], "Give in 20 words pointers")
    assert result == [{"text": "• The specification declares projects.", "citations": ["source"]}]


def test_detailed_response_contract_accepts_longer_connected_explanations():
    paragraphs = [{"text": "The specification describes project operations and their public contract. " * 10, "evidence": ["u1"]} for _ in range(8)]
    assert len(paragraphs[0]["text"]) > 700
    assert len(AnchoredAnswer(insufficient_evidence=False, statements=paragraphs).statements) == 8
    with pytest.raises(ValidationError):
        AnchoredAnswer(insufficient_evidence=False, statements=paragraphs + paragraphs)


def test_requested_length_survives_the_chat_worker_with_one_model_call(context, monkeypatch, hosted_query):
    client, _, _ = context
    register(client)
    text = (
        "The public specification describes a projects API with a project listing operation. "
        "Its declared contract gives reviewers a concrete starting point for understanding the client interface. "
        "The project schema contains an identifier represented as a string. "
        "These declarations describe the interface that the supplied document promises, including the route and the shape of its resource. "
        "They do not establish measured production traffic or expose implementation details inside a private service. "
        "A useful next review would compare client references with the declared operation and inspect any additional supplied authentication documentation before drawing conclusions about protected access or deployment behavior."
    )
    identifier = imported(client, [{"title": "API guide", "origin": "local:guide.md", "format": "markdown", "category": "documentation", "content": "# Projects API\n\n" + text}])
    jobs.process(identifier)
    before = client.get(f"/investigations/{identifier}").json()
    queued, calls = [], []
    monkeypatch.setattr(jobs, "enqueue_question", queued.append)
    def reply(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        calls.append(packet)
        assert packet["response_preferences"]["target_words"] == 100
        assert schema["properties"]["statements"]["maxItems"] == 10
        assert packet["assessment"]["scope"].startswith("Saved source assessment")
        units = [key for key, value in packet["passages"].items() if value in text][:4]
        assert units
        return {"insufficient_evidence": False, "statements": [{"text": text, "evidence": units}]}, {}
    monkeypatch.setattr(gateway, "generate", reply)
    question = client.post(f"/investigations/{identifier}/questions", json={"question": "Explain this API in 100 words"})
    assert question.status_code == 202
    jobs.process_question(queued[0])
    value = client.get(f"/investigations/{identifier}/questions").json()[0]
    assert value["status"] == "completed"
    answer = value["answer"]
    assert len(calls) == 1
    assert not answer["rejected_statements"]
    assert 85 <= answer["response_length"]["words"] <= 100
    assert answer["response_length"]["requested_words"] == 100
    assert len(answer["statements"][0]["text"]) > 700
    assert client.get(f"/investigations/{identifier}").json()["report"] == before["report"]
    sources = {s["id"]: s["content"] for s in before["evidence"]}
    for statement in answer["statements"]:
        for citation in statement["citations"]:
            assert sources[citation["evidence_id"]][citation["start"]:citation["end"]] == citation["quote"]
