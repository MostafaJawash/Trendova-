// Fixed workload profile for Requirement 3. Do NOT edit between runs: every
// before/after comparison must use exactly this file. Behaviour is selected only
// through environment variables (RUN_LABEL, ONLY, QUICK, DEEP_PAGE_MODE).
//
// Layout: warm-up, then one isolated scenario per endpoint (run sequentially so
// each endpoint is measured alone), then a mixed 90% read / 10% write profile.
// Read scenarios are closed-loop (constant VUs): req/s = capacity, latency = under
// saturation. create_order is open-loop at a low fixed rate to measure WRITE cost.
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

const BASE_URL = __ENV.BASE_URL || 'http://app:8000/api/v1';
const LABEL = __ENV.RUN_LABEL || 'adhoc';
const ONLY = __ENV.ONLY || '';                         // list|detail|search|my_orders|create_order|mixed
const QUICK = __ENV.QUICK === '1';                     // 20s smoke profile (run_phase1.py)
const DEEP_MODE = __ENV.DEEP_PAGE_MODE || 'offset';    // offset (default) | keyset (uses next_cursor)
const CUSTOMERS = 50;                                   // customer001..customer050@loadtest.example
const PASSWORD = __ENV.CUSTOMER_PASSWORD || 'LoadTest123!';
const CATEGORIES = 40, PRODUCTS = Number(__ENV.PRODUCTS || 20000);
const DEEP_PAGE = 900, DEEP_LIMIT = 20;                // offset 17,980

// Same vocabulary as scripts/seed.py.
const NOUNS = ['Headphones', 'Keyboard', 'Backpack', 'Lamp', 'Blender', 'Monitor', 'Notebook', 'Speaker', 'Charger', 'Jacket',
  'Sneakers', 'Watch', 'Camera', 'Router', 'Mug', 'Chair', 'Desk', 'Kettle', 'Tablet', 'Sunglasses'];
const ADJECTIVES = ['Wireless', 'Portable', 'Ergonomic', 'Premium', 'Compact', 'Smart', 'Classic', 'Rugged', 'Ultra', 'Eco',
  'Vintage', 'Modern', 'Deluxe', 'Mini', 'Pro'];

const D = QUICK
  ? { warmup: 5, scen: 20, mixed: 20 }
  : { warmup: 20, scen: 30, mixed: 60 };
const VUS = QUICK ? 5 : 20, MIXED_VUS = QUICK ? 5 : 30, CREATE_RATE = 5;
const GAP = 3;

const ALL = ['list', 'detail', 'search', 'my_orders', 'create_order', 'mixed'];
const selected = ONLY ? ALL.filter((n) => n === ONLY) : ALL;
if (ONLY && selected.length === 0) throw new Error('unknown ONLY=' + ONLY);

const closed = (execName, vus, dur, start) => ({ executor: 'constant-vus', exec: execName, vus, duration: dur + 's', startTime: start + 's', gracefulStop: '5s' });
const scenarios = {};
let cursor = 0;
scenarios.warmup = closed('warmup', Math.min(10, VUS), D.warmup, cursor);
cursor += D.warmup + GAP;
const SCEN_DUR = {};
for (const name of selected) {
  const dur = name === 'mixed' ? D.mixed : D.scen;
  SCEN_DUR[name] = dur;
  if (name === 'create_order') {
    scenarios[name] = { executor: 'constant-arrival-rate', exec: 'createOrder', rate: CREATE_RATE, timeUnit: '1s', duration: dur + 's', preAllocatedVUs: 10, maxVUs: 40, startTime: cursor + 's', gracefulStop: '5s' };
  } else if (name === 'mixed') {
    scenarios[name] = closed('mixed', MIXED_VUS, dur, cursor);
  } else {
    scenarios[name] = closed({ list: 'listScenario', detail: 'detailScenario', search: 'searchScenario', my_orders: 'myOrders' }[name], VUS, dur, cursor);
  }
  cursor += dur + GAP;
}

// Dummy thresholds exist only so per-endpoint sub-metrics appear in the summary.
const TAGS = ['warmup', 'list', 'list_deep', 'detail', 'search', 'my_orders', 'create_order',
  'mixed_list', 'mixed_detail', 'mixed_search', 'mixed_orders', 'mixed_create'];
