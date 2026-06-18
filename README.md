# Video Summarizer - AI 视频学习笔记生成器

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## 功能

- 支持 B站、YouTube、抖音等主流视频平台链接
- 支持上传本地音视频文件（mp4/mov/mkv/mp3/wav 等）
- AI 自动生成学习笔记式总结
- 生成思维导图（Mermaid 格式）
- 三种总结粒度：精简 / 标准 / 详细
- 视觉增强模式（关键帧识别）
- 导出 Markdown / PDF / PNG
- 历史记录管理

## 在线使用

部署后访问你的 Render URL 即可使用。

## 本地运行

```bash
# 克隆仓库
git clone https://github.com/Tongbeimingya/video-summarizer.git
cd video-summarizer

# 安装依赖
pip install -r requirements.txt

# 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key

# 启动
python app.py
```

访问 http://localhost:7860

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必填） | - |
| `DEEPSEEK_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `WHISPER_MODEL` | Whisper 模型 | `tiny` |
| `HF_ENDPOINT` | HuggingFace 镜像 | - |

## 技术栈

- Python / Flask
- faster-whisper（语音识别）
- yt-dlp（视频下载）
- OpenAI API（LLM 总结）
- Tailwind CSS
- Mermaid（思维导图）

## License

MIT
