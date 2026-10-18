"""Chromium namespace sandbox syscall admission with all container caps dropped."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def allowed_without_container_caps(profile, syscall):
    return [
        row
        for row in profile["syscalls"]
        if syscall in row.get("names", [])
        and row.get("action") == "SCMP_ACT_ALLOW"
        and not row.get("includes", {}).get("caps")
    ]


def service():
    spec = importlib.util.spec_from_file_location("prisma_sandbox_test", ROOT / "browser/service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chromium_chroot_is_not_gated_on_container_capabilities():
    profile = json.loads((ROOT / "browser/seccomp_profile.json").read_text())
    rows = allowed_without_container_caps(profile, "chroot")
    assert len(rows) == 1 and rows[0].get("args") == []
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"


def test_old_conditional_rule_cannot_admit_namespace_chroot():
    profile = {
        "syscalls": [
            {"names": ["chroot"], "action": "SCMP_ACT_ALLOW", "includes": {"caps": ["CAP_SYS_CHROOT"]}}
        ]
    }
    assert allowed_without_container_caps(profile, "chroot") == []


def test_namespace_calls_and_clone3_fallback_are_preserved():
    profile = json.loads((ROOT / "browser/seccomp_profile.json").read_text())
    for syscall in ("clone", "setns", "unshare"):
        assert allowed_without_container_caps(profile, syscall)
    assert any(
        "clone3" in row["names"] and row["action"] == "SCMP_ACT_ERRNO" and row.get("errnoRet") == 38
        for row in profile["syscalls"]
    )


def test_compose_retains_all_capability_drops_and_seccomp_profile():
    import yaml

    browser = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["browser"]
    assert browser["cap_drop"] == ["ALL"] and not browser.get("cap_add")
    assert browser["read_only"] and browser["security_opt"] == ["seccomp:./browser/seccomp_profile.json"]
    assert "USER pwuser" in (ROOT / "browser/Dockerfile").read_text()


def test_sandbox_and_pinned_proxy_are_preserved():
    options = service().launch_options()
    assert options["chromium_sandbox"] is True
    assert options["proxy"]["server"] == "http://127.0.0.1:9"
    assert not any(
        arg in {"--no-sandbox", "--disable-setuid-sandbox", "--single-process"} for arg in options["args"]
    )


def test_startup_diagnostic_identifies_exact_chroot_failure():
    reason = service().startup_reason(
        RuntimeError('Check failed: sys_chroot("/proc/self/fdinfo/") == 0 private target text')
    )
    assert "chroot" in reason and "seccomp" in reason and "private target" not in reason


def test_unknown_startup_diagnostic_does_not_echo_private_contents():
    assert "private target" not in service().startup_reason(RuntimeError("private target text"))
