import { evaluateViaGraphql } from '../api/graphql.js';
import { assertHistoryBeforeCandidate, buildScenario } from './scenarios.js';

export async function runLabScenario(id, opts = {}) {
  const scenario = buildScenario(id, opts);
  if (!scenario) throw new Error(`unknown lab scenario: ${id}`);
  assertHistoryBeforeCandidate(scenario);
  const submit = opts.submit || evaluateViaGraphql;
  const headers = opts.headers || {};
  const seeded = [];
  for (const row of scenario.history) {
    seeded.push(await submit(row, headers));
  }
  const candidate = await submit(scenario.candidate, headers);
  let replay = null;
  if (scenario.replay) {
    replay = await submit(scenario.candidate, headers);
  }
  return { scenario, seeded, candidate, replay };
}
