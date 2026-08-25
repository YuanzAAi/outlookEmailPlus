const EMAIL_PREFIX = "email:";
const DEFAULT_CODE_TTL_SECONDS = 300;
const DEFAULT_BACKEND_WAIT_SECONDS = 0;
const DEFAULT_BACKEND_SINCE_MINUTES = 5;
const DEFAULT_BACKEND_FAST_TIMEOUT_MS = 1500;
const DEFAULT_BACKEND_TIMEOUT_MS = 18000;
const DEFAULT_CACHE_POLL_SECONDS = 15;
const DEFAULT_FULL_BACKEND_POLL_SECONDS = 15;
const DEFAULT_CATCHALL_EMAIL_DOMAINS = "yuangod.cc.cd";
const MEMORY_CACHE_MAX_ENTRIES = 1000;
const WRITE_MARKER_PREFIX = "written:";

const WAITING_MESSAGE = "暂时未收到验证码，请稍后重试";
const EMAIL_NOT_EXISTS_MESSAGE = "该邮箱不存在";
const memoryCache = new Map();

const VERIFICATION_KEYWORDS = [
  "验证码",
  "verification",
  "verify",
  "code",
  "otp",
  "security code",
  "confirmation code",
  "your code",
  "code is",
  "动态码",
  "校验码",
];

function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type,x-webhook-token",
    },
  });
}

function html(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    },
  });
}

function normalizeEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function normalizeCode(value) {
  const code = String(value || "").trim().toUpperCase();
  if (!/^[A-Z0-9]{4,8}$/.test(code)) return "";
  if (!/\d/.test(code)) return "";
  return code;
}

function normalizeMetadata(value) {
  const text = String(value || "").trim();
  return text === "-" ? "" : text;
}

function mergePayloadMetadata(payload, fallback) {
  return {
    ...payload,
    from: normalizeMetadata(payload?.from || payload?.from_address || payload?.sender || fallback?.from),
    subject: normalizeMetadata(payload?.subject || fallback?.subject),
  };
}

function hasSameMetadata(left, right) {
  return normalizeMetadata(left?.from) === normalizeMetadata(right?.from) &&
    normalizeMetadata(left?.subject) === normalizeMetadata(right?.subject);
}

function positiveInt(value, fallback, min = 1, max = 86400) {
  const parsed = Number.parseInt(String(value || "").trim(), 10);
  if (Number.isFinite(parsed) && parsed >= min && parsed <= max) return parsed;
  return fallback;
}

function getCodeTtlSeconds(env) {
  return positiveInt(env.CODE_TTL_SECONDS, DEFAULT_CODE_TTL_SECONDS);
}

function getBackendWaitSeconds(env) {
  return positiveInt(env.BACKEND_WAIT_SECONDS, DEFAULT_BACKEND_WAIT_SECONDS, 0, 90);
}

function getBackendSinceMinutes(env) {
  return positiveInt(env.BACKEND_SINCE_MINUTES, DEFAULT_BACKEND_SINCE_MINUTES, 1, 1440);
}

function getBackendFastTimeoutMs(env) {
  return positiveInt(env.BACKEND_FAST_TIMEOUT_MS, DEFAULT_BACKEND_FAST_TIMEOUT_MS, 250, 10000);
}

function getBackendTimeoutMs(env) {
  return positiveInt(env.BACKEND_TIMEOUT_MS, DEFAULT_BACKEND_TIMEOUT_MS, 1000, 90000);
}

function getCachePollSeconds(env) {
  return positiveInt(env.CACHE_POLL_SECONDS, DEFAULT_CACHE_POLL_SECONDS, 1, 300);
}

function getFullBackendPollSeconds(env) {
  return positiveInt(env.FULL_BACKEND_POLL_SECONDS, DEFAULT_FULL_BACKEND_POLL_SECONDS, 5, 300);
}

