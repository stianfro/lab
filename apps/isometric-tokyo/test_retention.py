"""Offline release transition, retention, and activation gate contracts."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import release_context as context
import release_gate
import stage_release
from prepare_bundle import prepare


def bundle(root, letter, shared=b"shared", extra=None, kind="preview"):
    release_id = "web-" + letter * 24
    preview_id = "shinjuku-" + kind + "-" + letter * 24
    site = root / release_id
    site.mkdir()
    files = {
        "index.html": b"<html>" + letter.encode() + b"</html>",
        "LICENSE": b"MIT fixture",
        "SOFTWARE_LICENSES.txt": b"Dependency notice " + letter.encode(),
        "preview/manifest.json": json.dumps({"id": preview_id}).encode(),
        "assets/shared.js": shared,
        "assets/app-" + letter + ".js": letter.encode(),
        "preview/releases/" + preview_id + "/atlas/0/0_0.webp": b"tile "
        + letter.encode(),
        "preview/releases/" + preview_id + "/credits.json": b'{"fixture":true}',
        **(extra or {}),
    }
    for name, payload in files.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    inventory = {
        "id": release_id,
        "identity": {"preview_release": preview_id},
        "assets": context.scan(site),
    }
    (site / "web-release.json").write_text(json.dumps(inventory))
    return site


def verifier(root):
    script = root / "fixture_verifier.py"
    script.write_text("""import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[2]); metadata=json.loads((root/'web-release.json').read_bytes())
for record in metadata['assets']:
 data=(root/record['path']).read_bytes()
 assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256']
