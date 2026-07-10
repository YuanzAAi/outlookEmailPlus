/**
 * SPA 轮询引擎（对齐 static/js/features/poll-engine.js 最小可用子集）
 * - 多账号并行
 * - 按 interval / maxCount 停止
 * - 发现新邮件后尝试提取验证码
 */
import { extractEmailVerification, fetchEmails } from './emails';
import { fetchSettings } from './settings';

export type PollStatus = 'idle' | 'polling' | 'stopped' | 'error' | 'found';

export type PollSnapshot = {
  email: string;
  status: PollStatus;
  pollCount: number;
  maxCount: number;
  remaining: number;
  lastMessage?: string;
  verification?: string;
};

type PollState = {
  timer: ReturnType<typeof setInterval> | null;
  baselineIds: Set<string>;
  errorCount: number;
  pollCount: number;
  isPolling: boolean;
  intervalSec: number;
  maxCount: number;
  lastMessage?: string;
  verification?: string;
  status: PollStatus;
};

export type PollSettings = {
  enabled: boolean;
  interval: number;
  maxCount: number;
};

type Listener = (snapshots: PollSnapshot[]) => void;

const pollMap = new Map<string, PollState>();
const listeners = new Set<Listener>();

let settingsCache: PollSettings = {
  enabled: false,
  interval: 10,
  maxCount: 5,
};

function emit() {
  const snaps = getPollSnapshots();
  listeners.forEach((fn) => {
    try {
      fn(snaps);
    } catch {
      /* ignore */
    }
  });
}

export function getPollSnapshots(): PollSnapshot[] {
  return Array.from(pollMap.entries()).map(([email, state]) => ({
    email,
    status: state.status,
    pollCount: state.pollCount,
    maxCount: state.maxCount,
    remaining:
      state.maxCount > 0
        ? Math.max(0, state.maxCount - state.pollCount)
        : 0,
    lastMessage: state.lastMessage,
    verification: state.verification,
  }));
}

export function getPollSnapshot(email: string): PollSnapshot | undefined {
  return getPollSnapshots().find((s) => s.email === email);
}

export function subscribePoll(listener: Listener): () => void {
  listeners.add(listener);
  listener(getPollSnapshots());
  return () => listeners.delete(listener);
}

export function getPollSettings(): PollSettings {
  return { ...settingsCache };
}

export async function loadPollSettingsFromServer(): Promise<PollSettings> {
  try {
    const res = await fetchSettings();
    const s = res?.settings || {};
    settingsCache = {
      enabled: !!(
        s.enable_auto_polling === true ||
        s.enable_auto_polling === 'true' ||
        s.enable_auto_polling === 1 ||
        s.enable_auto_polling === '1'
      ),
      interval: Number(s.polling_interval || 10) || 10,
      maxCount: Number(s.polling_count || 5) || 5,
    };
  } catch {
    /* keep cache */
  }
  return getPollSettings();
}

export function applyPollSettings(partial: Partial<PollSettings>) {
  settingsCache = {
    ...settingsCache,
    ...partial,
    interval: Math.max(1, Number(partial.interval ?? settingsCache.interval) || 10),
    maxCount: Math.max(0, Number(partial.maxCount ?? settingsCache.maxCount) || 0),
  };
  // 运行中的轮询沿用新间隔需重启；此处仅更新缓存，UI 可选择 restart
  emit();
}

function stopInternal(email: string, message?: string, status: PollStatus = 'stopped') {
  const state = pollMap.get(email);
  if (!state) return;
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  state.status = status;
  state.lastMessage = message;
  state.isPolling = false;
  pollMap.delete(email);
  // 保留最后快照给 UI：用临时 entry 再 emit 后删除会丢，改为 emit 前写入 ghost
  // 简化：直接 emit 当前 map，并额外通知一次带 message 的 snapshot
  emit();
}

export function stopPoll(email: string, message?: string) {
  stopInternal(email, message, 'stopped');
}

