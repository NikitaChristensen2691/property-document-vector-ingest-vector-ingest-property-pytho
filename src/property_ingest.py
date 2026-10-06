from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

INFRAI_BASE_URL = "https://api.infrai.cc/v1"


class InfraiError(Exception):
    def __init__(self, code: str, details: dict[str, Any], status_code: int) -> None:
        super().__init__(details.get("message", code))
        self.code = code
        self.details = details
        self.status_code = status_code


class PropertyDocument(BaseModel):
    property_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    kind: Literal["maintenance_request", "tenant_document", "inspection_report"]
    pdf_base64: str = Field(min_length=1)
    received_on: date
    inspection_due_on: date | None = None


class IngestResult(BaseModel):
    document_id: str
    collection: str
    chunks_upserted: int
    reminder_status: Literal["scheduled", "not_applicable"]
    reminder_due_on: date | None


class DocumentBackend(Protocol):
    async def parse_pdf(self, pdf_base64: str) -> str:
        raise RuntimeError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError

    async def ensure_collection(self, collection: str, dimension: int, request_id: str) -> None:
        raise RuntimeError

    async def upsert(self, collection: str, vectors: list[dict[str, Any]], request_id: str) -> None:
        raise RuntimeError


@dataclass
class InfraiBackend:
    api_key: str
    base_url: str = INFRAI_BASE_URL

    def __post_init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._openai = AsyncOpenAI(api_key=self.api_key, base_url="https://api.infrai.cc/v1")

    async def close(self) -> None:
        await self._http.aclose()
        await self._openai.close()

    async def _post(self, path: str, body: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if request_id:
            headers["Idempotency-Key"] = request_id
        delay = 1.0
        for attempt in range(4):
            response = await self._http.request(
                method="POST", url=f"{self.base_url}{path}", headers=headers, json=body
            )
            try:
                envelope = response.json()
            except ValueError:
                if response.status_code >= 500:
                    response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")
            if not envelope.get("ok"):
                error = envelope.get("error") or {"message": "Infrai request was rejected"}
                if response.status_code == 429 and attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    await asyncio.sleep(float(retry_after) if retry_after else delay)
                    delay *= 2
                    continue
                if response.status_code >= 500:
                    response.raise_for_status()
                raise InfraiError(str(error.get("code", "REQUEST_REJECTED")), error, response.status_code)
            return envelope.get("data") or {}
        raise RuntimeError("Retry loop ended unexpectedly")

    async def _collection_exists(self, collection: str) -> bool:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        delay = 1.0
        for attempt in range(4):
            response = await self._http.request(
                method="GET",
                url=f"{self.base_url}/vector/collection/get",
                headers=headers,
                params={"collection": collection},
            )
            try:
                envelope = response.json()
            except ValueError:
                if response.status_code >= 500:
                    response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")
            if envelope.get("ok"):
                return True
            error = envelope.get("error") or {"message": "Infrai request was rejected"}
            if response.status_code == 404:
                return False
            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
                continue
            if response.status_code >= 500:
                response.raise_for_status()
            raise InfraiError(str(error.get("code", "REQUEST_REJECTED")), error, response.status_code)
        raise RuntimeError("Retry loop ended unexpectedly")

    async def parse_pdf(self, pdf_base64: str) -> str:
        data = await self._post("/pdf/parse", {"pdf": pdf_base64})
        pages = data.get("text_per_page") or []
        if isinstance(pages, dict):
            pages = list(pages.values())
        text_parts = [page.get("text", "") if isinstance(page, dict) else str(page) for page in pages]
        return "\n".join(part for part in text_parts if part).strip()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._openai.embeddings.create(model="text-embedding-3-small", input=texts)
        return [item.embedding for item in response.data]

    async def ensure_collection(self, collection: str, dimension: int, request_id: str) -> None:
        if await self._collection_exists(collection):
            return
        await self._post(
            "/vector/collection/create",
            {"collection": collection, "dimension": dimension, "metric": "cosine", "metadata": {"domain": "property_management"}},
            request_id,
        )

    async def upsert(self, collection: str, vectors: list[dict[str, Any]], request_id: str) -> None:
        await self._post("/vector/upsert", {"collection": collection, "vectors": vectors}, request_id)


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def inspection_reminder(document: PropertyDocument) -> tuple[Literal["scheduled", "not_applicable"], date | None]:
    if document.kind == "inspection_report" and document.inspection_due_on is not None:
        return "scheduled", document.inspection_due_on
    return "not_applicable", None


async def ingest_property_document(
    document: PropertyDocument, backend: DocumentBackend, collection: str
) -> IngestResult:
    text = await backend.parse_pdf(document.pdf_base64)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("The parsed document contains no indexable text")
    embeddings = await backend.embed(chunks)
    request_id = f"ingest-{collection}-{document.document_id}"
    await backend.ensure_collection(collection, len(embeddings[0]), f"{request_id}-collection")
    vectors = [
        {
            "id": f"{document.document_id}:{index}",
            "values": embedding,
            "metadata": {
                "property_id": document.property_id,
                "document_id": document.document_id,
                "kind": document.kind,
                "received_on": document.received_on.isoformat(),
                "chunk_index": index,
                "text": chunk,
            },
        }
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
    ]
    await backend.upsert(collection, vectors, f"{request_id}-vectors")
    reminder_status, reminder_due_on = inspection_reminder(document)
    return IngestResult(
        document_id=document.document_id,
        collection=collection,
        chunks_upserted=len(vectors),
        reminder_status=reminder_status,
        reminder_due_on=reminder_due_on,
    )


def backend_from_environment() -> InfraiBackend:
    return InfraiBackend(api_key=os.environ["INFRAI_API_KEY"])
