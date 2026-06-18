import os
import re
import subprocess
import tempfile


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


def export_mindmap_png(mermaid_code, output_path):
    try:
        from mermaid_cli import mmdc
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as f:
            f.write(mermaid_code)
            mmd_path = f.name
        try:
            mmdc(mmd_path, output_path, width=1920, height=1080, backgroundColor="white")
            return True
        except Exception:
            pass
        finally:
            if os.path.exists(mmd_path):
                os.unlink(mmd_path)
    except ImportError:
        pass

    return _export_mindmap_png_fallback(mermaid_code, output_path)


def _export_mindmap_png_fallback(mermaid_code, output_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "PNG export requires playwright or mermaid-cli.\n"
            "Install: pip install playwright && playwright install chromium\n"
            "Or: pip install mermaid-cli"
        )

    html = f"""<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<style>
body {{ margin:0; padding:20px; background:white; display:flex; justify-content:center; }}
#diagram {{ max-width:1800px; }}
</style>
</head><body>
<div id="diagram" class="mermaid">{mermaid_code}</div>
<script>mermaid.initialize({{startOnLoad:true,theme:'default',securityLevel:'loose'}});</script>
</body></html>"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        html_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"file:///{html_path.replace(os.sep, '/')}")
            page.wait_for_timeout(3000)
            page.locator("#diagram").screenshot(path=output_path)
            browser.close()
        return True
    except Exception as e:
        raise RuntimeError(f"PNG export failed: {e}")
    finally:
        if os.path.exists(html_path):
            os.unlink(html_path)


def export_summary_pdf(markdown_text, output_path):
    try:
        from weasyprint import HTML
        html_content = _markdown_to_html(markdown_text)
        HTML(string=html_content).write_pdf(output_path)
        return True
    except ImportError:
        pass

    return _export_pdf_fallback(markdown_text, output_path)


def _export_pdf_fallback(markdown_text, output_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "PDF export requires weasyprint or playwright.\n"
            "Install: pip install weasyprint\n"
            "Or: pip install playwright && playwright install chromium"
        )

    html_content = _markdown_to_html(markdown_text)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_content)
        html_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file:///{html_path.replace(os.sep, '/')}")
            page.wait_for_timeout(1000)
            page.pdf(path=output_path, format="A4", margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"})
            browser.close()
        return True
    except Exception as e:
        raise RuntimeError(f"PDF export failed: {e}")
    finally:
        if os.path.exists(html_path):
            os.unlink(html_path)


def _markdown_to_html(md_text):
    try:
        import markdown
        body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        body = _basic_md_to_html(md_text)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; max-width:800px;
        margin:0 auto; padding:20px; line-height:1.7; color:#333; font-size:14px; }}
h1 {{ font-size:1.8em; border-bottom:2px solid #3b82f6; padding-bottom:8px; }}
h2 {{ font-size:1.4em; color:#1e40af; margin-top:1.5em; }}
h3 {{ font-size:1.15em; color:#374151; }}
blockquote {{ border-left:3px solid #3b82f6; padding-left:12px; color:#6b7280; margin:12px 0; }}
code {{ background:#f3f4f6; padding:2px 6px; border-radius:4px; font-size:0.9em; }}
pre {{ background:#f3f4f6; padding:12px; border-radius:8px; overflow-x:auto; }}
strong {{ color:#1e40af; }}
table {{ border-collapse:collapse; width:100%; margin:12px 0; }}
th, td {{ border:1px solid #e5e7eb; padding:8px 12px; text-align:left; }}
th {{ background:#f9fafb; }}
hr {{ border:none; border-top:1px solid #e5e7eb; margin:16px 0; }}
</style></head><body>{body}</body></html>"""


def _basic_md_to_html(text):
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", text, flags=re.DOTALL)
    text = re.sub(r"^---+$", "<hr>", text, flags=re.MULTILINE)
    text = re.sub(r"^> (.+)$", r"<blockquote>\1</blockquote>", text, flags=re.MULTILINE)
    text = re.sub(r"\n\n", "</p><p>", text)
    return f"<p>{text}</p>"
