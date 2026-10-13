/**
 * Demo-only placeholders.
 *
 * Production chat execution must use apiClient.ts and the FastAPI backend.
 * These exports remain available for future stories or visual fixtures, but
 * they are intentionally empty so the UI cannot present mock backend records
 * as live conversations, indexed documents, citations, or answers.
 */
import type { ChatMessage, ConversationSummary, IndexedDocument } from '../types/contracts';

export const INITIAL_CONVERSATIONS: ConversationSummary[] = [];
export const INITIAL_PDF_LIBRARY: IndexedDocument[] = [];
export const INITIAL_MESSAGES: ChatMessage[] = [];
