/**
 * Citation + evidence + HUMAN_REVIEW rendering tests against real backend shapes.
 */
import React, { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MessageItem } from './MessageItem';
import { CitationBadge } from './CitationBadge';
import { ChatContext } from '../../context/chatContextDef';
import type { ChatMessage, EvidenceCitation, QueryEvidence } from '../../types/contracts';

function evidence(id: string, overrides: Partial<QueryEvidence> = {}): QueryEvidence {
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
    retrieval_score: 0.8712,
    decision_score: null,
    metadata: {},
    ...overrides,
  };
}

function citation(n: number, overrides: Partial<EvidenceCitation> = {}): EvidenceCitation {
  return {
    citation_number: n,
    evidence_id: 'EV-001',
    label: 'S1',
    document_title: 'Spindle example',
    page_number: 12,
    snippet: 'Example content.',
    section: '3.4.5',
    retrieval_score: 0.8712,
    ...overrides,
  };
}

function withCitations(citations: EvidenceCitation[]) {
  const noop = () => {};
  const Harness: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [selected, setSelected] = useState<number | null>(null);
    return (
      <ChatContext.Provider
        value={{
          transportState: 'idle' as const,
          errorMessage: null,
          connectionStatus: 'online' as const,
          conversations: [],
          activeConversationId: 'conv-live',
          storedConversations: [],
          messages: [],
          activeCitations: citations,
          selectedCitationNumber: selected,
          sessionAttachment: null,
          pdfLibrary: [],
          isMobileSidebarOpen: false,
          isSettingsOpen: false,
          isUploadModalOpen: false,
          documentsVersion: 0,
          sendMessage: async () => {},
          startNewChat: noop,
          selectConversation: noop,
          clearAllConversations: noop,
          setSelectedCitation: setSelected,
          attachSessionFile: async () => {},
          removeSessionFile: noop,
          checkBackendHealth: async () => {},
          setIsMobileSidebarOpen: noop,
          setSettingsOpen: noop,
          setUploadModalOpen: noop,
          notifyDocumentsChanged: noop,
        }}
      >
        {children}
      </ChatContext.Provider>
    );
  };
  return Harness;
}

function renderWithCitations(citations: EvidenceCitation[], ui: React.ReactElement) {
  const Harness = withCitations(citations);
  return render(<Harness>{ui}</Harness>);
}

function assistantMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'm-asst',
    sender: 'assistant',
    text: 'The spindle feed is displayed per axis [1].',
    timestamp: '10:00',
    status: 'pass',
    citations: [citation(1)],
    evidenceBundle: [evidence('EV-001')],
    reviewReasons: [],
    ...overrides,
  };
}

describe('citations', () => {
  it('citation renders the actual backend label', () => {
    renderWithCitations([citation(1, { label: 'S1' })], <CitationBadge citationNumber={1} />);
    fireEvent.click(screen.getByTitle('View source [1]'));
    expect(screen.getByText(/citation s1/i)).toBeInTheDocument();
  });

  it('citation popover uses actual evidence-backed title and snippet', () => {
    renderWithCitations([citation(1)], <CitationBadge citationNumber={1} />);
    fireEvent.click(screen.getByTitle('View source [1]'));
    expect(screen.getByText('Spindle example')).toBeInTheDocument();
    expect(screen.getByText('Example content.')).toBeInTheDocument();
  });

  it('citation resolves the corresponding evidence_id', () => {
    renderWithCitations(
      [citation(1, { evidence_id: 'EV-001' }), citation(2, { evidence_id: 'EV-002' })],
      <CitationBadge citationNumber={2} />,
    );
    fireEvent.click(screen.getByTitle('View source [2]'));
    expect(screen.getByText(/citation s1/i)).toBeInTheDocument();
  });

  it('document page is displayed only when supplied', () => {
    renderWithCitations([citation(1, { page_number: 12 })], <CitationBadge citationNumber={1} />);
    fireEvent.click(screen.getByTitle('View source [1]'));
    expect(screen.getByText('Page 12')).toBeInTheDocument();
  });

  it('document page is hidden when not supplied', () => {
    renderWithCitations([citation(1, { page_number: undefined })], <CitationBadge citationNumber={1} />);
    fireEvent.click(screen.getByTitle('View source [1]'));
    expect(screen.queryByText(/page \d+/i)).not.toBeInTheDocument();
  });

  it('missing evidence target renders safely without fabricated source', () => {
    renderWithCitations([], <CitationBadge citationNumber={99} />);
    // badge itself renders; clicking with no backing citation must not crash or invent content
    fireEvent.click(screen.getByTitle('View source [99]'));
    expect(screen.queryByText('Spindle example')).not.toBeInTheDocument();
  });

  it('retrieval score is labelled "Retrieval similarity"', () => {
    renderWithCitations([], <MessageItem message={assistantMessage()} />);
    fireEvent.click(screen.getByRole('button', { name: /retrieved evidence/i }));
    expect(screen.getByText(/retrieval similarity:/i)).toBeInTheDocument();
  });

  it('null retrieval score is not rendered as 0', () => {
    renderWithCitations(
      [],
      <MessageItem message={assistantMessage({ evidenceBundle: [evidence('EV-001', { retrieval_score: null })] })} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /retrieved evidence/i }));
    expect(screen.queryByText(/retrieval similarity:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.000/)).not.toBeInTheDocument();
  });

  it('evidence shows real evidence_id and document/page provenance', () => {
    renderWithCitations([], <MessageItem message={assistantMessage()} />);
    fireEvent.click(screen.getByRole('button', { name: /retrieved evidence/i }));
    expect(screen.getByText('EV-001')).toBeInTheDocument();
    expect(screen.getByText(/DOC-1.*p\. 12/)).toBeInTheDocument();
  });
});

describe('HUMAN_REVIEW', () => {
  it('human_review renders banner with answer visible and is not an error', () => {
    renderWithCitations(
      [],
      <MessageItem
        message={assistantMessage({
          status: 'human_review',
          text: 'Grounded reasoning unavailable: Gemini API key is not configured.',
          reviewReasons: ['reasoning_unavailable'],
        })}
      />,
    );
    expect(screen.getAllByText(/human review recommended/i)).not.toHaveLength(0);
    expect(screen.getByText(/grounded reasoning unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/query execution error/i)).not.toBeInTheDocument();
  });

  it('review reasons appear when expanded', () => {
    renderWithCitations(
      [],
      <MessageItem
        message={assistantMessage({ status: 'human_review', reviewReasons: ['grounding_failure'] })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /view details/i }));
    expect(screen.getByText('grounding_failure')).toBeInTheDocument();
  });
});
