import os
import re
import uuid
import time
import sys
import io
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from flask import Flask, request, jsonify, send_from_directory, render_template

from config import load_config
from subtitle_extractor import SubtitleExtractor
from audio_processor import AudioProcessor, SUPPORTED_EXTENSIONS
from summarizer import VideoSummarizer
from exporter import export_markdown, save_file, get_mindmap_code
from history import add_record, get_all_records, get_record, delete_record, get_total_count
from logger_setup import setup_logger

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

tasks = {}
executor = ThreadPoolExecutor(max_workers=2)
logger = setup_logger()

ACTIVATION_CODE = "tongbeimingyyya"
FREE_USAGE_LIMIT = 5
activation_store = {}


def _cleanup_old_tasks():
    """Remove completed tasks older than 1 hour to free memory."""
    now = time.time()
    expired = [tid for tid, t in tasks.items()
               if t["status"] in ("done", "error") and now - t.get("created_at", now) > 3600]
    for tid in expired:
        tasks.pop(tid, None)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route("/api/activate", methods=["POST"])
def activate():
    data = request.get_json() or {}
    code = data.get("code", "").strip()
    fingerprint = data.get("fingerprint", "").strip()

    if not fingerprint:
        return jsonify({"error": "无效请求"}), 400

    if code == ACTIVATION_CODE:
        activation_store[fingerprint] = {"activated": True, "time": time.time()}
        return jsonify({"ok": True, "activated": True, "message": "激活成功！已解锁无限使用"})

    return jsonify({"ok": False, "activated": False, "message": "激活码无效"}), 400


@app.route("/api/check-usage", methods=["POST"])
def check_usage():
    data = request.get_json() or {}
    fingerprint = data.get("fingerprint", "").strip()
    usage_count = data.get("usage_count", 0)

    if not fingerprint:
        return jsonify({"error": "无效请求"}), 400

    if fingerprint in activation_store and activation_store[fingerprint].get("activated"):
        return jsonify({"activated": True, "remaining": -1, "can_use": True})

    can_use = usage_count < FREE_USAGE_LIMIT
    remaining = max(0, FREE_USAGE_LIMIT - usage_count)

    return jsonify({"activated": False, "remaining": remaining, "can_use": can_use})


@app.route("/api/submit", methods=["POST"])
def submit():
    _cleanup_old_tasks()
    url = request.form.get("url", "").strip()
    file = request.files.get("file")
    vision = request.form.get("vision", "false") == "true"
    granularity = request.form.get("granularity", "standard")

    if not url and not file:
        return jsonify({"error": "请提供视频链接或上传文件"}), 400

    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "等待处理...",
        "title": "",
        "summary": "",
        "mindmap": "",
        "markdown": "",
        "error": None,
        "created_at": time.time(),
        "url": url,
        "vision": vision,
        "granularity": granularity,
    }

    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            tasks[task_id]["status"] = "error"
            tasks[task_id]["error"] = f"不支持的文件格式：{ext}"
            return jsonify({"task_id": task_id, "error": tasks[task_id]["error"]}), 400

        filepath = os.path.join(UPLOAD_DIR, f"{task_id}{ext}")
        file.save(filepath)
        executor.submit(_process_task, task_id, None, filepath)
    else:
        executor.submit(_process_task, task_id, url, None)

    return jsonify({"task_id": task_id})


@app.route("/api/progress/<task_id>")
def progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)


@app.route("/api/result/<task_id>")
def result(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    if task["status"] != "done":
        return jsonify({"error": "任务未完成", "status": task["status"]}), 202
    return jsonify({
        "title": task["title"],
        "summary": task["summary"],
        "mindmap": task["mindmap"],
        "markdown": task["markdown"],
        "url": task.get("url", ""),
    })


@app.route("/api/download/<task_id>")
def download(task_id):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "文件不存在"}), 404
    if not task.get("markdown"):
        return jsonify({"error": "内容为空"}), 404
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", task["title"][:50]) or "summary"
    safe_title = safe_title.strip("_. ")
    filename = f"{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    return jsonify({"filename": filename, "content": task["markdown"]})


@app.route("/api/mindmap-png/<task_id>")
def mindmap_png(task_id):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "文件不存在"}), 404
    if not task.get("mindmap"):
        return jsonify({"error": "无思维导图数据"}), 404

    try:
        from export_enhanced import export_mindmap_png
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            png_path = f.name
        export_mindmap_png(task["mindmap"], png_path)
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", task["title"][:30]) or "mindmap"
        return send_from_directory(
            os.path.dirname(png_path),
            os.path.basename(png_path),
            as_attachment=True,
            download_name=f"{safe_title}_mindmap.png",
        )
    except Exception as e:
        logger.error(f"PNG export failed for task {task_id}: {e}")
        return jsonify({"error": f"PNG 导出失败：{e}"}), 500


@app.route("/api/summary-pdf/<task_id>")
def summary_pdf(task_id):
    task = tasks.get(task_id)
    if not task or task["status"] != "done":
        return jsonify({"error": "文件不存在"}), 404
    if not task.get("markdown"):
        return jsonify({"error": "内容为空"}), 404

    try:
        from export_enhanced import export_summary_pdf
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
        export_summary_pdf(task["markdown"], pdf_path)
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", task["title"][:30]) or "summary"
        return send_from_directory(
            os.path.dirname(pdf_path),
            os.path.basename(pdf_path),
            as_attachment=True,
            download_name=f"{safe_title}_summary.pdf",
        )
    except Exception as e:
        logger.error(f"PDF export failed for task {task_id}: {e}")
        return jsonify({"error": f"PDF 导出失败：{e}"}), 500


