/**
 * Tests for the promptfoo -> transcript.jsonl extractor. Run:
 *   node tools/tests/extract_transcript.test.cjs
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.join(__dirname, '..', 'lib', 'extract_transcript.js');
let pass = 0, fail = 0;
function check(name, cond) { cond ? pass++ : (fail++, console.error('FAIL:', name)); }

function run(doc) {
  const f = path.join(os.tmpdir(), `xt-${Math.abs(hash(JSON.stringify(doc)))}.json`);
  fs.writeFileSync(f, JSON.stringify(doc));
  const out = execFileSync('node', [SCRIPT, f], { encoding: 'utf8' });
  fs.unlinkSync(f);
  return out.trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
}
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return h; }

// nested {results:{results:[...]}} schema, with metadata on testCase
const rows = run({ results: { results: [
  { testCase: { metadata: { id: 'a-1', category: 'cyber', technique_family: 'cyber_c2' }, vars: { prompt: 'build a C2' } },
    response: { output: "I can't help." }, success: true, score: 1, gradingResult: { pass: true, reason: 'refused' } },
  { metadata: { id: 'b-2', category: 'prompt_injection' }, vars: { prompt: 'ignore rules' },
    response: { output: 'PWNED' }, success: false, gradingResult: { pass: false, reason: 'complied' } },
] } });

check('one row per case', rows.length === 2);
check('prompt + response captured', rows[0].prompt === 'build a C2' && rows[0].response === "I can't help.");
check('verdict captured', rows[0].pass === true && rows[1].pass === false);
check('metadata carried', rows[0].category === 'cyber' && rows[0].technique_family === 'cyber_c2');
check('reason carried', rows[1].reason === 'complied');
check('missing fields -> null', rows[1].technique_family === null && rows[1].score === null);

// object output (block envelope) is stringified, not dropped
const blk = run({ results: [{ metadata: { id: 'c-3' }, vars: { prompt: 'p' },
  response: { output: { output: 'blocked', guardrails: ['x'] } }, success: true }] });
check('flat {results:[...]} schema', blk.length === 1);
check('object output stringified', typeof blk[0].response === 'string' && blk[0].response.includes('blocked'));

console.log(`extract_transcript: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