files=[path for path in root.rglob('*') if path.is_file()]
print(json.dumps({'id':metadata['id'],'preview_id':metadata['identity']['preview_release'],'assets':len(files),'bytes':sum(path.stat().st_size for path in files)}))
""")
    return script


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.verifier = verifier(self.root)
        self.a = bundle(self.root, "a")
        self.b = bundle(self.root, "b")
        self.output = self.root / "transition"

    def stage(self, **kwargs):
        return stage_release.stage(
            self.a, self.verifier, self.b, self.verifier, self.output, **kwargs
        )

    def test_two_stages_select_different_entrypoints_but_share_immutable_assets(self):
        plan = self.stage()
        self.assertEqual(plan, stage_release.verify_transition(self.output))
        compatibility = context.verify_context(self.output / "compatibility")
        activation = context.verify_context(self.output / "activation")
        self.assertEqual(compatibility["id"], self.a.name)
        self.assertEqual(activation["id"], self.b.name)
        self.assertEqual(
            (self.output / "compatibility/site/index.html").read_bytes(),
            (self.a / "index.html").read_bytes(),
        )
        self.assertEqual(
            (self.output / "activation/site/index.html").read_bytes(),
            (self.b / "index.html").read_bytes(),
        )
        for report in (compatibility, activation):
            self.assertFalse(
                any(
                    record["path"]
                    in (
                        "index.html",
                        "web-release.json",
                        "preview/manifest.json",
                        "LICENSE",
                    )
                    for record in report["retained"]
                )
            )
            self.assertTrue(
                any(
                    record["path"].startswith("retained-notices/")
                    for record in report["retained"]
                )
            )
        self.assertEqual(plan, self.stage())

    def test_preview_to_map_preserves_both_release_namespaces(self):
        map_root = self.root / "map"
        map_root.mkdir()
        self.b = bundle(map_root, "c", kind="map")
        self.stage()
        for role in ("compatibility", "activation"):
            report = context.verify_context(self.output / role)
            paths = [record["path"] for record in report["site"] + report["retained"]]
            self.assertTrue(any("/shinjuku-preview-" in path for path in paths))
            self.assertTrue(any("/shinjuku-map-" in path for path in paths))

    def test_history_survives_another_release(self):
        self.stage()
        c = bundle(self.root, "c")
        second = self.root / "transition2"
        stage_release.stage(
            self.b, self.verifier, c, self.verifier, second, self.output / "activation"
        )
        report = context.verify_context(second / "activation")
        self.assertEqual(report["retained_releases"], [self.a.name, self.b.name])
        self.assertTrue((second / "activation/retained/assets/app-a.js").is_file())
        self.assertTrue((second / "activation/retained/assets/app-b.js").is_file())
        self.assertFalse((second / "activation/retained/assets/shared.js").exists())

    def test_immutable_collision_fails_closed(self):
        changed = self.root / "changed"
        changed.mkdir()
        self.b = bundle(changed, "c", shared=b"changed")
        with self.assertRaisesRegex(ValueError, "Immutable path collision"):
            self.stage()
        self.assertFalse(self.output.exists())

    def test_rejects_unsafe_and_mutable_retained_paths(self):
        for path in (
            "../secret",
            "/secret",
            "assets/../index.html",
            "assets/.secret",
            "assets/a?x=1",
            "assets//a",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                context.retained_path(path)
        for path in (
            "index.html",
            "web-release.json",
            "preview/manifest.json",
            "LICENSE",
            "preview/releases/not-a-release/file",
        ):
            self.assertFalse(context.retained_path(path))

    def test_symlinks_are_not_copied_into_retention(self):
        (self.a / "assets/link.js").symlink_to(self.a / "assets/shared.js")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.stage()

    def test_limits_fail_without_discarding_history(self):
        with (
            patch.object(context, "MAX_RELEASES", 0),
            self.assertRaisesRegex(ValueError, "Retention budget"),
        ):
            self.stage()
        self.assertFalse(self.output.exists())
        with (
            patch.object(context, "MAX_BYTES", 100),
            self.assertRaisesRegex(ValueError, "Retention budget"),
        ):
            self.stage()

    def test_context_and_plan_tampering_is_detected(self):
        self.stage()
        path = self.output / "compatibility/retained/assets/app-b.js"
        path.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            stage_release.verify_transition(self.output)

    def test_configuration_tampering_is_detected(self):
        self.stage()
        (self.output / "activation/nginx.conf").write_text("wrong config")
        with self.assertRaisesRegex(ValueError, "configuration hash"):
            stage_release.verify_transition(self.output)

    def test_different_existing_context_is_not_overwritten(self):
        target = self.root / "single"
        prepare(self.a, self.verifier, target)
        with self.assertRaisesRegex(ValueError, "new context"):
            prepare(self.b, self.verifier, target)
        self.assertEqual(context.verify_context(target)["id"], self.a.name)

    def test_previous_context_must_match_current_release(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, "does not select"):
            stage_release.stage(
                self.b,
                self.verifier,
                self.a,
                self.verifier,
                self.root / "bad",
                self.output / "compatibility",
            )

    def test_transition_plan_hash_is_checked(self):
        self.stage()
        path = self.output / "transition.json"
        plan = json.loads(path.read_text())
        plan["to"] = self.a.name
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, "Transition identity"):
            stage_release.verify_transition(self.output)


def rollout_fixture():
    image = "registry.invalid/app@sha256:" + "a" * 64
    context_id = "runtime-" + "a" * 24
    metadata = {"annotations": {release_gate.ANNOTATION: context_id}}
    pod_spec = {"containers": [{"name": "app", "image": image}]}
    deployment = {
        "metadata": {"generation": 2},
        "spec": {"replicas": 2, "template": {"metadata": metadata, "spec": pod_spec}},
        "status": {
            "observedGeneration": 2,
            "replicas": 2,
            "updatedReplicas": 2,
            "readyReplicas": 2,
            "availableReplicas": 2,
        },
    }
    pods = {
        "items": [
            {
                "metadata": {**copy.deepcopy(metadata), "uid": f"pod-{i}"},
                "spec": copy.deepcopy(pod_spec),
                "status": {
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "containerStatuses": [{"ready": True, "imageID": image}],
                },
            }
            for i in range(2)
        ]
    }
    endpoints = {
        "items": [
            {
                "endpoints": [
                    {
                        "conditions": {"ready": True},
                        "targetRef": {
                            "kind": "Pod",
                            "namespace": release_gate.APP,
                            "uid": f"pod-{i}",
                        },
                    }
                    for i in range(2)
                ]
            }
        ]
    }
    return deployment, pods, endpoints, image, context_id


class GateTests(unittest.TestCase):
    def test_complete_compatibility_rollout_passes(self):
        evidence = release_gate.check_rollout(*rollout_fixture())
        self.assertEqual(evidence["pods"], ["pod-0", "pod-1"])

    def test_mixed_unready_or_stale_rollouts_are_rejected(self):
        mutations = [
            lambda d, p, e: d["status"].update(observedGeneration=1),
            lambda d, p, e: d["status"].update(updatedReplicas=1),
            lambda d, p, e: d["spec"]["template"]["metadata"]["annotations"].clear(),
            lambda d, p, e: p["items"].append(copy.deepcopy(p["items"][0])),
            lambda d, p, e: p["items"][0]["metadata"].update(deletionTimestamp="now"),
            lambda d, p, e: p["items"][0]["spec"]["containers"][0].update(
                image="wrong"
            ),
            lambda d, p, e: p["items"][0]["status"]["containerStatuses"][0].update(
                ready=False
            ),
            lambda d, p, e: p["items"][0]["status"]["containerStatuses"][0].update(
                imageID="wrong"
            ),
            lambda d, p, e: e["items"][0]["endpoints"].pop(),
            lambda d, p, e: e["items"][0]["endpoints"][0]["conditions"].update(
                terminating=True
            ),
            lambda d, p, e: e["items"][0]["endpoints"][0]["targetRef"].update(
                uid="old-pod"
            ),
        ]
        for mutate in mutations:
            fixture = rollout_fixture()
            mutate(*fixture[:3])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                release_gate.check_rollout(*fixture)

    def test_gate_requires_registry_binding_and_stable_snapshots(self):
        plan = {
            "compatibility": "runtime-fixture",
            "transition_id": "transition-fixture",
        }
        image = rollout_fixture()[3]
        directory = Path("fixture")
        with (
            patch.object(release_gate, "verify_transition", return_value=plan),
            patch.object(
                release_gate,
                "read_json",
                return_value={
                    "config": {"Labels": {release_gate.ANNOTATION: "runtime-fixture"}}
                },
            ),
            patch.object(
                release_gate,
                "snapshot",
                side_effect=[{"generation": 1}, {"generation": 2}],
            ),
            patch.object(release_gate, "verify"),
            self.assertRaisesRegex(ValueError, "changed during"),
        ):
            release_gate.gate(directory, image, "https://fixture.invalid")
        with (
            patch.object(release_gate, "verify_transition", return_value=plan),
            patch.object(
                release_gate, "read_json", return_value={"config": {"Labels": {}}}
            ),
            self.assertRaisesRegex(ValueError, "Registry image"),
        ):
            release_gate.gate(directory, image, "https://fixture.invalid")

    def test_unpinned_image_fails(self):
        fixture = rollout_fixture()
        with self.assertRaisesRegex(ValueError, "pinned"):
            release_gate.check_rollout(*fixture[:3], "app:latest", fixture[4])


if __name__ == "__main__":
    unittest.main()
