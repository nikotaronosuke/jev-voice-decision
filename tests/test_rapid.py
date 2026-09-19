from __future__ import annotations

import threading

from app.config import PROJECT_ROOT, Settings
from app.jev.client import JevClient
from app.main import Api
from app.pipeline import Pipeline
from app.rapid import RapidDemo, load_rapid_comments
from tests.fakes import DUMMY_KEY, FakeTransport


def make_pipeline(fake: FakeTransport) -> Pipeline:
    settings = Settings()
    return Pipeline(JevClient(settings, api_key=DUMMY_KEY, transport=fake.transport()), settings)


def test_fixture_has_25_fictional_comments():
    comments = load_rapid_comments()
    assert len(comments) == 25 and len(set(comments)) == 25
    assert all(comment.strip() for comment in comments)


def test_steps_run_in_order_one_request_each_and_progress_counts_to_25():
    fake = FakeTransport()
    demo = RapidDemo(make_pipeline(fake))
    seen = []
    while True:
        step = demo.step()
        if "text" in step:
            seen.append((step["index"], step["text"], step["result"]["ok"]))
            assert len(fake.requests) == step["index"]  # exactly one request per step, none ahead of time
        if step["done"]:
            break
    assert [index for index, _, _ in seen] == list(range(1, 26))
    assert [text for _, text, _ in seen] == demo.comments
    assert [r["json"]["state"]["utterance"] for r in fake.requests] == demo.comments
    assert all(ok for _, _, ok in seen)
    assert demo.step()["done"] is True and len(fake.requests) == 25  # finished: no extra request


def test_requests_never_overlap_even_when_called_from_two_threads():
    fake = FakeTransport()
    demo = RapidDemo(make_pipeline(fake), comments=[f"c{i}" for i in range(10)])
    started, busy, overlaps = threading.Lock(), [0], [0]
    original = fake.handler

    def slow_handler(request):
        with started:
            busy[0] += 1
            if busy[0] > 1:
                overlaps[0] += 1
        response = original(request)
        with started:
            busy[0] -= 1
        return response
    fake.handler = slow_handler
    demo.pipeline.jev._client = JevClient(Settings(), api_key=DUMMY_KEY, transport=__import__("httpx2").MockTransport(slow_handler))._client
    threads = [threading.Thread(target=lambda: [demo.step() for _ in range(5)]) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps[0] == 0
    assert [r["json"]["state"]["utterance"] for r in fake.requests] == demo.comments


def test_stop_prevents_further_requests():
    fake = FakeTransport()
    demo = RapidDemo(make_pipeline(fake))
    demo.step(); demo.step(); demo.step()
    demo.stop()
    step = demo.step()
    assert step["done"] is True and step["stopped"] is True and step["index"] == 3
    assert len(fake.requests) == 3
    demo.reset()
    assert demo.step()["index"] == 1 and len(fake.requests) == 4


def test_a_failing_item_is_reported_and_the_run_continues():
    fake = FakeTransport(status=500, text_body="boom")
    demo = RapidDemo(make_pipeline(fake), comments=["a", "b"])
    first = demo.step()
    assert first["result"]["ok"] is False and first["result"]["error_message"].startswith("Jevから判断を取得できませんでした")
    assert first["done"] is False
    second = demo.step()
    assert second["index"] == 2 and second["done"] is True


def test_rapid_runs_do_not_touch_normal_history_or_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = FakeTransport()
    pipeline = make_pipeline(fake)
    pipeline.run_text("通常の入力")
    demo = RapidDemo(pipeline, comments=["x", "y"])
    while not demo.step()["done"]:
        pass
    assert [h["transcript"] for h in pipeline.history()] == ["通常の入力"]
    assert list(tmp_path.iterdir()) == []
    assert not (PROJECT_ROOT / "logs").exists()
