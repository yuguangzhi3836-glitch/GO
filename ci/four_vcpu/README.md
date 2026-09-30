# Separate 4-vCPU comparison — execution resource pending

The 2-vCPU formal run 36665714654 failed at 100 actors: P95 7856.219058 ms,
P99 7922.968890 ms. This result remains FAIL even if a 4-vCPU comparison succeeds.

On 2026-09-30 the repository runner settings visibly reported "There are no
runners configured". All existing capacity workflows use ubuntu-24.04; actual
formal evidence records 2 vCPUs. No 4-vCPU run has been executed or booked.

Required resource: one dedicated isolated Linux x86_64 VM with exactly four
visible and allowed vCPUs, at least four cores of cgroup CPU quota (or unlimited),
8 GiB RAM minimum to match the observed 2-vCPU runner, Docker for PostgreSQL 18.4,
Python 3.12, repository checkout access and ordinary package installation access.
Do not attach production credentials, use the Hong Kong runtime, change repository
visibility, buy capacity, or register a new privileged runner as part of this code.
An operator must supply the approved existing runner's label through repository
variable GO_CAPACITY_4CPU_RUNNER. With the variable absent the job skips. Once the
resource is ready, trigger a PR update touching this experiment's path. Alternatively,
run `python ci/four_vcpu/run.py` in this checkout on that isolated VM with the same
local test PostgreSQL URL used by the workflow. A clean checkout is required.

The PR runtime is conservatively restored after failed screening; this driver creates
an isolated detached checkout of rejected candidate 4048cbe64d0551130618d5d028204f770143aab7
for the hardware experiment. It never re-adopts that runtime into the PR.
Runtime is pinned by application tree b77840d31f0e31b046d8f3359c35630c75b8a02d;
baseline remains 059ebec3ab379099ef258effc3ab0a9833d52c35. The driver first verifies
real visible CPUs, process affinity and every readable cgroup-v2 ancestor quota.
Unknown layouts or lower quotas fail before database access. Hardware allocation
is checked again after the run. Memory, CPU model and OS are archived, not inferred
from a label. The frozen 250 regressions and new 24 safety tests must pass with zero
skips. Then the same existing ABBA implementation runs original/candidate/candidate/
original, 20 then100, with two service workers, pool5/overflow0 and5ms switch interval.
No worker/pool/admission tuning is bundled with the hardware comparison.

Archive four-vcpu-qualification and cpu-candidate-evidence together under a distinct
four-vcpu artifact. Review cold/continued journey and separate diagnostics as for
the 2-vCPU experiment. Report within-machine baseline/candidate relative gains and
absolute100-actor P95/P99, measured CPU, memory and DB waits. Cross-machine 2→4 CPU
changes also include any observed CPU-model/OS/package differences, and must not
be described as a clean CPU-only causal effect. No additional concurrency tiers,
merge, deployment, C14 pass or production capacity claim follows from this script.

The driver overlays the current reviewed journey harness onto the pinned candidate
checkout before ABBA; cpu_candidate then copies that identical harness to both
variants. Application bytes remain pinned. Do not compare new harness results
with old harness results to estimate a speedup. Actual concurrency validation stays strict.
