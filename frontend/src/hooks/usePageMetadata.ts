import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

interface PageMetadata {
  title: string;
  description: string;
  canonicalPath: string;
}

const SITE_NAME = 'ManufacturaIQ';
const DEFAULT_DESCRIPTION =
  'AI-powered manufacturing engineering copilot. Ask about CNC equipment, manuals, lockout/tagout, alarms, and maintenance.';

const ROUTE_METADATA: Record<string, PageMetadata> = {
  '/': {
    title: `${SITE_NAME} — Manufacturing Engineering Copilot`,
    description: DEFAULT_DESCRIPTION,
    canonicalPath: '/',
  },
  '/knowledge-base': {
    title: `Knowledge Base — ${SITE_NAME}`,
    description: 'Indexed manufacturing equipment manuals, SOPs, and engineering reference documents.',
    canonicalPath: '/knowledge-base',
  },
  '/uploads': {
    title: `Upload Pipeline — ${SITE_NAME}`,
    description: 'Document ingestion history, indexing queue, and processing status.',
    canonicalPath: '/uploads',
  },
};

function getOrCreateMeta(attr: 'name' | 'property', key: string): HTMLMetaElement {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  return el;
}

function setMetaContent(attr: 'name' | 'property', key: string, content: string) {
  getOrCreateMeta(attr, key).setAttribute('content', content);
}

function setCanonicalUrl(path: string) {
  const url = `${window.location.origin}${path}`;
  let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!link) {
    link = document.createElement('link');
    link.setAttribute('rel', 'canonical');
    document.head.appendChild(link);
  }
  link.setAttribute('href', url);
}

export function usePageMetadata() {
  const location = useLocation();

  useEffect(() => {
    const meta =
      ROUTE_METADATA[location.pathname] ?? {
        title: `${SITE_NAME} — Manufacturing Engineering Copilot`,
        description: DEFAULT_DESCRIPTION,
        canonicalPath: location.pathname,
      };

    // Document title
    document.title = meta.title;

    // Meta description
    setMetaContent('name', 'description', meta.description);

    // Canonical URL
    setCanonicalUrl(meta.canonicalPath);

    // Open Graph tags
    setMetaContent('property', 'og:title', meta.title);
    setMetaContent('property', 'og:description', meta.description);
    setMetaContent('property', 'og:type', 'website');
    setMetaContent('property', 'og:url', `${window.location.origin}${meta.canonicalPath}`);
    setMetaContent('property', 'og:site_name', SITE_NAME);
    // TODO: Replace with actual social image URL when available
    setMetaContent('property', 'og:image', `${window.location.origin}/og-image.png`);

    // Twitter Card tags
    setMetaContent('name', 'twitter:card', 'summary_large_image');
    setMetaContent('name', 'twitter:title', meta.title);
    setMetaContent('name', 'twitter:description', meta.description);
    // TODO: Replace with actual social image URL when available
    setMetaContent('name', 'twitter:image', `${window.location.origin}/og-image.png`);
  }, [location.pathname]);
}
