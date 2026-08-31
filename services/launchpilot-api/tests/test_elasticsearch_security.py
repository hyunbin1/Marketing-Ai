from __future__ import annotations

import pytest

from launchpilot.bootstrap.config import Settings
from launchpilot.knowledge.elasticsearch import ElasticsearchCampaignDocumentSearch


def test_remote_elasticsearch_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICSEARCH_URL", "https://es.internal.example:9200")
    monkeypatch.delenv("ELASTICSEARCH_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ELASTICSEARCH_API_KEY"):
        Settings.from_environment()


def test_remote_elasticsearch_with_api_key_is_accepted(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICSEARCH_URL", "https://es.internal.example:9200/")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "encoded-key")

    settings = Settings.from_environment()

    assert settings.elasticsearch_api_key == "encoded-key"
    assert settings.elasticsearch_url == "https://es.internal.example:9200"
    assert settings.elasticsearch_verify_certs is True


def test_local_elasticsearch_allows_no_auth(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")
    monkeypatch.delenv("ELASTICSEARCH_API_KEY", raising=False)

    settings = Settings.from_environment()

    assert settings.elasticsearch_api_key is None


def test_verify_certs_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICSEARCH_URL", "https://es.internal.example:9200")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "encoded-key")
    monkeypatch.setenv("ELASTICSEARCH_VERIFY_CERTS", "false")

    settings = Settings.from_environment()

    assert settings.elasticsearch_verify_certs is False


def test_search_client_receives_api_key_and_tls_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeElasticsearch:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured["url"] = url
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "launchpilot.knowledge.elasticsearch.Elasticsearch", FakeElasticsearch
    )

    ElasticsearchCampaignDocumentSearch(
        "https://es.internal.example:9200",
        "launchpilot-documents-v1",
        api_key="encoded-key",
        ca_certs="/etc/ssl/es-ca.pem",
        verify_certs=False,
    )

    kwargs = captured["kwargs"]
    assert kwargs["api_key"] == "encoded-key"
    assert kwargs["ca_certs"] == "/etc/ssl/es-ca.pem"
    assert kwargs["verify_certs"] is False


def test_search_client_omits_tls_options_for_plain_http(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeElasticsearch:
        def __init__(self, url: str, **kwargs: object) -> None:
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "launchpilot.knowledge.elasticsearch.Elasticsearch", FakeElasticsearch
    )

    ElasticsearchCampaignDocumentSearch("http://127.0.0.1:9200", "idx")

    kwargs = captured["kwargs"]
    assert "verify_certs" not in kwargs
    assert "ca_certs" not in kwargs
    assert "api_key" not in kwargs
