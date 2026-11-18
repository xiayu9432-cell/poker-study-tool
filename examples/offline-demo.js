"use strict";
const assert = require("node:assert/strict");
const core = require("../poker-core.js");

// Artificial fixtures only. evaluate() orders scores lexicographically.
const scenarios = [
  { name: "皇家同花顺胜过三条", board: ["Qs", "Js", "Ts", "2d", "3c"], hero: ["As", "Ks"], villain: ["Qh", "Qd"], expected: "hero" },
  { name: "公共牌皇家同花顺，双方平分", board: ["As", "Ks", "Qs", "Js", "Ts"], hero: ["2d", "3c"], villain: ["4h", "5d"], expected: "tie" },
  { name: "一对输给三条", board: ["Ah", "7d", "2c", "9s", "Jd"], hero: ["Ac", "Kd"], villain: ["7c", "7s"], expected: "villain" },
];

for (const scenario of scenarios) {
  const cards = [...scenario.board, ...scenario.hero, ...scenario.villain];
  assert.equal(new Set(cards).size, cards.length, "样例不可有重复牌");
  const hero = core.evaluate([...scenario.hero, ...scenario.board]);
  const villain = core.evaluate([...scenario.villain, ...scenario.board]);
  assert.deepEqual(hero, core.evaluateBrute([...scenario.hero, ...scenario.board]));
  assert.deepEqual(villain, core.evaluateBrute([...scenario.villain, ...scenario.board]));
  let comparison = 0;
  for (let i = 0; i < Math.max(hero.length, villain.length); i++) {
    comparison = (hero[i] || 0) - (villain[i] || 0);
    if (comparison) break;
  }
  const winner = comparison > 0 ? "hero" : comparison < 0 ? "villain" : "tie";
  assert.equal(winner, scenario.expected);
  console.log(`${scenario.name}：${winner === "tie" ? "平分" : winner === "hero" ? "我方胜" : "对方胜"}`);
}
console.log("3 个离线样例通过；未验证策略质量或盈利能力。");
