import os
import re
from datetime import datetime


def export_markdown(title, summary_text, url=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (
        f"# {title}\n\n"
        f"> 生成时间：{now}\n\n"
        f"---\n\n"
    )
    mindmap_section = _build_mindmap_section(summary_text)
    body = _inject_timestamp_links(summary_text, url)
    return header + body + "\n\n---\n\n" + mindmap_section


def _parse_heading_tree(summary_text):
    """Parse markdown headings into a nested tree structure.
    Returns list of (level, text) tuples."""
    lines = summary_text.split("\n")
    tree = []
    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            text = re.sub(r"\*+", "", text)
            text = re.sub(r"`([^`]+)`", r"\1", text)
            tree.append((level, text))
    return tree


def _build_mermaid_mindmap(tree, root_label):
    """Build a mermaid mindmap with proper multi-level hierarchy.
    
    Mermaid mindmap indentation rules:
    - root((...)) at indent 2
    - Level 1 children (##) at indent 4
    - Level 2 children (###) at indent 6
    - Level 3 children (####) at indent 8
    """
    if not tree:
        tree = [(2, "核心内容")]

    lines = ["mindmap"]
    root_text = _mermaid_safe(root_label)
    lines.append(f"  root(({root_text}))")

    for level, text in tree:
        cleaned = _sanitize(text)
        if not cleaned or len(cleaned) < 2:
            continue

        node_text = _mermaid_safe(cleaned)

        indent = "  " * level

        lines.append(f"{indent}{node_text}")

    return "\n".join(lines)


def _build_mindmap_section(summary_text):
    tree = _parse_heading_tree(summary_text)
    if not tree:
        tree = [(2, "视频内容")]

    root_heading = tree[0][1]
    child_headings = tree[1:]

    mermaid_code = _build_mermaid_mindmap(child_headings, root_heading)
    mermaid_code = validate_and_fix_mindmap(mermaid_code)

    return (
        "## 思维导图\n\n"
        "```mermaid\n"
        + mermaid_code
        + "\n```\n"
    )


def _mermaid_safe(text):
    """Make text safe for mermaid mindmap node labels."""
    text = text.strip()
    text = text.replace("(", "（").replace(")", "）")
    text = text.replace("[", "【").replace("]", "】")
    text = text.replace("{", "｛").replace("}", "｝")
    text = text.replace("<", "＜").replace(">", "＞")
    text = text.replace('"', "").replace("'", "")
    text = text.replace("\u201c", "").replace("\u201d", "")
    text = text.replace("\u2018", "").replace("\u2019", "")
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("\u3001", " ").replace("\u3002", " ")
    text = text.replace("\uff0c", " ").replace("\uff1a", " ").replace("\uff1b", " ")
    text = text.replace("\uff01", " ").replace("\uff1f", " ")
    text = text.replace("\\", "")
    text = re.sub(r"[\[\]{}|<>:;!,.?/~`@#$%^&+=]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if not text:
        text = "内容"
    if len(text) > 35:
        text = text[:35]
    return text


def _sanitize(text):
    text = text.strip()
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.replace('"', "").replace("'", "")
    text = text.replace("\u201c", "").replace("\u201d", "")
    text = text.replace("\u2018", "").replace("\u2019", "")
    text = text.replace("\\", "")
    text = text.replace("\u2014", "-")
    text = text.replace("\u2013", "-")
    text = text.replace("\u3001", " ")
    text = text.replace("\u3002", " ")
    text = text.replace("\uff0c", " ")
    text = text.replace("\uff1a", " ")
    text = text.replace("\uff1b", " ")
    text = text.replace("\uff01", " ")
    text = text.replace("\uff1f", " ")
    text = re.sub(r"[\[\]{}|<>:;!,.?/\\~`@#$%^&+=]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    if not text:
        text = "..."
    if len(text) > 50:
        text = text[:50]
    return text


def _inject_timestamp_links(text, url):
    if not url or "bilibili" not in url:
        return text

    bv_match = re.search(r"(BV[a-zA-Z0-9]+)", url)
    if not bv_match:
        return text
    bvid = bv_match.group(1)
    base_url = f"https://www.bilibili.com/video/{bvid}"

    def replace_ts(match):
        ts_str = match.group(0)
        parts = ts_str.strip("[]").split(":")
        if len(parts) == 2:
            try:
                seconds = int(parts[0]) * 60 + int(parts[1])
                return f"[{ts_str}]({base_url}?t={seconds})"
            except ValueError:
                pass
        return ts_str

    return re.sub(r"\[\d{2}:\d{2}\]", replace_ts, text)


def validate_and_fix_mindmap(code):
    """Validate mermaid mindmap code and fix common issues."""
    if not code or not code.strip():
        return _fallback_mindmap()

    lines = code.strip().split("\n")

    if not lines[0].strip().startswith("mindmap"):
        code = "mindmap\n" + code
        lines = ["mindmap"] + lines

    fixed_lines = [lines[0]]
    seen_labels = set()
    node_counter = [0]

    for line in lines[1:]:
        stripped = line.rstrip()
        if not stripped:
            continue

        indent_match = re.match(r"^(\s*)", stripped)
        indent = indent_match.group(1) if indent_match else ""
        content = stripped[len(indent):]

        if content.startswith("root("):
            content = _fix_root_node(content)
            fixed_lines.append(indent + content)
            continue

        if not content or content.isspace():
            continue

        content = _fix_mermaid_content(content)
        if not content or len(content) < 2:
            continue

        if content in seen_labels:
            node_counter[0] += 1
            content = content + str(node_counter[0])
        seen_labels.add(content)

        if len(content) > 50:
            content = content[:47] + "..."

        fixed_lines.append(indent + content)

    result = "\n".join(fixed_lines)

    if len(fixed_lines) < 3:
        return _fallback_mindmap()

    return result


def _fix_root_node(content):
    m = re.match(r'^root\((.+)\)$', content)
    if not m:
        return "root((核心主题))"
    inner = m.group(1)
    inner = inner.strip("()")
    inner = _mermaid_safe(inner)
    if not inner:
        inner = "核心主题"
    return f"root(({inner}))"


def _fix_mermaid_content(content):
    content = content.replace("(", "（").replace(")", "）")
    content = content.replace("[", "【").replace("]", "】")
    content = content.replace("{", "｛").replace("}", "｝")
    content = content.replace("<", "＜").replace(">", "＞")
    content = content.replace('"', "").replace("'", "")
    content = re.sub(r"^\s*[\[\]{}|<>:;!,.?/\\~`@#$%^&+=\-]+\s*", "", content)
    content = re.sub(r"[\[\]{}|<>:;!,.?/\\~`@#$%^&+=]+$", "", content)
    content = re.sub(r"\s+", " ", content)
    content = content.strip()
    if not content or len(content) < 2:
        return ""
    if re.match(r"^[\d\s.,:;]+$", content):
        return ""
    return content


def _fallback_mindmap():
    return (
        "mindmap\n"
        "  root((视频总结))\n"
        "    核心要点\n"
        "    详细内容\n"
        "    总结"
    )


def get_mindmap_code(summary_text):
    tree = _parse_heading_tree(summary_text)
    if not tree:
        tree = [(2, "视频内容")]

    root_heading = tree[0][1]
    child_headings = tree[1:]

    mermaid_code = _build_mermaid_mindmap(child_headings, root_heading)
    mermaid_code = validate_and_fix_mindmap(mermaid_code)
    return mermaid_code


def save_file(title, content, output_dir=None):
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)
    safe_title = safe_title[:50].strip("_. ")
    if not safe_title:
        safe_title = "summary"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_title}_{timestamp}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath
