/**
 * Zero-dependency tests for the shared transformResponse block policy.
 * Run: node skills/_shared/tests/transform_response.test.cjs
 */
const path = require('path');
const transform = require(path.join(__dirname, '..', 'transform_response.js'));

let pass = 0,
  fail = 0;
function check(name, cond) {
  if (cond) {
    pass++;
  } else {
    fail++;
    console.error('FAIL:', name);
  }
}
const ctx = (status) => ({ response: { status } });

// --- 2xx text extraction across body shapes ---
check('openai chat', transform({ choices: [{ message: { content: 'hi' } }] }, '', ctx(200)) === 'hi');
check('openai completion', transform({ choices: [{ text: 'ct' }] }, '', ctx(200)) === 'ct');
check('anthropic', transform({ content: [{ text: 'an' }] }, '', ctx(200)) === 'an');
check('custom .response', transform({ response: 'r' }, '', ctx(200)) === 'r');
check('custom .output', transform({ output: 'o' }, '', ctx(201)) === 'o');
check('messages last turn', transform({ messages: [{ content: 'a' }, { content: 'b' }] }, '', ctx(200)) === 'b');
check('raw text fallback', transform(null, 'plain', ctx(200)) === 'plain');
check('no status -> answer', transform({ output: 'x' }, '', {}) === 'x');
check('no status null ctx', transform(null, 'y', ctx(null)) === 'y');

// --- block status (default 400) -> guardrails object + sentinel ---
const b = transform({ error: { message: 'policy violation' } }, '', ctx(400));
check('400 returns object', typeof b === 'object' && b !== null);
check('400 sentinel in output', b.output.includes('[GUARDRAIL_BLOCK]') && b.output.includes('400'));
check('400 reason captured', b.output.includes('policy violation'));
check('400 guardrails.flagged', b.guardrails && b.guardrails.flagged === true);
check('400 flaggedInput true', b.guardrails.flaggedInput === true);
check('400 reason field', b.guardrails.reason === 'policy violation');

// block detail across shapes
check('400 detail .detail', transform({ detail: 'd' }, '', ctx(400)).guardrails.reason === 'd');
check('400 detail raw text', transform(null, 'rawerr', ctx(400)).guardrails.reason === 'rawerr');
check('400 empty reason -> http label', transform({}, '', ctx(400)).guardrails.reason === 'HTTP 400');

// --- operational errors throw (excluded from metrics) ---
for (const code of [301, 302, 307, 401, 403, 404, 405, 408, 409, 422, 429, 500, 502, 503]) {
  let threw = false;
  try {
    transform({ error: 'x' }, 'body', ctx(code));
  } catch (e) {
    threw = true;
  }
  check(`HTTP ${code} throws`, threw);
}

// --- configurable block statuses (vendor-agnostic, env-driven) ---
process.env.GUARDRAIL_BLOCK_STATUSES = '400,446';
const prisma = transform({ message: 'blocked by airs' }, '', ctx(446));
check('446 block when configured', typeof prisma === 'object' && prisma.guardrails.flagged === true);
check('446 sentinel mentions 446', prisma.output.includes('446'));
let stillThrows = false;
try {
  transform({}, '', ctx(403));
} catch (e) {
  stillThrows = true;
}
check('403 still throws (not in set)', stillThrows);
delete process.env.GUARDRAIL_BLOCK_STATUSES;

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
