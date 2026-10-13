import { createContext } from 'react';
import type {
  ChatMessage,
  ConnectionStatus,
  Conversation,
  ConversationSummary,
  EvidenceCitation,
  IndexedDocument,
  SessionAttachment,
  UiTransportState,
} from '../types/contracts';

export interface ChatContextType {
  // State
  transportState: UiTransportState;
  errorMessage: string | null;
  connectionStatus: ConnectionStatus;
  conversations: ConversationSummary[];
  activeConversationId: string;
  storedConversations: Conversation[];
  messages: ChatMessage[];
  activeCitations: EvidenceCitation[];
  selectedCitationNumber: number | null;
  sessionAttachment: SessionAttachment | null;
  pdfLibrary: IndexedDocument[];
  isMobileSidebarOpen: boolean;
  isSettingsOpen: boolean;
  isUploadModalOpen: boolean;
  documentsVersion: number;

  // Actions
  sendMessage: (text: string) => Promise<void>;
  startNewChat: () => void;
  selectConversation: (id: string) => void;
  clearAllConversations: () => void;
  setSelectedCitation: (citationNumber: number | null) => void;
  attachSessionFile: (file: File) => Promise<void>;
  removeSessionFile: () => void;
  checkBackendHealth: () => Promise<void>;
  setIsMobileSidebarOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setUploadModalOpen: (open: boolean) => void;
  notifyDocumentsChanged: () => void;
}

export const ChatContext = createContext<ChatContextType | undefined>(undefined);
