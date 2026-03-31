import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks

from app import job_dispatcher


class JobDispatcherTests(unittest.TestCase):
    def test_local_dispatch_without_background_tasks_runs_worker_immediately(self):
        job = {"order_id": "order-1"}

        with patch("app.job_dispatcher.get_webhook_dispatch_mode", return_value="local"):
            with patch("app.job_dispatcher.process_webhook_job") as mock_worker:
                job_dispatcher.dispatch_webhook_job(job)

        mock_worker.assert_called_once_with(job)

    def test_local_dispatch_with_background_tasks_enqueues_worker(self):
        background_tasks = BackgroundTasks()
        job = {"order_id": "order-2"}

        with patch("app.job_dispatcher.get_webhook_dispatch_mode", return_value="local"):
            job_dispatcher.dispatch_webhook_job(job, background_tasks=background_tasks)

        self.assertEqual(len(background_tasks.tasks), 1)

    def test_sqs_dispatch_mode_uses_sqs_dispatcher(self):
        with patch("app.job_dispatcher.get_webhook_dispatch_mode", return_value="sqs"):
            with patch("app.job_dispatcher.dispatch_webhook_job_to_sqs") as mock_sqs:
                job_dispatcher.dispatch_webhook_job({"order_id": "order-3"})

        mock_sqs.assert_called_once_with({"order_id": "order-3"})


if __name__ == "__main__":
    unittest.main()
