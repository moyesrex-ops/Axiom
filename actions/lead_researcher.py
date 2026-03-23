import re
from urllib.parse import urlparse

from actions.web_search import _ddg_search, _fetch_page_content


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\d(). \-]{7,}\d)")
SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(?:linkedin\.com|twitter\.com|x\.com|facebook\.com|instagram\.com)/[^\s\"'<>]+",
    re.IGNORECASE,
)


def _clean_phone(phone: str) -> str:
    return re.sub(r"\s+", " ", phone).strip()


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _extract_lead(url: str, title: str, snippet: str, content: str) -> dict:
    emails = sorted(set(EMAIL_RE.findall(content or "")))
    phones = sorted({_clean_phone(p) for p in PHONE_RE.findall(content or "")})
    socials = sorted(set(SOCIAL_RE.findall(content or "")))
    return {
        "title": title or _domain(url),
        "url": url,
        "domain": _domain(url),
        "snippet": snippet,
        "emails": emails[:3],
        "phones": phones[:3],
        "socials": socials[:3],
    }


def _format_leads(query: str, leads: list[dict]) -> str:
    if not leads:
        return f"No public leads found for: {query}"

    lines = [f"Public lead research for: {query}"]
    for idx, lead in enumerate(leads, 1):
        lines.append(f"\n{idx}. {lead['title']}")
        lines.append(f"   URL: {lead['url']}")
        if lead["emails"]:
            lines.append(f"   Emails: {', '.join(lead['emails'])}")
        if lead["phones"]:
            lines.append(f"   Phones: {', '.join(lead['phones'])}")
        if lead["socials"]:
            lines.append(f"   Socials: {', '.join(lead['socials'])}")
        if lead["snippet"]:
            lines.append(f"   Notes: {lead['snippet'][:180]}")
    return "\n".join(lines)


def lead_researcher(parameters: dict = None, player=None, speak=None) -> str:
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    industry = str(params.get("industry", "")).strip()
    location = str(params.get("location", "")).strip()
    site = str(params.get("site", "")).strip()
    max_results = int(params.get("max_results", 5) or 5)

    if not query:
        query = " ".join(x for x in [industry, location] if x).strip()
    if not query:
        return "Please provide a lead query, industry, or location."

    search_query = query
    if site:
        search_query = f"{search_query} site:{site}"

    if speak:
        speak(f"Researching public leads for {query}.")

    results = _ddg_search(search_query, max_results=max_results * 3)
    leads = []
    seen_domains = set()

    for result in results:
        url = result.get("url", "")
        domain = _domain(url)
        if not url or not domain or domain in seen_domains:
            continue

        content = _fetch_page_content(url)
        lead = _extract_lead(
            url=url,
            title=result.get("title", ""),
            snippet=result.get("snippet", ""),
            content=content,
        )

        if lead["emails"] or lead["phones"] or lead["socials"]:
            leads.append(lead)
            seen_domains.add(domain)

        if len(leads) >= max_results:
            break

    report = _format_leads(search_query, leads)

    try:
        from memory.memory_manager import save_to_nexus
        from memory.runtime_store import log_event

        save_to_nexus(f"Lead Research: {query[:60]}", report[:2000])
        log_event("lead_research", query[:120], report[:2000], {"search_query": search_query})
    except Exception:
        pass

    return report
