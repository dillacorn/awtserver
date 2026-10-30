"""Unit tests for guarded qBittorrent Watchtower migration policies."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker/watchtower"))
from test_watchtower_fork_migration import make_container, compose_labels
import watchtower_verify_qbittorrent as verify
import enroll_qbittorrent_29 as enroll


def build_fleet():
    labels = compose_labels()
    fleet = {name: make_container(name, labels=labels.copy())
             for name in verify.EXPANDED}
    fleet["gluetun"]["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
    fleet["gluetun"]["State"]["Health"] = {"Status": "healthy"}
    parent = fleet["gluetun"]["Id"]
    for name in ("transmission", "mullvad-browser", "amutorrent", "prowlarr", "trawl"):
        fleet[name]["HostConfig"]["NetworkMode"] = "container:" + parent
    fleet["qbittorrent"] = make_container("qbittorrent", labels=labels.copy())
    fleet["qbittorrent"]["HostConfig"]["NetworkMode"] = "container:" + parent
    fleet["tailscale-qbittorrent"] = make_container(
        "tailscale-qbittorrent", labels=labels.copy()
    )
    # An existing old Tailscale machine may remain connected during migration.
    # It is not a member of either Watchtower exact-target policy.
    fleet["tailscale-transmission"] = make_container(
        "tailscale-transmission", labels=labels.copy()
    )
    fleet["transmission"]["State"]["Status"] = "exited"
    names = sorted(verify.QBIT_TRANSITION)
    updater = make_container("watchtower")
    updater["Config"]["Cmd"] = [
        "--schedule", verify.SCHEDULE, "--no-startup-message", *names
    ]
    updater["Config"]["Image"] = "nickfedor/watchtower:1.23.1"
    fleet["watchtower"] = updater
    return fleet, names


class QbitPolicyTests(unittest.TestCase):
    def test_exact_29_target_transition_keeps_old_tailscale_machine_unselected(self):
        fleet, names = build_fleet()
        self.assertEqual(len(names), 29)
        self.assertIn("tailscale-transmission", fleet)
        self.assertNotIn("tailscale-transmission", names)
        self.assertNotIn("transmission", names)
        self.assertEqual(verify.verify_runtime(fleet, names), names)

    def test_running_unselected_transmission_is_rejected(self):
        fleet, names = build_fleet()
        fleet["transmission"]["State"]["Status"] = "running"
        with self.assertRaisesRegex(verify.Stop, "excluded dependent transmission"):
            verify.verify_runtime(fleet, names)

    def test_unknown_namespace_child_still_rejected(self):
        fleet, names = build_fleet()
        fleet["unexpected"] = make_container(
            "unexpected", network="container:" + fleet["gluetun"]["Id"]
        )
        with self.assertRaisesRegex(verify.Stop, "Unapproved additional Gluetun"):
            verify.verify_runtime(fleet, names)

    def test_removing_old_tailscale_machine_needs_no_allowlist_change(self):
        fleet, names = build_fleet()
        del fleet["tailscale-transmission"]
        self.assertEqual(verify.verify_runtime(fleet, names), names)

    def test_bad_target_set_is_not_accepted(self):
        fleet, names = build_fleet()
        invalid = names[:-1]
        fleet["watchtower"]["Config"]["Cmd"] = [
            "--schedule", verify.SCHEDULE, "--no-startup-message", *invalid
        ]
        with self.assertRaisesRegex(verify.Stop, "approved Watchtower services"):
            verify.verify_runtime(fleet, invalid)

    def test_manifest_validates_both_old_and_interim_exact_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "targets.json"
            for names in (sorted(verify.EXPANDED), sorted(verify.QBIT_TRANSITION)):
                path.write_text(json.dumps({
                    "container_names": names,
                    "schedule": verify.SCHEDULE,
                }))
                path.chmod(0o600)
                self.assertEqual(verify.read_targets(root), names)
            path.write_text(json.dumps({
                "container_names": ["qbittorrent"],
                "schedule": verify.SCHEDULE,
            }))
            with self.assertRaises(verify.Stop):
                verify.read_targets(root)

    def test_candidate_changes_only_target_names(self):
        original = sorted(verify.EXPANDED)
        compose = {"services": {"watchtower": {
            "command": enroll.expected_cmd(original),
            "environment": {"WATCHTOWER_CLEANUP": "false"},
            "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
        }}}
        manifest = {"container_names": original, "schedule": verify.SCHEDULE,
                    "custom": {"preserve": 1}}
        before = copy.deepcopy((compose, manifest))
        names, proposed, result = enroll.candidates(compose, manifest, original)
        self.assertEqual(set(names), verify.QBIT_TRANSITION)
        self.assertEqual(len(names), 29)
        self.assertEqual(result["custom"], {"preserve": 1})
        self.assertEqual(proposed["services"]["watchtower"]["environment"],
                         compose["services"]["watchtower"]["environment"])
        self.assertEqual((compose, manifest), before)


if __name__ == "__main__":
    unittest.main()
