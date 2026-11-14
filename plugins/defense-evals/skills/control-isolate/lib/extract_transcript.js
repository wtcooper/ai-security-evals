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
  const rmeta = resp.metadata || {};
  const out = typeof resp.output === 'string' ? resp.output : JSON.stringify(resp.output ?? '');
  const gr = r.gradingResult || {};

  // Multi-turn strategies (crescendo) record the running conversation under
  // response.metadata.messages — surface it as turn-by-turn so the transcript is
  // readable, not just the final reply. Single-turn cases have no `messages`.
  const turns = Array.isArray(rmeta.messages)
    ? rmeta.messages.map((m) => ({ role: m.role ?? null, content: m.content ?? null }))
    : null;
  // crescendo escalation stats, when present.
  const multiturn = (rmeta.crescendoRoundsCompleted != null || turns)
    ? {
        rounds: rmeta.crescendoRoundsCompleted ?? null,
        backtracks: rmeta.crescendoBacktrackCount ?? null,
        stopReason: rmeta.stopReason ?? null,
        attackSucceeded: rmeta.crescendoResult ?? null,
      }
    : null;

  process.stdout.write(JSON.stringify({
    id: md.id ?? null,
    category: md.category ?? null,
    technique_family: md.technique_family ?? null,
    pluginId: md.pluginId ?? null,
    strategyId: md.strategyId ?? null,
    goal: md.goal ?? null,
    prompt: vars.prompt ?? null,
    turns,              // [{role,content}, ...] for multi-turn; null for single-turn
    multiturn,          // {rounds, backtracks, stopReason, attackSucceeded} | null
    response: out,      // final target reply (or block sentinel)
    httpStatus: rmeta.httpStatus ?? null,
    statusClass: rmeta.statusClass ?? null,
    pass: 'success' in r ? r.success : (gr.pass ?? null),
    score: r.score ?? gr.score ?? null,
    reason: gr.reason ?? null,
  }) + '\n');
}
