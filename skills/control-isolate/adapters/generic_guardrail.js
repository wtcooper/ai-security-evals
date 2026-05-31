/**
 * Generic, vendor-agnostic guardrail adapter for the control-isolate skill.
 *
 * Maps a guardrail/classifier API's response into promptfoo's native `guardrails`
 * object so `guardrails` / `not-guardrails` assertions grade it. A "block" is
 * inferred from EITHER:
 *
 *   1. the HTTP status (shared policy in ../../_shared/status_policy.js: a block
 *      status, default {400}, set GUARDRAIL_BLOCK_STATUSES e.g. "400,446"), OR
 *   2. a common block signal in the JSON body — recognized generically without
 *      per-vendor code:
 *        action/outcome/decision/verdict/result in {block,blocked,deny,denied,unsafe,malicious}
 *        blocked == true | flagged == true | is_malicious == true
 *      For an odd vendor, override with GUARDRAIL_BLOCK_FIELD + GUARDRAIL_BLOCK_VALUE
 *      (dotted path), e.g. FIELD="result.verdict" VALUE="unsafe".
 *
 * Operational errors (3xx, 401 auth, 429, 5xx — any non-2xx not in the block set)
 * throw -> errored, excluded from metrics (same policy as the app-eval transform).
 * This is the ONE place body-field block detection lives (Skill 4 only): the control
 * IS the thing under test, so its response shape is configured here once.
 */

const { classifyStatus, extractReason } = require('../../_shared/status_policy.js');

function dig(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

const BLOCK_WORDS = new Set(['block', 'blocked', 'deny', 'denied', 'unsafe', 'malicious']);

function bodySignalsBlock(json) {
  if (!json || typeof json !== 'object') return false;

  // explicit override
  const field = process.env && process.env.GUARDRAIL_BLOCK_FIELD;
  if (field) {
    const want = (process.env.GUARDRAIL_BLOCK_VALUE || 'true').toLowerCase();
    return String(dig(json, field)).toLowerCase() === want;
  }

  // generic recognizers
  for (const key of ['action', 'outcome', 'decision', 'verdict', 'result']) {
    const v = json[key];
    if (typeof v === 'string' && BLOCK_WORDS.has(v.toLowerCase())) return true;
  }
  if (json.blocked === true || json.flagged === true || json.is_malicious === true) return true;
  if (json.guardrails && json.guardrails.flagged === true) return true;
  return false;
}

module.exports = (json, text, context) => {
  const status = context && context.response && context.response.status;
  const kind = classifyStatus(status);

  // operational errors -> throw (excluded from metrics), consistent with app-eval.
  if (kind === 'error') {
    throw new Error(`Operational HTTP ${status} from guardrail — excluded. Body: ${String(text).slice(0, 160)}`);
  }

  const flagged = kind === 'block' || bodySignalsBlock(json);
  const reason = extractReason(json, text).slice(0, 300);
  return {
    output: flagged ? `[BLOCKED] ${reason}`.trim() : (text || 'allow'),
    guardrails: {
      flagged,
      flaggedInput: flagged,   // input-mode test: candidate rides in the request
      flaggedOutput: false,
      reason: reason || (flagged ? 'blocked' : 'allowed'),
    },
  };
};