const thresholds = {};
for (const t of TAGS) {
  thresholds[`http_req_duration{endpoint:${t}}`] = ['max>=0'];
  thresholds[`http_req_failed{endpoint:${t}}`] = ['rate>=0'];
  thresholds[`http_reqs{endpoint:${t}}`] = ['count>=0'];
}
thresholds['http_req_duration{scenario:mixed}'] = ['max>=0'];
thresholds['http_req_failed{scenario:mixed}'] = ['rate>=0'];
thresholds['http_reqs{scenario:mixed}'] = ['count>=0'];

export const options = {
  scenarios,
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  setupTimeout: '300s',
  discardResponseBodies: false,
};

// ---- deterministic pseudo-random helpers (no Math.random: runs are comparable) ----
function rnd(salt) {
  let x = (exec.vu.idInTest * 2654435761 + exec.vu.iterationInScenario * 40503 + salt * 9973) >>> 0;
  x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0;
  return (x % 1000003) / 1000003;
}
const skew = (u, n, p) => 1 + Math.floor(n * Math.pow(u, p)); // low ids are "hot"
const pick = (arr, u) => arr[Math.floor(u * arr.length) % arr.length];

export function setup() {
  const tokens = [];
  // Read-only endpoints need a single token; orders scenarios need all customers.
  const count = (ONLY === 'list' || ONLY === 'detail' || ONLY === 'search') ? 1 : CUSTOMERS;
  for (let i = 1; i <= count; i++) {
    const email = `customer${String(i).padStart(3, '0')}@loadtest.example`;
    const r = http.post(`${BASE_URL}/auth/login`, JSON.stringify({ email, password: PASSWORD }), { headers: { 'Content-Type': 'application/json' }, tags: { endpoint: 'setup' } });
    if (r.status !== 200) throw new Error(`login failed for ${email}: ${r.status} ${r.body}`);
    tokens.push(r.json('access_token'));
  }
  let deepCursor = null;
  if (DEEP_MODE === 'keyset') {
    const r = http.get(`${BASE_URL}/products?limit=${DEEP_LIMIT}&page=${DEEP_PAGE - 1}`, { headers: { Authorization: `Bearer ${tokens[0]}` }, tags: { endpoint: 'setup' } });
    deepCursor = r.json('next_cursor');
    if (!deepCursor) throw new Error('DEEP_PAGE_MODE=keyset but the API returned no next_cursor');
  }
  return { tokens, deepCursor };
}

const auth = (data, i) => ({ Authorization: `Bearer ${data.tokens[i % data.tokens.length]}` });
const get = (data, url, endpoint, userIdx = 0) =>
  http.get(`${BASE_URL}${url}`, { headers: auth(data, userIdx), tags: { endpoint } });

function doList(data, prefix) {
  const u = rnd(1);
  if (u < 0.15) { // deep page, no category filter
    const url = DEEP_MODE === 'keyset'
      ? `/products?limit=${DEEP_LIMIT}&cursor=${encodeURIComponent(data.deepCursor)}`
      : `/products?limit=${DEEP_LIMIT}&page=${DEEP_PAGE}`;
    return check(get(data, url, prefix === 'mixed_' ? 'mixed_list' : 'list_deep'), { 'list deep 200': (r) => r.status === 200 });
  }
  const cat = skew(rnd(2), CATEGORIES, 2.5);
  const page = u < 0.7 ? 1 : 2 + Math.floor(rnd(3) * 4);
  return check(get(data, `/products?category=${cat}&limit=20&page=${page}`, prefix === 'mixed_' ? 'mixed_list' : 'list'), { 'list 200': (r) => r.status === 200 });
}
function doDetail(data, prefix) {
  const id = skew(rnd(4), PRODUCTS, 2.0);
  return check(get(data, `/products/${id}`, prefix === 'mixed_' ? 'mixed_detail' : 'detail', exec.vu.idInTest), { 'detail 200': (r) => r.status === 200 });
}
function doSearch(data, prefix) {
  const term = (rnd(5) < 0.5 ? pick(NOUNS, rnd(6)) : pick(ADJECTIVES, rnd(7))).toLowerCase();
  return check(get(data, `/products?search=${term}&limit=20`, prefix === 'mixed_' ? 'mixed_search' : 'search'), { 'search 200': (r) => r.status === 200 });
}
function doMyOrders(data, prefix) {
  const idx = Math.floor(rnd(8) * data.tokens.length);
  const page = rnd(9) < 0.8 ? 1 : 2;
  return check(get(data, `/orders?limit=10&page=${page}`, prefix === 'mixed_' ? 'mixed_orders' : 'my_orders', idx), { 'orders 200': (r) => r.status === 200 });
}
function doCreate(data, prefix) {
  const idx = Math.floor(rnd(10) * data.tokens.length);
  const n = 1 + Math.floor(rnd(11) * 3);
  const items = [], seen = {};
  for (let i = 0; i < n; i++) {
    const pid = skew(rnd(12 + i), PRODUCTS, 2.0);
    if (!seen[pid]) { seen[pid] = 1; items.push({ product_id: pid, quantity: 1 }); }
  }
  const r = http.post(`${BASE_URL}/orders`, JSON.stringify({ items }), {
    headers: { ...auth(data, idx), 'Content-Type': 'application/json' },
    tags: { endpoint: prefix === 'mixed_' ? 'mixed_create' : 'create_order' },
  });
  return check(r, { 'create 201': (x) => x.status === 201 });
}

