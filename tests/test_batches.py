import json

import httpx
import pytest

from addisai import AddisAI, AddisAIError, to_batch_jsonl
from addisai.resources import files as files_module

BATCH_ID = "batch_0123456789abcdef0123456789abcdef"
FILE_ID = "file_0123456789abcdef0123456789abcdef"


def client_with(handler, max_retries=0):
    calls = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls) - 1)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return AddisAI(api_key="sk_test_123", http_client=http, max_retries=max_retries), calls


def batch(**overrides):
    body = {
        "id": BATCH_ID,
        "object": "batch",
        "endpoint": "/v1/voice/generations",
        "input_file_id": FILE_ID,
        "status": "validating",
        "output_file_id": None,
        "error_file_id": None,
        "request_counts": {"total": 2, "pending": 2},
        "metadata": {"project": "ch3"},
    }
    body.update(overrides)
    return body


def test_create_sends_body_and_generated_idempotency_key():
    client, calls = client_with(lambda r, i: httpx.Response(201, json=batch()))
    result = client.batches.create(input_file_id=FILE_ID, metadata={"project": "ch3"})

    request = calls[0]
    assert str(request.url) == "https://api.addisassistant.com/api/v1/batches"
    assert json.loads(request.content) == {
        "input_file_id": FILE_ID,
        "endpoint": "/v1/voice/generations",
        "completion_window": "24h",
        "metadata": {"project": "ch3"},
    }
    assert len(request.headers["idempotency-key"]) == 26
    assert request.headers["x-api-key"] == "sk_test_123"
    assert result["id"] == BATCH_ID


def test_create_reuses_idempotency_key_on_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    client, calls = client_with(
        lambda r, i: httpx.Response(503, headers={"retry-after": "0"}) if i == 0 else httpx.Response(201, json=batch()),
        max_retries=1,
    )
    client.batches.create(input_file_id=FILE_ID)
    assert len(calls) == 2
    assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]


def test_explicit_idempotency_key_is_kept():
    client, calls = client_with(lambda r, i: httpx.Response(201, json=batch()))
    client.batches.create(input_file_id=FILE_ID, request_options={"idempotency_key": "mine-1"})
    assert calls[0].headers["idempotency-key"] == "mine-1"


def test_create_from_requests_uploads_jsonl_then_creates():
    def handler(request, index):
        if request.url.path == "/api/v1/files":
            return httpx.Response(201, json={"id": FILE_ID, "status": "ready"})
        return httpx.Response(201, json=batch())

    client, calls = client_with(handler)
    client.batches.create_from_requests(
        [
            {"custom_id": "a", "text": "ሰላም", "voice_id": "selam-warm", "language": "am"},
            {"custom_id": "b", "text": "Akkam", "voice_id": "ayana", "language": "om",
             "output_format": "wav_44100", "voice_settings": {"speed": 60}},
        ],
        metadata={"project": "ch3"},
    )

    upload = calls[0]
    assert upload.headers["content-type"].startswith("multipart/form-data")
    content = upload.content.decode("utf-8")
    assert 'name="purpose"' in content and "batch_input" in content
    assert 'filename="batch.jsonl"' in content
    assert '{"custom_id": "a", "body": {"text": "ሰላም", "voice_id": "selam-warm", "language": "am", "output_format": "mp3_44100"}}' in content
    assert json.loads(calls[1].content)["input_file_id"] == FILE_ID


def test_to_batch_jsonl_rejects_duplicates_and_empty():
    with pytest.raises(AddisAIError):
        to_batch_jsonl([
            {"custom_id": "a", "text": "x", "voice_id": "v", "language": "am"},
            {"custom_id": "a", "text": "y", "voice_id": "v", "language": "am"},
        ])
    with pytest.raises(AddisAIError):
        to_batch_jsonl([])


def test_list_walks_pages_with_last_id():
    second = "batch_ffffffffffffffffffffffffffffffff"

    def handler(request, index):
        if index == 0:
            return httpx.Response(200, json={"data": [batch()], "has_more": True, "last_id": BATCH_ID})
        return httpx.Response(200, json={"data": [batch(id=second)], "has_more": False, "last_id": second})

    client, calls = client_with(handler)
    page = client.batches.list(limit=1)
    assert [b["id"] for b in page.data] == [BATCH_ID]
    assert [b["id"] for b in page] == [BATCH_ID, second]
    assert calls[1].url.params["after"] == BATCH_ID


def test_requests_pages_by_line():
    def handler(request, index):
        if index == 0:
            return httpx.Response(200, json={"data": [{"custom_id": "a", "line": 7, "status": "failed"}], "has_more": True})
        return httpx.Response(200, json={"data": [], "has_more": False})

    client, calls = client_with(handler)
    rows = list(client.batches.requests(BATCH_ID, status="failed"))
    assert rows[0]["line"] == 7
    assert calls[1].url.params["after"] == "7"
    assert calls[1].url.params["status"] == "failed"


