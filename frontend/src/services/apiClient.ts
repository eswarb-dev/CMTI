/**
 * ManufacturaIQ API Client
 * Wraps HTTP calls to backend endpoints:
 * - GET  /health
 * - GET  /ready
 * - POST /api/query
 */
import type {
  HealthResponse,
  ConnectionStatus,
  DocumentDeleteResponse,
  DocumentListResponse,
  DocumentUploadResponse,
  UserDocument,
  QueryApiRequest,
  QueryApiResponse,
  ReadyResponse,
  AuthUser,
  LoginResponse,
  RegisterRequest,
} from '../types/contracts';

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

export class ApiError extends Error {
  readonly status?: number;
  readonly detail?: unknown;

  constructor(message: string, status?: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export class ApiClient {
  readonly baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  /**
   * Health check: GET /health
   */
  async checkHealth(): Promise<HealthResponse> {
    return requestJson<HealthResponse>(`${this.baseUrl}/health`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });
  }

  /**
   * Readiness check: GET /ready
   */
  async checkReady(): Promise<ReadyResponse> {
    return requestJson<ReadyResponse>(`${this.baseUrl}/ready`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });
  }

  /**
   * Combined connection check
   */
  async checkConnection(): Promise<ConnectionStatus> {
    try {
      await this.checkHealth();
      return 'online';
    } catch {
      return 'offline';
    }
  }

  async login(username: string, password: string): Promise<LoginResponse> {
    return requestJson<LoginResponse>(`${this.baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });
  }

  async register(payload: RegisterRequest): Promise<LoginResponse> {
    return requestJson<LoginResponse>(`${this.baseUrl}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  }

  async getCurrentUser(token: string): Promise<AuthUser> {
    return requestJson<AuthUser>(`${this.baseUrl}/api/auth/me`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });
  }

  /**
   * Query backend: POST /api/query
   */
  async submitQuery(
    payload: QueryApiRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<QueryApiResponse> {
    return requestJson<QueryApiResponse>(`${this.baseUrl}/api/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: options.signal,
    });
  }

  /**
   * List dynamic user documents: GET /api/documents
   */
  async listDocuments(
    options: { signal?: AbortSignal } = {}
  ): Promise<DocumentListResponse> {
    return requestJson<DocumentListResponse>(`${this.baseUrl}/api/documents`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
      signal: options.signal,
    });
  }

  /**
   * Fetch one dynamic document: GET /api/documents/{id}
   */
  async getDocument(
    documentId: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<UserDocument> {
    return requestJson<UserDocument>(
      `${this.baseUrl}/api/documents/${encodeURIComponent(documentId)}`,
      {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        signal: options.signal,
      },
    );
  }

  /**
   * Upload one PDF: POST /api/documents (multipart).
   * The browser sets the multipart boundary; never set Content-Type manually.
   */
  async uploadDocument(
    file: File,
    options: { signal?: AbortSignal } = {}
  ): Promise<DocumentUploadResponse> {
    const form = new FormData();
    form.append('file', file);
    return requestJson<DocumentUploadResponse>(`${this.baseUrl}/api/documents`, {
      method: 'POST',
      headers: { 'Accept': 'application/json' },
      body: form,
      signal: options.signal,
    });
  }

  /**
   * Delete one dynamic document: DELETE /api/documents/{id}
   */
  async deleteDocument(
    documentId: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<DocumentDeleteResponse> {
    return requestJson<DocumentDeleteResponse>(
      `${this.baseUrl}/api/documents/${encodeURIComponent(documentId)}`,
      {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' },
        signal: options.signal,
      },
    );
  }
}

async function requestJson<T>(url: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw error;
    }
    throw new ApiError('Backend is unreachable. Check that the ManufacturaIQ API is running.');
  }

  const data = await readJsonSafely(response);
  if (!response.ok) {
    if (response.status === 422) {
      throw new ApiError('Request validation failed. Check the query fields and try again.', response.status, data);
    }
    if (response.status === 401) {
      throw new ApiError(authErrorMessage(data) || 'Invalid username or password.', response.status, data);
    }
    if (response.status === 409) {
      throw new ApiError(authErrorMessage(data) || 'That username is already in use.', response.status, data);
    }
    if (response.status >= 500) {
      throw new ApiError('Investigation could not be completed.', response.status);
    }
    throw new ApiError(`Request failed with status ${response.status}.`, response.status, data);
  }

  return data as T;
}

function authErrorMessage(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === 'string' ? detail : null;
}

async function readJsonSafely(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export const apiClient = new ApiClient();
export default apiClient;