export function warmup(data) {
  const u = rnd(20);
  const t = { endpoint: 'warmup' };
  if (u < 0.4) http.get(`${BASE_URL}/products?category=${skew(rnd(21), CATEGORIES, 2.5)}&limit=20`, { headers: auth(data, 0), tags: t });
  else if (u < 0.7) http.get(`${BASE_URL}/products/${skew(rnd(22), PRODUCTS, 2.0)}`, { headers: auth(data, 0), tags: t });
  else http.get(`${BASE_URL}/orders?limit=10`, { headers: auth(data, exec.vu.idInTest), tags: t });
}
export function listScenario(data) { doList(data, ''); }
export function detailScenario(data) { doDetail(data, ''); }
export function searchScenario(data) { doSearch(data, ''); }
export function myOrders(data) { doMyOrders(data, ''); }
export function createOrder(data) { doCreate(data, ''); }
export function mixed(data) {
  const u = rnd(30);
  if (u < 0.40) doList(data, 'mixed_');
  else if (u < 0.70) doDetail(data, 'mixed_');
  else if (u < 0.80) doSearch(data, 'mixed_');
  else if (u < 0.90) doMyOrders(data, 'mixed_');
  else doCreate(data, 'mixed_');
}

// ---- summary -> results/<label>.json ----
function stat(m, key) { return m && m.values ? m.values[key] : null; }
export function handleSummary(data) {
  const m = data.metrics;
  const out = { label: LABEL, only: ONLY || null, quick: QUICK, deep_page_mode: DEEP_MODE, generated_at: new Date().toISOString(), endpoints: {} };
  const scenOf = (tag) => SCEN_DUR[tag.startsWith('mixed_') ? 'mixed' : tag === 'list_deep' ? 'list' : tag] || null;
  const add = (name, durKey, dur) => {
    const d = m[`http_req_duration{${durKey}}`];
    const c = m[`http_reqs{${durKey}}`];
    const f = m[`http_req_failed{${durKey}}`];
    const count = stat(c, 'count') || 0;
    if (!count) return;
    out.endpoints[name] = {
      count, req_per_s: dur ? +(count / dur).toFixed(2) : null,
      avg_ms: stat(d, 'avg'), p50_ms: stat(d, 'med'), p90_ms: stat(d, 'p(90)'), p95_ms: stat(d, 'p(95)'), p99_ms: stat(d, 'p(99)'), max_ms: stat(d, 'max'),
      error_rate: stat(f, 'rate'),
    };
  };
  for (const t of TAGS) if (t !== 'warmup') add(t, `endpoint:${t}`, scenOf(t));
  add('mixed_total', 'scenario:mixed', SCEN_DUR.mixed);
  const dropped = m.dropped_iterations;
  out.dropped_iterations = dropped ? dropped.values.count : 0;
  return { [`/loadtest/results/${LABEL}.json`]: JSON.stringify(out, null, 2) };
}
