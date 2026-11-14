/** Tests for the control-isolate guardrail adapter (classify-driven). */
const path = require('path');
const adapt = require(path.join(__dirname, '..', 'adapters', 'generic_guardrail.js'));
let pass = 0, fail = 0;
const check = (n, c) => { c ? pass++ : (fail++, console.error('FAIL:', n)); };
const ctx = (status) => ({ response: { status } });
const threw = (fn) => { try { fn(); return false; } catch (e) { return true; } };

// --- allowed (2xx, no block signal) ---
check('200 action:allow -> not flagged', adapt({ action: 'allow', category: 'benign' }, '', ctx(200)).guardrails.flagged === false);
check('allowed metadata', adapt({ action: 'allow' }, '', ctx(200)).metadata.statusClass === 'answer');

// --- blocks via body signal (status-agnostic) ---
check('action:block', adapt({ action: 'block' }, '', ctx(200)).guardrails.flagged === true);
check('blocked:true', adapt({ blocked: true }, '', ctx(200)).guardrails.flagged === true);
check('is_malicious', adapt({ is_malicious: true }, '', ctx(200)).guardrails.flagged === true);
check('outcome:deny', adapt({ outcome: 'deny' }, '', ctx(200)).guardrails.flagged === true);
check('nested guardrails', adapt({ guardrails: { flagged: true } }, '', ctx(200)).guardrails.flagged === true);
check('403 litellm content-filter -> flagged',
  adapt({ error: { message: 'Content blocked', provider_specific_fields: { guardrail_name: 'content-filter' } } }, '', ctx(403)).guardrails.flagged === true);
check('block metadata', adapt({ action: 'block' }, '', ctx(200)).metadata.statusClass === 'block');
check('block sentinel output', adapt({ action: 'block', category: 'malicious' }, '', ctx(200)).output.startsWith('[BLOCKED]'));

// --- block via status hint ---
check('400 bare -> flagged', adapt({}, 'nope', ctx(400)).guardrails.flagged === true);

// --- operational errors throw (excluded) ---
for (const code of [500, 503, 429, 408, 401]) check(`HTTP ${code} throws`, threw(() => adapt({}, 'x', ctx(code))));
check('403 + auth throws', threw(() => adapt({ error: { message: 'invalid api key' } }, '', ctx(403))));

// --- ambiguous: throws loudly (no judge to fall back to) ---
check('403 bare -> throws (unmapped)', threw(() => adapt({}, 'Forbidden', ctx(403))));
check('451 bare -> throws (unmapped)', threw(() => adapt({}, '', ctx(451))));

// --- configurable: map an unmapped status to block ---
process.env.GUARDRAIL_BLOCK_STATUSES = '400,446';
check('446 block when configured', adapt({}, '', ctx(446)).guardrails.flagged === true);
delete process.env.GUARDRAIL_BLOCK_STATUSES;

// --- explicit field override ---
process.env.GUARDRAIL_BLOCK_FIELD = 'result.verdict';
process.env.GUARDRAIL_BLOCK_VALUE = 'unsafe';
check('override match -> flagged', adapt({ result: { verdict: 'unsafe' } }, '', ctx(200)).guardrails.flagged === true);
check('override no-match -> allowed', adapt({ result: { verdict: 'safe' } }, '', ctx(200)).guardrails.flagged === false);
delete process.env.GUARDRAIL_BLOCK_FIELD;
delete process.env.GUARDRAIL_BLOCK_VALUE;

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
