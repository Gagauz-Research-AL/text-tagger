import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backlog import JsonBacklogRepository, task_tags, task_text, utc_now

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("proxy")

ROOT = Path(__file__).parent / "static"
RANKER_SERVER_URL = "http://host.docker.internal:9090"
PROJECT_ID = "1"
PROJECT_ID_INT = int(PROJECT_ID)
ANNOTATOR_ID = 1
BACKLOG_FILE = Path(os.environ.get("BACKLOG_FILE", "/app/backlog.json"))


def _positive_int_env(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if value < 1:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    return value


PAGE_SIZE = _positive_int_env("PAGE_SIZE", 5)
PRELOAD_PAGES = _positive_int_env("PRELOAD_PAGES", 2)
WINDOW_SIZE = PAGE_SIZE * PRELOAD_PAGES
logger.info(
    "UI pagination: page_size=%d, preload_pages=%d, window_size=%d",
    PAGE_SIZE,
    PRELOAD_PAGES,
    WINDOW_SIZE,
)

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
}

repo = JsonBacklogRepository(BACKLOG_FILE)


def proxy_request(path, method="GET", data=None, timeout=5):
    url = f"{RANKER_SERVER_URL}{path}"
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"Proxy request failed for {url}: {e}")
        return 500, {"error": str(e)}


def build_webhook_payload(job, final_text):
    try:
        task_id = int(job["id"])
    except (TypeError, ValueError):
        task_id = job["id"]

    now = utc_now()
    return {
        "project": {"id": PROJECT_ID_INT, "title": "text-tagger"},
        "action": "ANNOTATION_CREATED",
        "task": {
            "id": task_id,
            "data": job.get("data") or {},
            "project": PROJECT_ID_INT,
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        },
        "annotation": {
            "id": task_id,
            "task": task_id,
            "project": PROJECT_ID_INT,
            "completed_by": ANNOTATOR_ID,
            "result": [{
                "from_name": "curated",
                "to_name": "original",
                "type": "textarea",
                "value": {"text": [final_text]},
            }],
            "was_cancelled": False,
            "ground_truth": False,
            "created_at": now,
            "updated_at": now,
        },
    }


