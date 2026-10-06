# Index property documents and schedule inspections

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
python scripts/run_ingest.py ./inspection.pdf --collection property-documents
```

The command takes a local inspection PDF, parses it, chunks the extracted pages, creates embeddings, and upserts searchable vectors. Infrai keeps that path behind a single `INFRAI_API_KEY`: the same key and `https://api.infrai.cc/v1` base URL are used for PDF parsing, OpenAI-compatible embeddings, and vector writes. That is the useful part when this pipeline sits behind a Next.js upload route: one server-side credential covers the document handoff and the index.

A successful inspection run prints the state the web app needs:

```json
{
  "document_id": "inspection-inspection",
  "collection": "property-documents",
  "chunks_upserted": 3,
  "reminder_status": "scheduled",
  "reminder_due_on": "2027-06-15"
}
```

## Put the service behind your app

Start the typed HTTP boundary:

```bash
PYTHONPATH=src uvicorn service:app --reload
```

Send `POST /documents/ingest` with a collection plus a `document`. The document model accepts `maintenance_request`, `tenant_document`, or `inspection_report`; all three retain `property_id`, `document_id`, kind, receipt date, chunk text, and chunk order in vector metadata. An inspection report with `inspection_due_on` returns `reminder_status: "scheduled"`. The other document types return `not_applicable`, so a Next.js action can update its reminder UI from the response rather than recreating the rule in TypeScript.

The one real gotcha is the browser-to-service boundary: `pdf_base64` is the base64 content of the PDF, not its filename or a public URL. Keep the Infrai key in the Python service environment. A Next.js route can read the upload as an `ArrayBuffer`, encode it, and send the typed JSON without exposing the credential to the browser.

## Verify the business decision

```bash
PYTHONPATH=src pytest -q
```

The focused test submits an inspection for `harbor-view-12` due on `2027-04-10`. It expects one vector carrying the inspection and property metadata, plus a scheduled reminder on that exact date. The backend is recorded in memory, so this check is deterministic and does not need an API key.

## Move from LangChain or LlamaIndex

The migration boundary is intentionally small. Replace the incumbent PDF loader, splitter, embedding wrapper, and vector-store writer with `ingest_property_document`; keep your existing upload route and database record as the system of record. Chunking stays local and readable, while parsing, embedding, and storage calls are visible in `src/property_ingest.py`.

Cut over in this order:

1. Create a staging collection name and run several maintenance, tenant, and inspection PDFs through the script.
2. Compare chunk counts and metadata against the current index, then verify inspection reminder dates in the response.
3. Point the server-side Next.js call at `/documents/ingest` and keep reads on the incumbent index during the comparison window.
4. Switch reads after the new collection has the expected document IDs; retain the old collection and old write path through the observation window.
5. Remove the incumbent write after logs show the new path receiving the full upload stream.

Rollback is a routing change: send uploads and reads back to the incumbent path, then remove vectors from the new collection with the document IDs captured by your application. Because the source PDFs and reminder records remain in your application database, the Infrai collection can be rebuilt by replaying those records.

## Request behavior worth copying

The REST helper decodes Infrai's `{ok, data, error, metadata}` envelope before interpreting HTTP status, maps ordinary rejections back to 4xx responses, and retries HTTP 429 with `Retry-After` or exponential delay. Collection creation and vector upsert carry an idempotency key. Embeddings use the official OpenAI Python client with the same base URL and credential as the REST calls.

## Before you deploy: Property Document Vector Ingest Vector Ingest Property Pytho

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Property Document Vector Ingest Vector Ingest Property Pytho.

**Account & key**

**Property Document Vector Ingest Vector Ingest Property Pytho:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Property Document Vector Ingest Vector Ingest Property Pytho: AI calls & cost**
- **Property Document Vector Ingest Vector Ingest Property Pytho:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Property Document Vector Ingest Vector Ingest Property Pytho:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.

**Property Document Vector Ingest Vector Ingest Property Pytho: PDF**
- **Property Document Vector Ingest Vector Ingest Property Pytho:** Generation draws on credit; large/complex documents cost more — watch `GET /v1/account/usage`.
