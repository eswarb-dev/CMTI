import React, { useState, useEffect, useRef } from 'react';
import { useChat } from '../../context/useChat';
import type { ConversationSummary } from '../../types/contracts';
import {
  Plus,
  MessageSquare,
  X,
  Search,
  Pin,
  MoreHorizontal,
  Pencil,
  Trash2,
  Share2,
} from 'lucide-react';

export const Sidebar: React.FC = () => {
  const {
    conversations,
    activeConversationId,
    selectConversation,
    startNewChat,
    clearAllConversations,
    isMobileSidebarOpen,
    setIsMobileSidebarOpen,
  } = useChat();

  // Local-only UI state — no backend wiring exists yet for pin/rename/delete/share
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(new Set());
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [renamedTitles, setRenamedTitles] = useState<Record<string, string>>({});
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmClearAll, setConfirmClearAll] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the open menu on outside click or Escape
  useEffect(() => {
    if (!openMenuId) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
        setConfirmDeleteId(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpenMenuId(null);
        setConfirmDeleteId(null);
        setRenamingId(null);
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [openMenuId]);

  const togglePin = (id: string) => {
    setPinnedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const displayTitle = (conv: ConversationSummary) => renamedTitles[conv.id] ?? conv.title;

  const startRename = (conv: ConversationSummary) => {
    setRenameValue(displayTitle(conv));
    setRenamingId(conv.id);
    setOpenMenuId(null);
    setConfirmDeleteId(null);
  };

  const commitRename = (id: string) => {
    const value = renameValue.trim();
    if (value) {
      // TODO: wire to a backend rename endpoint — local-only display override for now
      console.log(`[TODO] Rename conversation ${id} to "${value}" — needs backend wiring`);
      setRenamedTitles((prev) => ({ ...prev, [id]: value }));
    }
    setRenamingId(null);
  };

  const confirmDelete = (id: string) => {
    // TODO: wire to a backend delete endpoint — local-only hide for now
    console.log(`[TODO] Delete conversation ${id} — needs backend wiring`);
    setHiddenIds((prev) => new Set(prev).add(id));
    setConfirmDeleteId(null);
    setOpenMenuId(null);
  };

  const handleShare = (id: string) => {
    // TODO: no share endpoint exists — do not fake a share link
    console.log(`[TODO] Share conversation ${id} — no share endpoint exists`);
    setOpenMenuId(null);
  };

  const visibleConversations = conversations.filter((c) => !hiddenIds.has(c.id));
  const pinnedConversations = visibleConversations.filter((c) => pinnedIds.has(c.id));
  const unpinnedConversations = visibleConversations.filter((c) => !pinnedIds.has(c.id));

  const renderRow = (conv: ConversationSummary) => {
    const isActive = activeConversationId === conv.id;
    const isPinned = pinnedIds.has(conv.id);
    const isMenuOpen = openMenuId === conv.id;
    const title = displayTitle(conv);

    return (
      <div
        key={conv.id}
        onClick={() => {
          if (renamingId !== conv.id) {
            selectConversation(conv.id);
            if (isMobileSidebarOpen) setIsMobileSidebarOpen(false);
          }
        }}
        className={`group relative flex items-center justify-between px-2.5 py-2 rounded-lg text-xs cursor-pointer transition-colors ${
          isActive
            ? 'bg-brand-card text-brand-dark font-semibold border-l-2 border-brand-accent'
            : 'text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover'
        }`}
      >
        {renamingId === conv.id ? (
          <input
            autoFocus
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename(conv.id);
              if (e.key === 'Escape') setRenamingId(null);
            }}
            onBlur={() => commitRename(conv.id)}
            onClick={(e) => e.stopPropagation()}
            className="w-full bg-brand-surface border border-brand-accent rounded-md px-2 py-1 text-xs text-brand-dark focus:outline-none"
          />
        ) : (
          <>
            <div className="flex items-center gap-2.5 truncate min-w-0">
              <MessageSquare
                className={`w-3.5 h-3.5 shrink-0 ${
                  isActive ? 'text-brand-accentText' : 'text-brand-textSubtle'
                }`}
              />
              <span className="truncate" title={title}>
                {title}
              </span>
            </div>
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  togglePin(conv.id);
                }}
                className={`p-1 rounded-md transition-colors ${
                  isPinned
                    ? 'text-brand-accentText'
                    : 'text-brand-textSubtle hover:text-brand-accentText hover:bg-brand-surface'
                }`}
                title={isPinned ? 'Unpin conversation' : 'Pin conversation'}
              >
                <Pin
                  className="w-3.5 h-3.5"
                  fill={isPinned ? 'currentColor' : 'none'}
                />
              </button>
              <div className="relative" ref={isMenuOpen ? menuRef : undefined}>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDeleteId(null);
                    setOpenMenuId(isMenuOpen ? null : conv.id);
                  }}
                  className={`p-1 text-brand-textSubtle hover:text-brand-dark rounded-md hover:bg-brand-surface transition-colors ${
                    isActive || isMenuOpen ? 'flex' : 'hidden group-hover:flex'
                  }`}
                  title="Conversation options"
                >
                  <MoreHorizontal className="w-3.5 h-3.5" />
                </button>
                {isMenuOpen && (
                  <div className="absolute right-0 top-full mt-1 w-40 bg-brand-surface border border-brand-border rounded-lg shadow-card z-50 py-1">
                    {confirmDeleteId === conv.id ? (
                      <div className="px-3 py-2">
                        <p className="text-[11px] font-medium text-brand-text mb-2">
                          Delete this conversation?
                        </p>
                        <div className="flex gap-1.5">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              confirmDelete(conv.id);
                            }}
                            className="flex-1 px-2 py-1 rounded-md bg-brand-error/10 text-brand-error hover:bg-brand-error/20 text-[11px] font-medium transition-colors"
                          >
                            Delete
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(null);
                            }}
                            className="flex-1 px-2 py-1 rounded-md bg-brand-cardSubtle text-brand-textMuted hover:text-brand-dark text-[11px] font-medium transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            startRename(conv);
                          }}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover transition-colors"
                        >
                          <Pencil className="w-3 h-3" />
                          <span>Rename</span>
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(conv.id);
                          }}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-brand-textMuted hover:text-brand-error hover:bg-brand-error/10 transition-colors"
                        >
                          <Trash2 className="w-3 h-3" />
                          <span>Delete</span>
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleShare(conv.id);
                          }}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover transition-colors"
                        >
                          <Share2 className="w-3 h-3" />
                          <span>Share</span>
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    );
  };

  return (
    <>
      {/* Mobile Backdrop */}
      {isMobileSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-40 lg:hidden"
          onClick={() => setIsMobileSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed lg:static top-0 left-0 z-50 h-full w-72 bg-brand-surface border-r border-brand-border flex flex-col transition-transform duration-200 ease-in-out shrink-0 ${
          isMobileSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        {/* Mobile Header Close */}
        <div className="lg:hidden flex items-center justify-between p-3 border-b border-brand-border">
          <span className="text-xs font-semibold text-brand-textMuted uppercase tracking-wider">
            Conversations
          </span>
          <button
            type="button"
            onClick={() => setIsMobileSidebarOpen(false)}
            className="p-1 text-brand-textMuted hover:text-brand-dark rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* New Chat — prominent button */}
        <div className="p-3.5">
          <button
            type="button"
            onClick={() => {
              startNewChat();
              if (isMobileSidebarOpen) setIsMobileSidebarOpen(false);
            }}
            className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-full bg-brand-card border border-brand-border text-brand-dark font-medium text-sm shadow-sm transition-all hover:border-brand-accent/50 hover:shadow-card active:scale-[0.98] cursor-pointer"
          >
            <Plus className="w-4 h-4 text-brand-accentText" />
            <span>New Chat</span>
          </button>
        </div>

        {/* Scrollable Center: History List */}
        <div className="flex-1 overflow-y-auto px-3 py-2">
          {/* Section Header with Search + Clear All */}
          <div className="flex items-center justify-between px-2 py-1">
            <div className="flex items-center gap-2 text-xs font-semibold text-brand-text">
              <span>Your conversations</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="p-1 text-brand-textSubtle hover:text-brand-dark rounded-md hover:bg-brand-cardHover transition-colors"
                title="Search conversations"
              >
                <Search className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => {
                  if (confirmClearAll) {
                    clearAllConversations();
                    setConfirmClearAll(false);
                    return;
                  }
                  setConfirmClearAll(true);
                }}
                className="text-[10px] text-brand-textSubtle hover:text-brand-error font-medium px-1.5 py-0.5 rounded hover:bg-brand-error/10 transition-colors"
                title="Clear all conversations"
              >
                {confirmClearAll ? 'Confirm' : 'Clear All'}
              </button>
            </div>
          </div>

          {visibleConversations.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <p className="text-xs text-brand-textMuted">No conversations yet</p>
            </div>
          ) : (
            <>
              {/* Pinned — only rendered when at least one conversation is pinned */}
              {pinnedConversations.length > 0 && (
                <div className="mt-1 space-y-0.5">
                  <span className="px-2 text-[11px] font-semibold text-brand-textSubtle uppercase tracking-wider block">
                    Pinned
                  </span>
                  {pinnedConversations.map((conv) => renderRow(conv))}
                </div>
              )}

              {/* Conversations — every other conversation, most recent first */}
              <div className="mt-2 space-y-0.5">
                <span className="px-2 text-[11px] font-semibold text-brand-textSubtle uppercase tracking-wider block">
                  Conversations
                </span>
                {unpinnedConversations.length > 0 ? (
                  unpinnedConversations.map((conv) => renderRow(conv))
                ) : (
                  <p className="px-2 py-1 text-[11px] text-brand-textSubtle">
                    All conversations are pinned.
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
