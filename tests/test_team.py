"""Tests for the team system: TaskBoard, MessageBus, roles, callbacks."""

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agent.team.callbacks import TeamCallbacks
from agent.team.leader import TeamLeader
from agent.team.messages import Message, MessageBus
from agent.team.roles import TEAM_PRESETS, TeammateConfig
from agent.team.taskboard import Task, TaskBoard


class TestTaskBoard(unittest.TestCase):
    """TaskBoard thread safety, DAG, and lifecycle."""

    def setUp(self):
        self.tb = TaskBoard()

    def test_create_and_list(self):
        t = self.tb.create("Recon", "Do recon")
        self.assertEqual(t.subject, "Recon")
        self.assertEqual(t.status, "pending")
        self.assertEqual(len(self.tb.list_all()), 1)

    def test_claim_and_complete(self):
        t = self.tb.create("Task A", assignee="agent1")
        self.assertTrue(self.tb.claim(t.id, "agent1"))
        self.assertEqual(self.tb.get(t.id).status, "in_progress")

        # Can't double-claim
        self.assertFalse(self.tb.claim(t.id, "agent2"))

        self.tb.complete(t.id, "done")
        self.assertEqual(self.tb.get(t.id).status, "completed")
        self.assertEqual(self.tb.get(t.id).result, "done")

    def test_fail(self):
        t = self.tb.create("Task B")
        self.tb.claim(t.id, "x")
        self.tb.fail(t.id, "error")
        self.assertEqual(self.tb.get(t.id).status, "failed")

    def test_dependency_dag(self):
        t1 = self.tb.create("Recon", assignee="a")
        t2 = self.tb.create("Exploit", blocked_by=[t1.id], assignee="b")

        # t2 should not be available while t1 is pending
        avail = self.tb.list_available(for_agent="b")
        self.assertEqual(len(avail), 0)

        # t1 is available
        avail_a = self.tb.list_available(for_agent="a")
        self.assertEqual(len(avail_a), 1)
        self.assertEqual(avail_a[0].id, t1.id)

        # Complete t1 -> t2 unblocks
        self.tb.claim(t1.id, "a")
        self.tb.complete(t1.id, "findings")
        avail_b = self.tb.list_available(for_agent="b")
        self.assertEqual(len(avail_b), 1)
        self.assertEqual(avail_b[0].id, t2.id)

    def test_inverse_dependency_auto_populated(self):
        t1 = self.tb.create("A")
        t2 = self.tb.create("B", blocked_by=[t1.id])
        self.assertIn(t2.id, self.tb.get(t1.id).blocks)

    def test_all_done(self):
        self.assertFalse(self.tb.all_done())  # empty board
        t = self.tb.create("X")
        self.assertFalse(self.tb.all_done())
        self.tb.claim(t.id, "a")
        self.tb.complete(t.id)
        self.assertTrue(self.tb.all_done())

    def test_delete_cleans_references(self):
        t1 = self.tb.create("A")
        t2 = self.tb.create("B", blocked_by=[t1.id])
        self.tb.delete(t1.id)
        self.assertEqual(self.tb.get(t2.id).blocked_by, [])

    def test_update(self):
        t = self.tb.create("Old")
        self.tb.update(t.id, subject="New", metadata={"key": "val"})
        updated = self.tb.get(t.id)
        self.assertEqual(updated.subject, "New")
        self.assertEqual(updated.metadata["key"], "val")

    def test_summary(self):
        self.tb.create("Task A")
        s = self.tb.summary()
        self.assertIn("Task A", s)

    def test_concurrent_claims(self):
        """Only one thread should win a claim race."""
        t = self.tb.create("Race")
        results = []

        def try_claim(name):
            results.append(self.tb.claim(t.id, name))

        threads = [threading.Thread(target=try_claim, args=(f"a{i}",)) for i in range(10)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(sum(results), 1)  # exactly one winner


class TestMessageBus(unittest.TestCase):
    """MessageBus send/receive, broadcast, shutdown protocol."""

    def setUp(self):
        self.mb = MessageBus()
        self.mb.register("lead")
        self.mb.register("agent1")
        self.mb.register("agent2")

    def test_send_receive(self):
        self.mb.send("agent1", "lead", "hello", "info")
        msgs = self.mb.receive("lead")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "hello")
        self.assertEqual(msgs[0].sender, "agent1")

        # Drain — second receive returns empty
        self.assertEqual(len(self.mb.receive("lead")), 0)

    def test_broadcast(self):
        self.mb.broadcast("lead", "shutdown soon", "info")
        self.assertEqual(len(self.mb.receive("agent1")), 1)
        self.assertEqual(len(self.mb.receive("agent2")), 1)
        self.assertEqual(len(self.mb.receive("lead")), 0)  # sender excluded

    def test_broadcast_with_exclude(self):
        self.mb.broadcast("lead", "msg", "info", exclude="agent2")
        self.assertEqual(len(self.mb.receive("agent1")), 1)
        self.assertEqual(len(self.mb.receive("agent2")), 0)

    def test_peek_nondestructive(self):
        self.mb.send("a", "lead", "hi")
        self.assertEqual(len(self.mb.peek("lead")), 1)
        self.assertEqual(len(self.mb.peek("lead")), 1)  # still there

    def test_has_messages(self):
        self.assertFalse(self.mb.has_messages("lead"))
        self.mb.send("a", "lead", "hi")
        self.assertTrue(self.mb.has_messages("lead"))

    def test_shutdown_protocol(self):
        req_id = self.mb.send_shutdown_request("lead", "agent1", "done")
        msgs = self.mb.receive("agent1")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].msg_type, "shutdown_request")

        self.mb.send_shutdown_response("agent1", "lead", req_id, approved=True)
        resp = self.mb.receive("lead")
        self.assertEqual(len(resp), 1)
        self.assertEqual(resp[0].msg_type, "shutdown_response")
        self.assertEqual(resp[0].request_id, req_id)

    def test_get_discoveries(self):
        self.mb.send("agent1", "lead", "found SQLi", "discovery")
        self.mb.send("agent1", "lead", "status update", "info")
        discoveries = self.mb.get_discoveries()
        self.assertEqual(len(discoveries), 1)
        self.assertEqual(discoveries[0].content, "found SQLi")

    def test_get_log(self):
        for i in range(5):
            self.mb.send("a", "lead", f"msg{i}")
        log = self.mb.get_log(limit=3)
        self.assertEqual(len(log), 3)


