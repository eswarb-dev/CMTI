import React, { useEffect, useState } from 'react';
import {
  UploadCloud,
  FileCheck2,
  ArrowLeft,
  AlertCircle,
  Clock,
  Layers,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import Breadcrumbs from '../layout/Breadcrumbs';
import { useChat } from '../../context/useChat';
import apiClient from '../../services/apiClient';
import type { UserDocument } from '../../types/contracts';

function formatTimestamp(value: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export const UploadsView: React.FC = () => {
  const { documentsVersion } = useChat();
  const [documents, setDocuments] = useState<UserDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        setError(err instanceof Error ? err.message : 'Could not load ingestion records.');
        setLoading(false);
      },
    );
    return () => {
      active = false;
    };
  }, [documentsVersion]);

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent overflow-y-auto">
      <div className="p-6 md:p-8 max-w-5xl w-full mx-auto space-y-6">
        <div className="pb-6 border-b border-brand-border">
          <Breadcrumbs items={[{ label: 'Copilot Chat', to: '/' }, { label: 'Document Ingestion Pipeline', to: '/uploads' }]} />
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
              <UploadCloud className="w-4.5 h-4.5 text-brand-dark" />
            </div>
            <span>Document Ingestion Pipeline</span>
          </h1>
          <p className="text-sm text-brand-textMuted mt-1">
            Live document ingestion records — PDF parsing, text chunking, embeddings, and vector storage.
          </p>
        </div>

        {error && (
          <div className="p-4 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs flex items-start gap-3">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Ingestion Pipeline Steps */}
        <div className="bg-brand-surface border border-brand-border rounded-xl p-5 shadow-card space-y-4">
          <h3 className="text-sm font-semibold text-brand-text flex items-center gap-2">
            <div className="w-6 h-6 rounded-lg bg-brand-cardSubtle text-brand-dark flex items-center justify-center">
              <Layers className="w-3.5 h-3.5 text-brand-dark" />
            </div>
            <span>Standard Ingestion Protocol (STEP 05 - STEP 06)</span>
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-2">
            <div className="p-3.5 rounded-xl bg-brand-cardSubtle border border-brand-success/20 space-y-1.5 shadow-sm">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-brand-text">1. Extract</span>
                <div className="w-5 h-5 rounded-md bg-brand-success/10 text-brand-success flex items-center justify-center">
                  <FileCheck2 className="w-3.5 h-3.5 text-brand-success" />
                </div>
              </div>
              <p className="text-[11px] text-brand-textMuted">
                PDF text, candidate headings, and page boundaries extracted.
              </p>
            </div>

            <div className="p-3.5 rounded-xl bg-brand-cardSubtle border border-brand-success/20 space-y-1.5 shadow-sm">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-brand-text">2. Chunk</span>
                <div className="w-5 h-5 rounded-md bg-brand-success/10 text-brand-success flex items-center justify-center">
                  <FileCheck2 className="w-3.5 h-3.5 text-brand-success" />
                </div>
              </div>
              <p className="text-[11px] text-brand-textMuted">
                Hierarchical parent-child chunking preserving section provenance.
              </p>
            </div>

            <div className="p-3.5 rounded-xl bg-brand-cardSubtle border border-brand-success/20 space-y-1.5 shadow-sm">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-brand-text">3. Embed</span>
                <div className="w-5 h-5 rounded-md bg-brand-success/10 text-brand-success flex items-center justify-center">
                  <FileCheck2 className="w-3.5 h-3.5 text-brand-success" />
                </div>
              </div>
              <p className="text-[11px] text-brand-textMuted">
                BGE Small dense embedding generation per document chunk.
              </p>
            </div>

            <div className="p-3.5 rounded-xl bg-brand-cardSubtle border border-brand-accent/20 space-y-1.5 shadow-sm">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-brand-text">4. Vector Store</span>
                <div className="w-5 h-5 rounded-md bg-brand-accentLight text-brand-accentText flex items-center justify-center">
                  <Clock className="w-3.5 h-3.5 text-brand-accentText" />
                </div>
              </div>
              <p className="text-[11px] text-brand-textMuted">
                Vector collection with payload metadata and single-client lock.
              </p>
            </div>
          </div>
        </div>

        <div className="bg-brand-surface border border-brand-border rounded-xl shadow-card p-5">
          <h3 className="text-sm font-semibold text-brand-text mb-3">Ingestion records</h3>
          {loading ? (
            <p className="text-sm text-brand-textMuted">Loading ingestion records…</p>
          ) : documents.length === 0 ? (
            <p className="text-sm text-brand-textMuted">
              No ingestion records yet. Upload a PDF to create one.
            </p>
          ) : (
            <div className="space-y-2">
              {documents.map((document) => (
                <div
                  key={document.document_id}
                  className="p-3 rounded-lg bg-brand-cardSubtle border border-brand-border text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-brand-text truncate">
                      {document.original_filename}
                    </span>
                    <span className="text-brand-textSubtle shrink-0">{document.status}</span>
                  </div>
                  <p className="text-brand-textSubtle mt-1">
                    {formatTimestamp(document.created_at)} · {document.page_count} pages ·{' '}
                    {document.chunk_count} chunks
                    {document.status === 'FAILED' && document.error_code
                      ? ` · ${document.error_code}${document.error_message ? ` — ${document.error_message}` : ''}`
                      : ''}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default UploadsView;
