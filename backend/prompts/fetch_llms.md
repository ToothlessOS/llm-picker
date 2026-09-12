# Tasks 
- Implement the backend to obtain data from Aritificial Analysis API and the LMArena Leaderboard dataset on huggingface
- Implement API endpoints so the frontend can pull the data for visualization
- Create a documentation of these API endpoints for frontend developers

# Data
- Aritifical Analysis API: https://artificialanalysis.ai/api/v2, you can refer to `backend/prompts/artificial-analysis-openapi.yaml` for reference
- For LMArena, uses huggingface dataset to retrieve:

```python
from datasets import load_dataset

ds = load_dataset("lmarena-ai/leaderboard-dataset", "agent", split="latest")
```

# Stacks
The backend uses Django REST Framework and `uv` for managing python packages. `celery` is installed for cron data fetch tasks.

# Dataset Scope (v1)

## LMArena huggingface

Use `ds = load_dataset("lmarena-ai/leaderboard-dataset", "[field]", split="latest")` for all of the following fields; Refresh twice a day through cron tasks.

- `agent`
- `document` (intersect of the "latest" split with `agent`) 
- `search`  (intersect of the "latest" split with `agent`)
- `webdev`  (intersect of the "latest" split with `agent`)

## Aritifical Analysis API

Use `GET /api/v2/language/models/free` to retrieve full data for all "latest" split + `agent` subset of language models included in the LMArena dataset; Refresh twice a day through cron tasks.

# Important Notes
Take your time to plan out a good project structure for the implementation!