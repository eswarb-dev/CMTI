/**
 * ChatContext tests — chat response mapping, clarification tolerance,
 * PASS / HUMAN_REVIEW mapping, error safety, and stale-request behavior.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';
import { ChatProvider } from './ChatContext';
import { ACTIVE_CONVERSATION_KEY, CONVERSATIONS_KEY, titleFromQuery } from './conversationUtils';
import { useChat } from './useChat';
import type { QueryApiResponse } from '../types/contracts';

vi.mock('../services/apiClient', () => ({
  default: {
    checkConnection: vi.fn().mockResolvedValue('online'),
    checkHealth: vi.fn(),
    checkReady: vi.fn(),
    submitQuery: vi.fn(),
  },
}));

import apiClient from '../services/apiClient';

const mockedSubmit = () => vi.mocked(apiClient.submitQuery);

function baseResponse(overrides: Partial<QueryApiResponse> = {}): QueryApiResponse {
  return {
    query_id: 'q-1',
    status: 'pass',
    routing: {
      query_id: 'q-1',
      intent: 'DOCUMENTATION',
      selected_agents: ['DOCUMENT'],
      needs_clarification: false,
      clarification_reason: null,
      risk_level: 'LOW',
      confidence: null,
      provider_status: 'SUCCESS',
      decision_metadata: {},
    },
    evidence: { query_id: 'q-1', evidence: [], conflicts: [], missing_information: [], warnings: [], metadata: {} },
    reasoning: {
      query_id: 'q-1',
      observations: [],
      possible_causes: [],
      recommended_checks: [],
      missing_information: [],
      citations: [],
      raw_answer: 'The spindle feed is displayed per axis.',
      provider_status: 'SUCCESS',
      model: 'gemini-3.8-flash',
      metadata: {},
    },
    review: {
      query_id: 'q-1',
      action: 'PASS',
      reasons: [],
      confidence: null,
      provider_status: 'SUCCESS',
      metadata: {},
    },
    ...overrides,
  };
}

function ev(id: string) {
  return {
    evidence_id: id,
    source_type: 'MANUAL',
    provenance: {
      source_kind: 'DOCUMENT',
      source_dataset: 'technical_document_corpus',
      source_id: 'DOC-1',
      source_file: 'manuals/cnc/example.pdf',
      document_id: 'DOC-1',
      record_id: null,
      raw_record_id: null,
      chunk_id: 'CH-1',
      page_start: 12,
      page_end: 13,
      chapter: '3.4.5',
      section: null,
      subsection: null,
    },
    machine_id: null,
    product_id: null,
    batch_id: null,
    title: 'Spindle example',
    content: 'Example content.',
    observed_at: null,
    retrieval_score: 0.87,
    decision_score: null,
    metadata: {},
  };
}

/** Render provider and expose the live context value to the test. */
function renderChat() {
  const box: { current: ReturnType<typeof useChat> | undefined } = { current: undefined };
  const Probe: React.FC = () => {
    const value = useChat();
    React.useEffect(() => {
      box.current = value;
    }, [value]);
    return null;
  };
  const rendered = render(
    <ChatProvider>
      <Probe />
    </ChatProvider>,
  );
  const get = () => {
    if (!box.current) throw new Error('context not captured');
    return box.current;
  };
  return { get, unmount: rendered.unmount };
}

