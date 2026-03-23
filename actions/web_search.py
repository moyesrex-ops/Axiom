# actions/web_search.py
# AXIOM — Web Search & Deep Social Analysis
# Primary: Gemini google_search (yeni google.genai SDK)
# Fallback: DuckDuckGo (ddgs)
# Deep Mode: Iterative Perplexity-style multi-query synthesis
# Social: YouTube channel, Reddit, Twitter/X page analysis via playwright / BeautifulSoup

import json
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=query,
        config={"tools": [{"google_search": {}}]}
    )
    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text
    if not text.strip():
        raise ValueError("Empty response")
    return text.strip()



def _ddg_search(query: str, max_results: int = 6) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title", ""),
                "snippet": r.get("body", ""),
                "url":     r.get("href", ""),
            })
    return results

def _format_ddg(query: str, results: list) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list, aspect: str) -> str:
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e}")
        all_results = {}
        for item in items:
            try:
                all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
            except Exception:
                all_results[item] = []
        lines = [f"Comparison — {aspect.upper()}\n{'─'*40}"]
        for item in items:
            lines.append(f"\n▸ {item}")
            for r in all_results.get(item, [])[:2]:
                if r.get("snippet"):
                    lines.append(f"  • {r['snippet']}")
        return "\n".join(lines)


# ── Deep Perplexity-style Iterative Search ────────────────────────────────────

def _fetch_page_content(url: str) -> str:
    """Fetch page content using playwright (preferred) or requests+BS4 (fallback)."""
    # Try playwright first
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (compatible; AxiomBot/1.0)"})
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            content = page.inner_text("body")
            browser.close()
            return content[:8000]
    except Exception:
        pass

    # Fallback: requests + BeautifulSoup
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AxiomBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:8000]
    except Exception as e:
        return f"[PageFetch] Could not fetch {url}: {e}"


def deep_search(query: str, speak=None) -> str:
    """
    Perplexity-style iterative deep search.
    1. Breaks query into 3 focused sub-queries.
    2. Searches each sub-query and fetches page content.
    3. Feeds all scraped data into Gemini for a synthesised answer with citations.
    """
    if speak:
        speak(f"Initiating deep search for: {query}")

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        # Step 1: Break query into sub-queries
        sub_query_prompt = f"""
Break this research question into exactly 3 focused sub-queries for web search.
Return ONLY a JSON array of 3 strings. No markdown.

Question: {query}
"""
        sq_resp = model.generate_content(sub_query_prompt)
        sq_text = sq_resp.text.strip().replace("```json", "").replace("```", "").strip()
        try:
            sub_queries = json.loads(sq_text)
            if not isinstance(sub_queries, list):
                sub_queries = [query, f"{query} analysis", f"{query} strategy"]
        except Exception:
            sub_queries = [query, f"{query} analysis", f"{query} strategy"]

        print(f"[DeepSearch] 🔍 Sub-queries: {sub_queries}")

        # Step 2: Search each sub-query
        all_content = []
        for i, sq in enumerate(sub_queries[:3], 1):
            try:
                results = _ddg_search(sq, max_results=3)
                for r in results[:2]:
                    url = r.get("url", "")
                    snippet = r.get("snippet", "")
                    title = r.get("title", "")
                    if url:
                        page_text = _fetch_page_content(url)
                        all_content.append(
                            f"[Source {i}] {title}\nURL: {url}\n"
                            f"Snippet: {snippet}\n"
                            f"Page Content: {page_text[:2000]}"
                        )
                    else:
                        all_content.append(f"[Source {i}] {title}\n{snippet}")
            except Exception as e:
                print(f"[DeepSearch] Sub-query {i} failed: {e}")

        if not all_content:
            # Fall back to basic Gemini search
            return _gemini_search(query)

        # Step 3: Synthesise
        synthesis_prompt = f"""
You are a deep research analyst. Based ONLY on the scraped sources below, 
answer the following question comprehensively.

QUESTION: {query}

SOURCES:
{"─"*60}
{chr(10).join(all_content[:12])}
{"─"*60}

INSTRUCTIONS:
- Synthesise all source material into a detailed answer.
- Cite sources inline as [1], [2], [3] where relevant.
- Extract any trading strategies, patterns, or insights if present.
- Be specific, factual, and avoid generic filler.
"""
        synth_resp = model.generate_content(synthesis_prompt)
        result = synth_resp.text.strip()

        # Save to Nexus Brain
        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(f"Deep Search: {query[:60]}", result[:2000])
        except Exception:
            pass

        return f"[DEEP SEARCH] {query}\n\n{result}"

    except Exception as e:
        print(f"[DeepSearch] ❌ Failed: {e}")
        print("[DeepSearch] ⚠️ Falling back to basic Gemini search.")
        return _gemini_search(query)