@app.route("/api/history")
def api_history():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    offset = (page - 1) * per_page
    records = get_all_records(limit=per_page, offset=offset)
    total = get_total_count()
    return jsonify({
        "records": records,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


@app.route("/api/history/<int:record_id>")
def api_history_detail(record_id):
    record = get_record(record_id)
    if not record:
        return jsonify({"error": "记录不存在"}), 404
    if record.get("md_path") and os.path.exists(record["md_path"]):
        with open(record["md_path"], "r", encoding="utf-8") as f:
            record["markdown"] = f.read()
    else:
        record["markdown"] = ""
    return jsonify(record)


@app.route("/api/history/<int:record_id>", methods=["DELETE"])
def api_history_delete(record_id):
    delete_record(record_id)
    return jsonify({"ok": True})


def _process_task(task_id, url, file_path):
    task = tasks[task_id]
    try:
        config = load_config()
        task["status"] = "processing"
        task["progress"] = 5
        task["message"] = "正在初始化..."
        logger.info(f"Task {task_id} started: url={url}, file={file_path}")

        if file_path:
            _process_file(task, task_id, file_path, config)
        else:
            _process_url(task, task_id, url, config)

    except Exception as e:
        error_msg = str(e)
        task["status"] = "error"
        task["error"] = error_msg
        task["message"] = f"处理失败：{error_msg}"
        logger.error(f"Task {task_id} failed: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except Exception:
                pass


def _process_file(task, task_id, file_path, config):
    task["message"] = "正在提取音轨..."
    task["progress"] = 5

    processor = AudioProcessor(whisper_model=config["whisper_model"])
    title, subtitle_text, lang = processor.process_file(file_path)

    task["progress"] = 25
    task["message"] = "语音识别完成，准备总结..."

    vision_results = None
    if task.get("vision"):
        task["message"] = "正在提取关键帧..."
        task["progress"] = 30
        try:
            from vision_processor import VisionProcessor
            vp = VisionProcessor(
                api_key=config["api_key"],
                base_url=config["base_url"],
                model=config["vision_model"],
                interval=config["vision_interval"],
                scene_threshold=config["vision_scene_threshold"],
            )
            vision_results = vp.process_video(file_path)
            task["progress"] = 45
        except Exception as e:
            logger.warning(f"Vision processing failed for task {task_id}: {e}")

    task["progress"] = 50
    task["message"] = "正在调用 AI 生成总结..."
    _do_summarize(task, task_id, title, subtitle_text, lang, config,
                  url="", vision_results=vision_results)


def _process_url(task, task_id, url, config):
    task["message"] = "正在解析视频链接..."
    task["progress"] = 5

    extractor = SubtitleExtractor(whisper_model=config["whisper_model"])
    title, subtitle_text, lang = extractor.extract(url)

    task["progress"] = 25
    task["message"] = "正在获取字幕内容..."

    if subtitle_text:
        task["progress"] = 45
        task["message"] = "字幕提取完成，准备总结..."
    else:
        task["progress"] = 35
        task["message"] = "正在语音识别..."

    task["progress"] = 50
    task["message"] = "正在调用 AI 生成总结..."
    _do_summarize(task, task_id, title, subtitle_text, lang, config,
                  url=url, vision_results=None)


def _do_summarize(task, task_id, title, subtitle_text, lang, config,
                  url="", vision_results=None):
    import threading

    summarizer = VideoSummarizer(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
    )

    granularity = task.get("granularity", "standard")

    progress_stop = threading.Event()
    progress_step = [50]

    def advance_progress():
        while not progress_stop.is_set():
            if progress_step[0] < 88:
                progress_step[0] += 1
                task["progress"] = progress_step[0]
                if progress_step[0] < 70:
                    task["message"] = "正在调用 AI 生成总结..."
                elif progress_step[0] < 80:
                    task["message"] = "AI 正在分析内容..."
                else:
                    task["message"] = "正在整理输出..."
            progress_stop.wait(2.0)

    t = threading.Thread(target=advance_progress, daemon=True)
    t.start()

    try:
        summary_text = summarizer.summarize(
            title, subtitle_text,
            granularity=granularity,
            vision_results=vision_results,
        )
    finally:
        progress_stop.set()
        t.join(timeout=3)

    task["progress"] = 90
    task["message"] = "正在格式化输出..."

    markdown = export_markdown(title, summary_text, url=url)

    mindmap_code = get_mindmap_code(summary_text)
    task["mindmap"] = mindmap_code

    md_path = save_file(title, markdown)

    add_record(
        title=title,
        url=url,
        source_type="web",
        md_path=md_path,
        char_count=len(subtitle_text),
        summary_granularity=granularity,
        vision_enabled=vision_results is not None,
    )

    task["status"] = "done"
    task["progress"] = 100
    task["message"] = "完成"
    task["title"] = title
    task["summary"] = summary_text
    task["markdown"] = markdown
    logger.info(f"Task {task_id} completed: {title}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
