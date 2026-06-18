import os
from dotenv import load_dotenv


def load_config():
    load_dotenv()

    hf_mirror = os.getenv("HF_ENDPOINT", "")
    if hf_mirror:
        os.environ["HF_ENDPOINT"] = hf_mirror

    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    whisper_model = os.getenv("WHISPER_MODEL", "tiny")

    vision_model = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-vl2")
    vision_interval = int(os.getenv("VISION_INTERVAL", "10"))
    vision_scene_threshold = float(os.getenv("VISION_SCENE_THRESHOLD", "0.3"))

    if not api_key:
        raise ValueError(
            "未找到 DEEPSEEK_API_KEY，请在项目根目录创建 .env 文件并填入你的 API Key。\n"
            "参考 .env.example 文件进行配置。"
        )

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "whisper_model": whisper_model,
        "vision_model": vision_model,
        "vision_interval": vision_interval,
        "vision_scene_threshold": vision_scene_threshold,
    }
