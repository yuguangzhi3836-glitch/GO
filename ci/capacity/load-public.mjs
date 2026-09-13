import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

// This measures anonymous searches and entry pages only. It cannot pass login,
// orders, money, supplier/admin operations, runtime identity, or release gates.
const BASE = 'https://staging-api.goaidirect.com';
const IDENTITY = {
  main: '286e294d92df4b7d1c0073116a8e628734abec6c',
  application_tree: '3025b2b6b36ea9211da561a4631f304216de9d90',
  runtime_source_sha256: 'd90a9e26c3a64b98009aaf170056f4b3acfa6acebd41baaed276b7baf17c6925',
  generation: 'DEPTH48', expected_database_head: '0133_flight_change_plan',
  live_image_database_binding: 'HOLD_AUTHENTICATED_OBSERVATION_MISSING',
};
const PLAN = [
  { vus: 10, seconds: 30 }, { vus: 50, seconds: 45 },
  { vus: 100, seconds: 60 }, { vus: 250, seconds: 60 },
  { vus: 500, seconds: 60 }, { vus: 1000, seconds: 120 },
];
const VERTICALS = ['HOTEL', 'FLIGHT', 'RAIL', 'RIDE', 'RENTAL', 'ATTRACTION'];
const THRESHOLDS = { stage_p95_ms: 2000, stage_p99_ms: 5000,
  unexpected_error_rate: 0.01, semantic_error_count: 0,
  abort_window_ms: 15000, abort_p95_ms: 3000, abort_error_rate: 0.05,
  abort_consecutive_checks: 3, request_timeout_ms: 5000, max_requests: 50000 };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const iso = () => new Date().toISOString();
