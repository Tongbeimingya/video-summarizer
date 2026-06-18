import os
import re
import glob
import base64
import subprocess
import tempfile

from openai import OpenAI


def _get_ffmpeg_bin():
    import shutil
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def _get_duration(file_path):
    ffmpeg = _get_ffmpeg_bin()
    if not ffmpeg:
        return None
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe").replace("ffmpeg-win", "ffprobe-win")
    if not os.path.exists(ffprobe):
        ffprobe = ffmpeg
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return None


class VisionProcessor:
    """Extract keyframes and recognize visual content using DeepSeek-VL2."""

    def __init__(self, api_key, base_url, model, interval=10, scene_threshold=0.3):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.interval = interval
        self.scene_threshold = scene_threshold
        self._ffmpeg = _get_ffmpeg_bin()

    def process_video(self, video_path):
        if not self._ffmpeg:
            raise RuntimeError("ffmpeg not found, vision mode requires ffmpeg")

        duration = _get_duration(video_path)
        if not duration or duration < 1:
            raise RuntimeError("Cannot determine video duration")

        print(f"  [Vision] Extracting keyframes (interval={self.interval}s)...")
        frames = self._extract_keyframes(video_path, duration)
        if not frames:
            print("  [Vision] No keyframes extracted")
            return []

        print(f"  [Vision] Extracted {len(frames)} keyframes, recognizing content...")
        results = []
        for i, (ts, path) in enumerate(frames):
            print(f"  [Vision] Analyzing frame {i+1}/{len(frames)} [{int(ts)//60:02d}:{int(ts)%60:02d}]")
            desc = self._recognize_frame(path, ts)
            if desc:
                results.append({"timestamp": ts, "description": desc})

        self._cleanup_frames(frames)
        return results

    def _extract_keyframes(self, video_path, duration):
        with tempfile.TemporaryDirectory(prefix="vs_vision_") as tmpdir:
            fixed_frames = self._extract_fixed_interval(video_path, tmpdir, duration)
            scene_frames = self._extract_scene_changes(video_path, tmpdir, duration)

            all_frames = fixed_frames + scene_frames
            all_frames.sort(key=lambda x: x[0])

            deduped = self._deduplicate_frames(all_frames)
            return deduped

    def _extract_fixed_interval(self, video_path, tmpdir, duration):
        frames = []
        ts = 0
        while ts < duration:
            out_path = os.path.join(tmpdir, f"fixed_{int(ts):05d}.jpg")
            cmd = [
                self._ffmpeg, "-y", "-ss", str(ts), "-i", video_path,
                "-vframes", "1", "-q:v", "3", out_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=15)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                    frames.append((ts, out_path))
            except Exception:
                pass
            ts += self.interval
        return frames

    def _extract_scene_changes(self, video_path, tmpdir, duration):
        frames = []
        out_pattern = os.path.join(tmpdir, "scene_%05d.jpg")
        cmd = [
            self._ffmpeg, "-y", "-i", video_path,
            "-vf", f"select='gt(scene,{self.scene_threshold})',setpts=N/FRAME_RATE/TB",
            "-vsync", "vfr", "-frame_pts", "1",
            "-q:v", "3", out_pattern,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except Exception:
            pass

        for f in sorted(glob.glob(os.path.join(tmpdir, "scene_*.jpg"))):
            fname = os.path.basename(f)
            match = re.search(r"scene_(\d+)\.jpg", fname)
            if match:
                frame_pts = int(match.group(1))
                ts = frame_pts / 24.0
                if ts < duration:
                    frames.append((ts, f))
        return frames

    def _deduplicate_frames(self, frames, min_gap=8):
        if not frames:
            return []
        deduped = [frames[0]]
        for ts, path in frames[1:]:
            if ts - deduped[-1][0] >= min_gap:
                deduped.append((ts, path))
        return deduped

    def _recognize_frame(self, image_path, timestamp):
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a video frame analysis assistant. "
                            "Describe the key visual content in this frame concisely in Chinese. "
                            "Focus on: text/titles on screen, charts/diagrams, "
                            "code/terminal output, UI elements, key visual information. "
                            "Output 1-2 sentences. If nothing notable, output '无显著视觉内容'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": f"请描述这个视频帧（时间戳 {int(timestamp)//60:02d}:{int(timestamp)%60:02d}）的核心视觉内容。",
                            },
                        ],
                    },
                ],
                max_tokens=200,
                temperature=0.2,
            )
            content = response.choices[0].message.content.strip()
            if "无显著视觉内容" in content:
                return None
            return content
        except Exception as e:
            print(f"  [Vision] Recognition failed: {e}")
            return None

    def _cleanup_frames(self, frames):
        for _, path in frames:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass
