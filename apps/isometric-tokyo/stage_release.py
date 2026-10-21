"""Prepare a compatibility-first release transition without changing a service."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from prepare_bundle import outside_repository, prepare, verify
from release_context import canonical, digest, verify_context


def stage(
    current, current_verifier, upcoming, upcoming_verifier, output, previous=None
):
    output = outside_repository(output)
    current_report = verify(current_verifier, current)
    upcoming_report = verify(upcoming_verifier, upcoming)
    if current_report["id"] == upcoming_report["id"]:
        raise ValueError("Transition needs different current and next releases")
    if previous and verify_context(previous)["id"] != current_report["id"]:
        raise ValueError("Previous context does not select the current release")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".transition-stage-", dir=output.parent))
    try:
        transition = {"from": current_report["id"], "to": upcoming_report["id"]}
        compatibility = prepare(
            current,
            current_verifier,
            temporary / "compatibility",
            previous,
            upcoming,
            {"role": "compatibility", **transition},
        )
        activation = prepare(
            upcoming,
            upcoming_verifier,
            temporary / "activation",
            previous,
            current,
            {"role": "activation", **transition},
        )
        # Product verification applies independently to both bundles, even when
        # their formats require different verifier revisions.
        if (
            verify(current_verifier, current) != current_report
            or verify(upcoming_verifier, upcoming) != upcoming_report
        ):
            raise ValueError("Source release changed during transition preparation")
        plan = {
            "schema_version": 1,
            **transition,
            "compatibility": compatibility["context_id"],
            "activation": activation["context_id"],
        }
        plan["transition_id"] = "transition-" + digest(canonical(plan))[:24]
        (temporary / "transition.json").write_text(json.dumps(plan, indent=2) + "\n")
        verify_transition(temporary)
        if output.exists():
            if verify_transition(output) != plan:
                raise ValueError("Use a new transition path for a different release")
        else:
            temporary.rename(output)
        return plan
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify_transition(directory):
    plan = json.loads((directory / "transition.json").read_bytes())
    identity = {key: value for key, value in plan.items() if key != "transition_id"}
    if (
        plan.get("schema_version") != 1
        or plan.get("transition_id") != "transition-" + digest(canonical(identity))[:24]
    ):
        raise ValueError("Transition identity mismatch")
    reports = {}
    for role, selected in (("compatibility", "from"), ("activation", "to")):
        report = verify_context(directory / role)
        reports[role] = report
        if (
            report["context_id"] != plan[role]
            or report["id"] != plan[selected]
            or report["stage"] != {"role": role, "from": plan["from"], "to": plan["to"]}
        ):
            raise ValueError("Transition context binding mismatch")
    # Every immutable asset required by either version must be identical on
    # both images. This also catches assets missing from a retained inventory.
    from release_context import immutable

    payloads = []
    for report in reports.values():
        payloads.append(
            {
                record["path"]: record
                for record in report["site"] + report["retained"]
                if immutable(record["path"])
            }
        )
    if payloads[0] != payloads[1]:
        raise ValueError("Transition images do not share all immutable assets")
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("current_verifier", type=Path)
    parser.add_argument("upcoming", type=Path)
    parser.add_argument("upcoming_verifier", type=Path)
    parser.add_argument("output", type=Path)
    history = parser.add_mutually_exclusive_group(required=True)
    history.add_argument("--current-context", type=Path)
    history.add_argument(
        "--bootstrap",
        action="store_true",
        help="First transition only, current runtime has no retained history",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            stage(
                args.current,
                args.current_verifier,
                args.upcoming,
                args.upcoming_verifier,
                args.output,
                args.current_context,
            ),
            indent=2,
        )
    )
