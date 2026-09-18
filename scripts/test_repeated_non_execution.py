#!/usr/bin/env python3
import unittest
from repeated_non_execution import evaluate_repeated_non_execution as evaluate


class RepeatedNonExecutionTests(unittest.TestCase):
    def test_first_non_execution_allows_one_corrective_redispatch(self):
        r = evaluate([{"objective": "x"}])
        self.assertEqual(r["status"], "CORRECTIVE_REDISPATCH_ALLOWED")
        self.assertEqual(r["strike_count"], 1)

    def test_second_non_execution_requires_escalation(self):
        r = evaluate([{"objective": "x"}, {"objective": "x"}])
        self.assertEqual(r["status"], "ESCALATE")
        self.assertEqual(r["incident"], "REPEATED_NON_EXECUTION")

    def test_third_identical_dispatch_rejected_until_classified(self):
        r = evaluate([{"objective": "x"}, {"objective": "x"}],
                     proposed_dispatch={"objective": "x"})
        self.assertEqual(r["status"], "REJECTED")

    def test_classified_cause_and_corrective_action_allow_reroute(self):
        events = [
            {"objective": "x"},
            {"objective": "x", "cause": "shared_executor_undiscovered",
             "corrective_next_action": "discover and attempt browser-agent"},
        ]
        r = evaluate(events, proposed_dispatch={"objective": "x", "route": "browser-agent"})
        self.assertEqual(r["status"], "ESCALATE")
        self.assertEqual(r["cause"], "shared_executor_undiscovered")

    def test_browser_local_capability_claim_without_executor_attempt_is_strike(self):
        r = evaluate([{"objective": "#114 rendered acceptance",
                       "required_executor": "browser-agent",
                       "generic_blocker": "worker surface lacks browser"}])
        self.assertEqual(r["strike_count"], 1)

    def test_executor_attempt_or_fresh_unavailable_discovery_is_execution_evidence(self):
        attempted = evaluate([{"required_executor": "browser-agent",
                               "executor_attempt_evidence": "sanitized failure ref"}])
        unavailable = evaluate([{"required_executor": "browser-agent",
                                 "executor_unavailable_evidence": "fresh discovery ref"}])
        self.assertEqual(attempted["strike_count"], 0)
        self.assertEqual(unavailable["strike_count"], 0)

    def test_safety_and_human_gates_do_not_become_non_execution_strikes(self):
        for gate in ("MAIN_RED", "history_unsafe", "HUMAN_REQUIRED", "security"):
            with self.subTest(gate=gate):
                self.assertEqual(evaluate([{"safety_gate": gate}])["strike_count"], 0)


if __name__ == "__main__":
    unittest.main()
