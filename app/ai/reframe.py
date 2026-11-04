"""AI reframe: follow the speaker's face so a horizontal video becomes a well-framed vertical one.

Faces are detected a few times per second with OpenCV, the main subject is tracked with some
"stickiness" (so the camera doesn't jump between people every frame), and a virtual camera follows
it smoothly with a dead-zone, the way a human operator would.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import ffmpeg

DETECT_WIDTH = 480      # frames are downscaled to this width for detection
SAMPLES_PER_SECOND = 5


class ReframeError(RuntimeError):
    pass


@dataclass
class Face:
    cx: float  # center, 0..1 of frame width
    cy: float  # center, 0..1 of frame height
    size: float  # face height, 0..1 of frame height


def _cv2():
    try:
        import cv2
    except ImportError as e:
        raise ReframeError("opencv-python-headless is not installed; run `pip install -r requirements.txt`") from e
    if not hasattr(cv2, "CascadeClassifier"):
        raise ReframeError("This OpenCV version has no face detector; install opencv-python-headless<5")
    return cv2


class FaceDetector:
    def __init__(self):
        cv2 = _cv2()
        base = cv2.data.haarcascades
        self.cv2 = cv2
        self.frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        self.profile = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")

    def detect(self, frame) -> list[Face]:
        cv2 = self.cv2
        h, w = frame.shape[:2]
        scale = DETECT_WIDTH / w
        small = cv2.resize(frame, (DETECT_WIDTH, max(1, int(h * scale))))
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        sh, sw = gray.shape
        min_px = max(18, int(sh * 0.06))
        boxes = list(self.frontal.detectMultiScale(gray, 1.1, 5, minSize=(min_px, min_px)))
        if not boxes:  # try side views, both directions
            boxes = list(self.profile.detectMultiScale(gray, 1.1, 5, minSize=(min_px, min_px)))
            flipped = self.profile.detectMultiScale(cv2.flip(gray, 1), 1.1, 5, minSize=(min_px, min_px))
            boxes += [(sw - x - bw, y, bw, bh) for (x, y, bw, bh) in flipped]
        return [Face((x + bw / 2) / sw, (y + bh / 2) / sh, bh / sh) for (x, y, bw, bh) in boxes]


def choose_subject(faces: list[Face], previous: Face | None) -> Face | None:
    """Largest face wins, but keep following the previous subject unless someone is clearly bigger."""
    if not faces:
        return None
    biggest = max(faces, key=lambda f: f.size)
    if previous is None:
        return biggest
    nearest = min(faces, key=lambda f: abs(f.cx - previous.cx) + abs(f.cy - previous.cy))
    if abs(nearest.cx - previous.cx) < 0.15 and nearest.size >= biggest.size * 0.6:
        return nearest
    return biggest


def track(samples: list[list[Face]], hold: int = 2 * SAMPLES_PER_SECOND) -> list[float | None]:
    """Turn per-sample detections into the subject's horizontal position (None = nobody seen)."""
    out: list[float | None] = []
    prev: Face | None = None
    missing = 0
    for faces in samples:
        subject = choose_subject(faces, prev)
        if subject is None:
            missing += 1
            # briefly hold the last position through missed detections (blinks, head turns)
            out.append(prev.cx if prev is not None and missing <= hold else None)
            if missing > hold:
                prev = None
            continue
        missing = 0
        prev = subject
        out.append(subject.cx)
    return out


def camera_path(positions: list[float | None], frames: int, fps: float, crop_frac: float) -> list[float]:
    """Per-frame crop center (0..1 of source width), smoothed with a dead-zone like a camera operator.

    ``crop_frac`` is the crop width as a fraction of the source width.
    """
    half = crop_frac / 2
    known = [p for p in positions if p is not None]
    if not known:
        return [0.5] * frames
    # fill gaps: before the first sighting use the first position, later hold the last one
    filled, last = [], known[0]
    for p in positions:
        last = p if p is not None else last
        filled.append(last)
    step = fps / SAMPLES_PER_SECOND
    dead = crop_frac * 0.12      # subject can drift this far from center before the camera moves
    max_speed = crop_frac * 1.2 / fps  # at most 1.2 crop-widths per second
    cam = min(max(filled[0], half), 1 - half)
    path = []
    for i in range(frames):
        target = filled[min(int(i / step), len(filled) - 1)]
        offset = target - cam
        if abs(offset) > dead:
            move = (offset - dead if offset > 0 else offset + dead) * 0.12
            cam += max(-max_speed, min(max_speed, move))
        cam = min(max(cam, half), 1 - half)
        path.append(cam)
    return path


def reframe(src: Path, out: Path, out_w: int, out_h: int, progress=None) -> dict:
    """Write a video-only file of ``src`` reframed to out_w x out_h, following the main face.

    ``src`` should be constant frame rate (studio cuts segments at 30 fps). Returns tracking stats.
    """
    cv2 = _cv2()
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ReframeError(f"Could not open {src.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or int(ffmpeg.duration(src) * fps)

    target_aspect = out_w / out_h
    crop_w = min(src_w, int(round(src_h * target_aspect)))
    crop_h = min(src_h, int(round(crop_w / target_aspect)))
    crop_frac = crop_w / src_w

    # pass 1: detect faces a few times per second
    detector = FaceDetector()
    every = max(1, int(round(fps / SAMPLES_PER_SECOND)))
    samples: list[list[Face]] = []
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % every == 0:
            ok, frame = cap.retrieve()
            if ok:
                samples.append(detector.detect(frame))
            if progress and frames:
                progress(0.5 * i / frames)
        i += 1
    frames = i or frames
    positions = track(samples)
    path = camera_path(positions, frames, fps, crop_frac)
    seen = sum(p is not None for p in positions)

    # pass 2: crop every frame along the camera path and pipe to ffmpeg
    cap.release()
    cap = cv2.VideoCapture(str(src))
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{out_w}x{out_h}", "-r", f"{fps:.3f}", "-i", "-", "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    y0 = (src_h - crop_h) // 2
    try:
        for n in range(frames):
            ok, frame = cap.read()
            if not ok:
                break
            x0 = int(round(path[min(n, len(path) - 1)] * src_w - crop_w / 2))
            x0 = max(0, min(src_w - crop_w, x0))
            crop = frame[y0:y0 + crop_h, x0:x0 + crop_w]
            proc.stdin.write(cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_AREA).tobytes())
            if progress and n % 15 == 0:
                progress(0.5 + 0.5 * n / frames)
    except BrokenPipeError:
        pass
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
        err = proc.stderr.read().decode() if proc.stderr else ""
        proc.wait()
    if proc.returncode != 0:
        raise ReframeError(f"Encoding the reframed video failed: {err[-500:]}")
    return {"face_coverage": round(seen / max(len(positions), 1), 2)}
