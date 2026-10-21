"""Read-only gate: activation requires a complete compatibility rollout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from stage_release import verify_transition
from verify_runtime import verify

APP = "isometric-tokyo"
ANNOTATION = "isometric.tokyo/runtime-context"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def check_rollout(deployment, pods, endpoints, image, context_id):
    require(
        re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image),
        "Image must be pinned by digest",
    )
    spec = deployment["spec"]
    status = deployment.get("status", {})
    desired = spec.get("replicas", 1)
    require(desired >= 2, "At least two replicas are required")
    require(
        status.get("observedGeneration") == deployment["metadata"]["generation"],
        "Deployment has not observed this generation",
    )
    require(
        all(
            status.get(key) == desired
            for key in (
                "replicas",
                "updatedReplicas",
                "readyReplicas",
                "availableReplicas",
            )
        ),
        "Compatibility rollout is not complete",
    )
    require(status.get("unavailableReplicas", 0) == 0, "Unavailable replicas remain")
    template = spec["template"]
    require(
        template["metadata"].get("annotations", {}).get(ANNOTATION) == context_id,
        "Deployment context does not match compatibility image",
    )
    require(
        len(template["spec"]["containers"]) == 1
        and template["spec"]["containers"][0]["image"] == image,
        "Deployment image mismatch",
    )
    items = pods["items"]
    require(len(items) == desired, "Old, missing, or extra pods remain")
    uids = set()
    for pod in items:
        metadata = pod["metadata"]
        require(not metadata.get("deletionTimestamp"), "Terminating pods remain")
        require(
            metadata.get("annotations", {}).get(ANNOTATION) == context_id,
            "Mixed pod contexts",
        )
        containers = pod["spec"]["containers"]
        require(
            len(containers) == 1 and containers[0]["image"] == image, "Mixed pod images"
        )
        state = pod.get("status", {})
        require(state.get("phase") == "Running", "Pod is not running")
        statuses = state.get("containerStatuses", [])
        require(
            len(statuses) == 1
            and statuses[0].get("ready")
            and statuses[0].get("imageID", "").endswith(image.split("@", 1)[1]),
            "Pod is not ready on the expected digest",
        )
        require(
            any(
                item.get("type") == "Ready" and item.get("status") == "True"
                for item in state.get("conditions", [])
            ),
            "Pod Ready condition is missing",
        )
        uids.add(metadata["uid"])
    serving = set()
    for endpoint_slice in endpoints["items"]:
        for endpoint in endpoint_slice.get("endpoints", []):
            conditions = endpoint.get("conditions", {})
            require(
                conditions.get("ready") is True
                and not conditions.get("terminating", False),
                "Unready or terminating service endpoints remain",
            )
            target = endpoint.get("targetRef", {})
            require(
                target.get("kind") == "Pod" and target.get("namespace") == APP,
                "Unexpected service endpoint target",
            )
            serving.add(target.get("uid"))
    require(
        serving == uids, "Service endpoints do not exactly match the compatible pods"
    )
    return {
        "generation": deployment["metadata"]["generation"],
        "pods": sorted(uids),
        "image": image,
        "context_id": context_id,
    }


def read_json(command):
    return json.loads(subprocess.check_output(command, text=True))


def snapshot(image, context_id):
    prefix = ["kubectl", "-n", APP, "get"]
    deployment = read_json([*prefix, "deployment", APP, "-o", "json"])
    pods = read_json(
        [*prefix, "pods", "-l", "app.kubernetes.io/name=" + APP, "-o", "json"]
    )
    endpoints = read_json(
        [
            *prefix,
            "endpointslices",
            "-l",
            "kubernetes.io/service-name=" + APP,
            "-o",
            "json",
        ]
    )
    return check_rollout(deployment, pods, endpoints, image, context_id)


def gate(directory, image, url):
    plan = verify_transition(directory)
    require(
        re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image),
        "Image must be pinned by digest",
    )
    config = read_json(["crane", "config", image])
    require(
        config.get("config", {}).get("Labels", {}).get(ANNOTATION)
        == plan["compatibility"],
        "Registry image does not contain the expected context label",
    )
    before = snapshot(image, plan["compatibility"])
    verify(url.rstrip("/"), directory / "compatibility")
    after = snapshot(image, plan["compatibility"])
    require(before == after, "Deployment changed during verification")
    return {"activation_allowed": True, "transition_id": plan["transition_id"], **after}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transition", type=Path)
    parser.add_argument("compatibility_image")
    parser.add_argument("url")
    args = parser.parse_args()
    print(
        json.dumps(gate(args.transition, args.compatibility_image, args.url), indent=2)
    )
