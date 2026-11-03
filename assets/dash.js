/*
 * A tiny stand-in for the claude.ai dashboard runtime, so the dashboard
 * pages run as a normal website: loads datasets from data/<id>.json,
 * runs calculations, and keeps filters (remembered per page in this browser).
 *
 *   dash.data(id)        -> {status, data, message}
 *   dash.onData(fn)      -> run fn now and whenever data, filters, width or theme change
 *   dash.calc(id, {inputs, fn})
 *   dash.params() / dash.setParams({...}) / dash.resetParams()
 *   dash.colors          -> series colours resolved from the theme
 */
(function () {
  const cache = {};
  const calcs = {};
  const listeners = [];
  const defaults = Object.assign({}, window.DASH_PARAMS || {});
  const storeKey = 'params:' + location.pathname;
  let params = Object.assign({}, defaults);
  try { Object.assign(params, JSON.parse(localStorage.getItem(storeKey) || '{}')); } catch (e) { /* ignore */ }

  let queued = false;
  function fire() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    });
  }

  let loadedAt = Date.now();
  function fetchSet(id) {
    return fetch('data/' + id + '.json', { cache: 'no-cache' })
      .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then((d) => Array.isArray(d) ? d : (d.rows || d.data || d.results || []));
  }
  function load(id) {
    if (cache[id]) return;
    cache[id] = { status: 'loading', data: [] };
    fetchSet(id)
      .then((rows) => { cache[id] = { status: 'ok', data: rows }; fire(); })
      .catch((e) => { cache[id] = { status: 'error', data: [], message: String(e) }; fire(); });
  }
  // Fetch every dataset again, keeping what's on screen until the new copy arrives.
  function reloadAll() {
    loadedAt = Date.now();
    const ids = Object.keys(cache);
    ids.forEach((id) => { if (cache[id].status === 'ok') cache[id].refreshing = true; });
    return Promise.all(ids.map((id) => fetchSet(id)
      .then((rows) => { cache[id] = { status: 'ok', data: rows }; })
      .catch((e) => { if (cache[id].status !== 'ok') cache[id] = { status: 'error', data: [], message: String(e) }; else cache[id].refreshing = false; })))
      .then(() => { fire(); window.dispatchEvent(new Event('dash-reloaded')); });
  }

  const calcMemo = {};
  function calcData(id) {
    const c = calcs[id];
    const ins = c.inputs.map((i) => data(i));
    if (ins.some((x) => x.status === 'error')) return { status: 'error', data: [] };
    if (ins.some((x) => x.status !== 'ok')) return { status: 'loading', data: [] };
    const memo = calcMemo[id];
    if (memo && memo.ins.length === ins.length && memo.ins.every((x, i) => x === ins[i].data)) return memo.out;
    let out;
    try { out = { status: 'ok', data: c.fn(...ins.map((x) => x.data)) }; } catch (e) { console.error(e); out = { status: 'error', data: [] }; }
    calcMemo[id] = { ins: ins.map((x) => x.data), out };
    return out;
  }

  function data(id) {
    if (calcs[id]) return calcData(id);
    load(id);
    const c = cache[id];
    return Object.assign({ refreshing: false, meta: [] }, c, { rows: c.data });
  }

  function save() { try { localStorage.setItem(storeKey, JSON.stringify(params)); } catch (e) { /* ignore */ } }

  function resolveColors() {
    const cs = getComputedStyle(document.documentElement);
    const out = [];
    for (let i = 1; i <= 8; i++) out.push((cs.getPropertyValue('--series-' + i) || '').trim() || '#888');
    return out;
  }

  window.dash = {
    data,
    onData(fn) { listeners.push(fn); try { fn(); } catch (e) { console.error(e); } },
    calc(id, spec) { calcs[id] = spec; },
    loader() {},
    params() { return Object.assign({}, params); },
    setParams(o) { Object.assign(params, o); save(); fire(); },
    resetParams() { params = Object.assign({}, defaults); save(); fire(); },
    setLink(name) { try { history.replaceState(null, '', '#' + name); } catch (e) { /* ignore */ } },
    refresh() { return reloadAll(); },
    get colors() { return resolveColors(); },
  };

  // An installed app can sit in the background for days without reloading:
  // fetch fresh data whenever it comes back to the screen, and every 30 minutes while open.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && Date.now() - loadedAt > 2 * 60 * 1000) reloadAll();
  });
  window.addEventListener('pageshow', (e) => { if (e.persisted) reloadAll(); });
  setInterval(() => { if (document.visibilityState === 'visible') reloadAll(); }, 30 * 60 * 1000);

  let w = window.innerWidth;
  window.addEventListener('resize', () => { if (Math.abs(window.innerWidth - w) > 20) { w = window.innerWidth; fire(); } });
  try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', fire); } catch (e) { /* ignore */ }
})();
