// Hosted operator edition: every HTML, asset, API and download crosses backend authentication.
// Keep the archived public desktop Worker separate from this private release.
const origin = 'http://127.0.0.1:8892';

function failure(code, detail) {
  return Response.json({code, detail}, {status: 503, headers: {'Cache-Control': 'no-store', 'Retry-After': '15'}});
}

export async function handle(request, env) {
  if (!/^[a-f0-9]{64}$/.test(env.RELEASE_ID || '')) return failure('release_unconfigured', '릴리즈 설정을 확인하세요.');
  const url = new URL(request.url);
  if (url.pathname !== '/health/live' && !request.headers.get('Cf-Access-Jwt-Assertion')) {
    return Response.json({code: 'operator_auth_required', detail: '운영자 인증이 필요합니다.'},
      {status: 401, headers: {'Cache-Control': 'no-store'}});
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
    const source = request.headers.get('Origin');
    if (source && source !== url.origin) return new Response(null, {status: 403});
    const length = Number(request.headers.get('Content-Length') || 0);
    if (length > 12 * 1024 * 1024) return new Response(null, {status: 413});
  }
  const headers = new Headers(request.headers);
  headers.delete('Host');
  headers.set('X-Forwarded-Host', url.host);
  headers.set('X-Forwarded-Proto', 'https');
  let response;
  try {
    response = await env.BACKEND.fetch(new Request(new URL(url.pathname + url.search, origin), {
      method: request.method, headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      duplex: 'half',
      redirect: 'manual',
    }));
  } catch {
    return failure('origin_unavailable', '상시 업무 서버의 연결 상태를 확인하세요.');
  }
  if (response.status >= 502 && !response.headers.get('X-Gongmudam-Release')) {
    return failure('origin_unavailable', '상시 업무 서버의 연결 상태를 확인하세요.');
  }
  // Rejected identities reveal no code/data. Authentication still happens at the origin.
  if (![401, 403].includes(response.status) && url.pathname !== '/health/live' &&
      response.headers.get('X-Gongmudam-Release') !== env.RELEASE_ID) {
    return failure('release_mismatch', '화면과 업무 서버의 릴리즈가 다릅니다. 검증한 릴리즈를 연결하세요.');
  }
  const returned = new Headers(response.headers);
  returned.set('Cache-Control', 'no-store');
  const location = returned.get('Location');
  if (location?.startsWith(origin + '/')) returned.set('Location', location.slice(origin.length));
  return new Response(response.body, {status: response.status, statusText: response.statusText, headers: returned});
}

export default {fetch: handle};
