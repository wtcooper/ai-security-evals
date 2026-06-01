/** Tests for the shared status classifier. Run: node status_policy.test.cjs */
const path = require('path');
const sp = require(path.join(__dirname, '..', 'lib', 'status_policy.js'));
const { classify } = sp;

let pass = 0, fail = 0;
const check = (n, c) => { c ? pass++ : (fail++, console.error('FAIL:', n)); };
const k = (status, json, text) => classify(status, json, text).kind;

// --- answers (2xx / no status) ---
check('200 text -> answer', k(200, { choices: [{ message: { content: 'hi' } }] }, '') === 'answer');
check('no status -> answer', k(null, { output: 'x' }, '') === 'answer');
check('201 -> answer', k(201, { output: 'ok' }, '') === 'answer');

// --- blocks via BODY signal (status-agnostic) ---
check('200 + action:block -> block', k(200, { action: 'block' }, '') === 'block');
check('403 + guardrail_name (litellm) -> block',
  k(403, { error: { message: 'Content blocked', provider_specific_fields: { guardrail_name: 'content-filter' } } }, '') === 'block');
check('403 + "content blocked" msg -> block', k(403, { error: { message: 'Content blocked: keyword' } }, '') === 'block');
check('200 + flagged:true -> block', k(200, { flagged: true }, '') === 'block');
check('422 + blocked:true -> block', k(422, { blocked: true }, '') === 'block');
check('200 + nested guardrails.flagged -> block', k(200, { guardrails: { flagged: true } }, '') === 'block');
check('200 + policy violation msg -> block', k(200, { message: 'request denied: policy violation' }, '') === 'block');

// --- blocks via STATUS hint (default 400) ---
check('400 bare -> block (default hint)', k(400, {}, 'nope') === 'block');

// --- operational errors (excluded) ---
for (const s of [500, 502, 503, 504, 429, 408, 401, 407]) check(`${s} -> error`, k(s, {}, '') === 'error');
check('403 + auth msg -> error', k(403, { error: { message: 'Authentication Error: invalid api key' } }, '') === 'error');
check('400 + rate limit msg -> block-not-error (400 is a block hint)', k(400, { error: 'rate limit' }, '') === 'block'); // hint wins for 400
check('200 + quota msg -> answer (2xx, no block signal, error-msg ignored on 2xx)', k(200, { message: 'quota' }, '') === 'answer');

// --- ambiguous (non-2xx, no signal) ---
check('403 bare -> ambiguous', k(403, {}, 'Forbidden') === 'ambiguous');
check('451 bare -> ambiguous', k(451, {}, '') === 'ambiguous');
check('406 bare -> ambiguous', k(406, {}, '') === 'ambiguous');

// --- configurable block-status hint ---
process.env.GUARDRAIL_BLOCK_STATUSES = '400,451';
check('451 -> block when configured', k(451, {}, '') === 'block');
check('403 still ambiguous', k(403, {}, '') === 'ambiguous');
delete process.env.GUARDRAIL_BLOCK_STATUSES;

// --- explicit body field override ---
process.env.GUARDRAIL_BLOCK_FIELD = 'result.verdict';
process.env.GUARDRAIL_BLOCK_VALUE = 'unsafe';
check('override path match -> block', k(200, { result: { verdict: 'unsafe' } }, '') === 'block');
check('override path no-match -> answer', k(200, { result: { verdict: 'safe' } }, '') === 'answer');
delete process.env.GUARDRAIL_BLOCK_FIELD;
delete process.env.GUARDRAIL_BLOCK_VALUE;

// --- reason + httpStatus carried ---
const c = classify(403, { error: { message: 'Content blocked: bomb' } }, '');
check('reason extracted', c.reason.includes('Content blocked'));
check('httpStatus carried', c.httpStatus === 403);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
