// Shared native transport; tests inject offline dependencies into this same code.
type Dependencies = {
  baseUrl: string; fetch: typeof fetch; online: () => Promise<boolean>;
  accessToken: () => Promise<string | null>; refreshToken: () => Promise<string | null>;
  saveTokens: (access: string, refresh: string) => Promise<void>; clearTokens: () => Promise<void>;
  newKey: () => string; timeoutMs?: number;
};
export class RequestError extends Error {
  status: number; uncertain: boolean;
  constructor(code: string, status = 0, uncertain = false) {
    super(code); this.name = 'RequestError'; this.status = status; this.uncertain = uncertain;
  }
}
export function createTransport(d: Dependencies) {
  const base = d.baseUrl.replace(/\/$/, '');
  let generation = 0, writes: Promise<unknown> = Promise.resolve();
  let refreshing: {generation: number; promise: Promise<boolean>} | null = null;
  const listeners=new Set<()=>void>();
  const subscribe=(listener:()=>void)=>{listeners.add(listener);return ()=>{listeners.delete(listener);};};
  const version = () => generation;
  const current = (g: number) => { if (g !== generation) throw new RequestError('SESSION_CHANGED'); };
  const write = (g: number, action: () => Promise<void>) => {
    const result = writes.then(async () => { current(g); await action(); current(g); });
    writes = result.catch(() => {}); return result;
  };
  const clear = async () => { const g = ++generation;for(const listener of listeners)listener();await write(g, d.clearTokens); };
  async function send(path: string, init: RequestInit, g: number) {
    current(g);
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes(String(init.method || 'GET'));
    if (init.signal?.aborted) throw new RequestError('REQUEST_CANCELLED');
    const abort = new AbortController(), cancel = () => abort.abort();
    init.signal?.addEventListener('abort', cancel, {once: true});
    const timer = setTimeout(cancel, d.timeoutMs ?? 20000);
    try {
      const response = await d.fetch(base + path, {...init, signal: abort.signal});
      const raw = await response.text(); current(g);
      let body: any;
      try { body = raw ? JSON.parse(raw) : {}; }
      catch { throw new RequestError('INVALID_API_RESPONSE', response.status, mutating && response.ok); }
      return {response, body};
    } catch (error) {
      current(g);
      if (error instanceof RequestError) throw error;
      throw new RequestError(mutating ? 'NETWORK_RESULT_UNKNOWN' : 'NETWORK_REQUEST_FAILED', 0, mutating);
    } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', cancel); }
  }
  async function refresh(g: number, staleToken: string | null) {
    current(g);
    const tokenNow = await d.accessToken(); current(g);
    if (tokenNow && tokenNow !== staleToken) return true;
    if (refreshing?.generation === g) return refreshing.promise;
    const promise = (async () => {
      const token = await d.refreshToken(); current(g);
      if (!token) return false;
      const {response, body} = await send('/v1/mobile/auth/refresh', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({refresh_token: token}),
      }, g);
      if (!response.ok) {
        if ([401, 403].includes(response.status)) {await clear();throw new RequestError('SESSION_EXPIRED',401);}
        return false;
      }
      const pair = body?.data;
      if (typeof pair?.access_token !== 'string' || !pair.access_token || typeof pair.refresh_token !== 'string' || !pair.refresh_token)
        throw new RequestError('INVALID_TOKEN_RESPONSE');
      await write(g, () => d.saveTokens(pair.access_token, pair.refresh_token)); return true;
    })();
    refreshing = {generation: g, promise};
    try { return await promise; } finally { if (refreshing?.promise === promise) refreshing = null; }
  }
  async function request(path: string, init: RequestInit = {}, retry = true) {
    if (!path.startsWith('/v1/') || /[\\\s#]/.test(path) || path.includes('://')) throw new RequestError('INVALID_API_PATH');
    const g = generation, method = String(init.method || 'GET').toUpperCase();
    const authFlow = path.startsWith('/v1/mobile/auth/');
    const headers = new Headers(init.headers); headers.set('Content-Type', 'application/json');
    // Construct once: the key and body survive authentication refresh unchanged.
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !headers.has('Idempotency-Key')) headers.set('Idempotency-Key', d.newKey());
    headers.delete('Authorization');
    if (!await d.online()) throw new RequestError('NETWORK_OFFLINE'); current(g);
    const token = authFlow ? null : await d.accessToken(); current(g);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const prepared = {...init, method, headers};
    let result = await send(path, prepared, g);
    if (result.response.status === 401 && retry && !authFlow && token && await refresh(g, token)) {
      const next = await d.accessToken(); current(g);
      if (!next) throw new RequestError('SESSION_EXPIRED', 401);
      headers.set('Authorization', `Bearer ${next}`); result = await send(path, prepared, g);
    }
    current(g);
    if (!result.response.ok) {
      const value = result.body?.detail || result.body?.error?.code;
      throw new RequestError(typeof value === 'string' ? value : `HTTP_${result.response.status}`, result.response.status,
        !['GET', 'HEAD', 'OPTIONS'].includes(method) && result.response.status >= 500);
    }
    return result.body;
  }
  async function login(email: string, password: string) {
    await clear(); const g = generation;
    const result = await request('/v1/mobile/auth/login', {method: 'POST', body: JSON.stringify({email, password})}, false);
    const pair = result?.data;
    if (typeof pair?.access_token !== 'string' || !pair.access_token || typeof pair.refresh_token !== 'string' || !pair.refresh_token)
      throw new RequestError('INVALID_TOKEN_RESPONSE');
    await write(g, () => d.saveTokens(pair.access_token, pair.refresh_token)); return pair;
  }
  async function logout() {
    const g=generation;
    try { await request('/v1/consumer/auth/logout', {method: 'POST'}); }
    finally { if(g===generation)await clear(); }
  }
  return {request, login, logout, clear, version, subscribe};
}
