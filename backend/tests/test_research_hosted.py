import json
from contextlib import nullcontext

import httpx
import pytest
from sqlalchemy import func, select
from test_baseline import register
from test_saved_sources import imported

from app import jobs, model_gateway as gateway
from app.model_profiles import snapshot, using
from app.models import Chunk, Investigation, ModelCache, Question


def test_query_configuration_has_no_calls_or_secrets(context, monkeypatch, hosted_query):
    client, factory, queued = context
    assert client.get("/research/configuration").status_code == 401
    register(client)
    monkeypatch.setattr(gateway, "_request", lambda *a, **k: pytest.fail("Configuration must not call a provider"))
    value = client.get("/research/configuration").json()
    assert value == {"configured": True, "model": "gemini-3.5-flash-lite", "reason": ""}
    assert hosted_query.gemini_api_key not in json.dumps(gateway.provider_catalog())
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 0
        assert db.scalar(select(func.count()).select_from(ModelCache)) == 0
    assert not queued


def test_query_enablement_is_independent_and_key_is_required(context, monkeypatch, hosted_query):
    assert snapshot("gemini", purpose="query")["model"] == "gemini-3.5-flash-lite"
    with pytest.raises(gateway.ModelFailure, match="disabled"):
        snapshot("gemini")
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    queued=[]
    monkeypatch.setattr(jobs, "enqueue_question", queued.append)
    hosted_query.gemini_api_key = ""
    response = client.post(f"/investigations/{identifier}/questions", json={"question":"How does authentication work?"})
    assert response.status_code == 422 and "GEMINI_API_KEY" in response.text
    assert not queued
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 0


def test_hosted_query_uses_grounded_prompt_and_latest_transport(monkeypatch, hosted_query):
    monkeypatch.setattr(gateway, "model_slot", nullcontext)
    requests=[]
    def request(method, url, **kwargs):
        requests.append((method,url,kwargs))
        return {"candidates":[{"finishReason":"STOP","content":{"parts":[{"thought":True,"text":"internal"},{"text":'{"insufficient_evidence":true,"statements":[]}'}]}}],"usageMetadata":{"promptTokenCount":20}}
    monkeypatch.setattr(gateway,"_request",request)
    runtime=snapshot("gemini",purpose="query")
    with using({"model_settings":runtime}):
        assert gateway.model_identity("gemini") == "gemini:gemini-3.5-flash-lite"
        output,usage=gateway.generate("gemini","Question and selected source units",{"type":"object"})
    assert output["insufficient_evidence"] and usage["promptTokenCount"] == 20
    method,url,options=requests[0]
    assert method == "POST" and url.endswith("/gemini-3.5-flash-lite:generateContent")
    assert options["headers"]["x-goog-api-key"] == "test-only-api-key"
    body=options["json"]
    assert body["contents"][0]["role"] == "user"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel":"MINIMAL"}
    assert body["generationConfig"]["responseFormat"]["text"]["mimeType"] == "APPLICATION_JSON"
    assert body["generationConfig"]["responseFormat"]["text"]["schema"] == {"type":"object"}
    assert not {"temperature","topP","topK"} & body["generationConfig"].keys()
    assert "untrusted data" in body["systemInstruction"]["parts"][0]["text"]
    assert "conclusion first" in body["systemInstruction"]["parts"][0]["text"]
    assert len(requests)==1


