from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from sqlalchemy.orm import Session

from app.services.model_registry import resolve_web_search_settings


def _extract_source(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc or 'web'
    except Exception:
        return 'web'


def _normalize_result_url(url: str) -> str:
    raw = (url or '').strip()
    if not raw:
        return ''
    if raw.startswith('//'):
        raw = f'https:{raw}'
    parsed = urlparse(raw)
    if parsed.netloc.endswith('duckduckgo.com') and parsed.path.startswith('/l/'):
        query = parse_qs(parsed.query)
        uddg = query.get('uddg', [])
        if uddg:
            target = unquote(uddg[0]).strip()
            if target:
                return target
    return raw


def _search_duckduckgo(query: str, max_results: int = 4) -> list[dict]:
    q = (query or '').strip()
    if not q:
        return []

    body: dict = {}
    try:
        endpoint = 'https://api.duckduckgo.com/'
        params = {
            'q': q,
            'format': 'json',
            'no_html': 1,
            'skip_disambig': 1,
        }
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            resp = client.get(endpoint, params=params)
            resp.raise_for_status()
            body = resp.json()
    except Exception:
        body = {}

    results: list[dict] = []
    abstract_url = (body.get('AbstractURL') or '').strip()
    abstract_text = (body.get('AbstractText') or '').strip()
    heading = (body.get('Heading') or '').strip()
    if abstract_url and abstract_text:
        results.append(
            {
                'title': heading or 'Web result',
                'url': abstract_url,
                'snippet': abstract_text,
                'source': _extract_source(abstract_url),
            }
        )

    def _collect_related(items: list[dict]) -> None:
        for item in items:
            topics = item.get('Topics')
            if isinstance(topics, list):
                _collect_related(topics)
                continue
            url = (item.get('FirstURL') or '').strip()
            text = (item.get('Text') or '').strip()
            if not url or not text:
                continue
            results.append(
                {
                    'title': text[:80],
                    'url': url,
                    'snippet': text,
                    'source': _extract_source(url),
                }
            )
            if len(results) >= max_results:
                return

    related = body.get('RelatedTopics') or []
    if isinstance(related, list) and len(results) < max_results:
        _collect_related(related)

    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in results:
        url = item.get('url')
        if not isinstance(url, str) or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)
        if len(deduped) >= max_results:
            break
    if deduped:
        return deduped

    # Fallback: parse lightweight HTML result page when instant API has no hits.
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'}) as client:
            resp = client.get('https://html.duckduckgo.com/html/', params={'q': q})
            resp.raise_for_status()
            html = resp.text
    except Exception:
        return []

    anchors = re.findall(
        r'<a[^>]*class="(?:result__a|result-link)"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'<a[^>]*class="(?:result__snippet|result-snippet)"[^>]*>(.*?)</a>|<div[^>]*class="(?:result__snippet|result-snippet)"[^>]*>(.*?)</div>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    fallback_results: list[dict] = []
    for idx, (url, raw_title) in enumerate(anchors[: max_results * 3]):
        title = re.sub(r'<[^>]+>', '', raw_title).strip() or f'Web result {idx + 1}'
        snippet_raw = ''
        if idx < len(snippets):
            snippet_raw = snippets[idx][0] or snippets[idx][1] or ''
        snippet = re.sub(r'<[^>]+>', '', snippet_raw).strip()
        normalized_url = _normalize_result_url(url)
        if not normalized_url:
            continue
        fallback_results.append(
            {
                'title': title,
                'url': normalized_url,
                'snippet': snippet,
                'source': _extract_source(normalized_url),
            }
        )
    deduped_fallback: list[dict] = []
    seen: set[str] = set()
    for item in fallback_results:
        url = item['url']
        if url in seen:
            continue
        seen.add(url)
        deduped_fallback.append(item)
        if len(deduped_fallback) >= max_results:
            break
    return deduped_fallback


def _search_serper(query: str, *, endpoint: str, api_key: str, max_results: int = 4) -> list[dict]:
    if not api_key:
        return []
    payload = {'q': query, 'num': max(1, min(max_results, 10)), 'hl': 'zh-cn', 'gl': 'cn'}
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    with httpx.Client(timeout=12, follow_redirects=True) as client:
        resp = client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()

    organic = body.get('organic') or []
    results: list[dict] = []
    for item in organic:
        url = (item.get('link') or '').strip()
        title = (item.get('title') or '').strip()
        snippet = (item.get('snippet') or '').strip()
        if not url:
            continue
        results.append(
            {
                'title': title or 'Web result',
                'url': url,
                'snippet': snippet,
                'source': _extract_source(url),
            }
        )
        if len(results) >= max_results:
            break
    return results


def search_web(db: Session, query: str, max_results: int = 4) -> list[dict]:
    cfg = resolve_web_search_settings(db)
    if cfg.provider == 'serper':
        if cfg.serper_api_key:
            try:
                results = _search_serper(
                    query,
                    endpoint=cfg.serper_endpoint,
                    api_key=cfg.serper_api_key,
                    max_results=max_results,
                )
                if results:
                    return results
            except Exception:
                pass
        # Fallback to DuckDuckGo when Serper key is missing or Serper has no hits.
        try:
            return _search_duckduckgo(query, max_results=max_results)
        except Exception:
            return []
    try:
        return _search_duckduckgo(query, max_results=max_results)
    except Exception:
        return []
