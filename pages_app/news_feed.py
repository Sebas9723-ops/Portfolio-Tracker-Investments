"""
News Feed page — Bloomberg Terminal-style financial news aggregator.
Parses public RSS feeds using urllib + xml.etree.ElementTree (no extra deps).
"""

import datetime
import urllib.request
import xml.etree.ElementTree as ET

import streamlit as st

from app_core import info_section, render_page_title

# ── Constants ──────────────────────────────────────────────────────────────────

RSS_FEEDS = {
    "Reuters Markets":  "https://feeds.reuters.com/reuters/businessNews",
    "CNBC":             "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Yahoo Finance":    "https://finance.yahoo.com/news/rssindex",
    "Seeking Alpha":    "https://seekingalpha.com/feed.xml",
    "MarketWatch":      "https://feeds.marketwatch.com/marketwatch/topstories/",
    "Bloomberg Markets":"https://feeds.bloomberg.com/markets/news.rss",
}

_BLOOMBERG_BG = "#0b0f14"
_GOLD = "#f3a712"
_CARD_BG = "#111820"
_CARD_BORDER = "#1e2535"

_TIMEOUT_S = 8


# ── RSS parser ─────────────────────────────────────────────────────────────────

def _parse_rss_urllib(url: str, source_name: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    articles = []
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PortfolioTracker/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception:
        return articles

    # Handle both <rss> and <feed> (Atom) formats
    ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}

    # RSS 2.0 style
    for item in root.iter("item"):
        title = _tag_text(item, "title")
        link = _tag_text(item, "link") or _tag_text(item, "guid")
        pub_date = _tag_text(item, "pubDate")
        description = _tag_text(item, "description") or ""
        # Strip HTML tags from description
        description = _strip_html(description)[:280]

        parsed_dt = _parse_rss_date(pub_date)
        if title:
            articles.append({
                "source": source_name,
                "title": title.strip(),
                "link": link or "",
                "published": parsed_dt,
                "published_str": pub_date or "",
                "summary": description.strip(),
            })

    # Atom style fallback
    if not articles:
        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.iter(f"{{{atom_ns}}}entry"):
            title_el = entry.find(f"{{{atom_ns}}}title")
            link_el = entry.find(f"{{{atom_ns}}}link")
            updated_el = entry.find(f"{{{atom_ns}}}updated")
            summary_el = entry.find(f"{{{atom_ns}}}summary")
            title = title_el.text if title_el is not None else ""
            link = link_el.get("href", "") if link_el is not None else ""
            pub_date = updated_el.text if updated_el is not None else ""
            description = summary_el.text if summary_el is not None else ""
            description = _strip_html(description or "")[:280]
            parsed_dt = _parse_iso_date(pub_date)
            if title:
                articles.append({
                    "source": source_name,
                    "title": title.strip(),
                    "link": link,
                    "published": parsed_dt,
                    "published_str": pub_date,
                    "summary": description.strip(),
                })

    return articles


def _tag_text(element, tag: str) -> str:
    child = element.find(tag)
    if child is not None and child.text:
        return child.text
    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss_date(date_str: str | None) -> datetime.datetime | None:
    if not date_str:
        return None
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S +0000",
    ]:
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt)
        except Exception:
            pass
    return None


def _parse_iso_date(date_str: str | None) -> datetime.datetime | None:
    if not date_str:
        return None
    try:
        return datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Cached fetcher ────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_all_feeds(selected_sources: tuple) -> list[dict]:
    """Fetch all selected RSS feeds. Cache for 24 hours."""
    all_articles = []
    for source in selected_sources:
        url = RSS_FEEDS.get(source, "")
        if not url:
            continue
        arts = _parse_rss_urllib(url, source)
        all_articles.extend(arts)
    # Sort by date descending
    all_articles.sort(
        key=lambda a: a["published"] or datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc),
        reverse=True,
    )
    return all_articles[:50]


# ── Article card ──────────────────────────────────────────────────────────────

def _render_article_card(article: dict):
    """Render a single news article as a Bloomberg-styled card."""
    title = article.get("title", "Untitled")
    link = article.get("link", "")
    source = article.get("source", "")
    summary = article.get("summary", "")
    published = article.get("published")

    time_str = ""
    if published:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            pub_aware = published if published.tzinfo else published.replace(tzinfo=datetime.timezone.utc)
            delta = now_utc - pub_aware
            mins = int(delta.total_seconds() / 60)
            if mins < 60:
                time_str = f"{mins}m ago"
            elif mins < 1440:
                time_str = f"{mins // 60}h ago"
            else:
                time_str = pub_aware.strftime("%b %d %H:%M")
        except Exception:
            time_str = article.get("published_str", "")

    title_html = f'<a href="{link}" target="_blank" style="color:{_GOLD};text-decoration:none;font-weight:bold;font-size:14px;font-family:monospace;">{title}</a>' if link else f'<span style="color:{_GOLD};font-weight:bold;font-size:14px;font-family:monospace;">{title}</span>'

    st.markdown(
        f"""<div style='background:{_CARD_BG};border:1px solid {_CARD_BORDER};border-radius:6px;
        padding:12px 16px;margin-bottom:8px;'>
        {title_html}
        <div style='margin-top:6px;'>
            <span style='color:#888;font-size:11px;font-family:monospace;
                background:#1a1f2e;padding:2px 8px;border-radius:3px;margin-right:8px;'>
                {source}</span>
            <span style='color:#555;font-size:11px;font-family:monospace;'>{time_str}</span>
        </div>
        {f'<div style="color:#aaa;font-size:12px;font-family:sans-serif;margin-top:6px;line-height:1.4;">{summary}</div>' if summary else ''}
        </div>""",
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────────────────────

def render_news_feed_page(ctx):
    render_page_title("News Feed")

    @st.fragment(run_every=3600)
    def _live():
        st.caption(f"Last refreshed: {datetime.datetime.now().strftime('%H:%M:%S')}")

        # ── Controls ──────────────────────────────────────────────────────────────
        col_sources, col_filter = st.columns([2, 1])

        with col_sources:
            selected_sources = st.multiselect(
                "Sources",
                options=list(RSS_FEEDS.keys()),
                default=list(RSS_FEEDS.keys())[:4],
                key="news_sources",
            )

        with col_filter:
            keyword = st.text_input("Filter headlines", placeholder="e.g. Fed, inflation...",
                                    key="news_keyword")

        col_refresh, col_count = st.columns([1, 3])
        with col_refresh:
            if st.button("Refresh Feed", key="news_refresh"):
                st.cache_data.clear()
                st.rerun()
        with col_count:
            st.caption("Auto-refreshes every hour. Showing up to 50 articles.")

        if not selected_sources:
            st.info("Select at least one news source above.")
            return

        # ── Fetch ─────────────────────────────────────────────────────────────────
        with st.spinner("Loading news feeds..."):
            articles = _fetch_all_feeds(tuple(sorted(selected_sources)))

        if not articles:
            st.warning("No articles fetched. Some feeds may be temporarily unavailable.")
            return

        # ── Filter by keyword ─────────────────────────────────────────────────────
        if keyword.strip():
            kw = keyword.strip().lower()
            articles = [a for a in articles if kw in a.get("title", "").lower() or kw in a.get("summary", "").lower()]

        if not articles:
            st.info(f"No articles match the keyword '{keyword}'.")
            return

        info_section(
            "Latest Headlines",
            f"{len(articles)} articles · {datetime.datetime.now().strftime('%H:%M:%S')}",
        )

        for article in articles:
            _render_article_card(article)

    _live()
