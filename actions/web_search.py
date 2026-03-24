# actions/web_search.py
# AXIOM — Web Search & Deep Social Analysis
# Primary: Gemini google_search (yeni google.genai SDK)
# Fallback: DuckDuckGo (ddgs)
# Deep Mode: Iterative Perplexity-style multi-query synthesis
# Social: YouTube channel, Reddit, Twitter/X page analysis via playwright / BeautifulSoup

import json
import sys
from pathlib import Path

import requests

from core.runtime_config import load_runtime_config


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _runtime_models() -> dict:
    runtime = load_runtime_config()
    return runtime.get("text_models", {}) or {}


def _research_config() -> dict:
    runtime = load_runtime_config()
    return runtime.get("research", {}) or {}


def _reasoning_model_name() -> str:
    models = _runtime_models()
    return (
        str(models.get("reasoning") or "").strip()
        or str(models.get("default") or "").strip()
        or "gemini-2.5-flash"
    )


def _fast_model_name() -> str:
    models = _runtime_models()
    return (
        str(models.get("fast") or "").strip()
        or str(models.get("default") or "").strip()
        or "gemini-2.5-flash-lite"
    )


def _gemini_search(query: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model=_fast_model_name(),
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


def _normalized_vane_url() -> str:
    return str(_research_config().get("vane_url", "") or "").strip().rstrip("/")


def _match_provider_model(providers: list, provider_hint: str, model_hint: str, model_field: str) -> dict | None:
    provider_hint = str(provider_hint or "").strip().lower()
    model_hint = str(model_hint or "").strip().lower()

    provider_candidates = []
    for provider in providers:
        models = provider.get(model_field, []) or []
        if not models:
            continue
        provider_id = str(provider.get("id", "") or "").strip().lower()
        provider_name = str(provider.get("name", "") or "").strip().lower()
        if provider_hint and provider_hint not in {provider_id, provider_name}:
            continue
        provider_candidates.append(provider)

    if not provider_candidates:
        provider_candidates = [provider for provider in providers if provider.get(model_field)]

    for provider in provider_candidates:
        for model in provider.get(model_field, []) or []:
            key = str(model.get("key", "") or "").strip().lower()
            name = str(model.get("name", "") or "").strip().lower()
            if model_hint and model_hint not in {key, name}:
                continue
            return {
                "providerId": provider.get("id"),
                "key": model.get("key"),
                "providerName": provider.get("name", ""),
            }

    if provider_candidates:
        provider = provider_candidates[0]
        models = provider.get(model_field, []) or []
        if models:
            return {
                "providerId": provider.get("id"),
                "key": models[0].get("key"),
                "providerName": provider.get("name", ""),
            }
    return None


def _format_citations(sources: list, limit: int = 6) -> str:
    lines = []
    for index, source in enumerate((sources or [])[:limit], 1):
        metadata = source.get("metadata", {}) or {}
        title = str(metadata.get("title", "") or "").strip() or f"Source {index}"
        url = str(metadata.get("url", "") or "").strip()
        if url:
            lines.append(f"[{index}] {title} - {url}")
        else:
            lines.append(f"[{index}] {title}")
    return "\n".join(lines)


def _vane_search(
    query: str,
    optimization_mode: str = "balanced",
    sources: list[str] | None = None,
    system_instructions: str = "",
    history: list | None = None,
) -> str:
    base_url = _normalized_vane_url()
    if not base_url:
        raise ValueError("Vane URL is not configured.")

    research_cfg = _research_config()
    providers_response = requests.get(f"{base_url}/api/providers", timeout=20)
    providers_response.raise_for_status()
    providers = (providers_response.json() or {}).get("providers", []) or []
    if not providers:
        raise ValueError("Vane did not return any active providers/models.")

    chat_model = _match_provider_model(
        providers,
        research_cfg.get("vane_chat_provider", ""),
        research_cfg.get("vane_chat_model", ""),
        "chatModels",
    )
    embedding_model = _match_provider_model(
        providers,
        research_cfg.get("vane_embedding_provider", ""),
        research_cfg.get("vane_embedding_model", ""),
        "embeddingModels",
    )
    if not chat_model or not embedding_model:
        raise ValueError("Could not resolve Vane chat or embedding model configuration.")

    payload = {
        "chatModel": {
            "providerId": chat_model["providerId"],
            "key": chat_model["key"],
        },
        "embeddingModel": {
            "providerId": embedding_model["providerId"],
            "key": embedding_model["key"],
        },
        "optimizationMode": optimization_mode,
        "sources": list(sources or ["web"]),
        "query": query,
        "history": history or [],
        "systemInstructions": (
            system_instructions
            or "Cite concrete sources, avoid filler, and be explicit about uncertainty."
        ),
        "stream": False,
    }

    response = requests.post(f"{base_url}/api/search", json=payload, timeout=90)
    response.raise_for_status()
    data = response.json() or {}

    message = str(data.get("message", "") or "").strip()
    source_rows = data.get("sources", []) or []
    if not message:
        raise ValueError("Vane returned an empty answer.")

    citations = _format_citations(source_rows)
    result = f"[VANE SEARCH] {query}\n\n{message}"
    if citations:
        result += f"\n\nSources:\n{citations}"

    try:
        from memory.memory_manager import save_to_nexus
        from memory.runtime_store import log_event

        save_to_nexus(
            f"Vane Search: {query[:60]}",
            result[:6000],
            kind="research",
            source=base_url,
            metadata={
                "optimization_mode": optimization_mode,
                "sources": list(sources or ["web"]),
                "provider": chat_model.get("providerName", ""),
                "model": chat_model.get("key", ""),
            },
        )
        log_event(
            "research",
            "vane_search",
            query[:300],
            metadata={
                "source_count": len(source_rows),
                "base_url": base_url,
                "optimization_mode": optimization_mode,
            },
        )
    except Exception:
        pass

    return result



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


def _query_needs_repo_hunt(query: str) -> bool:
    normalized = str(query or "").lower()
    hints = (
        "github",
        "gitlab",
        "open source",
        "opensource",
        "repo",
        "repository",
        "clone",
        "tool",
        "framework",
        "agent",
        "memory system",
        "search engine",
    )
    return any(hint in normalized for hint in hints)


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


def deep_search(
    query: str,
    speak=None,
    system_instructions: str = "",
    sources: list[str] | None = None,
) -> str:
    """
    Perplexity-style iterative deep search.
    1. Breaks query into 3 focused sub-queries.
    2. Searches each sub-query and fetches page content.
    3. Feeds all scraped data into Gemini for a synthesised answer with citations.
    """
    if speak:
        speak(f"Initiating deep search for: {query}")

    research_cfg = _research_config()
    research_backend = str(research_cfg.get("backend", "axiom") or "axiom").strip().lower()
    if research_backend in ("vane", "auto") and _normalized_vane_url():
        try:
            return _vane_search(
                query,
                optimization_mode="quality",
                sources=sources or ["web", "discussions", "academic"],
                system_instructions=(
                    system_instructions
                    or "Perform a rigorous multi-source research pass. Prefer factual depth, explicit uncertainty, and citations."
                ),
            )
        except Exception as e:
            print(f"[DeepSearch] ⚠️ Vane backend failed: {e}")

    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel(_reasoning_model_name())

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

        if _query_needs_repo_hunt(query):
            repo_query = f"site:github.com {query}"
            if not any("github.com" in str(item).lower() for item in sub_queries):
                if len(sub_queries) >= 3:
                    sub_queries[-1] = repo_query
                else:
                    sub_queries.append(repo_query)

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
- {system_instructions or "Call out uncertainty clearly if the evidence is weak or conflicting."}
"""
        synth_resp = model.generate_content(synthesis_prompt)
        result = synth_resp.text.strip()

        # Save to Nexus Brain
        try:
            from memory.memory_manager import save_to_nexus
            save_to_nexus(
                f"Deep Search: {query[:60]}",
                result[:3000],
                kind="research",
                source="axiom.deep_search",
                metadata={"sources": len(all_content[:12])},
            )
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
    sources = params.get("sources", [])
    if not isinstance(sources, list):
        sources = []

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 Query: {query!r}  Mode: {mode}")

    # Deep Perplexity-style search
    if mode == "deep":
        return deep_search(
            query,
            system_instructions=str(params.get("context", "") or "").strip(),
            sources=sources,
        )

    # Social media analysis
    if mode == "social" and query:
        return analyze_social_page(query, params.get("context", query))

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] 📊 Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] ✅ Compare done.")
            return result

        research_cfg = _research_config()
        research_backend = str(research_cfg.get("backend", "axiom") or "axiom").strip().lower()
        if mode == "search" and query and research_backend in ("vane", "auto") and _normalized_vane_url():
            try:
                return _vane_search(
                    query,
                    optimization_mode="balanced",
                    sources=sources or ["web"],
                    system_instructions=str(params.get("context", "") or "").strip(),
                )
            except Exception as e:
                print(f"[WebSearch] ⚠️ Vane backend failed ({e}), falling back to local search.")

        print("[WebSearch] 🌐 Gemini search...")
        try:
            result = _gemini_search(query)
            print("[WebSearch] ✅ Gemini OK.")
            # Auto-save important searches to Nexus Brain
            try:
                from memory.memory_manager import save_to_nexus
                save_to_nexus(
                    f"Web Search: {query[:60]}",
                    result[:1500],
                    kind="research",
                    source="axiom.google_search",
                )
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
