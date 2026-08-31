from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Auto-load .env from services/launchpilot-api/.env
_env_path = Path(__file__).parents[3] / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v



def _local_mock_base_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError(
            "PLATFORM_MOCK_BASE_URL must be an origin on localhost. "
            "Remote mock endpoints could receive OAuth tokens."
        )
    return normalized


def _require_elasticsearch_security(url: str, api_key: str | None) -> None:
    """Refuse to connect to a non-local Elasticsearch without authentication.

    Local development runs Elasticsearch with security disabled (see compose.yaml),
    but a remote cluster reachable over the network must present an API key, or the
    document index — which holds tenant campaign text — would be world-readable.
    """
    host = urlparse(url).hostname
    if host in {"127.0.0.1", "localhost", "::1"}:
        return
    if not api_key:
        raise RuntimeError(
            "ELASTICSEARCH_URL points to a non-local cluster but ELASTICSEARCH_API_KEY "
            "is not set. Refusing to connect to an unauthenticated Elasticsearch; set "
            "ELASTICSEARCH_API_KEY."
        )


@dataclass(frozen=True, slots=True)
class Settings:
    telemetry_enabled: bool
    otel_service_name: str
    otel_exporter_endpoint: str | None
    database_url: str
    app_database_url: str | None
    elasticsearch_url: str
    elasticsearch_index: str
    elasticsearch_api_key: str | None
    elasticsearch_ca_certs: str | None
    elasticsearch_verify_certs: bool
    google_api_key: str | None
    google_genai_use_vertexai: bool
    google_cloud_project: str | None
    google_cloud_location: str
    llm_model: str
    public_base_url: str
    google_client_id: str | None
    google_client_secret: str | None
    token_encryption_key: str | None
    app_session_secret: str | None
    cookie_secure: bool
    google_ads_developer_token: str | None
    google_ads_api_version: str
    meta_graph_api_version: str
    meta_app_id: str | None
    meta_app_secret: str | None
    meta_primary_conversion_action: str | None
    platform_mock_base_url: str | None

    @classmethod
    def from_environment(cls) -> Settings:
        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip(
            "/"
        )
        cookie_secure_value = os.getenv("COOKIE_SECURE")
        cookie_secure = (
            cookie_secure_value.lower() in {"1", "true", "yes"}
            if cookie_secure_value is not None
            else public_base_url.startswith("https://")
        )
        use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        telemetry_enabled = os.getenv("TELEMETRY_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
        }
        elasticsearch_url = os.getenv(
            "ELASTICSEARCH_URL", "http://127.0.0.1:9200"
        ).rstrip("/")
        elasticsearch_api_key = os.getenv("ELASTICSEARCH_API_KEY")
        _require_elasticsearch_security(elasticsearch_url, elasticsearch_api_key)
        elasticsearch_verify_value = os.getenv("ELASTICSEARCH_VERIFY_CERTS")
        elasticsearch_verify_certs = (
            elasticsearch_verify_value.lower() in {"1", "true", "yes"}
            if elasticsearch_verify_value is not None
            else True
        )
        return cls(
            telemetry_enabled=telemetry_enabled,
            otel_service_name=os.getenv("OTEL_SERVICE_NAME", "launchpilot-api"),
            otel_exporter_endpoint=(
                os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            ),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://launchpilot:launchpilot-local@127.0.0.1:5432/launchpilot",
            ),
            app_database_url=os.getenv("APP_DATABASE_URL"),
            elasticsearch_url=elasticsearch_url,
            elasticsearch_index=os.getenv(
                "ELASTICSEARCH_INDEX", "launchpilot-documents-v1"
            ),
            elasticsearch_api_key=elasticsearch_api_key,
            elasticsearch_ca_certs=os.getenv("ELASTICSEARCH_CA_CERTS"),
            elasticsearch_verify_certs=elasticsearch_verify_certs,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            google_genai_use_vertexai=use_vertexai,
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            llm_model=os.getenv("LLM_MODEL", "gemini-3.6-flash"),
            public_base_url=public_base_url,
            google_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
            google_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
            token_encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
            app_session_secret=os.getenv("APP_SESSION_SECRET"),
            cookie_secure=cookie_secure,
            google_ads_developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
            google_ads_api_version=os.getenv("GOOGLE_ADS_API_VERSION", "v25"),
            meta_graph_api_version=os.getenv("META_GRAPH_API_VERSION", "v24.0"),
            meta_app_id=os.getenv("META_APP_ID"),
            meta_app_secret=os.getenv("META_APP_SECRET"),
            meta_primary_conversion_action=os.getenv("META_PRIMARY_CONVERSION_ACTION"),
            platform_mock_base_url=_local_mock_base_url(
                os.getenv("PLATFORM_MOCK_BASE_URL")
            ),
        )

    def require_telemetry_endpoint(self) -> str:
        if not self.otel_exporter_endpoint:
            raise RuntimeError(
                "Telemetry is enabled. Set OTEL_EXPORTER_OTLP_ENDPOINT or "
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT."
            )
        return self.otel_exporter_endpoint

    def require_google_oauth(self) -> None:
        if not self.google_client_id or not self.google_client_secret:
            raise RuntimeError(
                "Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET."
            )

    def require_google_ai(self) -> None:
        if self.google_genai_use_vertexai and not self.google_cloud_project:
            raise RuntimeError(
                "Vertex AI is enabled. Set GOOGLE_CLOUD_PROJECT and configure ADC."
            )
        if not self.google_genai_use_vertexai and not self.google_api_key:
            raise RuntimeError(
                "Gemini is not configured. Set GOOGLE_API_KEY, or enable Vertex AI."
            )

    def require_token_key(self) -> str:
        if not self.token_encryption_key:
            raise RuntimeError(
                "Token encryption is not configured. Set TOKEN_ENCRYPTION_KEY."
            )
        return self.token_encryption_key

    def require_session_secret(self) -> str:
        if not self.app_session_secret or len(self.app_session_secret) < 32:
            raise RuntimeError(
                "Session signing is not configured. Set APP_SESSION_SECRET to at least 32 characters."
            )
        return self.app_session_secret

    def require_google_ads(self) -> str:
        if not self.google_ads_developer_token:
            raise RuntimeError(
                "Google Ads is not configured. Set GOOGLE_ADS_DEVELOPER_TOKEN."
            )
        return self.google_ads_developer_token

    def require_meta_oauth(self) -> tuple[str, str]:
        if not self.meta_app_id or not self.meta_app_secret:
            raise RuntimeError(
                "Meta OAuth is not configured. Set META_APP_ID and META_APP_SECRET."
            )
        return self.meta_app_id, self.meta_app_secret
