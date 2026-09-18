#!/usr/bin/env python3
import json
from datetime import datetime, timezone

from resume_bundle import build_resume_bundle

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
MAIN = "c377f9bab2cad3504e51eaa81b0d08a6d3af6b91"
RULES = {
    "worker_bootstrap": "blob:boot",
    "ai_instructions": "blob:ai",
    "github_protocol": "blob:protocol",
}


def main():
    bundle = build_resume_bundle(
        main_sha=MAIN,
        rule_refs=RULES,
        owner_manager_directive_ref="Issue:#16:comment:owner",
        review_directive_ref="Issue:#19:comment:review",
        review_relevant=True,
        active_issues=[
            {
                "number": 119,
                "title": "Context-bounded resume",
                "state": "open",
                "workstream": "autonomy/context-bounded-resume",
                "owner": "worker-r310",
                "next_gate": "implementation",
                "history_unsafe": False,
                "raw_body": "MUST_NOT_LEAK",
            }
        ],
        open_prs=[
            {
                "number": 117,
                "head_sha": "head117",
                "base_sha": MAIN,
                "mergeable": True,
                "checks": ["watchdog:success"],
                "review_state": "review_required",
                "next_gate": "independent_review",
                "raw_diff": "MUST_NOT_LEAK",
            }
        ],
        next_gates=["PR:#117:independent-review", "Issue:#119:implementation"],
        target_issue={
            "number": 119,
            "issue_body": "full target issue body",
            "canonical_events": [
                {"id": 1, "type": "CLAIM"},
                {
                    "id": 2,
                    "type": "REVIEW",
                    "summary": "history_unsafe evidence retained for replay",
                },
            ],
            "history_unsafe": True,
        },
        resolved_history=[
            {"number": 1, "payload": "RESOLVED_HISTORY_MUST_NOT_APPEAR"},
            {"number": 2, "payload": "OTHER_RESOLVED_PAYLOAD"},
        ],
        generated_at=NOW,
    )

    encoded = json.dumps(bundle, sort_keys=True)
    assert bundle["authoritative"] is False
    assert bundle["visibility"] == "worker-private-ephemeral"
    assert bundle["freshness"]["main_sha"] == MAIN
    assert bundle["directive_refs"]["review"] == "Issue:#19:comment:review"
    assert bundle["active_queue"]["prs"][0]["head_sha"] == "head117"
    assert bundle["active_queue"]["next_gates"] == [
        "PR:#117:independent-review",
        "Issue:#119:implementation",
    ]
    assert "MUST_NOT_LEAK" not in encoded
    assert "RESOLVED_HISTORY_MUST_NOT_APPEAR" not in encoded
    assert bundle["omitted_history"] == {"count": 2, "policy": "on-demand-only"}
    assert bundle["target_replay"]["history_unsafe"] is True
    assert len(bundle["target_replay"]["canonical_events"]) == 2

    no_review = build_resume_bundle(
        main_sha=MAIN,
        rule_refs=RULES,
        owner_manager_directive_ref="Issue:#16:comment:owner",
        review_directive_ref="Issue:#19:comment:review",
        review_relevant=False,
        generated_at=NOW,
    )
    assert no_review["directive_refs"]["review"] is None
    assert no_review["target_replay"] is None

    try:
        build_resume_bundle(
            main_sha=MAIN,
            rule_refs={"worker_bootstrap": "x"},
            owner_manager_directive_ref="Issue:#16",
            generated_at=NOW,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("missing canonical rule refs must fail closed")

    print("RESUME_BUNDLE_OK")


if __name__ == "__main__":
    main()
