import sys
import io
import os
import time
import click

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from config import load_config
from subtitle_extractor import SubtitleExtractor
from audio_processor import AudioProcessor, SUPPORTED_EXTENSIONS
from summarizer import VideoSummarizer
from exporter import export_markdown, save_file, get_mindmap_code
from history import add_record, get_all_records, get_total_count
from logger_setup import setup_logger

logger = setup_logger()


@click.command()
@click.option("--url", default=None, help="在线视频链接（支持B站、YouTube等主流平台）")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="本地音视频文件路径")
@click.option("--output", "output_dir", default=None, type=click.Path(), help="输出目录（默认 output/）")
@click.option("--vision", is_flag=True, default=False, help="启用视觉增强模式（需配置视觉模型）")
@click.option("--batch", default=None, type=click.Path(exists=True), help="批量处理：传入txt文件，每行一个视频链接")
@click.option("--history", "show_history", is_flag=True, default=False, help="查看历史处理记录")
@click.option("--granularity", type=click.Choice(["brief", "standard", "detailed"]),
              default="standard", help="总结粒度：brief/standard/detailed")
def main(url, file_path, output_dir, vision, batch, show_history, granularity):
    """Video Summarizer - AI视频学习笔记生成器"""
    if show_history:
        _show_history()
        return

    if batch:
        _process_batch(batch, vision, output_dir, granularity)
        return

    if not url and not file_path:
        print("错误：请指定 --url、--file 或 --batch 参数", file=sys.stderr)
        print("用法：python main.py --url <视频链接>", file=sys.stderr)
        print("      python main.py --file <本地文件>", file=sys.stderr)
        print("      python main.py --batch <links.txt>", file=sys.stderr)
        print("      python main.py --history", file=sys.stderr)
        sys.exit(1)

    if url and file_path:
        print("错误：--url 和 --file 只能指定一个", file=sys.stderr)
        sys.exit(1)

    config = load_config()

    if file_path:
        _process_local_file(file_path, config, output_dir, vision, granularity)
    else:
        _process_online_video(url, config, output_dir, vision, granularity)


def _process_batch(batch_file, vision, output_dir, granularity):
    config = load_config()
    with open(batch_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not urls:
        print("错误：批量文件中没有有效链接", file=sys.stderr)
        sys.exit(1)

    total = len(urls)
    print(f"批量处理：共 {total} 个视频链接")
    print("=" * 50)

    results = []
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] {url}")
        print("-" * 40)
        t_start = time.time()
        try:
            _process_online_video(url, config, output_dir, vision, granularity, record=False)
            elapsed = time.time() - t_start
            results.append({"url": url, "status": "success", "elapsed": elapsed})
            print(f"  -> 成功 ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - t_start
            results.append({"url": url, "status": "failed", "error": str(e), "elapsed": elapsed})
            logger.error(f"Batch item failed: {url} - {e}")
            print(f"  -> 失败: {e}")

    print("\n" + "=" * 50)
    success = sum(1 for r in results if r["status"] == "success")
    failed = total - success
    print(f"完成：{success} 成功 / {failed} 失败 / {total} 总计")

    if failed > 0:
        print("\n失败列表：")
        for r in results:
            if r["status"] == "failed":
                print(f"  - {r['url']}: {r['error']}")


def _process_local_file(file_path, config, output_dir, vision, granularity):
    ext = os.path.splitext(file_path)[1].lower()
    print(f"[1/5] 本地文件：{os.path.basename(file_path)}")
    print(f"[2/5] 处理音视频文件...")

    processor = AudioProcessor(whisper_model=config["whisper_model"])
    try:
        title, subtitle_text, lang = processor.process_file(file_path)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"文件处理失败：{e}", file=sys.stderr)
        sys.exit(1)

    vision_results = None
    if vision:
        vision_results = _run_vision(config, file_path)

    _run_summarize(title, subtitle_text, lang, config, output_dir,
                   url="", vision_results=vision_results,
                   granularity=granularity, source_type="local_file")


def _process_online_video(url, config, output_dir, vision, granularity, record=True):
    print(f"[1/5] 正在解析视频链接：{url}")
    print("[2/5] 正在提取字幕（优先平台字幕，无则自动语音识别）...")

    extractor = SubtitleExtractor(whisper_model=config["whisper_model"])
    try:
        title, subtitle_text, lang = extractor.extract(url)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        if record:
            sys.exit(1)
        raise
    except Exception as e:
        print(f"链接解析失败：{e}", file=sys.stderr)
        if record:
            sys.exit(1)
        raise

    _run_summarize(title, subtitle_text, lang, config, output_dir,
                   url=url, vision_results=None,
                   granularity=granularity, source_type="online",
                   record=record)


def _run_vision(config, file_path):
    from vision_processor import VisionProcessor
    print("[Vision] 启用视觉增强模式...")
    vp = VisionProcessor(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["vision_model"],
        interval=config["vision_interval"],
        scene_threshold=config["vision_scene_threshold"],
    )
    try:
        return vp.process_video(file_path)
    except Exception as e:
        print(f"  [Vision] 视觉处理失败: {e}，将仅使用语音内容")
        logger.warning(f"Vision processing failed: {e}")
        return None


def _run_summarize(title, subtitle_text, lang, config, output_dir,
                   url="", vision_results=None, granularity="standard",
                   source_type="", record=True):
    source_map = {
        "zh": "中文字幕", "en": "英文字幕",
        "whisper": "ASR 语音识别", "asr": "ASR 语音识别",
    }
    source = source_map.get(lang, lang)
    print(f"  标题：{title}")
    print(f"  来源：{source}")
    print(f"  文本：{len(subtitle_text)} 字符")
    print(f"  粒度：{granularity}")

    print("[3/5] 正在调用大模型生成总结...")
    summarizer = VideoSummarizer(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
    )
    t_start = time.time()
    try:
        summary_text = summarizer.summarize(
            title, subtitle_text,
            granularity=granularity,
            vision_results=vision_results,
        )
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        if record:
            sys.exit(1)
        raise
    except Exception as e:
        print(f"总结生成失败：{e}", file=sys.stderr)
        if record:
            sys.exit(1)
        raise
    elapsed = time.time() - t_start
    logger.info(f"Summarize completed: {title} in {elapsed:.1f}s")

    print("[4/5] 正在保存文件...")
    content = export_markdown(title, summary_text, url=url)
    filepath = save_file(title, content, output_dir=output_dir)
    print(f"  -> Markdown: {filepath}")

    if record:
        print("[5/5] 记录历史...")
        add_record(
            title=title,
            url=url,
            source_type=source_type,
            md_path=filepath,
            char_count=len(subtitle_text),
            summary_granularity=granularity,
            vision_enabled=vision_results is not None,
        )

    print(f"\n总结已保存至：{filepath}")


def _show_history():
    total = get_total_count()
    records = get_all_records(limit=50)

    if not records:
        print("暂无历史记录")
        return

    print(f"历史记录（共 {total} 条，显示最近 {len(records)} 条）")
    print("=" * 80)
    print(f"{'ID':<5} {'时间':<20} {'标题':<35} {'来源':<10}")
    print("-" * 80)

    for r in records:
        title_short = r["title"][:32] + "..." if len(r["title"]) > 35 else r["title"]
        print(f"{r['id']:<5} {r['created_at_str']:<20} {title_short:<35} {r['source_type']:<10}")

    print("-" * 80)
    print("提示：使用网页端查看详细历史记录")


if __name__ == "__main__":
    main()
