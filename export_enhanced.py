import os
import re
import tempfile


def export_mindmap_png(mermaid_code, output_path):
    """Export mindmap as PNG using playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "PNG export requires playwright.\n"
            "Install: pip install playwright && playwright install chromium"
        )

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
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
    """Export summary as PDF. Tries weasyprint, falls back to HTML."""
    try:
        from weasyprint import HTML
        html_content = _markdown_to_html(markdown_text)
        HTML(string=html_content).write_pdf(output_path)
        return True
    except (ImportError, Exception):
        pass

    html_content = _markdown_to_html(markdown_text)
    with open(output_path.replace('.pdf', '.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)
    raise RuntimeError(
        "PDF export requires weasyprint.\n"
        "HTML version has been saved. You can print it as PDF from your browser."
    )


def _markdown_to_html(md_text):
    try:
        import markdown
        body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        body = _basic_md_to_html(md_text)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>视频总结</title>
<style>
body {{ font-family: -apple-system, "Microsoft YaHei", "Noto Sans SC", sans-serif; max-width:800px;
        margin:0 auto; padding:20px; line-height:1.8; color:#333; font-size:14px; }}
h1 {{ font-size:1.8em; border-bottom:2px solid #3b82f6; padding-bottom:8px; }}
h2 {{ font-size:1.4em; color:#1e40af; margin-top:1.5em; }}
h3 {{ font-size:1.15em; color:#374151; }}
blockquote {{ border-left:3px solid #3b82f6; padding-left:12px; color:#6b7280; margin:12px 0; background:#f8fafc; padding:8px 12px; border-radius:0 6px 6px 0; }}
code {{ background:#f1f5f9; padding:2px 6px; border-radius:4px; font-size:0.9em; color:#e11d48; }}
pre {{ background:#1e293b; color:#e2e8f0; padding:12px; border-radius:8px; overflow-x:auto; }}
pre code {{ background:none; color:inherit; padding:0; }}
strong {{ color:#1e40af; }}
table {{ border-collapse:collapse; width:100%; margin:12px 0; }}
th, td {{ border:1px solid #e5e7eb; padding:8px 12px; text-align:left; }}
th {{ background:#f8fafc; font-weight:600; }}
hr {{ border:none; border-top:1px solid #e5e7eb; margin:16px 0; }}
a {{ color:#3b82f6; }}
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
