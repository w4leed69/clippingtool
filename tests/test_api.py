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


@pytest.mark.parametrize("mode,aspect,size", [("blur", "9:16", (1080, 1920)), ("split", "9:16", (1080, 1920)),
                                              ("center", "1:1", (1080, 1080)), ("none", "9:16", (640, 360))])
def test_studio_reframe_modes(client, source_video, mode, aspect, size):
    r = client.post("/api/jobs/studio", json={"upload_id": source_video.name, "clip": False, "start": 2, "end": 8,
                                              "reframe": mode, "aspect": aspect, "captions": False,
                                              "enhance": False})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["id"])
    assert job["status"] == "done", job["error"]
    info = video_info(job["outputs"][0]["url"])
    assert (info["width"], info["height"]) == size
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


def test_studio_all_features(client, source_video, monkeypatch):
    import math
    from app import config
    from app.ai import reframe
    import subprocess
    monkeypatch.setattr(transcribe, "transcribe", _fake_transcribe)
    monkeypatch.setattr(reframe.FaceDetector, "detect", lambda self, f: [reframe.Face(0.7, 0.4, 0.2)])
    broll_clip = config.BROLL_DIR / "secret-vault.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=orange:s=360x640:r=30",
                    "-t", "4", "-pix_fmt", "yuv420p", str(broll_clip)], check=True)
    r = client.post("/api/jobs/studio", json={
        "upload_id": source_video.name, "clip": True, "clip_count": 2, "clip_min": 8, "clip_max": 14,
        "reframe": "ai", "captions": True, "broll": True, "enhance": True,
        "voiceover": True, "vo_mode": "duck", "vo_voice": "silent",
        "vo_script": "Watch this closely because the secret is coming up right now."})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["id"], timeout=400)
    assert job["status"] == "done", job["error"]
    assert 1 <= len(job["outputs"]) <= 2
    for o in job["outputs"]:
        assert o["picker"] == "heuristic"
        assert {"AI reframe", "Audio enhance", "AI voice-over", "AI captions"} <= set(o["features"])
        assert o["srt"] and client.get(o["srt"]).status_code == 200
        info = video_info(o["url"])
        assert (info["width"], info["height"]) == (1080, 1920)
        assert 7 < info["duration"] <= 14.6
    broll_clip.unlink()


def test_studio_voiceover_needs_script_without_ai(client, source_video):
    job = wait_job(client, client.post("/api/jobs/studio", json={
        "upload_id": source_video.name, "clip": False, "end": 4, "captions": False, "reframe": "blur",
        "voiceover": True}).json()["id"])
    assert job["status"] == "error" and "script" in job["error"]


def test_validation_errors(client):
    assert client.post("/api/jobs/studio", json={"url": "x", "clip_min": 60, "clip_max": 30}).status_code == 422
    assert client.post("/api/jobs/studio", json={"reframe": "blur"}).status_code == 422
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
