#!/usr/bin/env python3
from evidence_action_gate import terminal_projection

def base_event():
    return {
        "event_kind": "rendered_e2e_completion",
        "acceptance_class": "PARTIAL",
        "operator_report": {
            "what_changed": "Post-change rendered E2E completed cleanly.",
            "evidence_identity": "artifact:10534444913",
            "user_visible_impact": "Narrow review target remains below initial viewport.",
            "unresolved_findings": ["review target is 147px below initial viewport at 390x844"],
            "next_action": "Route the unresolved narrow finding to a current-main disposition.",
        },
    }

event = base_event()
out = terminal_projection([event])
assert out["terminal_ready"] is False
assert out["action_disposition_required"] is True

event["action_disposition"] = {
    "kind": "live_equivalent",
    "workstream": "ux/narrow-review-target",
    "reason": "Fresh current-main workstream owns the same measured finding.",
}
out = terminal_projection([event])
assert out["terminal_ready"] is True
assert out["events"][0]["unresolved_finding_count"] == 1

deferred = base_event()
deferred["action_disposition"] = {"kind": "DEFERRED", "reason": "capacity"}
assert terminal_projection([deferred])["terminal_ready"] is False
deferred["action_disposition"]["authority"] = "Issue:#16"
assert terminal_projection([deferred])["terminal_ready"] is True

missing_report = base_event()
missing_report["operator_report"].pop("user_visible_impact")
missing_report["action_disposition"] = {
    "kind": "HUMAN_REQUIRED", "reason": "ambiguous admission"
}
out = terminal_projection([missing_report])
assert out["terminal_ready"] is False
assert out["operator_report_required"] is True

non_material = terminal_projection([{"event_kind": "routine_progress"}])
assert non_material["terminal_ready"] is True
print("EVIDENCE_ACTION_GATE_OK")
