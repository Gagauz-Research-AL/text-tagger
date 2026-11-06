# text-tagger

## For humans

`text-tagger` is a focused human-review interface for sentence-level tagging. It gives reviewers a fast way to inspect ranked sentences, edit or add tags, and approve or reject items. It runs as a small proxy with a built-in Vue UI and persists the queue in a local JSON file.

Run it with Docker:

```bash
docker build -t text-tagger . && docker run -p 8000:8000 --name text-tagger-container text-tagger
```

Open <http://localhost:8000>. The upstream ranking service is expected at `http://host.docker.internal:9090`; map the host port your upstream service calls to the container port `8000`.

For local development:

```bash
BACKLOG_FILE=./backlog.json python3 server.py --host 127.0.0.1 --port 8000
```

Tests:

```bash
python3 -m unittest discover -v
node static/logic.test.js
```

---

## For LLM agents

### What this repository is

A dependency-light Python HTTP proxy and a static Vue 3 UI for reviewing sentence-level text-tagging tasks. It exposes a Label Studio-compatible subset needed by an upstream ranking service, stores tasks in a single JSON backlog, and sends review decisions back upstream.

No frontend build step is required. `static/index.html` loads Vue and the shared UI logic directly.

### Components

| Path | Purpose |
| --- | --- |
| `server.py` | HTTP server, static file serving, upstream proxy, API implementation |
| `backlog.py` | JSON persistence, idempotent imports, pagination, tags, status updates |
| `static/index.html` | Vue application and styling |
| `static/logic.js` | Pure edit/windowing/tag-formatting helpers |
| `static/logic.test.js` | Node test suite for `logic.js` |
| `tag_rules.json` | Configurable tag types removed before sending to upstream |
| `test_backlog.py` | Repository tests |
| `test_server.py` | HTTP/API/webhook tests |
| `test_mock_data.py` | Mock-data compatibility tests |
| `mock_data.py`, `tagger.py`, `cli.py` | Legacy/demo utilities, not used by the main UI |
| `integrate_with_ranker_server.md` | Historical integration notes |

### Persistence model

`JsonBacklogRepository` uses schema version `2`:

```json
{
  "schema_version": 2,
  "next_id": 1,
  "tasks": {
    "1": {
      "id": 1,
      "source_key": "[\"file.pdf\",\"0\",\"1\"]",
      "data": {
        "raw_text": "...",
        "file_name": "file.pdf",
        "page_nr": 0,
        "sentence_index": 1,
        "tags": [
          {
            "left_pos": 0,
            "right_pos": 5,
            "type": "spelling",
            "candidates": ["..."]
          }
        ]
      },
      "predictions": [],
      "status": "queued",
      "version": 1,
      "created_at": "ISO-8601",
      "updated_at": "ISO-8601"
    }
  }
}
```

Rules and invariants:

- IDs are proxy-assigned integers in arrival order.
- Imports are idempotent by `source_key`, derived from `file_name`, `page_nr`, and `sentence_index`.
- Duplicate source keys are skipped; existing task content and status are preserved.
- Tasks without those coordinates are accepted but cannot be deduplicated.
- Valid stored statuses: `queued`, `approved`, `skipped`.
- The UI label “Rejected” maps to stored status `skipped`.
- Tags are explicit metadata in `data.tags`; they are never inferred from prediction score.
- Tag offsets use `left_pos` inclusive and `right_pos` exclusive character offsets.
- Invalid, out-of-range, and overlapping tags are ignored during normalization.
- New batches are appended in arrival order. Prediction score is displayed but does not reorder the backlog.
- Writes use a lock and atomic file replacement.

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `BACKLOG_FILE` | `/app/backlog.json` | Backlog JSON path |
| `PAGE_SIZE` | `5` | UI rows per page |
| `PRELOAD_PAGES` | `2` | Pages held in the client window |
| `TAG_RULES_FILE` | `tag_rules.json` next to `server.py` | Tag filtering config |
| `RANKER_SERVER_URL` | hardcoded `http://host.docker.internal:9090` | Upstream base URL |

