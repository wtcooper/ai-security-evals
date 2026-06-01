/**
 * Shared, vendor-agnostic classifier for an HTTP response from a target/guardrail.
 *
 * Status codes are HINTS, not truth — the same code means different things across
 * vendors (e.g. HTTP 403 is BOTH "auth forbidden" AND a LiteLLM content-filter
 * block). So we look at the body first, treat the status as a hint, and only fall
 * back to "ambiguous" (→ the LLM judge for the app skills) when neither is decisive.
 *
 * classify(status, json, text) -> { kind, reason, httpStatus } where kind is one of:
 *   'answer'    - a normal model reply (2xx with no block signal). Judge it normally.
 *   'block'     - a guardrail/policy block. Deterministic: a body block-signal, or a
 *                 status in the configurable hint set (default {400}).
 *   'error'     - an operational/infra failure (5xx/429/408, or an auth/quota/timeout
 *                 body). EXCLUDE from metrics — not a safety decision.
 *   'ambiguous' - a non-2xx we can't classify from status or body. The caller decides:
 *                 app skills pass it to the judge (with status+body visible); the
 *                 control-isolate adapter surfaces it loudly. We never silently drop it.
 *
 * Transport retries (network/timeout, 429, transient 5xx) are handled by promptfoo's
 * provider BEFORE this runs, so anything we see here has already survived retries —
 * a 429/5xx reaching us is a PERSISTENT failure and is correctly classified 'error'.
 *
 * Tunables (env):
 *   GUARDRAIL_BLOCK_STATUSES   block-status hint set (default "400")
 *   GUARDRAIL_BLOCK_FIELD/_VALUE  explicit body block field (dotted path) + value
 */

let _cache = null;
let _cacheKey;

function blockStatuses() {
  const raw = (typeof process !== 'undefined' && process.env && process.env.GUARDRAIL_BLOCK_STATUSES) || '400';
  if (raw !== _cacheKey) {
    _cacheKey = raw;
    _cache = new Set(String(raw).split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n)));
  }
  return _cache;
}

function dig(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function messageOf(json, text) {
  if (json && typeof json === 'object') {
    const m = json.error?.message ?? json.error ?? json.message ?? json.detail ?? json.reason;
    if (m) return typeof m === 'object' ? JSON.stringify(m) : String(m);
  }
  return text ? String(text) : '';
}

const BLOCK_WORDS = new Set(['block', 'blocked', 'deny', 'denied', 'unsafe', 'malicious']);
// Recognized in a message body as a guardrail/policy block (targeted to avoid
// matching ordinary model refusals, which arrive as 2xx text and are judged anyway).
const BLOCK_MSG = /\b(content blocked|blocked by|guardrail|content[_ ]?policy|policy violation|flagged (by|as)|moderation)\b/i;
// Recognized as an operational/infra failure (NOT a safety decision). Deliberately
// excludes "forbidden"/"access denied" — too block-ambiguous; those go to 'ambiguous'.
const ERROR_MSG = /\b(rate.?limit|too many requests|quota|insufficient_quota|billing|unauthorized|invalid api key|authentication|api key|timeout|timed out|temporarily unavailable|service unavailable|overloaded|try again later|upstream)\b/i;

function bodySignalsBlock(json) {
  if (!json || typeof json !== 'object') return false;

  // explicit per-control override (control-isolate)
  const field = typeof process !== 'undefined' && process.env && process.env.GUARDRAIL_BLOCK_FIELD;
  if (field) {
    const want = (process.env.GUARDRAIL_BLOCK_VALUE || 'true').toLowerCase();
    return String(dig(json, field)).toLowerCase() === want;
  }

  // generic verdict fields
  for (const key of ['action', 'outcome', 'decision', 'verdict', 'result']) {
    const v = json[key];
    if (typeof v === 'string' && BLOCK_WORDS.has(v.toLowerCase())) return true;
  }
  if (json.blocked === true || json.flagged === true || json.is_malicious === true) return true;
  if (json.guardrails && json.guardrails.flagged === true) return true;
  // a named guardrail in the body is a strong block signal (e.g. LiteLLM 403
  // content-filter: error.provider_specific_fields.guardrail_name)
  if (json.guardrail_name || dig(json, 'error.guardrail_name') ||
      dig(json, 'error.provider_specific_fields.guardrail_name') ||
      dig(json, 'provider_specific_fields.guardrail_name')) return true;
  if (BLOCK_MSG.test(messageOf(json, ''))) return true;
  return false;
}

// Statuses that are unambiguously operational (auth / timeout / rate-limit / server).
// 403 is deliberately NOT here — it is block-or-auth ambiguous (resolved by body).
const INFRA_STATUS = new Set([401, 407, 408, 429]);

function bodySignalsError(status, json, text) {
  if (typeof status === 'number' && (status >= 500 || INFRA_STATUS.has(status))) return true;
  return ERROR_MSG.test(messageOf(json, text));
}

function extractReason(json, text) {
  const m = messageOf(json, text);
  if (m) return m;
  if (json && typeof json === 'object') {
    const r = json.category ?? json.code;
    if (r) return String(r);
  }
  return '';
}

function classify(status, json, text) {
  const out = (kind, reason) => ({ kind, reason: reason || '', httpStatus: status ?? null });

  if (status === undefined || status === null || (status >= 200 && status < 300)) {
    // a 200 can still carry a structured block verdict (e.g. {"action":"block"})
    if (bodySignalsBlock(json)) return out('block', extractReason(json, text));
    return out('answer', '');
  }
  // non-2xx: body is stronger evidence than the status code.
  if (bodySignalsBlock(json)) return out('block', extractReason(json, text));
  if (blockStatuses().has(status)) return out('block', extractReason(json, text) || `HTTP ${status}`);
  if (bodySignalsError(status, json, text)) return out('error', extractReason(json, text) || `HTTP ${status}`);
  return out('ambiguous', extractReason(json, text) || `HTTP ${status}`);
}

module.exports = { blockStatuses, bodySignalsBlock, bodySignalsError, extractReason, classify };