class TestTeamPresets(unittest.TestCase):
    """Verify all 8 categories have presets."""

    EXPECTED_CATEGORIES = {"web", "pwn", "crypto", "forensics", "reverse", "osint", "ai", "misc"}

    def test_all_categories_have_presets(self):
        self.assertEqual(set(TEAM_PRESETS.keys()), self.EXPECTED_CATEGORIES)

    def test_each_preset_has_at_least_two_teammates(self):
        for cat, mates in TEAM_PRESETS.items():
            self.assertGreaterEqual(len(mates), 2, f"{cat} has <2 teammates")

    def test_teammate_names_unique_within_preset(self):
        for cat, mates in TEAM_PRESETS.items():
            names = [m.name for m in mates]
            self.assertEqual(len(names), len(set(names)), f"{cat} has duplicate names")

    def test_ai_preset_has_correct_roles(self):
        ai = TEAM_PRESETS["ai"]
        roles = {m.role for m in ai}
        self.assertIn("AI probing & reconnaissance", roles)
        self.assertIn("AI secret extraction", roles)


class TestTeamCallbacks(unittest.TestCase):
    """TeamCallbacks forward events correctly."""

    def setUp(self):
        self.mb = MessageBus()
        self.tb = TaskBoard()
        self.mb.register("lead")
        self.mb.register("agent1")
        self.cb = TeamCallbacks("agent1", self.mb, self.tb)

    def test_flag_forwarded(self):
        self.cb.on_flag_found("FLAG{test}")
        msgs = self.mb.receive("lead")
        flag_msgs = [m for m in msgs if m.msg_type == "flag"]
        # 2 messages: direct send + broadcast
        self.assertEqual(len(flag_msgs), 2)
        self.assertEqual(flag_msgs[0].content, "FLAG{test}")

    def test_error_forwarded(self):
        self.cb.on_error("something broke")
        msgs = self.mb.receive("lead")
        self.assertTrue(any("something broke" in m.content for m in msgs))

    def test_tool_result_discovery(self):
        self.cb.on_tool_result("shell", "x" * 100, True)
        msgs = self.mb.receive("lead")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].msg_type, "discovery")

    def test_tool_result_llm_interact_forwarded(self):
        self.cb.on_tool_result("llm_interact", "x" * 100, True)
        msgs = self.mb.receive("lead")
        self.assertEqual(len(msgs), 1)

    def test_tool_result_short_output_ignored(self):
        self.cb.on_tool_result("shell", "ok", True)
        msgs = self.mb.receive("lead")
        self.assertEqual(len(msgs), 0)

    def test_tool_result_failure_ignored(self):
        self.cb.on_tool_result("shell", "x" * 100, False)
        msgs = self.mb.receive("lead")
        self.assertEqual(len(msgs), 0)

    def test_create_task(self):
        task_id = self.cb.create_task("Follow-up", "Do more work")
        self.assertIsNotNone(self.tb.get(task_id))
        msgs = self.mb.receive("lead")
        self.assertTrue(any(m.msg_type == "task_created" for m in msgs))

    def test_on_ask_user_returns_empty(self):
        result = self.cb.on_ask_user("Need password")
        self.assertEqual(result, "")