const sha = s => crypto.createHash('sha256').update(s).digest('hex');
function quantile(values, q) {
  if (!values.length) return null;
  const a = [...values].sort((x, y) => x - y);
  return a[Math.max(0, Math.ceil(a.length * q) - 1)];
}
function summarize(rows) {
  const latency = rows.map(x => x.elapsed_ms);
  return { requests: rows.length, errors: rows.filter(x => !x.ok).length,
    semantic_errors: rows.filter(x => x.status === 200 && !x.semantic_ok).length,
    error_rate: rows.length ? rows.filter(x => !x.ok).length / rows.length : null,
    p50_ms: quantile(latency, .5), p95_ms: quantile(latency, .95),
    p99_ms: quantile(latency, .99), max_ms: latency.length ? Math.max(...latency) : null,
    statuses: rows.reduce((a, x) => (a[x.status] = (a[x.status] || 0) + 1, a), {}) };
}
function criteria(vertical, vu) {
  const date = n => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
  const day = date(30 + vu % 5), end = date(35 + vu % 5);
  return {
    HOTEL: ['/v1/search/hotels', { destination: { city_code: 'TYO' }, stay: { check_in: day, check_out: end }, occupancy: { rooms: 1, adults: 2, children: 0 }, currency: 'CNY' }],
    FLIGHT: ['/v1/flights/journeys/search', { trip_type: 'ROUND_TRIP', adults: 2, legs: [{ origin: 'SHA', destination: 'PEK', departure_date: day }, { origin: 'PEK', destination: 'SHA', departure_date: end }] }],
    RAIL: ['/v1/rail/search', { origin_station: 'SHA', destination_station: 'HZH', travel_date: day }],
    RIDE: ['/v1/mobility/rides/search', { pickup: 'PVG', dropoff: 'Bund', pickup_at: day + 'T10:00:00+08:00' }],
    RENTAL: ['/v1/mobility/rentals/search', { pickup_location: 'NRT', return_location: 'NRT', pickup_at: day + 'T10:00:00+09:00', return_at: end + 'T10:00:00+09:00' }],
    ATTRACTION: ['/v1/attractions/search', { destination: '\u4e1c\u4eac', visit_date: day }],
  }[vertical];
}
function validate(kind, status, body) {
  if (status !== 200) return false;
  if (kind.endsWith('_ENTRY')) return body.includes('<html') && body.includes('GO');
  try {
    const d = JSON.parse(body).data;
    if (kind === 'HOTEL') return d.hotels.length > 0 && d.hotels.every(h => h.best_offer?.offer_id);
    if (kind === 'FLIGHT') return d.legs.length === 2 && d.legs.every(l => l.items.length > 0) && d.external_live === false;
    return d.items.length > 0 && d.items.every(x => x.external_live === false);
  } catch { return false; }
}
function errorDetails(error, signal) {
  const codes = new Set();
  function visit(value, depth = 0) {
    if (!value || depth > 3) return;
    if (typeof value.code === 'string') codes.add(value.code);
    visit(value.cause, depth + 1);
    if (Array.isArray(value.errors)) value.errors.slice(0, 10).forEach(e => visit(e, depth + 1));
  }
  visit(error);
  return { error_code: [...codes][0] || null, error_cause_codes: [...codes],
    client_aborted: signal.aborted && (error === signal.reason || error.name === 'AbortError') };
}
function effectiveSteadySeconds(steadyStart, deadline, stoppedAt, now) {
  return Math.max(0, (Math.min(deadline, stoppedAt ?? now, now) - steadyStart) / 1000);
}
function publicLoadPassed(maxPassed, stopReason, health) {
  return maxPassed === 1000 && !stopReason && health.status === 200 && health.elapsed_ms <= 3000;
}
if (process.argv.includes('--self-test')) {
  assert.equal(quantile([9, 1, 2, 3], .95), 9);
  assert.equal(validate('ATTRACTION', 200, '{"data":{"items":[]}}'), false);
  assert.equal(validate('RAIL', 200, '{"data":{"items":[{"external_live":true}]}}'), false);
  assert.equal(validate('FLIGHT', 500, '{}'), false);
  assert.equal(summarize([{ elapsed_ms: 5, ok: false, status: 200, semantic_ok: false }]).semantic_errors, 1);
  const controller = new AbortController();
  const transportFailure = new TypeError('fetch failed', { cause: new AggregateError([
    Object.assign(new Error('socket'), { code: 'ECONNRESET' }),
    Object.assign(new Error('connect'), { code: 'UND_ERR_CONNECT_TIMEOUT' })]) });
  assert.deepEqual(errorDetails(transportFailure, controller.signal).error_cause_codes, ['ECONNRESET', 'UND_ERR_CONNECT_TIMEOUT']);
  controller.abort();
  assert.equal(errorDetails(controller.signal.reason, controller.signal).client_aborted, true);
  assert.equal(errorDetails(new DOMException('timeout', 'TimeoutError'), controller.signal).client_aborted, false);
  assert.equal(errorDetails(transportFailure, controller.signal).client_aborted, false);
  assert.equal(effectiveSteadySeconds(10000, 130000, 12093, 19000), 2.093);
  assert.equal(effectiveSteadySeconds(10000, 130000, null, 130001), 120);
  assert.equal(effectiveSteadySeconds(10000, 130000, 9000, 19000), 0);
  assert.equal(publicLoadPassed(1000, null, {status: 200, elapsed_ms: 100}), true);
  assert.equal(publicLoadPassed(1000, 'POST_STAGE_HEALTH_DEGRADED', {status: 200, elapsed_ms: 100}), false);
  assert.equal(publicLoadPassed(1000, null, {status: 503, elapsed_ms: 100}), false);
  console.log('SELF_TEST_PASS');
  process.exit(0);
}
if (!process.argv.includes('--run')) {
  console.log(JSON.stringify({ mode: 'PLAN_ONLY', base: BASE, identity: IDENTITY, plan: PLAN, thresholds: THRESHOLDS }, null, 2));
  process.exit(0);
}
const runId = 'depth48-public-load-' + iso().replace(/[-:.]/g, '');
const out = path.resolve(process.env.GO_LOAD_OUTPUT || path.join(os.tmpdir(), runId));
fs.mkdirSync(out, { recursive: true });
const rawFile = fs.openSync(path.join(out, 'requests.ndjson'), 'wx');
const report = { run_id: runId, started_at: iso(), target: BASE, identity: IDENTITY,
  workload: 'ANONYMOUS_PROTOCOL_SEARCH_AND_ENTRY_PAGES', authenticated_users: 0,
  role_allocation: '90% consumer searches; 8% supplier login page; 2% admin login page',
  think_time_seconds: [3, 7], plan: PLAN, thresholds: THRESHOLDS, stages: [],
  orders_created: 0, payments_attempted: 0, application_services_changed: false,
  generator: { node: process.version, platform: process.platform, cpus: os.cpus().length,
    total_memory_bytes: os.totalmem() }, monitor: [], samples: {},
  gates: { authenticated_1000_users: 'HOLD', three_end_login_ux: 'HOLD',
    six_vertical_transaction_closed_loop: 'HOLD', sealed_node: 'HOLD', final_release: 'HOLD' },
  limitations: ['No authenticated supplier/admin operations or order lifecycle',
    'No live image/DB-head verification or HK host CPU/RAM/DB/queue telemetry',
    'Synthetic offer data and a small set of destinations; not real provider capacity',
    'Server metrics are cumulative process-wide values, not this run alone'] };
