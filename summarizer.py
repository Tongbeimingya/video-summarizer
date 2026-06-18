import time
from openai import OpenAI


GRANULARITY_INSTRUCTIONS = {
    "brief": "请用简洁的语言生成精简版总结，重点突出核心观点，控制在800字以内。",
    "standard": "请生成标准详细的学习笔记式总结，覆盖核心知识点和关键细节。",
    "detailed": "请生成非常详细的学习笔记式总结，覆盖所有知识点、关键细节、公式、定义、操作步骤等，尽量不遗漏任何重要内容。",
}

PROMPT_TEMPLATE = """你是一个专业的学习助手。请根据以下视频内容，生成一份学习笔记式总结。

要求：
- 面向学生群体，帮助他们理解和学习视频中的知识
- 按视频内容的逻辑顺序组织，适当分章节/主题
- 关键概念用加粗标注，重要数据/公式/定义要保留
- 在每段要点前标注对应的时间戳[MM:SS]，方便回看
- 适当加入自己的理解说明，帮助学生更好地理解难点

{granularity}

视频标题：{title}

字幕/内容：
{subtitle_text}

{vision_section}

请以Markdown格式直接输出总结内容，使用合理的标题层级和列表格式。
不要输出JSON，不要输出多余说明，直接输出Markdown格式的总结文本。
"""

VISION_SECTION_TEMPLATE = """
以下是视频关键帧的视觉识别结果（按时间戳排列），请将这些视觉信息与语音内容融合：
{vision_text}
"""


class VideoSummarizer:

    def __init__(self, api_key, base_url, model, max_retries=3):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries

    def summarize(self, title, subtitle_text, granularity="standard", vision_results=None):
        granularity_instruction = GRANULARITY_INSTRUCTIONS.get(
            granularity, GRANULARITY_INSTRUCTIONS["standard"]
        )

        vision_section = ""
        if vision_results:
            vision_lines = []
            for vr in vision_results:
                ts = vr["timestamp"]
                ts_str = f"[{int(ts)//60:02d}:{int(ts)%60:02d}]"
                vision_lines.append(f"{ts_str} {vr['description']}")
            vision_section = VISION_SECTION_TEMPLATE.format(
                vision_text="\n".join(vision_lines)
            )

        prompt = PROMPT_TEMPLATE.format(
            title=title,
            subtitle_text=subtitle_text,
            granularity=granularity_instruction,
            vision_section=vision_section,
        )

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个专业的学习助手，擅长整理和总结学习内容。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4096,
                )
                result = response.choices[0].message.content
                if result:
                    return result.strip()
                raise RuntimeError("API 返回内容为空")
            except Exception as e:
                last_error = e
                error_msg = str(e)
                if "401" in error_msg or "Unauthorized" in error_msg:
                    raise RuntimeError("API Key 无效，请检查 .env 中的 DEEPSEEK_API_KEY 配置。")
                if "429" in error_msg or "rate" in error_msg.lower():
                    wait_time = min(2 ** attempt * 5, 30)
                    if attempt < self.max_retries - 1:
                        time.sleep(wait_time)
                        continue
                    raise RuntimeError("API 调用频率过高，请稍后重试。")
                if "timeout" in error_msg.lower():
                    if attempt < self.max_retries - 1:
                        time.sleep(3)
                        continue
                    raise RuntimeError("API 调用超时，请检查网络连接后重试。")
                if "500" in error_msg or "502" in error_msg or "503" in error_msg:
                    if attempt < self.max_retries - 1:
                        time.sleep(3)
                        continue
                if attempt < self.max_retries - 1:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"API 调用失败：{error_msg}")
