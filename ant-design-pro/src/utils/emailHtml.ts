/**
 * 邮件 HTML 处理：CID 内联图重写 + 基础消毒（对齐旧 emails.js）。
 */

export function normalizeEmailInlineResourceKey(value?: string | null): string {
  if (!value) return '';
  let normalized = String(value).trim();
  if (!normalized) return '';
  if (normalized.toLowerCase().startsWith('cid:')) {
    normalized = normalized.slice(4);
  }
  if (normalized.startsWith('<') && normalized.endsWith('>')) {
    normalized = normalized.slice(1, -1);
  }
  return normalized.trim().toLowerCase();
}

export function resolveEmailInlineResource(
  resourceMap: Record<string, string> | null | undefined,
  reference?: string | null,
): string {
  if (!resourceMap || typeof resourceMap !== 'object') return '';
  const key = normalizeEmailInlineResourceKey(reference);
  if (!key) return '';
  return resourceMap[key] || '';
}

/** 将 cid: 引用替换为 data URL / 可渲染 URL */
export function rewriteEmailInlineImages(
  html: string,
  inlineResources?: Record<string, string> | null,
): string {
  const sourceHtml = typeof html === 'string' ? html : '';
  const resourceMap =
    inlineResources && typeof inlineResources === 'object' ? inlineResources : null;
  if (
    !sourceHtml ||
    !resourceMap ||
    !Object.keys(resourceMap).length ||
    typeof DOMParser === 'undefined'
  ) {
    return sourceHtml;
  }
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(sourceHtml, 'text/html');
    const images = doc.querySelectorAll('img[src]');
    images.forEach((img) => {
      const originalSrc = img.getAttribute('src') || '';
      if (!/^cid:/i.test(originalSrc)) return;
      const resolved = resolveEmailInlineResource(resourceMap, originalSrc);
      if (resolved) img.setAttribute('src', resolved);
    });
    return doc.body ? doc.body.innerHTML : sourceHtml;
  } catch {
    return sourceHtml;
  }
}

/** 非信任模式下的基础消毒（DOMPurify 不可用时的回退） */
export function basicSanitizeEmailHtml(html: string): string {
  return String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
    .replace(/<object[\s\S]*?<\/object>/gi, '')
    .replace(/<embed[\s\S]*?<\/embed>/gi, '')
    .replace(/<form[\s\S]*?<\/form>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/javascript:/gi, '');
}

export function buildEmailSrcDoc(options: {
  body?: string;
  bodyType?: string;
  inlineResources?: Record<string, string> | null;
  trusted?: boolean;
}): string {
  const raw = String(options.body || '');
  if (!raw) return '';
  const isText = String(options.bodyType || '').toLowerCase() === 'text';
  if (isText) {
    const escaped = raw
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    return wrapEmailDocument(
      `<pre style="white-space:pre-wrap;font-family:inherit;margin:0">${escaped}</pre>`,
    );
  }
  const withCid = rewriteEmailInlineImages(raw, options.inlineResources);
  const body = options.trusted ? withCid : basicSanitizeEmailHtml(withCid);
  return wrapEmailDocument(body);
}

function wrapEmailDocument(bodyHtml: string): string {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;font-size:15px;line-height:1.6;color:#333;margin:0;padding:0;background:transparent}
img{max-width:100%;height:auto}a{color:#B85C38}
</style></head><body>${bodyHtml}</body></html>`;
}

export function sortEmailsByNewestFirst<T extends { date?: string }>(
  list: T[],
): T[] {
  return [...list].sort((a, b) => {
    const ta = Date.parse(String(a.date || '')) || 0;
    const tb = Date.parse(String(b.date || '')) || 0;
    return tb - ta;
  });
}
