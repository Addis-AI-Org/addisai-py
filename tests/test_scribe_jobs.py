import json
import time
from pathlib import Path

import httpx
import pytest

import addisai.resources.scribe as scribe_module
from addisai import AddisAI, AddisAIError, APIConnectionError, InsufficientCreditsError, ScribeJobs

RESULT = {"text": "ሰላም ወዳጆቻችን", "request_id": "job1", "seconds": 9015.3, "compute_ms": 61234, "backend": "turbo", "chunk": "1120ms", "mode": "job", "model": "addis-scribe-streaming", "chunks": 6,
          "words": [{"text": "ሰላም", "start": 0.7, "end": 1.1, "speaker": 1}], "segments": [{"text": "ሰላም ወዳጆቻችን", "start": 0.3, "end": 4.2, "speaker": 1}], "speakers": 3,
          "usage": {"record_id": "ledger", "characters": 74210, "price_per_1000_characters": 3.5, "credits_used": 259.735, "credits_remaining": 1240.27, "currency": "ETB", "settled": True}}
QUEUED = {"request_id": "job1", "status": "queued", "audio_seconds": None, "poll_url": "/api/v1/scribe/requests/job1", "job_url": "/api/v1/scribe/jobs/job1"}
PROGRESS = {"request_id": "job1", "status": "processing", "audio_seconds": 9015.3, "processed_seconds": 3000.0, "chunks": {"total": 6, "done": 2}, "poll_url": "/api/v1/scribe/requests/job1", "job_url": "/api/v1/scribe/jobs/job1"}
FILE = b"0123456789"   # ten bytes; with MAX_UPLOAD_BYTES=8 and part_bytes=4 it is three parts: 0123, 4567, 89

def client(handler):
    return AddisAI(api_key="test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps

def test_one_request_upload_polls_with_progress_and_retry_after(monkeypatch):
    sleeps = no_sleep(monkeypatch)
    calls, progress = [], []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path == "/api/v1/scribe/jobs"
            assert dict(request.url.params) == {"request_id": "job1", "backend": "turbo", "chunk": "1120ms", "timestamps": "word", "speakers": "true"}
            assert request.headers["x-api-key"] == "test-secret"
            assert request.headers["content-type"].startswith("multipart/form-data;")
            assert b'name="audio"' in request.content and b"audio-bytes" in request.content
            return httpx.Response(202, json={"data": QUEUED}, headers={"Location": QUEUED["poll_url"], "Retry-After": "5"})
        assert request.url.path == "/api/v1/scribe/requests/job1"
        if len(calls) == 2:
            return httpx.Response(202, json={"data": {**PROGRESS, "status": "queued", "audio_seconds": None}}, headers={"Retry-After": "10"})
        if len(calls) == 3:
            return httpx.Response(202, json={"data": PROGRESS}, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"data": RESULT})
    result = client(handler).scribe.transcribe_long(audio=b"audio-bytes", request_id="job1", speakers=True, on_progress=progress.append)
    assert result["text"] == RESULT["text"] and result["chunks"] == 6 and result["speakers"] == 3
    assert result["usage"]["settled"] is True
    assert [p["status"] for p in progress] == ["queued", "processing"]
    assert progress[1]["processed_seconds"] == 3000.0 and progress[1]["chunks"] == {"total": 6, "done": 2}
    assert sleeps == [10.0, 3.0]
    assert calls == [("POST", "/api/v1/scribe/jobs")] + [("GET", "/api/v1/scribe/requests/job1")] * 3

def test_upload_sends_timestamps_always_and_speakers_only_when_true():
    seen = []
    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(202, json={"data": QUEUED})
    jobs = client(handler).scribe.jobs
    assert isinstance(jobs, ScribeJobs)
    assert jobs.upload(audio=b"audio", request_id="job1")["status"] == "queued"
    jobs.upload(audio=("meeting.mp3", b"audio", "audio/mpeg"), request_id="job1", timestamps="none")
    assert seen == [{"request_id": "job1", "backend": "turbo", "chunk": "1120ms", "timestamps": "word"},
                    {"request_id": "job1", "backend": "turbo", "chunk": "1120ms", "timestamps": "none"}]

