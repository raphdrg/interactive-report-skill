#!/usr/bin/env python3
"""Probe every rollout video and cut a poster frame for it.

Usage:
    python3 prepare_media.py <run_dir> [--poster-at 0.45] [--max-video-mb 14]

Needs ffmpeg + ffprobe on PATH. Reads <run_dir>/videos/**/*.mp4 and writes:
    <run_dir>/interactive/posters/<same path>.jpg   480px-wide poster per video
    <run_dir>/interactive/media.json               duration, size, resolution, poster per video

Videos are published as-is. A video over --max-video-mb (the Artifact limit
for one binary file is 15 MB) is re-encoded into
<run_dir>/interactive/video_small/<same path> and media.json points at that copy.
"""
import argparse
import json
import subprocess
from pathlib import Path


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,codec_name:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    num, den = st.get("r_frame_rate", "0/1").split("/")
    return {"width": st["width"], "height": st["height"], "codec": st.get("codec_name"),
            "fps": round(float(num) / float(den or 1), 2),
            "duration_s": round(float(j["format"]["duration"]), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--poster-at", type=float, default=0.45, help="fraction of the clip to grab the poster from")
    ap.add_argument("--max-video-mb", type=float, default=14.0)
    a = ap.parse_args()

    run = Path(a.run_dir).resolve()
    out = run / "interactive"
    media = {}
    vids = sorted((run / "videos").rglob("*.mp4"))
    for v in vids:
        rel = v.relative_to(run).as_posix()
        info = probe(v)
        info["bytes"] = v.stat().st_size
        poster_rel = f"interactive/posters/{rel[len('videos/'):-4]}.jpg"
        poster = run / poster_rel
        poster.parent.mkdir(parents=True, exist_ok=True)
        t = max(0.0, info["duration_s"] * a.poster_at)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(v), "-frames:v", "1",
                        "-vf", "scale=480:-2", "-q:v", "5", str(poster)], check=True)
        info["poster"] = poster_rel
        info["src"] = rel
        if info["bytes"] > a.max_video_mb * 1024 * 1024 or info["codec"] != "h264":
            small_rel = f"interactive/video_small/{rel[len('videos/'):]}"
            small = run / small_rel
            small.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(v), "-c:v", "libx264", "-crf", "28",
                            "-preset", "medium", "-vf", "scale='min(1280,iw)':-2", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", "-an", str(small)], check=True)
            info["src"] = small_rel
            info["bytes"] = small.stat().st_size
        media[rel] = info
    (out / "media.json").write_text(json.dumps(media, indent=1))
    total = sum(m["bytes"] for m in media.values())
    print(f"wrote {out / 'media.json'}: {len(media)} videos, {total / 1e6:.1f} MB to publish, posters in {out / 'posters'}")


if __name__ == "__main__":
    main()
