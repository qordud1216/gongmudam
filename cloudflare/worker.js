const STATIC_PREFIX = '/desktop/';

export function offlineResponse(api = false) {
  const text = '업무 서버에 연결하지 못했어요. 연결 PC와 공무담 서버가 켜져 있는지 확인한 뒤 다시 시도해 주세요.';
  return new Response(api ? JSON.stringify({detail: text, code: 'origin_unavailable'}) :
    `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>공무담 연결 확인</title><body><main><h1>업무 서버 연결이 필요해요</h1><p>${text}</p><p><a href="/desktop/">공무담 바탕화면으로</a></p></main></body></html>`,
    {status: 503, headers: {'Content-Type': api ? 'application/json; charset=utf-8' : 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Retry-After': '15'}});
}

export async function handle(request, env) {
  const url = new URL(request.url);
  if (url.pathname === '/') return Response.redirect(url.origin + '/desktop/?variant=B', 307);
  if (url.pathname.startsWith(STATIC_PREFIX)) {
    if (!['GET', 'HEAD'].includes(request.method)) return new Response(null, {status: 405});
    if (url.pathname === STATIC_PREFIX) url.pathname += 'index.html';
    return env.ASSETS.fetch(new Request(url, request));
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
    const origin = request.headers.get('Origin');
    if (origin && origin !== url.origin) return Response.json({detail: '다른 사이트의 요청은 허용하지 않습니다.'}, {status: 403});
    const length = Number(request.headers.get('Content-Length') || 0);
    if (length > 12 * 1024 * 1024) return Response.json({detail: '공개 시연 업로드 한도는 12MB입니다.'}, {status: 413});
  }
  const target = new URL(url.pathname + url.search, 'http://127.0.0.1:8892');
  const headers = new Headers(request.headers);
  // Origin was validated above; the private service sees its own loopback host.
  headers.delete('Origin');
  headers.delete('Host');
  headers.set('X-Forwarded-Host', url.host);
  headers.set('X-Forwarded-Proto', 'https');
  try {
    const response = await env.BACKEND.fetch(new Request(target, {method: request.method,
      headers, body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      duplex: 'half',
      redirect: 'manual'}));
    if (response.status >= 502) return offlineResponse(url.pathname.startsWith('/api/'));
    const result = new Response(response.body, response);
    const location = result.headers.get('Location');
    if (location) {
      const redirect = new URL(location, target);
      if (redirect.origin === target.origin) result.headers.set('Location', redirect.pathname + redirect.search + redirect.hash);
    }
    result.headers.set('Cache-Control', 'no-store');
    result.headers.set('X-Content-Type-Options', 'nosniff');
    return result;
  } catch {
    return offlineResponse(url.pathname.startsWith('/api/'));
  }
}

export default {fetch: handle};
