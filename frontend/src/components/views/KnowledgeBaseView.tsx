import React, { useCallback, useEffect, useState } from 'react';
import {
  BookOpen,
  Plus,
  ArrowLeft,
  AlertCircle,
  Trash2,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import Breadcrumbs from '../layout/Breadcrumbs';
import { useChat } from '../../context/useChat';
import apiClient from '../../services/apiClient';
import type { UserDocument } from '../../types/contracts';

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function formatTimestamp(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export const KnowledgeBaseView: React.FC = () => {
  const { setUploadModalOpen, documentsVersion, notifyDocumentsChanged } = useChat();
  const [documents, setDocuments] = useState<UserDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.listDocuments();
      setDocuments(response.documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load documents.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    apiClient.listDocuments().then(
      (response) => {
        if (!active) return;
        setDocuments(response.documents);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Could not load documents.');
        setLoading(false);
      },
    );
    return () => {
      active = false;
    };
  }, [documentsVersion]);

  const remove = async (documentId: string) => {
    setDeletingId(documentId);
    setActionError(null);
    try {
      await apiClient.deleteDocument(documentId);
      setConfirmDeleteId(null);
      notifyDocumentsChanged();
      await refresh();
    } catch {
      setActionError('The document could not be deleted.');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent overflow-y-auto">
      <div className="p-6 md:p-8 max-w-5xl w-full mx-auto space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-brand-border">
          <div>
            <Breadcrumbs items={[{ label: 'Copilot Chat', to: '/' }, { label: 'Knowledge Base', to: '/knowledge-base' }]} />
            <div className="flex items-center gap-2 mb-1">
              <Link
                to="/"
                className="text-xs text-brand-accentText hover:underline flex items-center gap-1 font-medium transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Back to Copilot Chat</span>
              </Link>
            </div>
            <h1 className="text-2xl font-bold text-brand-text tracking-tight flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-brand-cardSubtle border border-brand-border text-brand-dark flex items-center justify-center shrink-0">
                <BookOpen className="w-4.5 h-4.5 text-brand-dark" />
              </div>
              <span>Knowledge Base</span>
            </h1>
            <p className="text-sm text-brand-textMuted mt-1">
              User-uploaded documents. The built-in manual corpus is separate.
            </p>
          </div>

          <div className="relative group">
            <button
              type="button"
              onClick={() => setUploadModalOpen(true)}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand-card border border-brand-border text-brand-text shadow-sm hover:border-brand-accent/40 transition-colors"
              title="Upload a PDF document"
            >
              <Plus className="w-4 h-4 text-brand-accentText" />
              <span className="text-xs font-semibold">Add PDF</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs flex items-start gap-3">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {actionError && (
          <div className="p-4 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs flex items-start gap-3">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{actionError}</span>
          </div>
        )}

        {loading ? (
          <div className="p-6 text-sm text-brand-textMuted">Loading documents…</div>
        ) : documents.length === 0 ? (
          <div className="p-6 rounded-xl bg-brand-surface border border-brand-border text-sm text-brand-textMuted">
            No uploaded documents yet.
          </div>
        ) : (
          <div className="space-y-3">
            {documents.map((document) => (
              <div
                key={document.document_id}
                className="p-4 rounded-xl bg-brand-surface border border-brand-border shadow-card"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-brand-text truncate">
                      {document.original_filename}
                    </p>
                    <p className="text-[11px] text-brand-textSubtle mt-0.5">
                      {document.status} · {document.page_count} pages · {document.chunk_count} chunks ·{' '}
                      {formatBytes(document.file_size_bytes)} · {formatTimestamp(document.created_at)}
                    </p>
                    {document.status === 'FAILED' && (
                      <p className="text-[11px] text-brand-warning mt-1">
                        {document.error_code ?? 'FAILED'}
                        {document.error_message ? ` — ${document.error_message}` : ''}
                      </p>
                    )}
                  </div>
                  {confirmDeleteId === document.document_id ? (
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        type="button"
                        disabled={deletingId === document.document_id}
                        onClick={() => void remove(document.document_id)}
                        className="px-2.5 py-1 rounded-md bg-brand-error/10 text-brand-error hover:bg-brand-error/20 text-[11px] font-medium disabled:opacity-50"
                      >
                        {deletingId === document.document_id ? 'Deleting…' : 'Confirm'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-2.5 py-1 rounded-md bg-brand-cardSubtle text-brand-textMuted text-[11px] font-medium"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(document.document_id)}
                      className="p-1.5 text-brand-textSubtle hover:text-brand-error rounded-md hover:bg-brand-error/10 transition-colors shrink-0"
                      title="Delete document"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="p-4 rounded-xl bg-brand-accentLight border border-brand-accent/20 text-xs text-brand-textMuted space-y-1">
          <p className="font-semibold text-brand-accentText">Grounding Protocol Notice</p>
          <p>
            Chat citations are returned by the backend query response with deterministic evidence identifiers. Document scores represent retrieval similarity, not subjective truth.
          </p>
        </div>
      </div>
    </div>
  );
};

export default KnowledgeBaseView;
