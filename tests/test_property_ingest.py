import asyncio
import base64
from datetime import date
from typing import Any

from property_ingest import PropertyDocument, ingest_property_document


class RecordingBackend:
    def __init__(self) -> None:
        self.vectors: list[dict[str, Any]] = []

    async def parse_pdf(self, pdf_base64: str) -> str:
        assert base64.b64decode(pdf_base64) == b"inspection-pdf"
        return "Boiler room passed.\n\nReplace corridor detector before the next inspection."

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 0.5] for index, _ in enumerate(texts)]

    async def ensure_collection(self, collection: str, dimension: int, request_id: str) -> None:
        assert (collection, dimension) == ("property-documents", 2)
        assert request_id

    async def upsert(self, collection: str, vectors: list[dict[str, Any]], request_id: str) -> None:
        assert collection == "property-documents"
        assert request_id
        self.vectors = vectors


def test_inspection_is_indexed_and_schedules_its_due_date() -> None:
    backend = RecordingBackend()
    document = PropertyDocument(
        property_id="harbor-view-12",
        document_id="inspection-2026-04",
        kind="inspection_report",
        pdf_base64=base64.b64encode(b"inspection-pdf").decode("ascii"),
        received_on=date(2026, 4, 10),
        inspection_due_on=date(2027, 4, 10),
    )

    result = asyncio.run(ingest_property_document(document, backend, "property-documents"))

    assert result.reminder_status == "scheduled"
    assert result.reminder_due_on == date(2027, 4, 10)
    assert result.chunks_upserted == 1
    assert backend.vectors[0]["metadata"]["kind"] == "inspection_report"
    assert backend.vectors[0]["metadata"]["property_id"] == "harbor-view-12"