class TestWorkspaceIsolation(unittest.TestCase):
    """Verify per-teammate workspace directories."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_spawn_creates_per_teammate_dirs(self):
        leader = TeamLeader(workspace=self.tmpdir)
        mate_a = TeammateConfig(name="recon", role="Recon", prompt="Do recon")
        mate_b = TeammateConfig(name="exploit", role="Exploit", prompt="Exploit")

        # Call _spawn_teammate (doesn't start the thread, just creates it)
        leader._spawn_teammate(mate_a, "test challenge")
        leader._spawn_teammate(mate_b, "test challenge")

        self.assertTrue((self.tmpdir / "team_recon").is_dir())
        self.assertTrue((self.tmpdir / "team_exploit").is_dir())

    def test_spawn_symlinks_challenge_files(self):
        # Create a challenge file
        challenge_file = self.tmpdir / "challenge.py"
        challenge_file.write_text("print('hello')")

        leader = TeamLeader(workspace=self.tmpdir)
        mate = TeammateConfig(name="solver", role="Solver", prompt="Solve")
        leader._spawn_teammate(mate, "test", files=[challenge_file])

        linked = self.tmpdir / "team_solver" / "challenge.py"
        self.assertTrue(linked.exists())
        self.assertEqual(linked.read_text(), "print('hello')")

    def test_teammates_get_separate_workspaces(self):
        """Files written in one teammate dir don't appear in another."""
        leader = TeamLeader(workspace=self.tmpdir)
        mate_a = TeammateConfig(name="a", role="A", prompt="A")
        mate_b = TeammateConfig(name="b", role="B", prompt="B")

        leader._spawn_teammate(mate_a, "test")
        leader._spawn_teammate(mate_b, "test")

        # Write a file in a's workspace
        (self.tmpdir / "team_a" / "exploit.py").write_text("pwn")

        # b's workspace should not have it
        self.assertFalse((self.tmpdir / "team_b" / "exploit.py").exists())


if __name__ == "__main__":
    unittest.main()