def ls_task(task):
    predictions = task.get("predictions") or []
    approved = task.get("status") == "approved"
    return {
        "id": task.get("id"),
        "data": task.get("data") or {},
        "predictions": predictions,
        "project": PROJECT_ID_INT,
        "is_labeled": approved,
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "total_annotations": 1 if approved else 0,
        "total_predictions": len(predictions),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj), "application/json; charset=utf-8")

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/" or path == "/index.html":
            self._serve_file("index.html")
        elif path == "/api/ui-config":
            self._json(200, {
                "page_size": PAGE_SIZE,
                "preload_pages": PRELOAD_PAGES,
                "window_size": WINDOW_SIZE,
            })
        elif path == "/api/jobs":
            params = self._query()
            if "offset" in params or "limit" in params:
                try:
                    offset = max(0, int(params.get("offset", ["0"])[0]))
                except (TypeError, ValueError):
                    offset = 0
                try:
                    limit = int(params.get("limit", [str(WINDOW_SIZE)])[0])
                except (TypeError, ValueError):
                    limit = WINDOW_SIZE
                if limit < 0:
                    limit = WINDOW_SIZE
                limit = min(limit, WINDOW_SIZE)
            else:
                offset = 0
                limit = None

            jobs, total, first_pending_offset, latest_id = repo.get_jobs_window(offset, limit)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            first_pending_page = (
                None if first_pending_offset is None
                else first_pending_offset // PAGE_SIZE
            )
            self._json(200, {
                "jobs": jobs,
                "total": total,
                "offset": offset,
                "limit": total if limit is None else limit,
                "total_pages": total_pages,
                "first_pending_offset": first_pending_offset,
                "first_pending_page": first_pending_page,
                "latest_id": latest_id,
            })
        elif path.startswith("/api/score/"):
            job_id = path.split("/")[-1]
            job_data = repo.get_job(job_id)
            if not job_data:
                self._json(404, {"error": "job not found"})
                return

            payload = {"tasks": [{"data": {"raw_text": task_text(job_data)}}]}
            code, predict_data = proxy_request("/predict", "POST", payload)
            if code != 200 or not isinstance(predict_data, dict):
                self._json(502, {"error": "ranker prediction failed", "ranker_status": code})
                return

            results = predict_data.get("results")
            score = results[0].get("score") if isinstance(results, list) and results else None
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                self._json(502, {"error": "ranker returned no score"})
                return

            self._json(200, {"id": job_data["id"], "score": score})
        elif path.startswith("/api/job/"):
            job_id = path.split("/")[-1]
            job_data = repo.get_job(job_id)
            if not job_data:
                self._json(404, {"error": "job not found"})
                return

            self._json(200, {
                "id": job_data["id"],
                "text": task_text(job_data),
                "underlines": task_tags(job_data),
            })
        elif path == "/api/tasks":
            params = self._query()
            project = params.get("project", [None])[0]
            if project not in (None, "", PROJECT_ID):
                self._json(200, {
                    "tasks": [],
                    "total": 0,
                    "total_annotations": 0,
                    "total_predictions": 0,
                })
                return

            tasks, total_annotations, total_predictions = repo.get_tasks()
            total = len(tasks)
            try:
                page = max(1, int(params.get("page", ["1"])[0]))
            except (TypeError, ValueError):
                page = 1

            page_size = None
            if "page_size" in params:
                try:
                    page_size = max(0, int(params["page_size"][0]))
                except (TypeError, ValueError):
                    page_size = None

            if page_size is not None:
                start = (page - 1) * page_size
                page_tasks = tasks[start:start + page_size]
            else:
                page_tasks = tasks if page == 1 else []

            self._json(200, {
                "tasks": [ls_task(task) for task in page_tasks],
                "total": total,
                "total_annotations": total_annotations,
                "total_predictions": total_predictions,
            })
        elif path.startswith("/api/users/"):
            user_id = path.split("/")[-1]
            if str(user_id) != str(ANNOTATOR_ID):
                self._json(404, {"error": "user not found"})
                return
            self._json(200, {
                "id": ANNOTATOR_ID,
                "username": "annotator",
                "first_name": "Annotator",
                "last_name": "",
                "email": "annotator@example.com",
                "initials": "A",
                "avatar": None,
                "phone": "",
                "active_organization": 1,
                "last_activity": "2026-01-01T00:00:00Z",
                "date_joined": "2026-01-01T00:00:00Z",
            })
        elif path.startswith("/static/"):
            self._serve_file(path.removeprefix("/static/"))
        else:
            self._send(404, "not found")

    def do_POST(self):
        try:
            path = self.path.split("?", 1)[0].rstrip("/")
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw_data = self.rfile.read(length) if length else b""
            try:
                raw = json.loads(raw_data) if raw_data else {}
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return

            logger.info(f"POST {path} received")

            if path == "/api/token/refresh":
                logger.info("Intercepted token refresh request")
                self._json(200, {"access": "your-personal-access-token-or-refresh-string"})
                return

            if path == "/api/next-batch":
                pushed = 0
                message = ""
                for _ in range(WINDOW_SIZE):
                    code, response = proxy_request("/push", "POST", {})
                    if code != 200 or not isinstance(response, dict):
                        message = f"ranker push failed with status {code}"
                        break
                    if response.get("result") != "ok":
                        message = response.get("message") or "ranker push failed"
                        break
                    step_message = str(response.get("message", ""))
                    if "No undispatched" in step_message:
                        message = step_message
                        break
                    pushed += 1

                _, total, _, _ = repo.get_jobs_window(0, 0)
                logger.info("Requested next batch: pushed=%d total=%d message=%s", pushed, total, message)
                self._json(200, {
                    "pushed": pushed,
                    "total": total,
                    "message": message or f"pushed {pushed} sentences",
                })
                return

            if path in ("/api/result", "/api/unapprove", "/api/reopen", "/api/skip") and not isinstance(raw, dict):
                self._json(400, {"error": "expected a JSON object"})
                return

            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] in ("import", "tasks"):
                started = time.perf_counter()
                tasks = raw if isinstance(raw, list) else raw.get("tasks") if isinstance(raw, dict) else None
                if not isinstance(tasks, list):
                    self._json(400, {"error": "expected a task list"})
                    return

                result = repo.add_tasks(tasks)
                body = {
                    "task_count": result["task_count"],
                    "annotation_count": 0,
                    "predictions_count": result["predictions_count"],
                    "duration": round(time.perf_counter() - started, 6),
                }
                return_ids = self._query().get("return_task_ids", ["false"])[0].lower() == "true"
                if return_ids:
                    body["task_ids"] = result["task_ids"]
                self._json(201, body)
                return

            if path == "/api/result":
                job_id = raw.get("id")
                final_text = raw.get("text")
                if job_id is None or not isinstance(final_text, str):
                    self._json(400, {"error": "id and text are required"})
                    return

                job = repo.get_job(job_id)
                if not job:
                    self._json(404, {"error": "job not found"})
                    return

                code, resp = proxy_request("/webhook", "POST", build_webhook_payload(job, final_text))
                if 200 <= code < 300:
                    repo.update_status(job_id, "approved")
                    self._json(200, {"status": "saved", "id": job["id"]})
                else:
                    self._json(code if code >= 400 else 502, {
                        "status": "error",
                        "id": job["id"],
                        "ranker_status": code,
                        "detail": resp,
                    })
                return

            if path in ("/api/unapprove", "/api/reopen", "/api/skip"):
                job_id = raw.get("id")
                status = "skipped" if path == "/api/skip" else "queued"
                if not repo.update_status(job_id, status):
                    self._json(404, {"error": "job not found"})
                    return
                self._json(200, {"status": "queued" if status == "queued" else "skipped", "id": job_id})
                return

            logger.warning(f"Unhandled POST path: {path}")
            self._json(404, {"error": "not found", "path": path})
        except Exception as e:
            logger.error(f"Error in do_POST: {e}")
            self._json(500, {"error": str(e)})

    def _serve_file(self, name):
        f = (ROOT / name).resolve()
        if not str(f).startswith(str(ROOT.resolve())) or not f.is_file():
            self._send(404, "not found")
            return
        ctype = TYPES.get(f.suffix, "application/octet-stream")
        self._send(200, f.read_bytes(), ctype)

    def log_message(self, fmt, *args):
        pass


def trigger_setup():
    time.sleep(0.2)
    try:
        logger.info(f"Triggering ranker_server setup for project {PROJECT_ID}...")
        code, response = proxy_request("/setup", "POST", {"project": PROJECT_ID}, timeout=30)
        if 200 <= code < 300:
            logger.info("Ranker server setup triggered successfully")
        else:
            logger.error(f"Ranker server setup failed with status {code}: {response}")
    except Exception as e:
        logger.error(f"Failed to trigger ranker_server setup: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    print(f"text-tagger UI on http://{args.host}:{args.port} (Proxying to {RANKER_SERVER_URL})", flush=True)
    threading.Thread(target=trigger_setup, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
