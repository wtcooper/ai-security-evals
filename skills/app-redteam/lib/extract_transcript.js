#!/usr/bin/env node
/**
 * Slim, legible transcript from a promptfoo results.json -> JSONL (one row per case:
 * the prompt, the target's response, and the verdict). The full per-case detail is
 * already in results.json; this is the readable view for eyeballing a conversation.
 *
 *   node extract_transcript.js <results.json> > transcript.jsonl
 */
const fs = require('fs');

const inPath = process.argv[2];
if (!inPath) {
  console.error('usage: node extract_transcript.js <promptfoo-results.json>');
  process.exit(2);
}

const doc = JSON.parse(fs.readFileSync(inPath, 'utf8'));
// promptfoo schema variants: {results:{results:[...]}} | {results:[...]} | [...]
let rows = doc && doc.results ? (doc.results.results || doc.results) : doc;
if (!Array.isArray(rows)) rows = [];

for (const r of rows) {
  const md = (r.testCase && r.testCase.metadata) || r.metadata || {};
  const vars = r.vars || (r.testCase && r.testCase.vars) || {};
  const resp = r.response || {};
  const out = typeof resp.output === 'string' ? resp.output : JSON.stringify(resp.output ?? '');
  const gr = r.gradingResult || {};
  process.stdout.write(JSON.stringify({
    id: md.id ?? null,
    category: md.category ?? null,
    technique_family: md.technique_family ?? null,
    prompt: vars.prompt ?? null,
    response: out,
    pass: 'success' in r ? r.success : (gr.pass ?? null),
    score: r.score ?? gr.score ?? null,
    reason: gr.reason ?? null,
  }) + '\n');
}