# ── Social Media Analysis ─────────────────────────────────────────────────────

def _get_hostname(url: str) -> str:
    """Safely extract the hostname from a URL using urllib."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _is_reddit_url(url: str) -> bool:
    hostname = _get_hostname(url)
    return hostname == "reddit.com" or hostname.endswith(".reddit.com")


def _is_twitter_url(url: str) -> bool:
    hostname = _get_hostname(url)
    return hostname in ("twitter.com", "x.com") or \
           hostname.endswith(".twitter.com") or hostname.endswith(".x.com")


def _scrape_reddit_page(url: str) -> str:
    """Scrape a Reddit page or subreddit for posts and comments."""
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse
        # Use old Reddit for easier scraping
        parsed = urlparse(url)
        if parsed.hostname in ("www.reddit.com", "reddit.com"):
            url = url.replace(parsed.netloc, "old.reddit.com", 1)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AxiomBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        titles = [t.get_text(strip=True) for t in soup.find_all("a", class_="title")[:20]]
        return "\n".join(titles) if titles else _fetch_page_content(url)
    except Exception:
        return _fetch_page_content(url)


def _scrape_twitter_page(url: str) -> str:
    """Attempt to scrape a Twitter/X profile using playwright."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=25000)
            page.wait_for_timeout(3000)
            content = page.inner_text("body")
            browser.close()
            return content[:6000]
    except Exception as e:
        return f"[TwitterScrape] Could not scrape {url}: {e}"


def analyze_social_page(url: str, query: str, speak=None) -> str:
    """
    Analyse a social media page (YouTube channel, Reddit, Twitter/X) and
    extract trading strategies or insights relevant to the query.
    """
    if speak:
        speak(f"Analysing social page for: {query}")

    print(f"[SocialAnalyzer] 🌐 Scraping: {url}")

    if _is_reddit_url(url):
        raw_content = _scrape_reddit_page(url)
    elif _is_twitter_url(url):
        raw_content = _scrape_twitter_page(url)
    else:
        raw_content = _fetch_page_content(url)

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = f"""
You are an expert analyst. Analyse the following scraped content from {url}.

RESEARCH GOAL: {query}

SCRAPED CONTENT:
{raw_content[:5000]}

Extract:
1. Key themes, strategies, or signals discussed.
2. Any specific trading setups, entry/exit criteria, or market biases mentioned.
3. Community sentiment (bullish/bearish/neutral).
4. Notable personalities or accounts to follow based on the content.
5. Your overall synthesis and actionable takeaways.

Be specific and factual. Avoid generic filler.
"""
        response = model.generate_content(prompt)
        result = response.text.strip()

        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(f"Social Analysis: {url[:50]}", result[:2000])
        except Exception:
            pass

        return f"[SOCIAL ANALYSIS] {url}\n\n{result}"

    except Exception as e:
        return f"Social page analysis failed: {e}"


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode", "search").lower()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general")

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 Query: {query!r}  Mode: {mode}")

    # Deep Perplexity-style search
    if mode == "deep":
        return deep_search(query)

    # Social media analysis
    if mode == "social" and query:
        return analyze_social_page(query, params.get("context", query))

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] 📊 Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] ✅ Compare done.")
            return result

        print("[WebSearch] 🌐 Gemini search...")
        try:
            result = _gemini_search(query)
            print("[WebSearch] ✅ Gemini OK.")
            # Auto-save important searches to Nexus Brain
            try:
                from memory.memory_manager import save_to_nexus
                save_to_nexus(f"Web Search: {query[:60]}", result[:1000])
            except Exception:
                pass
            return result
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini failed ({e}), trying DDG...")
            results = _ddg_search(query)
            result  = _format_ddg(query, results)
            print(f"[WebSearch] ✅ DDG: {len(results)} results.")
            return result

    except Exception as e:
        print(f"[WebSearch] ❌ Failed: {e}")
        return f"Search failed, sir: {e}"