let allRows = [], stopReason = null, stopAtMs = null, inFlight = 0, maxInFlight = 0, active = 0;
const abort = new AbortController();
const save = () => fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
function stop(reason) { if (!stopReason) { stopReason = reason; stopAtMs = Date.now(); abort.abort(); console.log(JSON.stringify({ abort: reason, at: iso() })); } }
async function probe(name, route) {
  const start = performance.now();
  try {
    const r = await fetch(BASE + route, { redirect: 'error', signal: AbortSignal.timeout(5000), headers: { 'User-Agent': 'GO-Staging-Acceptance/1.0', 'X-Request-ID': runId + '-' + name } });
    const body = await r.text();
    const item = { name, at: iso(), status: r.status, elapsed_ms: performance.now() - start, body };
    report.monitor.push(item); save(); return item;
  } catch (e) { const item = { name, at: iso(), status: 0, error: String(e), elapsed_ms: performance.now() - start }; report.monitor.push(item); save(); return item; }
}
async function request(stage, vu, iteration, kind, route, body) {
  const id = `${runId}-${stage}-${vu}-${iteration}`;
  const payload = body ? JSON.stringify(body) : undefined;
  const row = { stage, vu, iteration, kind, path: route, method: body ? 'POST' : 'GET', request_id: id, started_at: iso(), started_ms: Date.now(), payload_sha256: sha(payload || '') };
  const start = performance.now(); ++inFlight; maxInFlight = Math.max(maxInFlight, inFlight);
  try {
    const r = await fetch(BASE + route, { method: row.method, body: payload, redirect: 'error',
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': id, 'Idempotency-Key': id, 'User-Agent': 'GO-Staging-Acceptance/1.0' },
      signal: AbortSignal.any([AbortSignal.timeout(THRESHOLDS.request_timeout_ms), abort.signal]) });
    const text = await r.text(); row.status = r.status; row.response_request_id = r.headers.get('x-request-id');
    row.response_sha256 = sha(text); row.semantic_ok = validate(kind, r.status, text);
    row.ok = row.status === 200 && row.semantic_ok && row.response_request_id === id;
    if (!report.samples[kind] || !row.ok) {
      const sample = `${stage}-${vu}-${iteration}-${kind}.txt`;
      fs.writeFileSync(path.join(out, sample), text);
      row.sample_file = sample; report.samples[kind] ??= sample;
    }
    if (row.status === 429) stop('RATE_LIMIT_429');
  } catch (e) { row.status = 0; row.ok = false; row.semantic_ok = false; row.error = `${e.name}: ${e.message}`; Object.assign(row, errorDetails(e, abort.signal)); }
  finally { --inFlight; row.elapsed_ms = Math.round((performance.now() - start) * 100) / 100; row.finished_ms = Date.now(); allRows.push(row); fs.writeSync(rawFile, JSON.stringify(row) + '\n'); }
  if (allRows.length >= THRESHOLDS.max_requests) stop('REQUEST_BUDGET_EXHAUSTED');
  return row;
}
try {
  const policy = await probe('environment', '/bff/auth/policy');
  if (policy.status !== 200 || JSON.parse(policy.body).data.environment !== 'staging') throw new Error('STAGING_ENVIRONMENT_NOT_VERIFIED');
  for (const kind of VERTICALS) {
    const [route, body] = criteria(kind, 0);
    const r = await request(1, 0, VERTICALS.indexOf(kind), kind, route, body);
    if (!r.ok) throw new Error('PREFLIGHT_FAILED_' + kind);
  }
  await probe('metrics_before', '/metrics');
  for (const spec of PLAN) {
    if (stopReason) break;
    const started = Date.now(), rampMs = Math.min(10000, spec.vus * 40);
    const steadyStart = started + rampMs, deadline = steadyStart + spec.seconds * 1000;
    const s = { vus: spec.vus, started_at: iso(), started_ms: started, ramp_ms: rampMs, requested_steady_seconds: spec.seconds, resources: [], interval_activity: [] };
    report.stages.push(s); let badWindows = 0, lastTick = Date.now(), lastLog = started;
    let lastCpu = process.cpuUsage(), lastResource = started;
    console.log(JSON.stringify({ stage_start: spec.vus, out, at: iso() }));
    const timer = setInterval(() => {
      const now = Date.now(), lag = Math.max(0, now - lastTick - 1000); lastTick = now;
      const recent = allRows.filter(x => x.stage === spec.vus && x.finished_ms > now - THRESHOLDS.abort_window_ms && !x.client_aborted);
      if (recent.length >= 30 && now >= steadyStart) {
        const w = summarize(recent);
        badWindows = w.p95_ms > THRESHOLDS.abort_p95_ms || w.error_rate > THRESHOLDS.abort_error_rate ? badWindows + 1 : 0;
        if (badWindows >= THRESHOLDS.abort_consecutive_checks) stop('SUSTAINED_LATENCY_OR_ERRORS_AT_' + spec.vus);
      }
      if (now - lastLog >= 10000) {
        const cpu = process.cpuUsage(), dt = (now - lastResource) * 1000;
        const resource = { at: iso(), active_vus: active, in_flight: inFlight, event_loop_lag_ms: lag, rss_bytes: process.memoryUsage().rss, host_free_bytes: os.freemem(), generator_cpu_cores: ((cpu.user - lastCpu.user) + (cpu.system - lastCpu.system)) / dt };
        s.resources.push(resource); lastCpu = cpu; lastResource = now;
        s.interval_activity.push({ at: iso(), successful_distinct_vus_last_15s: new Set(recent.filter(r => r.ok).map(r => r.vu)).size });
        console.log(JSON.stringify({ checkpoint: spec.vus, active_vus: active, in_flight: inFlight, ...summarize(recent) }));
        save(); lastLog = now;
      }
      if (lag > 1000) stop('GENERATOR_EVENT_LOOP_LAG');
    }, 1000);
    try {
      await Promise.all(Array.from({ length: spec.vus }, async (_, vu) => {
        await sleep(rampMs * vu / spec.vus);
        if (stopReason) return;
        ++active; let iteration = 0;
        try {
          while (!stopReason && Date.now() < deadline) {
            const bucket = vu % 100;
            const kind = bucket >= 98 ? 'ADMIN_ENTRY' : bucket >= 90 ? 'SUPPLIER_ENTRY' : VERTICALS[(vu + iteration) % 6];
            const [route, body] = kind === 'ADMIN_ENTRY' ? ['/go-admin/'] : kind === 'SUPPLIER_ENTRY' ? ['/supplier-console/'] : criteria(kind, vu);
            await request(spec.vus, vu, iteration++, kind, route, body);
            if (!stopReason) await sleep(Math.min(3000 + ((vu * 977 + iteration * 137) % 4001), Math.max(0, deadline - Date.now())));
          }
        } finally { --active; }
      }));
    } finally { clearInterval(timer); }
    const rows = allRows.filter(x => x.stage === spec.vus && !x.client_aborted), steady = rows.filter(x => x.started_ms >= steadyStart && x.started_ms < deadline);
    const measuredSteadySeconds = effectiveSteadySeconds(steadyStart, deadline, stopAtMs, Date.now());
    Object.assign(s, { finished_at: iso(), actual_elapsed_seconds: (Date.now() - started) / 1000,
      summary: summarize(rows), steady_summary: summarize(steady), successful_distinct_vus: new Set(steady.filter(x => x.ok).map(x => x.vu)).size,
      measured_steady_seconds: measuredSteadySeconds,
      stopped_at: stopAtMs ? new Date(stopAtMs).toISOString() : null,
      steady_rps: measuredSteadySeconds ? steady.filter(x => x.finished_ms <= Math.min(deadline, stopAtMs ?? deadline)).length / measuredSteadySeconds : null,
      per_kind: Object.fromEntries([...new Set(rows.map(x => x.kind))].map(k => [k, summarize(rows.filter(x => x.kind === k))])), abort: stopReason });
    s.passed = !stopReason && s.successful_distinct_vus === spec.vus && steady.length > 0 && s.steady_summary.p95_ms <= THRESHOLDS.stage_p95_ms && s.steady_summary.p99_ms <= THRESHOLDS.stage_p99_ms && s.steady_summary.error_rate <= THRESHOLDS.unexpected_error_rate && s.steady_summary.semantic_errors === 0;
    console.log(JSON.stringify({ stage_result: spec.vus, passed: s.passed, ...s.steady_summary })); save();
    const h = await probe('health_after_' + spec.vus, '/health');
    if (h.status !== 200 || h.elapsed_ms > 3000) stop('POST_STAGE_HEALTH_DEGRADED');
    if (!s.passed && !stopReason) stop('STAGE_ACCEPTANCE_FAILED_AT_' + spec.vus);
  }
} catch (e) { stop(String(e.message)); }
finally {
  await probe('metrics_after', '/metrics'); const finalHealth = await probe('final_health', '/health');
  fs.closeSync(rawFile);
  report.finished_at = iso(); report.stop_reason = stopReason; report.stop_at = stopAtMs ? new Date(stopAtMs).toISOString() : null;
  report.client_aborted_requests = allRows.filter(x => x.client_aborted).length;
  report.summary = summarize(allRows.filter(x => !x.client_aborted));
  report.maximum_in_flight_requests = maxInFlight;
  report.maximum_stage_started = Math.max(0, ...report.stages.map(x => x.vus));
  report.maximum_stage_passed = Math.max(0, ...report.stages.filter(x => x.passed).map(x => x.vus));
  report.gates.public_search_1000_vus = publicLoadPassed(report.maximum_stage_passed, stopReason, finalHealth) ? 'SCOPED_PASS' : 'NOT_PASSED';
  report.evidence_dir = out; save();
  const manifest = Object.fromEntries(fs.readdirSync(out).filter(n => n !== 'sha256.json').map(n => [n, sha(fs.readFileSync(path.join(out, n)))]));
  fs.writeFileSync(path.join(out, 'sha256.json'), JSON.stringify(manifest, null, 2));
  console.log('FINAL_REPORT=' + JSON.stringify(report));
}
