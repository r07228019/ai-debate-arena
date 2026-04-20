"""PTT 八卦版 / 政黑版熱門文章抓取。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PTT_BASE = "https://www.ptt.cc"
PTT_COOKIES = {"over18": "1"}
PTT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
}


@dataclass
class PttArticle:
    board: str
    title: str
    url: str
    push_count: int   # 推文數；「爆」=100，「XX」表示負推（噓）

    def to_dict(self) -> dict:
        return {
            "board": self.board,
            "title": self.title,
            "url": self.url,
            "push_count": self.push_count,
        }


def _parse_push_count(mark: str) -> int:
    """解析 PTT 推文數標記：空字串=0, '爆'=100, '1'~'99'=對應數字, 'XN'=-N*10 取負值。"""
    mark = (mark or "").strip()
    if not mark:
        return 0
    if mark == "爆":
        return 100
    if mark.startswith("X"):
        rest = mark[1:]
        if rest.isdigit():
            return -int(rest) * 10
        if rest == "X":
            return -100
        return -10
    if mark.isdigit():
        return int(mark)
    return 0


def _fetch_page(url: str) -> str:
    resp = requests.get(url, cookies=PTT_COOKIES, headers=PTT_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _parse_index(html: str, board: str) -> tuple[list[PttArticle], str | None]:
    """解析 PTT 板面列表 HTML，回傳 (文章清單, 上一頁相對 URL or None)。"""
    soup = BeautifulSoup(html, "html.parser")
    articles: list[PttArticle] = []

    for entry in soup.select("div.r-ent"):
        title_a = entry.select_one("div.title a")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        href = title_a.get("href", "")
        if not href:
            continue
        if title.startswith(("Re:", "Fw:", "[公告]", "公告")):
            continue
        mark_el = entry.select_one("div.nrec span")
        push = _parse_push_count(mark_el.get_text(strip=True) if mark_el else "")
        articles.append(PttArticle(
            board=board,
            title=title,
            url=PTT_BASE + href,
            push_count=push,
        ))

    prev_link = None
    for a in soup.select("div.btn-group-paging a.btn"):
        if "‹ 上頁" in a.get_text():
            prev_link = a.get("href")
            break

    return articles, prev_link


def fetch_hot_articles(board: str, top_n: int = 20, min_push: int = 30, pages: int = 3) -> list[PttArticle]:
    """抓取指定看板近 `pages` 頁、推文數 >= `min_push` 的前 `top_n` 篇文章。"""
    url = f"{PTT_BASE}/bbs/{board}/index.html"
    collected: list[PttArticle] = []
    for _ in range(pages):
        try:
            html = _fetch_page(url)
        except requests.RequestException as e:
            logger.warning("抓取 %s 失敗：%s", url, e)
            break
        articles, prev_link = _parse_index(html, board)
        collected.extend(articles)
        if not prev_link:
            break
        url = PTT_BASE + prev_link

    hot = [a for a in collected if a.push_count >= min_push]
    hot.sort(key=lambda a: a.push_count, reverse=True)
    return hot[:top_n]


def fetch_article_content(url: str) -> str:
    """抓取單篇 PTT 文章的本文（去除推文、簽名、meta），失敗回傳空字串。"""
    try:
        html = _fetch_page(url)
    except requests.RequestException as e:
        logger.warning("抓取文章失敗：%s", e)
        return ""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#main-content")
    if not main:
        return ""
    for el in main.select("div.article-metaline, div.article-metaline-right, div.push, span.f2"):
        el.decompose()
    text = main.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 截斷避免過長
    return text[:3000]


def clean_title(title: str) -> str:
    """清理標題常見的分類標籤前綴。"""
    return re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