describe('ChatContext', () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedSubmit().mockReset();
  });

  it('user message appears immediately and submitQuery is called exactly once', async () => {
    mockedSubmit().mockImplementation(() => new Promise(() => {}));
    const { get } = renderChat();
    await act(async () => {
      void get().sendMessage('spindle vibration');
    });
    expect(get().messages).toHaveLength(1);
    expect(get().messages[0].sender).toBe('user');
    expect(get().messages[0].text).toBe('spindle vibration');
    expect(mockedSubmit()).toHaveBeenCalledTimes(1);
  });

  it('sets pending/loading state while the request is in flight', async () => {
    mockedSubmit().mockImplementation(() => new Promise(() => {}));
    const { get } = renderChat();
    await act(async () => {
      void get().sendMessage('hello');
    });
    expect(get().transportState).toBe('submitting');
  });

  it('assistant response uses reasoning.raw_answer', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    const assistant = get().messages.find((m) => m.sender === 'assistant');
    expect(assistant?.text).toBe('The spindle feed is displayed per axis.');
  });

  it('clarification uses routing.clarification_reason', async () => {
    mockedSubmit().mockResolvedValueOnce(
      baseResponse({
        status: 'needs_clarification',
        routing: {
          ...baseResponse().routing,
          needs_clarification: true,
          clarification_reason: 'Which machine is affected?',
        },
      }),
    );
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('vague query');
    });
    const assistant = get().messages.find((m) => m.sender === 'assistant');
    expect(assistant?.text).toBe('Which machine is affected?');
    expect(assistant?.status).toBe('needs_clarification');
  });

  it.each([
    ['evidence', { evidence: null }],
    ['reasoning', { reasoning: null }],
    ['review', { review: null }],
  ])('clarification tolerates %s=null', async (_name, patch) => {
    mockedSubmit().mockResolvedValueOnce(
      baseResponse({
        status: 'needs_clarification',
        routing: {
          ...baseResponse().routing,
          needs_clarification: true,
          clarification_reason: 'Need machine id.',
        },
        ...patch,
      } as Partial<QueryApiResponse>),
    );
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('vague');
    });
    const assistant = get().messages.find((m) => m.sender === 'assistant');
    expect(assistant?.text).toBe('Need machine id.');
  });

  it('PASS state maps correctly with review reasons empty', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse({ status: 'pass' }));
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    const assistant = get().messages.find((m) => m.sender === 'assistant');
    expect(assistant?.status).toBe('pass');
    expect(assistant?.reviewReasons ?? []).toEqual([]);
  });

  it('HUMAN_REVIEW maps from review.action and preserves reasons', async () => {
    mockedSubmit().mockResolvedValueOnce(
      baseResponse({
        status: 'human_review',
        review: { ...baseResponse().review!, action: 'HUMAN_REVIEW', reasons: ['grounding_failure'] },
      }),
    );
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    const assistant = get().messages.find((m) => m.sender === 'assistant');
    expect(assistant?.status).toBe('human_review');
    expect(assistant?.reviewReasons).toEqual(['grounding_failure']);
    // answer must remain visible, not replaced by an error
    expect(assistant?.text).toBe('The spindle feed is displayed per axis.');
    expect(get().transportState).not.toBe('error');
  });

  it('maps backend citations to actual label + evidence_id', async () => {
    const evidence = ev('EV-001');
    mockedSubmit().mockResolvedValueOnce(
      baseResponse({
        evidence: { ...baseResponse().evidence!, evidence: [evidence] },
        reasoning: {
          ...baseResponse().reasoning!,
          citations: [{ evidence_id: 'EV-001', label: 'S1' }],
        },
      }),
    );
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    const citations = get().activeCitations;
    expect(citations).toHaveLength(1);
    expect(citations[0].evidence_id).toBe('EV-001');
    expect(citations[0].label).toBe('S1');
    expect(citations[0].document_title).toBe('Spindle example');
  });

  it('API error produces a safe error state with no fabricated answer', async () => {
    mockedSubmit().mockRejectedValueOnce(new Error('Investigation could not be completed.'));
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    expect(get().transportState).toBe('error');
    expect(get().errorMessage).toBe('Investigation could not be completed.');
    expect(get().messages.filter((m) => m.sender === 'assistant')).toHaveLength(0);
  });

  it('stale request A cannot overwrite newer request B (abort + sequence invalidation)', async () => {
    let resolveA!: (v: QueryApiResponse) => void;
    let resolveB!: (v: QueryApiResponse) => void;
    const gateA = new Promise<QueryApiResponse>((r) => { resolveA = r; });
    const gateB = new Promise<QueryApiResponse>((r) => { resolveB = r; });
    mockedSubmit()
      .mockImplementationOnce(() => gateA)
      .mockImplementationOnce(() => gateB);

    const { get } = renderChat();
    let promiseA!: Promise<void>;
    let promiseB!: Promise<void>;
    await act(async () => {
      promiseA = get().sendMessage('request A');
      promiseB = get().sendMessage('request B');
    });
    const signalA = mockedSubmit().mock.calls[0][1]?.signal as AbortSignal | undefined;
    // A must have been aborted when B was submitted
    expect(signalA?.aborted).toBe(true);

    const responseB = baseResponse({ query_id: 'q-b', reasoning: { ...baseResponse().reasoning!, raw_answer: 'answer B' } });
    const responseA = baseResponse({ query_id: 'q-a', reasoning: { ...baseResponse().reasoning!, raw_answer: 'answer A' } });
    // Resolve B first, then A late — A must not overwrite B (sequence invalidation).
    await act(async () => {
      resolveB(responseB);
      await promiseB;
    });
    await act(async () => {
      resolveA(responseA);
      await promiseA;
    });
    const assistants = get().messages.filter((m) => m.sender === 'assistant');
    expect(assistants).toHaveLength(1);
    expect(assistants[0].text).toBe('answer B');
  });

  it('initial state has no conversations', () => {
    const { get } = renderChat();
    expect(get().conversations).toEqual([]);
    expect(get().messages).toEqual([]);
  });

  it('first direct query creates a conversation and title', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('What are the recommended steps for spindle vibration?');
    });
    expect(get().conversations).toHaveLength(1);
    expect(get().conversations[0].title).toBe('Recommended steps for spindle vibration?');
    expect(get().messages[0].sender).toBe('user');
  });

  it('title generation preserves engineering identifiers', () => {
    expect(titleFromQuery('Why did CNC-05 show repeated spindle alarms?')).toBe(
      'Why did CNC-05 show repeated spindle alarms?',
    );
    expect(titleFromQuery('Show quality failures for SHAFT-A and MNT-001 LOTO')).toContain('SHAFT-A');
  });

  it('long title truncates deterministically', () => {
    const title = titleFromQuery('What is the very long engineering procedure for spindle vibration diagnosis across multiple machine families and shifts?');
    expect(title.endsWith('…')).toBe(true);
    expect(title.length).toBeLessThanOrEqual(56);
  });

  it('assistant response joins the same conversation', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('hello');
    });
    expect(get().storedConversations[0].messages.map((m) => m.sender)).toEqual(['user', 'assistant']);
  });

  it('second query does not rename conversation', async () => {
    mockedSubmit().mockResolvedValue(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('Why did CNC-05 show repeated spindle alarms?');
    });
    await act(async () => {
      await get().sendMessage('What changed yesterday?');
    });
    expect(get().conversations[0].title).toBe('Why did CNC-05 show repeated spindle alarms?');
  });

  it('New Chat preserves existing history', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('first question');
      get().startNewChat();
    });
    expect(get().conversations).toHaveLength(1);
    expect(get().messages).toEqual([]);
    expect(get().activeConversationId).toBe('');
  });

  it('query after New Chat creates a second conversation', async () => {
    mockedSubmit().mockResolvedValue(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('first question');
      get().startNewChat();
      await get().sendMessage('second question');
    });
    expect(get().conversations).toHaveLength(2);
    expect(get().conversations[0].title).toBe('Second question');
  });

  it('clicking conversation restores messages', async () => {
    mockedSubmit().mockResolvedValue(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('first question');
      get().startNewChat();
      await get().sendMessage('second question');
    });
    const first = get().conversations.find((c) => c.title === 'First question')!;
    await act(async () => {
      get().selectConversation(first.id);
    });
    expect(get().messages[0].text).toBe('first question');
  });

  it('reload/localStorage restores conversations and active conversation', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const first = renderChat();
    await act(async () => {
      await first.get().sendMessage('persist me');
    });
    const activeId = first.get().activeConversationId;
    first.unmount();
    const second = renderChat();
    expect(second.get().conversations).toHaveLength(1);
    expect(second.get().activeConversationId).toBe(activeId);
    expect(second.get().messages[0].text).toBe('persist me');
  });

  it('invalid localStorage payload fails safely', () => {
    window.localStorage.setItem(CONVERSATIONS_KEY, '{bad json');
    window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, 'missing');
    const { get } = renderChat();
    expect(get().conversations).toEqual([]);
    expect(get().messages).toEqual([]);
  });

  it('localStorage failure does not block chat', async () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('still works');
    });
    expect(get().messages.map((m) => m.sender)).toEqual(['user', 'assistant']);
    spy.mockRestore();
  });

  it('Clear All removes conversations and active id', async () => {
    mockedSubmit().mockResolvedValueOnce(baseResponse());
    const { get } = renderChat();
    await act(async () => {
      await get().sendMessage('delete all');
      get().clearAllConversations();
    });
    expect(get().conversations).toEqual([]);
    expect(get().activeConversationId).toBe('');
    expect(window.localStorage.getItem(CONVERSATIONS_KEY)).toBeNull();
  });
});
