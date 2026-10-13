import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SettingsPanel from './SettingsPanel';
import { ChatContext } from '../../context/chatContextDef';
import type { ChatContextType } from '../../context/chatContextDef';
import type { EvidenceCitation, UserDocument } from '../../types/contracts';

vi.mock('../../services/apiClient', () => ({
  default: {
    listDocuments: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

const logoutMock = vi.fn();
const openAuthDialogMock = vi.fn();
let mockAuthenticated = true;

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    user: mockAuthenticated ? {
      id: 'user-1',
      username: 'eswar',
      display_name: 'Eswar Balu',
      role: 'Manufacturing Engineer',
    } : null,
    authenticated: mockAuthenticated,
    logout: logoutMock,
    openAuthDialog: openAuthDialogMock,
  }),
}));

import apiClient from '../../services/apiClient';

const readyDocument: UserDocument = {
  document_id: 'USR-123',
  original_filename: 'demo_manual.pdf',
  mime_type: 'application/pdf',
  file_size_bytes: 1200,
  status: 'READY',
  page_count: 2,
  chunk_count: 1,
  created_at: '2026-09-28T00:00:00Z',
  updated_at: '2026-09-28T00:00:00Z',
  error_code: null,
  error_message: null,
};

function citation(documentId: string, sourceLabel: EvidenceCitation['source_label']): EvidenceCitation {
  return {
    citation_number: 1,
    evidence_id: `EV-${documentId}`,
    label: 'S1',
    document_title: documentId.startsWith('USR-') ? 'demo_manual.pdf' : 'Machine Maintenance Manual',
    document_id: documentId,
    page_number: 12,
    snippet: 'Real cited source text.',
    retrieval_score: 0.8123,
    source_label: sourceLabel,
  };
}

function renderPanel(patch: Partial<ChatContextType> = {}) {
  const setUploadModalOpen = vi.fn();
  const setSettingsOpen = vi.fn();
  const value: ChatContextType = {
    transportState: 'idle',
    errorMessage: null,
    connectionStatus: 'online',
    conversations: [],
    activeConversationId: 'conv-1',
    storedConversations: [],
    messages: [],
    activeCitations: [],
    selectedCitationNumber: null,
    sessionAttachment: null,
    pdfLibrary: [],
    isMobileSidebarOpen: false,
    isSettingsOpen: true,
    isUploadModalOpen: false,
    documentsVersion: 0,
    sendMessage: async () => {},
    startNewChat: vi.fn(),
    selectConversation: vi.fn(),
    clearAllConversations: vi.fn(),
    setSelectedCitation: vi.fn(),
    attachSessionFile: async () => {},
    removeSessionFile: vi.fn(),
    checkBackendHealth: async () => {},
    setIsMobileSidebarOpen: vi.fn(),
    setSettingsOpen,
    setUploadModalOpen,
    notifyDocumentsChanged: vi.fn(),
    ...patch,
  };
  const result = render(
    <MemoryRouter>
      <ChatContext.Provider value={value}>
        <SettingsPanel />
      </ChatContext.Provider>
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole('button', { name: /sources & evidence/i }));
  return { ...result, setUploadModalOpen, setSettingsOpen };
}

