export const CONVERSATIONS_KEY = 'manufacturaiq.conversations.v1';
export const ACTIVE_CONVERSATION_KEY = 'manufacturaiq.activeConversationId.v1';

export function titleFromQuery(query: string): string {
  const cleaned = query.trim().replace(/\s+/g, ' ');
  const withoutLead = cleaned.replace(/^what are the\s+/i, '').replace(/^what is the\s+/i, '');
  const title = withoutLead.charAt(0).toUpperCase() + withoutLead.slice(1);
  const limit = 56;
  if (title.length <= limit) return title;
  return `${title.slice(0, limit - 1).trimEnd()}…`;
}
