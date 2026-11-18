importScripts("preflop-participation.js","poker-core.js");

self.onmessage = event => {
  if (event.data?.warmup) {
    self.PokerCore.analyzePreflopEquity(["As", "Kd"], ["tight", "medium", "loose", "medium", "tight", "loose"], 80);
    self.PokerCore.comparePreflopScenarioActions({
      hero: ["As", "Kd"], pot: .15, call: .1, effective: 10, trials: 80,
      candidates: [{kind:"fold",amount:0},{kind:"call",amount:.1},{kind:"minimum_raise",amount:.3}],
      scenarioContext: {scenario:"facing_open",position:"dealer",players:3,live:.1,posted:0,currentPrice:.1,
        participants:{committed:[{seat:1,position:"middle",role:"raiser",invested:.1,rangeType:"medium"}],
          unacted:[{seat:2,position:"big_blind",role:"unacted",invested:.05,rangeType:"medium"}]}},
    });
    return;
  }
  const { generation, key, hero, board, rangeTypes, players, trials, calculationStartedAt, chunkIndex, chunkCount, preflop, conditionalRequests = [], baseSimulation = null, preflopScenarioRequest = null, decisionEconomicsRequest = null } = event.data;
  try {
    const simulation = baseSimulation ? { ...baseSimulation, baseSimulationReused: true } : preflop && preflopScenarioRequest
      ? { equity: null, win: null, tie: null, samples: 0, threats: [] }
      : preflop
      ? self.PokerCore.analyzePreflopEquity(hero, rangeTypes, trials)
      : players > 1
        ? self.PokerCore.analyzeMultiway(hero, board, rangeTypes, trials)
        : self.PokerCore.analyzeEquity(hero, board, rangeTypes[0] || "medium", trials);
    if (chunkIndex === 0 && conditionalRequests.length) {
      simulation.conditionalEquityByCandidate = {};
      const byFraction = new Map();
      for (const request of conditionalRequests) {
        const fraction = Number(request.continueFraction);
        if (!byFraction.has(fraction)) {
          byFraction.set(fraction, self.PokerCore.analyzeConditionalEquityByCallerCount(
            hero, board, rangeTypes, fraction, Math.max(600, trials)
          ));
        }
        simulation.conditionalEquityByCandidate[request.key] = byFraction.get(fraction);
      }
    }
    if (chunkIndex === 0 && preflopScenarioRequest) {
      simulation.preflopScenarioComparison = self.PokerCore.comparePreflopScenarioActions(
        preflopScenarioRequest
      );
      simulation.equity = simulation.preflopScenarioComparison.equity;
      simulation.samples = simulation.preflopScenarioComparison.samples;
    }
    if (chunkIndex === 0 && decisionEconomicsRequest) {
      simulation.decisionEconomics = self.PokerCore.buildDecisionEconomics(decisionEconomicsRequest);
    }
    if (!baseSimulation && !preflop && chunkIndex === Math.min(1, chunkCount - 1) &&
        (board.length === 3 || board.length === 4)) {
      simulation.boardPotential = self.PokerCore.analyzeBoardPotential(hero, board);
    }
    if (!baseSimulation && chunkIndex === 0) {
      const robustTrials = Math.max(80, Math.min(200, Math.floor(trials / 4)));
      simulation.rangeHypotheses = Object.fromEntries(
        [["悲观", "tight"], ["中性", "medium"], ["乐观", "loose"]].map(([label, range]) => {
          const ranges = Array.from({length: Math.max(1, players)}, () => range);
          const result = preflop
            ? self.PokerCore.analyzePreflopEquity(hero, ranges, robustTrials)
            : players > 1
              ? self.PokerCore.analyzeMultiway(hero, board, ranges, robustTrials)
              : self.PokerCore.analyzeEquity(hero, board, range, robustTrials);
          return [label, {equity: result.equity, samples: result.samples}];
        })
      );
    }
    self.postMessage({ generation, key, simulation, calculationStartedAt, chunkIndex, chunkCount });
  } catch (error) {
    self.postMessage({ generation, key, error: String(error?.message || error), calculationStartedAt, chunkIndex, chunkCount });
  }
};