def parts_handler(received, calls, sleeps_poll=False):
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/v1/scribe/jobs":
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == {"request_id": "job1", "bytes": 10, "backend": "turbo", "chunk": "1120ms", "timestamps": "word", "speakers": True}
            return httpx.Response(201 if not received else 200, json={"data": {"request_id": "job1", "status": "uploading", "part_bytes": 4, "parts": 3, "received": list(received), "expires_at": 1792000000, "job_url": "/api/v1/scribe/jobs/job1"}})
        if request.method == "PUT":
            index = int(request.url.path.rsplit("/", 1)[1])
            assert request.url.path == f"/api/v1/scribe/jobs/job1/parts/{index}"
            assert request.headers["content-type"] == "application/octet-stream"
            assert request.content == FILE[index * 4:(index + 1) * 4]
            received.add(index)
            return httpx.Response(200, json={"data": {"index": index, "received": sorted(received)}})
        if request.method == "POST" and request.url.path == "/api/v1/scribe/jobs/job1/complete":
            assert received == {0, 1, 2}
            return httpx.Response(202, json={"data": QUEUED}, headers={"Retry-After": "5"})
        assert (request.method, request.url.path) == ("GET", "/api/v1/scribe/requests/job1")
        return httpx.Response(200, json={"data": RESULT})
    return handler

