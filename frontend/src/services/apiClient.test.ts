/**
 * apiClient tests — verify the REAL backend wiring:
 * GET /health, GET /ready, POST /api/query.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiClient, ApiError } from './apiClient';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('apiClient', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('GET /health uses the correct URL', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok', service: 'manufacturaiq' }));
    const client = new ApiClient('http://localhost:8000');
    await client.checkHealth();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/health');
  });

  it('/health success maps to Online', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok', service: 'manufacturaiq' }));
    const client = new ApiClient('http://localhost:8000');
    await expect(client.checkConnection()).resolves.toBe('online');
  });

  it('network failure maps to Offline', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('fetch failed'));
    const client = new ApiClient('http://localhost:8000');
    await expect(client.checkConnection()).resolves.toBe('offline');
  });

  it('GET /ready uses the correct URL', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: 'ready', service: 'manufacturaiq', orchestrator: 'available' }),
    );
    const client = new ApiClient('http://localhost:8000');
    await client.checkReady();
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/ready');
  });

  it('POST /api/query uses the correct URL and POST method', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query_id: 'q1', status: 'pass' }));
    const client = new ApiClient('http://localhost:8000');
    await client.submitQuery({ query: 'hello' });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/query');
    expect(init.method).toBe('POST');
  });

  it('sends Content-Type application/json', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query_id: 'q1', status: 'pass' }));
    const client = new ApiClient('http://localhost:8000');
    await client.submitQuery({ query: 'hello' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('request body exactly matches the API type', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query_id: 'q1', status: 'pass' }));
    const client = new ApiClient('http://localhost:8000');
    const payload = {
      query: 'spindle vibration',
      machine_id: 'CNC-05',
      product_id: null,
      document_context: { manufacturer: 'Siemens' },
    };
    await client.submitQuery(payload);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual(payload);
  });

  it('optional fields omitted are preserved as absent (not fabricated)', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query_id: 'q1', status: 'pass' }));
    const client = new ApiClient('http://localhost:8000');
    await client.submitQuery({ query: 'minimal' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ query: 'minimal' });
  });

  it('returns the successful JSON response as-is', async () => {
    const body = { query_id: 'q1', status: 'pass', routing: {}, evidence: null, reasoning: null, review: null };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    const client = new ApiClient('http://localhost:8000');
    expect(await client.submitQuery({ query: 'x' })).toEqual(body);
  });

  it('HUMAN_REVIEW response does not mark backend Offline', async () => {
    const body = { query_id: 'q1', status: 'human_review', routing: {}, evidence: null, reasoning: null, review: null };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    const client = new ApiClient('http://localhost:8000');
    const result = await client.submitQuery({ query: 'x' });
    expect(result.status).toBe('human_review');
  });

  it('Gemini unavailable response does not mark backend Offline', async () => {
    const body = {
      query_id: 'q1',
      status: 'human_review',
      routing: {},
      evidence: null,
      reasoning: { provider_status: 'UNAVAILABLE', raw_answer: '', citations: [] },
      review: null,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));
    const client = new ApiClient('http://localhost:8000');
    const result = await client.submitQuery({ query: 'x' });
    expect(result.reasoning?.provider_status).toBe('UNAVAILABLE');
  });

  it('forwards AbortSignal', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query_id: 'q1' }));
    const client = new ApiClient('http://localhost:8000');
    const controller = new AbortController();
    await client.submitQuery({ query: 'x' }, { signal: controller.signal });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });

  it('handles HTTP 422 safely with a validation message', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'bad' }, 422));
    const client = new ApiClient('http://localhost:8000');
    const err = await client.submitQuery({ query: '' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as Error).message).toMatch(/validation/i);
  });

  it('handles HTTP 500 safely', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, 500));
    const client = new ApiClient('http://localhost:8000');
    const err = await client.submitQuery({ query: 'x' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it('handles network failure safely', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('fetch failed'));
    const client = new ApiClient('http://localhost:8000');
    const err = await client.submitQuery({ query: 'x' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as Error).message).toMatch(/unreachable/i);
  });

  it('rethrows AbortError without wrapping (stale-request support)', async () => {
    const abortErr = new DOMException('aborted', 'AbortError');
    fetchMock.mockRejectedValueOnce(abortErr);
    const client = new ApiClient('http://localhost:8000');
    const err = await client.submitQuery({ query: 'x' }).catch((e) => e);
    expect(err).toBe(abortErr);
  });

  it('has no mockData fallback in the client source', async () => {
    const { readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    const src = readFileSync(join(process.cwd(), 'src', 'services', 'apiClient.ts'), 'utf8');
    expect(src).not.toMatch(/mockData/i);
    expect(src).not.toMatch(/INITIAL_MESSAGES|INITIAL_CONVERSATIONS/);
  });

  it('VITE_API_BASE_URL joining does not create //api/query', () => {
    const client = new ApiClient('http://localhost:8000/');
    expect(client.baseUrl).toBe('http://localhost:8000');
    expect(`${client.baseUrl}/api/query`).toBe('http://localhost:8000/api/query');
  });
});

describe('apiClient documents', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('listDocuments uses GET /api/documents', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ documents: [], count: 0 }));
    const client = new ApiClient('http://localhost:8000');
    await client.listDocuments();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/documents');
    expect(init.method).toBe('GET');
  });

  it('getDocument uses the encoded document URL', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ document_id: 'USR-ABC' }));
    const client = new ApiClient('http://localhost:8000');
    await client.getDocument('USR-ABC');
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/documents/USR-ABC');
  });

  it('uploadDocument posts FormData without a manual Content-Type', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ document_id: 'USR-ABC', duplicate: false }));
    const client = new ApiClient('http://localhost:8000');
    const file = new File(['bytes'], 'manual.pdf', { type: 'application/pdf' });
    await client.uploadDocument(file);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/documents');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers['Content-Type']).toBeUndefined();
    expect((init.body as FormData).get('file')).toBe(file);
  });

  it('deleteDocument uses DELETE on the document URL', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ document_id: 'USR-ABC', deleted: true }));
    const client = new ApiClient('http://localhost:8000');
    await client.deleteDocument('USR-ABC');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/documents/USR-ABC');
    expect(init.method).toBe('DELETE');
  });

  it('maps 413 and 415 with status preserved', async () => {
    const client = new ApiClient('http://localhost:8000');
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'big' }, 413));
    const tooLarge = await client.uploadDocument(
      new File(['x'], 'a.pdf')).catch((error) => error);
    expect(tooLarge).toBeInstanceOf(ApiError);
    expect((tooLarge as ApiError).status).toBe(413);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'bad' }, 415));
    const badType = await client.uploadDocument(
      new File(['x'], 'a.txt')).catch((error) => error);
    expect((badType as ApiError).status).toBe(415);
  });

  it('maps server errors and forwards AbortSignal', async () => {
    const client = new ApiClient('http://localhost:8000');
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'err' }, 500));
    const failed = await client.listDocuments().catch((error) => error);
    expect(failed).toBeInstanceOf(ApiError);
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(jsonResponse({ documents: [], count: 0 }));
    await client.listDocuments({ signal: controller.signal });
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });
});

describe('apiClient auth', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('login posts username and password to /api/auth/login', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      access_token: 'token',
      token_type: 'bearer',
      user: { id: 'u1', username: 'eswar', display_name: 'Eswar Balu', role: 'Manufacturing Engineer' },
    }));
    const client = new ApiClient('http://localhost:8000');
    await client.login('eswar', 'private-pass');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/auth/login');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ username: 'eswar', password: 'private-pass' });
  });

  it('getCurrentUser sends bearer token to /api/auth/me', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      id: 'u1',
      username: 'eswar',
      display_name: 'Eswar Balu',
      role: 'Manufacturing Engineer',
    }));
    const client = new ApiClient('http://localhost:8000');
    await client.getCurrentUser('token');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/auth/me');
    expect(init.method).toBe('GET');
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer token');
  });

  it('401 login failures preserve safe auth message and do not mean offline', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid username or password.' }, 401));
    const client = new ApiClient('http://localhost:8000');
    const err = await client.login('eswar', 'wrong').catch((error) => error);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as Error).message).toBe('Invalid username or password.');
  });

  it('register posts safe account fields to /api/auth/register', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      access_token: 'token',
      token_type: 'bearer',
      user: { id: 'u2', username: 'new-user', display_name: 'New User', role: 'Engineer' },
    }, 201));
    const client = new ApiClient('http://localhost:8000');
    await client.register({
      username: 'new-user',
      display_name: 'New User',
      role: 'Engineer',
      password: 'private-pass',
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/auth/register');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      username: 'new-user',
      display_name: 'New User',
      role: 'Engineer',
      password: 'private-pass',
    });
  });

  it('register duplicate username preserves safe 409 message', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'That username is already in use.' }, 409));
    const client = new ApiClient('http://localhost:8000');
    const err = await client.register({
      username: 'new-user',
      display_name: 'New User',
      role: 'Engineer',
      password: 'private-pass',
    }).catch((error) => error);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as Error).message).toBe('That username is already in use.');
  });
});
