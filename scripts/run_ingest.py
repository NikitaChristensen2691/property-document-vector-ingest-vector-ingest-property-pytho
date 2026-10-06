import argparse
import asyncio
import base64
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from property_ingest import PropertyDocument, backend_from_environment, ingest_property_document


async def run(pdf_path: Path, collection: str) -> None:
    document = PropertyDocument(
        property_id="harbor-view-12",
        document_id=f"inspection-{pdf_path.stem}",
        kind="inspection_report",
        pdf_base64=base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
        received_on=date.today(),
        inspection_due_on=date(date.today().year + 1, 6, 15),
    )
    backend = backend_from_environment()
    try:
        result = await ingest_property_document(document, backend, collection)
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    finally:
        await backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse, chunk, embed, and index a property inspection PDF")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--collection", default="property-documents")
    args = parser.parse_args()
    asyncio.run(run(args.pdf, args.collection))
