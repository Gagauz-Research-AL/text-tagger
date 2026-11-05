# Integration Plan: Text-Tagger <-> Ranker Server

## Goal
Connect the `text-tagger` frontend to the real `ranker_server` backend (Data Provider and Analytics Engine), replacing Label Studio as the labeling interface.

## Infrastructure
- **Port Alignment**: The `text-tagger` container will listen on the port defined as `LABEL_STUDIO_URL` in the `ranker_server` config. This allows the `ranker_server` to "push" tasks directly to the `text-tagger` proxy.

## 1. The Repository (State Management)
To maintain separation of concerns, a Repository pattern will be used to handle the backlog.

- **`IBacklogRepository`**: Interface defining `add_tasks`, `get_jobs`, `get_job`, and `update_status`.
- **`JsonBacklogRepository`**: Minimalist JSON implementation tracking:
    - `id`, `text`, `underlines`, `status`.
    - `updated_at`: Timestamp of the last modification.
    - `version`: Incrementing counter for edits.

## 2. The Proxy Implementation (`server.py`)
The `server.py` will act as a bridge between the `ranker_server` and the Vue UI.

### Incoming from Ranker Server (The "Push")
- **`POST /api/projects/{id}/tasks`**: 
    - Intercepts the `ranker_server`'s `import_tasks` call.
    - Parses the `ls_tasks` payload and persists them via the repository.

### Outgoing to UI (The "Fetch")
- **`GET /api/jobs`**: 
    - Returns the list of pending/reviewing jobs from the repository.
- **`GET /api/job/{id}`**: 
    - Fetches the job from the repository.
    - Calls `ranker_server`'s `/predict` endpoint to identify low-probability words and generates "low probability" underlines.

### Return Path (The "Feedback")
- **`POST /api/result`**: 
    - Updates the repository (status, `updated_at`, `version`).
    - Forwards the result to `ranker_server` via the `/webhook` endpoint (simulating a Label Studio notification) to trigger model retraining.

## 3. Verification Steps
1. **Connectivity**: Verify `ranker_server` can successfully push tasks to the proxy.
2. **Persistence**: Verify tasks are saved to and loaded from the JSON backlog.
3. **Analytics**: Verify that `/predict` is used to generate underlines in the UI.
4. **Loop Closure**: Verify that "Approve" in the UI triggers a `/webhook` call and updates the ranker's internal state.
