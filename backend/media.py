"""Streaming media inspection and decoder-PTS frame iteration."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import av


class MediaError(ValueError):
    """Raised when an input cannot satisfy the Phase 01 media contract."""


@dataclass
class TimestampAudit:
    frame_count: int = 0
    missing_pts_count: int = 0
    non_monotonic_count: int = 0
    delta_samples: set[float] = field(default_factory=set)
    _previous_pts_s: float | None = None

    def observe(self, pts_s: float | None) -> None:
        self.frame_count += 1
        if pts_s is None:
            self.missing_pts_count += 1
            return
        if self._previous_pts_s is not None:
            delta = pts_s - self._previous_pts_s
            if delta <= 0:
                self.non_monotonic_count += 1
            else:
                self.delta_samples.add(round(delta, 9))
        self._previous_pts_s = pts_s

    @property
    def variable_frame_rate(self) -> bool:
        return len(self.delta_samples) > 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "decoded_frame_count": self.frame_count,
            "missing_pts_count": self.missing_pts_count,
            "non_monotonic_pts_count": self.non_monotonic_count,
            "timestamp_quality": "continuous"
            if self.missing_pts_count == 0 and self.non_monotonic_count == 0
            else "discontinuous",
            "variable_frame_rate": self.variable_frame_rate,
        }


@dataclass(frozen=True)
class VideoMetadata:
    width: int | None
    height: int | None
    fps_nominal: float | None
    duration_s: float | None
    frame_count: int | None


@dataclass(frozen=True)
class FramePreview:
    """One decoded frame retained for deterministic UI preview only."""

    frame_number: int
    pts_s: float
    width: int
    height: int
    frame: av.VideoFrame


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _video_stream(container: av.container.InputContainer) -> av.video.stream.VideoStream:
    streams = list(container.streams.video)
    if not streams:
        raise MediaError("The input contains no video stream")
    return streams[0]


def inspect_video(path: Path) -> VideoMetadata:
    """Read stream metadata without materialising source frames in memory."""
    if not path.is_file():
        raise MediaError(f"Video file does not exist: {path}")
    try:
        with av.open(str(path)) as container:
            stream = _video_stream(container)
            fps = float(stream.average_rate) if stream.average_rate else None
            duration_s = float(stream.duration * stream.time_base) if stream.duration is not None else None
            if duration_s is None and container.duration is not None:
                duration_s = float(container.duration / av.time_base)
            return VideoMetadata(
                width=stream.codec_context.width or None,
                height=stream.codec_context.height or None,
                fps_nominal=fps,
                duration_s=duration_s,
                frame_count=stream.frames or None,
            )
    except av.FFmpegError as error:
        raise MediaError(f"Unable to inspect video {path}: {error}") from error


def iter_frames_with_pts(path: Path) -> Iterator[tuple[int, float, TimestampAudit]]:
    """Yield decoded frame indexes and decoder PTS seconds sequentially."""
    audit = TimestampAudit()
    try:
        with av.open(str(path)) as container:
            stream = _video_stream(container)
            for frame_number, frame in enumerate(container.decode(stream)):
                time_base = frame.time_base or stream.time_base
                pts_s = float(frame.pts * time_base) if frame.pts is not None and time_base is not None else None
                audit.observe(pts_s)
                if pts_s is None:
                    raise MediaError(f"Frame {frame_number} has no decoder presentation timestamp")
                yield frame_number, pts_s, audit
    except av.FFmpegError as error:
        raise MediaError(f"Unable to decode video {path}: {error}") from error


def preview_frame(path: Path, frame_number: int) -> FramePreview:
    """Decode up to one requested source frame without materialising the video."""
    if frame_number < 0:
        raise MediaError("Preview frame number must be non-negative")
    try:
        with av.open(str(path)) as container:
            stream = _video_stream(container)
            for current_frame_number, frame in enumerate(container.decode(stream)):
                if current_frame_number != frame_number:
                    continue
                time_base = frame.time_base or stream.time_base
                if frame.pts is None or time_base is None:
                    raise MediaError(f"Frame {frame_number} has no decoder presentation timestamp")
                return FramePreview(
                    frame_number=frame_number,
                    pts_s=float(frame.pts * time_base),
                    width=frame.width,
                    height=frame.height,
                    frame=frame,
                )
    except av.FFmpegError as error:
        raise MediaError(f"Unable to decode video {path}: {error}") from error
    raise MediaError(f"Preview frame {frame_number} does not exist")


def iter_decoded_images(path: Path) -> Iterator[tuple[int, float, np.ndarray]]:
    """Sequentially decode RGB images for a downstream phase without retaining prior frames."""
    try:
        with av.open(str(path)) as container:
            stream = _video_stream(container)
            for frame_number, frame in enumerate(container.decode(stream)):
                time_base = frame.time_base or stream.time_base
                if frame.pts is None or time_base is None:
                    raise MediaError(f"Frame {frame_number} has no decoder presentation timestamp")
                yield frame_number, float(frame.pts * time_base), frame.to_ndarray(format="rgb24")
    except av.FFmpegError as error:
        raise MediaError(f"Unable to decode video {path}: {error}") from error
