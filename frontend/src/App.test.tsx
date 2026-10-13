import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('optional local account UX', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    window.localStorage.clear();
    window.history.pushState({}, '', '/');
    Element.prototype.scrollIntoView = vi.fn();
    fetchMock.mockReset();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/health')) {
        return Promise.resolve(jsonResponse({ status: 'ok', service: 'manufacturaiq' }));
      }
      if (url.endsWith('/api/query')) {
        return Promise.resolve(jsonResponse({
          query_id: 'q1',
          status: 'human_review',
          routing: {
            query_id: 'q1',
            intent: 'maintenance',
            selected_agents: ['DOCUMENT'],
            needs_clarification: false,
            clarification_reason: null,
            risk_level: 'medium',
            confidence: null,
            provider_status: 'FALLBACK',
            decision_metadata: {},
          },
          evidence: { query_id: 'q1', evidence: [], conflicts: [], missing_information: [], warnings: [], metadata: {} },
          reasoning: {
            query_id: 'q1',
            observations: [],
            possible_causes: [],
            recommended_checks: [],
            missing_information: [],
            citations: [],
            raw_answer: 'Guest query answered.',
            provider_status: 'FALLBACK',
            model: null,
            metadata: {},
          },
          review: { query_id: 'q1', action: 'HUMAN_REVIEW', reasons: [], confidence: null, provider_status: 'FALLBACK', metadata: {} },
        }));
      }
      if (url.endsWith('/api/documents') && init?.method === 'GET') {
        return Promise.resolve(jsonResponse({ documents: [], count: 0 }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it('no token renders main chat, not a blocking login page', async () => {
    render(<App />);
    expect(await screen.findByText('Ask an engineering question.')).toBeInTheDocument();
    expect(screen.getByText('Using Guest mode')).toBeInTheDocument();
    expect(screen.queryByText('Local Prototype Access')).not.toBeInTheDocument();
  });

  it('guest can submit a chat query and create a conversation', async () => {
    render(<App />);
    const input = await screen.findByPlaceholderText(/Ask a manufacturing engineering question/i);
    fireEvent.change(input, { target: { value: 'What are the steps for spindle warm-up on a Haas mill?' } });
    fireEvent.click(screen.getByTitle(/Send query/i));
    expect(await screen.findByText('Guest query answered.')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/query'),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(window.localStorage.getItem('manufacturaiq.conversations.v1')).toContain('Haas mill');
  });

  it('knowledge-base navigation remains usable as guest', async () => {
    window.history.pushState({}, '', '/knowledge-base');
    render(<App />);
    expect((await screen.findAllByText(/Knowledge Base/i)).length).toBeGreaterThan(0);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/documents'),
      expect.objectContaining({ method: 'GET' }),
    ));
  });
});
