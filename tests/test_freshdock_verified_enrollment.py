"""Offline guards for verified full-project Freshdock enrollment."""
import copy
import io
import json
import tarfile
from types import SimpleNamespace
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "freshdock"))
import enroll_services_verified as verified


def live_spec(image="alpine:3.20", service="web"):
    c = {
        "Name": "/" + service,
        "Config": {
            "Image": image, "Env": ["X=one"],
            "Labels": {"com.docker.compose.project": "proj",
                       "com.docker.compose.service": service},
        },
        "HostConfig": {"NetworkMode": "bridge",
                       "RestartPolicy": {"Name": "unless-stopped"}},
        "Mounts": [],
    }
    spec = {"image": image, "restart": "unless-stopped",
            "environment": {"X": "one"}}
    return c, spec


class VerifiedEnrollmentTests(unittest.TestCase):
    def test_reviewed_hash_drift_is_exact(self):
        self.assertEqual(len(verified.KNOWN_HASH_DRIFT), 12)
        self.assertEqual(len(verified.KNOWN_IMAGE_DRIFT), 2)
        self.assertEqual(len(verified.PROTECTED), 5)
        self.assertLessEqual(verified.KNOWN_IMAGE_DRIFT,
                             verified.KNOWN_HASH_DRIFT)

    def test_labels_and_image_overlay_preserve_old_ref(self):
        output = verified.overlay({
            "database": ("mariadb_jellyseerr", "mariadb:old"),
            "web": ("jellyseerr", None),
        })
        self.assertIn("    image: \"mariadb:old\"", output)
        self.assertEqual(output.count("freshdock.enable:"), 2)
        self.assertIn('freshdock.mode: "nightly"', output)
        self.assertIn('freshdock.schedule: "45 2 * * *"', output)
        self.assertNotIn("vaultwarden:", output)


    def test_capabilities_accept_docker_prefixes_but_not_missing_privileges(self):
        live, spec = live_spec(image="tailscale/tailscale:latest", service="tailscale")
        spec["cap_add"] = ["NET_ADMIN", "NET_RAW"]
        live["HostConfig"]["CapAdd"] = ["CAP_NET_RAW", "CAP_NET_ADMIN"]
        self.assertEqual(verified.validate_runtime(live, spec, {}, "proj"), [])
        live["HostConfig"]["CapAdd"] = ["CAP_NET_RAW"]
        self.assertIn("cap_add differs",
                      verified.validate_runtime(live, spec, {}, "proj"))

    def test_compose_inline_config_matches_exact_existing_file(self):
        original = b'{"Web":{"domain":"internal.example"}}\n'
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name="serve.json")
            info.size = len(original)
            archive.addfile(info, io.BytesIO(original))
        fake = SimpleNamespace(returncode=0, stdout=stream.getvalue())
        container, spec = live_spec(image="tailscale/tailscale:latest", service="tailscale")
        spec["configs"] = [{"source": "ts-serve", "target": "/config/serve.json"}]
        tree = {"configs": {"ts-serve": {"content": original.decode()}}}
        with patch.object(verified.subprocess, "run", return_value=fake) as runner:
            self.assertEqual(verified.validate_runtime(container, spec, {}, "proj", tree), [])
            tree["configs"]["ts-serve"]["content"] = '{"unexpected":true}\n'
            self.assertIn("running config JSON top-level keys differ",
                          verified.validate_runtime(container, spec, {}, "proj", tree))
            # Equivalent JSON must not be refused just for whitespace,
            # member order or trailing-newline differences.
            tree["configs"]["ts-serve"]["content"] = '{"Web": { "domain": "internal.example" }}'
            self.assertEqual(
                verified.validate_runtime(container, spec, {}, "proj", tree), [])
            tree["configs"]["ts-serve"]["content"] = original.decode()
            args = runner.call_args.args[0]
            self.assertEqual(args, ["docker", "cp", "tailscale:/config/serve.json", "-"])

    def test_tailscale_serves_runtime_hostname_from_its_identity(self):
        template = {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {"${TS_CERT_DOMAIN}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8090"}}}},
            "AllowFunnel": {"${TS_CERT_DOMAIN}:443": False},
        }
        domain = "demo.tailnet.ts.net"
        live_config = json.loads(json.dumps(template).replace("${TS_CERT_DOMAIN}", domain))
        contents = json.dumps(live_config).encode("utf-8")
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            entry = tarfile.TarInfo(name="serve.json")
            entry.size = len(contents)
            archive.addfile(entry, io.BytesIO(contents))
        runtime_file = SimpleNamespace(returncode=0, stdout=stream.getvalue())
        identity = SimpleNamespace(returncode=0, stdout=json.dumps(
            {"Self": {"DNSName": domain + "."}}).encode("utf-8"))
        def fake_run(argv, **kwargs):
            if argv[:3] == ["docker", "exec", "tailscale"]:
                return identity
            if argv[:3] == ["docker", "cp", "tailscale:/config/serve.json"]:
                return runtime_file
            raise AssertionError("Unexpected command")
        container, spec = live_spec(image="tailscale/tailscale:latest", service="tailscale")
        spec["configs"] = [{"source": "ts-serve", "target": "/config/serve.json"}]
        tree = {"configs": {"ts-serve": {"content": json.dumps(template)}}}
        with patch.object(verified.subprocess, "run", side_effect=fake_run):
            self.assertEqual(
                verified.validate_runtime(container, spec, {}, "proj", tree), [])
            # An unrelated or stale identity must never authorize a changed Web key.
            identity.stdout = json.dumps({"Self": {"DNSName": "other.tailnet.ts.net."}}).encode()
            self.assertIn("Tailscale config differs after verified hostname substitution",
                          verified.validate_runtime(container, spec, {}, "proj", tree))
            identity.stdout = json.dumps({"Self": {"DNSName": domain + "."}}).encode()
            tree["configs"]["ts-serve"]["content"] = json.dumps({
                **template, "TCP": {"443": {"HTTPS": False}}})
            self.assertIn("Tailscale config differs after verified hostname substitution",
                          verified.validate_runtime(container, spec, {}, "proj", tree))

    def test_tailscale_invalid_identity_is_not_accepted(self):
        container, spec = live_spec(image="tailscale/tailscale:latest", service="tailscale")
        with patch.object(verified.subprocess, "run",
                          return_value=SimpleNamespace(
                              returncode=0,
                              stdout=b'{"Self":{"DNSName":"not/a/domain"}}')):
            self.assertIsNone(verified.live_tailscale_cert_domain(container))


    def test_masked_diagnostic_does_not_reveal_web_hostname(self):
        import diagnose_tailscale_serve as diag
        source = {
            "TCP": {"443": {"HTTPS": True}},
            "Web": {"__TOKEN__:443": {"Handlers": {"/": {
                "Proxy": "http://127.0.0.1:8080"}}}},
            "AllowFunnel": {"__TOKEN__:443": False},
        }
        import json as _json
        active = _json.loads(_json.dumps(source).replace(
            "__TOKEN__", "test.secret-tailnet.ts.net"))
        template = _json.loads(_json.dumps(source).replace(
            "__TOKEN__", diag.TOKEN))
        self.assertEqual(diag.web_key_kind(template, "test.secret-tailnet.ts.net"),
                         "TEMPLATE")
        self.assertEqual(diag.web_key_kind(active, "test.secret-tailnet.ts.net"),
                         "IDENTITY")
        self.assertEqual(diag.compare_fields(template, active,
                                              "test.secret-tailnet.ts.net"), "MATCH")
        active["Web"]["test.secret-tailnet.ts.net:443"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:8081"
        result = diag.compare_fields(template, active,
                                     "test.secret-tailnet.ts.net")
        self.assertEqual(result, "Web")
        self.assertNotIn("secret-tailnet", result)
        self.assertNotIn("8081", result)

    def test_diagnostic_does_not_normalize_unverified_web_hostname(self):
        import diagnose_tailscale_serve as diag
        template = {"Web": {diag.TOKEN + ":443": {"Handlers": {}}},
                    "AllowFunnel": {diag.TOKEN + ":443": False}, "TCP": {}}
        unrelated = {"Web": {"other.tailnet.ts.net:443": {"Handlers": {}}},
                     "AllowFunnel": {"other.tailnet.ts.net:443": False}, "TCP": {}}
        self.assertEqual(diag.compare_fields(template, unrelated,
                                             "real.tailnet.ts.net"),
                         "Web,AllowFunnel")

    def test_unavailable_config_does_not_silently_pass(self):
        container, spec = live_spec(image="tailscale/tailscale:latest", service="tailscale")
        spec["configs"] = [{"source": "ts-serve", "target": "/config/serve.json"}]
        self.assertIn("config source tree unavailable",
                      verified.validate_runtime(container, spec, {}, "proj"))
        self.assertIn("config source cannot be verified byte-for-byte",
                      verified.validate_runtime(container, spec, {}, "proj",
                                                {"configs": {"ts-serve": {"external": True}}}))

    def test_runtime_explicit_values_detected(self):
        c, spec = live_spec()
        self.assertEqual(verified.validate_runtime(c, spec, {"web": c}, "proj"), [])
        spec["user"] = "1234"
        self.assertIn("user differs",
                      verified.validate_runtime(c, spec, {"web": c}, "proj"))

    def test_known_image_drift_requires_known_source_difference(self):
        c, spec = live_spec(image="mariadb:live", service="mariadb_jellyseerr")
        spec["image"] = "mariadb:source"
        self.assertEqual(verified.validate_runtime(
            c, spec, {"mariadb_jellyseerr": c}, "proj"), [])
        spec["image"] = "mariadb:live"
        with self.assertRaisesRegex(verified.Refused, "expected image reference drift disappeared"):
            verified.validate_runtime(c, spec, {"mariadb_jellyseerr": c}, "proj")

    def test_unexpected_image_drift_refused(self):
        c, spec = live_spec(image="nginx:live")
        spec["image"] = "nginx:unknown"
        with self.assertRaisesRegex(verified.Refused, "unexpected source image"):
            verified.validate_runtime(c, spec, {"web": c}, "proj")

    def test_no_host_action_wrong_machine(self):
        with patch.object(verified.os, "geteuid", return_value=0), \
             patch.object(verified.socket, "gethostname", return_value="other"), \
             patch.object(verified, "live") as live:
            with self.assertRaisesRegex(verified.Refused, "openmediavault required"):
                verified.plan()
            live.assert_not_called()

    def test_composer_project_command_is_not_per_service(self):
        code = Path(verified.__file__).read_text()
        self.assertIn("--force-recreate", code)
        self.assertIn("*selected_services", code)
        self.assertIn("never", code)
        self.assertIn("base.verify_network", code)
        self.assertNotIn("journalctl", code)


if __name__ == "__main__":
    unittest.main()
