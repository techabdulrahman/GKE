import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import collectors_github, collectors_grafana, remediate
from agent.models import Action


class CollectorAuthorizationTests(unittest.TestCase):
    def test_github_token_uses_bearer_authorization(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "unit-test-token"}):
            header = collectors_github._h()["Authorization"]
        self.assertTrue(header.startswith("Bearer "))
        self.assertTrue(header.endswith("unit-test-token"))

    def test_grafana_token_uses_bearer_authorization(self):
        with patch.dict(os.environ, {"GRAFANA_TOKEN": "unit-test-token"}):
            header = collectors_grafana._h()["Authorization"]
        self.assertTrue(header.startswith("Bearer "))
        self.assertTrue(header.endswith("unit-test-token"))


class RemediationTests(unittest.TestCase):
    def test_dry_run_does_not_execute_kubectl(self):
        action = Action("rollout_restart", "ai-k8s-demo", "restart after alert")
        with patch.object(remediate.subprocess, "run") as run:
            result = remediate.run(action, "ai-troubleshooter", {"ai-k8s-demo"}, apply=False)
        run.assert_not_called()
        self.assertIn("DRY-RUN", result)

    def test_rejected_action_is_not_executed(self):
        action = Action("delete_namespace", "ai-k8s-demo", "invalid")
        with patch.object(remediate.subprocess, "run") as run:
            result = remediate.run(action, "ai-troubleshooter", {"ai-k8s-demo"}, apply=True)
        run.assert_not_called()
        self.assertIn("BLOCKED", result)

    def test_failed_remediation_is_not_reported_as_recovered(self):
        action = Action("rollout_restart", "ai-k8s-demo", "restart after alert")
        failed = subprocess.CompletedProcess([], 1, "", "forbidden")
        with patch.object(remediate.subprocess, "run", return_value=failed):
            result = remediate.run(action, "ai-troubleshooter", {"ai-k8s-demo"}, apply=True)
        self.assertIn("FAILED remediation", result)
        self.assertNotIn("VERIFIED recovered", result)

    def test_successful_remediation_checks_rollout_status(self):
        action = Action("rollout_undo", "ai-k8s-demo", "bad release")
        completed = subprocess.CompletedProcess([], 0, "rolled back", "")
        verified = subprocess.CompletedProcess([], 0, "successfully rolled out", "")
        with patch.object(remediate.subprocess, "run", side_effect=[completed, verified]) as run:
            result = remediate.run(action, "ai-troubleshooter", {"ai-k8s-demo"}, apply=True)
        self.assertEqual(run.call_count, 2)
        self.assertIn("VERIFIED recovered", result)


if __name__ == "__main__":
    unittest.main()
