import React, {
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import type {
  ChatMessage,
  ConnectionStatus,
  Conversation,
  ConversationSummary,
  EvidenceCitation,
  IndexedDocument,
  QueryApiResponse,
  QueryEvidence,
  SessionAttachment,
  UiTransportState,
} from '../types/contracts';
import apiClient from '../services/apiClient';
import { ChatContext } from './chatContextDef';
import { ACTIVE_CONVERSATION_KEY, CONVERSATIONS_KEY, titleFromQuery } from './conversationUtils';
const EMPTY_MESSAGES: ChatMessage[] = [];
const EMPTY_CITATIONS: EvidenceCitation[] = [];

export const ChatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [transportState, setTransportState] = useState<UiTransportState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('checking');

  const [storedConversations, setStoredConversations] = useState<Conversation[]>(() =>
    loadStoredConversations(),
  );
  const [activeConversationId, setActiveConversationId] = useState<string>(() =>
    loadActiveConversationId(),
  );

  const activeConversation = storedConversations.find((item) => item.id === activeConversationId);
  const messages = activeConversation?.messages ?? EMPTY_MESSAGES;
  const conversations = toConversationSummaries(storedConversations);

  const [selectedCitationNumber, setSelectedCitationNumber] = useState<number | null>(null);

  const [sessionAttachment, setSessionAttachment] = useState<SessionAttachment | null>(null);
  const [pdfLibrary] = useState<IndexedDocument[]>([]);

  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [documentsVersion, setDocumentsVersion] = useState(0);
  const currentRequestRef = useRef<AbortController | null>(null);
  const requestSequenceRef = useRef(0);
  const activeCitations =
    [...messages].reverse().find((message) => message.sender === 'assistant')?.citations ?? EMPTY_CITATIONS;

  const checkBackendHealth = useCallback(async () => {
    try {
      const status = await apiClient.checkConnection();
      setConnectionStatus(status);
    } catch {
      setConnectionStatus('offline');
    }
  }, []);

  useEffect(() => {
    let isMounted = true;
    apiClient.checkConnection().then((status) => {
      if (isMounted) setConnectionStatus(status);
    }).catch(() => {
      if (isMounted) setConnectionStatus('offline');
    });

    return () => {
      isMounted = false;
      currentRequestRef.current?.abort();
    };
  }, [setActiveConversationId, setSelectedCitationNumber, setErrorMessage]);

  useEffect(() => {
    if (storedConversations.length === 0) {
      removeLocalStorage(CONVERSATIONS_KEY);
    } else {
      saveLocalStorage(CONVERSATIONS_KEY, JSON.stringify(storedConversations));
    }
  }, [storedConversations]);

  useEffect(() => {
    const exists = storedConversations.some((item) => item.id === activeConversationId);
    if (activeConversationId && exists) {
      saveLocalStorage(ACTIVE_CONVERSATION_KEY, activeConversationId);
    } else {
      removeLocalStorage(ACTIVE_CONVERSATION_KEY);
    }
  }, [activeConversationId, storedConversations]);

  const startNewChat = () => {
    setActiveConversationId('');
    setSelectedCitationNumber(null);
    setSessionAttachment(null);
    setTransportState('idle');
    setErrorMessage(null);
  };

  const selectConversation = (id: string) => {
    setActiveConversationId(id);
    setSelectedCitationNumber(null);
    setErrorMessage(null);
  };

  const clearAllConversations = () => {
    setStoredConversations([]);
    setActiveConversationId('');
    setSelectedCitationNumber(null);
    setErrorMessage(null);
    setTransportState('idle');
    removeLocalStorage(CONVERSATIONS_KEY);
    removeLocalStorage(ACTIVE_CONVERSATION_KEY);
  };

  const attachSessionFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setErrorMessage('Only PDF documents are supported.');
      setTransportState('error');
      return;
    }
    setSessionAttachment(null);
    setErrorMessage('Use Sources & Evidence or Knowledge Base to add PDFs.');
    setTransportState('error');
  };

  const removeSessionFile = () => {
    setSessionAttachment(null);
  };

  const notifyDocumentsChanged = () => {
    setDocumentsVersion((version) => version + 1);
  };

  const sendMessage = useCallback(async (queryText: string) => {
    if (!queryText.trim()) return;

    currentRequestRef.current?.abort();
    const controller = new AbortController();
    currentRequestRef.current = controller;
    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;

    const trimmedQuery = queryText.trim();
    const now = new Date();
    let conversationId = activeConversationId;
    const userMessage: ChatMessage = {
      id: `${makeId('msg')}-user`,
      sender: 'user',
      text: trimmedQuery,
      timestamp: formatMessageTime(now),
    };

    if (!conversationId || !storedConversations.some((item) => item.id === conversationId)) {
      conversationId = makeId('conv');
      const newConversation: Conversation = {
        id: conversationId,
        title: titleFromQuery(trimmedQuery),
        createdAt: now.toISOString(),
        updatedAt: now.toISOString(),
        messages: [userMessage],
      };
      setStoredConversations((prev) => [newConversation, ...prev]);
      setActiveConversationId(conversationId);
    } else {
      appendMessageToConversation(setStoredConversations, conversationId, userMessage);
    }

    setTransportState('submitting');
    setErrorMessage(null);

    try {
      const result = await apiClient.submitQuery({ query: trimmedQuery }, { signal: controller.signal });
      if (requestId !== requestSequenceRef.current) return;

      const citations = mapCitations(result);
      const assistantMessage: ChatMessage = {
        id: `${makeId('msg')}-asst`,
        sender: 'assistant',
        text: responseText(result),
        timestamp: formatMessageTime(new Date()),
        status: result.status,
        citations,
        reasoning: result.reasoning
          ? {
              observations: result.reasoning.observations,
              possible_causes: result.reasoning.possible_causes,
              recommended_checks: result.reasoning.recommended_checks,
              missing_information: result.reasoning.missing_information,
            }
          : undefined,
        evidenceBundle: result.evidence?.evidence,
        reviewReasons: result.review?.reasons,
      };

      appendMessageToConversation(setStoredConversations, conversationId, assistantMessage);
      setTransportState('success');
      setTimeout(() => setTransportState('idle'), 1200);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setErrorMessage((err as Error).message || 'Investigation could not be completed.');
      setTransportState('error');
    }
  }, [activeConversationId, storedConversations]);

  return (
    <ChatContext.Provider
      value={{
        transportState,
        errorMessage,
        connectionStatus,
        conversations,
        activeConversationId,
        storedConversations,
        messages,
        activeCitations,
        selectedCitationNumber,
        sessionAttachment,
        pdfLibrary,
        isMobileSidebarOpen,
        isSettingsOpen,
        isUploadModalOpen,
        documentsVersion,
        sendMessage,
        startNewChat,
        selectConversation,
        clearAllConversations,
        setSelectedCitation: setSelectedCitationNumber,
        attachSessionFile,
        removeSessionFile,
        checkBackendHealth,
        setIsMobileSidebarOpen,
        setSettingsOpen: setIsSettingsOpen,
        setUploadModalOpen: setIsUploadModalOpen,
        notifyDocumentsChanged,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
};

export default ChatProvider;

function responseText(result: QueryApiResponse): string {
  if (result.status === 'needs_clarification') {
    return result.routing.clarification_reason || 'Please provide more information to continue.';
  }
  return result.reasoning?.raw_answer || 'Investigation completed without a generated answer.';
}

function mapCitations(result: QueryApiResponse): EvidenceCitation[] {
  const evidenceById = new Map<string, QueryEvidence>();
  for (const item of result.evidence?.evidence ?? []) {
    evidenceById.set(item.evidence_id, item);
  }

  return (result.reasoning?.citations ?? []).map((citation, index) => {
    const evidence = evidenceById.get(citation.evidence_id);
    const documentId = evidence?.provenance.document_id ?? evidence?.provenance.source_id ?? null;
    return {
      citation_number: index + 1,
      evidence_id: citation.evidence_id,
      label: citation.label || String(index + 1),
      document_title: evidence?.title || 'Source unavailable',
      document_id: documentId,
      page_number: evidence?.provenance.page_start ?? undefined,
      snippet: evidence?.content || 'Source unavailable',
      section: evidence?.provenance.section || evidence?.provenance.chapter || undefined,
      retrieval_score: evidence?.retrieval_score ?? null,
      source_label: sourceLabel(documentId),
    };
  });
}

function sourceLabel(documentId: string | null): EvidenceCitation['source_label'] {
  if (documentId?.startsWith('USR-')) return 'Uploaded document';
  if (documentId?.startsWith('DOC-')) return 'Built-in document';
  return 'Structured evidence';
}

function loadStoredConversations(): Conversation[] {
  try {
    const raw = window.localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isConversation).sort(sortNewest);
  } catch {
    return [];
  }
}

function loadActiveConversationId(): string {
  try {
    return window.localStorage.getItem(ACTIVE_CONVERSATION_KEY) || '';
  } catch {
    return '';
  }
}

function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<Conversation>;
  return (
    typeof item.id === 'string'
    && typeof item.title === 'string'
    && typeof item.createdAt === 'string'
    && typeof item.updatedAt === 'string'
    && Array.isArray(item.messages)
  );
}

function saveLocalStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Chat remains usable in memory if localStorage is unavailable.
  }
}

function removeLocalStorage(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures; in-memory state is authoritative for this tab.
  }
}

function appendMessageToConversation(
  setStoredConversations: React.Dispatch<React.SetStateAction<Conversation[]>>,
  conversationId: string,
  message: ChatMessage,
): void {
  const updatedAt = new Date().toISOString();
  setStoredConversations((prev) =>
    prev.map((conversation) =>
      conversation.id === conversationId
        ? {
            ...conversation,
            updatedAt,
            messages: [...conversation.messages, message],
          }
        : conversation,
    ).sort(sortNewest),
  );
}

function toConversationSummaries(conversations: Conversation[]): ConversationSummary[] {
  return [...conversations].sort(sortNewest).map((conversation) => ({
    id: conversation.id,
    title: conversation.title,
    dateGroup: dateGroup(conversation.updatedAt),
    timestamp: formatMessageTime(new Date(conversation.updatedAt)),
    lastMessageSnippet: conversation.messages.at(-1)?.text,
  }));
}

function sortNewest(a: Conversation, b: Conversation): number {
  return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
}

function dateGroup(value: string): ConversationSummary['dateGroup'] {
  const date = new Date(value);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return 'Today';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return 'Older';
}

function formatMessageTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function makeId(prefix: string): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
