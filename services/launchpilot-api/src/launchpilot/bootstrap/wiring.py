from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from launchpilot.analysis.agent import CampaignAgentFactory
from launchpilot.analysis.use_case import CampaignAnalysisService
from launchpilot.bootstrap.config import Settings
from launchpilot.campaigns.application.access import CampaignAccessService
from launchpilot.campaigns.postgres import (
    PostgresCampaignRepository,
    PostgresConversationRepository,
)
from launchpilot.campaigns.service import CampaignService, ConversationService
from launchpilot.identity.access_tokens import PlatformAccessTokenProvider
from launchpilot.identity.oauth.google import GoogleOAuthClient
from launchpilot.identity.oauth.meta import MetaOAuthClient
from launchpilot.identity.postgres import PostgresIdentityStore
from launchpilot.identity.security import (
    BrowserStateManager,
    SessionManager,
    SignedTokenCodec,
)
from launchpilot.identity.workspace_access import IdentityWorkspaceAccessReader
from launchpilot.knowledge.elasticsearch import (
    ElasticsearchCampaignDocumentSearch,
)
from launchpilot.knowledge.postgres import (
    PostgresCampaignDocumentRepository,
)
from launchpilot.knowledge.service import TextRetrievalService
from launchpilot.observability.retrieval import OpenTelemetryRetrievalObserver
from launchpilot.performance.catalog import AdvertisingCatalogService
from launchpilot.performance.factory import AdsConnectorFactory
from launchpilot.performance.ingestion import AdsIngestionSourcePlanner
from launchpilot.performance.observation_postgres import PostgresObservationRepository
from launchpilot.performance.observation_service import ObservationService
from launchpilot.performance.postgres import (
    PostgresStructuredRetrievalRepository,
)
from launchpilot.performance.retrieval import StructuredRetrievalService
from launchpilot.persistence.postgres import PostgresDatabase


@lru_cache
def repository_store() -> PostgresDatabase:
    """Admin store (superuser). Runs migrations, seeding, and auth/scope lookups;
    bypasses RLS. Used for everything that must read across tenants or resolve which
    tenant a request belongs to before the tenant context is known."""
    return PostgresDatabase(settings().database_url)


@lru_cache
def app_repository_store() -> PostgresDatabase:
    """Runtime store for tenant domain data. Connects as the non-superuser app_user
    (APP_DATABASE_URL) so RLS applies, and stamps app.workspace_id from the request
    context onto each connection. Falls back to the admin URL when APP_DATABASE_URL
    is unset, in which case enforcement stays inert (superuser bypasses RLS)."""
    config = settings()
    repository_store()  # ensure migrations have run under the admin store
    return PostgresDatabase(
        config.app_database_url or config.database_url,
        set_tenant_guc=True,
        run_migrations=False,
    )


def campaign_service() -> CampaignService:
    return CampaignService(PostgresCampaignRepository(repository_store()))


def conversation_service() -> ConversationService:
    database = repository_store()
    return ConversationService(
        PostgresCampaignRepository(database), PostgresConversationRepository(database)
    )


def observation_service() -> ObservationService:
    database = repository_store()
    return ObservationService(
        CampaignService(PostgresCampaignRepository(database)),
        PostgresObservationRepository(database),
    )


def structured_retrieval_service() -> StructuredRetrievalService:
    # Tenant domain reads — go through the RLS-enforced app store.
    return StructuredRetrievalService(
        PostgresStructuredRetrievalRepository(app_repository_store())
    )


def text_retrieval_service() -> TextRetrievalService:
    config = settings()
    return TextRetrievalService(
        # Tenant domain reads/writes — go through the RLS-enforced app store.
        PostgresCampaignDocumentRepository(app_repository_store()),
        ElasticsearchCampaignDocumentSearch(
            config.elasticsearch_url,
            config.elasticsearch_index,
            api_key=config.elasticsearch_api_key,
            ca_certs=config.elasticsearch_ca_certs,
            verify_certs=config.elasticsearch_verify_certs,
        ),
        observer=OpenTelemetryRetrievalObserver(),
    )


@lru_cache
def agent_model() -> BaseChatModel:
    config = settings()
    try:
        config.require_google_ai()
    except RuntimeError as error:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    model_options = {
        "model": config.llm_model,
        "max_retries": 2,
        "vertexai": config.google_genai_use_vertexai,
    }
    if config.google_genai_use_vertexai:
        model_options.update(
            project=config.google_cloud_project,
            location=config.google_cloud_location,
        )
    else:
        model_options["api_key"] = config.google_api_key
    return ChatGoogleGenerativeAI(**model_options)


