"""Document management API tests (isolated tmp storage, stub embedder)."""

from __future__ import annotations

import hashlib
import io

import numpy as np
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.documents.ingestion import DocumentIngestionService
from app.documents.registry import DocumentRegistry
from app.documents.storage import DocumentStorage
from app.main import create_app
from app.rag.vector_store import VectorStore


class StubEmbedder:
    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self.model_name = "stub"

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, texts, *, as_query: bool = False):
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(self._dimension).astype(np.float32)
            vector /= max(1e-9, float(np.linalg.norm(vector)))
            vectors.append(vector)
        return np.stack(vectors)


class FakeOrchestrator:
    async def run(self, query):
        raise AssertionError("document API tests do not call query")


def make_pdf_bytes(pages: list[str]) -> bytes:
    import fitz

    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 770), text)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def build_service(tmp_path, **overrides) -> DocumentIngestionService:
    fields: dict = {
        "document_storage_path": str(tmp_path / "storage"),
        "document_max_upload_mb": 5,
        "document_dynamic_collection": "test_api_dynamic",
        "document_ingest_batch_size": 4,
    }
    fields.update(overrides)
    settings = Settings(_env_file=None, **fields)
    storage = DocumentStorage(settings.document_storage_root)
    registry = DocumentRegistry(storage.registry_dir / "documents.db")
    store = VectorStore(storage.vectors, settings.document_dynamic_collection)
    return DocumentIngestionService(storage=storage, registry=registry,
                                    embedder=StubEmbedder(), store=store,
                                    settings=settings)


def make_client(service) -> TestClient:
    app = create_app(orchestrator=FakeOrchestrator(), document_service=service)
    return TestClient(app)


PDF_BYTES = make_pdf_bytes(["API upload spindle content. " * 20,
                            "Second page torque content. " * 20])


def upload(client: TestClient, data: bytes = PDF_BYTES, filename: str = "manual.pdf",
           content_type: str = "application/pdf"):
    return client.post("/api/documents",
                       files={"file": (filename, data, content_type)})


# ---------------- upload ----------------

