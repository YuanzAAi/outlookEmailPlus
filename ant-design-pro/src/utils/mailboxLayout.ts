/**
 * SPA 三栏布局状态（对齐 static/js/layout-manager.js + state-manager.js 最小可用子集）
 * - panels: groups / accounts / emails
 * - localStorage key: outlook_layout_state_{userId}
 * - 宽度上下限与默认值与旧 LayoutManager 一致
 */

export type PanelKey = 'groups' | 'accounts' | 'emails';

export type PanelState = {
  width: number;
  collapsed: boolean;
};

export type MailboxLayoutState = {
  version: string;
  userId: string;
  panels: Record<PanelKey, PanelState>;
  timestamp?: number;
};

export type MailboxViewMode = 'standard' | 'compact';

export const LAYOUT_VERSION = '1.1';
export const STORAGE_KEY_PREFIX = 'outlook_layout_state_';
export const VIEW_MODE_KEY = 'ol_mailbox_view_mode';

export const DEFAULT_WIDTHS: Record<PanelKey, number> = {
  groups: 200,
  accounts: 260,
  emails: 380,
};

export const MIN_WIDTHS: Record<PanelKey, number> = {
  groups: 150,
  accounts: 180,
  emails: 280,
};

export const MAX_WIDTHS: Record<PanelKey, number> = {
  groups: 400,
  accounts: 500,
  emails: 600,
};

export const PANEL_LABELS: Record<PanelKey, string> = {
  groups: '分组',
  accounts: '账号',
  emails: '邮件',
};

export function clampWidth(panel: PanelKey, width: number): number {
  const n = Math.round(Number(width) || DEFAULT_WIDTHS[panel]);
  return Math.min(MAX_WIDTHS[panel], Math.max(MIN_WIDTHS[panel], n));
}

export function createDefaultLayout(userId = 'guest'): MailboxLayoutState {
  return {
    version: LAYOUT_VERSION,
    userId: userId || 'guest',
    panels: {
      groups: { width: DEFAULT_WIDTHS.groups, collapsed: false },
      accounts: { width: DEFAULT_WIDTHS.accounts, collapsed: false },
      emails: { width: DEFAULT_WIDTHS.emails, collapsed: false },
    },
    timestamp: Date.now(),
  };
}

function parsePx(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw !== 'string') return null;
  const m = raw.trim().match(/^(\d+(?:\.\d+)?)px$/i);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

export function validateLayoutState(state: any): state is MailboxLayoutState {
  if (!state || typeof state !== 'object') return false;
  if (!state.version || !state.panels || typeof state.panels !== 'object') {
    return false;
  }
  for (const key of ['groups', 'accounts', 'emails'] as PanelKey[]) {
    const panel = state.panels[key];
    if (!panel || typeof panel !== 'object') return false;
    const width =
      typeof panel.width === 'number' ? panel.width : parsePx(panel.width);
    if (width == null) return false;
    if (typeof panel.collapsed !== 'boolean') return false;
  }
  return true;
}

function normalizeLoaded(raw: any, userId: string): MailboxLayoutState {
  const base = createDefaultLayout(userId);
  if (!validateLayoutState(raw)) return base;
  const panels = { ...base.panels };
  (['groups', 'accounts', 'emails'] as PanelKey[]).forEach((key) => {
    const p = raw.panels[key];
    const widthVal =
      typeof p.width === 'number' ? p.width : parsePx(p.width) || DEFAULT_WIDTHS[key];
    panels[key] = {
      width: clampWidth(key, widthVal),
      collapsed: !!p.collapsed,
    };
  });
  return {
    version: LAYOUT_VERSION,
    userId: String(raw.userId || userId || 'guest'),
    panels,
    timestamp: Number(raw.timestamp) || Date.now(),
  };
}

export function loadLayoutState(userId = 'guest'): MailboxLayoutState {
  try {
    const key = `${STORAGE_KEY_PREFIX}${userId || 'guest'}`;
    const raw = localStorage.getItem(key);
    if (!raw) return createDefaultLayout(userId);
    return normalizeLoaded(JSON.parse(raw), userId);
  } catch {
    return createDefaultLayout(userId);
  }
}

export function saveLayoutState(
  state: MailboxLayoutState,
  userId = 'guest',
): boolean {
  try {
    const payload: MailboxLayoutState = {
      ...state,
      version: LAYOUT_VERSION,
      userId: userId || state.userId || 'guest',
      timestamp: Date.now(),
    };
    if (!validateLayoutState(payload)) return false;
    // 序列化时 width 存 "Npx" 与旧 StateManager 兼容
    const serializable = {
      ...payload,
      panels: {
        groups: {
          width: `${payload.panels.groups.width}px`,
          collapsed: payload.panels.groups.collapsed,
        },
        accounts: {
          width: `${payload.panels.accounts.width}px`,
          collapsed: payload.panels.accounts.collapsed,
        },
        emails: {
          width: `${payload.panels.emails.width}px`,
          collapsed: payload.panels.emails.collapsed,
        },
      },
    };
    localStorage.setItem(
      `${STORAGE_KEY_PREFIX}${userId || 'guest'}`,
      JSON.stringify(serializable),
    );
    return true;
  } catch {
    return false;
  }
}

export function loadViewMode(): MailboxViewMode {
  try {
    const v = localStorage.getItem(VIEW_MODE_KEY);
    return v === 'compact' ? 'compact' : 'standard';
  } catch {
    return 'standard';
  }
}

export function saveViewMode(mode: MailboxViewMode) {
  try {
    localStorage.setItem(
      VIEW_MODE_KEY,
      mode === 'compact' ? 'compact' : 'standard',
    );
  } catch {
    /* ignore */
  }
}

/** 计算标准三栏 grid-template-columns（折叠列宽为 36px 指示条） */
export function buildGridTemplate(panels: Record<PanelKey, PanelState>): string {
  const col = (key: PanelKey) =>
    panels[key].collapsed ? '36px' : `${panels[key].width}px`;
  // 邮件列用 minmax 吃掉剩余空间，但保留保存宽度作为 min
  const emails = panels.emails.collapsed
    ? '36px'
    : `minmax(${panels.emails.width}px, 1fr)`;
  return `${col('groups')} 6px ${col('accounts')} 6px ${emails}`;
}
