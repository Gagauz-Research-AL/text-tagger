"""Persistent backlog storage for the Label Studio-compatible proxy."""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("backlog")

SOURCE_FIELDS = ("file_name", "page_nr", "sentence_index")
VALID_STATUSES = {"queued", "approved", "skipped"}


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_source_key(data):
    if not isinstance(data, dict):
        return None
    if any(field not in data or data[field] is None for field in SOURCE_FIELDS):
        return None
    values = [str(data[field]) for field in SOURCE_FIELDS]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def task_text(task):
    data = task.get("data") or {}
    text = data.get("raw_text")
    if not isinstance(text, str):
        text = data.get("original", "")
    return text if isinstance(text, str) else str(text)


def task_score(task):
    predictions = task.get("predictions") or []
    if not predictions or not isinstance(predictions[0], dict):
        return None
    score = predictions[0].get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return score


def _tag_offset(value):
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float):
            if not value.is_integer():
                return None
        return int(value)
    except (TypeError, ValueError):
        return None


def task_tags(task):
    data = task.get("data") or {}
    raw_tags = data.get("tags") if "tags" in data else data.get("underlines")
    if not isinstance(raw_tags, list):
        return []

    text = task_text(task)
    tags = []
    for raw in raw_tags:
        if not isinstance(raw, dict):
            continue
        bounds = raw.get("limit") if isinstance(raw.get("limit"), dict) else raw
        left = _tag_offset(bounds.get("left_pos"))
        right = _tag_offset(bounds.get("right_pos"))
        if left is None or right is None:
            continue
        if left < 0 or right <= left or right > len(text):
            continue
        candidates = raw.get("candidates")
        tags.append({
            "left_pos": left,
            "right_pos": right,
            "type": raw.get("type") if isinstance(raw.get("type"), str) else "",
            "candidates": [c for c in candidates if isinstance(c, str)] if isinstance(candidates, list) else [],
            "original": text[left:right],
        })

    tags.sort(key=lambda tag: tag["left_pos"])
    non_overlapping = []
    last_right = 0
    for tag in tags:
        if tag["left_pos"] < last_right:
            continue
        non_overlapping.append(tag)
        last_right = tag["right_pos"]
    return non_overlapping


def task_tag_count(task):
    return len(task_tags(task))


