import json
import tempfile
import unittest
from pathlib import Path

from backlog import (
    JsonBacklogRepository,
    make_source_key,
    task_tag_count,
    task_tags,
    task_text,
)


def make_task(file_name="doc.txt", page_nr=0, sentence_index=1, text="Hello world", **data_extra):
    data = {
        "original": text,
        "raw_text": text,
        "file_name": file_name,
        "page_nr": page_nr,
        "sentence_index": sentence_index,
        "total_sentences": 10,
        "file_line": f"{file_name} | page {page_nr}",
        "page_line": f"sentence {sentence_index}/10",
    }
    data.update(data_extra)
    return {
        "data": data,
        "predictions": [{
            "result": [],
            "score": 0.25,
            "model_version": "ranker_v1",
        }],
    }


class BacklogRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "backlog.json"
        self.repo = JsonBacklogRepository(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_preserves_full_data_and_assigns_numeric_id(self):
        task = make_task(extra_field={"nested": True})
        result = self.repo.add_tasks([task])

        self.assertEqual(result["task_count"], 1)
        self.assertEqual(result["predictions_count"], 1)
        self.assertEqual(result["task_ids"], [1])

        stored = self.repo.get_job(1)
        self.assertEqual(stored["id"], 1)
        self.assertEqual(stored["status"], "queued")
        self.assertEqual(stored["data"], task["data"])
        self.assertEqual(stored["source_key"], make_source_key(task["data"]))

    def test_duplicate_coordinates_skip_and_preserve_existing_task(self):
        self.repo.add_tasks([make_task(text="first")])
        self.repo.update_status(1, "approved")

        result = self.repo.add_tasks([make_task(text="second")])

        self.assertEqual(result["task_count"], 0)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["task_ids"], [1])
        stored = self.repo.get_job(1)
        self.assertEqual(task_text(stored), "first")
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["version"], 2)

    def test_coordinate_value_types_are_normalized(self):
        self.repo.add_tasks([make_task(page_nr=0, sentence_index=1, text="first")])
        result = self.repo.add_tasks([make_task(page_nr="0", sentence_index="1", text="second")])

        self.assertEqual(result["task_count"], 0)
        self.assertEqual(len(self.repo.get_jobs()), 1)

    def test_same_text_with_different_coordinates_is_stored(self):
        result = self.repo.add_tasks([
            make_task(sentence_index=1, text="same"),
            make_task(sentence_index=2, text="same"),
        ])

        self.assertEqual(result["task_count"], 2)
        self.assertEqual(len(self.repo.get_jobs()), 2)

    def test_missing_coordinates_are_accepted_without_deduplication(self):
        task = make_task()
        task["data"].pop("file_name")

        result = self.repo.add_tasks([task, task])

        self.assertEqual(result["task_count"], 2)
        self.assertIsNone(self.repo.get_job(1)["source_key"])
        self.assertIsNone(self.repo.get_job(2)["source_key"])

    def test_idempotency_survives_reload(self):
        self.repo.add_tasks([make_task()])

        reloaded = JsonBacklogRepository(self.path)
        result = reloaded.add_tasks([make_task()])

        self.assertEqual(result["task_count"], 0)
        self.assertEqual(len(reloaded.get_jobs()), 1)
        self.assertEqual(reloaded.get_job(1)["source_key"], make_source_key(make_task()["data"]))

    def test_separate_import_batches_append_in_fifo_order(self):
        self.repo.add_tasks([
            make_task(sentence_index=1, text="First"),
            make_task(sentence_index=2, text="Second"),
        ])
        self.repo.add_tasks([
            make_task(sentence_index=3, text="Third"),
            make_task(sentence_index=4, text="Fourth"),
        ])

        jobs = self.repo.get_jobs()

        self.assertEqual([job["id"] for job in jobs], [1, 2, 3, 4])
        self.assertEqual([job["text"] for job in jobs], ["First", "Second", "Third", "Fourth"])

    def test_get_tasks_reports_totals(self):
        self.repo.add_tasks([
            make_task(sentence_index=1),
            make_task(sentence_index=2),
        ])
        self.repo.update_status(1, "approved")

        tasks, total_annotations, total_predictions = self.repo.get_tasks()

        self.assertEqual(len(tasks), 2)
        self.assertEqual(total_annotations, 1)
        self.assertEqual(total_predictions, 2)
        self.assertTrue(tasks[0]["data"]["raw_text"])

    def test_legacy_backlog_is_migrated(self):
        legacy = {
            "job-101": {
                "id": "job-101",
                "text": "Legacy text",
                "status": "approved",
                "version": 2,
                "updated_at": "2026-11-05T17:13:35.572731",
            },
            "job-201": {
                "id": "job-201",
                "text": "Second legacy text",
                "status": "queued",
                "version": 1,
                "updated_at": "2026-11-05T17:14:55.197649",
            },
        }
        self.path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = JsonBacklogRepository(self.path)
        jobs = migrated.get_jobs()

        self.assertEqual([job["id"] for job in jobs], [1, 2])
        self.assertEqual(jobs[0]["status"], "approved")
        self.assertEqual(migrated.get_job(1)["legacy_id"], "job-101")
        self.assertEqual(task_text(migrated.get_job(1)), "Legacy text")

    def test_explicit_tags_are_counted_and_normalized(self):
        task = make_task(text="Hello world", tags=[
            {"limit": {"left_pos": 6, "right_pos": 11}, "type": "spelling", "candidates": ["earth", "planet"]},
            {"left_pos": 0, "right_pos": 5, "type": "phrasing"},
        ])
        self.repo.add_tasks([task])

        stored = self.repo.get_job(1)
        tags = task_tags(stored)

        self.assertEqual([(tag["left_pos"], tag["right_pos"]) for tag in tags], [(0, 5), (6, 11)])
        self.assertEqual(tags[1]["original"], "world")
        self.assertEqual(tags[1]["candidates"], ["earth", "planet"])
        self.assertEqual(task_tag_count(stored), 2)

    def test_invalid_and_overlapping_tags_are_ignored(self):
        task = make_task(text="Hello world", tags=[
            {"left_pos": 0, "right_pos": 5},
            {"left_pos": 3, "right_pos": 8},
            {"left_pos": -1, "right_pos": 2},
            {"left_pos": 0, "right_pos": 99},
            {"left_pos": "6", "right_pos": "11", "candidates": ["earth", 1]},
        ])
        self.repo.add_tasks([task])

        tags = task_tags(self.repo.get_job(1))

        self.assertEqual([(tag["left_pos"], tag["right_pos"]) for tag in tags], [(0, 5), (6, 11)])
        self.assertEqual(tags[1]["candidates"], ["earth"])

    def test_tags_are_not_inferred_from_prediction_score(self):
        task = make_task()
        task["predictions"][0]["score"] = 0.0
        self.repo.add_tasks([task])

        self.assertEqual(task_tag_count(self.repo.get_job(1)), 0)

    def test_non_list_import_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.add_tasks({"tasks": []})


if __name__ == "__main__":
    unittest.main()