@lru_cache
def reranker_model() -> BaseChatModel:
    config = settings()
    try:
        config.require_google_ai()
    except RuntimeError as error:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    model_options = {
        "model": "gemini-2.5-flash" if "gemini" in config.llm_model else config.llm_model,
        "temperature": 0.0,
        "max_output_tokens": 50,
        "max_retries": 2,
        "vertexai": config.google_genai_use_vertexai,
    }
    if config.google_genai_use_vertexai:
        model_options.update(
            project=config.google_cloud_project,
            location=config.google_cloud_location,
        )
    else:
        model_options["api_key"] = config.google_api_key
    return ChatGoogleGenerativeAI(**model_options)


@lru_cache
def settings() -> Settings:
    return Settings.from_environment()


@lru_cache
def identity_store() -> PostgresIdentityStore:
    config = settings()
    return PostgresIdentityStore(repository_store(), config.token_encryption_key)


def campaign_access_service(
    campaigns: Annotated[CampaignService, Depends(campaign_service)],
    store: Annotated[PostgresIdentityStore, Depends(identity_store)],
) -> CampaignAccessService:
    return CampaignAccessService(campaigns, IdentityWorkspaceAccessReader(store))


def campaign_analysis_service(
    model: Annotated[BaseChatModel, Depends(agent_model)],
    retrieval: Annotated[
        StructuredRetrievalService, Depends(structured_retrieval_service)
    ],
    text_retrieval: Annotated[TextRetrievalService, Depends(text_retrieval_service)],
    access: Annotated[CampaignAccessService, Depends(campaign_access_service)],
) -> CampaignAnalysisService:
    return CampaignAnalysisService(
        access=access,
        agents=CampaignAgentFactory(
            model=model,
            retrieval=retrieval,
            text_retrieval=text_retrieval,
        ),
    )


def google_oauth_client() -> GoogleOAuthClient:
    config = settings()
    mock_base_url = config.platform_mock_base_url
    if not mock_base_url:
        try:
            config.require_google_oauth()
        except RuntimeError as error:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error
    return GoogleOAuthClient(
        client_id="mock-google-client"
        if mock_base_url
        else config.google_client_id or "",
        client_secret=(
            "mock-google-secret" if mock_base_url else config.google_client_secret or ""
        ),
        public_base_url=config.public_base_url,
        authorize_url=(
            f"{mock_base_url}/google/o/oauth2/v2/auth"
            if mock_base_url
            else "https://accounts.google.com/o/oauth2/v2/auth"
        ),
        token_url=(
            f"{mock_base_url}/google/token"
            if mock_base_url
            else "https://oauth2.googleapis.com/token"
        ),
        userinfo_url=(
            f"{mock_base_url}/google/userinfo"
            if mock_base_url
            else "https://openidconnect.googleapis.com/v1/userinfo"
        ),
    )


def platform_access_tokens(
    store: Annotated[PostgresIdentityStore, Depends(identity_store)],
    oauth: Annotated[GoogleOAuthClient, Depends(google_oauth_client)],
) -> PlatformAccessTokenProvider:
    return PlatformAccessTokenProvider(store, oauth)


def ads_connector_factory(
    config: Annotated[Settings, Depends(settings)],
) -> AdsConnectorFactory:
    return AdsConnectorFactory(config)


def ads_ingestion_source_planner(
    access_tokens: Annotated[
        PlatformAccessTokenProvider, Depends(platform_access_tokens)
    ],
    connectors: Annotated[AdsConnectorFactory, Depends(ads_connector_factory)],
) -> AdsIngestionSourcePlanner:
    return AdsIngestionSourcePlanner(access_tokens, connectors)


def advertising_catalog_service(
    access_tokens: Annotated[
        PlatformAccessTokenProvider, Depends(platform_access_tokens)
    ],
    connectors: Annotated[AdsConnectorFactory, Depends(ads_connector_factory)],
) -> AdvertisingCatalogService:
    return AdvertisingCatalogService(access_tokens, connectors)


def meta_oauth_client() -> MetaOAuthClient:
    config = settings()
    if config.platform_mock_base_url:
        app_id, app_secret = "mock-meta-app", "mock-meta-secret"
    else:
        try:
            app_id, app_secret = config.require_meta_oauth()
        except RuntimeError as error:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error
    return MetaOAuthClient(
        app_id=app_id,
        app_secret=app_secret,
        public_base_url=config.public_base_url,
        api_version=config.meta_graph_api_version,
        authorize_base_url=(
            f"{config.platform_mock_base_url}/meta"
            if config.platform_mock_base_url
            else "https://www.facebook.com"
        ),
        graph_base_url=(
            f"{config.platform_mock_base_url}/meta"
            if config.platform_mock_base_url
            else "https://graph.facebook.com"
        ),
    )


def signed_token_codec() -> SignedTokenCodec:
    config = settings()
    try:
        secret = config.require_session_secret()
    except RuntimeError as error:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    return SignedTokenCodec(secret)


def browser_state_manager() -> BrowserStateManager:
    return BrowserStateManager(signed_token_codec())


def session_manager() -> SessionManager:
    return SessionManager(signed_token_codec())
