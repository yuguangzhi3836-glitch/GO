"""Fixed local registration-email verification probe.
This runtime never reads, prints, or returns a credential, message body, recipient, or one-time code.
It relies on the application-owned Unix socket, which performs the configured credential and delivery/redeem/audit test internally.
"""
import json, os, socket, stat
CONFIG="/etc/go-registration-email/verification.json"
SOCKET="/run/go-registration-email/verification.sock"
EXPECTED={"schema_version":"1","from_address":"postmaster@goaidirect.com","credential_reference":"hk-staging-registration-email"}
GATES={"sender_identity","credentials_usable","test_code_sent","delivery","code_verified","audit","secret_redaction"}
def run_probe():
    mode=os.lstat(CONFIG).st_mode
    if not stat.S_ISREG(mode) or mode & 0o022: raise ValueError("config protection")
    with open(CONFIG,encoding="utf-8") as f: cfg=json.load(f)
    if cfg != EXPECTED: raise ValueError("config identity")
    # Fixed request and fixed socket. No network URL, recipient, command, or secret is accepted as input.
    s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.settimeout(120); s.connect(SOCKET)
    try:
        s.sendall(b'{"action":"registration-email-config-verify-v1"}\\n')
        raw=s.makefile("rb").readline(4096)
    finally: s.close()
    result=json.loads(raw.decode("utf-8"))
    if not isinstance(result,dict) or set(result)!={"status","gate_results"} or result["status"]!="SUCCESS" or not isinstance(result["gate_results"],dict) or set(result["gate_results"])!=GATES or any(v!="PASS" for v in result["gate_results"].values()): raise ValueError("application probe")
    return result["gate_results"]
