from __future__ import annotations

from uuid import UUID

from elasticsearch import Elasticsearch

from .contracts.retrieval import (
    CampaignDocument,
    DocumentType,
    TextSearchHit,
)
from .contracts.search_profile import (
    BM25_WHOLE_DOCUMENT_PROFILE,
    RetrievalProfile,
)


class ElasticsearchCampaignDocumentSearch:
    """Rebuildable BM25 projection for campaign text documents."""

    def __init__(
        self,
        url: str,
        index_name: str,
        profile: RetrievalProfile = BM25_WHOLE_DOCUMENT_PROFILE,
        *,
        api_key: str | None = None,
        ca_certs: str | None = None,
        verify_certs: bool = True,
    ) -> None:
        client_kwargs: dict[str, object] = {"request_timeout": 5}
        if api_key:
            client_kwargs["api_key"] = api_key
        if url.startswith("https"):
            client_kwargs["verify_certs"] = verify_certs
            if ca_certs:
                client_kwargs["ca_certs"] = ca_certs
        self._client = Elasticsearch(url, **client_kwargs)
        self._index_name = index_name
        self._profile = profile.model_copy(update={"index_version": index_name})

    @property
    def profile(self) -> RetrievalProfile:
        return self._profile

    def ensure_index(self) -> None:
        if self._client.indices.exists(index=self._index_name):
            return
        self._client.indices.create(
            index=self._index_name,
            mappings={
                "dynamic": "strict",
                "properties": {
                    "document_id": {"type": "keyword"},
                    "workspace_id": {"type": "keyword"},
                    "campaign_id": {"type": "keyword"},
                    "document_type": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "source_ref": {"type": "keyword"},
                    "created_at": {"type": "date"},
                },
            },
        )

    def index(self, document: CampaignDocument) -> None:
        self.ensure_index()
        self._client.index(
            index=self._index_name,
            id=str(document.id),
            document={
                "document_id": str(document.id),
                "workspace_id": str(document.workspace_id),
                "campaign_id": str(document.campaign_id),
                "document_type": document.document_type.value,
                "title": document.title,
                "content": document.content,
                "source_ref": document.source_ref,
                "created_at": document.created_at.isoformat(),
            },
            refresh="wait_for",
        )

    def search(
        self,
        *,
        workspace_id: UUID,
        campaign_id: UUID,
        query: str,
        document_types: tuple[DocumentType, ...] = (),
        top_k: int = 5,
    ) -> tuple[TextSearchHit, ...]:
        self.ensure_index()
        filters: list[dict[str, object]] = [
            {"term": {"workspace_id": str(workspace_id)}},
            {"term": {"campaign_id": str(campaign_id)}},
        ]
        if document_types:
            filters.append(
                {"terms": {"document_type": [item.value for item in document_types]}}
            )
        response = self._client.search(
            index=self._index_name,
            size=max(1, min(top_k, 20)),
            query={
                "bool": {
                    "filter": filters,
                    "must": {
                        "multi_match": {
                            "query": query,
                            "fields": ["title^2", "content"],
                        }
                    },
                }
            },
            highlight={
                "fields": {"content": {"fragment_size": 180, "number_of_fragments": 1}}
            },
        )
        return tuple(
            self._hit(item, rank=rank)
            for rank, item in enumerate(response["hits"]["hits"], start=1)
        )

    def _hit(self, hit: dict[str, object], *, rank: int) -> TextSearchHit:
        source = hit["_source"]
        highlight = hit.get("highlight", {})
        fragments = highlight.get("content", [])
        excerpt = fragments[0] if fragments else str(source["content"])[:180]
        return TextSearchHit(
            document_id=source["document_id"],
            campaign_id=source["campaign_id"],
            document_type=source["document_type"],
            title=source["title"],
            excerpt=excerpt,
            source_ref=source["source_ref"],
            score=hit["_score"],
            rank=rank,
            retrieval_method=self._profile.method,
            index_version=self._profile.index_version,
            chunker_version=self._profile.chunker_version,
            retriever_version=self._profile.retriever_version,
        )