@pytest.mark.parametrize("kind", ["str", "pathlike", "file", "tuple"])
def test_large_file_is_declared_sent_in_parts_completed_and_waited(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    no_sleep(monkeypatch)
    path = tmp_path / "meeting.wav"
    path.write_bytes(FILE)
    calls, received = [], set()
    addis = client(parts_handler(received, calls))
    if kind == "str":
        result = addis.scribe.transcribe_long(audio=str(path), request_id="job1", speakers=True)
    elif kind == "pathlike":
        result = addis.scribe.transcribe_long(audio=Path(path), request_id="job1", speakers=True)
    elif kind == "file":
        with open(path, "rb") as audio:
            result = addis.scribe.transcribe_long(audio=audio, request_id="job1", speakers=True)
            assert not audio.closed
    else:
        with open(path, "rb") as audio:
            result = addis.scribe.transcribe_long(audio=("meeting.wav", audio, "audio/wav"), request_id="job1", speakers=True)
    assert result["text"] == RESULT["text"]
    assert calls == [("POST", "/api/v1/scribe/jobs"), ("PUT", "/api/v1/scribe/jobs/job1/parts/0"), ("PUT", "/api/v1/scribe/jobs/job1/parts/1"),
                     ("PUT", "/api/v1/scribe/jobs/job1/parts/2"), ("POST", "/api/v1/scribe/jobs/job1/complete"), ("GET", "/api/v1/scribe/requests/job1")]

def test_parts_resume_from_received(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    no_sleep(monkeypatch)
    calls, received = [], {0, 2}
    result = client(parts_handler(received, calls)).scribe.transcribe_long(audio=FILE, request_id="job1", speakers=True)
    assert result["usage"]["settled"] is True
    assert [c for c in calls if c[0] == "PUT"] == [("PUT", "/api/v1/scribe/jobs/job1/parts/1")]

def test_part_is_sent_again_after_a_connection_error(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    sleeps = no_sleep(monkeypatch)
    calls, received, dropped = [], set(), []
    inner = parts_handler(received, calls)
    def handler(request):
        if request.method == "PUT" and request.url.path.endswith("/1") and not dropped:
            dropped.append(True)
            raise httpx.ConnectError("reset")
        return inner(request)
    client(handler).scribe.transcribe_long(audio=FILE, request_id="job1", speakers=True)
    assert [c for c in calls if c[0] == "PUT"] == [("PUT", f"/api/v1/scribe/jobs/job1/parts/{i}") for i in (0, 1, 2)]
    assert sleeps[0] == 0.5

def test_part_connection_errors_give_up_after_the_retries(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    no_sleep(monkeypatch)
    puts = []
    def handler(request):
        if request.method == "PUT":
            puts.append(request.url.path)
            raise httpx.ConnectError("reset")
        return httpx.Response(201, json={"data": {"request_id": "job1", "status": "uploading", "part_bytes": 4, "parts": 3, "received": []}})
    with pytest.raises(APIConnectionError):
        client(handler).scribe.transcribe_long(audio=FILE, request_id="job1")
    assert puts == ["/api/v1/scribe/jobs/job1/parts/0"] * (scribe_module.PART_RETRIES + 1)

def test_local_validation_happens_before_any_request():
    calls = []
    addis = client(lambda request: calls.append(request) or httpx.Response(500))
    with pytest.raises(AddisAIError, match="request_id"):
        addis.scribe.transcribe_long(audio=b"audio", request_id="bad id!")
    with pytest.raises(AddisAIError, match="turbo"):
        addis.scribe.transcribe_long(audio=b"audio", backend="standard", speakers=True)
    with pytest.raises(AddisAIError, match="turbo"):
        addis.scribe.jobs.upload(audio=b"audio", backend="standard", speakers=True)
    with pytest.raises(AddisAIError, match="turbo"):
        addis.scribe.jobs.create(request_id="job1", bytes=10, backend="standard", speakers=True)
    with pytest.raises(AddisAIError, match='"none" or "word"'):
        addis.scribe.jobs.upload(audio=b"audio", timestamps="sentence")
    with pytest.raises(AddisAIError, match="jobs.create"):
        addis.scribe.jobs.upload(audio=b"\0" * (95 * 1024**2 + 1), request_id="job1")
    with pytest.raises(AddisAIError, match="positive integer"):
        addis.scribe.jobs.create(request_id="job1", bytes=0)
    with pytest.raises(AddisAIError, match="index"):
        addis.scribe.jobs.put_part("job1", -1, b"data")
    with pytest.raises(AddisAIError, match="non-empty"):
        addis.scribe.jobs.put_part("job1", 0, b"")
    with pytest.raises(AddisAIError, match="request_id"):
        addis.scribe.jobs.status("bad id!")
    with pytest.raises(AddisAIError, match="empty"):
        addis.scribe.transcribe_long(audio=b"")
    assert calls == []

def test_paid_job_steps_are_not_retried():
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": {"code": "BILLING_PENDING", "message": "recover"}})
    jobs = client(handler).scribe.jobs
    options = {"max_retries": 3}
    with pytest.raises(AddisAIError, match="recover"):
        jobs.upload(audio=b"audio", request_id="job1", request_options=options)
    with pytest.raises(AddisAIError, match="recover"):
        jobs.create(request_id="job1", bytes=10, request_options=options)
    with pytest.raises(AddisAIError, match="recover"):
        jobs.put_part("job1", 0, b"data", request_options=options)
    with pytest.raises(AddisAIError, match="recover"):
        jobs.complete("job1", request_options=options)
    assert calls == ["POST", "POST", "PUT", "POST"]

def test_status_returns_the_job_view():
    view = {"request_id": "job1", "status": "processing", "part_bytes": 4194304, "parts": 1, "received": [0], "audio_seconds": 9015.3, "processed_seconds": 1500.0, "chunks": {"total": 6, "done": 1}, "poll_url": "/api/v1/scribe/requests/job1"}
    def handler(request):
        assert (request.method, request.url.path) == ("GET", "/api/v1/scribe/jobs/job1")
        return httpx.Response(200, json={"data": view})
    assert client(handler).scribe.jobs.status("job1") == view

def test_failed_job_surfaces_its_own_error_on_poll(monkeypatch):
    no_sleep(monkeypatch)
    def handler(request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": QUEUED})
        return httpx.Response(402, json={"error": {"code": "INSUFFICIENT_CREDITS", "message": "Add credit."}})
    with pytest.raises(InsufficientCreditsError) as exc:
        client(handler).scribe.transcribe_long(audio=b"audio", request_id="job1")
    assert exc.value.status == 402 and exc.value.code == "INSUFFICIENT_CREDITS"

def test_unsettled_result_is_rejected(monkeypatch):
    no_sleep(monkeypatch)
    handler = lambda request: httpx.Response(200, json={"data": {**RESULT, "usage": {**RESULT["usage"], "settled": False}}})
    with pytest.raises(AddisAIError, match="settled"):
        client(handler).scribe.jobs.wait("job1")

def test_wait_gives_up_after_its_timeout(monkeypatch):
    no_sleep(monkeypatch)
    progress = []
    handler = lambda request: httpx.Response(202, json={"data": PROGRESS})
    with pytest.raises(AddisAIError, match="recover"):
        client(handler).scribe.jobs.wait("job1", on_progress=progress.append, timeout=0)
    assert progress == [PROGRESS]

CANCELLED = {"request_id": "job1", "status": "cancelled", "was": "uploading", "request_id_reusable": True}

def test_cancel_sends_delete_and_returns_the_answer():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/gone"):
            return httpx.Response(409, json={"error": {"code": "JOB_FINISHED", "message": "Finished."}, "status": 409})
        return httpx.Response(200, json={"data": CANCELLED})
    addis = client(handler)
    assert addis.scribe.jobs.cancel("job1") == CANCELLED
    with pytest.raises(Exception) as finished:
        addis.scribe.jobs.cancel("gone")
    assert getattr(finished.value, "code", None) == "JOB_FINISHED"
    with pytest.raises(AddisAIError, match="request_id"):
        addis.scribe.jobs.cancel("bad/id")
    assert calls == [("DELETE", "/api/v1/scribe/jobs/job1"), ("DELETE", "/api/v1/scribe/jobs/gone")]

def test_an_interrupted_upload_cancels_its_own_job_and_reraises(monkeypatch):
    monkeypatch.setattr(scribe_module, "MAX_UPLOAD_BYTES", 8)
    no_sleep(monkeypatch)
    calls, received = [], set()
    upload = parts_handler(received, calls)
    def handler(request):
        if request.method == "PUT" and request.url.path.endswith("/1"):
            calls.append((request.method, request.url.path)); raise KeyboardInterrupt   # Ctrl-C mid-part
        if request.method == "DELETE":
            calls.append((request.method, request.url.path)); return httpx.Response(200, json={"data": CANCELLED})
        return upload(request)
    with pytest.raises(KeyboardInterrupt):
        client(handler).scribe.transcribe_long(audio=FILE, request_id="job1", speakers=True)
    assert calls == [("POST", "/api/v1/scribe/jobs"), ("PUT", "/api/v1/scribe/jobs/job1/parts/0"), ("PUT", "/api/v1/scribe/jobs/job1/parts/1"),
                     ("DELETE", "/api/v1/scribe/jobs/job1")]

def test_an_interrupted_one_request_upload_cancels_and_a_failed_cancel_keeps_the_interrupt():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            raise KeyboardInterrupt
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "Job not found."}, "status": 404})
    with pytest.raises(KeyboardInterrupt):
        client(handler).scribe.transcribe_long(audio=b"audio-bytes", request_id="job1")
    assert calls == [("POST", "/api/v1/scribe/jobs"), ("DELETE", "/api/v1/scribe/jobs/job1")]

def test_other_upload_errors_and_an_interrupt_while_waiting_leave_the_job(monkeypatch):
    no_sleep(monkeypatch)
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(202, json={"data": QUEUED})
        raise KeyboardInterrupt   # while polling: the job is queued and runs on
    with pytest.raises(KeyboardInterrupt):
        client(handler).scribe.transcribe_long(audio=b"audio-bytes", request_id="job1")
    def busy(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(429, json={"error": {"code": "BUSY", "message": "Busy."}, "status": 429})
    with pytest.raises(Exception):
        client(busy).scribe.transcribe_long(audio=b"audio-bytes", request_id="job1", request_options={"max_retries": 0})
    assert not [c for c in calls if c[0] == "DELETE"]
