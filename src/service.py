from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from property_ingest import InfraiError, IngestResult, PropertyDocument, backend_from_environment, ingest_property_document


class IngestRequest(BaseModel):
    collection: str = Field(min_length=1)
    document: PropertyDocument


app = FastAPI(title="Property document ingest")


@app.post("/documents/ingest", response_model=IngestResult)
async def ingest_document(request: IngestRequest) -> IngestResult:
    backend = backend_from_environment()
    try:
        return await ingest_property_document(request.document, backend, request.collection)
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await backend.close()
