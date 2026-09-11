# Backend Leaderboard Data Integration

## Goal

Build the backend data pipeline and REST API needed for the frontend to visualize model leaderboard data from:

1. Artificial Analysis API v2
2. LMArena’s Hugging Face leaderboard dataset

The backend uses Django REST Framework, `uv` for package management, and Celery for scheduled data refreshes.

Please begin in **plan mode**. First inspect the existing project structure, existing Django/DRF conventions, Celery setup, and the source schemas. Present a concise implementation plan and flag assumptions or ambiguities before making consequential design decisions.

## Data Sources

### Artificial Analysis

- API base URL: `https://artificialanalysis.ai/api/v2`
- Local API reference: `backend/prompts/artificial-analysis-openapi.yaml`
- Required source endpoint:

```text
GET /language/models/free
```

Use the local OpenAPI file as the source of truth for authentication, request format, pagination, response fields, rate limits, and other API behavior.

### LMArena

Use the Hugging Face `datasets` library to retrieve each required latest leaderboard split:

```python
from datasets import load_dataset

ds = load_dataset(
    "lmarena-ai/leaderboard-dataset",
    "<field>",
    split="latest",
)
```

Required fields:

- `agent`
- `document`
- `search`
- `webdev`

## Dataset Scope

### LMArena

- Load the `latest` split for all four required fields.
- Treat `agent` as the primary model set.
- For `document`, `search`, and `webdev`, retain only records whose model is also present in the latest `agent` split.
- Determine the correct stable model identity field by inspecting the actual dataset schemas. Do not assume field names or use undocumented fuzzy matching.

### Artificial Analysis

- Retrieve data using `GET /language/models/free`.
- Keep the records corresponding to language models in the retained LMArena `agent` subset.
- Inspect the actual source schemas and choose a robust, maintainable cross-source model matching approach.
- Clearly report unmatched records so they can be reviewed rather than silently dropped without visibility.

## Refreshing Data

- Refresh all source data **twice daily** through Celery scheduled tasks.
- Reuse the project’s existing scheduling pattern if one exists; otherwise recommend an appropriate Celery-compatible approach.
- Ensure refreshes are safe to rerun, do not create duplicate records, and do not remove the last successful data if an external request fails.
- Record enough ingestion status and freshness metadata to troubleshoot failures and let the frontend show when data was last updated.

## Backend Requirements

Implement a clean, maintainable Django structure that separates:

- External data retrieval
- Data validation and normalization
- Model matching/intersection logic
- Database persistence
- Celery task orchestration
- DRF serializers, views, and URL routing

Follow existing repository conventions wherever possible. Manage any new packages with `uv` and update the lockfile.

Store data in the backend database so frontend requests are fast and do not trigger live external API calls.

## Frontend API Requirements

Create versioned, read-only DRF endpoints under a consistent path such as:

```text
/api/v1/leaderboard/
```

The frontend needs endpoints that support:

1. **Overview / joined data**
   - A visualization-ready model list combining available LMArena category data with matching Artificial Analysis information.
   - Include data freshness timestamps.

2. **LMArena category data**
   - Query leaderboard data for `agent`, `document`, `search`, or `webdev`.
   - Support practical filtering, ordering, and pagination based on the available schema and frontend visualization needs.

3. **Artificial Analysis data**
   - Return the matched Artificial Analysis model records and useful normalized metrics.
   - Support practical filtering, ordering, and pagination.

4. **Model detail**
   - Return all available LMArena categories and Artificial Analysis data for a single model.

5. **Metadata / freshness**
   - Return supported categories, latest successful refresh times, and enough source/status information for frontend loading and stale-data states.

Design response schemas that are stable and visualization-friendly. Prefer explicit normalized fields for commonly used metrics, while avoiding unnecessary exposure of large raw upstream payloads.

Use standard DRF error behavior, validate query parameters, and follow the project’s existing authentication, permissions, CORS, pagination, and API formatting conventions.

## Documentation Required

Create or update frontend-facing API documentation that includes:

- Endpoint paths and HTTP methods
- Query parameters, valid values, defaults, and validation behavior
- Response schemas
- Representative JSON examples using sanitized/realistic data
- Pagination behavior
- Error responses
- Freshness and missing-data semantics
- How the frontend should use overview, category, and model-detail endpoints

The documentation should distinguish confirmed source fields from fields chosen by the backend after schema inspection.

## Quality Expectations

- Inspect the local OpenAPI specification and real LMArena schemas before finalizing source mappings.
- Add database migrations as needed.
- Add unit tests for retrieval, intersection/matching, refresh behavior, and key API contracts.
- Add integration tests or mocks for external providers where practical.
- Handle external failures, timeouts, rate limits, schema changes, and retries appropriately.
- Keep secrets in configuration/environment variables; never commit API keys.
- Document any assumptions, schema limitations, or unresolved matching issues.

## Expected Deliverables

1. Django models/migrations and ingestion implementation.
2. LMArena and Artificial Analysis data clients.
3. Twice-daily Celery refresh workflow.
4. Versioned DRF endpoints for frontend visualizations.
5. Automated tests for the main pipeline and endpoints.
6. Frontend API documentation.
7. A concise implementation summary covering architecture, matching decisions, scheduling, configuration required, and known limitations.