export function stopAllPolls() {
  const keys = Array.from(pollMap.keys());
  keys.forEach((email) => stopInternal(email, undefined, 'stopped'));
}

async function collectFolderIds(email: string, folder: string): Promise<string[]> {
  const res = await fetchEmails(email, {
    method: 'graph',
    folder,
    skip: 0,
    top: 50,
  });
  if (res?.success && Array.isArray(res.emails)) {
    return res.emails.map((e) => e.id).filter(Boolean);
  }
  return [];
}

async function pollOnce(email: string, state: PollState) {
  if (!pollMap.has(email) || state.isPolling) return;
  state.isPolling = true;
  state.status = 'polling';
  emit();
  try {
    const [inboxIds, junkIds] = await Promise.all([
      collectFolderIds(email, 'inbox'),
      collectFolderIds(email, 'junkemail').catch(() => [] as string[]),
    ]);
    if (!pollMap.has(email)) return;

    state.pollCount += 1;
    state.errorCount = 0;
    const allIds = new Set([...inboxIds, ...junkIds]);
    let hasNew = false;
    allIds.forEach((id) => {
      if (!state.baselineIds.has(id)) hasNew = true;
    });

    if (state.maxCount > 0 && state.pollCount >= state.maxCount && !hasNew) {
      stopInternal(email, '监听超时，未检测到新邮件', 'stopped');
      return;
    }

    if (!hasNew) {
      state.isPolling = false;
      emit();
      return;
    }

    // 发现新邮件 → 尝试提取验证码
    try {
      const vres = await extractEmailVerification(email);
      if (vres?.success && vres.data) {
        const code =
          vres.data.verification_code ||
          vres.data.code ||
          vres.data.formatted ||
          '';
        if (code) {
          state.verification = String(code);
          try {
            await navigator.clipboard.writeText(String(code));
          } catch {
            /* ignore */
          }
          stopInternal(email, `检测到验证码：${code}`, 'found');
          return;
        }
      }
    } catch {
      /* fall through */
    }
    stopInternal(email, '发现新邮件', 'found');
  } catch {
    state.errorCount += 1;
    state.isPolling = false;
    state.status = 'error';
    emit();
    if (state.errorCount >= 3) {
      stopInternal(email, '拉取失败，已停止监听', 'error');
    }
  }
}

export async function startPoll(
  email: string,
  opts?: { interval?: number; maxCount?: number; force?: boolean },
) {
  const addr = String(email || '').trim();
  if (!addr) return;
  if (!opts?.force && !settingsCache.enabled) {
    // 仍允许 force 启动（邮箱页手动监听）
  }
  if (pollMap.has(addr)) {
    stopInternal(addr);
  }

  const intervalSec = opts?.interval ?? settingsCache.interval ?? 10;
  const maxCount =
    opts?.maxCount !== undefined ? opts.maxCount : settingsCache.maxCount ?? 5;

  const state: PollState = {
    timer: null,
    baselineIds: new Set(),
    errorCount: 0,
    pollCount: 0,
    isPolling: false,
    intervalSec,
    maxCount,
    status: 'polling',
  };
  pollMap.set(addr, state);
  emit();

  try {
    const [inboxIds, junkIds] = await Promise.all([
      collectFolderIds(addr, 'inbox'),
      collectFolderIds(addr, 'junkemail').catch(() => [] as string[]),
    ]);
    if (!pollMap.has(addr)) return;
    [...inboxIds, ...junkIds].forEach((id) => state.baselineIds.add(id));
  } catch {
    // baseline 失败仍继续轮询
  }

  // 首次轮询略延迟，确保 baseline 写入
  setTimeout(() => {
    if (pollMap.has(addr)) void pollOnce(addr, state);
  }, 150);

  state.timer = setInterval(() => {
    if (pollMap.has(addr)) void pollOnce(addr, state);
  }, Math.max(1, intervalSec) * 1000);
}

export function isPolling(email: string): boolean {
  return pollMap.has(email);
}
