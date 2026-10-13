import React, { useRef, useState } from 'react';
import { useChat } from '../../context/useChat';
import { ApiError, default as apiClient } from '../../services/apiClient';
import type { DocumentUploadResponse } from '../../types/contracts';
import { X, FileText, Upload, CheckCircle2, AlertTriangle } from 'lucide-react';

type UploadPhase = 'idle' | 'uploading' | 'success' | 'error';

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 413) return 'The PDF exceeds the upload size limit.';
    if (error.status === 415) return 'Only valid PDF documents are supported.';
    const code = (error.detail as { error_code?: string } | undefined)?.error_code;
    if (code === 'ENCRYPTED_PDF') return 'Password-protected PDFs are not supported.';
    if (code === 'NO_EXTRACTABLE_TEXT') return 'No extractable text was found in this PDF.';
    if (error.status === 503) return 'Document upload is currently unavailable. Try again later.';
    if (typeof error.detail === 'object' && error.detail !== null) {
      const message = (error.detail as { error?: string }).error;
      if (typeof message === 'string' && message && message.length < 200) return message;
    }
    return 'The document could not be uploaded. Try again.';
  }
  return 'The document could not be uploaded. Try again.';
}

export const UploadModal: React.FC = () => {
  const { isUploadModalOpen, setUploadModalOpen, notifyDocumentsChanged } = useChat();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [phase, setPhase] = useState<UploadPhase>('idle');
  const [serverMessage, setServerMessage] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  if (!isUploadModalOpen) return null;

  const reset = () => {
    requestRef.current?.abort();
    setSelectedFile(null);
    setClientError(null);
    setPhase('idle');
    setServerMessage(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const close = () => {
    reset();
    setUploadModalOpen(false);
  };

  const onSelect = (file: File | undefined) => {
    if (!file) return;
    if (file.type && file.type !== 'application/pdf') {
      setClientError('Only valid PDF documents are supported.');
      setSelectedFile(null);
      return;
    }
    setClientError(null);
    setSelectedFile(file);
    setPhase('idle');
    setServerMessage(null);
  };

  const submit = async () => {
    if (!selectedFile || phase === 'uploading') return;
    const controller = new AbortController();
    requestRef.current = controller;
    setPhase('uploading');
    setServerMessage(null);
    try {
      const result: DocumentUploadResponse = await apiClient.uploadDocument(selectedFile, {
        signal: controller.signal,
      });
      setServerMessage(
        result.duplicate === true
          ? 'This document already exists in the knowledge base.'
          : 'Document added to the knowledge base.',
      );
      setPhase('success');
      notifyDocumentsChanged();
    } catch (error) {
      if ((error as Error).name === 'AbortError') return;
      setServerMessage(friendlyError(error));
      setPhase('error');
    }
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/30 z-[80] animate-fadeIn"
        onClick={close}
      />

      {/* Modal */}
      <div className="fixed inset-0 z-[90] flex items-center justify-center p-4">
        <div className="bg-brand-surface rounded-2xl shadow-2xl w-full max-w-md animate-slideInUp border border-brand-border">
          {/* Header */}
          <div className="flex items-center justify-between p-5 border-b border-brand-border">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-brand-cardSubtle border border-brand-border text-brand-dark flex items-center justify-center">
                <Upload className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-brand-text">Document Ingestion</h2>
                <p className="text-xs text-brand-textMuted">Upload a PDF to the knowledge base</p>
              </div>
            </div>
            <button
              type="button"
              onClick={close}
              className="p-1.5 text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover rounded-lg transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="p-5 space-y-4">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="w-full p-4 rounded-xl border border-dashed border-brand-border bg-brand-cardSubtle text-left hover:border-brand-accent/40 transition-colors"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-brand-cardSubtle text-brand-dark flex items-center justify-center shrink-0">
                  <FileText className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-brand-text">
                    {selectedFile ? selectedFile.name : 'Select a PDF document'}
                  </h3>
                  <p className="text-xs text-brand-textMuted mt-1 leading-relaxed">
                    {selectedFile
                      ? `${(selectedFile.size / 1024).toFixed(1)} KB — ready to upload`
                      : 'Only PDF files are accepted. Text is indexed as data.'}
                  </p>
                </div>
              </div>
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => onSelect(e.target.files?.[0])}
            />

            {clientError && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{clientError}</span>
              </div>
            )}

            {phase === 'uploading' && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-brand-accentLight border border-brand-accent/20 text-brand-accentText text-xs">
                <span className="animate-pulse font-medium">Uploading / Processing…</span>
              </div>
            )}

            {phase === 'success' && serverMessage && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-brand-success/10 border border-brand-success/20 text-brand-success text-xs">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{serverMessage}</span>
              </div>
            )}

            {phase === 'error' && serverMessage && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{serverMessage}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 p-5 border-t border-brand-border">
            <button
              type="button"
              onClick={close}
              className="px-4 py-2 rounded-lg text-sm font-medium text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover transition-colors"
            >
              {phase === 'success' ? 'Done' : 'Cancel'}
            </button>
            {phase !== 'success' && (
              <button
                type="button"
                onClick={submit}
                disabled={!selectedFile || phase === 'uploading'}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-brand-accent text-brand-dark hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {phase === 'uploading' ? 'Uploading…' : 'Upload'}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default UploadModal;
