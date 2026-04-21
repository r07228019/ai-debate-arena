"""將辯論 JSON 紀錄渲染為靜態 HTML 網站。"""
from __future__ import annotations

import html as html_lib
import json
import logging
from datetime import datetime
from pathlib import Path

import markdown as md_lib

logger = logging.getLogger(__name__)
_PROJECT_DIR = Path(__file__).parent


def _giscus_script(giscus_cfg: dict) -> str:
    if not giscus_cfg.get("enabled"):
        return ""
    return f"""
<script src="https://giscus.app/client.js"
    data-repo="{giscus_cfg['repo']}"
    data-repo-id="{giscus_cfg['repo_id']}"
    data-category="{giscus_cfg['category']}"
    data-category-id="{giscus_cfg['category_id']}"
    data-mapping="{giscus_cfg.get('mapping', 'pathname')}"
    data-strict="0"
    data-reactions-enabled="1"
    data-emit-metadata="0"
    data-input-position="bottom"
    data-theme="{giscus_cfg.get('theme', 'dark_dimmed')}"
    data-lang="zh-TW"
    crossorigin="anonymous"
    async>
</script>
"""


def _render_page(title: str, body: str, sidebar_items: list[dict], active_date: str,
                 base_path: str, giscus_cfg: dict) -> str:
    sidebar_html_parts = []
    for i, item in enumerate(sidebar_items):
        active = ' aria-current="page"' if item["date"] == active_date else ""
        href = (
            f"{base_path}index.html" if item["date"] == sidebar_items[0]["date"]
            else f"{base_path}debates/{item['filename']}"
        )
        delay = f"{i * 0.05 + 0.05:.2f}s"
        topic_escaped = html_lib.escape(item["topic"])
        sidebar_html_parts.append(
            f'        <li style="animation-delay:{delay}"><a href="{href}"{active}>'
            f'<i class="ph ph-chat-teardrop-text"></i> {item["date"]}'
            f'<span class="entry-topic">{topic_escaped}</span></a></li>'
        )
    sidebar_html = "\n".join(sidebar_html_parts)

    template = (_PROJECT_DIR / "template.html").read_text(encoding="utf-8")
    return (
        template
        .replace("%%TITLE%%", html_lib.escape(title))
        .replace("%%SIDEBAR%%", sidebar_html)
        .replace("%%BODY_HTML%%", body)
    )


def _format_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year} 年 {d.month} 月 {d.day} 日"
    except ValueError:
        return date_str


def _paragraphs_to_html(text: str) -> str:
    """把純文字段落（以換行分隔）轉成 <p>...</p>。保留文字換行。"""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{html_lib.escape(p).replace(chr(10), '<br>')}</p>" for p in parts)


def _render_debate_body(debate: dict, date_str: str, giscus_cfg: dict) -> str:
    topic = debate["topic"]
    personas = debate["personas"]
    history = debate["history"]
    rounds = debate["rounds"]

    persona_color = {p["id"]: p["color"] for p in personas}

    # Hero
    parts = ['<div class="hero">']
    parts.append('<div class="hero-label"><i class="ph-fill ph-flame"></i> 今日辯題</div>')
    parts.append(f'<div class="hero-date">{html_lib.escape(_format_date(date_str))}</div>')
    parts.append(f'<div class="hero-topic">{html_lib.escape(topic["debate_topic"])}</div>')
    if topic.get("topic_description"):
        parts.append(f'<div class="hero-description">{html_lib.escape(topic["topic_description"])}</div>')
    parts.append('</div>')

    # Source
    src = topic.get("source") or {}
    if src.get("url"):
        parts.append(
            '<div class="source-box">'
            f'<span class="tag">議題來源</span>'
            f'<span>PTT / {html_lib.escape(src.get("board", ""))}</span>'
            f'<span>·</span>'
            f'<a href="{html_lib.escape(src["url"])}" target="_blank" rel="noopener">'
            f'{html_lib.escape(src.get("title", ""))}</a>'
            f'<span style="color:var(--text-muted)">·</span>'
            f'<span>推 {src.get("push_count", 0)}</span>'
            '</div>'
        )

    # Rounds
    for r in range(1, rounds + 1):
        parts.append(
            f'<div class="round-heading">'
            f'<span class="round-num">{r}</span>'
            f'<span>第 {r} 輪 · '
            + ('亮出立場' if r == 1 else '回應與深化')
            + '</span></div>'
        )
        for h in history:
            if h["round"] != r:
                continue
            color = persona_color.get(h["persona_id"], "#ef4444")
            parts.append(
                f'<div class="msg" style="--accent-color:{color}">'
                f'<div class="msg-avatar" style="border-color:{color};color:{color}">{h["persona_emoji"]}</div>'
                f'<div class="msg-body">'
                f'<div class="msg-header">'
                f'<span class="msg-name" style="color:{color}">{html_lib.escape(h["persona_name"])}</span>'
                f'</div>'
                f'<div class="msg-text">{html_lib.escape(h["text"])}</div>'
                f'</div>'
                f'</div>'
            )

    # Judge
    judge_html = md_lib.markdown(debate["judge"], extensions=["tables", "fenced_code"])
    parts.append(
        '<div class="judge">'
        '<div class="judge-tag"><i class="ph-fill ph-gavel"></i> 裁判評論</div>'
        f'{judge_html}'
        '</div>'
    )

    # Comments
    giscus_content = (
        _giscus_script(giscus_cfg)
        if giscus_cfg.get("enabled")
        else '<div class="comments-placeholder">（尚未啟用留言功能，請於 config.yaml 設定 giscus）</div>'
    )
    parts.append(
        '<div class="comments">'
        '<div class="comments-heading"><i class="ph ph-chats"></i> 你怎麼看？</div>'
        f'<div id="giscus-container">{giscus_content}</div>'
        '</div>'
    )

    return "\n".join(parts)


