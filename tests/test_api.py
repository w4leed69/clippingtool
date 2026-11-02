import pytest

from app import transcribe
from app.tts import Word
from tests.conftest import video_info, wait_job


def test_meta_lists_placeholders_and_voices(client):
    meta = client.get("/api/meta").json()
    assert any(b["id"].startswith("placeholder-") for b in meta["backgrounds"])
    assert any(v["id"] == "silent" for v in meta["voices"])
    assert meta["ai_enabled"] is False


def test_story_job_renders_vertical_video(client):
    r = client.post("/api/jobs/story", json={
        "title": "I accidentally adopted a raccoon",
        "body": "It started when I left the garage open. The next morning he was asleep in the dryer. Now he has a name.",
        "voice": "silent", "background": "placeholder-neon-gradient.mp4", "caption_style": "green",
    })
    assert r.status_code == 202
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "done", job["error"]
    info = video_info(job["outputs"][0]["url"])
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["audio"] and info["duration"] > 4
    assert client.get(job["outputs"][0]["thumbnail"]).status_code == 200


def test_story_in_parts(client):
    body = " ".join(f"This is sentence {i} of a long story." for i in range(40))
    job = wait_job(client, client.post("/api/jobs/story", json={
        "title": "Long one", "body": body, "voice": "silent", "part_seconds": 30}).json()["id"])
    assert job["status"] == "done", job["error"]
    assert len(job["outputs"]) >= 2
    assert "(Part 1)" in job["outputs"][0]["title"]


def test_chat_job(client):
    r = client.post("/api/jobs/chat", json={
        "contact_name": "Dad", "hook": "My dad thinks I crashed his car",
        "messages": [{"sender": "me", "text": "so about the car"}, {"sender": "them", "text": "What about it"},
                     {"sender": "me", "text": "it's fine. april fools"}],
        "voice_me": "silent", "voice_them": "silent", "theme": "dark"})
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "done", job["error"]
    info = video_info(job["outputs"][0]["url"])
    assert (info["width"], info["height"]) == (1080, 1920)


@pytest.mark.parametrize("layout", ["blur", "split", "crop"])
def test_edit_layouts(client, source_video, layout):
    r = client.post("/api/jobs/edit", json={"upload_id": source_video.name, "layout": layout,
                                            "captions": False, "start": 2, "end": 8})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "done", job["error"]
    info = video_info(job["outputs"][0]["url"])
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 5.5 < info["duration"] < 6.6


def _fake_transcribe(media, language=None):
    segs, t = [], 0.0
    lines = ["Hello and welcome.", "This is the craziest secret ever!", "Nobody knows why.",
             "Anyway that's the show.", "Thanks for watching!"]
    while t < 38:
        for line in lines:
            words, wt = [], t
            for tok in line.split():
                words.append(Word(tok, wt, wt + 0.35))
                wt += 0.4
            segs.append(transcribe.Segment(t, wt, line, words))
            t = wt + 0.4
    return [s for s in segs if s.end < 39.5]


def test_clip_job_with_captions(client, source_video, monkeypatch):
    monkeypatch.setattr(transcribe, "transcribe", _fake_transcribe)
    r = client.post("/api/jobs/clip", json={"upload_id": source_video.name, "count": 2, "min_seconds": 6,
                                            "max_seconds": 12, "layout": "blur"})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "done", job["error"]
    assert 1 <= len(job["outputs"]) <= 2
    for o in job["outputs"]:
        assert o["picker"] == "heuristic"
        info = video_info(o["url"])
        assert (info["width"], info["height"]) == (1080, 1920)
        assert 5 < info["duration"] <= 12.6


def test_validation_errors(client):
    assert client.post("/api/jobs/clip", json={"url": "x", "min_seconds": 60, "max_seconds": 30}).status_code == 422
    assert client.post("/api/jobs/edit", json={"layout": "blur"}).status_code == 422
    r = client.post("/api/jobs/story", json={"title": "t", "body": "b", "background": "../../etc/passwd"})
    assert r.status_code == 400
    assert client.post("/api/ai/script", json={"kind": "story", "idea": "a cat"}).status_code == 400


def test_upload_rejects_unknown_type(client):
    r = client.post("/api/uploads", files={"file": ("evil.sh", b"echo hi", "text/plain")})
    assert r.status_code == 400


def test_delete_job(client):
    job = wait_job(client, client.post("/api/jobs/story", json={"title": "x", "body": "short one.",
                                                                 "voice": "silent"}).json()["id"])
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