def test_results_read_signed_files_without_the_api_key():
    output = '{"custom_id":"a","line":1,"status":"succeeded","response":{"audio_file_id":"file_x"}}\n'
    errors = '{"custom_id":"b","line":2,"status":"failed","error":{"code":"voice_not_found","message":"m"}}\n'

    def handler(request, index):
        path = request.url.path
        if path == f"/api/v1/batches/{BATCH_ID}":
            return httpx.Response(200, json=batch(status="completed", output_file_id="file_out", error_file_id="file_err"))
        if path == "/api/v1/files/file_out/content":
            return httpx.Response(302, headers={"location": "https://storage.test/out?sig=1"})
        if path == "/api/v1/files/file_err/content":
            return httpx.Response(302, headers={"location": "https://storage.test/err?sig=1"})
        return httpx.Response(200, text=output if path == "/out" else errors)

    client, calls = client_with(handler)
    results = list(client.batches.results(BATCH_ID))
    assert [r["custom_id"] for r in results] == ["a", "b"]
    assert results[1]["error"]["code"] == "voice_not_found"

    storage = [c for c in calls if c.url.host == "storage.test"]
    assert len(storage) == 2
    assert all("x-api-key" not in c.headers and "authorization" not in c.headers for c in storage)


def test_wait_for_polls_until_final():
    statuses = iter(["queued", "in_progress", "completed"])
    client, calls = client_with(lambda r, i: httpx.Response(200, json=batch(status=next(statuses))))
    slept = []
    result = client.batches.wait_for(BATCH_ID, poll_interval=1, _sleep=slept.append)
    assert result["status"] == "completed"
    assert slept == [5.0, 5.0]  # interval floor is 5 s


def test_cancel():
    client, calls = client_with(lambda r, i: httpx.Response(200, json=batch(status="cancelling")))
    assert client.batches.cancel(BATCH_ID)["status"] == "cancelling"
    assert calls[0].method == "POST"
    assert calls[0].url.path == f"/api/v1/batches/{BATCH_ID}/cancel"


def test_large_upload_uses_signed_put(monkeypatch):
    monkeypatch.setattr(files_module, "DIRECT_UPLOAD_MAX_BYTES", 10)

    def handler(request, index):
        if request.url.path == "/api/v1/files":
            return httpx.Response(201, json={
                "id": FILE_ID, "status": "pending",
                "upload": {"method": "PUT", "url": "https://storage.test/put?sig=1",
                           "headers": {"content-type": "application/jsonl"}, "expires_at": "x"},
            })
        if request.url.host == "storage.test":
            return httpx.Response(200)
        return httpx.Response(200, json={"id": FILE_ID, "status": "ready"})

    client, calls = client_with(handler)
    result = client.files.upload(b"x" * 64, filename="big.jsonl")
    assert json.loads(calls[0].content) == {
        "purpose": "batch_input", "filename": "big.jsonl", "bytes": 64, "content_type": "application/jsonl",
    }
    assert calls[1].method == "PUT" and "x-api-key" not in calls[1].headers
    assert calls[2].url.path == f"/api/v1/files/{FILE_ID}/complete"
    assert result["status"] == "ready"


def test_upload_from_path(tmp_path):
    path = tmp_path / "chapters.jsonl"
    path.write_bytes(b'{"custom_id":"a","body":{}}\n')
    client, calls = client_with(lambda r, i: httpx.Response(201, json={"id": FILE_ID, "status": "ready"}))
    client.files.upload(path)
    assert 'filename="chapters.jsonl"' in calls[0].content.decode()


def test_oversized_upload_is_refused_locally(monkeypatch):
    monkeypatch.setattr(files_module, "SIGNED_UPLOAD_MAX_BYTES", 4)
    client, calls = client_with(lambda r, i: httpx.Response(200, json={}))
    with pytest.raises(AddisAIError):
        client.files.upload(b"12345")
    assert calls == []


def test_content_url_returns_signed_link():
    client, _ = client_with(lambda r, i: httpx.Response(302, headers={"location": "https://storage.test/a.mp3"}))
    assert client.files.content_url("file_a") == "https://storage.test/a.mp3"


TI_VOICES = ["ti-berhane", "ti-senait", "ti-haben", "ti-rahel", "ti-filimon", "ti-danait", "ti-yonas"]


def test_tigrinya_batch_lines_carry_ti_and_each_native_voice():
    from addisai.resources.batches import to_batch_jsonl

    content = to_batch_jsonl(
        {"custom_id": f"ti-{i}", "text": "ሎሚ ጽቡቕ መዓልቲ እዩ።", "voice_id": v, "language": "ti"}
        for i, v in enumerate(TI_VOICES)
    )
    lines = [json.loads(line) for line in content.strip().split("\n")]
    assert [(l["body"]["language"], l["body"]["voice_id"]) for l in lines] == [("ti", v) for v in TI_VOICES]
    assert lines[0]["body"]["text"] == "ሎሚ ጽቡቕ መዓልቲ እዩ።"


@pytest.mark.parametrize("language", ["sid", "wal", "ha", "sw", "en", "fr", "", "unknown", None])
def test_batch_rejects_other_languages_before_any_request(language):
    from addisai import AddisAIError

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    client = AddisAI(api_key="sk_test_123", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AddisAIError, match=r"ti \(Tigrinya\)"):
        client.batches.create_from_requests([{"custom_id": "a", "text": "x", "voice_id": "v", "language": language}])
    assert calls == []