def _render_index_body(sidebar_items: list[dict]) -> str:
    parts = [
        '<div class="index-hero">',
        '<h1>AI 多人格辯論擂台</h1>',
        '<p>每天從 PTT 熱門話題中挑一題，抽三個 AI 人格輪流辯論，最後交給裁判評論。你可以在下方留言加入討論。</p>',
        '</div>',
    ]
    parts.append('<div class="debate-list">')
    for item in sidebar_items:
        href = "index.html" if item["date"] == sidebar_items[0]["date"] else f"debates/{item['filename']}"
        emojis = "".join(item["persona_emojis"])
        parts.append(
            f'<a class="debate-card" href="{href}">'
            f'<div class="debate-card-date">{item["date"]}</div>'
            f'<div class="debate-card-topic">{html_lib.escape(item["topic"])}</div>'
            f'<div class="debate-card-meta">'
            f'<span class="debate-card-personas">{emojis}</span>'
            f'<span>·</span>'
            f'<span>PTT / {html_lib.escape(item.get("board", ""))}</span>'
            f'</div>'
            f'</a>'
        )
    parts.append('</div>')
    return "\n".join(parts)


def generate_website(data_dir: Path, docs_dir: Path, giscus_cfg: dict, keep_n: int = 30) -> int:
    """掃描 data_dir 下的 JSON 紀錄，生成靜態網站到 docs_dir。回傳渲染數量。"""
    json_files = sorted(data_dir.glob("debate_*.json"), reverse=True)[:keep_n]
    if not json_files:
        print("      無任何辯論紀錄可渲染")
        return 0

    debates_dir = docs_dir / "debates"
    debates_dir.mkdir(parents=True, exist_ok=True)

    items = []
    debates = []
    for p in json_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("無法解析 %s：%s", p, e)
            continue
        date_str = p.stem.replace("debate_", "")
        items.append({
            "date": date_str,
            "topic": data["topic"]["debate_topic"],
            "filename": f"{p.stem}.html",
            "persona_emojis": [x["emoji"] for x in data["personas"]],
            "board": (data["topic"].get("source") or {}).get("board", ""),
        })
        debates.append((date_str, data))

    # 首頁 = 最新一篇辯論 + 側欄導覽
    latest_date, latest_data = debates[0]
    latest_body = _render_debate_body(latest_data, latest_date, giscus_cfg)
    (docs_dir / "index.html").write_text(
        _render_page(
            f"AI Debate Arena — {latest_data['topic']['debate_topic']}",
            latest_body, items, latest_date, base_path="", giscus_cfg=giscus_cfg,
        ),
        encoding="utf-8",
    )

    # 獨立頁面
    for date_str, data in debates:
        body = _render_debate_body(data, date_str, giscus_cfg)
        filename = f"debate_{date_str}.html"
        (debates_dir / filename).write_text(
            _render_page(
                f"AI Debate Arena — {data['topic']['debate_topic']}",
                body, items, date_str, base_path="../", giscus_cfg=giscus_cfg,
            ),
            encoding="utf-8",
        )

    # 清除超過 keep_n 的舊檔
    for old in sorted(debates_dir.glob("debate_*.html"), reverse=True)[keep_n:]:
        old.unlink()

    # 另外產一個 archive.html 當「全部列表」（可選，先做簡單版）
    archive_body = _render_index_body(items)
    (docs_dir / "archive.html").write_text(
        _render_page(
            "AI Debate Arena — 歷史辯論",
            archive_body, items, "archive", base_path="", giscus_cfg={"enabled": False},
        ),
        encoding="utf-8",
    )

    return len(debates)