@pytest.mark.parametrize("reply,code",[
    ({"candidates":[]},"blocked_output"),
    ({"candidates":[{"finishReason":"MAX_TOKENS"}]},"incomplete_output"),
    ({"candidates":[{"finishReason":"SAFETY"}]},"blocked_output"),
    ({"candidates":[{"finishReason":"STOP","content":{"parts":[None]}}]},"invalid_response"),
    ({"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"not json"}]}}]},"invalid_json"),
])
def test_rejected_hosted_answers_do_not_retry(monkeypatch,hosted_query,reply,code):
    calls=[]
    monkeypatch.setattr(gateway,"model_slot",nullcontext)
    monkeypatch.setattr(gateway,"_request",lambda *a,**k:calls.append(a) or reply)
    with using({"model_settings":snapshot("gemini",purpose="query")}):
        with pytest.raises(gateway.ModelFailure) as error:
            gateway.generate("gemini","Bounded question",{})
    assert error.value.code==code and len(calls)==1


@pytest.mark.parametrize("status,code",[(401,"access_denied"),(403,"access_denied"),(404,"model_unavailable"),(429,"capacity_exhausted")])
def test_hosted_service_errors_are_actionable_and_private(monkeypatch,hosted_query,status,code):
    from app import research_budget
    monkeypatch.setattr(research_budget,"admit",lambda *a:0)
    monkeypatch.setattr(gateway.time,"sleep",lambda _:None)
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(status,json={"error":{"message":"private-provider-detail " + hosted_query.gemini_api_key}})
    client=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **options:client(transport=httpx.MockTransport(handler),**options))
    monkeypatch.setattr(gateway,"model_slot",nullcontext)
    with using({"model_settings":snapshot("gemini",purpose="query")}):
        with pytest.raises(gateway.ModelFailure) as error:
            gateway.generate("gemini","Question",{})
    assert error.value.code==code and error.value.http_status==status
    assert "private-provider-detail" not in str(error.value) and hosted_query.gemini_api_key not in str(error.value)
    assert len(requests)==(3 if status==429 else 1)


def test_bad_request_exposes_field_paths_without_echoing_provider_data(monkeypatch,hosted_query):
    client=httpx.Client
    def handler(request):
        return httpx.Response(400,json={"error":{"status":"INVALID_ARGUMENT","message":"private question "+hosted_query.gemini_api_key,"details":[{"fieldViolations":[{"field":"generation_config.response_format.text.mime_type","description":"private source excerpt"},{"field":"bad field with private contents"}]}]}})
    monkeypatch.setattr(httpx,"Client",lambda **options:client(transport=httpx.MockTransport(handler),**options))
    with pytest.raises(gateway.ModelFailure) as error:
        gateway._request("POST","https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent",json={})
    assert error.value.code=="invalid_request"
    assert "generation_config.response_format.text.mime_type" in str(error.value)
    assert not any(secret in str(error.value) for secret in ("private",hosted_query.gemini_api_key))


def test_google_invalid_key_on_http_400_is_identified(monkeypatch):
    client=httpx.Client
    transport=httpx.MockTransport(lambda request:httpx.Response(400,json={"error":{"message":"API key not valid. Please pass a valid API key."}}))
    monkeypatch.setattr(httpx,"Client",lambda **options:client(transport=transport,**options))
    with pytest.raises(gateway.ModelFailure) as error:
        gateway._request("POST","https://generativelanguage.googleapis.com/v1beta/models/example:generateContent",json={})
    assert error.value.code=="api_key_invalid" and "GEMINI_API_KEY" in str(error.value)


def test_custom_query_models_do_not_inherit_a_model_specific_thinking_level(monkeypatch,hosted_query):
    hosted_query.gemini_query_model="gemini-3.1-pro-preview"
    requests=[]
    monkeypatch.setattr(gateway,"model_slot",nullcontext)
    def request(method,url,**options):
        requests.append(options["json"])
        return {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":'{"insufficient_evidence":true,"statements":[]}'}]}}]}
    monkeypatch.setattr(gateway,"_request",request)
    with using({"model_settings":snapshot("gemini",purpose="query")}):
        gateway.generate("gemini","Question",{})
    assert "thinkingConfig" not in requests[0]["generationConfig"] and len(requests)==1


def test_queries_do_not_require_the_assessments_embedding_service(context,monkeypatch,hosted_query):
    client,factory,_=context
    register(client)
    identifier=imported(client)
    jobs.process(identifier)
    with factory() as db:
        inv=db.get(Investigation,identifier)
        inv.processing_options={"provider":"ollama","semantic_retrieval":True,"model_settings":{"model":"qwen3:1.7b","embedding_model":"all-minilm","profile":"light"}}
        inv.report={**inv.report,"run":{**inv.report["run"],"retrieval":"semantic","semantic_index":"complete"}}
        for chunk in db.scalars(select(Chunk).where(Chunk.investigation_id==identifier)):
            chunk.embedding_model="ollama:previous-index";chunk.embedding=[1.0,0.0]
        db.commit()
    before=client.get(f"/investigations/{identifier}").json()
    queued=[]
    monkeypatch.setattr(jobs,"enqueue_question",queued.append)
    monkeypatch.setattr(gateway,"_request",lambda *a,**k:pytest.fail("No Ollama metadata or provider request"))
    monkeypatch.setattr(gateway,"embed",lambda *a:pytest.fail("Research must not require embedding calls"))
    def reply(provider,prompt,schema):
        packet=json.loads(prompt.split("\n",1)[1])
        assert provider=="gemini" and packet["assessment"]["counts"]["api_endpoints"]
        assert len(prompt.encode())<28000+2000
        return {"insufficient_evidence":False,"statements":[{"text":"The API declares a project-list operation.","evidence":[next(iter(packet["passages"]))]}]},{}
    monkeypatch.setattr(gateway,"generate",reply)
    # Even an older client's local-engine fields cannot change the managed path.
    response=client.post(f"/investigations/{identifier}/questions",json={"question":"Which API operations are declared?","provider":"ollama","semantic_retrieval":True})
    assert response.status_code==202
    jobs.process_question(queued[0])
    value=client.get(f"/investigations/{identifier}/questions").json()[0]
    assert value["status"]=="completed" and value["answer"]["retrieval"]=="lexical"
    assert value["answer"]["model"]=="gemini:gemini-3.5-flash-lite"
    assert value["answer"]["statements"][0]["citations"]
    after=client.get(f"/investigations/{identifier}").json()
    assert after["report"]==before["report"] and after["processing_options"]==before["processing_options"]
    source_text={row["id"]:row["content"] for row in after["evidence"]}
    for citation in value["answer"]["statements"][0]["citations"]:
        assert source_text[citation["evidence_id"]][citation["start"]:citation["end"]]==citation["quote"]