def test_upload_valid_pdf_returns_201_ready(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = upload(client)
    assert response.status_code == 201
    body = response.json()
    assert body["document_id"].startswith("USR-")
    assert body["status"] == "READY"
    assert body["page_count"] > 0
    assert body["chunk_count"] > 0
    assert body["duplicate"] is False


def test_duplicate_upload_returns_success_without_reindex(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        first = upload(client)
        assert first.status_code == 201
        count = service.store.point_count()
        second = upload(client, filename="renamed-copy.pdf")
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["document_id"] == first.json()["document_id"]
    assert service.store.point_count() == count


def test_non_pdf_rejected(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = upload(client, data=b"plain text", filename="note.txt",
                          content_type="text/plain")
    assert response.status_code == 415


def test_fake_pdf_rejected(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = upload(client, data=b"%PDF-1.4 garbage \xff\x00", filename="fake.pdf")
    assert response.status_code in (415, 422)


def test_malformed_pdf_rejected_safely(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = upload(client, data=b"%PDF-1.4\n%truncated \xff\xfe", filename="broken.pdf")
    assert response.status_code in (415, 422)
    assert "traceback" not in response.text.lower()


def test_encrypted_pdf_rejected_safely(tmp_path) -> None:
    import fitz

    service = build_service(tmp_path)
    buffer = io.BytesIO()
    document = fitz.open()
    document.new_page().insert_text((72, 72), "secret")
    document.save(buffer, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="o")
    document.close()
    with make_client(service) as client:
        response = upload(client, data=buffer.getvalue(), filename="enc.pdf")
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "ENCRYPTED_PDF"


def test_image_only_pdf_rejected_safely(tmp_path) -> None:
    import fitz

    service = build_service(tmp_path)
    buffer = io.BytesIO()
    document = fitz.open()
    document.new_page()
    document.save(buffer)
    document.close()
    with make_client(service) as client:
        response = upload(client, data=buffer.getvalue(), filename="blank.pdf")
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "NO_EXTRACTABLE_TEXT"


def test_oversized_upload_returns_413(tmp_path) -> None:
    service = build_service(tmp_path, document_max_upload_mb=1)
    with make_client(service) as client:
        response = upload(client, data=b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024))
    assert response.status_code == 413


def test_traversal_filename_harmless(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = upload(client, filename="../../evil.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "../../evil.pdf"
    record = service.get_document(body["document_id"])
    assert record is not None
    assert "/" not in record.stored_filename
    assert service.storage.has_original(record.stored_filename)


def test_original_filename_not_storage_path(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        body = upload(client, filename="report.pdf").json()
    record = service.get_document(body["document_id"])
    assert record is not None
    assert record.stored_filename == f"{body['document_id']}.pdf"


def test_upload_disabled_returns_503(tmp_path) -> None:
    settings = Settings(_env_file=None, document_upload_enabled=False,
                        document_storage_path=str(tmp_path / "s"))
    app = create_app(orchestrator=FakeOrchestrator(), settings=settings)
    with TestClient(app) as client:
        response = upload(client)
    assert response.status_code == 503


def test_no_secrets_or_paths_returned(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        body = upload(client).json()
    text = str(body)
    assert "stored_filename" not in body
    assert "sha256" not in body
    for forbidden in ("GEMINI_API_KEY", "TYPESAFE_API_KEY", "D:\\", "/tmp", ".db",
                      "vectors", "documents.db"):
        assert forbidden not in text


# ---------------- list ----------------

def test_list_empty_registry(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        body = client.get("/api/documents").json()
    assert body == {"documents": [], "count": 0}


def test_list_ready_documents(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        upload(client)
        body = client.get("/api/documents").json()
    assert body["count"] == 1
    assert body["documents"][0]["status"] == "READY"


def test_rejected_upload_retained_as_failed_for_audit(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        upload(client, data=b"not a pdf", filename="bad.txt", content_type="text/plain")
        body = client.get("/api/documents").json()
    assert body["count"] == 1
    item = body["documents"][0]
    assert item["status"] == "FAILED"
    assert item["error_code"] == "NOT_A_PDF"


def test_list_deterministic_order(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        first = upload(client).json()
        second = upload(client, data=make_pdf_bytes(["Different content here. " * 20])).json()
        body = client.get("/api/documents").json()
    first_seen = client.get("/api/documents").json()
    assert [d["document_id"] for d in body["documents"]] == [
        d["document_id"] for d in first_seen["documents"]]
    assert {first["document_id"], second["document_id"]} == {
        d["document_id"] for d in body["documents"]}


def test_list_hides_internal_fields(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        body = client.get("/api/documents").json()
    assert body == {"documents": [], "count": 0}
    with make_client(service) as client:
        upload(client)
        item = client.get("/api/documents").json()["documents"][0]
    assert "stored_filename" not in item
    assert "sha256" not in item
    assert "metadata_json" not in item
    assert all(":\\" not in str(value) and "/tmp" not in str(value)
               for value in item.values() if isinstance(value, str))


# ---------------- get ----------------

def test_get_known_dynamic_id(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        created = upload(client).json()
        response = client.get(f"/api/documents/{created['document_id']}")
    assert response.status_code == 200
    assert response.json()["document_id"] == created["document_id"]


def test_get_unknown_id_returns_404(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        response = client.get("/api/documents/USR-FFFFFFFFFFFF")
    assert response.status_code == 404


def test_get_static_doc_id_returns_404(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        for bad in ("DOC-53F6788896F3", "CHUNK-X", "not-an-id", "USR-tooshort"):
            assert client.get(f"/api/documents/{bad}").status_code == 404


def test_get_contains_only_safe_fields(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        body = upload(client).json()
        item = client.get(f"/api/documents/{body['document_id']}").json()
    assert set(item) == {"document_id", "original_filename", "mime_type",
                         "file_size_bytes", "status", "page_count", "chunk_count",
                         "created_at", "updated_at", "error_code", "error_message"}


# ---------------- delete ----------------

def test_delete_full_lifecycle(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        created = upload(client).json()
        document_id = created["document_id"]
        assert client.get(f"/api/documents/{document_id}").status_code == 200
        assert service.vector_count_for(document_id) > 0
        deleted = client.delete(f"/api/documents/{document_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"document_id": document_id, "deleted": True}
    assert service.get_document(document_id) is None
    assert service.vector_count_for(document_id) == 0


def test_delete_removes_original_file(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        created = upload(client).json()
        record = service.get_document(created["document_id"])
        assert record is not None
        path = service.storage.original_path(record.stored_filename)
        assert path.is_file()
        client.delete(f"/api/documents/{created['document_id']}")
    assert not path.is_file()


def test_delete_unknown_returns_404(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        assert client.delete("/api/documents/USR-FFFFFFFFFFFF").status_code == 404
        assert client.delete("/api/documents/DOC-53F6788896F3").status_code == 404


def test_delete_failed_document_cleanup(tmp_path) -> None:
    import fitz

    service = build_service(tmp_path)
    buffer = io.BytesIO()
    document = fitz.open()
    document.new_page()
    document.save(buffer)
    document.close()
    with make_client(service) as client:
        created = upload(client, data=buffer.getvalue(), filename="blank.pdf")
        assert created.status_code == 422
        # Direct service-level FAILED record still deletable.
        record = service.registry.list_documents()[0]
        assert record.status == "FAILED"
        deleted = client.delete(f"/api/documents/{record.document_id}")
    assert deleted.status_code == 200
    assert service.get_document(record.document_id) is None


def test_deleted_document_no_longer_retrieved(tmp_path) -> None:
    import asyncio

    from app.contracts.query import QueryRequest
    from app.documents.retrieval import DynamicDocumentRetriever
    from app.rag.embeddings import build_embedding_model

    from tests.documents.conftest import make_pdf

    phrase = "api delete retrieval smoke phrase"
    service = build_service(tmp_path)
    service.embedder = build_embedding_model("BAAI/bge-small-en-v1.5")
    pdf = tmp_path / "del.pdf"
    make_pdf(pdf, [f"Note about {phrase} for service checks. " * 12])
    with make_client(service) as client:
        created = upload(client, data=pdf.read_bytes(), filename="del.pdf").json()
        document_id = created["document_id"]
        retriever = DynamicDocumentRetriever(
            path=service.store.path, collection=service.store.collection,
            embedder=service.embedder, settings=service.settings, store=service.store)
        before = asyncio.run(retriever.retrieve(
            QueryRequest(query_id="Q-DEL-1", query=phrase), top_k=5))
        assert any(e.provenance.document_id == document_id for e in before)
        assert client.delete(f"/api/documents/{document_id}").status_code == 200
        after = asyncio.run(retriever.retrieve(
            QueryRequest(query_id="Q-DEL-2", query=phrase), top_k=5))
    assert not any(e.provenance.document_id == document_id for e in after)


def test_reupload_after_delete_works(tmp_path) -> None:
    service = build_service(tmp_path)
    with make_client(service) as client:
        first = upload(client).json()
        assert client.delete(f"/api/documents/{first['document_id']}").status_code == 200
        second = upload(client)
    assert second.status_code == 201
    assert second.json()["duplicate"] is False
    assert second.json()["document_id"] != first["document_id"]


# ---------------- lifecycle ----------------

def test_service_and_retriever_share_store(tmp_path) -> None:
    from app.documents.ingestion import build_document_resources

    settings = Settings(_env_file=None,
                        document_storage_path=str(tmp_path / "storage"),
                        document_dynamic_collection="test_share")
    resources = build_document_resources(settings)
    try:
        service = resources.build_service()
        retriever = resources.build_dynamic_retriever()
        assert service.store is retriever.store
        composite = resources.build_composite_retriever()
        assert composite._sources[1].searcher.store is service.store
    finally:
        resources.close()


def test_app_owned_resources_close_once_injected_not_closed(tmp_path) -> None:
    service = build_service(tmp_path)
    app = create_app(orchestrator=FakeOrchestrator(), document_service=service)
    with TestClient(app):
        pass
    # Externally owned: still usable, nothing double-closed.
    assert service.registry.list_documents() == []
    service.registry.close()
    service.store.close()
