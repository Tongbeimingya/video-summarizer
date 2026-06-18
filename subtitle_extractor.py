import re
import os
import json
import glob
import tempfile
import subprocess
import time
import urllib.request
import yt_dlp
from tqdm import tqdm

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


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


def _is_bilibili(url):
    return "bilibili.com" in url or "b23.tv" in url


def _extract_bvid(url):
    match = re.search(r"(BV[a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def _api_get(url):
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


class BilibiliExtractor:

    def get_video_info(self, bvid):
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        data = _api_get(url)
        if data.get("code") != 0:
            raise RuntimeError(f"Bilibili API 错误：{data.get('message', '未知错误')}")
        return data["data"]

    def get_subtitle(self, bvid, cid):
        player_url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
        player_data = _api_get(player_url)
        if player_data.get("code") != 0:
            return None

        subtitles = player_data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            return None

        chosen = None
        for sub in subtitles:
            if "zh" in sub.get("lan", ""):
                chosen = sub
                break
        if not chosen:
            chosen = subtitles[0]

        sub_url = chosen.get("subtitle_url", "")
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url

        sub_data = _api_get(sub_url)
        return sub_data, chosen.get("lan", "zh")

    def extract(self, url):
        bvid = _extract_bvid(url)
        if not bvid:
            return None

        info = self.get_video_info(bvid)
        title = info.get("title", "未知标题")
        cid = info.get("cid") or info.get("pages", [{}])[0].get("cid")

        if not cid:
            return title, None, None

        try:
            sub_data, lang = self.get_subtitle(bvid, cid)
            if sub_data:
                body = sub_data.get("body", [])
                lines = []
                for item in body:
                    from_time = item.get("from", 0)
                    content = item.get("content", "").strip()
                    if content:
                        ts = f"[{int(from_time) // 60:02d}:{int(from_time) % 60:02d}]"
                        lines.append(f"{ts} {content}")
                if lines:
                    return title, "\n".join(lines), lang
        except Exception:
            pass

        return title, None, None


class SubtitleExtractor:

    def __init__(self, whisper_model="small"):
        self.whisper_model = whisper_model
        self._whisper_model_instance = None
        self._ffmpeg = _get_ffmpeg_bin()
        self._bilibili = BilibiliExtractor()

    def extract(self, url):
        with tempfile.TemporaryDirectory() as tmpdir:
            if _is_bilibili(url):
                print("  [Bilibili] 使用专用 API...")
                result = self._bilibili.extract(url)
                if result:
                    title, sub_text, lang = result
                    if sub_text:
                        print("  -> 获取到平台字幕")
                        return title, sub_text, lang
                    print("  -> 无字幕，降级到 ASR")
                    bvid = _extract_bvid(url)
                    if not bvid:
                        raise RuntimeError("无法解析 Bilibili 链接")
                    audio_path = self._download_bilibili_audio(bvid, tmpdir)
                    if audio_path:
                        text = self._transcribe(audio_path)
                        if text.strip():
                            return title or "未知标题", text, "whisper"
                    raise RuntimeError("无法获取音频，请检查链接是否正确。")

            print("  [yt-dlp] 尝试提取平台字幕...")
            title, subtitle_path, lang = self._download_subtitle_ytdlp(url, tmpdir)
            if subtitle_path:
                raw_text = self._read_file(subtitle_path)
                cleaned = self._clean_subtitle(raw_text, subtitle_path)
                if cleaned.strip():
                    print("  -> 获取到平台字幕")
                    return title, cleaned, lang
                print("  -> 字幕为空，降级到 ASR")

            if not title:
                title = self._get_title_only(url, tmpdir)

            print("  [下载音频]")
            audio_path = self._download_audio(url, tmpdir)
            if not audio_path:
                raise RuntimeError("无法下载视频音频，请检查链接是否正确。")

            text = self._transcribe(audio_path)
            if not text.strip():
                raise RuntimeError("语音识别结果为空，视频可能没有语音内容。")

            return title or "未知标题", text, "whisper"

    def _download_bilibili_audio(self, bvid, tmpdir):
        try:
            info_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            info_data = _api_get(info_url)
            if info_data.get("code") != 0:
                return None

            cid = info_data["data"].get("cid")
            if not cid:
                return None

            play_url = f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=16&qn=64"
            play_data = _api_get(play_url)
            if play_data.get("code") != 0:
                return None

            dash = play_data.get("data", {}).get("dash", {})
            audio_list = dash.get("audio", [])
            if not audio_list:
                return None

            audio_url = audio_list[0].get("baseUrl") or audio_list[0].get("base_url")
            if not audio_url:
                return None

            audio_path = os.path.join(tmpdir, f"{bvid}.m4a")
            req = urllib.request.Request(audio_url, headers={
                **BROWSER_HEADERS,
                "Referer": f"https://www.bilibili.com/video/{bvid}",
            })

            pbar = tqdm(desc="  下载音频", unit="B", unit_scale=True, ncols=80)
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0)) or None
                pbar.total = total
                with open(audio_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        pbar.update(len(chunk))
            pbar.close()

            return audio_path if os.path.exists(audio_path) else None
        except Exception as e:
            print(f"  Bilibili 音频下载失败：{e}")
            return None

    def _get_base_ydl_opts(self, tmpdir):
        opts = {
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "http_headers": BROWSER_HEADERS,
        }
        if self._ffmpeg:
            opts["ffmpeg_location"] = os.path.dirname(self._ffmpeg)
        return opts

    def _download_subtitle_ytdlp(self, url, tmpdir):
        zh_langs = ["zh-Hans", "zh", "zh-CN", "zh-Hant"]
        en_langs = ["en"]

        for langs in [zh_langs, en_langs]:
            title, path, lang = self._try_download_subtitle(url, tmpdir, langs)
            if path:
                return title, path, lang

        title = self._get_title_only(url, tmpdir)
        return title, None, None

    def _get_title_only(self, url, tmpdir):
        opts = self._get_base_ydl_opts(tmpdir)
        opts["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("title", "未知标题")
        except Exception:
            return None

    def _try_download_subtitle(self, url, tmpdir, lang_list):
        opts = self._get_base_ydl_opts(tmpdir)
        opts.update({
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": lang_list,
            "subtitlesformat": "json3/srv3/vtt/srt/best",
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "未知标题")
                requested_langs = info.get("requested_subtitles") or {}
                if not requested_langs:
                    return title, None, None

                chosen_lang = next(iter(requested_langs))
                sub_info = requested_langs[chosen_lang]
                sub_path = sub_info.get("filepath")
                if not sub_path:
                    sub_path = os.path.join(
                        tmpdir,
                        f"{info['id']}.{chosen_lang}.{sub_info.get('ext', 'vtt')}"
                    )
                    ydl.download([url])

                if not os.path.exists(sub_path):
                    candidates = [
                        f for f in os.listdir(tmpdir)
                        if f.endswith(('.vtt', '.srt', '.json3', '.srv3'))
                    ]
                    if candidates:
                        sub_path = os.path.join(tmpdir, candidates[0])
                    else:
                        return title, None, None

                return title, sub_path, chosen_lang
        except Exception:
            return None, None, None

    def _download_audio(self, url, tmpdir):
        opts = self._get_base_ydl_opts(tmpdir)
        opts.update({
            "skip_download": False,
            "format": "bestaudio/best",
            "writesubtitles": False,
            "writeautomaticsub": False,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }],
        })

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            for ext in ["mp3", "wav", "m4a", "ogg", "opus", "webm"]:
                matches = glob.glob(os.path.join(tmpdir, f"*.{ext}"))
                if matches:
                    return matches[0]

            for f in os.listdir(tmpdir):
                if any(f.endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".webm")):
                    return os.path.join(tmpdir, f)

            return None
        except Exception as e:
            print(f"  音频下载失败：{e}")
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

    def _transcribe(self, audio_path):
        model = self._get_whisper_model()
        t_start = time.time()

        wav_path = self._to_wav_16k(audio_path)

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
        duration = info.duration
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

        if wav_path != audio_path and os.path.exists(wav_path):
            os.unlink(wav_path)

        return "\n".join(lines)

    def _to_wav_16k(self, audio_path):
        if not self._ffmpeg:
            return audio_path
        out_path = audio_path.rsplit(".", 1)[0] + "_16k.wav"
        cmd = [
            self._ffmpeg, "-y", "-i", audio_path,
            "-ar", "16000", "-ac", "1",
            "-acodec", "pcm_s16le", out_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            return out_path
        except Exception:
            return audio_path

    def _read_file(self, path):
        for enc in ["utf-8", "gbk", "latin-1"]:
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return ""

    def _clean_subtitle(self, text, path):
        if path.endswith(".json3"):
            return self._clean_json3(text)
        return self._clean_srt_vtt(text)

    def _clean_json3(self, text):
        try:
            data = json.loads(text)
            events = data.get("events", [])
            lines = []
            for event in events:
                segs = event.get("segs", [])
                t_start = event.get("tStartMs", 0)
                line = "".join(s.get("utf8", "") for s in segs).strip()
                if not line or line == "\n":
                    continue
                if re.match(r"^\d+$", line):
                    continue
                if re.match(r"^https?://\S+$", line):
                    continue
                timestamp = f"[{t_start // 60000:02d}:{(t_start % 60000) // 1000:02d}]"
                lines.append((t_start, timestamp, line))
            return self._dedupe_and_join(lines)
        except json.JSONDecodeError:
            return ""

    def _clean_srt_vtt(self, text):
        lines = text.split("\n")
        blocks = []
        current_ts = ""
        current_text = []

        ts_pattern = re.compile(
            r"(\d{1,2}:\d{2}:\d{2}[,.:]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.:]\d{3})"
        )
        vtt_header = re.compile(r"^(WEBVTT|Kind:|Language:)", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_text:
                    blocks.append((current_ts, " ".join(current_text)))
                    current_text = []
                    current_ts = ""
                continue

            if vtt_header.match(stripped) or re.match(r"^\d+$", stripped):
                continue

            ts_match = ts_pattern.search(stripped)
            if ts_match:
                if current_text:
                    blocks.append((current_ts, " ".join(current_text)))
                    current_text = []
                current_ts = self._parse_timestamp(ts_match.group(1))
                continue

            if stripped.startswith("align:") or stripped.startswith("position:"):
                continue

            clean_line = re.sub(r"<[^>]+>", "", stripped).strip()
            if clean_line and not re.match(r"^\d+$", clean_line):
                current_text.append(clean_line)

        if current_text:
            blocks.append((current_ts, " ".join(current_text)))

        deduped = []
        prev_text = ""
        for ts, txt in blocks:
            normalized = txt.strip()
            if normalized == prev_text or self._is_noise(normalized):
                continue
            deduped.append((0, ts, normalized))
            prev_text = normalized

        return self._dedupe_and_join(deduped)

    def _parse_timestamp(self, ts_str):
        ts_str = ts_str.replace(",", ".")
        parts = ts_str.replace(":", ".").split(".")
        while len(parts) < 3:
            parts.insert(0, "0")
        h, m, s = int(parts[-3]), int(parts[-2]), int(parts[-1])
        total_seconds = h * 3600 + m * 60 + s
        return f"[{total_seconds // 60:02d}:{total_seconds % 60:02d}]"

    def _is_noise(self, text):
        if not text or len(text) < 2:
            return True
        if re.match(r"^\d+$", text):
            return True
        if re.match(r"^(www\.|http|\.com|\.cn)", text, re.IGNORECASE):
            return True
        if re.match(r"^\[.*广告.*\]$", text):
            return True
        if re.match(r"^\[.*关注.*订阅.*\]$", text):
            return True
        return False

    def _dedupe_and_join(self, entries):
        result = []
        prev_text = ""
        for _, ts, txt in entries:
            normalized = txt.strip()
            if normalized == prev_text:
                continue
            if normalized:
                result.append(f"{ts} {normalized}")
                prev_text = normalized
        return "\n".join(result)