class JsonBacklogRepository:
    SCHEMA_VERSION = 2

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = {
            "schema_version": self.SCHEMA_VERSION,
            "next_id": 1,
            "tasks": {},
        }
        self._source_index = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.error("Failed to load backlog: %s", e)
            return
        if not isinstance(raw, dict):
            logger.error("Backlog root must be an object; ignoring %s", self.path)
            return

        if raw.get("schema_version") == self.SCHEMA_VERSION and isinstance(raw.get("tasks"), dict):
            self.data = {
                "schema_version": self.SCHEMA_VERSION,
                "next_id": raw.get("next_id", 1),
                "tasks": raw["tasks"],
            }
            changed = self._normalize_tasks()
        else:
            self._migrate_legacy(raw)
            changed = True

        self._rebuild_source_index()
        if changed:
            self._save_unlocked()

    def _normalize_tasks(self):
        changed = False
        tasks = {}
        max_id = 0
        for key, task in self.data["tasks"].items():
            if not isinstance(task, dict):
                changed = True
                continue
            try:
                tid = int(task.get("id", key))
            except (TypeError, ValueError):
                changed = True
                continue
            if task.get("id") != tid:
                task["id"] = tid
                changed = True
            for field, default in (
                ("data", {}),
                ("predictions", []),
                ("status", "queued"),
                ("version", 1),
            ):
                if field not in task:
                    task[field] = default
                    changed = True
            if not task.get("created_at"):
                task["created_at"] = task.get("updated_at") or utc_now()
                changed = True
            if not task.get("updated_at"):
                task["updated_at"] = task["created_at"]
                changed = True
            if "source_key" not in task:
                task["source_key"] = make_source_key(task["data"])
                changed = True
            tasks[str(tid)] = task
            max_id = max(max_id, tid)
        if len(tasks) != len(self.data["tasks"]):
            changed = True
        self.data["tasks"] = tasks
        try:
            next_id = int(self.data.get("next_id", 1))
        except (TypeError, ValueError):
            next_id = 1
        normalized_next_id = max(next_id, max_id + 1, 1)
        if normalized_next_id != next_id:
            changed = True
        self.data["next_id"] = normalized_next_id
        return changed

    def _migrate_legacy(self, raw):
        tasks = {}
        next_id = 1
        for key, record in raw.items():
            if not isinstance(record, dict):
                continue
            if isinstance(record.get("data"), dict):
                data = record["data"]
                predictions = record.get("predictions") or []
                source_key = record.get("source_key")
                created_at = record.get("created_at")
                updated_at = record.get("updated_at")
                status = record.get("status", "queued")
                version = record.get("version", 1)
            else:
                data = {"raw_text": record.get("text", "")}
                predictions = []
                source_key = None
                created_at = record.get("created_at") or record.get("updated_at")
                updated_at = record.get("updated_at") or created_at
                status = record.get("status", "queued")
                version = record.get("version", 1)

            tid = next_id
            next_id += 1
            tasks[str(tid)] = {
                "id": tid,
                "legacy_id": str(key),
                "source_key": source_key if source_key is not None else make_source_key(data),
                "data": data,
                "predictions": predictions if isinstance(predictions, list) else [],
                "status": status if status in VALID_STATUSES else "queued",
                "version": int(version) if isinstance(version, int) else 1,
                "created_at": created_at or utc_now(),
                "updated_at": updated_at or created_at or utc_now(),
            }
        self.data = {
            "schema_version": self.SCHEMA_VERSION,
            "next_id": next_id,
            "tasks": tasks,
        }

    def _rebuild_source_index(self):
        index = {}
        for key, task in self.data["tasks"].items():
            source_key = task.get("source_key")
            if source_key:
                index.setdefault(source_key, str(task.get("id", key)))
        self._source_index = index

    def _save_unlocked(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(f".{self.path.name}.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.path)
        except Exception as e:
            logger.error("Failed to save backlog: %s", e)

    def add_tasks(self, tasks):
        if not isinstance(tasks, list):
            raise ValueError("tasks must be a list")

        created = 0
        predictions_added = 0
        duplicates = 0
        skipped = 0
        task_ids = []
        now = utc_now()

        with self.lock:
            for item in tasks:
                if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
                    skipped += 1
                    logger.warning("Skipping import item without a data object")
                    continue

                data = item["data"]
                predictions = item.get("predictions")
                if not isinstance(predictions, list):
                    predictions = []

                source_key = make_source_key(data)
                if source_key is not None:
                    existing_id = self._source_index.get(source_key)
                    if existing_id is not None:
                        duplicates += 1
                        task_ids.append(int(existing_id) if str(existing_id).isdigit() else existing_id)
                        continue

                tid = int(self.data["next_id"])
                self.data["next_id"] = tid + 1
                self.data["tasks"][str(tid)] = {
                    "id": tid,
                    "source_key": source_key,
                    "data": data,
                    "predictions": predictions,
                    "status": "queued",
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                if source_key is not None:
                    self._source_index[source_key] = str(tid)
                created += 1
                predictions_added += len(predictions)
                task_ids.append(tid)

            if created:
                self._save_unlocked()

        if skipped:
            logger.warning("Import skipped %d malformed item(s)", skipped)
        logger.info(
            "Import created=%d duplicates=%d skipped=%d predictions=%d",
            created,
            duplicates,
            skipped,
            predictions_added,
        )
        return {
            "task_count": created,
            "predictions_count": predictions_added,
            "task_ids": task_ids,
            "duplicate_count": duplicates,
            "skipped_count": skipped,
        }

    def _sorted_tasks(self):
        def sort_key(item):
            key = str(item[0])
            return (0, int(key)) if key.isdigit() else (1, key)

        return [task for _, task in sorted(self.data["tasks"].items(), key=sort_key)]

    @staticmethod
    def _job_summary(task):
        return {
            "id": task["id"],
            "status": task.get("status", "queued"),
            "text": task_text(task),
            "score": task_score(task),
            "tag_count": task_tag_count(task),
        }

    def get_jobs(self):
        return self.get_jobs_window(0, None)[0]

    def get_jobs_window(self, offset, limit):
        with self.lock:
            tasks = self._sorted_tasks()
            total = len(tasks)
            start = max(0, offset)
            if limit is None:
                selected = tasks[start:]
            else:
                selected = tasks[start:start + max(0, limit)]

            first_pending_offset = next(
                (
                    index for index, task in enumerate(tasks)
                    if task.get("status", "queued") not in ("approved", "skipped")
                ),
                None,
            )
            latest_id = 0
            for task in tasks:
                try:
                    latest_id = max(latest_id, int(task.get("id")))
                except (TypeError, ValueError):
                    continue

            return (
                [self._job_summary(task) for task in selected],
                total,
                first_pending_offset,
                latest_id,
            )

    def get_job(self, job_id):
        with self.lock:
            task = self.data["tasks"].get(str(job_id))
            return dict(task) if task else None

    def get_tasks(self):
        with self.lock:
            tasks = [dict(task) for task in self._sorted_tasks()]
            total_annotations = sum(1 for task in tasks if task.get("status") == "approved")
            total_predictions = sum(len(task.get("predictions") or []) for task in tasks)
            return tasks, total_annotations, total_predictions

    def update_status(self, job_id, status):
        if status not in VALID_STATUSES:
            return False
        with self.lock:
            task = self.data["tasks"].get(str(job_id))
            if not task:
                return False
            task["status"] = status
            task["version"] = int(task.get("version", 1)) + 1
            task["updated_at"] = utc_now()
            self._save_unlocked()
            return True

    def get_approved_tag_types(self):
        with self.lock:
            types = set()
            for task in self.data["tasks"].values():
                if task.get("status") != "approved":
                    continue
                for tag in task_tags(task):
                    tag_type = tag.get("type")
                    if tag_type:
                        types.add(tag_type)
            return sorted(types, key=str.lower)

    def update_tags(self, job_id, tags):
        if not isinstance(tags, list):
            return None
        with self.lock:
            task = self.data["tasks"].get(str(job_id))
            if not task:
                return None
            data = task.get("data")
            if not isinstance(data, dict):
                data = {}
                task["data"] = data
            normalized = task_tags({"data": {**data, "tags": tags}})
            data["tags"] = normalized
            task["version"] = int(task.get("version", 1)) + 1
            task["updated_at"] = utc_now()
            self._save_unlocked()
            return normalized
