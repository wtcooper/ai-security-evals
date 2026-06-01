/**
 * Tests for the app-skill transformResponse (classify-driven). Run:
 *   node tools/tests/transform_response.test.cjs
 */
const path = require('path');
const transform = require(path.join(__dirname, '..', 'lib', 'transform_response.js'));

let pass = 0, fail = 0;
function check(name, cond) { cond ? pass++ : (fail++, console.error('FAIL:', name)); }
const ctx = (status) => ({ response: { status } });
const threw = (fn) => { try { fn(); return false; } catch (e) { return true; } };

// --- answers: text extraction + metadata ---
check('openai chat', transform({ choices: [{ message: { content: 'hi' } }] }, '', ctx(200)).output === 'hi');
check('anthropic', transform({ content: [{ text: 'an' }] }, '', ctx(200)).output === 'an');
check('messages last turn', transform({ messages: [{ content: 'a' }, { content: 'b' }] }, '', ctx(200)).output === 'b');
check('raw text', transform(null, 'plain', ctx(200)).output === 'plain');
check('no status -> answer', transform({ output: 'x' }, '', {}).output === 'x');
check('answer metadata', transform({ output: 'x' }, '', ctx(200)).metadata.statusClass === 'answer');
check('answer httpStatus', transform({ output: 'x' }, '', ctx(201)).metadata.httpStatus === 201);

// --- block via status hint (400) ---
const b = transform({ error: { message: 'policy violation' } }, '', ctx(400));
check('400 sentinel', b.output.includes('[GUARDRAIL_BLOCK]') && b.output.includes('400'));
check('400 guardrails.flagged', b.guardrails.flagged === true);
check('400 metadata block', b.metadata.statusClass === 'block');

// --- block via BODY signal at a non-hint status (no env needed) ---
const litellm = transform({ error: { message: 'Content blocked: keyword', provider_specific_fields: { guardrail_name: 'content-filter' } } }, '', ctx(403));
check('403 litellm content-filter -> block', litellm.guardrails && litellm.guardrails.flagged === true);
check('403 block sentinel', litellm.output.includes('[GUARDRAIL_BLOCK]'));
check('200 + action:block -> block', transform({ action: 'block' }, '', ctx(200)).guardrails.flagged === true);

// --- operational errors throw (excluded) ---
for (const code of [500, 502, 503, 504, 429, 408, 401, 407]) {
  check(`HTTP ${code} throws`, threw(() => transform({}, 'body', ctx(code))));
}
check('403 + auth msg throws', threw(() => transform({ error: { message: 'invalid api key' } }, '', ctx(403))));

// --- ambiguous: default judge path (not thrown) ---
const amb = transform({}, 'Forbidden', ctx(403));
check('403 bare -> ambiguous output', amb.output.startsWith('[AMBIGUOUS HTTP 403]'));
check('ambiguous keeps body', amb.output.includes('Forbidden'));
check('ambiguous metadata', amb.metadata.statusClass === 'ambiguous');
check('451 bare -> ambiguous', transform({}, '', ctx(451)).metadata.statusClass === 'ambiguous');

// --- ambiguous: exclude policy -> throws ---
process.env.GUARDRAIL_AMBIGUOUS_POLICY = 'exclude';
check('ambiguous excludes when configured', threw(() => transform({}, '', ctx(451))));
delete process.env.GUARDRAIL_AMBIGUOUS_POLICY;

// --- configurable block-status hint ---
process.env.GUARDRAIL_BLOCK_STATUSES = '400,446';
check('446 block when configured', transform({ message: 'blocked' }, '', ctx(446)).guardrails.flagged === true);
delete process.env.GUARDRAIL_BLOCK_STATUSES;

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