describe('SettingsPanel Sources & Evidence', () => {
  beforeEach(() => {
    logoutMock.mockReset();
    openAuthDialogMock.mockReset();
    mockAuthenticated = true;
    vi.mocked(apiClient.listDocuments).mockReset();
    vi.mocked(apiClient.deleteDocument).mockReset();
    vi.mocked(apiClient.listDocuments).mockResolvedValue({ documents: [readyDocument], count: 1 });
  });

  it('shows Guest Mode account info and optional auth actions when unsigned', () => {
    mockAuthenticated = false;
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /general/i }));
    expect(screen.getByText('Guest Mode')).toBeInTheDocument();
    expect(screen.getByText('No local account is currently signed in.')).toBeInTheDocument();
    expect(screen.getByText(/without an account/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));
    expect(openAuthDialogMock).toHaveBeenCalledWith('sign-in');
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(openAuthDialogMock).toHaveBeenCalledWith('create-account');
    expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
    expect(screen.queryByText('JD')).not.toBeInTheDocument();
  });

  it('shows the authenticated account and generated initials', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /general/i }));
    expect(screen.getByText('Eswar Balu')).toBeInTheDocument();
    expect(screen.getByText('Manufacturing Engineer')).toBeInTheDocument();
    expect(screen.getByText('EB')).toBeInTheDocument();
    expect(screen.queryByText('John Doe')).not.toBeInTheDocument();
    expect(screen.queryByText('JD')).not.toBeInTheDocument();
  });

  it('Sign Out delegates to auth logout without clearing conversations or documents', () => {
    const clearAllConversations = vi.fn();
    const notifyDocumentsChanged = vi.fn();
    renderPanel({ clearAllConversations, notifyDocumentsChanged });
    fireEvent.click(screen.getByRole('button', { name: /general/i }));
    fireEvent.click(screen.getByRole('button', { name: /sign out/i }));
    expect(logoutMock).toHaveBeenCalled();
    expect(clearAllConversations).not.toHaveBeenCalled();
    expect(notifyDocumentsChanged).not.toHaveBeenCalled();
  });

  it('removes outdated disabled-ingestion copy', async () => {
    renderPanel();
    expect(screen.queryByText(/coming next/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/permanent ingestion endpoint disabled/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/backend ships/i)).not.toBeInTheDocument();
  });

  it('Add PDF opens the real UploadModal trigger', () => {
    const { setUploadModalOpen } = renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /add pdf/i }));
    expect(setUploadModalOpen).toHaveBeenCalledWith(true);
  });

  it('fetches uploaded documents from API and shows READY document', async () => {
    renderPanel();
    await waitFor(() => expect(apiClient.listDocuments).toHaveBeenCalled());
    expect(await screen.findByText('demo_manual.pdf')).toBeInTheDocument();
    expect(screen.getByText(/READY · 2 pages/)).toBeInTheDocument();
  });

  it('shows current answer citations and uploaded label', () => {
    renderPanel({ activeCitations: [citation('USR-123', 'Uploaded document')] });
    expect(screen.getByText('demo_manual.pdf')).toBeInTheDocument();
    expect(screen.getByText('Page 12')).toBeInTheDocument();
    expect(screen.getByText('Uploaded document')).toBeInTheDocument();
    expect(screen.getByText(/similarity 0\.812/i)).toBeInTheDocument();
  });

  it('renders DOC-* as Built-in document', () => {
    renderPanel({ activeCitations: [citation('DOC-123', 'Built-in document')] });
    expect(screen.getByText('Machine Maintenance Manual')).toBeInTheDocument();
    expect(screen.getByText('Built-in document')).toBeInTheDocument();
  });

  it('does not fabricate sources when no current response exists', () => {
    renderPanel({ activeCitations: [] });
    expect(screen.getByText('No sources for the current conversation yet.')).toBeInTheDocument();
    expect(screen.queryByText('Uploaded document')).not.toBeInTheDocument();
    expect(screen.queryByText('Built-in document')).not.toBeInTheDocument();
  });

  it('switching conversations switches current sources', () => {
    const first = renderPanel({ activeCitations: [citation('USR-123', 'Uploaded document')] });
    expect(screen.getByText('Uploaded document')).toBeInTheDocument();
    first.rerender(
      <MemoryRouter>
        <ChatContext.Provider
          value={{
            ...(first as unknown as { value?: ChatContextType }).value,
            transportState: 'idle',
            errorMessage: null,
            connectionStatus: 'online',
            conversations: [],
            activeConversationId: 'conv-2',
            storedConversations: [],
            messages: [],
            activeCitations: [citation('DOC-123', 'Built-in document')],
            selectedCitationNumber: null,
            sessionAttachment: null,
            pdfLibrary: [],
            isMobileSidebarOpen: false,
            isSettingsOpen: true,
            isUploadModalOpen: false,
            documentsVersion: 0,
            sendMessage: async () => {},
            startNewChat: vi.fn(),
            selectConversation: vi.fn(),
            clearAllConversations: vi.fn(),
            setSelectedCitation: vi.fn(),
            attachSessionFile: async () => {},
            removeSessionFile: vi.fn(),
            checkBackendHealth: async () => {},
            setIsMobileSidebarOpen: vi.fn(),
            setSettingsOpen: vi.fn(),
            setUploadModalOpen: vi.fn(),
            notifyDocumentsChanged: vi.fn(),
          }}
        >
          <SettingsPanel />
        </ChatContext.Provider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /sources & evidence/i }));
    expect(screen.getByText('Built-in document')).toBeInTheDocument();
  });
});
