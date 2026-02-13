from types import SimpleNamespace

from app.services import web_search


def test_search_web_serper_without_key_falls_back_to_duckduckgo(monkeypatch):
    monkeypatch.setattr(
        web_search,
        'resolve_web_search_settings',
        lambda db: SimpleNamespace(
            enabled=True,
            provider='serper',
            serper_endpoint='https://google.serper.dev/search',
            serper_api_key='',
        ),
    )
    monkeypatch.setattr(
        web_search,
        '_search_duckduckgo',
        lambda query, max_results=4: [{'title': 'ddg', 'url': 'https://example.com', 'snippet': 'ok', 'source': 'example.com'}],
    )

    rows = web_search.search_web(db=None, query='bonjour', max_results=4)
    assert len(rows) == 1
    assert rows[0]['title'] == 'ddg'


def test_search_web_does_not_gate_by_enabled_flag(monkeypatch):
    monkeypatch.setattr(
        web_search,
        'resolve_web_search_settings',
        lambda db: SimpleNamespace(
            enabled=False,
            provider='duckduckgo',
            serper_endpoint='',
            serper_api_key='',
        ),
    )
    monkeypatch.setattr(
        web_search,
        '_search_duckduckgo',
        lambda query, max_results=4: [{'title': 'ddg', 'url': 'https://example.com', 'snippet': 'ok', 'source': 'example.com'}],
    )

    rows = web_search.search_web(db=None, query='search this', max_results=4)
    assert len(rows) == 1


def test_normalize_result_url_decodes_duckduckgo_redirect():
    url = (
        'https://duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FBeijing_Foreign_Studies_University'
    )
    normalized = web_search._normalize_result_url(url)
    assert normalized == 'https://en.wikipedia.org/wiki/Beijing_Foreign_Studies_University'
