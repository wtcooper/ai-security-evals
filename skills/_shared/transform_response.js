/**
 * Shared promptfoo transformResponse for security evaluation (vendor-agnostic).
 *
 * promptfoo's HTTP provider accepts all status codes, so we decide here what each
 * one means. The HTTP-status policy is shared with the control-isolate adapter via
 * ./status_policy.js (one definition, no drift):
 *
 *   'ok'    (2xx / no status) -> extract the reply text across common body shapes
 *                               (OpenAI / Anthropic / custom). The llm-rubric judge
 *                               then decides refusal vs compliance. Apps that turn a
 *                               guardrail block into a 200 + refusal text are handled
 *                               here automatically.
 *   'block' (default {400},   -> a guardrail/policy block. Emit promptfoo's native
 *            GUARDRAIL_BLOCK_     `guardrails` object so `guardrails`/`not-guardrails`
 *            STATUSES)            assertions work, AND a sentinel in `output` so a
 *                               plain llm-rubric reads it as "refused / blocked".
 *   'error' (other non-2xx)   -> operational (3xx/401/429/5xx). NOT a guardrail
 *                               decision, so throw: promptfoo records the test as
 *                               errored and EXCLUDES it from metrics, so a broken run
 *                               is visible instead of scoring as "secure".
 *
 * Body-field block detection (200 + {"action":"block"}) is deliberately NOT done here
 * — that only appears when calling a guardrail API directly (control-isolate).
 */

const { classifyStatus, extractReason } = require('./status_policy.js');

function extractText(json, text) {
  if (json && typeof json === 'object') {
    const msgs = Array.isArray(json.messages) ? json.messages : null;
    return (
      json.response ??
      json.output ??
      json.text ??
      json.completion ??
      json.message?.content ??
      (msgs && msgs[msgs.length - 1]?.content) ??   // {messages:[...]} (last turn)
      json.choices?.[0]?.message?.content ??         // OpenAI chat
      json.choices?.[0]?.text ??                     // OpenAI completion
      json.content?.[0]?.text ??                     // Anthropic
      text ??
      JSON.stringify(json)
    );
  }
  return text ?? '';
}

module.exports = (json, text, context) => {
  const status = context && context.response && context.response.status;

  switch (classifyStatus(status)) {
    case 'ok':
      return extractText(json, text);
    case 'block': {
      const reason = extractReason(json, text).slice(0, 300);
      return {
        output: `[GUARDRAIL_BLOCK] The target returned HTTP ${status} and refused the request. ${reason}`.trim(),
        guardrails: { flagged: true, flaggedInput: true, flaggedOutput: false, reason: reason || `HTTP ${status}` },
      };
    }
    default: // 'error'
      throw new Error(
        `Operational HTTP ${status} (not a guardrail block) — test marked as error, ` +
          `excluded from security metrics. Body: ${String(text).slice(0, 200)}`,
      );
  }
};
