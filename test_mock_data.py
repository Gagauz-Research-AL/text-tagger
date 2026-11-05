"""Unit tests for the mock backlog payload."""

import unittest

from mock_data import generate_mock, generate_mock_jobs
from tagger import load_job


class MockDataTest(unittest.TestCase):
    def test_backlog_has_two_stable_jobs(self):
        jobs = generate_mock_jobs()
        self.assertEqual([j["id"] for j in jobs], ["txt-001", "txt-002"])

    def test_generate_mock_is_compatibility_alias(self):
        self.assertEqual(generate_mock()["id"], "txt-001")

    def test_backlog_spans_are_valid_and_preserve_originals(self):
        expected = {
            "txt-001": ["sitted", "the", "mat", "barked", "mailman"],
            "txt-002": ["their", "too", "whether"],
        }
        for raw in generate_mock_jobs():
            job = load_job(raw)
            self.assertEqual([u["original"] for u in job["underlines"]], expected[raw["id"]])

    def test_second_job_exposes_expected_candidates(self):
        job = load_job(generate_mock_jobs()[1])
        self.assertEqual(job["underlines"][0]["candidates"], ["they're", "there"])
        self.assertEqual(job["underlines"][1]["candidates"], ["to"])
        self.assertEqual(job["underlines"][2]["candidates"], ["weather"])


if __name__ == "__main__":
    unittest.main()
