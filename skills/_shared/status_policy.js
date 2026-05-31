/**
 * Shared, vendor-agnostic HTTP-status block policy for guardrail evaluation.
 *
 * One place decides what an HTTP status means, so the app-eval transform and the
 * control-isolate adapter never drift:
 *   2xx / no status -> 'ok'     (a normal answer; caller extracts text)
 *   block status     -> 'block'  (a guardrail/policy block; default {400},
 *                                 configurable via GUARDRAIL_BLOCK_STATUSES)
 *   any other non-2xx-> 'error'  (operational: 3xx/auth/rate-limit/5xx — caller
 *                                 throws so promptfoo excludes it from metrics)
 *
 * The block-status set is parsed once per env value (memoized), not per request.
 */

let _cache = null;
let _cacheKey;

function blockStatuses() {
  const raw = (typeof process !== 'undefined' && process.env && process.env.GUARDRAIL_BLOCK_STATUSES) || '400';
  if (raw !== _cacheKey) {
    _cacheKey = raw;
    _cache = new Set(
      String(raw).split(',').map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n)),
    );
  }
  return _cache;
}

// 'ok' | 'block' | 'error'
function classifyStatus(status) {
  if (status === undefined || status === null) return 'ok';
  if (status >= 200 && status < 300) return 'ok';
  if (blockStatuses().has(status)) return 'block';
  return 'error';
}

// Best-effort human-readable reason from a block/error body (superset of the
// shapes both callers previously handled), truncated by the caller.
function extractReason(json, text) {
  if (json && typeof json === 'object') {
    const r =
      json.reason ??
      json.category ??
      json.error?.message ??
      json.error ??
      json.message ??
      json.detail;
    if (r) return typeof r === 'object' ? JSON.stringify(r) : String(r);
  }
  return text ? String(text) : '';
}

module.exports = { blockStatuses, classifyStatus, extractReason };
