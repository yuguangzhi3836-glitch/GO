# HK three-end 1000-VU acceptance — in progress

Target: deployed PR183 `edd3500575d2f2b81298cc9273025e0a3b734897`, image `sha256:8f8beb568209393fd74660c226ca7b14b2efe171caf5521645ec6fe4cea56119`, database `0137_hosted_unknown_episode`.

Run 01 authenticated 700 consumer, 150 supplier READ_ONLY and 150 admin GO_READ_ONLY accounts. All 1000 sessions were revoked successfully. The actual maximum active population reached 100, not 1000. 20 VU completed 60 s and passed. At 100 VU, five initial-burst requests took approximately 3.4 s at the client and 28–39 ms in the application; a supplier rolling-window latency gate stopped the run after 6.46 s. No HTTP errors or application restarts were observed. This is not a sustained 100-VU capacity verdict.

The first generator unintentionally released every stage's initial requests within one second. A reviewed actual-arrival ramp is being prepared with unchanged population, steady duration and thresholds. Run 01 remains a failed burst-profile result and will not be overwritten. No product deployment has been performed during this load work.

`run01-evidence.zip` SHA256: `58dc99a2e746e5863ed08cc88d9a8b7c4ccde747c0915f728ee8093575fb3c79` (240564 bytes); contains raw request/activity/host evidence, the executed harness, probe and report, with per-file hashes. No passwords, cookies, tokens or response bodies are archived. Payment/order mutation/browser rendering/real-supplier certification/Production are outside this protocol-load result.
