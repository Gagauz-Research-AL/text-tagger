import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server
from backlog import JsonBacklogRepository


def make_task(file_name="doc.txt", page_nr=0, sentence_index=1, text="Hello world"):
    return {
        "data": {
            "original": text,
            "raw_text": text,
            "file_name": file_name,
            "page_nr": page_nr,
            "sentence_index": sentence_index,
            "total_sentences": 10,
            "file_line": f"{file_name} | page {page_nr + 1}",
            "page_line": f"sentence {sentence_index}/10",
        },
        "predictions": [{
            "result": [],
            "score": 0.25,
            "model_version": "ranker_v1",
        }],
    }


class ServerEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "backlog.json"
        server.repo = JsonBacklogRepository(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, path, payload=None):
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.getcode(), json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            return e.code, json.loads(body) if body else {}

    def test_ui_config_endpoint_returns_pagination_settings(self):
        status, body = self.request("GET", "/api/ui-config")

        self.assertEqual(status, 200)
        self.assertEqual(body["page_size"], server.PAGE_SIZE)
        self.assertEqual(body["preload_pages"], server.PRELOAD_PAGES)
        self.assertEqual(body["window_size"], server.PAGE_SIZE * server.PRELOAD_PAGES)

    def test_positive_int_env_accepts_overrides_and_rejects_invalid_values(self):
        with patch.dict(os.environ, {"PAGE_SIZE": "7"}):
            self.assertEqual(server._positive_int_env("PAGE_SIZE", 5), 7)

        for invalid in ("0", "-1", "abc", ""):
            with self.subTest(value=invalid):
                with patch.dict(os.environ, {"PAGE_SIZE": invalid}):
                    with self.assertLogs("proxy", level="WARNING"):
                        self.assertEqual(server._positive_int_env("PAGE_SIZE", 5), 5)

    def test_import_batches_are_returned_in_fifo_order(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1, text="First"),
            make_task(sentence_index=2, text="Second"),
        ])
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=3, text="Third"),
            make_task(sentence_index=4, text="Fourth"),
        ])

        status, body = self.request("GET", "/api/jobs?offset=0&limit=10")

        self.assertEqual(status, 200)
        self.assertEqual([job["id"] for job in body["jobs"]], [1, 2, 3, 4])
        self.assertEqual(
            [job["text"] for job in body["jobs"]],
            ["First", "Second", "Third", "Fourth"],
        )

    def test_import_preserves_incoming_order_not_score_order(self):
        first = make_task(sentence_index=1, text="First")
        first["predictions"][0]["score"] = 0.1
        second = make_task(sentence_index=2, text="Second")
        second["predictions"][0]["score"] = 0.9

        self.request("POST", "/api/projects/1/import", [first, second])

        status, body = self.request("GET", "/api/jobs?offset=0&limit=10")

        self.assertEqual(status, 200)
        self.assertEqual([job["text"] for job in body["jobs"]], ["First", "Second"])

    def test_jobs_window_supports_offset_limit_and_caps(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1),
            make_task(sentence_index=2),
            make_task(sentence_index=3),
            make_task(sentence_index=4),
        ])

        status, body = self.request("GET", "/api/jobs?offset=1&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 4)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["limit"], 2)
        self.assertEqual([job["id"] for job in body["jobs"]], [2, 3])

        with patch.object(server, "WINDOW_SIZE", 2):
            status, body = self.request("GET", "/api/jobs?offset=0&limit=99")
        self.assertEqual(status, 200)
        self.assertEqual(body["limit"], 2)
        self.assertEqual(len(body["jobs"]), 2)

    def test_jobs_response_includes_backend_pagination_metadata(self):
        status, body = self.request("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(body["jobs"], [])
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["total_pages"], 1)
        self.assertIsNone(body["first_pending_offset"])
        self.assertIsNone(body["first_pending_page"])
        self.assertEqual(body["latest_id"], 0)

        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1),
            make_task(sentence_index=2),
            make_task(sentence_index=3),
        ])
        server.repo.update_status(1, "approved")
        server.repo.update_status(2, "skipped")

        with patch.object(server, "PAGE_SIZE", 2):
            status, body = self.request("GET", "/api/jobs?offset=0&limit=0")

        self.assertEqual(status, 200)
        self.assertEqual(body["jobs"], [])
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["total_pages"], 2)
        self.assertEqual(body["first_pending_offset"], 2)
        self.assertEqual(body["first_pending_page"], 1)
        self.assertEqual(body["latest_id"], 3)
        self.assertEqual(body["limit"], 0)

        server.repo.update_status(3, "approved")
        status, body = self.request("GET", "/api/jobs?limit=0")
        self.assertEqual(status, 200)
        self.assertIsNone(body["first_pending_offset"])
        self.assertIsNone(body["first_pending_page"])

    def test_jobs_expose_score_and_explicit_tag_count(self):
        task = make_task(text="Hello world", sentence_index=1)
        task["data"]["tags"] = [{"left_pos": 0, "right_pos": 5, "type": "spelling"}]
        task["predictions"][0]["score"] = 0.75
        self.request("POST", "/api/projects/1/import", [task])

        status, body = self.request("GET", "/api/jobs")

        self.assertEqual(status, 200)
        self.assertEqual(body["jobs"][0]["score"], 0.75)
        self.assertEqual(body["jobs"][0]["tag_count"], 1)

    def test_job_uses_only_explicit_tags(self):
        tagged = make_task(text="Hello world", sentence_index=1)
        tagged["data"]["tags"] = [{"left_pos": 0, "right_pos": 5, "type": "spelling"}]
        tagged["predictions"][0]["score"] = 0.99
        untagged = make_task(text="Second sentence", sentence_index=2)
        untagged["predictions"][0]["score"] = 0.01
        self.request("POST", "/api/projects/1/import", [tagged, untagged])

        with patch.object(server, "proxy_request", side_effect=AssertionError("predict must not be called")):
            status, tagged_body = self.request("GET", "/api/job/1")
            status_untagged, untagged_body = self.request("GET", "/api/job/2")

        self.assertEqual(status, 200)
        self.assertEqual(status_untagged, 200)
        self.assertEqual([(u["left_pos"], u["right_pos"]) for u in tagged_body["underlines"]], [(0, 5)])
        self.assertEqual(tagged_body["underlines"][0]["original"], "Hello")
        self.assertEqual(untagged_body["underlines"], [])

    def test_next_batch_pushes_until_ranker_is_exhausted(self):
        responses = [
            (200, {"result": "ok", "message": "Pushed 1 sentence"}),
            (200, {"result": "ok", "message": "No undispatched sentences remaining"}),
        ]
        with patch.object(server, "proxy_request", side_effect=responses) as proxy:
            status, body = self.request("POST", "/api/next-batch")

        self.assertEqual(status, 200)
        self.assertEqual(body["pushed"], 1)
        self.assertEqual(proxy.call_count, 2)
        self.assertEqual(proxy.call_args_list[0].args, ("/push", "POST", {}))

    def test_next_batch_stops_at_window_size(self):
        with patch.object(server, "WINDOW_SIZE", 2):
            with patch.object(
                server,
                "proxy_request",
                return_value=(200, {"result": "ok", "message": "Pushed 1 sentence"}),
            ) as proxy:
                status, body = self.request("POST", "/api/next-batch")

        self.assertEqual(status, 200)
        self.assertEqual(body["pushed"], 2)
        self.assertEqual(proxy.call_count, 2)

    def test_score_endpoint_refreshes_from_ranker(self):
        self.request("POST", "/api/projects/1/import", [make_task(text="Original text")])
        captured = {}

        def fake_proxy(path, method="GET", data=None):
            captured["path"] = path
            captured["method"] = method
            captured["payload"] = data
            return 200, {"results": [{"score": 0.91}]}

        with patch.object(server, "proxy_request", side_effect=fake_proxy):
            status, body = self.request("GET", "/api/score/1")

        self.assertEqual(status, 200)
        self.assertEqual(body, {"id": 1, "score": 0.91})
        self.assertEqual(captured["path"], "/predict")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"]["tasks"][0]["data"]["raw_text"], "Original text")

        status, _ = self.request("GET", "/api/score/999")
        self.assertEqual(status, 404)

        with patch.object(server, "proxy_request", return_value=(502, {"error": "down"})):
            status, _ = self.request("GET", "/api/score/1")
        self.assertEqual(status, 502)

    def test_import_is_idempotent_and_supports_task_ids(self):
        status, body = self.request("POST", "/api/projects/1/import", [make_task()])
        self.assertEqual(status, 201)
        self.assertEqual(body["task_count"], 1)
        self.assertEqual(body["predictions_count"], 1)

        status, body = self.request("POST", "/api/projects/1/import?return_task_ids=true", [make_task()])
        self.assertEqual(status, 201)
        self.assertEqual(body["task_count"], 0)
        self.assertEqual(body["task_ids"], [1])

    def test_legacy_tasks_route_uses_standard_response(self):
        status, body = self.request("POST", "/api/projects/1/tasks", [make_task()])
        self.assertEqual(status, 201)
        self.assertEqual(body["task_count"], 1)
        self.assertIn("predictions_count", body)
        self.assertNotIn("count", body)

    def test_task_list_includes_all_statuses_and_original_data(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1, text="First"),
            make_task(sentence_index=2, text="Second"),
        ])
        server.repo.update_status(1, "approved")
        server.repo.update_status(2, "skipped")

        status, body = self.request("GET", "/api/tasks?project=1")

        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["total_annotations"], 1)
        self.assertEqual(body["total_predictions"], 2)
        self.assertEqual(body["tasks"][0]["data"]["raw_text"], "First")
        self.assertTrue(body["tasks"][0]["is_labeled"])
        self.assertEqual(body["tasks"][1]["data"]["raw_text"], "Second")

    def test_task_list_paginates_when_page_size_is_supplied(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1),
            make_task(sentence_index=2),
        ])

        status, body = self.request("GET", "/api/tasks?project=1&page_size=1&page=2")

        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["tasks"]), 1)
        self.assertEqual(body["tasks"][0]["data"]["sentence_index"], 2)

    def test_task_list_returns_all_tasks_on_first_page_by_default(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1),
            make_task(sentence_index=2),
        ])

        status, body = self.request("GET", "/api/tasks?project=1&page=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["tasks"]), 2)

        status, body = self.request("GET", "/api/tasks?project=1&page=2")
        self.assertEqual(status, 200)
        self.assertEqual(body["tasks"], [])
        self.assertEqual(body["total"], 2)

    def test_reopen_persists_queued_status(self):
        self.request("POST", "/api/projects/1/import", [make_task()])
        server.repo.update_status(1, "skipped")

        status, body = self.request("POST", "/api/reopen", {"id": 1})

        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "queued", "id": 1})
        self.assertEqual(server.repo.get_job(1)["status"], "queued")

    def test_jobs_use_persisted_statuses(self):
        self.request("POST", "/api/projects/1/import", [
            make_task(sentence_index=1, text="First"),
            make_task(sentence_index=2, text="Second"),
        ])
        server.repo.update_status(1, "approved")

        status, body = self.request("GET", "/api/jobs")

        self.assertEqual(status, 200)
        self.assertEqual(body["jobs"][0]["status"], "approved")
        self.assertEqual(body["jobs"][1]["status"], "queued")
        self.assertEqual(body["jobs"][1]["text"], "Second")

    def test_users_endpoint_resolves_annotator(self):
        status, body = self.request("GET", "/api/users/1/")

        self.assertEqual(status, 200)
        self.assertEqual(body["id"], 1)
        self.assertEqual(body["username"], "annotator")

        status, _ = self.request("GET", "/api/users/2/")
        self.assertEqual(status, 404)

    def test_load_drop_tags_reads_config_and_lowercases(self):
        path = Path(self.tmp.name) / "tag_rules.json"
        path.write_text(json.dumps({"drop_on_send": ["Hyphenated", "romanism"]}), encoding="utf-8")

        self.assertEqual(server.load_drop_tags(path), {"hyphenated", "romanism"})

    def test_tag_types_endpoint_returns_approved_types_only(self):
        tagged = make_task(text="Hello world", sentence_index=1)
        tagged["data"]["tags"] = [{"left_pos": 0, "right_pos": 5, "type": "approved-type"}]
        pending = make_task(text="Second sentence", sentence_index=2)
        pending["data"]["tags"] = [{"left_pos": 0, "right_pos": 6, "type": "pending-type"}]
        self.request("POST", "/api/projects/1/import", [tagged, pending])
        server.repo.update_status(1, "approved")

        status, body = self.request("GET", "/api/tag-types")

        self.assertEqual(status, 200)
        self.assertEqual(body["tag_types"], ["approved-type"])

    def test_webhook_drops_configured_tag_types(self):
        self.request("POST", "/api/projects/1/import", [make_task(text="Hello world")])
        captured = {}

        def fake_proxy(path, method="GET", data=None):
            captured["payload"] = data
            return 200, {"result": "ok"}

        tags = [
            {"left_pos": 0, "right_pos": 5, "type": "hyphenated"},
            {"left_pos": 6, "right_pos": 11, "type": "spelling"},
        ]
        with patch.object(server, "DROP_TAGS", {"hyphenated"}):
            with patch.object(server, "proxy_request", side_effect=fake_proxy):
                status, _ = self.request("POST", "/api/result", {
                    "id": 1, "text": "Hello world", "tags": tags,
                })

        self.assertEqual(status, 200)
        self.assertEqual(
            [tag["type"] for tag in captured["payload"]["annotation"]["tags"]],
            ["spelling"],
        )
        self.assertEqual(
            [tag["type"] for tag in captured["payload"]["task"]["data"]["tags"]],
            ["spelling"],
        )
        self.assertEqual(len(server.repo.get_job(1)["data"]["tags"]), 2)

    def test_skip_sends_rejected_webhook_without_tags(self):
        task = make_task(text="Hello world")
        task["data"]["tags"] = [{"left_pos": 0, "right_pos": 5, "type": "spelling"}]
        self.request("POST", "/api/projects/1/import", [task])
        captured = {}

        def fake_proxy(path, method="GET", data=None, timeout=5):
            captured["path"] = path
            captured["payload"] = data
            captured["timeout"] = timeout
            return 200, {"result": "ok"}

        with patch.object(server, "proxy_request", side_effect=fake_proxy):
            status, body = self.request("POST", "/api/skip", {"id": 1})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "skipped")
        self.assertEqual(captured["path"], "/webhook")
        self.assertEqual(
            captured["payload"]["annotation"]["result"][0]["value"]["choices"],
            ["Rejected"],
        )
        self.assertNotIn("tags", captured["payload"]["annotation"])
        self.assertNotIn("tags", captured["payload"]["task"]["data"])
        self.assertEqual(server.repo.get_job(1)["status"], "skipped")

    def test_job_tags_endpoint_persists_normalized_tags(self):
        self.request("POST", "/api/projects/1/import", [make_task(text="Hello world")])

        status, body = self.request("POST", "/api/job/1/tags", {
            "tags": [{"left_pos": 0, "right_pos": 5, "type": "manual"}],
        })

        self.assertEqual(status, 200)
        self.assertEqual(body["tag_count"], 1)
        self.assertEqual(body["tags"][0]["type"], "manual")
        self.assertEqual(body["tags"][0]["original"], "Hello")

        status, job = self.request("GET", "/api/job/1")
        self.assertEqual(status, 200)
        self.assertEqual(len(job["underlines"]), 1)
        self.assertEqual(job["underlines"][0]["type"], "manual")

        status, jobs = self.request("GET", "/api/jobs?offset=0&limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(jobs["jobs"][0]["tag_count"], 1)

    def test_result_webhook_includes_explicit_tags(self):
        self.request("POST", "/api/projects/1/import", [make_task(text="Hello world")])
        captured = {}

        def fake_proxy(path, method="GET", data=None):
            captured["payload"] = data
            return 200, {"result": "ok"}

        with patch.object(server, "proxy_request", side_effect=fake_proxy):
            status, _ = self.request("POST", "/api/result", {
                "id": 1,
                "text": "Hello world",
                "tags": [{"left_pos": 0, "right_pos": 5, "type": "manual"}],
            })

        self.assertEqual(status, 200)
        self.assertEqual(captured["payload"]["annotation"]["tags"][0]["type"], "manual")
        self.assertEqual(server.repo.get_job(1)["data"]["tags"][0]["type"], "manual")

    def test_result_webhook_echoes_original_metadata(self):
        self.request("POST", "/api/projects/1/import", [make_task(text="Original text")])
        captured = {}

        def fake_proxy(path, method="GET", data=None):
            captured["path"] = path
            captured["method"] = method
            captured["payload"] = data
            return 200, {"result": "ok"}

        with patch.object(server, "proxy_request", side_effect=fake_proxy):
            status, body = self.request("POST", "/api/result", {"id": 1, "text": "Edited text"})

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "saved")
        self.assertEqual(captured["path"], "/webhook")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"]["task"]["data"]["raw_text"], "Original text")
        self.assertEqual(captured["payload"]["annotation"]["result"][0]["value"]["text"], ["Edited text"])
        self.assertEqual(captured["payload"]["annotation"]["completed_by"], 1)
        self.assertEqual(captured["payload"]["project"]["id"], 1)
        self.assertEqual(server.repo.get_job(1)["status"], "approved")

    def test_result_keeps_status_when_ranker_rejects(self):
        self.request("POST", "/api/projects/1/import", [make_task()])

        with patch.object(server, "proxy_request", return_value=(500, {"error": "down"})):
            status, _ = self.request("POST", "/api/result", {"id": 1, "text": "Edited"})

        self.assertEqual(status, 500)
        self.assertEqual(server.repo.get_job(1)["status"], "queued")


if __name__ == "__main__":
    unittest.main()