function isCatchallEmail(value, env) {
  const email = normalizeEmail(value);
  const separator = email.lastIndexOf("@");
  if (separator <= 0) return false;
  const domain = email.slice(separator + 1);
  const configured = String(env.CATCHALL_EMAIL_DOMAINS || DEFAULT_CATCHALL_EMAIL_DOMAINS);
  return configured
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .includes(domain);
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function memoryKey(email) {
  const normalized = normalizeEmail(email);
  return normalized ? EMAIL_PREFIX + normalized : "";
}

function writeMarkerKey(email, code) {
  const normalizedEmail = normalizeEmail(email);
  const normalizedCode = normalizeCode(code);
  return normalizedEmail && normalizedCode ? `${WRITE_MARKER_PREFIX}${normalizedEmail}:${normalizedCode}` : "";
}

function pruneMemoryCache() {
  const now = Date.now();
  for (const [key, value] of memoryCache.entries()) {
    if (!value || value.expiresAt <= now) memoryCache.delete(key);
  }
  while (memoryCache.size > MEMORY_CACHE_MAX_ENTRIES) {
    const firstKey = memoryCache.keys().next().value;
    if (!firstKey) break;
    memoryCache.delete(firstKey);
  }
}

function rememberPayload(payload, env) {
  const displayEmail = String(payload?.email || "").trim();
  const email = normalizeEmail(displayEmail);
  const code = normalizeCode(payload?.code);
  if (!email || !code) return false;
  pruneMemoryCache();
  memoryCache.set(memoryKey(email), {
    type: "hit",
    email: displayEmail || email,
    code,
    from: normalizeMetadata(payload?.from || payload?.from_address || payload?.sender),
    subject: normalizeMetadata(payload?.subject),
    folder: String(payload?.folder || "").trim(),
    source: String(payload?.source || "").trim(),
    received_at: String(payload?.received_at || "").trim(),
    expiresAt: Date.now() + getCodeTtlSeconds(env) * 1000,
  });
  return true;
}

function rememberKvWrite(email, code, env) {
  const key = writeMarkerKey(email, code);
  if (!key) return;
  pruneMemoryCache();
  memoryCache.set(key, {
    type: "write",
    expiresAt: Date.now() + getCodeTtlSeconds(env) * 1000,
  });
}

function hasRecentKvWrite(email, code) {
  const key = writeMarkerKey(email, code);
  if (!key) return false;
  const cached = memoryCache.get(key);
  if (!cached) return false;
  if (cached.expiresAt <= Date.now()) {
    memoryCache.delete(key);
    return false;
  }
  return cached.type === "write";
}

function rememberCacheMiss(email, env) {
  const key = memoryKey(email);
  if (!key) return;
  pruneMemoryCache();
  memoryCache.set(key, {
    type: "miss",
    expiresAt: Date.now() + getCachePollSeconds(env) * 1000,
  });
}

function readMemoryCode(email) {
  const key = memoryKey(email);
  if (!key) return null;
  const cached = memoryCache.get(key);
  if (!cached) return null;
  if (cached.expiresAt <= Date.now()) {
    memoryCache.delete(key);
    return null;
  }
  if (cached.type === "miss") return { miss: true };
  const code = normalizeCode(cached.code);
  return code
    ? {
        email: String(cached.email || email).trim(),
        code,
        from: normalizeMetadata(cached.from),
        subject: normalizeMetadata(cached.subject),
        folder: String(cached.folder || "").trim(),
        source: String(cached.source || "").trim(),
        received_at: String(cached.received_at || "").trim(),
      }
    : null;
}

function payloadTime(payload) {
  const parsed = Date.parse(String(payload?.received_at || payload?.updated_at || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function isReceivedAtFresh(payload, env) {
  const parsed = Date.parse(String(payload?.received_at || ""));
  if (!Number.isFinite(parsed)) return true;
  return Date.now() - parsed < getCodeTtlSeconds(env) * 1000;
}

function waiting(email = "") {
  return {
    success: false,
    email: String(email || "").trim(),
    code: "",
    message: WAITING_MESSAGE,
  };
}

function emailNotExists() {
  return {
    success: false,
    email: "",
    code: "",
    message: EMAIL_NOT_EXISTS_MESSAGE,
  };
}

function wantsHtml(request, url) {
  if (url.searchParams.get("format") === "json" || url.searchParams.get("api") === "1") return false;
  const accept = String(request.headers.get("accept") || "").toLowerCase();
  return accept.includes("text/html") && !accept.includes("application/json");
}

function renderPollingPage(email, env) {
  const emailJson = JSON.stringify(String(email || "").trim());
  const initialJson = JSON.stringify(waiting(email), null, 2);
  const cachePollMs = getCachePollSeconds(env) * 1000;
  const fullBackendPollMs = getFullBackendPollSeconds(env) * 1000;
  return html(`<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${String(email || "verification-code").replace(/[<>&"]/g, "")}</title>
  <style>
    body { margin: 0; padding: 12px; background: #fff; color: #111; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: 14px/1.45 Consolas, Monaco, "Courier New", monospace; }
    @media (prefers-color-scheme: dark) { body { background: #111; color: #eee; } }
  </style>
</head>
<body>
  <pre id="json">${initialJson.replace(/[<>&]/g, (c) => ({ "<": "\\u003c", ">": "\\u003e", "&": "\\u0026" }[c]))}</pre>
  <script>
    const email = ${emailJson};
    const pollDelayMs = 1000;
    const requestTimeoutMs = 20000;
    const cachePollMs = ${cachePollMs};
    const fullBackendPollMs = ${fullBackendPollMs};
    const jsonEl = document.getElementById("json");
    let lastPayloadText = JSON.stringify(${initialJson.replace(/[<>&]/g, (c) => ({ "<": "\\u003c", ">": "\\u003e", "&": "\\u0026" }[c]))});
    let lastRenderedText = jsonEl.textContent;
    let pendingText = "";
    let lastCachePollAt = 0;
    let resolvedCode = "";
    let displayedSuccessPayload = null;
    let waitingPolls = 0;
    let initialCacheProbeDone = false;
    let lastFullBackendPollAt = Date.now();
    let fullBackendPollInFlight = false;
    let nextRequestId = 0;
    let latestAppliedRequestId = 0;

    function sleep(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    function hasSelectionInside(element) {
      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return false;
      const range = selection.getRangeAt(0);
      return element.contains(range.commonAncestorContainer);
    }

    function updateJsonText(nextText) {
      if (nextText === lastRenderedText) return;
      if (hasSelectionInside(jsonEl)) {
        pendingText = nextText;
        return;
      }
      pendingText = "";
      jsonEl.textContent = nextText;
      lastRenderedText = nextText;
    }

    function notePollState(data) {
      if (data && data.success && data.code) {
        resolvedCode = String(data.code || "").trim();
        waitingPolls = 0;
      } else {
        waitingPolls += 1;
      }
    }

    function receivedTimestamp(data) {
      const timestamp = Date.parse(String(data?.received_at || ""));
      return Number.isFinite(timestamp) ? timestamp : 0;
    }

    function mergeSuccessfulPayload(current, incoming) {
      if (!current || String(current.code || "") !== String(incoming.code || "")) return incoming;
      const merged = { ...current, ...incoming };
      for (const key of ["from", "subject", "folder", "received_at"]) {
        if (!incoming[key] && current[key]) merged[key] = current[key];
      }
      return merged;
    }

    function formatLocalTimestamp(value) {
      const date = new Date(String(value || ""));
      if (Number.isNaN(date.getTime())) return String(value || "");
      const parts = new Intl.DateTimeFormat("sv-SE", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).formatToParts(date);
      const values = {};
      for (const part of parts) values[part.type] = part.value;
      return [
        values.year,
        values.month,
        values.day,
      ].join("-") + " " + [
        values.hour,
        values.minute,
        values.second,
      ].join(":");
    }

    function renderPayload(data) {
      notePollState(data);
      const hasCode = Boolean(data && data.success && data.code);
      if (!hasCode && displayedSuccessPayload) return;
      if (hasCode && displayedSuccessPayload) {
        const currentCode = String(displayedSuccessPayload.code || "");
        const incomingCode = String(data.code || "");
        if (
          incomingCode !== currentCode &&
          receivedTimestamp(data) &&
          receivedTimestamp(displayedSuccessPayload) &&
          receivedTimestamp(data) < receivedTimestamp(displayedSuccessPayload)
        ) {
          return;
        }
        data = mergeSuccessfulPayload(displayedSuccessPayload, data);
      }
      if (hasCode) displayedSuccessPayload = data;
      const payloadText = JSON.stringify(data || null);
      if (payloadText === lastPayloadText) return;
      lastPayloadText = payloadText;
      const displayData = data && typeof data === "object" ? { ...data } : data;
      if (displayData && typeof displayData === "object") {
        if (displayData.received_at) {
          displayData.received_at = formatLocalTimestamp(displayData.received_at);
        }
        displayData.polled_at = formatLocalTimestamp(new Date().toISOString());
      }
      updateJsonText(JSON.stringify(displayData, null, 2));
    }

    document.addEventListener("selectionchange", () => {
      if (pendingText && !hasSelectionInside(jsonEl)) {
        updateJsonText(pendingText);
      }
    });

    async function requestPayload(url, renderErrors = true) {
      const requestId = ++nextRequestId;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
      try {
        const response = await fetch(url.toString(), {
          headers: { accept: "application/json" },
          cache: "no-store",
          signal: controller.signal,
        });
        const data = await response.json();
        const hasCode = Boolean(data && data.success && data.code);
        if (requestId < latestAppliedRequestId && !hasCode) return;
        latestAppliedRequestId = Math.max(latestAppliedRequestId, requestId);
        renderPayload(data);
      } catch (error) {
        if (!renderErrors || requestId < latestAppliedRequestId) return;
        latestAppliedRequestId = requestId;
        renderPayload({
          success: false,
          email,
          code: "",
          message: "请求超时或网络异常，正在重试"
        });
      } finally {
        clearTimeout(timeout);
      }
    }

    async function pollFullBackend() {
      if (fullBackendPollInFlight) return;
      fullBackendPollInFlight = true;
      const url = new URL(window.location.href);
      url.searchParams.set("format", "json");
      url.searchParams.set("fast", "0");
      url.searchParams.set("cache", "0");
      url.searchParams.set("_", String(Date.now()));
      try {
        await requestPayload(url, false);
      } finally {
        lastFullBackendPollAt = Date.now();
        fullBackendPollInFlight = false;
      }
    }

    async function pollOnce() {
      const url = new URL(window.location.href);
      url.searchParams.set("format", "json");
      url.searchParams.set("fast", "1");
      const now = Date.now();
      const shouldProbeCache =
        (
          !initialCacheProbeDone ||
          (waitingPolls >= 3 && now - lastCachePollAt >= cachePollMs)
        );
      if (shouldProbeCache) {
        url.searchParams.set("cache", "1");
        initialCacheProbeDone = true;
        lastCachePollAt = now;
      } else {
        url.searchParams.set("cache", "0");
      }
      url.searchParams.set("_", String(Date.now()));
      await requestPayload(url);

      const fullProbeNow = Date.now();
      if (
        waitingPolls >= 3 &&
        fullProbeNow - lastFullBackendPollAt >= fullBackendPollMs
      ) {
        void pollFullBackend();
      }
    }

    async function loop() {
      while (true) {
        await pollOnce();
        await sleep(waitingPolls >= 3 ? 3000 : pollDelayMs);
      }
    }

    // 先给 fast/cache 请求机会，避免页面打开时被慢的全量检索阻塞。
    setTimeout(() => {
      void pollFullBackend();
    }, 250);
    loop();
  </script>
</body>
</html>`);
}

function pickLine(text, label) {
  const re = new RegExp(`^${label}:\\s*(.+)$`, "im");
  const match = String(text || "").match(re);
  return match ? match[1].trim() : "";
}

function extractEmail(text) {
  const labelled = pickLine(text, "来源邮箱");
  const source = labelled || String(text || "");
  const match = source.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return match ? normalizeEmail(match[0]) : "";
}

function extractSearchText(text) {
  const subject = pickLine(text, "主题");
  const bodyMatch = String(text || "").match(/正文摘要:\s*([\s\S]*)$/i);
  const body = bodyMatch ? bodyMatch[1] : text;
  return `${subject}\n${body || ""}`;
}

function codeCandidates(text) {
  return [...String(text || "").matchAll(/\b[A-Z0-9]{4,8}\b/gi)]
    .map((match) => normalizeCode(match[0]))
    .filter(Boolean);
}

function isWeakNumericCandidate(code) {
  if (!/^\d{4}$/.test(code)) return false;
  const value = Number(code);
  if (value >= 1900 && value <= 2100) return true;
  const hour = Number(code.slice(0, 2));
  const minute = Number(code.slice(2));
  return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
}

function extractCodeFromWebhookText(text) {
  const source = extractSearchText(text);
  const lower = source.toLowerCase();

  for (const keyword of VERIFICATION_KEYWORDS) {
    const index = lower.indexOf(keyword.toLowerCase());
    if (index === -1) continue;
    const context = source.slice(Math.max(0, index - 80), index + keyword.length + 80);
    const code = codeCandidates(context).find((item) => !isWeakNumericCandidate(item));
    if (code) return code;
  }

  return codeCandidates(source).find((item) => !isWeakNumericCandidate(item)) || "";
}

async function saveCodePayload(payload, env, options = {}) {
  const displayEmail = String(payload?.email || "").trim();
  const email = normalizeEmail(displayEmail);
  const code = normalizeCode(payload?.code);
  if (!email || !code || !isReceivedAtFresh(payload, env)) return false;

  let stored = {
    email: displayEmail || email,
    code,
    from: normalizeMetadata(payload?.from || payload?.from_address || payload?.sender),
    subject: normalizeMetadata(payload?.subject),
    received_at: payload.received_at || new Date().toISOString(),
    updated_at: new Date().toISOString(),
    source: payload.source || "",
    folder: payload.folder || "",
  };
  const putOptions = { expirationTtl: getCodeTtlSeconds(env) };
  const key = EMAIL_PREFIX + email;
  if (options.dedupe && hasRecentKvWrite(email, code)) {
    const cached = readMemoryCode(email);
    stored = mergePayloadMetadata(stored, cached);
    rememberPayload(stored, env);
    if (cached?.code === code && hasSameMetadata(stored, cached)) return true;
  }

  if (options.protectNewer) {
    const raw = await env.EMAIL_CODES.get(key);
    if (raw) {
      try {
        const existing = JSON.parse(raw);
        if (isPayloadFresh(existing, env)) {
          const existingCode = normalizeCode(existing.code);
          const existingTime = payloadTime(existing);
          const storedTime = payloadTime(stored);
          if (existingCode === code) {
            const preferExisting = existingTime >= storedTime;
            const preferred = preferExisting ? existing : stored;
            const fallback = preferExisting ? stored : existing;
            const merged = mergePayloadMetadata(preferred, fallback);
            if (preferExisting && hasSameMetadata(merged, existing)) {
              rememberPayload(existing, env);
              rememberKvWrite(email, code, env);
              return true;
            }
            stored = { ...merged, updated_at: new Date().toISOString() };
          } else if (existingTime >= storedTime) {
            rememberPayload(existing, env);
            rememberKvWrite(email, code, env);
            return true;
          }
        }
      } catch {
        // Malformed cache will be overwritten by the current valid payload.
      }
    }
  }

  rememberPayload(stored, env);
  await env.EMAIL_CODES.put(key, JSON.stringify(stored), putOptions);
  rememberKvWrite(email, code, env);
  return true;
}

async function saveWebhook(request, env) {
  const expectedToken = String(env.WEBHOOK_TOKEN || "").trim();
  if (expectedToken) {
    const provided = String(request.headers.get("x-webhook-token") || "").trim();
    if (provided !== expectedToken) return json({ ok: false, error: "unauthorized" }, 401);
  }

  const text = await request.text();
  const payload = {
    email: extractEmail(text),
    code: extractCodeFromWebhookText(text),
    from: pickLine(text, "发件人"),
    subject: pickLine(text, "主题"),
    received_at: pickLine(text, "时间") || new Date().toISOString(),
  };
  const saved = await saveCodePayload(payload, env, { dedupe: true, protectNewer: true });
  return json({ ok: true, saved, email: payload.email || "", code: payload.code || "" });
}

async function fetchBackendJson(path, params, env, options = {}) {
  const baseUrl = normalizeBaseUrl(env.BACKEND_BASE_URL);
  const apiKey = String(env.BACKEND_API_KEY || "").trim();
  if (!baseUrl || !apiKey) return null;

  const url = new URL(`${baseUrl}${path}`);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && String(value) !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || getBackendTimeoutMs(env));
  try {
    const response = await fetch(url.toString(), {
      headers: {
        accept: "application/json",
        "user-agent": "OutlookEmailPlusWebhook/2.0",
        "x-api-key": apiKey,
      },
      signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      return {
        backend_error: true,
        status: response.status,
        code: String(data?.code || data?.error?.code || "").trim().toUpperCase(),
        message: data?.message || data?.error?.message || "",
        data,
      };
    }
    return data;
  } catch {
    return {
      backend_error: true,
      status: 0,
      code: "BACKEND_UNAVAILABLE",
      message: "Backend request failed",
    };
  } finally {
    clearTimeout(timeout);
  }
}

function isBackendAccountNotFound(result) {
  return result?.backend_error && result.code === "ACCOUNT_NOT_FOUND";
}

function backendAccountNotFoundPayload() {
  return { account_not_found: true };
}

function isBackendAccountNotFoundPayload(payload) {
  return payload?.account_not_found === true;
}

function pickReceivedAt(data) {
  return data?.received_at || data?.created_at || data?.message?.received_at || new Date().toISOString();
}

function buildBackendPayload(result, requestedEmail, folder, code, source) {
  const data = result?.data || {};
  return {
    email: String(data.email || data.email_address || requestedEmail || "").trim(),
    code,
    from: normalizeMetadata(data.from || data.from_address || data.sender || result?.from),
    subject: normalizeMetadata(data.subject || result?.subject),
    folder: String(data.folder || folder || "").trim(),
    source,
    received_at: pickReceivedAt(data),
  };
}

async function fetchBackendSummaryCode(email, env) {
  const requestedEmail = String(email || "").trim();
  if (!requestedEmail) return null;

  const result = await fetchBackendJson(
    "/api/external/verification-summary",
    {
      email: requestedEmail,
      since_minutes: getBackendSinceMinutes(env),
    },
    env,
    { timeoutMs: getBackendFastTimeoutMs(env) },
  );
  if (isBackendAccountNotFound(result)) return backendAccountNotFoundPayload();
  const data = result?.data || {};
  const code = normalizeCode(data.verification_code || result?.verification_code || result?.code);
  if (!code) return null;
  return buildBackendPayload(result, requestedEmail, data.folder || "", code, "backend_summary");
}

async function fetchBackendVerificationCode(email, env) {
  const requestedEmail = String(email || "").trim();
  if (!requestedEmail) return null;

  const summaryPayload = await fetchBackendSummaryCode(requestedEmail, env);
  if (isBackendAccountNotFoundPayload(summaryPayload)) return summaryPayload;
  if (summaryPayload) return summaryPayload;

  // 后端默认入口会按账号实际通道统一覆盖 Graph/IMAP 的 Inbox 与 Junk。
  // 单次调用可复用 Graph token、并行 IMAP 文件夹读取，并返回真实 folder。
  const result = await fetchBackendJson(
    "/api/external/verification-code",
    {
      email: requestedEmail,
      wait: getBackendWaitSeconds(env),
      since_minutes: getBackendSinceMinutes(env),
    },
    env,
    { timeoutMs: getBackendTimeoutMs(env) },
  );
  if (isBackendAccountNotFound(result)) return backendAccountNotFoundPayload();
  const code = normalizeCode(result?.data?.verification_code || result?.verification_code || result?.code);
  if (!code) return null;
  const folder = String(result?.data?.folder || result?.folder || "").trim();
  return buildBackendPayload(result, requestedEmail, folder, code, "backend");
}

function isPayloadFresh(payload, env) {
  const updatedAt = Date.parse(String(payload?.updated_at || ""));
  return Number.isFinite(updatedAt) && Date.now() - updatedAt < getCodeTtlSeconds(env) * 1000;
}

async function readCachedCode(email, env, options = {}) {
  const allowKv = options.allowKv !== false;
  const memoryPayload = readMemoryCode(email);
  if (memoryPayload?.miss) return null;
  if (memoryPayload?.code) return memoryPayload;
  if (!allowKv) return null;

  const normalizedEmail = normalizeEmail(email);
  if (!normalizedEmail) return null;
  const key = EMAIL_PREFIX + normalizedEmail;
  const raw = await env.EMAIL_CODES.get(key);
  if (!raw) {
    rememberCacheMiss(normalizedEmail, env);
    return null;
  }

  try {
    const payload = JSON.parse(raw);
    if (!isPayloadFresh(payload, env)) {
      rememberCacheMiss(normalizedEmail, env);
      return null;
    }
    const code = normalizeCode(payload.code);
    if (!code) return null;
    const stored = {
      email: String(payload.email || normalizedEmail).trim(),
      code,
      from: normalizeMetadata(payload.from || payload.from_address || payload.sender),
      subject: normalizeMetadata(payload.subject),
      folder: String(payload.folder || "").trim(),
      source: String(payload.source || "").trim(),
      received_at: String(payload.received_at || "").trim(),
    };
    rememberPayload(stored, env);
    return stored;
  } catch {
    rememberCacheMiss(normalizedEmail, env);
    return null;
  }
}

async function readCode(request, env) {
  const url = new URL(request.url);
  const rawEmail = String(url.searchParams.get("email") || "").trim();
  const fast = url.searchParams.get("fast") === "1";
  const allowCache = url.searchParams.get("cache") !== "0";

  if (request.method === "GET" && rawEmail && wantsHtml(request, url)) {
    return renderPollingPage(rawEmail, env);
  }

  if (!rawEmail) return json({ success: false, error: "not_found", message: "接口不存在" }, 404);

  let cached;
  if (fast && allowCache) {
    cached = await readCachedCode(normalizeEmail(rawEmail), env);
    if (cached) {
      return json({
        success: true,
        email: cached.email,
        code: cached.code,
        from: cached.from || "",
        subject: cached.subject || "",
        source: "cache",
        folder: cached.folder || undefined,
        received_at: cached.received_at || undefined,
      });
    }
  }

  // 高频 fast 轮询只负责低频 KV 探测，不再重复请求后端摘要。
  if (fast) return json(waiting(rawEmail));

  const backendPayload = await fetchBackendVerificationCode(rawEmail, env);
  if (isBackendAccountNotFoundPayload(backendPayload)) {
    if (!isCatchallEmail(rawEmail, env)) return json(emailNotExists());
  } else if (backendPayload) {
    await saveCodePayload(backendPayload, env, { dedupe: true, protectNewer: true });
    const savedPayload = readMemoryCode(backendPayload.email || rawEmail);
    const responsePayload = savedPayload?.code === backendPayload.code
      ? mergePayloadMetadata(backendPayload, savedPayload)
      : backendPayload;
    return json({
      success: true,
      email: responsePayload.email,
      code: responsePayload.code,
      from: responsePayload.from || "",
      subject: responsePayload.subject || "",
      source: responsePayload.source || "backend",
      folder: responsePayload.folder,
      received_at: responsePayload.received_at,
    });
  }

  if (!cached) {
    cached = await readCachedCode(normalizeEmail(rawEmail), env, { allowKv: allowCache });
  }
  if (cached) {
    return json({
      success: true,
      email: cached.email,
      code: cached.code,
      from: cached.from || "",
      subject: cached.subject || "",
      source: "cache",
      folder: cached.folder || undefined,
      received_at: cached.received_at || undefined,
    });
  }

  return json(waiting(rawEmail));
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return json({ ok: true });

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/" && url.searchParams.get("email")) {
      return readCode(request, env);
    }
    if (request.method === "POST" && url.pathname === "/webhook") {
      return saveWebhook(request, env);
    }

    return json({ success: false, error: "not_found", message: "接口不存在" }, 404);
  },
};
