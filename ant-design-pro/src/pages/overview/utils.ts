/** 概览页格式化工具 */

export function formatNumber(value: number | string | null | undefined): string {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return '0';
  return new Intl.NumberFormat('zh-CN').format(n);
}

/** rate 支持 0-1 或 0-100 */
export function formatPercent(value: number | string | null | undefined): string {
  let n = Number(value || 0);
  if (!Number.isFinite(n)) n = 0;
  if (n > 0 && n <= 1) n = n * 100;
  return `${n.toFixed(1)}%`;
}

export function formatDurationMs(ms: number | null | undefined): string {
  const n = Number(ms || 0);
  if (!Number.isFinite(n) || n <= 0) return '0ms';
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(2)}s`;
}

export function formatDurationSeconds(sec: number | null | undefined): string {
  const n = Number(sec || 0);
  if (!Number.isFinite(n) || n <= 0) return '0s';
  if (n < 60) return `${Math.round(n)}s`;
  if (n < 3600) return `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return `${h}h ${m}m`;
}

export function formatTime(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '--';
  // unix seconds
  if (typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))) {
    const n = Number(value);
    const ms = n > 1e12 ? n : n * 1000;
    const d = new Date(ms);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString('zh-CN');
  }
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('zh-CN');
}

export function channelLabel(channel?: string, label?: string): string {
  if (label) return label;
  const map: Record<string, string> = {
    graph_inbox: 'Graph Inbox',
    graph_junk: 'Graph Junk',
    imap_new: 'IMAP New',
    imap_old: 'IMAP Old',
    temp_mail: 'Temp Mail',
    ai_fallback: 'AI Fallback',
    graph_delta: 'Graph',
    imap_ssl: 'IMAP',
  };
  const key = String(channel || '').trim();
  return map[key] || key || 'unknown';
}
