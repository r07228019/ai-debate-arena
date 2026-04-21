"""彙整 PTT 熱門文章、請 Claude 挑出當日辯論題目。"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic

from .claude_client import call_with_retry
from .ptt_scraper import PttArticle, clean_title, fetch_article_content, fetch_hot_articles

logger = logging.getLogger(__name__)


def collect_candidates(
    boards: list[str], top_n_per_board: int, min_push_count: int, pages_per_board: int = 3,
) -> list[PttArticle]:
    """從多個看板抓取熱門文章，合併為候選清單。"""
    candidates: list[PttArticle] = []
    for board in boards:
        print(f"      抓取 PTT/{board} 熱門文章 ...")
        articles = fetch_hot_articles(
            board, top_n=top_n_per_board, min_push=min_push_count, pages=pages_per_board,
        )
        print(f"        → {len(articles)} 篇符合條件")
        candidates.extend(articles)
    candidates.sort(key=lambda a: a.push_count, reverse=True)
    return candidates


def pick_topic(
    candidates: list[PttArticle],
    aws_region: str,
    bedrock_model: str,
    max_tokens: int,
    system_prompt: str,
) -> dict | None:
    """請 Claude 從候選中挑出最適合的辯論題目。回傳 None 表示沒有合適題目。"""
    if not candidates:
        return None

    payload = [
        {"index": i, "title": clean_title(a.title), "board": a.board, "push_count": a.push_count}
        for i, a in enumerate(candidates)
    ]
    user_prompt = (
        "以下是今日從 PTT 八卦版與政黑版抓到的熱門文章，請依系統指示挑出一題最適合辯論的主題。\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )

    client = anthropic.AnthropicBedrock(aws_region=aws_region)
    text, t_in, t_out = call_with_retry(
        client, model=bedrock_model, max_tokens=max_tokens,
        system=system_prompt, user=user_prompt, stream=False,
    )
    print(f"        Token 用量：input={t_in}, output={t_out}")

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.error("挑題回傳非合法 JSON：%s", text[:300])
        return None

    idx = result.get("chosen_index", -1)
    if idx < 0 or idx >= len(candidates):
        logger.info("Claude 判定無合適題目：%s", result.get("reason", ""))
        return None

    chosen = candidates[idx]
    print(f"      抓取原文內容 ...")
    content = fetch_article_content(chosen.url)

    return {
        "debate_topic": result["debate_topic"],
        "topic_description": result.get("topic_description", ""),
        "reason": result.get("reason", ""),
        "source": chosen.to_dict(),
        "source_content": content,
    }


def load_topic_picker_prompt(prompts_dir: Path) -> str:
    return (prompts_dir / "topic_picker.md").read_text(encoding="utf-8").strip()
