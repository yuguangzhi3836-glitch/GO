import json
import os
import shutil
import tempfile
import unittest

os.environ["GOAI_DATA_DIR"] = tempfile.mkdtemp(prefix="goai-m2-test-")
os.environ["DEEPSEEK_API_KEY"] = ""

from app import app, db, now
from test_task_routing import draft


class CommandOnlyTaskDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with db() as connection:
            connection.execute("INSERT INTO users(id,name,role,created_at,active) VALUES(?,?,?,?,1)", ("owner", "测试负责人", "owner", now()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(os.environ["GOAI_DATA_DIR"], ignore_errors=True)

    def client(self):
        client = app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = "owner"
        return client

    def test_post_is_recorded_but_never_executed(self):
        response = self.client().post("/api/tasks", json={"body": "讨论一下测试方案", "source": "manual"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "classifying")
        health = self.client().get("/healthz").get_json()
        self.assertFalse(health["execution_enabled"])

    def test_draft_can_be_updated_confirmed_and_cancelled_without_execution(self):
        with db() as connection:
            connection.execute("INSERT INTO tasks(id,body,source,status,created_by,created_at) VALUES(?,?,?,?,?,?)", ("GO-9001", "任务原文", "manual", "task_candidate", "owner", now()))
            connection.execute("INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)", ("GO-9001", "human", "任务原文", "owner", now()))
            connection.execute("INSERT INTO task_drafts(id,source_task_id,status,analysis_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", ("DRAFT-test", "GO-9001", "draft", json.dumps(draft()), "owner", now(), now()))
        response = self.client().patch("/api/task-drafts/DRAFT-test", json={"analysis": draft()})
        self.assertEqual(response.status_code, 200)
        response = self.client().post("/api/task-drafts/DRAFT-test/confirm", json={})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["execution_enabled"])
        with db() as connection:
            status = connection.execute("SELECT status FROM task_drafts WHERE id='DRAFT-test'").fetchone()[0]
        self.assertEqual(status, "confirmed")


if __name__ == "__main__":
    unittest.main()
