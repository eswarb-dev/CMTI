/**
 * Upload / knowledge-base behavior + static secret/coupling boundaries.
 * STEP 19B2: UploadModal, KnowledgeBaseView, and UploadsView use the real
 * document API. Success/failure claims must come from server responses only.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { UploadModal } from './UploadModal';
import { KnowledgeBaseView } from '../views/KnowledgeBaseView';
import { UploadsView } from '../views/UploadsView';
import { ChatContext } from '../../context/chatContextDef';
import type { UserDocument } from '../../types/contracts';

vi.mock('../../services/apiClient', () => {
  class MockApiError extends Error {
    status?: number;
    detail?: unknown;
    constructor(message: string, status?: number, detail?: unknown) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.detail = detail;
    }
  }
  return {
    ApiError: MockApiError,
    default: {
      checkConnection: vi.fn().mockResolvedValue('online'),
      submitQuery: vi.fn(),
      listDocuments: vi.fn(),
      getDocument: vi.fn(),
      uploadDocument: vi.fn(),
      deleteDocument: vi.fn(),
    },
  };
});

import apiClient from '../../services/apiClient';

const mockedList = () => vi.mocked(apiClient.listDocuments);
const mockedUpload = () => vi.mocked(apiClient.uploadDocument);
const mockedDelete = () => vi.mocked(apiClient.deleteDocument);

function chatState(uploadOpen: boolean, notify: () => void = () => {}) {
  const noop = () => {};
  return {
    transportState: 'idle' as const,
    errorMessage: null,
    connectionStatus: 'online' as const,
    conversations: [],
    activeConversationId: 'conv-live',
    storedConversations: [],
    messages: [],
    activeCitations: [],
    selectedCitationNumber: null,
    sessionAttachment: null,
    pdfLibrary: [],
    isMobileSidebarOpen: false,
    isSettingsOpen: false,
    isUploadModalOpen: uploadOpen,
    documentsVersion: 0,
    sendMessage: async () => {},
    startNewChat: noop,
    selectConversation: noop,
    clearAllConversations: noop,
    setSelectedCitation: noop,
    attachSessionFile: async () => {},
    removeSessionFile: noop,
    checkBackendHealth: async () => {},
    setIsMobileSidebarOpen: noop,
    setSettingsOpen: noop,
    setUploadModalOpen: noop,
    notifyDocumentsChanged: notify,
  };
}

function readyDocument(overrides: Partial<UserDocument> = {}): UserDocument {
  return {
    document_id: 'USR-ABCDEF123456',
    original_filename: 'manual.pdf',
    mime_type: 'application/pdf',
    file_size_bytes: 1024,
    status: 'READY',
    page_count: 3,
    chunk_count: 5,
    created_at: '2026-09-27T10:00:00+00:00',
    updated_at: '2026-09-27T10:01:00+00:00',
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

describe('upload behavior', () => {
  beforeEach(() => {
    mockedList().mockReset();
    mockedUpload().mockReset();
    mockedDelete().mockReset();
  });

  it('UploadModal is no longer informational-only', () => {
    render(
      <ChatContext.Provider value={chatState(true)}>
        <UploadModal />
      </ChatContext.Provider>,
    );
    expect(screen.getByText(/select a pdf document/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^upload$/i })).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/not connected yet/i);
  });

  it('UploadModal calls uploadDocument exactly once and is disabled while pending', async () => {
    let resolveUpload!: (value: unknown) => void;
    mockedUpload().mockImplementationOnce(
      () => new Promise((resolve) => { resolveUpload = resolve as (value: unknown) => void; }),
    );
    render(
      <ChatContext.Provider value={chatState(true)}>
        <UploadModal />
      </ChatContext.Provider>,
    );
    const file = new File(['pdf-bytes'], 'manual.pdf', { type: 'application/pdf' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    const button = screen.getByRole('button', { name: /^upload$/i });
    fireEvent.click(button);
    expect(mockedUpload()).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    await waitFor(() => {
      resolveUpload({ ...readyDocument(), duplicate: false });
    });
  });

  it('READY success and duplicate render accurately from server response', async () => {
    mockedUpload().mockResolvedValueOnce({ ...readyDocument(), duplicate: false });
    const { unmount } = render(
      <ChatContext.Provider value={chatState(true)}>
        <UploadModal />
      </ChatContext.Provider>,
    );
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [new File(['x'], 'a.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: /^upload$/i }));
    await screen.findByText(/document added to the knowledge base/i);
    unmount();

    mockedUpload().mockResolvedValueOnce({ ...readyDocument(), duplicate: true });
    render(
      <ChatContext.Provider value={chatState(true)}>
        <UploadModal />
      </ChatContext.Provider>,
    );
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [new File(['x'], 'a.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: /^upload$/i }));
    await screen.findByText(/already exists in the knowledge base/i);
  });

  it('failure shows a safe message and no success', async () => {
    const { ApiError } = await import('../../services/apiClient');
    mockedUpload().mockRejectedValueOnce(new ApiError('Too big', 413));
    render(
      <ChatContext.Provider value={chatState(true)}>
        <UploadModal />
      </ChatContext.Provider>,
    );
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, {
      target: { files: [new File(['x'], 'a.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: /^upload$/i }));
    await screen.findByText(/exceeds the upload size limit/i);
    expect(screen.queryByText(/document added to the knowledge base/i)).not.toBeInTheDocument();
  });

  it('UploadModal uses the real upload endpoint (no fake ingestion claims)', async () => {
    const { readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    const src = readFileSync(join(process.cwd(), 'src', 'components', 'chat', 'UploadModal.tsx'), 'utf8');
    expect(src).toMatch(/uploadDocument/);
    expect(src).not.toMatch(/successfully uploaded|ingestion complete|is now indexed/i);
  });

  it('mockData module exposes no records that could be mistaken for live data', async () => {
    const mock = await import('../../services/mockData');
    expect(mock.INITIAL_CONVERSATIONS).toEqual([]);
    expect(mock.INITIAL_PDF_LIBRARY).toEqual([]);
    expect(mock.INITIAL_MESSAGES).toEqual([]);
  });
});

describe('KnowledgeBaseView', () => {
  beforeEach(() => {
    mockedList().mockReset();
    mockedDelete().mockReset();
  });

  function renderView(notify: () => void = () => {}) {
    return render(
      <ChatContext.Provider value={chatState(false, notify)}>
        <MemoryRouter>
          <KnowledgeBaseView />
        </MemoryRouter>
      </ChatContext.Provider>,
    );
  }

  it('calls listDocuments and shows loading then empty state', async () => {
    mockedList().mockImplementationOnce(() => new Promise(() => {}));
    renderView();
    expect(mockedList()).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/loading documents/i)).toBeInTheDocument();
  });

  it('empty state does not pretend frozen manuals are uploads', async () => {
    mockedList().mockResolvedValueOnce({ documents: [], count: 0 });
    renderView();
    await screen.findByText(/no uploaded documents yet/i);
  });

  it('READY document renders with pages/chunks, FAILED renders safely', async () => {
    mockedList().mockResolvedValueOnce({
      documents: [readyDocument(), readyDocument({
        document_id: 'USR-000000000002',
        original_filename: 'bad.pdf',
        status: 'FAILED',
        page_count: 0,
        chunk_count: 0,
        error_code: 'NO_EXTRACTABLE_TEXT',
        error_message: 'No extractable text was found in this PDF.',
      })],
      count: 2,
    });
    renderView();
    await screen.findByText('manual.pdf');
    expect(screen.getByText(/3 pages · 5 chunks/i)).toBeInTheDocument();
    expect(screen.getByText(/NO_EXTRACTABLE_TEXT/i)).toBeInTheDocument();
  });

  it('delete confirmation removes the item and refreshes', async () => {
    mockedList()
      .mockResolvedValueOnce({ documents: [readyDocument()], count: 1 })
      .mockResolvedValueOnce({ documents: [], count: 0 });
    mockedDelete().mockResolvedValueOnce({ document_id: 'USR-ABCDEF123456', deleted: true });
    renderView();
    await screen.findByText('manual.pdf');
    fireEvent.click(screen.getByTitle(/delete document/i));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await screen.findByText(/no uploaded documents yet/i);
    expect(mockedDelete()).toHaveBeenCalledWith('USR-ABCDEF123456');
  });

  it('delete failure preserves the item and shows a safe error', async () => {
    mockedList().mockResolvedValue({ documents: [readyDocument()], count: 1 });
    mockedDelete().mockRejectedValueOnce(new Error('boom'));
    renderView();
    await screen.findByText('manual.pdf');
    fireEvent.click(screen.getByTitle(/delete document/i));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    await screen.findByText(/could not be deleted/i);
    expect(screen.getByText('manual.pdf')).toBeInTheDocument();
  });

  it('renders no mock documents', async () => {
    mockedList().mockResolvedValueOnce({ documents: [readyDocument()], count: 1 });
    renderView();
    await screen.findByText('manual.pdf');
    expect(screen.queryByText(/live server documents/i)).not.toBeInTheDocument();
  });
});

describe('UploadsView', () => {
  beforeEach(() => {
    mockedList().mockReset();
  });

  it('shows live registry data with real statuses and no fake progress', async () => {
    mockedList().mockResolvedValueOnce({ documents: [readyDocument()], count: 1 });
    render(
      <ChatContext.Provider value={chatState(false)}>
        <MemoryRouter>
          <UploadsView />
        </MemoryRouter>
      </ChatContext.Provider>,
    );
    await screen.findByText('manual.pdf');
    expect(screen.getByText(/ready/i)).toBeInTheDocument();
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/\d+%/);
    expect(text).not.toMatch(/worker|queue state|job id/i);
  });
});

describe('static boundaries', () => {
  const SECRET_PATTERNS = [
    /GEMINI_API_KEY/,
    /TYPESAFE_API_KEY/,
    /DATABASE_URL/,
    /demo_cases\.json/,
    /hidden_simulated_cause/,
  ];
  const COUPLING_PATTERNS = [
    /sqlite/i,
    /qdrant/i,
    /typesafe_sdk/,
    /google\.genai/,
    /langgraph/i,
    /stored_filename/,
    /registry\.db/,
    /documents\.db/,
  ];

  async function frontendSource(): Promise<string> {
    const { readdirSync, readFileSync } = await import('node:fs');
    const { join } = await import('node:path');
    const srcRoot = join(process.cwd(), 'src');
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === 'node_modules' || entry.name === 'dist') continue;
          walk(full);
        } else if (/\.(ts|tsx|js|jsx|json)$/.test(entry.name) && !entry.name.endsWith('.test.tsx') && !entry.name.endsWith('.test.ts')) {
          files.push(readFileSync(full, 'utf8'));
        }
      }
    };
    walk(srcRoot);
    return files.join('\n');
  }

  it('frontend source has no runtime use of backend secrets', async () => {
    const src = await frontendSource();
    for (const pattern of SECRET_PATTERNS) {
      expect(src, `forbidden secret reference: ${pattern}`).not.toMatch(pattern);
    }
  });

  it('frontend source has no backend implementation imports', async () => {
    const src = await frontendSource();
    for (const pattern of COUPLING_PATTERNS) {
      expect(src, `forbidden backend coupling: ${pattern}`).not.toMatch(pattern);
    }
    expect(src).not.toMatch(/from ['"]\.\.\/.*backend/i);
    expect(src).not.toMatch(/from ['"]app\./);
  });
});
