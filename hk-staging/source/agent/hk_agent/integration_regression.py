"""Offline-only BOSS-02 integration proof.

This test runs the actual candidate dispatcher but substitutes FakeExecutor.
It never invokes Docker, sudo, or the installed privileged executor.
"""
import inspect
from . import deployment_actions

def main():
    result = deployment_actions.offline_tests()
    required = {
        "VALID_CANARY_ACCEPTED", "VALID_DEPLOY_ACCEPTED", "VALID_VERIFY_ACCEPTED",
        "VALID_ROLLBACK_ACCEPTED", "UNKNOWN_ACTION_REJECTED",
        "UNKNOWN_PARAMETER_REJECTED", "MISSING_PARAMETER_REJECTED",
        "INVALID_IMAGE_ID_REJECTED", "INVALID_PACKAGE_REJECTED",
        "SHELL_METACHAR_REJECTED", "PATH_TRAVERSAL_REJECTED",
        "EXECUTOR_PATH_OVERRIDE_REJECTED", "SERVICE_OVERRIDE_REJECTED",
        "COMPOSE_OVERRIDE_REJECTED", "ENV_OVERRIDE_REJECTED",
        "PROJECT_OVERRIDE_REJECTED", "ROLLBACK_IMAGE_OVERRIDE_REJECTED",
        "DEPLOY_WITHOUT_APPROVAL_REJECTED", "ROLLBACK_WITHOUT_APPROVAL_REJECTED",
        "DEPLOY_WITHOUT_CANARY_EVIDENCE_REJECTED", "AI_SELF_APPROVAL_REJECTED",
    }
    if set(required) - set(result):
        raise SystemExit("missing offline regression cases")
    if any(result[name] not in ("PASS", "REJECT") for name in required):
        raise SystemExit("offline regression rejection failure")
    if result["NEGATIVE_FAKE_EXECUTOR_CALLED"] != "NO":
        raise SystemExit("negative case called fake executor")
    source = inspect.getsource(deployment_actions.ProductionExecutor.run)
    if "shell=False" not in source or "SUDO_EXECUTABLE" not in source or deployment_actions.EXECUTOR_PATH != "/usr/local/libexec/go-hk-deployctl":
        raise SystemExit("fixed executor boundary failure")
    for name in sorted(required):
        print(name + "=" + result[name])
    print("OFFLINE_TEST_COUNT=" + result["TEST_COUNT"])
    print("OFFLINE_TEST_PASS_COUNT=" + result["PASS_COUNT"])
    print("OFFLINE_TEST_FAIL_COUNT=" + result["FAIL_COUNT"])
    print("NEGATIVE_FAKE_EXECUTOR_CALLED=" + result["NEGATIVE_FAKE_EXECUTOR_CALLED"])
    print("SUBPROCESS_SHELL_FALSE=YES")
    print("EXECUTOR_PATH_FIXED=YES")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
