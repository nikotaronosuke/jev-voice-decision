from __future__ import annotations

import json
import threading
import time

import httpx2

from app.config import PROJECT_ROOT, Settings
from app.jev.client import JevClient
from app.main import Api
from app.pipeline import Pipeline
from app.rapid import FIXTURE_200, RapidRunner, load_rapid_comments
from tests.fakes import DUMMY_KEY, answer_body


class ConcurrentFake:
    """Fake TypeSafe endpoint that tracks how many requests are in flight at once."""

    def __init__(self, delay_s: float = 0.02, status_for: dict[str, int] | None = None):
        self.delay_s = delay_s
        self.status_for = status_for or {}
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0
        self.utterances: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        utterance = json.loads(request.content)["state"]["utterance"]
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.utterances.append(utterance)
        time.sleep(self.delay_s)
        with self.lock:
            self.in_flight -= 1
        status = self.status_for.get(utterance, 200)
        if status != 200:
            return httpx2.Response(status, text="nope", headers={"x-typesafe-request-id": "req_fake"})
        return httpx2.Response(200, json=answer_body(), headers={"x-typesafe-request-id": "req_fake"})

    def pipeline(self, max_retries: int = 0) -> Pipeline:
        settings = Settings(max_auto_retries=max_retries)
        return Pipeline(JevClient(settings, api_key=DUMMY_KEY, transport=httpx2.MockTransport(self.handler)), settings)


def drain(runner: RapidRunner, timeout: float = 30.0) -> list[dict]:
    items = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        poll = runner.poll()
        items.extend(poll["results"])
        if poll["finished"] and not poll["results"]:
            break
        time.sleep(0.01)
    return items


def test_fixture_200_is_unique_and_fictional_sized():
    comments = load_rapid_comments(FIXTURE_200)
    assert len(comments) == 200 and len(set(comments)) == 200


def test_all_200_processed_once_within_the_concurrency_bound():
    fake = ConcurrentFake(delay_s=0.01)
    runner = RapidRunner(fake.pipeline(), concurrency=12)
    runner.start()
    items = drain(runner)
    assert runner.wait(5)
    assert len(items) == 200 and len({i["index"] for i in items}) == 200
    assert sorted(fake.utterances) == sorted(runner.comments)  # each sent exactly once, no duplicates
    assert fake.peak <= 12 and runner.peak_in_flight <= 12
    assert all(i["result"]["ok"] for i in items) and runner.errors == 0


def test_concurrency_setting_is_respected_when_small():
    fake = ConcurrentFake(delay_s=0.02)
    runner = RapidRunner(fake.pipeline(), comments=[f"文 {i}" for i in range(30)], concurrency=3)
    runner.start()
    items = drain(runner)
    assert len(items) == 30 and fake.peak <= 3 and runner.peak_in_flight <= 3


def test_stop_halts_new_submissions_but_lets_in_flight_requests_finish():
    fake = ConcurrentFake(delay_s=0.05)
    runner = RapidRunner(fake.pipeline(), concurrency=4)
    runner.start()
    time.sleep(0.08)
    runner.stop()
    assert runner.wait(5)
    items = drain(runner)
    assert 0 < len(items) < 200
    assert len(items) == runner.completed == len(fake.utterances)  # nothing submitted after stop, nothing lost
    assert runner.in_flight == 0 and runner.stopped and runner.finished


def test_rate_limit_lowers_concurrency_and_pauses_new_submissions():
    comments = [f"文 {i}" for i in range(40)]
    fake = ConcurrentFake(delay_s=0.01, status_for={"文 5": 429})
    runner = RapidRunner(fake.pipeline(max_retries=0), comments=comments, concurrency=8, pause_s=0.3)
    runner.start()
    started = time.monotonic()
    items = drain(runner)
    assert runner.wait(5)
    assert len(items) == 40 and runner.rate_limited == 1 and runner.errors == 1
    assert runner.limit == 4  # halved once, never raised again
    failed = [i for i in items if not i["result"]["ok"]]
    assert len(failed) == 1 and failed[0]["result"]["error_code"] == "rate_limit"
    assert time.monotonic() - started >= 0.3  # the pause really held new submissions back
    assert len(fake.utterances) == 40  # no extra retries beyond the SDK policy (0 here)


def test_one_failure_does_not_stop_the_run():
    fake = ConcurrentFake(delay_s=0.005, status_for={"文 7": 500})
    runner = RapidRunner(fake.pipeline(max_retries=0), comments=[f"文 {i}" for i in range(20)], concurrency=5)
    runner.start()
    items = drain(runner)
    assert len(items) == 20 and runner.errors == 1
    assert sum(not i["result"]["ok"] for i in items) == 1


def test_results_are_not_written_to_disk_or_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = ConcurrentFake(delay_s=0.001)
    pipeline = fake.pipeline()
    runner = RapidRunner(pipeline, comments=[f"文 {i}" for i in range(15)], concurrency=4)
    runner.start()
    drain(runner)
    assert list(tmp_path.iterdir()) == []
    assert pipeline.history() == []
    assert not (PROJECT_ROOT / "logs").exists()


def test_page_api_starts_polls_and_stops():
    fake = ConcurrentFake(delay_s=0.005)
    api = Api(fake.pipeline(), Settings())
    assert api.rapid_poll()["finished"] is True
    assert api.rapid_start() == {"ok": True, "total": 200}
    api.rapid_stop()
    assert api._rapid.wait(5)
    poll = api.rapid_poll()
    assert poll["finished"] and poll["stopped"] and poll["completed"] <= 200
