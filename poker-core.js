(function (root) {
  const ranks = "23456789TJQKA";
  const suits = "shdc";
  const PREFLOP = root.PreflopParticipation || (typeof require === "function" ? require("./preflop-participation.js") : null);

  function truncateName(name) {
    let width = 0, output = "";
    const text = String(name || "未知").trim();
    for (const char of text) {
      const size = /[\u3400-\u9fff]/.test(char) ? 2 : 1;
      if (width + size > 6) return `${output}···`;
      output += char;
      width += size;
    }
    return output;
  }

  function hudMetrics(stats) {
    const observedOpportunities = stats.preflopOpportunities || 0;
    const observedVpip = observedOpportunities ? (stats.vpipHands || 0) / observedOpportunities : null;
    const observedPfr = observedOpportunities ? (stats.pfrHands || 0) / observedOpportunities : null;
    const platform = stats.platformStatistics || {}, platformHands = Number(platform.levelHands);
    const platformWeight = Number.isFinite(platformHands) ? platformHands < 5 ? 0 : platformHands < 15 ? .15 : platformHands < 30 ? .35 : platformHands < 60 ? .60 : .80 : 0;
    const observedWeight = observedOpportunities < 5 ? 0 : observedOpportunities < 15 ? .15 : observedOpportunities < 30 ? .35 : observedOpportunities < 60 ? .60 : .80;
    const weightTotal = platformWeight + observedWeight;
    const vpip = weightTotal ? ((Number(platform.vpipRate) || 0) * platformWeight + (observedVpip || 0) * observedWeight) / weightTotal : null;
    const pfr = weightTotal ? ((Number(platform.pfrRate) || 0) * platformWeight + (observedPfr || 0) * observedWeight) / weightTotal : null;
    const opportunities = Math.max(observedOpportunities, Number.isFinite(platformHands) ? platformHands : 0);
    const aggression = (stats.postflopCalls || 0) ? ((stats.postflopBets || 0) + (stats.postflopRaises || 0)) / stats.postflopCalls : null;
    const fold = (stats.facingBetOpportunities || 0) ? (stats.foldsFacingBet || 0) / stats.facingBetOpportunities : null;
    let style = "观察中", reliability = opportunities < 20 ? "watching" : opportunities < 50 ? "early" : "stable";
    if (opportunities >= 20 && vpip !== null) {
      const ratio = vpip > 0 ? pfr / vpip : 0;
      style = vpip < .25 ? (ratio >= .65 ? "紧凶" : "紧弱") : (ratio >= .65 ? "松凶" : "松弱");
      if (fold !== null && fold >= .60) style += "·易弃";
      else if (fold !== null && fold < .35) style += "·黏";
      else if (aggression !== null && aggression >= 3) style += "·激进";
      else if (aggression !== null && aggression < 1.5) style += "·被动";
    }
    return { opportunities, vpip, pfr, aggression, fold, style, reliability,
      observedOpportunities, platformHands: Number.isFinite(platformHands) ? platformHands : 0,
      platformWeight, observedWeight };
  }

  function parseCards(value, min, max) {
    const cards = String(value || "").trim() ? String(value).trim().split(/[\s,，]+/).map(card => card[0]?.toUpperCase() + card[1]?.toLowerCase()) : [];
    if (cards.length < min || cards.length > max) throw new Error(`牌张数量必须为 ${min === max ? min : `${min} 至 ${max}`} 张`);
    if (cards.some(card => card.length !== 2 || !ranks.includes(card[0]) || !suits.includes(card[1]))) throw new Error("牌面格式错误");
    if (new Set(cards).size !== cards.length) throw new Error("发现重复牌");
    return cards;
  }

  function cardValue(card) { return ranks.indexOf(card[0]) + 2; }
  function fullDeck() { return [...ranks].flatMap(rank => [...suits].map(suit => rank + suit)); }
  function compareRanks(a, b) { for (let i = 0; i < Math.max(a.length, b.length); i++) if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) - (b[i] || 0); return 0; }
  function rankFive(cards) {
    const values = cards.map(cardValue).sort((a, b) => b - a);
    const counts = [...values.reduce((map, value) => map.set(value, (map.get(value) || 0) + 1), new Map()).entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0]);
    const flush = cards.every(card => card[1] === cards[0][1]);
    const unique = [...new Set(values)]; if (unique[0] === 14) unique.push(1);
    let straight = 0; for (let i = 0; i <= unique.length - 5; i++) if (unique[i] - unique[i + 4] === 4) { straight = unique[i]; break; }
    if (flush && straight) return [8, straight];
    if (counts[0][1] === 4) return [7, counts[0][0], counts[1][0]];
    if (counts[0][1] === 3 && counts[1][1] === 2) return [6, counts[0][0], counts[1][0]];
    if (flush) return [5, ...values];
    if (straight) return [4, straight];
    if (counts[0][1] === 3) return [3, counts[0][0], ...counts.slice(1).map(x => x[0]).sort((a, b) => b - a)];
    if (counts[0][1] === 2 && counts[1][1] === 2) return [2, Math.max(counts[0][0], counts[1][0]), Math.min(counts[0][0], counts[1][0]), counts[2][0]];
    if (counts[0][1] === 2) return [1, counts[0][0], ...counts.slice(1).map(x => x[0]).sort((a, b) => b - a)];
    return [0, ...values];
  }
  function straightHigh(values) {
    const unique = [...new Set(values)].sort((a, b) => b - a);
    if (unique[0] === 14) unique.push(1);
    for (let index = 0; index <= unique.length - 5; index++) if (unique[index] - unique[index + 4] === 4) return unique[index];
    return 0;
  }
  function rankBest(cards) {
    if (cards.length === 5) return rankFive(cards);
    const values = cards.map(cardValue).sort((a, b) => b - a);
    const counts = new Map(), bySuit = new Map();
    cards.forEach(card => { const value = cardValue(card); counts.set(value, (counts.get(value) || 0) + 1); const suited = bySuit.get(card[1]) || []; suited.push(value); bySuit.set(card[1], suited); });
    for (const suited of bySuit.values()) { const high = suited.length >= 5 ? straightHigh(suited) : 0; if (high) return [8, high]; }
    const groups = [...counts].sort((left, right) => right[1] - left[1] || right[0] - left[0]);
    const quad = groups.find(group => group[1] === 4); if (quad) return [7, quad[0], values.find(value => value !== quad[0])];
    const trips = groups.filter(group => group[1] >= 3), pairs = groups.filter(group => group[1] >= 2);
    if (trips.length && pairs.some(group => group[0] !== trips[0][0])) return [6, trips[0][0], pairs.find(group => group[0] !== trips[0][0])[0]];
    const flush = [...bySuit.values()].filter(suited => suited.length >= 5).map(suited => suited.sort((a, b) => b - a).slice(0, 5)).sort(compareRanks).pop(); if (flush) return [5, ...flush];
    const straight = straightHigh(values); if (straight) return [4, straight];
    if (trips.length) return [3, trips[0][0], ...values.filter(value => value !== trips[0][0]).slice(0, 2)];
    if (pairs.length >= 2) { const pairValues = pairs.map(group => group[0]).sort((a, b) => b - a); return [2, pairValues[0], pairValues[1], values.find(value => value !== pairValues[0] && value !== pairValues[1])]; }
    if (pairs.length) return [1, pairs[0][0], ...values.filter(value => value !== pairs[0][0]).slice(0, 3)];
    return [0, ...values.slice(0, 5)];
  }
  function evaluateBrute(cards) {
    let best = null;
    for (let a = 0; a < cards.length - 4; a++) for (let b = a + 1; b < cards.length - 3; b++) for (let c = b + 1; c < cards.length - 2; c++) for (let d = c + 1; d < cards.length - 1; d++) for (let e = d + 1; e < cards.length; e++) {
      const rank = rankFive([cards[a], cards[b], cards[c], cards[d], cards[e]]); if (!best || compareRanks(rank, best) > 0) best = rank;
    }
    return best;
  }
  function evaluate(cards) { return cards.length >= 5 && cards.length <= 7 ? rankBest(cards) : evaluateBrute(cards); }
  function comboKey(cards) { const sorted = [...cards].sort((a, b) => cardValue(b) - cardValue(a)); return `${sorted[0][0]}${sorted[1][0]}${sorted[0][0] === sorted[1][0] ? "" : sorted[0][1] === sorted[1][1] ? "s" : "o"}`; }
  function exactComboKey(cards) { return [...cards].sort().join(""); }
  function inRange(cards, type) {
    if (type && typeof type === "object" && type.allowed instanceof Set) {
      return type.allowed.has(exactComboKey(cards));
    }
    if (type === "random") return true;
    const values = cards.map(cardValue).sort((a, b) => b - a), pair = values[0] === values[1], suited = cards[0][1] === cards[1][1], gap = values[0] - values[1];
    const strength = pair ? 40 + values[0] * 3 : values[0] * 2 + values[1] + (suited ? 4 : 0) - gap;
    const threshold = type && typeof type === "object" && Number.isFinite(type.strengthThreshold)
      ? type.strengthThreshold : ({ tight: 55, medium: 43, loose: 34 }[type] || 0);
    return strength >= threshold;
  }
  function weightedRange(defaultRange, profileRange, weight) {
    const thresholds = { tight: 55, medium: 43, loose: 34 }, bounded = Math.max(0, Math.min(1, Number(weight) || 0));
    const base = thresholds[defaultRange], profile = thresholds[profileRange];
    if (!Number.isFinite(base) || !Number.isFinite(profile) || bounded <= 0 || defaultRange === profileRange) return defaultRange;
    if (bounded >= 1) return profileRange;
    return { strengthThreshold: base + (profile - base) * bounded,
      source: "weighted_profile_range", defaultRange, profileRange, weight: bounded };
  }
  function defaultOpponentRange({ actions = [], currentAction = "", bet = 0, pot = 0, position = "middle" } = {}) {
    const aggressive = actions.some(item => ["raise", "reraise", "allin"].includes(item.action)) ||
      ["raise", "reraise", "allin"].includes(currentAction);
    const passiveEntry = actions.some(item => item.action === "call") || currentAction === "call";
    const largeBet = pot > 0 && bet / pot >= .75;
    if (aggressive || largeBet) return "tight";
    return passiveEntry && ["dealer", "cutoff", "late", "blind", "small_blind", "big_blind", "straddle"].includes(position) ? "loose" : "medium";
  }
  function profileSampleTier(opportunities) {
    if (opportunities < 20) return "watching";
    if (opportunities < 50) return "early";
    if (opportunities < 100) return "usable";
    if (opportunities < 200) return "actionable";
    return "stable";
  }
  function sceneSampleTier(samples) {
    if (samples < 5) return "S0";
    if (samples < 15) return "S1";
    if (samples < 30) return "S2";
    if (samples < 60) return "S3";
    return "S4";
  }
  function nextTierProgress(count, thresholds) {
    const value = Math.max(0, Number(count) || 0);
    const target = thresholds.find(item => value < item) || null;
    return { count: value, nextTarget: target, remaining: target === null ? 0 : target - value };
  }
  function normalizedSceneAction(value) {
    const action = String(value || "").toLowerCase();
    return action === "all-in" || action === "all_in" ? "allin" : action;
  }
  function sceneValue(value) {
    return value === undefined || value === null || value === "unknown" || Number.isNaN(value) ? null : value;
  }
  function matchingSceneEvidence(profile, event = {}) {
    const buckets = profile?.modelEvidence?.buckets || [], street = event.street || "preflop", action = normalizedSceneAction(event.action);
    const expected = {
      facingAction: sceneValue(event.facingAction), position: sceneValue(event.position),
      boardClass: sceneValue(event.boardClass || (street === "preflop" ? "preflop" : null)),
      ratioBucket: Number.isFinite(Number(event.betPotRatio)) ? Math.round(Number(event.betPotRatio) / .25) * .25 : null,
      stackBucketBb: Number.isFinite(Number(event.effectiveStackBb)) ? Math.min(200, Math.round(Number(event.effectiveStackBb) / 50) * 50) : null,
      playerCountBucket: Number.isFinite(Number(event.playerCount)) ? Math.min(5, Math.max(2, Math.round(Number(event.playerCount)))) : null,
    };
    const weights = { facingAction: 8, position: 5, boardClass: 4, ratioBucket: 3, stackBucketBb: 2, playerCountBucket: 2 };
    const candidates = buckets.filter(bucket => bucket.street === street).map(bucket => {
      let score = 0, compared = 0, matched = 0;
      for (const [field, weight] of Object.entries(weights)) {
        const actual = sceneValue(bucket[field]), wanted = expected[field];
        if (actual === null || wanted === null) continue;
        compared++;
        if (actual === wanted) { score += weight; matched++; }
        else score -= weight;
      }
      return { bucket, score, compared, matched };
    }).sort((left, right) => right.score - left.score || right.matched - left.matched || Number(right.bucket.sampleCount) - Number(left.bucket.sampleCount));
    const selected = candidates[0], bucket = selected?.bucket || null, shown = bucket?.verifiedClasses?.[action] || {};
    const actionSampleCount = Math.max(0, Number(bucket?.sampleCount) || 0), showdownSampleCount = Object.values(shown).reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0);
    return { event: { ...event, street, action }, bucket, actionSampleCount, showdownSampleCount,
      matchTier: !selected ? "no_matching_street" : selected.compared > 0 && selected.matched === selected.compared ? "exact_scene" : "nearest_scene",
      matchedDimensions: selected?.matched || 0, comparedDimensions: selected?.compared || 0 };
  }
  function comboClassStrength(combo) {
    const ranks = "23456789TJQKA", text = String(combo || ""), first = ranks.indexOf(text[0]) + 2, second = ranks.indexOf(text[1]) + 2;
    if (first < 2 || second < 2) return null;
    const pair = text.length === 2, suited = text.endsWith("s"), high = Math.max(first, second), low = Math.min(first, second);
    return pair ? 40 + high * 3 : high * 2 + low + (suited ? 4 : 0) - (high - low);
  }
  function showdownTarget(sceneEvidence, overallRange, calibration) {
    const counts = sceneEvidence?.bucket?.verifiedClasses?.[sceneEvidence?.event?.action] || {};
    let samples = 0, totalStrength = 0;
    for (const [combo, countValue] of Object.entries(counts)) {
      const count = Math.max(0, Number(countValue) || 0), strength = comboClassStrength(combo);
      if (!count || !Number.isFinite(strength)) continue;
      samples += count; totalStrength += strength * count;
    }
    const eligible = calibration?.eligibleToAffectAdvice === true && calibration?.currentEvidence === true && Number(calibration?.heldOutHands) >= 30 && samples >= 5;
    if (!eligible) return { range: overallRange, samples, category: null, blendWeight: 0, eligible: false };
    const average = totalStrength / samples, category = average >= 55 ? "tight" : average >= 43 ? "medium" : "loose", blendWeight = samples < 15 ? .10 : samples < 30 ? .25 : samples < 60 ? .45 : .65;
    const base = ({ tight:55, medium:43, loose:34 })[overallRange], target = ({ tight:55, medium:43, loose:34 })[category];
    return { range: { strengthThreshold: base + (target - base) * blendWeight, source: "calibrated_showdown_target", defaultRange: overallRange, profileRange: category, weight: blendWeight }, samples, category, blendWeight, eligible: true };
  }
  function profileRangeDecision({ profile = {}, actions = [], currentAction = "", bet = 0, pot = 0, position = "middle", strategyMode = "auto", playerCount = 2, maximumExploitWeight = null } = {}) {
    const input = { actions, currentAction, bet, pot, position }, metrics = hudMetrics(profile);
    const defaultRange = defaultOpponentRange(input), strongCurrentEvidence = defaultRange === "tight" && (
      actions.some(item => ["raise", "reraise", "allin"].includes(item.action)) ||
      ["raise", "reraise", "allin"].includes(currentAction) || (pot > 0 && bet / pot >= .75));
    let fusedRange = defaultRange;
    if (!strongCurrentEvidence && metrics.vpip !== null) {
      if (metrics.vpip <= .24) fusedRange = actions.some(item => item.action === "call") || currentAction === "call" ? "tight" : "medium";
      else if (metrics.vpip >= .38 && (actions.some(item => item.action === "call") || currentAction === "call" || ["dealer", "cutoff", "late", "blind", "small_blind", "big_blind", "straddle"].includes(position))) fusedRange = "loose";
    }
    const lastAction = [...actions].reverse().find(item => item?.action) || {}, sceneEvidence = matchingSceneEvidence(profile, { ...lastAction, action: lastAction.action || currentAction, position: lastAction.position || position, playerCount: lastAction.playerCount || playerCount }), sampleTier = profileSampleTier(metrics.opportunities), sceneSamples = sceneEvidence.actionSampleCount, sceneTier = sceneSampleTier(sceneSamples);
    const sceneWeight = sceneSamples < 5 ? 0 : sceneSamples < 15 ? .15 : sceneSamples < 30 ? .35 : sceneSamples < 60 ? .60 : .80;
    const overallWeight = Math.max(metrics.platformWeight * .45, metrics.observedWeight * .60);
    const policy = strategyPolicy(strategyMode);
    let exploitationWeight = strategyMode === "baseline" ? 0 : strategyMode === "strict_exploit"
      ? Math.min(overallWeight, sceneWeight)
      : Math.max(overallWeight, sceneWeight * .80);
    const externallyBounded = maximumExploitWeight != null && Number.isFinite(Number(maximumExploitWeight));
    const configuredCap = externallyBounded
      ? Math.max(0, Math.min(1, Number(maximumExploitWeight))) : policy.maximumExploitWeight;
    const multiwayPenalty = externallyBounded ? 0 : Math.max(0, Number(playerCount) - 2) * .12;
    exploitationWeight = Math.max(0, Math.min(policy.maximumExploitWeight, configuredCap, exploitationWeight - multiwayPenalty));
    if (strongCurrentEvidence) exploitationWeight = 0;
    const minimumWeight = strategyMode === "baseline" ? Infinity : strategyMode === "strict_exploit" ? .35 : .15;
    const sampleGate = strategyMode !== "strict_exploit" || metrics.opportunities >= 100 && sceneSamples >= 30;
    const canApplyProfile = exploitationWeight >= minimumWeight && sampleGate && !strongCurrentEvidence;
    const calibratedShowdown = showdownTarget(sceneEvidence, fusedRange, profile.modelCalibration), order = ["tight", "medium", "loose"], defaultIndex = order.indexOf(defaultRange), fusedIndex = order.indexOf(fusedRange);
    const appliedRange = canApplyProfile ? order[Math.max(0, Math.min(order.length - 1, defaultIndex + Math.sign(fusedIndex - defaultIndex)))] : defaultRange;
    const changed = fusedRange !== defaultRange, applied = appliedRange !== defaultRange;
    const sources = [];
    if (metrics.observedWeight > 0) sources.push("observed_overall");
    if (metrics.platformWeight > 0) sources.push("platform_overall");
    if (calibratedShowdown.eligible) sources.push("calibrated_showdown");
    const overallProgress = nextTierProgress(metrics.opportunities, [20, 50, 100, 200]);
    const sceneProgress = nextTierProgress(sceneSamples, [5, 15, 30, 60]);
    const showdownChangesRange = calibratedShowdown.eligible && calibratedShowdown.category !== fusedRange;
    const reasons = strongCurrentEvidence ? ["本手强行动或大尺度投入优先，历史画像不得放宽范围"] :
      canApplyProfile && showdownChangesRange ?
        [`亮牌已通过整手留出校准，按当前场景${calibratedShowdown.samples}个亮牌动作样本受限修正范围`] :
      !changed ? ["画像与基础范围一致"] : canApplyProfile ?
        [`${strategyMode === "strict_exploit" ? "严格条件剥削" : "自动综合"}权重${Math.round(exploitationWeight * 100)}%，对手范围最多修正一档`] :
        [`总体${overallProgress.count}次、当前场景${sceneProgress.count}次，尚未达到本模式的正式修正门槛`];
    const profileTarget = calibratedShowdown.eligible ? calibratedShowdown.range : appliedRange, profileThreshold = profileTarget && typeof profileTarget === "object" ? Number(profileTarget.strengthThreshold) : ({ tight:55, medium:43, loose:34 })[profileTarget], defaultThreshold = ({ tight:55, medium:43, loose:34 })[defaultRange], formalRange = canApplyProfile && Number.isFinite(profileThreshold) && profileThreshold !== defaultThreshold ? { strengthThreshold: defaultThreshold + (profileThreshold - defaultThreshold) * exploitationWeight, source: "weighted_profile_range", defaultRange, profileRange: calibratedShowdown.eligible ? calibratedShowdown.category : profileTarget, weight: exploitationWeight } : defaultRange;
    return { defaultRange, fusedRange, appliedRange, sampleTier, sceneTier, effectiveOpportunities: metrics.opportunities,
      allowedToChangeAction: canApplyProfile && formalRange !== defaultRange, sources,
      impact: formalRange !== defaultRange ? "applied" : changed ? "audit_only" : "none",
      reasons, strongCurrentEvidence, metrics, strategyMode, exploitationWeight,
      formalRange,
      sceneSampleCount: sceneSamples, sceneEvidence: { event: sceneEvidence.event, actionSampleCount: sceneSamples, showdownSampleCount: sceneEvidence.showdownSampleCount, matchTier: sceneEvidence.matchTier, matchedDimensions: sceneEvidence.matchedDimensions, comparedDimensions: sceneEvidence.comparedDimensions },
      showdownSampleCount: sceneEvidence.showdownSampleCount, showdownRange: calibratedShowdown.category,
      showdownCalibrationEligible: calibratedShowdown.eligible, showdownBlendWeight: calibratedShowdown.blendWeight,
      showdownFormalWeight: calibratedShowdown.eligible && canApplyProfile ? calibratedShowdown.blendWeight * exploitationWeight : 0,
      overallProgress, sceneProgress, policy };
  }
  function strategyPolicy(mode = "auto") {
    if (mode === "baseline") return {
      mode, label: "稳健基础策略", minimumPopulationSamples: Infinity,
      minimumPersonalSamples: Infinity, maximumFallbackLevel: -1,
      maximumExploitWeight: 0, allowPopulationColdStart: false,
    };
    if (mode === "strict_exploit") return {
      mode, label: "严格条件剥削", minimumPopulationSamples: 30,
      minimumPersonalSamples: 30, maximumFallbackLevel: 1,
      maximumExploitWeight: .35, allowPopulationColdStart: false,
    };
    return {
      mode: "auto", label: "自动基础与剥削策略", minimumPopulationSamples: 5,
      minimumPersonalSamples: 5, maximumFallbackLevel: 3,
      maximumExploitWeight: .80, allowPopulationColdStart: true,
    };
  }
  function reactionPolicy(estimate, mode = "auto", maximumExploitWeight = null) {
    const policy = strategyPolicy(mode), personal = Math.max(0, Number(estimate?.sampleCount) || 0),
      population = Math.max(0, Number(estimate?.populationSampleCount) || 0),
      fallbackLevel = Number.isFinite(Number(estimate?.fallbackLevel)) ? Number(estimate.fallbackLevel) : 0,
      exactEnough = fallbackLevel <= policy.maximumFallbackLevel,
      personalReady = personal >= policy.minimumPersonalSamples,
      populationReady = population >= policy.minimumPopulationSamples,
      coldStart = policy.allowPopulationColdStart && !personalReady && populationReady,
      usable = mode !== "baseline" && exactEnough && (mode === "strict_exploit"
        ? personalReady && populationReady : personalReady || populationReady);
    const sampleWeight = personal >= 60 ? .80 : personal >= 30 ? .60 : personal >= 15 ? .35 : personal >= 5 ? .15 : 0;
    const populationWeight = population >= 60 ? .35 : population >= 30 ? .25 : population >= 15 ? .15 : population >= 5 ? .08 : 0;
    const matchPenalty = fallbackLevel <= 0 ? 1 : fallbackLevel === 1 ? .75 : fallbackLevel === 2 ? .50 : .30;
    const configuredCap = maximumExploitWeight != null && Number.isFinite(Number(maximumExploitWeight))
      ? Math.max(0, Math.min(1, Number(maximumExploitWeight))) : policy.maximumExploitWeight;
    const exploitWeight = usable ? Math.min(policy.maximumExploitWeight, configuredCap,
      Math.max(sampleWeight, coldStart ? populationWeight : Math.min(sampleWeight, populationWeight)) * matchPenalty) : 0;
    return {...policy, usable, personalReady, populationReady, coldStart, personalSamples:personal,
      populationSamples:population, fallbackLevel, exploitWeight};
  }
  function opponentRange(input = {}) { return profileRangeDecision(input).formalRange; }
  function shuffle(array) { for (let i = array.length - 1; i; i--) { const j = Math.floor(Math.random() * (i + 1)); [array[i], array[j]] = [array[j], array[i]]; } }
  function shufflePrefix(array, count, start = 0) { for (let i = start; i < Math.min(array.length, start + count); i++) { const j = i + Math.floor(Math.random() * (array.length - i)); [array[i], array[j]] = [array[j], array[i]]; } }
  function analyzeEquity(hero, board, rangeType, trials = 5000) {
    const deck = fullDeck().filter(card => !new Set([...hero, ...board]).has(card));
    const groups = { ahead: new Map(), behind: new Map(), tie: new Map() }; let score = 0, accepted = 0, attempts = 0;
    while (accepted < trials && attempts < trials * 30) {
      attempts++; shufflePrefix(deck, 2); const villain = deck.slice(0, 2); if (!inRange(villain, rangeType)) continue;
      shufflePrefix(deck, 5 - board.length, 2);
      const finalBoard = [...board, ...deck.slice(2, 2 + 5 - board.length)];
      const comparison = compareRanks(evaluate([...hero, ...finalBoard]), evaluate([...villain, ...finalBoard]));
      const group = comparison > 0 ? "ahead" : comparison < 0 ? "behind" : "tie"; const key = comboKey(villain);
      groups[group].set(key, (groups[group].get(key) || 0) + 1); score += comparison > 0 ? 1 : comparison === 0 ? .5 : 0; accepted++;
    }
    const summarize = map => [...map].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([combo, count]) => ({ combo, share: count / accepted }));
    return { equity: score / accepted, samples: accepted, matchups: { ahead: summarize(groups.ahead), behind: summarize(groups.behind), tie: summarize(groups.tie) } };
  }
  function advice({ equity, required, pot, call, effective, texture, styles, rakeRate = null, rakeCap = null }) {
    const grossPot = pot + call;
    const rakeKnown = Number.isFinite(rakeRate) && rakeRate >= 0;
    const estimatedRake = rakeKnown ? Math.min(grossPot * rakeRate, Number.isFinite(rakeCap) ? rakeCap : Infinity) : null;
    const netPot = grossPot - (estimatedRake || 0);
    const ev = equity * netPot - call, roi = call ? ev / call : 0, spr = pot ? effective / pot : 0;
    const aggressive = styles.filter(x => /凶|激进/.test(x)).length, weak = styles.filter(x => /弱|易弃/.test(x)).length;
    let approach = aggressive >= 2 ? "收紧诱导·价值优先" : weak >= 2 ? "位置进攻·扩大价值" : "均衡应对";
    if (texture === "wet") approach += "·保护牌力";
    let primary = call > 0 ? (equity >= Math.max(required + .12, .62) ? "加注" : ev >= 0 ? "跟注" : "弃牌") : (equity >= .62 ? "加注" : "让牌");
    let scale = equity >= .70 || texture === "wet" ? [.75, 1.10] : equity >= .52 ? [.50, .70] : [.25, .40];
    const ratio = (scale[0] + scale[1]) / 2;
    const precision = pot < 20 ? 100 : 1;
    let recommended = Math.min(effective, Math.round((call + (pot + call) * ratio) * precision) / precision);
    const reasonable = [
      Math.min(effective, Math.round((call + (pot + call) * scale[0]) * precision) / precision),
      Math.min(effective, Math.round((call + (pot + call) * scale[1]) * precision) / precision)
    ];
    const allIn = effective > 0 && (recommended >= effective * .8 || spr <= 1);
    const requiredAfterRake = call > 0 ? call / (netPot || 1) : 0;
    return { approach, primary: allIn && primary === "加注" ? "All-in候选" : primary, alternative: primary === "加注" ? "跟注" : primary === "跟注" ? "加注" : "让牌", scale, recommended, reasonable, ev, roi, spr, rakeKnown, estimatedRake, netPot, requiredAfterRake };
  }
  function preflopAdvice(hero, position, facingBet, players, opponentProfiles = [], pot = 0, effective = Infinity, raiseCount = 0) {
    const detailedPosition=position;
    position=({dealer:"late",cutoff:"late",hijack:"middle",middle:"middle",under_the_gun_plus_one:"early",under_the_gun:"early",straddle:"straddle",small_blind:"blind",big_blind:"blind"}[position]||position);
    const key=comboKey(hero), short=players<=4;
    const groups={
      premium:new Set(["AA","KK"]),
      strong:new Set(["QQ","JJ","AKs","AKo"]),
      early:new Set(["AA","KK","QQ","JJ","TT","99","AKs","AQs","AJs","KQs","AKo","AQo"]),
      middle:new Set(["88","77","ATs","A5s","A4s","A3s","A2s","KJs","QJs","JTs","AJo","KQo","T9s","98s"]),
      late:new Set(["66","55","44","33","22","A9s","A8s","A7s","A6s","A5s","A4s","A3s","A2s","KTs","K9s","QTs","Q9s","J9s","T8s","87s","76s","65s","ATo","KJo","QJo"]),
      defend:new Set(["TT","99","88","AQs","AJs","ATs","KQs","KJs","QJs","JTs","AQo","AJo","KQo"])
    };
    const open=groups.early.has(key)||(position!=="early"&&groups.middle.has(key))||((position==="late"||position==="blind"||position==="straddle"||short)&&groups.late.has(key));
    const stackPressure=Number.isFinite(effective)&&effective>0?facingBet/effective:0;
    const severePressure=stackPressure>=.33||raiseCount>=2;
    const highPressure=stackPressure>=.18||raiseCount>=1||facingBet>Math.max(3,pot*.75);
    const continueHand=groups.premium.has(key)||groups.strong.has(key)||(!highPressure&&(groups.early.has(key)||groups.defend.has(key)));
    const singleRaiseValue=raiseCount===1&&stackPressure<.18&&(
      new Set(["AA","KK","QQ","AKs","AKo"]).has(key)||
      (["dealer","cutoff"].includes(detailedPosition)&&new Set(["AQs","AQo"]).has(key))
    );
    let primary;
    if(facingBet<=0)primary=open?"加注":position==="straddle"?"让牌":"弃牌";
    else if(groups.premium.has(key)||singleRaiseValue)primary="加注";
    else if(severePressure)primary=new Set(["QQ","AKs"]).has(key)?"跟注":"弃牌";
    else if(highPressure)primary=groups.strong.has(key)?"跟注":continueHand?"跟注":"弃牌";
    else primary=groups.strong.has(key)?"加注":continueHand?"跟注":"弃牌";
    const reason=primary==="加注"?(facingBet>0?"强牌适合继续主动加注":"当前位置允许这组牌主动进入"):primary==="跟注"?"这组牌可承受当前普通加注":primary==="让牌"?"Straddle已强制投入且当前可免费让牌":"这组牌在当前位置或当前压力下长期回报偏低";
    const scale=facingBet>0?[.75,1.10]:[.45,.70];
    const uncappedRecommended=Math.max(facingBet+pot*scale[1],facingBet*2.5);
    const recommended=primary==="加注"?Math.min(effective,uncappedRecommended):0;
    const rakeRobust=groups.premium.has(key)||groups.strong.has(key)||primary==="弃牌";
    return {primary,alternative:primary==="加注"?"跟注或弃牌":primary==="跟注"?"弃牌":"无",approach:"翻牌前位置牌组",reason,handGroup:key,position:detailedPosition,scale,recommended,reasonable:[Math.min(effective,Math.max(facingBet+pot*scale[0],facingBet*2.2)),recommended],ev:null,roi:null,spr:null,pressure:severePressure?"severe":highPressure?"high":"normal",rakeRobust};
  }
  function analyzeMultiway(hero, board, rangeTypes, trials = 6000) {
    const known = new Set([...hero, ...board]);
    const baseDeck = fullDeck().filter(card => !known.has(card));
    let wins = 0, ties = 0, accepted = 0, attempts = 0;
    const threats = Array(rangeTypes.length).fill(0);
    while (accepted < trials && attempts < trials * 50) {
      attempts++; const deck = [...baseDeck]; const villains = []; let cursor = 0, valid = true;
      for (const rangeType of rangeTypes) {
        let found = false;
        for (let tries = 0; tries < 20 && cursor + 1 < deck.length; tries++) {
          const first = cursor + Math.floor(Math.random() * (deck.length - cursor));
          [deck[cursor], deck[first]] = [deck[first], deck[cursor]];
          const second = cursor + 1 + Math.floor(Math.random() * (deck.length - cursor - 1));
          [deck[cursor + 1], deck[second]] = [deck[second], deck[cursor + 1]];
          const hand = deck.slice(cursor, cursor + 2);
          if (inRange(hand, rangeType)) { villains.push(hand); cursor += 2; found = true; break; }
        }
        if (!found) { valid = false; break; }
      }
      if (!valid) continue;
      shufflePrefix(deck, 5 - board.length, cursor);
      const runout = deck.slice(cursor, cursor + 5 - board.length), finalBoard = [...board, ...runout];
      const heroRank = evaluate([...hero, ...finalBoard]); const villainRanks = villains.map(hand => evaluate([...hand, ...finalBoard]));
      const bestVillain = villainRanks.reduce((best, rank) => compareRanks(rank, best) > 0 ? rank : best, villainRanks[0]);
      const comparison = compareRanks(heroRank, bestVillain);
      if (comparison > 0) wins++;
      else if (comparison === 0) {
        const tiedOpponents = villainRanks.filter(rank => compareRanks(rank, heroRank) === 0).length;
        ties += 1 / (tiedOpponents + 1);
      }
      villainRanks.forEach((rank, index) => { if (compareRanks(rank, heroRank) >= 0) threats[index]++; }); accepted++;
    }
    return { equity: (wins + ties) / accepted, win: wins / accepted, tie: ties / accepted, samples: accepted, threats: threats.map(value => value / accepted) };
  }

  function analyzeNuts(hero, board, deadCards = []) {
    const heroCards = parseCards(hero, 2, 2);
    const boardCards = parseCards(board, 0, 5);
    const dead = Array.isArray(deadCards) ? deadCards : String(deadCards || "").trim().split(/[\s,]+/).filter(Boolean);
    if (boardCards.length < 3) return { isNuts: false, reason: "board_incomplete", street: boardCards.length, betterHands: null, tyingHands: null, combinations: 0 };
    const known = new Set([...heroCards, ...boardCards, ...dead]);
    const deck = fullDeck().filter(card => !known.has(card));
    const heroRank = evaluate([...heroCards, ...boardCards]);
    let betterHands = 0, tyingHands = 0, combinations = 0;
    for (let first = 0; first < deck.length - 1; first++) for (let second = first + 1; second < deck.length; second++) {
      const comparison = compareRanks(evaluate([deck[first], deck[second], ...boardCards]), heroRank);
      if (comparison > 0) betterHands++;
      else if (comparison === 0) tyingHands++;
      combinations++;
    }
    return { isNuts: betterHands === 0, reason: betterHands === 0 ? "no_opponent_hand_beats" : "opponent_hand_can_beat", street: boardCards.length, heroRank, betterHands, tyingHands, combinations };
  }

  function isNutsExact(heroCards, boardCards, deadCards = []) {
    const known = new Set([...heroCards, ...boardCards, ...deadCards]);
    const deck = fullDeck().filter(card => !known.has(card));
    const heroRank = evaluate([...heroCards, ...boardCards]);
    for (let first = 0; first < deck.length - 1; first++) {
      for (let second = first + 1; second < deck.length; second++) {
        if (compareRanks(evaluate([deck[first], deck[second], ...boardCards]), heroRank) > 0) {
          return false;
        }
      }
    }
    return true;
  }

  function analyzeBoardPotential(hero, board, deadCards = []) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 3, 4);
    const dead = Array.isArray(deadCards) ? deadCards : String(deadCards || "").trim().split(/[\s,]+/).filter(Boolean);
    const known = new Set([...heroCards, ...boardCards, ...dead]);
    const remaining = fullDeck().filter(card => !known.has(card));
    const currentRank = evaluate([...heroCards, ...boardCards]);
    const currentIsNuts = isNutsExact(heroCards, boardCards, dead);
    let improvements = 0, newlyNutted = 0, lostNuts = 0;
    for (const card of remaining) {
      const nextBoard = [...boardCards, card];
      const nextRank = evaluate([...heroCards, ...nextBoard]);
      const boardRank = nextBoard.length >= 5 ? evaluate(nextBoard) : null;
      if (nextRank[0] > currentRank[0] && (!boardRank || nextRank[0] > boardRank[0])) improvements++;
      const nextNuts = isNutsExact(heroCards, nextBoard, dead);
      if (!currentIsNuts && nextNuts) newlyNutted++;
      if (currentIsNuts && !nextNuts) lostNuts++;
    }
    const total = remaining.length;
    return {
      street: boardCards.length,
      nextStreetCards: total,
      currentIsNuts,
      improvementProbability: total ? improvements / total : 0,
      nutsImprovementProbability: total ? newlyNutted / total : 0,
      protectionGain: currentIsNuts && total ? lostNuts / total : 0,
      improvingCards: improvements,
      newlyNuttedCards: newlyNutted,
      vulnerableCards: lostNuts,
      exact: true,
      conservative: true,
    };
  }

  function analyzeCrossStreet({ hero, board = [], deadCards = [], trials = 300 } = {}) {
    const heroCards = parseCards(hero, 2, 2);
    const boardCards = parseCards(board, 0, 5);
    const current = analyzeNuts(heroCards, boardCards, deadCards);
    const remainingStreets = Math.max(0, 5 - boardCards.length);
    if (remainingStreets === 0) return { ...current, remainingStreets: 0, nextStreetNutsProbability: null, riverNutsProbability: current.isNuts ? 1 : 0 };
    const known = new Set([...heroCards, ...boardCards, ...(Array.isArray(deadCards) ? deadCards : [])]);
    const deck = fullDeck().filter(card => !known.has(card));
    const sampleCount = Math.min(Math.max(1, Number(trials) || 300), 1000);
    let nextNuts = 0, riverNuts = 0, sampled = 0;
    for (let attempt = 0; attempt < sampleCount; attempt++) {
      const shuffled = [...deck]; shuffle(shuffled);
      const nextBoard = [...boardCards, shuffled[0]];
      if (analyzeNuts(heroCards, nextBoard, deadCards).isNuts) nextNuts++;
      if (remainingStreets >= 2) {
        const riverBoard = [...boardCards, shuffled[0], shuffled[1]];
        if (analyzeNuts(heroCards, riverBoard, deadCards).isNuts) riverNuts++;
      } else if (current.isNuts) riverNuts++;
      sampled++;
    }
    return { ...current, remainingStreets, nextStreetNutsProbability: nextNuts / sampled, riverNutsProbability: riverNuts / sampled, samples: sampled };
  }

  function analyzeFutureStreetEV({ hero, board = [], opponents = [], deadCards = [], pot, call = 0, rakeRate = null, rakeCap = null } = {}) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 3, 4);
    const opponentHands = (opponents || []).map(item => parseCards(item?.cards ?? item, 2, 2));
    if (!opponentHands.length) throw new Error("at least one known opponent hand is required");
    if (!Number.isFinite(pot) || pot < 0 || !Number.isFinite(call) || call < 0) throw new Error("pot and call must be non-negative numbers");
    const dead = Array.isArray(deadCards) ? deadCards : String(deadCards || "").trim().split(/[\s,]+/).filter(Boolean);
    const known = [...heroCards, ...boardCards, ...opponentHands.flat(), ...dead];
    if (new Set(known).size !== known.length) throw new Error("known cards contain duplicates");
    const deck = fullDeck().filter(card => !known.includes(card)), missing = 5 - boardCards.length;
    const netPot = finalPotAfterRake(pot + call, rakeRate, rakeCap), routes = new Map();
    let equitySum = 0, samples = 0;
    const score = finalBoard => {
      const heroRank = evaluate([...heroCards, ...finalBoard]);
      const opponentRanks = opponentHands.map(hand => evaluate([...hand, ...finalBoard]));
      const bestOpponent = opponentRanks.reduce((best, rank) => compareRanks(rank, best) > 0 ? rank : best, opponentRanks[0]);
      const comparison = compareRanks(heroRank, bestOpponent);
      if (comparison < 0) return 0;
      if (comparison > 0) return 1;
      return 1 / (1 + opponentRanks.filter(rank => compareRanks(rank, heroRank) === 0).length);
    };
    const add = (nextCard, finalBoard) => {
      const share = score(finalBoard), route = routes.get(nextCard) || { card: nextCard, equitySum: 0, runouts: 0 };
      equitySum += share; samples++; route.equitySum += share; route.runouts++; routes.set(nextCard, route);
    };
    if (missing === 1) deck.forEach(card => add(card, [...boardCards, card]));
    else for (let turn = 0; turn < deck.length; turn++) for (let river = 0; river < deck.length; river++) {
      if (turn !== river) add(deck[turn], [...boardCards, deck[turn], deck[river]]);
    }
    const equity = samples ? equitySum / samples : null;
    return {
      street: boardCards.length === 3 ? "flop" : "turn",
      remainingStreets: missing,
      exactRunoutEnumeration: true,
      samples,
      equity,
      grossTerminalPot: pot + call,
      netTerminalPot: netPot,
      passiveEV: equity === null ? null : equity * netPot - call,
      nextStreetRoutes: [...routes.values()].map(route => ({
        card: route.card,
        runouts: route.runouts,
        equity: route.equitySum / route.runouts,
        netTerminalPot: netPot,
        passiveEV: route.equitySum / route.runouts * netPot - call,
      })),
      behaviorModel: "none",
      scope: "known_hands_fixed_investment_showdown",
      futureStreetSolved: true,
      futureStreetEVSolved: true,
      fullOpponentBehaviorTreeSolved: false,
    };
  }

  function normalizeContributions(contributions) {
    if (contributions instanceof Map) return [...contributions.entries()].map(([seat, amount]) => [Number(seat), Number(amount)]);
    if (Array.isArray(contributions)) return contributions.map(item => Array.isArray(item) ? [Number(item[0]), Number(item[1])] : [Number(item.seat), Number(item.amount)]);
    return Object.entries(contributions || {}).map(([seat, amount]) => [Number(seat), Number(amount)]);
  }

  function buildSidePotLayers(contributions, foldedSeats = []) {
    const folded = new Set((foldedSeats || []).map(Number));
    const entries = normalizeContributions(contributions).filter(([seat, amount]) => Number.isInteger(seat) && Number.isFinite(amount) && amount > 0);
    const levels = [...new Set(entries.map(([, amount]) => amount))].sort((a, b) => a - b);
    const layers = []; let previous = 0;
    for (const cap of levels) {
      const contributors = entries.filter(([, amount]) => amount >= cap - 1e-9).map(([seat]) => seat);
      if (contributors.length < 2) break;
      layers.push({ cap, amount: (cap - previous) * contributors.length, contributors, eligibleSeats: contributors.filter(seat => !folded.has(seat)) });
      previous = cap;
    }
    return layers;
  }

  function buildSidePotAccounting(contributions, foldedSeats = []) {
    const folded = new Set((foldedSeats || []).map(Number));
    const merged = new Map();
    for (const [seat, amount] of normalizeContributions(contributions)) {
      if (!Number.isInteger(seat) || !Number.isFinite(amount) || amount <= 0) continue;
      merged.set(seat, Math.max(merged.get(seat) || 0, Number(amount)));
    }
    const entries = [...merged].sort((left, right) => left[0] - right[0]);
    const levels = [...new Set(entries.map(([, amount]) => amount))].sort((left, right) => left - right);
    const layers = [];
    const returned = new Map();
    let previous = 0;
    for (const cap of levels) {
      const contributors = entries.filter(([, amount]) => amount >= cap - 1e-9).map(([seat]) => seat);
      const amount = (cap - previous) * contributors.length;
      const eligibleSeats = contributors.filter(seat => !folded.has(seat));
      if (contributors.length >= 2) {
        layers.push({
          cap,
          amount,
          contributors,
          eligibleSeats,
          deadMoney: (cap - previous) * (contributors.length - eligibleSeats.length),
          returned: 0,
        });
      } else if (contributors.length === 1 && eligibleSeats.length === 1) {
        const seat = contributors[0];
        returned.set(seat, (returned.get(seat) || 0) + amount);
      } else if (contributors.length === 1) {
        const target = [...layers].reverse().find(layer => layer.eligibleSeats.length > 0);
        if (target) {
          target.amount += amount;
          target.deadMoney += amount;
        }
      }
      previous = cap;
    }
    const returnedObject = Object.fromEntries([...returned].filter(([, amount]) => amount > 1e-9));
    const inPotContributions = Object.fromEntries([...merged].map(([seat, amount]) => [seat, amount - (returned.get(seat) || 0)]));
    const grossPot = layers.reduce((sum, layer) => sum + layer.amount, 0);
    const committedTotal = [...merged.values()].reduce((sum, amount) => sum + amount, 0);
    const returnedTotal = Object.values(returnedObject).reduce((sum, amount) => sum + amount, 0);
    return {
      committedContributions: Object.fromEntries(merged),
      inPotContributions,
      returned: returnedObject,
      returnedTotal,
      deadMoney: [...merged].filter(([seat]) => folded.has(seat)).reduce((sum, [, amount]) => sum + amount, 0),
      grossPot,
      layers: layers.filter(layer => layer.amount > 1e-9 || layer.deadMoney > 1e-9),
      exact: layers.every(layer => layer.eligibleSeats.length > 0) && Math.abs(committedTotal - grossPot - returnedTotal) <= 1e-8,
    };
  }

  function requiresSidePotLayering(layers = []) {
    const eligibleGroups = new Set((layers || []).map(layer =>
      [...new Set((layer.eligibleSeats || []).map(Number).filter(Number.isInteger))]
        .sort((left, right) => left - right).join(",")));
    return eligibleGroups.size > 1;
  }

  function buildSidePotContract({ heroSeat, contributions, foldedSeats = [], reportedPot = null,
    hasAllIn = false, unknown = false, legalActions = [], rakeRate = null, rakeCap = null,
    rakeAllocation = null } = {}) {
    const seat = Number(heroSeat), accounting = buildSidePotAccounting(contributions, foldedSeats);
    const reported = Number(reportedPot), returnedTotal = Number(accounting.returnedTotal) || 0;
    const reportedContested = Number.isFinite(reported) ? Math.max(0, reported - returnedTotal) : null;
    const tolerance = Number.isFinite(reportedContested) ? Math.max(.10, Math.abs(reportedContested) * .15) : null;
    const consistent = Number.isFinite(reportedContested) && Math.abs(reportedContested - accounting.grossPot) <= tolerance;
    const requiresLayering = hasAllIn === true && requiresSidePotLayering(accounting.layers);
    const rakeKnown = Number.isFinite(rakeRate) && rakeRate >= 0 && (rakeRate === 0 || Number.isFinite(rakeCap) && rakeCap >= 0);
    const allocationKnown = rakeKnown && (Number(rakeRate) === 0 || rakeAllocation === "main_pot_first");
    let remainingRake = rakeKnown ? Math.min(accounting.grossPot * Number(rakeRate), Number.isFinite(rakeCap) ? Number(rakeCap) : Infinity) : null;
    const layers = accounting.layers.map((layer, index) => {
      const heroEligible = layer.eligibleSeats.includes(seat);
      const layerRake = allocationKnown ? Math.min(layer.amount * Number(rakeRate), remainingRake) : null;
      if (layerRake !== null) remainingRake -= layerRake;
      return {
        id: index === 0 ? "main" : `side-${index}`,
        kind: index === 0 ? "main" : "side",
        ordinal: index,
        cap: layer.cap,
        grossAmount: layer.amount,
        netAmount: layerRake === null ? null : layer.amount - layerRake,
        rake: layerRake,
        contributors: [...layer.contributors],
        participants: [...layer.eligibleSeats],
        eligibleSeats: [...layer.eligibleSeats],
        deadMoney: Number(layer.deadMoney) || 0,
        heroEligible,
        heroWinnableGross: heroEligible ? layer.amount : 0,
        heroWinnableNet: heroEligible && layerRake !== null ? layer.amount - layerRake : heroEligible ? null : 0,
      };
    });
    const heroLayers = layers.filter(layer => layer.heroEligible);
    const heroWinnableGross = heroLayers.reduce((sum, layer) => sum + layer.grossAmount, 0);
    const heroWinnableNet = allocationKnown ? heroLayers.reduce((sum, layer) => sum + layer.netAmount, 0) : null;
    const exact = unknown !== true && accounting.exact === true && consistent && layers.every(layer => layer.participants.length >= 2);
    return {
      contractVersion: 1,
      heroSeat: Number.isInteger(seat) ? seat : null,
      requiresLayering,
      complexMultiway: requiresLayering && layers.some(layer => layer.participants.length > 2),
      exact,
      unknown: unknown === true,
      consistent,
      reportedPot: Number.isFinite(reported) ? reported : null,
      reportedContestedPot: reportedContested,
      accountedPot: accounting.grossPot,
      grossPot: accounting.grossPot,
      contestedPot: heroWinnableGross,
      heroWinnableGross,
      heroWinnableNet,
      committedContributions: accounting.committedContributions,
      contributions: accounting.inPotContributions,
      returned: accounting.returned,
      returnedTotal,
      deadMoney: accounting.deadMoney,
      mainPot: layers[0] || null,
      sidePots: layers.slice(1),
      layers,
      legalActions: [...new Set((legalActions || []).filter(Boolean))],
      rake: {
        rate: Number.isFinite(rakeRate) ? Number(rakeRate) : null,
        cap: Number.isFinite(rakeCap) ? Number(rakeCap) : null,
        allocation: rakeAllocation || null,
        known: rakeKnown,
        allocationKnown,
        estimatedTotal: rakeKnown ? Math.min(accounting.grossPot * Number(rakeRate), Number.isFinite(rakeCap) ? Number(rakeCap) : Infinity) : null,
      },
      evPolicy: {
        mode: requiresLayering ? "layered_passive_only" : "single_contested_pot",
        v2T2T3Supported: !requiresLayering,
        t2T3Supported: !requiresLayering,
        reason: requiresLayering ? "V2/T2/T3未支持复杂多人边池逐层EV" : null,
      },
    };
  }

  function buildSidePotContractFromState(state, heroSeat) {
    const actions = (state?.actionLog || []).filter(item => item.handId === state.handId);
    const money = new Set(["blind", "post_blind", "straddle", "call", "bet", "raise", "reraise", "allin"]);
    const foldedSeats = actions.filter(item => item.action === "fold").map(item => Number(item.seat));
    const byStreet = new Map();
    const unknown = actions.some(item => money.has(item.action) && !Number.isFinite(item.amount));
    for (const item of actions) {
      if (!money.has(item.action) || !Number.isInteger(item.seat) || !Number.isFinite(item.amount)) continue;
      const key = `${item.street || "preflop"}:${item.seat}`;
      byStreet.set(key, Math.max(byStreet.get(key) || 0, Math.max(0, Number(item.amount))));
    }
    const contributions = new Map();
    for (const [key, amount] of byStreet) {
      const seat = Number(key.split(":")[1]);
      contributions.set(seat, (contributions.get(seat) || 0) + amount);
    }
    for (const player of state?.seats || []) {
      if (!Number.isInteger(player.index) || !Number.isFinite(player.streetBet)) continue;
      const seat = player.index + 1, key = `${state.street}:${seat}`, known = byStreet.get(key) || 0;
      if (player.streetBet > known + .001) contributions.set(seat, (contributions.get(seat) || 0) + player.streetBet - known);
    }
    const ante = Number(state?.blindAnte), listedParticipants = Array.isArray(state?.handParticipants) ? state.handParticipants.map(Number).filter(Number.isInteger) : [];
    const participantSeats = listedParticipants.length >= 2 ? listedParticipants : (state?.seats || []).filter(player => Number.isInteger(player.index) && !player.empty && player.action !== "empty").map(player => player.index + 1);
    if (state?.street === "preflop" && Number.isFinite(ante) && ante > 0) {
      for (const seat of participantSeats) contributions.set(seat, (contributions.get(seat) || 0) + ante);
    }
    if (Number.isInteger(Number(heroSeat)) && !contributions.has(Number(heroSeat))) contributions.set(Number(heroSeat), 0);
    const contract = buildSidePotContract({
      heroSeat, contributions, foldedSeats, reportedPot: state?.pot,
      hasAllIn: actions.some(item => item.action === "allin"), unknown,
      legalActions: (state?.visualButtons?.length ? state.visualButtons : state?.buttons || []).map(item => item.kind).filter(Boolean),
      rakeRate: state?.rakeRate, rakeCap: state?.rakeCap,
      rakeAllocation: state?.tablePlay?.decisionRules?.rakeAllocation,
    });
    return { ...contract, antePerPlayer: Number.isFinite(ante) && ante > 0 ? ante : 0, anteSeats: Number.isFinite(ante) && ante > 0 ? participantSeats : [] };
  }

  function analyzeSidePotEquity({ hero, board = [], heroSeat, contributions, foldedSeats = [], opponents = [], trials = 1000, rakeRate = null, rakeCap = null, deadMoney = 0 } = {}) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 0, 5), accounting = buildSidePotAccounting(contributions, foldedSeats), layers = accounting.layers.map(layer => ({ ...layer })), extraDeadMoney = Math.max(0, Number(deadMoney) || 0);
    if (layers.length && extraDeadMoney > 0) { layers[0].amount += extraDeadMoney; layers[0].deadMoney += extraDeadMoney; }
    const opponentBySeat = new Map((opponents || []).map(item => [Number(item.seat), item]));
    const activeSeats = [...new Set(layers.flatMap(layer => layer.eligibleSeats))].filter(seat => seat !== Number(heroSeat));
    const knownOpponents = activeSeats.every(seat => Array.isArray(opponentBySeat.get(seat)?.cards) && opponentBySeat.get(seat).cards.length === 2);
    const exactHands = knownOpponents && boardCards.length >= 3;
    const requested = exactHands ? 1 : Math.min(Math.max(1, Number(trials) || 1000), 5000);
    const sums = layers.map(() => 0); let accepted = 0;
    const baseKnown = new Set([...heroCards, ...boardCards]);
    const runouts = [];
    if (exactHands) {
      const missing = 5 - boardCards.length;
      if (missing === 1) {
        const used = new Set([...heroCards, ...boardCards, ...activeSeats.flatMap(seat => opponentBySeat.get(seat)?.cards || [])]);
        for (const card of fullDeck()) if (!used.has(card)) runouts.push([card]);
      } else if (missing === 2) {
        const used = new Set([...heroCards, ...boardCards, ...activeSeats.flatMap(seat => opponentBySeat.get(seat)?.cards || [])]);
        const available = fullDeck().filter(card => !used.has(card));
        for (let first = 0; first < available.length - 1; first++) for (let second = first + 1; second < available.length; second++) runouts.push([available[first], available[second]]);
      }
    }
    const iterations = exactHands && runouts.length ? runouts.length : requested;
    const baseDeck = fullDeck().filter(card => !baseKnown.has(card));
    for (let trial = 0; trial < iterations; trial++) {
      const used = new Set(baseKnown), deck = [...baseDeck];
      const hands = new Map([[Number(heroSeat), heroCards]]);
      for (const seat of activeSeats) {
        const item = opponentBySeat.get(seat); let hand;
        if (Array.isArray(item?.cards) && item.cards.length === 2) hand = item.cards;
        else {
          const range = item?.rangeType || "random"; let found = false;
          for (let tries = 0; tries < 100 && !found; tries++) { shufflePrefix(deck, 2); const candidate = deck.slice(0, 2); if (inRange(candidate, range)) { hand = candidate; found = true; } }
          if (!found) hand = deck.slice(0, 2);
        }
        if (!hand || hand.some(card => used.has(card))) continue;
        hand.forEach(card => { used.add(card); const index = deck.indexOf(card); if (index >= 0) deck.splice(index, 1); }); hands.set(seat, hand);
      }
      const missing = 5 - boardCards.length, runout = exactHands && runouts.length ? runouts[trial] : deck; if (!exactHands) shufflePrefix(runout, missing); const finalBoard = [...boardCards, ...runout.slice(0, missing)];
      if (finalBoard.length !== 5 || activeSeats.some(seat => !hands.has(seat))) continue;
      const ranksBySeat = new Map([...hands].map(([seat, hand]) => [seat, evaluate([...hand, ...finalBoard])]));
      layers.forEach((layer, index) => {
        if (!layer.eligibleSeats.includes(Number(heroSeat))) return;
        const eligible = layer.eligibleSeats.filter(seat => ranksBySeat.has(seat));
        if (!eligible.length) return;
        const best = eligible.reduce((winner, seat) => !winner || compareRanks(ranksBySeat.get(seat), ranksBySeat.get(winner)) > 0 ? seat : winner, null);
        const winners = eligible.filter(seat => compareRanks(ranksBySeat.get(seat), ranksBySeat.get(best)) === 0);
        if (winners.includes(Number(heroSeat))) sums[index] += 1 / winners.length;
      });
      accepted++;
    }
    let remainingCap = Number.isFinite(rakeCap) ? Math.max(0, rakeCap) : Infinity;
    const resultLayers = layers.map((layer, index) => { const grossLayer = layer.amount; const rake = Number.isFinite(rakeRate) && rakeRate >= 0 ? Math.min(grossLayer * rakeRate, remainingCap) : null; if (rake !== null) remainingCap -= rake; const netPot = rake === null ? null : grossLayer - rake, heroEquity = accepted ? sums[index] / accepted : null; return { ...layer, grossPot: grossLayer, rake, netPot, heroEquity, heroShare: heroEquity === null ? null : heroEquity * grossLayer, netHeroShare: heroEquity === null || netPot === null ? null : heroEquity * netPot }; });
    const rangeEstimate = accounting.exact && !exactHands && boardCards.length >= 3 && accepted >= 1000;
    return { layers: resultLayers, acceptedSamples: accepted, accountingExact: accounting.exact, rangeEstimate, riverRangeEstimate: rangeEstimate && boardCards.length === 5, exact: accounting.exact && exactHands && accepted > 0, exactRunoutEnumeration: accounting.exact && exactHands && (boardCards.length === 5 || runouts.length > 0), rakeKnown: Number.isFinite(rakeRate) && rakeRate >= 0, rakeRate: Number.isFinite(rakeRate) ? rakeRate : null, rakeCap: Number.isFinite(rakeCap) ? rakeCap : null, grossPot: accounting.grossPot + extraDeadMoney, deadMoney: accounting.deadMoney + extraDeadMoney, returned: accounting.returned, returnedTotal: accounting.returnedTotal };
  }

  function variantDecisionGate(tablePlay) {
    const play = typeof tablePlay === "string" ? { type: tablePlay } : tablePlay;
    const type = String(play?.type || "").trim();
    if (!type) return { usableForDecision: false, hardGate: true, reason: "牌桌玩法缺失，不输出正式策略", type: null };
    if (type === "德州扑克") return { usableForDecision: true, hardGate: false, reason: "", type, special: false };
    const rules = play?.decisionRules;
    const confirmed = play?.rulesConfirmed === true && rules?.complete === true;
    const compatible = rules?.standardHoldemCompatible === true;
    if (!confirmed || !compatible) {
      return {
        usableForDecision: false,
        hardGate: true,
        reason: "特殊玩法附加规则尚未完整确认，不输出正式策略",
        type,
        special: true,
      };
    }
    return { usableForDecision: true, hardGate: false, reason: "", type, special: true };
  }

  function summarizeSidePotForDecision(result, heroSeat) {
    const seat = Number(heroSeat);
    const layers = (result?.layers || []).filter(layer =>
      Array.isArray(layer.eligibleSeats) && layer.eligibleSeats.includes(seat));
    const exact = result?.exact === true && result?.exactRunoutEnumeration === true &&
      Number(result?.acceptedSamples) > 0 && layers.length > 0;
    const sampled = result?.rangeEstimate === true && Number(result?.acceptedSamples) >= 1000;
    const solved = exact || sampled;
    const rakeKnown = result?.rakeKnown === true && layers.every(layer => Number.isFinite(layer.netPot));
    const grossPot = layers.reduce((sum, layer) => sum + Math.max(0, Number(layer.grossPot) || 0), 0);
    const netPot = rakeKnown ? layers.reduce((sum, layer) => sum + Math.max(0, Number(layer.netPot) || 0), 0) : null;
    const expectedGrossShare = solved ? layers.reduce((sum, layer) => sum + Number(layer.heroShare || 0), 0) : null;
    const expectedNetShare = solved && rakeKnown ? layers.reduce((sum, layer) => sum + Number(layer.netHeroShare || 0), 0) : null;
    return {
      exact,
      rakeKnown,
      sampled,
      usableForDecision: solved && rakeKnown && Number.isFinite(expectedNetShare),
      acceptedSamples: Number(result?.acceptedSamples) || 0,
      grossPot,
      netPot,
      expectedGrossShare,
      expectedNetShare,
      returnedTotal: Number(result?.returnedTotal) || 0,
      layers,
    };
  }

  function economicsActionKey(kind, amount) {
    return Number.isFinite(amount) ? `${kind}:${Number(amount)}` : kind;
  }

  function buildDecisionEconomics({ hero, board = [], opponents = [], pot, call = 0, rakeRate = null, rakeCap = null, tablePlay = { type: "德州扑克" }, sidePot = null, aggressiveActionAvailable = false } = {}) {
    const variant = variantDecisionGate(tablePlay);
    if (!variant.usableForDecision) return { ...variant, auditOnly: true, source: "variant_gate", actions: {} };
    const numericPot = Number(pot), numericCall = Number(call);
    if (!Number.isFinite(numericPot) || numericPot < 0 || !Number.isFinite(numericCall) || numericCall < 0) {
      return { usableForDecision: false, hardGate: true, auditOnly: true, reason: "底池或跟注量无效", source: "invalid_money", variant, actions: {} };
    }
    const rakeKnown = Number.isFinite(rakeRate) && rakeRate >= 0 && (rakeRate === 0 || Number.isFinite(rakeCap) && rakeCap >= 0);
    if (!rakeKnown) return { usableForDecision: false, hardGate: true, auditOnly: true, reason: "抽成比例或上限未确认", source: "rake_unresolved", variant, actions: {} };
    if (sidePot) {
      if (aggressiveActionAvailable) {
        return { usableForDecision: false, hardGate: false, auditOnly: true, reason: "边池主动金额分支尚未逐层求解，只比较可靠的被动动作", source: "side_pot_variable_branch", variant, actions: {} };
      }
      const heroSeat = Number(sidePot.heroSeat), contributions = Object.fromEntries(normalizeContributions(sidePot.contributions));
      if (!Number.isInteger(heroSeat)) return { usableForDecision: false, hardGate: true, auditOnly: true, reason: "边池本人座位缺失", source: "side_pot_missing_hero", variant, actions: {} };
      if (sidePot.includesCall !== true) contributions[heroSeat] = Math.max(0, Number(contributions[heroSeat]) || 0) + numericCall;
      const result = analyzeSidePotEquity({
        hero, board, heroSeat, contributions,
        foldedSeats: sidePot.foldedSeats || [], opponents: sidePot.opponents || opponents,
        trials: sidePot.trials || 1000, rakeRate, rakeCap, deadMoney: sidePot.deadMoney,
      });
      const summary = summarizeSidePotForDecision(result, heroSeat);
      const expectedGrossPot = numericPot + (sidePot.includesCall === true ? 0 : numericCall) - summary.returnedTotal;
      const potMismatch = Math.abs(summary.grossPot - expectedGrossPot);
      const potConsistent = potMismatch <= Math.max(summary.sampled ? .10 : .01,
        expectedGrossPot * (summary.sampled ? .15 : .001));
      const rakeAllocationKnown = rakeRate === 0 || sidePot.rakeAllocation === "main_pot_first";
      if (!summary.usableForDecision) {
        return { usableForDecision: false, hardGate: true, auditOnly: true, reason: summary.rakeKnown ? "边池牌面、投入或资格不是精确证据" : "边池抽成未知", source: "side_pot_unresolved", variant, sidePot: summary, actions: {} };
      }
      if (!potConsistent) return { usableForDecision: false, hardGate: true, auditOnly: true, reason: "边池分层与当前底池无法对账", source: "side_pot_mismatch", variant, sidePot: summary, actions: {} };
      const callKind = sidePot.callKind === "allin_call" ? "allin_call" : "call";
      if (!rakeAllocationKnown) {
        const totalRake = Math.min(summary.grossPot * rakeRate, Number.isFinite(rakeCap) ? rakeCap : Infinity);
        const optimisticEV = summary.expectedGrossShare - numericCall;
        const pessimisticEV = Math.max(0, summary.expectedGrossShare - totalRake) - numericCall;
        const samplingMargin = summary.sampled
          ? Math.max(.01, expectedGrossPot * 2 / Math.sqrt(summary.acceptedSamples) + potMismatch)
          : .01;
        const robustEV = optimisticEV < -samplingMargin ? optimisticEV : pessimisticEV > samplingMargin ? pessimisticEV : null;
        if (robustEV === null) return { usableForDecision: false, hardGate: true, auditOnly: true, reason: "边池抽成扣除顺序会影响动作结论", source: "side_pot_rake_allocation_unresolved", variant, sidePot: summary, actions: {} };
        const actions = { fold: { ev: 0, exact: true }, [economicsActionKey(callKind, numericCall)]: { ev: robustEV, exact: false, bounded: true } };
        if (numericCall === 0) actions.check = { ev: Math.max(0, pessimisticEV), exact: false, bounded: true };
        return { usableForDecision: true, hardGate: false, auditOnly: false, reason: "抽成分配上下界结论一致", source: "side_pot_rake_allocation_bound", equity: summary.grossPot > 0 ? summary.expectedGrossShare / summary.grossPot : 0, pot: Math.max(0, summary.grossPot - numericCall), passiveEV: robustEV, variant, sidePot: summary, actions };
      }
      const ev = summary.expectedNetShare - numericCall;
      const samplingMargin = summary.sampled
        ? Math.max(.01, expectedGrossPot * 2 / Math.sqrt(summary.acceptedSamples) + potMismatch)
        : 0;
      if (summary.sampled && Math.abs(ev) <= samplingMargin) {
        return { usableForDecision: false, hardGate: true, auditOnly: true,
          reason: "边池范围抽样误差可能改变弃牌或跟注结论",
          source: "side_pot_range_uncertain", variant, sidePot: summary, actions: {} };
      }
      const actions = {
        fold: { ev: 0, exact: true },
        [economicsActionKey(callKind, numericCall)]: { ev, exact: summary.exact,
          bounded: summary.sampled, evLow: ev - samplingMargin, evHigh: ev + samplingMargin },
      };
      if (numericCall === 0) actions.check = { ev: summary.expectedNetShare, exact: true };
      return {
        usableForDecision: true,
        hardGate: false,
        auditOnly: false,
        reason: "",
        source: summary.exact ? "exact_side_pot_runout" : "side_pot_range_estimate",
        equity: summary.netPot > 0 ? summary.expectedNetShare / summary.netPot : 0,
        pot: Math.max(0, summary.grossPot - numericCall),
        passiveEV: ev,
        variant,
        sidePot: summary,
        actions,
      };
    }
    if (aggressiveActionAvailable) {
      return { usableForDecision: false, hardGate: false, auditOnly: true, reason: "跨街固定投入模型不覆盖主动金额分支", source: "future_street_variable_branch", variant, actions: {} };
    }
    const knownHands = (opponents || []).map(item => item?.cards ?? item);
    if (![3, 4].includes(Array.isArray(board) ? board.length : -1) || !knownHands.length || knownHands.some(cards => !Array.isArray(cards) || cards.length !== 2)) {
      return { usableForDecision: false, hardGate: false, auditOnly: true, reason: "缺少全部对手底牌，跨街结果仅供审核", source: "future_street_unresolved", variant, actions: {} };
    }
    const future = analyzeFutureStreetEV({ hero, board, opponents: knownHands, pot: numericPot, call: numericCall, rakeRate, rakeCap });
    const callKind = numericCall > 0 ? "call" : "check";
    const actions = { fold: { ev: 0, exact: true }, [economicsActionKey(callKind, numericCall > 0 ? numericCall : undefined)]: { ev: future.passiveEV, exact: true } };
    return {
      usableForDecision: true,
      hardGate: false,
      auditOnly: false,
      reason: "",
      source: "exact_known_hand_runout",
      equity: future.equity,
      pot: numericPot,
      passiveEV: future.passiveEV,
      variant,
      futureStreet: future,
      actions,
    };
  }

  function applyDecisionEconomics(comparison, economics) {
    if (!comparison) return comparison;
    if (!economics?.usableForDecision && economics?.source === "side_pot_variable_branch") {
      const evaluated = (comparison.evaluated || []).map(item =>
        ["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(item.kind)
          ? { ...item, ev: -Infinity, eligible: false, exactEconomics: false,
              reason: "边池主动金额分支尚未逐层求解" }
          : item);
      const eligible = evaluated.filter(item => item.eligible !== false && Number.isFinite(item.ev));
      const best = eligible.reduce((winner, item) => !winner || item.ev > winner.ev ? item : winner, null);
      return { ...comparison, evaluated, best, bestPassive: best, decisionEconomics: economics };
    }
    if (!economics?.usableForDecision) return comparison;
    const evaluated = (comparison.evaluated || []).map(item => {
      const alternateCallKind = item.kind === "allin_call" ? "call" : item.kind === "call" ? "allin_call" : null;
      const override = economics.actions?.[economicsActionKey(item.kind, item.amount)] || economics.actions?.[item.kind] ||
        (alternateCallKind && (economics.actions?.[economicsActionKey(alternateCallKind, item.amount)] || economics.actions?.[alternateCallKind]));
      if (override && Number.isFinite(override.ev)) {
        return { ...item, ev: override.ev, economicsSource: economics.source, exactEconomics: override.exact === true };
      }
      if (["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(item.kind)) {
        return { ...item, ev: -Infinity, eligible: false, exactEconomics: false, reason: "跨街或边池模型未覆盖该主动金额" };
      }
      return item;
    });
    const eligible = evaluated.filter(item => item.eligible !== false && Number.isFinite(item.ev));
    const best = eligible.reduce((winner, item) => !winner || item.ev > winner.ev ? item : winner, null);
    const bestPassive = eligible.filter(item => ["fold", "check", "call", "allin_call"].includes(item.kind))
      .reduce((winner, item) => !winner || item.ev > winner.ev ? item : winner, null);
    return { ...comparison, evaluated, best, bestPassive, decisionEconomics: economics };
  }
  function normalizePreflopRanges(rangeTypes) {
    const ranges = rangeTypes === undefined || rangeTypes === null ? ["random"] :
      (Array.isArray(rangeTypes) ? [...rangeTypes] : [rangeTypes]);
    if (!ranges.length) throw new Error("at least one opponent range is required");
    if (ranges.some(range => typeof range !== "string" && !(range && (range.allowed instanceof Set || Number.isFinite(range.strengthThreshold))) || typeof range === "string" && !range.trim())) throw new Error("opponent ranges must be named ranges, weighted thresholds or allowed-combo sets");
    return ranges.map(range => typeof range === "string" ? range.trim() : range);
  }
  const percentileRangeCache = new Map();
  function percentileOpponentRange(fraction) {
    const bounded = Math.max(.02, Math.min(1, Number(fraction) || 1)), key = bounded.toFixed(3);
    if (percentileRangeCache.has(key)) return percentileRangeCache.get(key);
    const deck = fullDeck(), combos = [];
    for (let first = 0; first < deck.length - 1; first++) for (let second = first + 1; second < deck.length; second++) {
      const cards = [deck[first], deck[second]], values = cards.map(cardValue).sort((left, right) => right - left),
        pair = values[0] === values[1], suited = cards[0][1] === cards[1][1], gap = values[0] - values[1],
        score = pair ? 70 + values[0] * 3 : values[0] * 3 + values[1] * 1.35 + (suited ? 3.5 : 0) + Math.max(0, 4 - gap) * 1.3 + (values[0] === 14 ? 2 : 0);
      combos.push({ cards, score });
    }
    combos.sort((left, right) => right.score - left.score || exactComboKey(left.cards).localeCompare(exactComboKey(right.cards)));
    const keep = Math.max(1, Math.ceil(combos.length * bounded)), range = { allowed: new Set(combos.slice(0, keep).map(item => exactComboKey(item.cards))), fraction: bounded, source: "preflop_combo_percentile" };
    percentileRangeCache.set(key, range); return range;
  }
  function validatePreflopTrials(trials) {
    const value = Number(trials);
    const normalized = Math.floor(value);
    if (!Number.isFinite(value) || normalized <= 0) throw new Error("trials must be a positive finite number");
    return normalized;
  }
  function preflopRealizationProfile({ hero, position = "unknown", players = 1, effective = 0, live = 1,
    pot = 0, call = 0, rakeRate = null, rakeCap = null, scenario = "unopened", candidate = {}, path = {}, unactedCount = 0 } = {}) {
    const heroCards = parseCards(hero, 2, 2), values = heroCards.map(cardValue).sort((left, right) => right - left),
      high = values[0], low = values[1], pair = high === low, suited = heroCards[0][1] === heroCards[1][1], gap = high - low,
      allIn = candidate.kind === "allin_call" || candidate.kind !== "call" ||
        Number(candidate.amount) >= Math.max(0, Number(effective) - 1e-9) || Number(call) <= 1e-9,
      positionFactor = ({dealer:.98, cutoff:.95, hijack:.90, middle:.85, under_the_gun_plus_one:.82,
        under_the_gun:.78, small_blind:.62, big_blind:.76, straddle:.65}[position] ?? .70),
      activeOpponents = Math.max(1, (path.activeSeats || []).length || Number(players) || 1),
      multiwayFactor = activeOpponents <= 1 ? .98 : activeOpponents === 2 ? .85 : activeOpponents === 3 ? .76 :
        activeOpponents === 4 ? .69 : .62,
      handFactor = pair ? high >= 11 ? .96 : high >= 8 ? .88 : .72 : suited ?
        (high >= 12 && low >= 10 ? .92 : gap <= 1 && high >= 8 ? .78 : high >= 11 ? .74 : .58) :
        (high >= 13 && low >= 10 ? .82 : gap <= 1 && high >= 10 ? .62 : high >= 12 ? .58 : .30),
      depthBb = Number(live) > 0 ? Number(effective) / Number(live) : Infinity,
      weakOffsuit = !pair && !suited && high < 12 && low < 10,
      speculative = !pair && (suited || gap <= 1) && high < 12,
      stackFactor = !Number.isFinite(depthBb) || allIn ? 1 : depthBb <= 20 ? (speculative ? .72 : .92) :
        depthBb <= 40 ? (speculative ? .84 : .95) : depthBb <= 100 ? 1 : weakOffsuit ? .78 : pair ? .90 : .96,
      scenarioFactor = ({unopened:1, limped:.95, raised:.82, raise_call:.78, reraised:.72}[scenario] ?? .80),
      priceRatio = Number(call) > 0 ? Number(call) / Math.max(.000001, Number(pot) + Number(call)) : 0,
      priceFactor = priceRatio >= .33 ? .75 : priceRatio >= .25 ? .82 : priceRatio >= .15 ? .90 : 1,
      futureActionFactor = allIn ? 1 : unactedCount <= 0 ? 1 : unactedCount === 1 ? .92 :
        unactedCount === 2 ? .86 : unactedCount === 3 ? .80 : .75,
      futureStreetFactor = allIn ? 1 : .85,
      factors = {position:positionFactor, multiway:multiwayFactor, handPlayability:handFactor,
        stackDepth:stackFactor, actionPressure:scenarioFactor, pricePressure:priceFactor,
        futureActionRisk:futureActionFactor, futureStreetRisk:futureStreetFactor},
      rawFactor = Object.values(factors).reduce((product, value) => product * value, 1),
      gateApplies = weakOffsuit || speculative,
      factor = !gateApplies ? 1 : pair || high >= 12 ? Math.max(.90, rawFactor) : rawFactor,
      requiredImmediate = Number(call) > 0 ? Number(call) /
        Math.max(.000001, finalPotAfterRake(Number(pot) + Number(call), rakeRate, rakeCap)) : 0,
      safetyMargin = allIn ? 0 : Number(call) > 0 ? .02 : 0,
      requiredWithSafety = requiredImmediate + safetyMargin;
    return {applied:!allIn && candidate.kind === "call" && Number(call) > 0, allIn, activeOpponents,
      weakOffsuit, speculative, gateApplies,
      depthBb:Number.isFinite(depthBb) ? depthBb : null, factors, rawFactor, factor, requiredImmediate,
      safetyMargin, requiredWithSafety, source:"preflop_realization_v1"};
  }
  function trainingDecisionValue({ equity, pot = 0, call = 0, rakeRate = null, rakeCap = null,
    players = 1, position = "unknown", effectiveStack = Infinity, bigBlind = 0,
    actionChainReliable = true, rangeReliable = true, confidence = 1, street = "river", allIn = false } = {}) {
    const rawEquity = Number(equity), currentPot = Number(pot), callAmount = Number(call);
    if (equity === null || equity === undefined || equity === "" || pot === null || pot === undefined ||
        call === null || call === undefined || call === "" || !Number.isFinite(rawEquity) ||
        !Number.isFinite(currentPot) || currentPot < 0 || !Number.isFinite(callAmount) || callAmount <= 0)
      return { ready: false, reason: "底池或跟注金额尚未确认" };
    const opponentCount = Math.max(1, Math.floor(Number(players) || 1));
    const multiway = opponentCount <= 1 ? 1 : opponentCount === 2 ? .90 : .82;
    const inPosition = ["dealer", "cutoff", "hijack"].includes(position);
    const positionFactor = inPosition ? 1 : .94;
    const depthBb = Number(bigBlind) > 0 && Number.isFinite(Number(effectiveStack)) ?
      Number(effectiveStack) / Number(bigBlind) : Infinity;
    const stackFactor = Number.isFinite(depthBb) && depthBb <= 20 && street !== "river" && !allIn ? .97 : 1;
    const actionFactor = actionChainReliable ? 1 : .95;
    const rangeFactor = rangeReliable ? 1 : .92;
    const realizationFactor = multiway * positionFactor * stackFactor * actionFactor * rangeFactor;
    const grossPot = currentPot + callAmount;
    const netPot = finalPotAfterRake(grossPot, rakeRate, rakeCap);
    const requiredImmediate = callAmount / Math.max(.000001, netPot);
    const certainty = Number(confidence);
    const uncertaintyMargin = certainty >= .90 ? .01 : certainty >= .85 ? .03 : .05;
    const safetyMargin = allIn || street === "river" ? 0 : uncertaintyMargin;
    const finalThreshold = requiredImmediate + safetyMargin;
    const effectiveEquity = Math.max(0, Math.min(1, rawEquity * realizationFactor));
    const difference = effectiveEquity - finalThreshold;
    const conclusion = difference >= .02 ? "有效权益高于最终门槛，倾向跟注" :
      difference <= -.02 ? "有效权益低于最终门槛，倾向弃牌" : "接近最终门槛，属于临界决定";
    return { ready: true, rawEquity: Math.max(0, Math.min(1, rawEquity)), effectiveEquity,
      realizationFactor, factors: { multiway, position: positionFactor, stack: stackFactor,
      actionChain: actionFactor, range: rangeFactor }, requiredImmediate, uncertaintyMargin, safetyMargin,
      finalThreshold, difference, conclusion, netPot, depthBb: Number.isFinite(depthBb) ? depthBb : null,
      source: "training_effective_equity_v1" };
  }
  function analyzePreflopEquity(hero, rangeTypes = ["random"], trials = 6000) {
    const heroCards = parseCards(hero, 2, 2);
    const ranges = normalizePreflopRanges(rangeTypes);
    const requestedTrials = validatePreflopTrials(trials);
    const result = ranges.length === 1
      ? analyzeEquity(heroCards, [], ranges[0], requestedTrials)
      : analyzeMultiway(heroCards, [], ranges, requestedTrials);
    if (!Number.isFinite(result.equity) || !Number.isFinite(result.samples) || result.samples <= 0) {
      throw new Error("preflop equity simulation produced no accepted samples");
    }
    return {
      ...result,
      street: "preflop",
      equitySource: "monte_carlo",
      futureStreetSolved: false,
      futureStreetEVSolved: false,
      opponents: ranges.length,
      opponentRangeTypes: ranges,
      trialsRequested: requestedTrials,
      acceptedSamples: result.samples,
    };
  }
  function seededPreflopEquity(hero, rangeTypes, trials, seed = "preflop") {
    const heroCards=parseCards(hero,2,2),ranges=normalizePreflopRanges(rangeTypes),known=new Set(heroCards),baseDeck=fullDeck().filter(card=>!known.has(card));let value=2166136261;
    for(const character of String(seed)){value^=character.charCodeAt(0);value=Math.imul(value,16777619)}
    const random=()=>{value+=0x6D2B79F5;let mixed=value;mixed=Math.imul(mixed^mixed>>>15,mixed|1);mixed^=mixed+Math.imul(mixed^mixed>>>7,mixed|61);return((mixed^mixed>>>14)>>>0)/4294967296};
    let share=0,accepted=0,attempts=0;const requested=validatePreflopTrials(trials);
    while(accepted<requested&&attempts<requested*80){attempts++;const deck=[...baseDeck],villains=[];let cursor=0,valid=true;
      for(const range of ranges){let found=false;for(let tries=0;tries<40&&cursor+1<deck.length;tries++){const first=cursor+Math.floor(random()*(deck.length-cursor));[deck[cursor],deck[first]]=[deck[first],deck[cursor]];const second=cursor+1+Math.floor(random()*(deck.length-cursor-1));[deck[cursor+1],deck[second]]=[deck[second],deck[cursor+1]];const hand=[deck[cursor],deck[cursor+1]];if(inRange(hand,range)){villains.push(hand);cursor+=2;found=true;break}}if(!found){valid=false;break}}
      if(!valid)continue;const remaining=deck.slice(cursor);for(let index=0;index<5;index++){const pick=index+Math.floor(random()*(remaining.length-index));[remaining[index],remaining[pick]]=[remaining[pick],remaining[index]]}const board=remaining.slice(0,5),heroRank=evaluate([...heroCards,...board]),villainRanks=villains.map(hand=>evaluate([...hand,...board])),all=[heroRank,...villainRanks],best=all.reduce((winner,item)=>compareRanks(item,winner)>0?item:winner,all[0]),winners=all.filter(item=>compareRanks(item,best)===0);if(compareRanks(heroRank,best)===0)share+=1/winners.length;accepted++}
    if(!accepted)throw new Error("seeded preflop equity produced no samples");return{equity:share/accepted,samples:accepted,acceptedSamples:accepted,trialsRequested:requested,opponents:ranges.length,opponentRangeTypes:ranges,equitySource:"seeded_monte_carlo",street:"preflop",futureStreetSolved:false,futureStreetEVSolved:false};
  }
  function callerSubsets(values, size) {
    const result = [];
    const visit = (start, selected) => {
      if (selected.length === size) { result.push([...selected]); return; }
      for (let index = start; index <= values.length - (size - selected.length); index++) {
        selected.push(values[index]); visit(index + 1, selected); selected.pop();
      }
    };
    visit(0, []);
    return result;
  }
  function analyzeEquityByCallerCount(hero, board, rangeTypes, trials = 1200) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 0, 5);
    const ranges = normalizePreflopRanges(rangeTypes), result = {};
    for (let count = 1; count <= ranges.length; count++) {
      const subsets = callerSubsets(ranges, count);
      const perSubset = Math.max(120, Math.floor(Number(trials) / subsets.length));
      const equities = subsets.map(subset => count === 1
        ? analyzeEquity(heroCards, boardCards, subset[0], perSubset).equity
        : analyzeMultiway(heroCards, boardCards, subset, perSubset).equity);
      result[String(count)] = equities.reduce((sum, value) => sum + value, 0) / equities.length;
    }
    return result;
  }
  function conditionalContinueRange(hero, board, baseType, continueFraction) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 0, 5);
    const known = new Set([...heroCards, ...boardCards]);
    const deck = fullDeck().filter(card => !known.has(card));
    const candidates = [];
    for (let first = 0; first < deck.length - 1; first++) for (let second = first + 1; second < deck.length; second++) {
      const cards = [deck[first], deck[second]];
      if (!inRange(cards, baseType)) continue;
      const rank = boardCards.length >= 3 ? evaluate([...cards, ...boardCards]) : [0];
      const values = cards.map(cardValue).sort((a, b) => b - a);
      const pair = values[0] === values[1] ? 1 : 0;
      const suited = cards[0][1] === cards[1][1] ? 1 : 0;
      const gap = values[0] - values[1];
      const preflopStrength = pair ? 40 + values[0] * 3 : values[0] * 2 + values[1] + suited * 4 - gap;
      candidates.push({ cards, rank, preflopStrength });
    }
    candidates.sort((left, right) => {
      if (boardCards.length >= 3) {
        const compared = compareRanks(right.rank, left.rank);
        if (compared) return compared;
      }
      return right.preflopStrength - left.preflopStrength;
    });
    const fraction = Math.max(.01, Math.min(1, Number(continueFraction)));
    const keep = Math.max(1, Math.ceil(candidates.length * fraction));
    return { allowed: new Set(candidates.slice(0, keep).map(item => exactComboKey(item.cards))),
      baseType, continueFraction: fraction, combinations: candidates.length, keptCombinations: keep };
  }
  function analyzeConditionalEquityByCallerCount(hero, board, rangeTypes, continueFraction, trials = 1200) {
    const heroCards = parseCards(hero, 2, 2), boardCards = parseCards(board, 0, 5);
    const ranges = normalizePreflopRanges(rangeTypes);
    const conditional = ranges.map(range => conditionalContinueRange(
      heroCards, boardCards, range, continueFraction));
    const result = {};
    for (let count = 1; count <= conditional.length; count++) {
      const subsets = callerSubsets(conditional, count);
      const perSubset = Math.max(120, Math.floor(Number(trials) / subsets.length));
      const equities = subsets.map(subset => count === 1
        ? analyzeEquity(heroCards, boardCards, subset[0], perSubset).equity
        : analyzeMultiway(heroCards, boardCards, subset, perSubset).equity);
      result[String(count)] = equities.reduce((sum, value) => sum + value, 0) / equities.length;
    }
    return { equityByCallers: result, continueFraction: Math.max(.01, Math.min(1, Number(continueFraction))),
      source: "conditional_continue_range_model",
      rangeSizes: conditional.map(item => ({ baseType: item.baseType,
        combinations: item.combinations, keptCombinations: item.keptCombinations })) };
  }
  function comparePreflopActions(options = {}) {
    if (!options || typeof options !== "object" || Array.isArray(options)) throw new Error("options object is required");
    if (Object.prototype.hasOwnProperty.call(options, "board")) {
      throw new Error("comparePreflopActions does not accept a board");
    }
    const heroCards = parseCards(options.hero, 2, 2);
    const ranges = normalizePreflopRanges(options.rangeTypes ?? options.opponentRangeTypes ?? options.opponentRanges);
    const players = options.players === undefined ? ranges.length : Number(options.players);
    if (!Number.isFinite(players) || players < 1) throw new Error("players must be at least one opponent");
    const supplied = options.equity !== undefined && options.equity !== null;
    let equityResult = null;
    let equity;
    if (supplied) {
      equity = Number(options.equity);
      if (!Number.isFinite(equity) || equity < 0 || equity > 1) throw new Error("equity must be a number between 0 and 1");
    } else {
      equityResult = analyzePreflopEquity(heroCards, ranges, options.trials === undefined ? 6000 : options.trials);
      equity = equityResult.equity;
    }
    const comparison = compareLegalActions({
      candidates: options.candidates,
      buttons: options.buttons,
      pot: options.pot,
      call: options.call,
      effective: options.effective,
      equity,
      players,
      rakeRate: options.rakeRate,
      rakeCap: options.rakeCap,
      reactions: options.reactions,
      improvementProbability: options.improvementProbability,
      protectionGain: options.protectionGain,
      semiBluffMinImprovement: options.semiBluffMinImprovement,
      freeRaiseAmounts: options.freeRaiseAmounts,
      minRaiseTo: options.minRaiseTo,
      allInCall: options.allInCall,
      includeAllIn: options.includeAllIn,
      requireConditionalEquity: options.requireConditionalEquity,
    });
    return {
      ...comparison,
      equity,
      equitySource: supplied ? "provided" : "monte_carlo",
      equityResult,
      street: "preflop",
      futureStreetSolved: false,
      futureStreetEVSolved: false,
      opponents: ranges.length,
      opponentRangeTypes: ranges,
      samples: equityResult ? equityResult.samples : null,
    };
  }
  function comparePreflopScenarioActions(options = {}) {
    if (!PREFLOP) throw new Error("preflop participation model is unavailable");
    const context = options.scenarioContext || {}, participants = PREFLOP.scenarioParticipants(context);
    if (!participants.valid) throw new Error(participants.reason || "invalid preflop scenario");
    const heroCards = parseCards(options.hero, 2, 2), pot = Math.max(0, Number(options.pot) || 0),
       effective = Math.max(0, Number(options.effective) || 0), call = Math.max(0, Number(options.call) || 0),
       posted = Math.max(0, Number(context.posted) || 0), currentPrice = Math.max(posted + call, Number(context.currentPrice) || 0),
       liveValue = Number(context.live), live = Number.isFinite(liveValue) && liveValue > 0 ? liveValue : 1,
       players = Math.max(1, Number(options.players) || Number(context.players) || participants.committed.length + participants.unacted.length),
       trials = validatePreflopTrials(options.trials === undefined ? 300 : options.trials),
      participantBySeat = new Map([...participants.committed, ...participants.unacted].map(item => [Number(item.seat), item])),
      equityCache = new Map(), aggressiveKinds = new Set(["quick_bet", "custom_raise", "minimum_raise", "allin"]);
    const rangeTypeFor = (participant, action, mode) => {
      const roleFraction = action === "raise" || participant.role === "reraiser" || participant.role === "allin" ? .08 :
        mode === "aggressive" && action === "call" ? .18 : participant.role === "raiser" ? .20 :
          participant.role === "caller" ? .28 : participant.role === "forced_straddle" ? .36 : .30;
      const threshold = Number(participant.rangeType?.strengthThreshold), profileFraction = Number.isFinite(threshold)
        ? threshold >= 43 ? .30 - (threshold - 43) / 12 * .12 : .30 + (43 - threshold) / 9 * .12
        : ({tight:.18,medium:.30,loose:.42})[participant.rangeType];
      return percentileOpponentRange(Number.isFinite(profileFraction)
        ? Math.max(.02, Math.min(1, roleFraction * .75 + profileFraction * .25)) : roleFraction);
    };
    const equityInput = (path, mode) => {
      const actionBySeat = new Map((path.responses || []).map(item => [Number(item.seat), item.action]));
      const ranges = (path.activeSeats || []).map(seat => rangeTypeFor(participantBySeat.get(Number(seat)) || {}, actionBySeat.get(Number(seat)), mode)).sort();
      const key = ranges.map(range => range.fraction).join(",");
      return {key, ranges};
    };
    const estimatedResponseTree = candidate => {
      const estimate = typeof options.reactions === "function" ? options.reactions(candidate) : reactionFor(options.reactions, candidate);
      if (!estimate || estimate.reliable !== true || !Array.isArray(estimate.paths) || !estimate.paths.length) return null;
      const lockedSeats = participants.committed.filter(item => item.role === "allin").map(item => Number(item.seat)), paths = [];
      for (const rawPath of estimate.paths) {
        const probability = Math.max(0, Number(rawPath.probability) || 0), responses = (rawPath.responses || []).filter(item => participantBySeat.has(Number(item.seat)) && !lockedSeats.includes(Number(item.seat)));
        if (!probability) continue;
        const activeSeats = [...new Set([...lockedSeats, ...responses.filter(item => item.action !== "fold").map(item => Number(item.seat))])];
        const raised = responses.some(item => item.action === "raise"), outcome = raised ? "raise" : activeSeats.length ? "call" : "fold";
        paths.push({probability, responses, activeSeats, outcome, callers:activeSeats.length});
      }
      const pruned = Math.max(0, Number(estimate.prunedPathProbability) || 0);
      if (pruned) paths.push({probability:pruned,responses:[],activeSeats:[...lockedSeats],outcome:"raise",callers:lockedSeats.length,pruned:true});
      const total = paths.reduce((sum,path)=>sum+path.probability,0);
      if (total <= 0) return null;
      const normalized = paths.map(path=>({...path,probability:path.probability/total})), probabilities={fold:0,call:0,raise:0}, callCountDistribution={};
      normalized.forEach(path=>{probabilities[path.outcome]+=path.probability;if(path.outcome==="call")callCountDistribution[path.callers]=(callCountDistribution[path.callers]||0)+path.probability});
      const callTotal=probabilities.call||1;Object.keys(callCountDistribution).forEach(key=>callCountDistribution[key]/=callTotal);
      return{sequential:true,source:"observed_ordered_reactions",sampleCount:estimate.sampleCount,populationSampleCount:estimate.populationSampleCount,lockedSeats,orderedSeats:estimate.orderedSeats||[],probabilities,callCountDistribution,paths:normalized,prunedProbability:pruned/total,prunedAs:pruned?"raise_conservative":null,exploitWeight:Number.isFinite(Number(estimate.exploitWeight))?Math.max(0,Math.min(1,Number(estimate.exploitWeight))):1,policy:estimate.policy||null};
    };
    const priorResponseTree = (candidate, mode) => {
      const heroTo = posted + Math.max(0, Number(candidate.amount) || 0), increase = Math.max(0, heroTo - currentPrice),
        sizeRatio = increase / Math.max(.000001, pot), allin=participants.committed.filter(item=>item.role==="allin"), responsiveCommitted=participants.committed.filter(item=>item.role!=="allin"), passiveLocked=participants.committed.filter(item=>item.role==="allin"||Number(item.invested)>=currentPrice-1e-9), passiveResponders=responsiveCommitted.filter(item=>Number(item.invested)<currentPrice-1e-9), responders = mode === "passive" ? [...participants.unacted,...passiveResponders] : [...participants.unacted, ...responsiveCommitted];
      const tree=PREFLOP.continuationTree({locked:mode === "passive" ? passiveLocked : allin, responders, maxPaths:64,
        responseFor:participant => PREFLOP.responsePrior(participant, {mode, sizeRatio, priceIncrease:Math.max(0, currentPrice - Number(participant.invested || 0))})});
      return{...tree,source:"position_role_prior"};
    };
    const blendResponseTrees = (prior, observed) => {
      const weight=observed.exploitWeight;
      if(weight>=1-1e-9)return observed;
      const paths=[...prior.paths.map(path=>({...path,probability:path.probability*(1-weight)})),
        ...observed.paths.map(path=>({...path,probability:path.probability*weight}))],probabilities={fold:0,call:0,raise:0},callCountDistribution={};
      for(const path of paths){probabilities[path.outcome]+=path.probability;if(path.outcome==="call")callCountDistribution[path.callers]=(callCountDistribution[path.callers]||0)+path.probability}
      const callTotal=probabilities.call||1;Object.keys(callCountDistribution).forEach(key=>callCountDistribution[key]/=callTotal);
      return{...observed,source:observed.policy?.coldStart?"population_cold_start_blend":"profile_reaction_blend",paths,probabilities,callCountDistribution,priorWeight:1-weight,exploitWeight:weight};
    };
    const responseTree = (candidate, mode) => {
      const estimated=estimatedResponseTree(candidate);
      const prior=priorResponseTree(candidate,mode);
      return estimated?blendResponseTrees(prior,estimated):prior;
    };
    const treeByCandidate = new Map(), uniqueEquityInputs = new Map();
    for (const candidate of options.candidates || []) {
      if (candidate.kind === "fold") continue;
      const mode = aggressiveKinds.has(candidate.kind) ? "aggressive" : "passive", tree = responseTree(candidate, mode);
      treeByCandidate.set(candidate, tree);
      for (const path of tree.paths) {
        if (path.outcome === "fold") continue;
        const input = equityInput(path, mode);
        if (input.ranges.length) uniqueEquityInputs.set(input.key, input.ranges);
      }
    }
    const trialsPerEquityInput = Math.max(80, Math.floor(trials / Math.max(1, uniqueEquityInputs.size)));
    for (const [key, ranges] of uniqueEquityInputs) {
      equityCache.set(key, seededPreflopEquity(heroCards, ranges, trialsPerEquityInput, `${heroCards.join("")}:${key}`).equity);
    }
    const equityFor = (path, mode) => {
      const input = equityInput(path, mode);
      return input.ranges.length ? equityCache.get(input.key) : 1;
    };
    const evaluatePath = (path, candidate, mode) => {
      const investment = Math.max(0, Number(candidate.amount) || 0), heroTo = posted + investment,
        actionBySeat = new Map((path.responses || []).map(item => [Number(item.seat), item.action]));
      if (path.outcome === "fold") return pot;
      const raised = path.outcome === "raise", raiseTo = Math.min(posted + effective, Math.max(heroTo * 2.2, heroTo + live)),
        opponentAdded = (path.activeSeats || []).reduce((sum, seat) => {
          const participant = participantBySeat.get(Number(seat)) || {}, target = actionBySeat.get(Number(seat)) === "raise" ? raiseTo : heroTo;
          return sum + Math.max(0, target - Math.max(0, Number(participant.invested) || 0));
         }, 0), equity = equityFor(path, mode), realization = preflopRealizationProfile({
           hero:heroCards, position:context.position, players, effective, live, pot, call,
           rakeRate:options.rakeRate, rakeCap:options.rakeCap, scenario:context.scenario, candidate, path,
           unactedCount:(participants.unacted || []).length,
         }), effectiveEquity = equity * (realization.applied && realization.gateApplies ? realization.factor : 1);
       if (!raised) return effectiveEquity * finalPotAfterRake(pot + investment + opponentAdded, options.rakeRate, options.rakeCap) - investment;
      const heroExtra = Math.max(0, raiseTo - heroTo), foldValue = -investment,
        continueValue = equity * finalPotAfterRake(pot + investment + opponentAdded + heroExtra, options.rakeRate, options.rakeCap) - investment - heroExtra;
      return Math.max(foldValue, continueValue);
    };
    const evaluated = (options.candidates || []).map(candidate => {
      if (candidate.kind === "fold") return {...candidate, ev:0, eligible:true, branchModel:"preflop_participation_v1"};
      const investment = Number(candidate.amount) || 0;
      if (candidate.kind === "check" && call > 1e-9) return {...candidate, ev:null, eligible:false, reason:"check_is_illegal_when_facing_bet"};
      if (["call", "allin_call"].includes(candidate.kind) && investment + 1e-9 < call) return {...candidate, ev:null, eligible:false, reason:"call_amount_below_price"};
      if (aggressiveKinds.has(candidate.kind) && (investment <= call + 1e-9 || investment > effective + 1e-9)) return {...candidate, ev:null, eligible:false, reason:"raise_amount_illegal"};
      const mode = aggressiveKinds.has(candidate.kind) ? "aggressive" : "passive", tree = treeByCandidate.get(candidate) || responseTree(candidate, mode);
       let callProbability = 0, callValue = 0, equityProbability = 0, weightedEquity = 0,
         weightedEffectiveEquity = 0, weightedRealizationFactor = 0, realizationWeight = 0, realizationParts = {};
       const ev = tree.paths.reduce((sum, path) => { const pathValue=evaluatePath(path,candidate,mode),rawEquity=equityFor(path,mode),profile=preflopRealizationProfile({
         hero:heroCards,position:context.position,players,effective,live,pot,call,rakeRate:options.rakeRate,rakeCap:options.rakeCap,
          scenario:context.scenario,candidate,path,unactedCount:(participants.unacted || []).length});if(path.outcome!=="fold"){equityProbability+=path.probability;weightedEquity+=path.probability*rawEquity;realizationWeight+=path.probability;weightedEffectiveEquity+=path.probability*rawEquity*(profile.applied&&profile.gateApplies?profile.factor:1);weightedRealizationFactor+=path.probability*(profile.applied&&profile.gateApplies?profile.factor:1);Object.entries(profile.factors).forEach(([key,value])=>{realizationParts[key]=(realizationParts[key]||0)+path.probability*value})}if(path.outcome==="call"){callProbability+=path.probability;callValue+=path.probability*pathValue}return sum+path.probability*pathValue; }, 0);
       const calledPathEV=callProbability>0?callValue/callProbability:null;
       const equity=equityProbability>0?weightedEquity/equityProbability:null,
         effectiveEquity=realizationWeight>0?weightedEffectiveEquity/realizationWeight:null,
         realizationFactor=realizationWeight>0?weightedRealizationFactor/realizationWeight:1,
         realizationBreakdown=Object.fromEntries(Object.entries(realizationParts).map(([key,value])=>[key,value/realizationWeight])),
          realization=preflopRealizationProfile({hero:heroCards,position:context.position,players,effective,live,pot,call,rakeRate:options.rakeRate,rakeCap:options.rakeCap,scenario:context.scenario,candidate,path:tree.paths.find(path=>path.outcome!=="fold")||{},unactedCount:(participants.unacted || []).length}),
         requiredWithSafety=realization.requiredWithSafety,
         realizationGate=!(candidate.kind === "call" && call > 0 && realization.applied && realization.gateApplies) || Number(effectiveEquity) >= requiredWithSafety - 1e-9;
       return {...candidate, ev, eligible:Number.isFinite(ev), responseTree:tree, branchModel:"preflop_participation_v1",
         calledPathEV, equity, effectiveEquity, realizationFactor, realizationBreakdown,
         requiredImmediate:realization.requiredImmediate, safetyMargin:realization.safetyMargin, requiredWithSafety,
         realizationGate, realizationSource:realization.source,
         participantAudit:{committed:participants.committed.map(item => ({position:item.position,role:item.role})),unacted:participants.unacted.map(item => item.position)}};
    });
      const tolerance=Math.max(.05,pot*.05);
    evaluated.forEach(item=>{if(item.kind!=="allin"||item.responseTree?.source==="observed_ordered_reactions")return;const totalStack=posted+effective,totalCommitted=posted+call,shortStack=Number(item.amount)<=live*10,deeplyCommitted=totalStack>0&&totalCommitted/totalStack>=.25,lowSpr=pot>0&&effective/pot<=1;if(!shortStack&&!deeplyCommitted&&!lowSpr){item.selectionEligible=false;item.riskGateReason="当前筹码深度下，全下被跟注后的结果样本不足"}});
      evaluated.forEach(item=>{if(item.realizationGate===false){item.selectionEligible=false;item.riskGateReason=`兑现后有效权益低于实战门槛（${(Number(item.effectiveEquity)*100).toFixed(1)}% < ${(Number(item.requiredWithSafety)*100).toFixed(1)}%）`}});
      const passiveBest=evaluated.filter(item=>["fold","check","call","allin_call"].includes(item.kind)&&item.eligible&&item.selectionEligible!==false&&Number.isFinite(item.ev)).reduce((winner,item)=>!winner||item.ev>winner.ev?item:winner,null);
      evaluated.forEach(item=>{if(!aggressiveKinds.has(item.kind)||!item.eligible||!Number.isFinite(passiveBest?.ev))return;const valueEdge=Number(item.calledPathEV)-passiveBest.ev;if(!Number.isFinite(valueEdge)||valueEdge<tolerance){item.selectionEligible=false;item.riskGateReason="被跟注后的价值没有超过最佳保守动作";return}item.classification="价值加注";item.classificationEvidence={source:"preflop_called_path_value_edge",calledPathEV:item.calledPathEV,bestPassiveEV:passiveBest.ev,calledValueEdge:valueEdge,engineeringTolerance:tolerance}});
    const best = evaluated.filter(item => item.eligible && item.selectionEligible!==false && Number.isFinite(item.ev)).reduce((winner, item) => !winner || item.ev > winner.ev ? item : winner, null);
    const equity = evaluated.find(item => ["check", "call", "allin_call"].includes(item.kind) && Number.isFinite(item.equity))?.equity ?? best?.equity ?? null;
    return {best, evaluated, equity, source:"scenario_branch_ev", participants, opponents:null,
      samples:uniqueEquityInputs.size * trialsPerEquityInput,
      equityInputCount:uniqueEquityInputs.size, trialsPerEquityInput,
      street:"preflop", futureStreetSolved:false, futureStreetEVSolved:false};
  }
  function comparePreflopRangeCell(options = {}) {
    const base = preflopAdvice(
      options.hero, options.position, options.call || 0, options.players || 8,
      options.opponentProfiles || [], options.pot || 0, options.effective,
      options.raiseCount || 0,
    );
    const comparison = options.scenarioContext ? comparePreflopScenarioActions(options) : comparePreflopActions({
      hero: options.hero,
      candidates: options.candidates,
      pot: options.pot,
      call: options.call || 0,
      effective: options.effective,
      rangeTypes: options.rangeTypes,
      players: Math.max(1, (options.players || 2) - 1),
      rakeRate: options.rakeRate,
      rakeCap: options.rakeCap,
      reactions: options.reactions,
      trials: options.trials === undefined ? 300 : options.trials,
    });
    const aggressiveKinds = new Set(["quick_bet", "custom_raise", "minimum_raise", "allin"]);
    const best = comparison.best, source = options.scenarioContext ? "scenario_branch_ev" : "unified_ev";
    const primary = !best ? null : aggressiveKinds.has(best.kind) ? "加注" :
      ["call", "allin_call"].includes(best.kind) ? "跟注" :
      best.kind === "fold" ? "弃牌" : best.kind === "check" ? "让牌" : null;
    return { primary, source, base, best, comparison };
  }
  function actionSituation({ street = "preflop", action, priorActions = [], handActions = [], heroSeat = null, heroPosition = "unknown", preflopRaiseCount = 0 } = {}) {
    const normalize = (item, fallbackStreet = street) => typeof item === "string"
      ? { action:item, street:fallbackStreet, seat:null }
      : { action:item?.action, street:item?.street || fallbackStreet, seat:Number(item?.seat) || null };
    const current = priorActions.map(item => normalize(item)).filter(item => item.action);
    const hand = (handActions.length ? handActions : priorActions).map(item => normalize(item)).filter(item => item.action);
    const prior = current.map(item => item.action);
    const voluntary = prior.filter(item => !["blind", "post_blind", "straddle", "check", "fold"].includes(item));
    const observedRaises = prior.filter(item => ["raise", "reraise"].includes(item)).length;
    const raises = Math.max(observedRaises, Number(preflopRaiseCount) || 0);
    const firstRaise = prior.findIndex(item => ["raise", "reraise"].includes(item));
    const callsAfterRaise = firstRaise >= 0 && prior.slice(firstRaise + 1).some(item => item === "call");
    const heroCallIndex = Number.isInteger(heroSeat)
      ? current.findIndex(item => item.seat === heroSeat && item.action === "call")
      : -1;
    const heroLimped = heroCallIndex >= 0 && (firstRaise < 0 || heroCallIndex < firstRaise);
    if (street === "preflop" && ["raise", "reraise", "bet", "allin"].includes(action)) {
      if (heroLimped && raises > 0) return "Limp-reraise";
      if (raises > 2) return "再次加注";
      if (raises === 2) return "4下注";
      if (raises === 1 && callsAfterRaise) return "挤压加注";
      if (raises === 1) return "3下注";
      if (voluntary.some(item => item === "call")) return "隔离加注";
      if (["dealer", "cutoff"].includes(heroPosition)) return "偷盲开局加注";
      return "开局加注";
    }
    if (street === "preflop" && action === "call") {
      if (heroPosition === "big_blind" && raises > 0) return "大盲防守";
      if (raises > 0) return "冷跟";
      if (prior.includes("straddle")) return "跟注Straddle";
      return "Limp";
    }
    const aggressive = item => ["bet", "raise", "reraise", "allin"].includes(item.action);
    const streets = ["preflop", "flop", "turn", "river"];
    const streetIndex = streets.indexOf(street);
    const previousStreet = streetIndex > 0 ? streets[streetIndex - 1] : null;
    const preflopAggressor = [...hand].reverse().find(item => item.street === "preflop" && aggressive(item))?.seat;
    const previousAggressor = [...hand].reverse().find(item => item.street === previousStreet && aggressive(item))?.seat;
    const enteringAggressor = previousAggressor ?? preflopAggressor;
    const currentAggression = current.filter(aggressive);
    const heroChecked = Number.isInteger(heroSeat) && current.some(item => item.seat === heroSeat && item.action === "check");
    if (street !== "preflop" && ["bet", "raise", "reraise", "allin"].includes(action)) {
      if (heroChecked && currentAggression.length) return "过牌加注";
      if (currentAggression.length) return "再次加注";
      if (!currentAggression.length && street === "flop" && preflopAggressor === heroSeat) return "持续下注";
      const flopEvents = hand.filter(item => item.street === "flop");
      const heroCheckedFlop = Number.isInteger(heroSeat) && flopEvents.some(item => item.seat === heroSeat && item.action === "check");
      if (!currentAggression.length && street === "turn" && preflopAggressor === heroSeat && heroCheckedFlop && !flopEvents.some(aggressive)) return "延迟持续下注";
      const priorAggressorChecked = Number.isInteger(enteringAggressor) && hand.some(item => item.street === previousStreet && item.seat === enteringAggressor && item.action === "check");
      if (!currentAggression.length && enteringAggressor !== heroSeat && priorAggressorChecked) return "探路下注";
      if (!currentAggression.length && street === "flop" && preflopAggressor !== heroSeat) return "领先下注";
      if (!currentAggression.length && enteringAggressor !== heroSeat) return "反主动下注";
      return "主动下注";
    }
    if (street !== "preflop" && action === "call" && currentAggression.length) return "面对下注跟注";
    if (street !== "preflop" && action === "fold" && currentAggression.length) return "面对下注弃牌";
    if (street !== "preflop" && action === "check") return heroPosition === "dealer" ? "后位过牌" : "让牌";
    return null;
  }
  function platformAmount(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric === 0) return numeric;
    const magnitude = Math.floor(Math.log10(Math.abs(numeric)));
    const precision = Math.pow(10, 1 - magnitude);
    return Math.round(numeric * precision) / precision;
  }
  function actionCandidates(buttons, { pot = 0, call = 0, effective = Infinity, minRaiseTo = null, allInCall = false, freeRaiseAmounts = [], includeAllIn = true } = {}) {
    const source = Array.isArray(buttons) ? buttons : [];
    const hasFold = source.some(button => button.kind === "fold");
    const detectedAllInCall = allInCall || hasFold && source.some(button =>
      button.kind === "allin_call" ||
      (button.kind === "call" && (button.value === "allin" || /all\s*-?\s*in|全下/i.test(String(button.text || ""))))
    );
    const numericCall = Number.isFinite(call) ? Math.max(0, call) : null;
    const result = [];
    const monetary = amount => Math.min(effective, platformAmount(amount));
    const add = candidate => {
      const duplicate = result.some(item => item.action === candidate.action &&
        (Number.isFinite(item.amount) && Number.isFinite(candidate.amount)
          ? Math.abs(item.amount - candidate.amount) < .000001
          : item.kind === candidate.kind));
      if (!duplicate) result.push(candidate);
    };
    for (const button of source) {
      if (button.kind === "fold") add({ action: "弃牌", kind: "fold", amount: 0, button });
      else if (button.kind === "check") add({ action: "让牌", kind: "check", amount: 0, button });
      else if (button.kind === "call" && !detectedAllInCall) {
        const amount = Number.isFinite(button.value) ? button.value : numericCall;
        if (Number.isFinite(amount)) add({ action: "跟注", kind: "call", amount, button });
      } else if ((button.kind === "call" || button.kind === "allin_call") && detectedAllInCall) {
        if (Number.isFinite(effective) && effective >= 0) add({ action: "全下跟注", kind: "allin_call", amount: effective, button });
      } else if (button.kind === "allin" && detectedAllInCall) {
        if (Number.isFinite(effective) && effective >= 0) add({ action: "全下跟注", kind: "allin_call", amount: effective, button });
      } else if (button.kind === "allin") {
        if (Number.isFinite(effective) && effective > numericCall) add({ action: "全下", kind: "allin", amount: effective, button });
      } else if (button.kind === "quick_bet" && Number.isFinite(button.value) && numericCall !== null) {
        const amount = monetary(numericCall + (pot + numericCall) * button.value);
        if (Number.isFinite(amount) && (!Number.isFinite(minRaiseTo) || amount >= minRaiseTo || amount === effective)) add({ action: numericCall <= .000001 ? "下注" : "加注", kind: "quick_bet", amount, ratio: button.value, button });
      }
    }
    const raiseButton = source.find(button => button.kind === "custom_raise");
    if (raiseButton && !detectedAllInCall) {
      const amounts = [...new Set([minRaiseTo, ...freeRaiseAmounts]
        .filter(amount => Number.isFinite(amount) && amount <= effective)
        .map(monetary))].sort((a, b) => a - b);
      for (const amount of amounts) {
        if (amount > numericCall && amount <= effective && (!Number.isFinite(minRaiseTo) || amount >= minRaiseTo)) {
          add({ action: numericCall <= .000001 ? "下注" : "加注", kind: amount === minRaiseTo ? "minimum_raise" : "custom_raise", amount, button: raiseButton });
        }
      }
      if (!amounts.length && raiseButton.kind === "custom_raise") add({ action: "加注", kind: "custom_raise", amount: null, button: raiseButton });
      if (includeAllIn && Number.isFinite(effective) && effective > numericCall) add({ action: "全下", kind: "allin", amount: effective, button: raiseButton });
    }
    return result;
  }
  function finalPotAfterRake(grossPot, rakeRate, rakeCap) {
    if (!Number.isFinite(rakeRate) || rakeRate < 0) return grossPot;
    return grossPot - Math.min(grossPot * rakeRate, Number.isFinite(rakeCap) ? rakeCap : Infinity);
  }
  function reactionFor(reactions, candidate) {
    if (typeof reactions === "function") return reactions(candidate);
    if (!reactions || typeof reactions !== "object") return null;
    const amountKey = Number.isFinite(candidate.amount) ? String(candidate.amount) : "";
    const ratioKey = Number.isFinite(candidate.ratio) ? String(candidate.ratio) : "";
    const exact = reactions[`${candidate.kind}:${amountKey}`] ||
      (ratioKey && reactions[`${candidate.kind}:${ratioKey}`]) ||
      reactions[amountKey] || reactions[ratioKey] || reactions[candidate.kind] || reactions[candidate.action] || null;
    if (exact) return exact;
    const values = Object.entries(reactions);
    const match = values.find(([key, value]) => {
      if (!value || typeof value !== "object") return false;
      if (value.kind && value.kind !== candidate.kind) return false;
      if (Number.isFinite(candidate.amount) && Number.isFinite(Number(value.amount)) &&
          Math.abs(Number(value.amount) - candidate.amount) <= Math.max(.000001, Math.abs(candidate.amount) * .000001)) return true;
      return Number.isFinite(candidate.ratio) && Number.isFinite(Number(value.ratio)) &&
        Math.abs(Number(value.ratio) - candidate.ratio) <= .0001;
    });
    return match ? match[1] : null;
  }
  function normalizeReaction(response) {
    if (!response || typeof response !== "object") return null;
    const probabilities = response.probabilities && typeof response.probabilities === "object" ? response.probabilities : response;
    const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    const fold = number(probabilities.fold);
    const call = number(probabilities.call) + number(probabilities.check);
    const raise = number(probabilities.raise) + number(probabilities.bet) +
      number(probabilities.reraise) + number(probabilities.allin);
    const total = fold + call + raise;
    if (total <= 0) return null;
    const rawCallCounts = response.callCountDistribution && typeof response.callCountDistribution === "object" ? response.callCountDistribution : null;
    const callCountEntries = rawCallCounts ? Object.entries(rawCallCounts).map(([count, probability]) =>
      [Math.max(1, Math.floor(Number(count))), number(probability)]).filter(([count, probability]) => Number.isFinite(count) && probability > 0) : [];
    const callCountTotal = callCountEntries.reduce((sum, [, probability]) => sum + probability, 0);
    const callCountDistribution = callCountTotal > 0 ? Object.fromEntries(callCountEntries.map(([count, probability]) =>
      [String(count), probability / callCountTotal])) : null;
    const expectedCallers = callCountDistribution ? Object.entries(callCountDistribution).reduce((sum, [count, probability]) =>
      sum + Number(count) * probability, 0) : Number(response.expectedCallers ?? response.callers ?? response.callCount);
    const normalized = {
      ...response,
      fold: fold / total,
      call: call / total,
      raise: raise / total,
      sampleCount: Number.isFinite(Number(response.sampleCount)) ? Number(response.sampleCount) :
        Number.isFinite(Number(response.minPersonalSamples)) ? Number(response.minPersonalSamples) : null,
      populationSampleCount: Number.isFinite(Number(response.populationSampleCount)) ? Number(response.populationSampleCount) :
        Number.isFinite(Number(response.minPopulationSamples)) ? Number(response.minPopulationSamples) : null,
    };
    if (callCountDistribution) normalized.callCountDistribution = callCountDistribution;
    if (Number.isFinite(expectedCallers) && expectedCallers > 0) normalized.expectedCallers = expectedCallers;
    return normalized;
  }
  function compareLegalActions({ candidates, buttons, pot, call = 0, effective = Infinity, equity, players = 1, street = null, rakeRate = null, rakeCap = null, reactions = null, improvementProbability = 0, protectionGain = 0, semiBluffMinImprovement = .12, thinValuePotRatio = .05, freeRaiseAmounts = [], minRaiseTo = null, allInCall = false, includeAllIn = true, requireConditionalEquity = false } = {}) {
    const legal = Array.isArray(candidates) ? candidates : actionCandidates(buttons, { pot, call, effective, freeRaiseAmounts, minRaiseTo, allInCall, includeAllIn });
    const boundedEquity = Math.max(0, Math.min(1, Number(equity)));
    const numericCall = Number(call);
    if (!Number.isFinite(pot) || pot < 0 || !Number.isFinite(boundedEquity) || !Number.isFinite(numericCall) || numericCall < 0) return { best: null, evaluated: [], reason: "底池、跟注量或胜率无效" };
    const stackLimit = Number.isFinite(effective) ? Math.max(0, Number(effective)) : Infinity;
    const amountReason = candidate => {
      if (candidate.kind === "check" && numericCall > .000001) return "有待补齐量时不能让牌";
      if (!["call", "allin_call", "quick_bet", "custom_raise", "minimum_raise", "allin"].includes(candidate.kind)) return "";
      if (!Number.isFinite(candidate.amount)) return "金额未确认";
      if (candidate.amount < 0 || candidate.amount > stackLimit + .000001) return "金额超过有效筹码";
      if (["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(candidate.kind) && candidate.amount <= numericCall + .000001) return "加注额未超过需要补齐量";
      if (["call", "allin_call"].includes(candidate.kind) && candidate.amount < numericCall - .000001) return "跟注额低于需要补齐量";
      return "";
    };
    const passive = legal.map(candidate => {
      const invalid = amountReason(candidate);
      if (invalid) return { ...candidate, ev: -Infinity, eligible: false, classification: null, reason: invalid };
      if (candidate.kind === "fold") return { ...candidate, ev: 0, eligible: true, classification: null };
      if (candidate.kind === "check") return { ...candidate, ev: boundedEquity * finalPotAfterRake(pot, rakeRate, rakeCap), eligible: true, classification: null };
      if (["call", "allin_call"].includes(candidate.kind) && Number.isFinite(candidate.amount)) {
        return { ...candidate, ev: boundedEquity * finalPotAfterRake(pot + candidate.amount, rakeRate, rakeCap) - candidate.amount, eligible: true, classification: null };
      }
      return null;
    }).filter(Boolean);
    const bestPassive = passive.reduce((best, item) => !best || item.ev > best.ev ? item : best, null);
    const bestPassiveEV = bestPassive?.ev ?? -Infinity;
    const aggressive = legal.filter(candidate => ["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(candidate.kind)).map(candidate => {
      const invalid = amountReason(candidate);
      if (invalid) return { ...candidate, ev: -Infinity, eligible: false, classification: null, reason: invalid };
      const rawResponse = reactionFor(reactions, candidate);
      const response = normalizeReaction(rawResponse);
      if (!response) return { ...candidate, ev: -Infinity, eligible: false, classification: null, reason: "缺少对应金额的对手反应概率" };
      const potRatio = pot > 0 ? Math.max(0, candidate.amount - numericCall) / pot : Infinity;
      if (candidate.kind === "minimum_raise" && numericCall <= .000001 && potRatio < .20 &&
          response.matchTier !== "exact" && response.matchTier !== "near_amount") {
        return { ...candidate, ev: -Infinity, eligible: false, classification: null,
          response, reason: "极小试探下注缺少该尺度的精确或近似反应样本" };
      }
      const fold = response.fold, callProbability = response.call, raise = response.raise;
      const opponentCall = Math.max(0, candidate.amount - numericCall);
      const maximumCallers = Math.max(1, Math.floor(Number(players)));
      const callerDistribution = response.callCountDistribution ? Object.entries(response.callCountDistribution).map(([count, probability]) =>
        [Math.max(1, Math.min(maximumCallers, Math.floor(Number(count)))), Number(probability)]).filter(([, probability]) => Number.isFinite(probability) && probability > 0) : [];
      const callersValue = Number(response.expectedCallers ?? response.callers ?? response.callCount);
      const callers = Number.isFinite(callersValue) ? Math.max(1, Math.min(maximumCallers, callersValue)) : 1;
      const requiredCallerCounts = callerDistribution.length
        ? [...new Set(callerDistribution.map(([count]) => String(Math.round(count))))]
        : [String(Math.round(callers))];
      const conditionalSourceReady = ["conditional_continue_range_model", "verified_continue_range", "conservative_all_continue_baseline"]
        .includes(response.conditionalEquitySource);
      const conditionalEquityReady = callProbability <= 0 || conditionalSourceReady &&
        requiredCallerCounts.every(count => Number.isFinite(Number(response.equityByCallers?.[count])));
      if (requireConditionalEquity && !conditionalEquityReady) return { ...candidate, ev: -Infinity, eligible: false,
        classification: null, response, reason: "缺少该金额被跟注后的条件继续范围胜率" };
      const calledEVByCount = {};
      const calledEquityFor = count => {
        const value = response.equityByCallers?.[String(count)] ?? response.equityByCallers?.[count];
        return Number.isFinite(Number(value)) ? Math.max(0, Math.min(1, Number(value))) : boundedEquity;
      };
      const calledEVFor = count => {
        const normalizedCount = Math.max(1, Math.min(maximumCallers, Math.round(Number(count))));
        const value = calledEquityFor(normalizedCount) * finalPotAfterRake(
          pot + candidate.amount + opponentCall * normalizedCount, rakeRate, rakeCap
        ) - candidate.amount;
        calledEVByCount[String(normalizedCount)] = value;
        return value;
      };
      const calledEV = callerDistribution.length ? callerDistribution.reduce((sum, [count, probability]) =>
        sum + probability * calledEVFor(count), 0) : calledEVFor(callers);
      const raisedEV = Number.isFinite(response.raiseEV) ? response.raiseEV : -candidate.amount;
      const ev = fold * pot + callProbability * calledEV + raise * raisedEV;
      const continueProbability = callProbability + raise;
      const noFoldEV = continueProbability > 0 ? (callProbability * calledEV + raise * raisedEV) / continueProbability : -Infinity;
      const improvement = Number.isFinite(response.improvementProbability) ? response.improvementProbability : improvementProbability;
      const protection = Number.isFinite(response.protectionGain) ? response.protectionGain : protectionGain;
      const valueEdge = calledEV - bestPassiveEV;
      const betLabel = street && street !== "preflop" && numericCall <= .000001;
      let classification = valueEdge >= 0
        ? protection >= .02 ? "保护性下注"
          : valueEdge <= Math.max(0, pot * thinValuePotRatio) + 1e-9 ? (betLabel ? "薄价值下注" : "薄价值加注")
            : betLabel ? "价值下注" : "价值加注"
        : improvement >= semiBluffMinImprovement ? "半诈唬" : "纯诈唬";
      const personalSamples = response.sampleCount == null ? NaN : Number(response.sampleCount);
      const populationSamples = response.populationSampleCount == null ? NaN : Number(response.populationSampleCount);
      const pureBluffSampleReady = Number.isFinite(personalSamples) && personalSamples >= 30 &&
        Number.isFinite(populationSamples) && populationSamples >= 30;
      const multiwayResponseReady = maximumCallers === 1 || callProbability <= 0 ||
        callerDistribution.length > 0 || Number.isFinite(callersValue) && callersValue > 0;
      const deepAllIn = candidate.kind === "allin" && candidate.amount > Math.max(pot * 1.5, numericCall * 2);
      const lowSampleAllIn = deepAllIn && !(Number.isFinite(personalSamples) && personalSamples >= 30 &&
        Number.isFinite(populationSamples) && populationSamples >= 30);
      const alreadyCommitted = Number.isFinite(stackLimit) && stackLimit > 0 && numericCall / stackLimit >= .25;
      const independentlyCalibratedResponse = response.conditionalEquitySource !== "conservative_all_continue_baseline";
      const strongCalledValue = independentlyCalibratedResponse && valueEdge >= Math.max(.05, pot * .10);
      const uncalibratedDeepAllIn = lowSampleAllIn && !strongCalledValue && !alreadyCommitted;
      const eligible = !(players > 1 && classification === "纯诈唬") &&
        !(classification === "纯诈唬" && !pureBluffSampleReady) && multiwayResponseReady;
      const selectionEligible = !uncalibratedDeepAllIn;
      const riskGateReason = uncalibratedDeepAllIn ? "低样本深筹码超池全下缺少被跟注价值优势" : null;
      const reason = players > 1 && classification === "纯诈唬" ? "多人底池禁用纯诈唬" :
        classification === "纯诈唬" && !pureBluffSampleReady ? "相似场景不足30次，禁用纯诈唬" :
        !multiwayResponseReady ? "多人响应人数分布缺失，不评估激进行为" : "";
      const classificationEvidence = {
        calledValueEdge: valueEdge,
        improvementProbability: improvement,
        protectionGain: protection,
        semiBluffMinImprovement,
        pureBluffSampleReady,
        multiwayResponseReady,
        conditionalEquityReady,
        conditionalSourceReady,
        conditionalEquitySource: response.conditionalEquitySource || null,
      };
      return { ...candidate, ev, calledEV, calledEVByCount, raisedEV, noFoldEV, eligible,
        selectionEligible, riskGateReason, classification,
        classificationEvidence,
        reactionSampleCount: Number.isFinite(personalSamples) ? personalSamples : 0,
        reactionPopulationSampleCount: Number.isFinite(populationSamples) ? populationSamples : 0,
        sampleTier: response.sampleTier || null,
        response: { ...response, fold, call: callProbability, raise, callers }, reason };
    });
    const evaluated = [...passive, ...aggressive];
    const eligible = evaluated.filter(item => item.eligible && item.selectionEligible !== false && Number.isFinite(item.ev));
    const rawBest = eligible.reduce((winner, item) => !winner || item.ev > winner.ev ? item : winner, null);
    let best = rawBest;
    if (rawBest && ["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(rawBest.kind)) {
      const tolerance = Math.min(Math.max(0, pot * .03), Math.max(.001, Math.abs(rawBest.ev) * .10));
      const nearAggressive = eligible.filter(item =>
        ["quick_bet", "custom_raise", "minimum_raise", "allin"].includes(item.kind) &&
        Number.isFinite(item.amount) && rawBest.ev - item.ev <= tolerance + 1e-12
      );
      if (nearAggressive.length) best = nearAggressive.reduce((lower, item) => item.amount < lower.amount ? item : lower);
      if (best !== rawBest) best.selectionReason = "模拟误差范围内收益接近，选择较低投入尺度";
    }
    return { best, rawBest, evaluated, bestPassive, reason: best ? "" : "没有可评估的合法动作" };
  }
  function decisionExplanationSummary({ evaluated = [], calculationSource = null, sampleEvidence = [] } = {}) {
    const actions = evaluated.map(item => {
      const rawEv = Number.isFinite(item.ev) ? item.ev : null;
      const selectable = item.eligible !== false && item.selectionEligible !== false && rawEv !== null;
      const evLow = Number.isFinite(item.evLow) ? item.evLow : null, evHigh = Number.isFinite(item.evHigh) ? item.evHigh : null;
      const conservativeEv = selectable ? evLow ?? rawEv : null;
      return {
        action: item.action || null, kind: item.kind || null,
        amount: Number.isFinite(item.amount) ? item.amount : null,
        rawEv, conservativeEv,
        conservativeMethod: !selectable ? null : evLow !== null ? "ev_low" : "risk_gated_point_estimate",
        errorInterval: evLow !== null && evHigh !== null ? { low: evLow, high: evHigh } : null,
        personalSamples: Number(item.reactionSampleCount) || 0,
        populationSamples: Number(item.reactionPopulationSampleCount) || 0,
        sampleTier: item.sampleTier || null, selectable,
        eliminationReason: selectable ? null : item.riskGateReason || item.reason || "动作不可选",
      };
    });
    const byRawEv = (left, right) => (right.rawEv ?? -Infinity) - (left.rawEv ?? -Infinity);
    const byConservativeEv = (left, right) => (right.conservativeEv ?? -Infinity) - (left.conservativeEv ?? -Infinity);
    return {
      calculationSource,
      sampleEvidence,
      actions,
      conservativeEvRanking: actions.filter(item => item.selectable).sort(byConservativeEv),
      riskRejected: actions.filter(item => !item.selectable && item.rawEv !== null).sort(byRawEv),
    };
  }
  function chooseButton(strategy, buttons, pot, effective, options = {}) {
    const candidates = actionCandidates(buttons, { pot, effective, ...options });
    const hasFreeCheck = candidates.some(candidate => candidate.kind === "check");
    const primary = strategy.primary === "弃牌" && hasFreeCheck ? "让牌" : strategy.primary;
    if (primary !== strategy.primary) strategy.primary = primary;
    if (["跟注", "全下跟注"].includes(primary)) return candidates.find(candidate => candidate.kind === (primary === "全下跟注" ? "allin_call" : "call"))?.button || null;
    if (primary === "弃牌") return candidates.find(candidate => candidate.kind === "fold")?.button || null;
    if (primary === "让牌") return candidates.find(candidate => candidate.kind === "check")?.button || null;
    const target = (strategy.scale[0] + strategy.scale[1]) / 2;
    const quick = candidates.filter(candidate => candidate.kind === "quick_bet" && candidate.ratio >= strategy.scale[0] && candidate.ratio <= strategy.scale[1]).sort((a, b) => Math.abs(a.ratio - target) - Math.abs(b.ratio - target))[0];
    return quick?.button || candidates.find(candidate => candidate.kind === "custom_raise")?.button || null;
  }
  function simulationTrials(players, phase = "quick") {
    if (phase === "quick") return 300;
    if (phase === "precalc_variant") return 600;
    return 1200;
  }
  root.PokerCore = { truncateName, hudMetrics, defaultOpponentRange, weightedRange, matchingSceneEvidence, profileRangeDecision, strategyPolicy, reactionPolicy, opponentRange, parseCards, analyzeEquity, analyzeMultiway, analyzeEquityByCallerCount, analyzeConditionalEquityByCallerCount, analyzeNuts, analyzeBoardPotential, analyzeCrossStreet, analyzeFutureStreetEV, buildSidePotLayers, buildSidePotAccounting, requiresSidePotLayering, buildSidePotContract, buildSidePotContractFromState, analyzeSidePotEquity, variantDecisionGate, summarizeSidePotForDecision, buildDecisionEconomics, applyDecisionEconomics, analyzePreflopEquity, preflopRealizationProfile, trainingDecisionValue, advice, preflopAdvice, actionSituation, platformAmount, actionCandidates, compareLegalActions, decisionExplanationSummary, comparePreflopActions, comparePreflopScenarioActions, comparePreflopRangeCell, chooseButton, simulationTrials, evaluate, evaluateBrute, compareRanks };
  if (typeof module !== "undefined") module.exports = root.PokerCore;
})(typeof globalThis !== "undefined" ? globalThis : window);
