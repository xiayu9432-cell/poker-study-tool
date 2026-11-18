const assert = require("node:assert/strict");
const core = require("./poker-core.js");
const v2 = require("./v2-model.js");
const deep = require("./v2-deep-model.js");

const contract = core.buildSidePotContract({
  heroSeat: 3,
  contributions: { 1: 100, 2: 100, 3: 40, 4: 20 },
  foldedSeats: [4], reportedPot: 260, hasAllIn: true,
  legalActions: ["fold", "call"], rakeRate: 0.05, rakeCap: 10,
  rakeAllocation: "main_pot_first",
});
assert.equal(contract.contractVersion, 1);
assert.equal(contract.exact, true);
assert.equal(contract.requiresLayering, true);
assert.equal(contract.complexMultiway, true);
assert.equal(contract.mainPot.grossAmount, 80);
assert.deepEqual(contract.mainPot.participants, [1, 2, 3]);
assert.deepEqual(contract.sidePots.map(layer => [layer.grossAmount, layer.participants]), [
  [60, [1, 2, 3]],
  [120, [1, 2]],
]);
assert.equal(contract.heroWinnableGross, 140);
assert.equal(contract.heroWinnableNet, 133);
assert.equal(contract.rake.estimatedTotal, 10);
assert.deepEqual(contract.legalActions, ["fold", "call"]);
assert.equal(contract.evPolicy.v2T2T3Supported, false);
assert.equal(contract.evPolicy.t2T3Supported, false);

const state = {
  layout: "8max", handId: 9, street: "river", pot: 240, rakeRate: 0.05, rakeCap: 10,
  activePlayerCount: 3, actionButtonSequence: 1, expectedActionSeat: 5, reliable: true,
  heroCards: ["As", "Ah"], boardCards: ["2c", "7d", "9s", "Jc", "3h"],
  tablePlay: { type: "德州扑克", decisionRules: { rakeAllocation: "main_pot_first" } },
  visualButtons: [{ kind: "fold" }, { kind: "call" }],
  actionLog: [
    { handId: 9, street: "river", seat: 1, action: "allin", amount: 100 },
    { handId: 9, street: "river", seat: 2, action: "call", amount: 100 },
    { handId: 9, street: "river", seat: 5, action: "allin", amount: 40 },
  ],
  seats: Array.from({ length: 8 }, (_, index) => ({
    index, streetBet: [100, 100, 0, 0, 40][index] || 0,
    chips: [0, 0, 0, 0, 0][index] || 0,
    empty: ![0, 1, 4].includes(index),
  })),
};
const stateContract = core.buildSidePotContractFromState(state, 5);
assert.equal(stateContract.heroWinnableGross, 120);
assert.equal(stateContract.sidePots[0].heroEligible, false);

const anteState = {
  layout: "8max", handId: 19, street: "preflop", pot: 2.41,
  blindAnte: 0.05, rakeRate: 0.04, rakeCap: 0.6,
  handParticipants: [1, 2, 3, 4, 5, 6, 7, 8],
  visualButtons: [{ kind: "fold" }, { kind: "call" }],
  actionLog: [
    { handId: 19, street: "preflop", seat: 5, action: "blind", amount: 0.05 },
    { handId: 19, street: "preflop", seat: 6, action: "blind", amount: 0.10 },
    { handId: 19, street: "preflop", seat: 7, action: "straddle", amount: 0.20 },
    { handId: 19, street: "preflop", seat: 8, action: "fold", amount: 0 },
    { handId: 19, street: "preflop", seat: 1, action: "raise", amount: 0.83 },
    { handId: 19, street: "preflop", seat: 2, action: "call", amount: 0.83 },
    { handId: 19, street: "preflop", seat: 3, action: "fold", amount: 0 },
    { handId: 19, street: "preflop", seat: 4, action: "fold", amount: 0 },
  ],
  seats: Array.from({ length: 8 }, (_, index) => ({ index, streetBet: [0.83, 0.83, 0, 0, 0.05, 0.10, 0.20, 0][index], chips: 20, empty: false })),
};
const anteContract = core.buildSidePotContractFromState(anteState, 5);
assert.equal(anteContract.consistent, true);
assert.equal(anteContract.exact, true);
assert.equal(anteContract.accountedPot, 2.41);
assert.equal(anteContract.antePerPlayer, 0.05);
assert.deepEqual(anteContract.anteSeats, [1, 2, 3, 4, 5, 6, 7, 8]);

const configuredStraddleState = {
  layout: "8max", handId: 21, street: "preflop", pot: 0.75,
  blindAnte: 0.05, blindStraddle: 0.20,
  handParticipants: [1, 2, 3, 4, 5, 6, 7, 8],
  visualButtons: [{ kind: "fold" }, { kind: "call" }],
  actionLog: [
    { handId: 21, street: "preflop", seat: 7, action: "blind", amount: 0.05 },
    { handId: 21, street: "preflop", seat: 8, action: "blind", amount: 0.10 },
    { handId: 21, street: "preflop", seat: 1, action: "straddle", amount: 0.20 },
  ],
  seats: Array.from({ length: 8 }, (_, index) => ({
    index, streetBet: [0.20, 0, 0, 0, 0, 0, 0.05, 0.10][index],
    chips: 20, empty: false,
  })),
};
const configuredStraddleContract = core.buildSidePotContractFromState(configuredStraddleState, 5);
assert.equal(configuredStraddleContract.consistent, true);
assert.equal(configuredStraddleContract.exact, true);
assert.equal(configuredStraddleContract.reportedPot, 0.75);
assert.ok(Math.abs(configuredStraddleContract.accountedPot - 0.65) < 1e-9);
assert.ok(Math.abs(configuredStraddleContract.returnedTotal - 0.10) < 1e-9);

const snapshot = v2.buildDecisionSnapshot(state);
assert.equal(snapshot.sidePotContract.heroWinnableGross, 120);
assert.deepEqual(snapshot.sidePotContract.legalActions, ["fold", "call"]);
for (const decision of [
  v2.shadowDecision({ snapshot, candidates: [{ kind: "call", amount: 0 }], solveTier: "T0" }),
  v2.t1Decision({ snapshot, candidates: [{ kind: "call", amount: 0 }] }),
  deep.deepDecision({ snapshot, candidates: [{ kind: "call", amount: 0 }], tier: "T2" }),
  deep.deepDecision({ snapshot, candidates: [{ kind: "call", amount: 0 }], tier: "T3" }),
]) {
  assert.equal(decision.unsupported, true);
  assert.equal(decision.best, null);
  assert.equal(decision.evaluated[0].eligible, false);
  assert.match(decision.reason, /V2\/T2\/T3未支持复杂多人边池逐层EV/);
}

console.log("unified side-pot contract and T2/T3 capability gate: OK");
