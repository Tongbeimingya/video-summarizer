import os
import subprocess
import tempfile
import time

from tqdm import tqdm

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".ts", ".m4v"}
SUPPORTED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


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
    """用 ffprobe 获取音视频时长（秒）"""
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


class AudioProcessor:
    """本地音视频处理：音轨提取 + ASR 转写"""

    def __init__(self, whisper_model="small"):
        self.whisper_model = whisper_model
        self._ffmpeg = _get_ffmpeg_bin()
        self._whisper_model_instance = None

    def process_file(self, file_path):
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise RuntimeError(
                f"不支持的文件格式：{ext}\n"
                f"支持的格式：{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        title = os.path.splitext(os.path.basename(file_path))[0]
        duration = _get_duration(file_path)
        duration_str = f" ({duration:.0f}s)" if duration else ""
        print(f"  文件：{os.path.basename(file_path)}{duration_str}")

        # Step 1: 音轨提取/转换
        step1 = "提取音轨" if ext in VIDEO_EXTENSIONS else "转换音频格式"
        print(f"\n  [{step1}]")
        if ext in AUDIO_EXTENSIONS:
            wav_path = self._ensure_wav(file_path)
        else:
            wav_path = self._extract_audio(file_path)

        if not wav_path:
            raise RuntimeError("音轨提取失败，请检查文件是否损坏。")

        wav_size = os.path.getsize(wav_path) / 1024 / 1024
        print(f"  -> 输出：{wav_size:.1f}MB WAV (16kHz mono)")

        # Step 2: ASR 转写
        print(f"\n  [ASR 转写] 模型={self.whisper_model}")
        text = self._transcribe(wav_path, duration)
        if not text.strip():
            raise RuntimeError("转写结果为空，文件可能没有语音内容。")

        return title, text, "asr"

    def _ensure_wav(self, file_path):
        return self._convert_to_mono_16k(file_path)

    def _extract_audio(self, video_path):
        if not self._ffmpeg:
            raise RuntimeError(
                "未找到 ffmpeg，请安装：\n"
                "  Windows: pip install imageio-ffmpeg 或从 https://ffmpeg.org 下载\n"
                "  macOS: brew install ffmpeg\n"
                "  Linux: sudo apt install ffmpeg"
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        cmd = [
            self._ffmpeg, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            wav_path,
        ]

        duration = _get_duration(video_path)
        pbar = tqdm(total=duration or 100, unit="s", desc="  提取音轨", ncols=80)

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            if duration:
                while proc.poll() is None:
                    time.sleep(0.5)
                    current = _get_duration_progress(wav_path)
                    if current is not None:
                        pbar.update(min(current - pbar.n, duration - pbar.n))
                pbar.n = duration
                pbar.refresh()
            else:
                proc.wait()
                pbar.n = pbar.total
                pbar.refresh()

            pbar.close()

            if proc.returncode != 0:
                stderr = proc.stderr.read().decode("utf-8", errors="replace")[:200]
                print(f"  ffmpeg 错误：{stderr}")
                if os.path.exists(wav_path):
                    os.unlink(wav_path)
                return None

            return wav_path
        except Exception as e:
            pbar.close()
            print(f"  音轨提取失败：{e}")
            if os.path.exists(wav_path):
                os.unlink(wav_path)
            return None

    def _convert_to_mono_16k(self, audio_path):
        if not self._ffmpeg:
            ext = os.path.splitext(audio_path)[1].lower()
            if ext == ".wav":
                return audio_path
            raise RuntimeError(
                "未找到 ffmpeg，请安装：\n"
                "  Windows: pip install imageio-ffmpeg 或从 https://ffmpeg.org 下载\n"
                "  macOS: brew install ffmpeg\n"
                "  Linux: sudo apt install ffmpeg"
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        cmd = [
            self._ffmpeg, "-y", "-i", audio_path,
            "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", wav_path,
        ]

        duration = _get_duration(audio_path)
        pbar = tqdm(total=duration or 100, unit="s", desc="  转换格式", ncols=80)

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if duration:
                while proc.poll() is None:
                    time.sleep(0.5)
                    current = _get_duration_progress(wav_path)
                    if current is not None:
                        pbar.update(min(current - pbar.n, duration - pbar.n))
                pbar.n = duration
                pbar.refresh()
            else:
                proc.wait()
                pbar.n = pbar.total
                pbar.refresh()

            pbar.close()
            return wav_path if proc.returncode == 0 else None
        except Exception:
            pbar.close()
            if os.path.exists(wav_path):
                os.unlink(wav_path)
            return None

    def _get_whisper_model(self):
        if self._whisper_model_instance is None:
            import warnings
            warnings.filterwarnings("ignore", message=".*HF_HUB.*")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

            from faster_whisper import WhisperModel
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
            compute_type = "float16" if device == "cuda" else "int8"

            hf_endpoint = os.environ.get("HF_ENDPOINT", "")
            mirror_info = f" (mirror: {hf_endpoint})" if hf_endpoint else ""
            print(f"  加载 Whisper {self.whisper_model}{mirror_info}...")
            if not hf_endpoint:
                print("  提示：首次下载模型较慢，可在 .env 中设置 HF_ENDPOINT=https://hf-mirror.com 加速")

            self._whisper_model_instance = WhisperModel(
                self.whisper_model,
                device=device,
                compute_type=compute_type,
            )
            print(f"  模型加载完成")
        return self._whisper_model_instance

    def _transcribe(self, wav_path, total_duration=None):
        model = self._get_whisper_model()
        t_start = time.time()

        segments, info = model.transcribe(
            wav_path,
            language=None,
            task="transcribe",
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        detected_lang = info.language
        duration = total_duration or info.duration
        print(f"  语言: {detected_lang} | 时长: {duration:.0f}s")

        pbar = tqdm(total=duration, unit="s", desc="  转写进度", ncols=80)
        lines = []
        last_end = 0

        for segment in segments:
            seg_start = segment.start
            ts = f"[{int(seg_start) // 60:02d}:{int(seg_start) % 60:02d}]"
            text = segment.text.strip()
            if text:
                lines.append(f"{ts} {text}")

            pbar.update(segment.end - last_end)
            last_end = segment.end
            pbar.set_postfix_str(f"{len(lines)} 段")

        pbar.close()
        elapsed = time.time() - t_start
        speed = duration / elapsed if elapsed > 0 else 0
        print(f"  完成：{len(lines)} 段 | 耗时 {elapsed:.1f}s | 速度 {speed:.1f}x")

        if wav_path and os.path.exists(wav_path):
            os.unlink(wav_path)

        return "\n".join(lines)


def _get_duration_progress(file_path):
    """快速获取已写入文件的时长"""
    if not os.path.exists(file_path):
        return None
    size = os.path.getsize(file_path)
    return size / (16000 * 2)  # 16kHz, 16bit mono