`WINDOW_SIZE = PAGE_SIZE * PRELOAD_PAGES`.

`tag_rules.json` contains `drop_on_send`, a list of case-insensitive tag type names. Matching tags are removed only from the upstream webhook payload. Proxy storage and UI retain them.

The server binds to `127.0.0.1:8000` by default when run directly. The Docker image binds to `0.0.0.0:8000`.

### HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Vue UI |
| `GET` | `/api/ui-config` | `page_size`, `preload_pages`, `window_size` |
| `GET` | `/api/jobs?offset=&limit=` | Window of job summaries |
| `GET` | `/api/jobs?limit=0` | Metadata only: totals, pending position, latest ID |
| `GET` | `/api/job/<id>` | Full job text and explicit tags |
| `GET` | `/api/score/<id>` | Fresh prediction score from upstream |
| `GET` | `/api/tag-types` | Unique tag types from approved tasks |
| `GET` | `/api/tasks?project=1` | Label Studio-compatible task list |
| `GET` | `/api/users/<id>` | Label Studio-compatible user lookup |
| `POST` | `/api/projects/<id>/import` | Import tasks; also accepts `/tasks` |
| `POST` | `/api/job/<id>/tags` | Replace explicit tags for a job |
| `POST` | `/api/result` | Approve, persist final text/tags, send webhook |
| `POST` | `/api/unapprove` | Return approved job to `queued` |
| `POST` | `/api/reopen` | Return rejected job to `queued` |
| `POST` | `/api/skip` | Reject job and notify upstream best-effort |
| `POST` | `/api/next-batch` | Ask upstream for more sentences |
| `POST` | `/api/token/refresh` | Static token-refresh stub |

`/api/jobs` without parameters returns all jobs for compatibility. Explicit `limit` values are capped at `WINDOW_SIZE`. `limit=0` is the cheap polling mode used by the UI.

### UI behavior

- The UI fetches `/api/ui-config` before loading jobs.
- Only the configured window is resident; navigation reports the full upstream page count.
- Jumping outside the loaded window replaces it. Locally edited, unapproved items are carried forward and pinned first.
- Reload opens the first pending item.
- The UI polls `/api/jobs?limit=0` every five seconds for new batches.
- Selecting an item refreshes its displayed score through `/api/score/<id>`.
- Selecting text opens the manual tag toolbar. Available types come from `/api/tag-types` (approved tasks only); custom types are supported.
- `tags left` is the sum of server `tag_count` values for resident pending jobs.
- Approving the final resident item loads the next window automatically. If no work remains, `/api/next-batch` is requested.

### Upstream integration

The upstream service is expected to be reachable at `RANKER_SERVER_URL` and expose:

- Label Studio-style task import into this proxy.
- `POST /predict` for score refresh.
- `POST /webhook` for approval/rejection updates.
- `POST /push` for fetching additional sentences.

Basic payloads sent upstream:

- Approval: curated final text plus `task.data.tags` and `annotation.tags`.
- Rejection: `status` choice `Rejected`, without tags.
- Score refresh: `POST /predict` with `tasks[].data.raw_text`.
- Batch request: repeated `POST /push` calls until the client window is refilled or the upstream queue is exhausted.

The proxy does not require the upstream service to understand tag metadata. Unsupported fields may be ignored upstream.

### Development guidance

- Preserve import idempotency and FIFO append order.
- Keep upstream-facing request/response shapes compatible with the existing tests.
- Do not infer tags from scores.
- Keep tag filtering limited to outbound webhook payloads unless explicitly changing the contract.
- Run both test suites after changes:
  ```bash
  python3 -m unittest discover -v
  node static/logic.test.js
  ```
- There is no frontend build step; edit `static/index.html` and `static/logic.js` directly.

### Known limitations

- No authentication or authorization; intended for a trusted network.
- Fixed project ID `1`.
- Single JSON-file store; not designed for multiple proxy instances sharing a backlog.
- Upstream base URL is hardcoded in `server.py`.
- Polling is fixed at five seconds.
- The token-refresh endpoint returns a placeholder value.
