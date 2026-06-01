/**
 * Generic, vendor-agnostic guardrail adapter for the control-isolate skill.
 *
 * Maps a guardrail/classifier API's response into promptfoo's native `guardrails`
 * object (for `guardrails` / `not-guardrails` assertions) using the SHARED status
 * policy (../lib/status_policy.js) — body-signal first, status as a hint:
 *
 *   answer (2xx, no block signal) -> allowed (flagged: false)
 *   block (body signal or hint status) -> flagged: true
 *   error (5xx/429/408 or auth/quota/timeout body) -> throw (excluded from metrics)
 *   ambiguous (non-2xx, no signal) -> throw with a LOUD message naming the status.
 *     There is no judge here to fall back to, so rather than silently bucket an
 *     unmapped status as "allow" (under-counting blocks) we surface it and tell the
 *     operator to map it via GUARDRAIL_BLOCK_STATUSES / GUARDRAIL_BLOCK_FIELD+VALUE.
 *
 * Recognized block signals (no per-vendor code): action/outcome/decision/verdict in
 * {block,blocked,deny,denied,unsafe,malicious}; blocked/flagged/is_malicious == true;
 * guardrails.flagged; a guardrail_name in the body (e.g. LiteLLM 403 content-filter);
 * a "content blocked / guardrail / policy violation" message. Override with
 * GUARDRAIL_BLOCK_FIELD (dotted path) + GUARDRAIL_BLOCK_VALUE for odd shapes.
 */

const { classify } = require('../lib/status_policy.js');

module.exports = (json, text, context) => {
  const status = context && context.response && context.response.status;
  const c = classify(status, json, text);

  if (c.kind === 'error') {
    throw new Error(`Operational HTTP ${status} from guardrail (${c.reason}) — excluded. ` +
      `Body: ${String(text).slice(0, 160)}`);
  }
  if (c.kind === 'ambiguous') {
    throw new Error(`Unmapped guardrail response: HTTP ${status} with no recognizable ` +
      `block or error signal — excluded. If this is a block, map it via ` +
      `GUARDRAIL_BLOCK_STATUSES=${status} or GUARDRAIL_BLOCK_FIELD/VALUE. ` +
      `Body: ${String(text).slice(0, 160)}`);
  }

  const flagged = c.kind === 'block';
  return {
    output: flagged ? `[BLOCKED] ${c.reason}`.trim() : (text || 'allow'),
    guardrails: {
      flagged,
      flaggedInput: flagged,   // input-mode test: candidate rides in the request
      flaggedOutput: false,
      reason: c.reason || (flagged ? 'blocked' : 'allowed'),
    },
    metadata: { httpStatus: c.httpStatus, statusClass: c.kind },
  };
};
