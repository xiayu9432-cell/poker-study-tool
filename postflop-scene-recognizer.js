(function (root) {
  const RANKS = "23456789TJQKA";
  const SUITS = new Set(["s", "h", "d", "c"]);
  const SEQUENCES = ["A2345", "23456", "34567", "45678", "56789", "6789T", "789TJ", "89TJQ", "9TJQK", "TJQKA"];

  function normalizeCard(card) {
    if (typeof card !== "string" || card.length !== 2) return null;
    const value = card[0].toUpperCase(), suit = card[1].toLowerCase();
    return RANKS.includes(value) && SUITS.has(suit) ? `${value}${suit}` : null;
  }

  function normalizeCards(cards) {
    return Array.isArray(cards) ? cards.map(normalizeCard).filter(Boolean) : [];
  }

  function rankValues(cards) {
    return cards.map(card => card[0] === "A" ? 14 : RANKS.indexOf(card[0]) + 2);
  }

  function uniqueSorted(values) {
    return [...new Set(values)].sort((left, right) => left - right);
  }

  function straightMissingRanks(cards) {
    const ranks = new Set(rankValues(cards));
    return SEQUENCES.map(sequence => {
      const values = sequence.split("").map(rank => rank === "A" ? 14 : RANKS.indexOf(rank) + 2);
      return { values, missing: values.filter(value => !ranks.has(value)) };
    }).filter(item => item.missing.length <= 2).sort((left, right) => left.missing.length - right.missing.length);
  }

  function boardTexture(board) {
    const cards = normalizeCards(board);
    if (![3, 4, 5].includes(cards.length) || new Set(cards).size !== cards.length) return { key: "unknown", label: "牌面未确认", reasons: ["公共牌数量或唯一性未确认"] };
    const values = uniqueSorted(rankValues(cards));
    const suits = Object.values(cards.reduce((counts, card) => {
      counts[card[1]] = (counts[card[1]] || 0) + 1;
      return counts;
    }, {}));
    const rankCounts = Object.values(cards.reduce((counts, card) => {
      counts[card[0]] = (counts[card[0]] || 0) + 1;
      return counts;
    }, {}));
    const paired = rankCounts.some(count => count >= 2);
    const flushPotential = Math.max(0, ...suits) >= 3;
    const connected = straightMissingRanks(cards).some(item => item.missing.length <= 2);
    const highCard = values.some(value => value >= 11);
    if (paired && !flushPotential && !connected) return { key: "paired_dry", label: "对子干燥牌面", reasons: ["牌面已配对", "同花和顺子联系较少"] };
    if (flushPotential || connected) return { key: "wet", label: "湿润牌面", reasons: [flushPotential ? "存在同花发展可能" : "牌面牌张较连贯"] };
    if (highCard) return { key: "dry_high", label: "干燥高张牌面", reasons: ["含高张牌", "牌面分散，顺子和同花联系较少"] };
    return { key: "dry_low", label: "干燥低张牌面", reasons: ["牌面分散", "没有明显高张、同花或顺子联系"] };
  }

  function handStrength(hero, board, evaluate) {
    const cards = normalizeCards(hero), publicCards = normalizeCards(board);
    if (cards.length !== 2 || publicCards.length < 3 || typeof evaluate !== "function") return { key: "unknown", label: "未知牌力", category: null, reason: "手牌或公共牌未确认" };
    const rank = evaluate([...cards, ...publicCards]), category = Number(rank?.[0]);
    if (!Number.isInteger(category)) return { key: "unknown", label: "未知牌力", category: null, reason: "牌力计算失败" };
    if (category >= 6) return { key: "nuts_candidate", label: "坚果候选", category, reason: "当前为葫芦或更强牌力" };
    if (category >= 2) return { key: "strong_made", label: "强成牌", category, reason: "当前为两对、三条或更强成牌" };
    if (category === 1) {
      const high = Math.max(...rankValues(cards));
      return high >= 11 ? { key: "medium_showdown", label: "中等摊牌价值", category, reason: "当前为一对且带高张" } : { key: "weak_pair", label: "弱对", category, reason: "当前只有较弱一对" };
    }
    return { key: "air", label: "空气", category, reason: "当前没有成对牌力" };
  }

  function drawStrength(hero, board) {
    const cards = normalizeCards(hero), publicCards = normalizeCards(board), all = [...cards, ...publicCards];
    if (cards.length !== 2 || publicCards.length < 3) return { key: "unknown", label: "未知听牌", cleanOuts: 0, reasons: ["手牌或公共牌未确认"] };
    if (publicCards.length >= 5) return { key: "none", label: "无后续听牌", cleanOuts: 0, reasons: ["河牌后没有下一张公共牌"] };
    const suitCounts = all.reduce((counts, card) => {
      counts[card[1]] = (counts[card[1]] || 0) + 1;
      return counts;
    }, {});
    const flushDraw = Object.values(suitCounts).some(count => count >= 4);
    const sequence = straightMissingRanks(all)[0];
    const straightDraw = sequence?.missing.length === 1;
    const backdoorStraight = publicCards.length === 3 && !straightDraw && straightMissingRanks(all).some(item => item.missing.length === 2);
    const backdoorFlush = publicCards.length === 3 && cards.some(card => (suitCounts[card[1]] || 0) === 3);
    const reasons = [];
    if (flushDraw) reasons.push("已有四张同花组合，存在同花听牌");
    if (straightDraw) reasons.push("只差一张牌组成顺子");
    if (backdoorStraight) reasons.push("存在后门顺子可能");
    if (flushDraw && straightDraw) return { key: "combo_draw", label: "组合听牌", cleanOuts: 0, reasons };
    if (flushDraw || straightDraw) return { key: "strong_draw", label: "强听牌", cleanOuts: 0, reasons };
    if (backdoorStraight || backdoorFlush) {
      if (backdoorFlush) reasons.push("一张手牌参与三张同花组合，存在后门同花可能");
      return { key: "weak_draw", label: "弱听牌", cleanOuts: 0, reasons };
    }
    return { key: "none", label: "无听牌", cleanOuts: 0, reasons: ["没有达到明确听牌条件"] };
  }

  function turnChange(previousBoard, board) {
    const before = normalizeCards(previousBoard), after = normalizeCards(board);
    if (before.length !== 3 || after.length !== 4 || before.some((card, index) => card !== after[index])) return { key: "unknown", label: "转牌变化未确认", scary: false, reasons: ["缺少稳定的翻牌到转牌变化"] };
    const turnCard = after[3], beforeTexture = boardTexture(before), afterTexture = boardTexture(after);
    const values = rankValues(after), suits = Object.values(after.reduce((counts, card) => {
      counts[card[1]] = (counts[card[1]] || 0) + 1;
      return counts;
    }, {}));
    const beforeMissing = Math.min(...SEQUENCES.map(sequence => sequence.split("").filter(rank => !new Set(rankValues(before)).has(rank === "A" ? 14 : RANKS.indexOf(rank) + 2)).length));
    const afterMissing = Math.min(...SEQUENCES.map(sequence => sequence.split("").filter(rank => !new Set(rankValues(after)).has(rank === "A" ? 14 : RANKS.indexOf(rank) + 2)).length));
    const completesStraight = afterMissing <= 1 && afterMissing < beforeMissing;
    const completesFlush = Math.max(0, ...suits) >= 4;
    const turnValue = rankValues([turnCard])[0];
    const priorHigh = Math.max(0, ...rankValues(before));
    const highCard = turnValue >= 11 && turnValue > priorHigh;
    const paired = values.length !== new Set(values).size;
    const connected = afterMissing < beforeMissing;
    const reasons = [];
    if (completesFlush) reasons.push("转牌使同花组合显著增加");
    if (completesStraight) reasons.push("转牌使顺子组合显著增加");
    if (highCard) reasons.push("转牌出现高张覆盖牌");
    if (paired) reasons.push("牌面出现对子化");
    if (connected) reasons.push("牌面连通性提高");
    const scary = completesFlush || completesStraight || highCard || connected;
    return { key: scary ? "scary" : paired ? "paired" : "neutral", label: scary ? "危险转牌" : paired ? "牌面配对" : "普通转牌", turnCard, scary, completesStraight, completesFlush, highCard, connected, reasons: reasons.length ? reasons : ["转牌没有明显改变牌面风险"] };
  }

  function actionSituation({ state = {}, context = {} } = {}) {
    const actions = (state.actionLog || []).filter(item => item.handId === state.handId), heroSeat = Number.isInteger(context.heroSeat) ? context.heroSeat : null;
    const initiative = actions.some(item => item.street === "preflop" && item.seat === heroSeat && ["raise", "reraise", "allin"].includes(item.action));
    const currentAggression = actions.some(item => item.street === state.street && item.seat !== heroSeat && ["bet", "raise", "reraise", "allin"].includes(item.action));
    const opponents = Number.isInteger(context.opponents) ? context.opponents : Number.isInteger(context.players) ? context.players : null;
    const players = Number.isInteger(context.totalPlayers) ? context.totalPlayers : opponents;
    const pot = Number(context.pot), call = Number(context.call), effective = Number(context.effective);
    return { street: state.street || null, players, opponents, multiway: opponents !== null && opponents >= 2, facingBet: call > 0 || currentAggression, initiative, position: context.position || state.heroPosition || "未知", callRatio: pot > 0 && call >= 0 ? call / pot : null, spr: pot > 0 && effective > 0 ? effective / pot : null, actionType: currentAggression || call > 0 ? "面对下注" : initiative ? "主动方未面对下注" : "无人下注" };
  }

  function baselineAction(recognized) {
    const result = (action, reason, evidenceLevel = "B", requiresRealtimeMath = false) =>
      ({ action, reason, evidenceLevel, requiresRealtimeMath,
        evidenceSource: evidenceLevel === "B" ? "翻后场景规则与当前数学模型交叉验证" : "翻后经验边界，待录像数据校准" });
    if (!recognized || recognized.reliable !== true) return result(null, "翻后识别输入不足，不能匹配场景策略", null, false);
    const handKey = recognized.handStrength.key;
    const textureKey = recognized.texture.key;
    const facingBet = recognized.action.facingBet;
    const multiway = recognized.action.multiway;
    const initiative = recognized.action.initiative;
    const lowSpr = Number.isFinite(recognized.action.spr) && recognized.action.spr <= 2;
    const noDraw = recognized.drawStrength.key === "none";
    if (lowSpr && ["strong_made", "nuts_candidate"].includes(handKey)) return result(null, "有效筹码较低，强牌进入底池承诺区，下注金额交给实时精算核对合法全下", "B", true);
    if (multiway && facingBet && recognized.drawStrength.key === "strong_draw") return result(null, "多人底池强听牌面对下注，必须按人数、底池赔率和实现率比较", "B", true);
    if (facingBet && ["air", "weak_pair"].includes(handKey) && noDraw) return result("弃牌", "弱牌且无听牌，面对下注缺少继续依据");
    if (!facingBet && ["strong_made", "nuts_candidate"].includes(handKey)) return result("加注", "强成牌优先直接取值并收取听牌成本");
    if (!facingBet && multiway && ["air", "weak_pair"].includes(handKey)) return result("让牌", "多人底池弱牌减少纯诈唬和边缘投入");
    if (!facingBet && !multiway && initiative && ["dry_high", "paired_dry", "dry_low"].includes(textureKey)) return result("加注", "单挑主动方在干燥牌面使用小额持续下注");
    if (!facingBet && textureKey === "wet" && ["air", "weak_pair"].includes(handKey)) return result("让牌", "湿润牌面弱牌减少无依据诈唬");
    if (!facingBet && recognized.turnChange.scary && ["medium_showdown", "weak_pair"].includes(handKey)) return result("让牌", `转牌被识别为${recognized.turnChange.label}，中等牌力先控制底池`);
    if (recognized.action.street === "river" && !facingBet && handKey === "medium_showdown") return result("让牌", "河牌中等摊牌价值优先保留摊牌，避免薄价值下注");
    if (recognized.action.street === "river" && !facingBet && handKey === "air") return result(null, "河牌无摊牌价值，只有对手示弱和范围优势同时确认时才考虑诈唬", "C", true);
    if (recognized.action.street === "turn" && !facingBet && recognized.drawStrength.key === "strong_draw" && !multiway) return result(null, "转牌强听牌可半诈唬，但下注尺度和弃牌收益交给实时精算", "B", true);
    if (recognized.action.street === "turn" && !facingBet && recognized.drawStrength.key === "weak_draw") return result("让牌", "转牌弱听牌改善机会有限，先控制投入");
    if (recognized.action.street === "flop" && facingBet && recognized.drawStrength.key === "weak_draw") return result(null, "翻牌弱听牌面对下注，必须按价格和隐含赔率比较", "B", true);
    if (recognized.action.street === "river" && facingBet && handKey === "medium_showdown" && Number.isFinite(recognized.action.callRatio) && recognized.action.callRatio <= .25 && recognized.turnChange.scary !== true) return result(null, "河牌小额下注可作为抓诈唬候选，但需要价值与诈唬组合比较", "B", true);
    return result(null, "当前翻后场景交给实时精算比较", "C", true);
  }

  function recognize({ state = {}, context = {}, hero = [], board = [], evaluate } = {}) {
    const publicCards = normalizeCards(board), texture = boardTexture(publicCards), hand = handStrength(hero, publicCards, evaluate), draw = drawStrength(hero, publicCards), action = actionSituation({ state, context });
    const previousBoard = context.previousBoard || state.previousBoardCards || [];
    const turn = publicCards.length === 4 ? turnChange(previousBoard, publicCards) : { key: "not_turn", label: "非转牌", scary: false, reasons: [] };
    const unique = new Set(publicCards).size === publicCards.length && new Set([...normalizeCards(hero), ...publicCards]).size === normalizeCards(hero).length + publicCards.length;
    return { street: state.street || null, texture, handStrength: hand, drawStrength: draw, turnChange: turn, action, reliable: unique && texture.key !== "unknown" && hand.key !== "unknown" };
  }

  root.PostflopSceneRecognizer = { boardTexture, handStrength, drawStrength, turnChange, actionSituation, baselineAction, recognize };
})(typeof window !== "undefined" ? window : globalThis);
