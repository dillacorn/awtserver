"""Offline guards for Freshdock automatic-update/rollback disposable tests."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import freshdock_auto_canary as canary


def fake_wud():
    return {
        "Config": {
            "Labels": {
                "com.docker.compose.project": "wud",
                "com.docker.compose.service": "wud",
                "com.docker.compose.project.working_dir": "/docker/wud",
            },
            "Env": [
                "WUD_WATCHER_LOCAL_INCLUDE=^(?:brave|gluetun|transmission)$",
                "WUD_WATCHER_LOCAL_WATCHBYDEFAULT=false",
                "WUD_WATCHER_LOCAL_WATCHEVENTS=false",
            ],
        },
        "State": {"Status": "running"},
    }


def fake_docker(args, **kwargs):
    if args == ["info"]:
        return Mock(returncode=0)
    if args == ["compose", "version"]:
        return Mock(returncode=0)
    if args == ["image", "inspect", "alpine:3.20"]:
        return Mock(returncode=1)
    raise AssertionError(f"Unexpected command: {args}")


class SafetyTests(unittest.TestCase):
    def test_uses_pinned_freshdock_and_separate_old_and_moving_images(self):
        self.assertEqual(canary.FRESHDOCk_IMAGE,
                         "ghcr.io/turbootzz/freshdock:1.7.1")
        self.assertEqual(canary.OLD_IMAGE, "alpine:3.20.0")
        self.assertEqual(canary.MOVING_TAG, "alpine:3.20")

    def test_compose_explicitly_enables_only_disposable_parent(self):
        for rollback in (False, True):
            yml = canary.stack("fdautocanary123-parent",
                               "fdautocanary123-child", rollback)
            self.assertIn('network_mode: "service:parent"', yml)
            self.assertEqual(yml.count('freshdock.enable: "true"'), 1)
            self.assertEqual(yml.count('freshdock.mode: "live"'), 1)
            self.assertEqual(yml.count('wud.watch: "false"'), 2)
            self.assertIn("condition: service_healthy", yml)
            self.assertNotIn("privileged:", yml)
            self.assertNotIn("volumes:", yml)
            self.assertNotIn("network_mode: host", yml)

    def test_rollback_healthcheck_fails_only_after_upgrade(self):
        before = canary.stack("parent", "child", False)
        rollback = canary.stack("parent", "child", True)
        self.assertIn("test -r /etc/alpine-release", before)
        self.assertIn("grep -qx '3.20.0'", rollback)

    def test_opted_in_existing_containers_block_scheduler(self):
        self.assertTrue(canary.is_freshdock_opt_in(
            {"Config": {"Labels": {"freshdock.enable": "true"}}}))
        self.assertTrue(canary.is_freshdock_opt_in(
            {"Config": {"Labels": {
                "com.centurylinklabs.watchtower.enable": "true"}}}))
        self.assertFalse(canary.is_freshdock_opt_in(
            {"Config": {"Labels": {"freshdock.enable": "false"}}}))

    def test_preflight_accepts_paused_transmission(self):
        production = [{
            "Name": "/transmission", "Id": "old",
            "State": {"Status": "paused"},
            "Config": {"Labels": {}, "Image": "lscr.io/linuxserver/transmission:latest"},
        }]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary.subprocess, "run",
                          return_value=Mock(stdout="openmediavault\n")), \
             patch.object(canary, "docker", side_effect=fake_docker), \
             patch.object(canary, "all_containers", return_value=production), \
             patch.object(canary, "by_name", return_value=fake_wud()):
            before, regex = canary.preflight()
        self.assertEqual(before["/transmission"], ("old", "paused"))
        self.assertFalse(canary.re.search(regex, "fdautocanary123-parent"))

    def test_tag_collision_rejects_before_creating_test(self):
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary.subprocess, "run",
                          return_value=Mock(stdout="openmediavault\n")), \
             patch.object(canary, "docker", side_effect=lambda args, **kwargs:
                          Mock(returncode=0)), \
             patch.object(canary, "all_containers", return_value=[]):
            with self.assertRaisesRegex(canary.Unsafe, "already exists"):
                canary.preflight()

    def test_existing_enabled_freshdock_container_rejected(self):
        production = [{
            "Name": "/other", "Id": "one",
            "State": {"Status": "running"},
            "Config": {"Image": "nginx:latest",
                       "Labels": {"freshdock.enable": "true"}},
        }]
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary.subprocess, "run",
                          return_value=Mock(stdout="openmediavault\n")), \
             patch.object(canary, "docker", side_effect=fake_docker), \
             patch.object(canary, "all_containers", return_value=production):
            with self.assertRaisesRegex(canary.Unsafe, "pre-existing container"):
                canary.preflight()

    def test_preflight_rejects_wrong_host(self):
        with patch.object(canary.os, "geteuid", return_value=0), \
             patch.object(canary.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(canary.subprocess, "run",
                          return_value=Mock(stdout="some-other-host\n")), \
             patch.object(canary, "docker") as client:
            with self.assertRaisesRegex(canary.Unsafe, "Unexpected host"):
                canary.preflight()
            client.assert_not_called()

    def test_failed_preflight_creates_no_test_containers(self):
        with patch.object(canary, "preflight",
                          side_effect=canary.Unsafe("unsafe host")), \
             patch.object(canary, "docker") as client:
            with self.assertRaisesRegex(canary.Unsafe, "unsafe host"):
                canary.run_stage(False)
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
