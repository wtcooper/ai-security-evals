const path = require('path');
const adapt = require(path.join(__dirname, '..', 'adapters', 'generic_guardrail.js'));
let pass = 0, fail = 0;
const check = (n, c) => { c ? pass++ : (fail++, console.error('FAIL:', n)); };
const ctx = (status) => ({ response: { status } });

// generic body recognizers (200 + verdict)
check('action block', adapt({ action: 'block' }, '', ctx(200)).guardrails.flagged === true);
check('action allow', adapt({ action: 'allow' }, '', ctx(200)).guardrails.flagged === false);
check('blocked bool', adapt({ blocked: true }, '', ctx(200)).guardrails.flagged === true);
check('flagged bool', adapt({ flagged: true }, '', ctx(200)).guardrails.flagged === true);
check('is_malicious', adapt({ is_malicious: true }, '', ctx(200)).guardrails.flagged === true);
check('outcome deny', adapt({ outcome: 'deny' }, '', ctx(200)).guardrails.flagged === true);
check('nested guardrails', adapt({ guardrails: { flagged: true } }, '', ctx(200)).guardrails.flagged === true);
check('benign passes', adapt({ action: 'allow', category: 'benign' }, '', ctx(200)).guardrails.flagged === false);

// status-code blockers
check('400 blocks', adapt({}, 'nope', ctx(400)).guardrails.flagged === true);
process.env.GUARDRAIL_BLOCK_STATUSES = '400,446';
check('446 blocks when configured', adapt({}, '', ctx(446)).guardrails.flagged === true);
delete process.env.GUARDRAIL_BLOCK_STATUSES;

// reason extraction
check('reason from category', adapt({ action: 'block', category: 'malicious' }, '', ctx(200)).guardrails.reason === 'malicious');
check('output sentinel on block', adapt({ action: 'block' }, '', ctx(200)).output.startsWith('[BLOCKED]'));

// explicit field override (odd vendor)
process.env.GUARDRAIL_BLOCK_FIELD = 'result.verdict';
process.env.GUARDRAIL_BLOCK_VALUE = 'unsafe';
check('override path match', adapt({ result: { verdict: 'unsafe' } }, '', ctx(200)).guardrails.flagged === true);
check('override path no-match', adapt({ result: { verdict: 'safe' } }, '', ctx(200)).guardrails.flagged === false);
delete process.env.GUARDRAIL_BLOCK_FIELD;
delete process.env.GUARDRAIL_BLOCK_VALUE;

// operational errors throw — incl. 3xx and 4xx-below-401 (regression: these used
// to slip through as "allow" instead of being excluded)
for (const code of [301, 302, 307, 404, 408, 401, 429, 500, 503]) {
  let threw = false;
  try { adapt({}, 'x', ctx(code)); } catch (e) { threw = true; }
  check(`HTTP ${code} throws (operational)`, threw);
}

// when the block set is overridden away from 400, a 400 is operational -> throws
process.env.GUARDRAIL_BLOCK_STATUSES = '446';
let threw400 = false;
try { adapt({}, 'x', ctx(400)); } catch (e) { threw400 = true; }
check('400 throws when not in block set', threw400);
check('446 blocks when set is overridden', adapt({}, '', ctx(446)).guardrails.flagged === true);
delete process.env.GUARDRAIL_BLOCK_STATUSES;

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
