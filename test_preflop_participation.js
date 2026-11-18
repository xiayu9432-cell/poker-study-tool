const assert=require("node:assert/strict");
const participation=require("./preflop-participation.js"),core=require("./poker-core.js"),v2=require("./v2-model.js"),deep=require("./v2-deep-model.js");

const freeBigBlind=participation.responsePrior({role:"unacted",position:"big_blind"},{mode:"passive",priceIncrease:0});
assert.equal(freeBigBlind.fold,0,"a blind with a free check cannot fold its forced bet");
assert.equal(Math.abs(freeBigBlind.call+freeBigBlind.raise-1)<1e-9,true);

const scenario=participation.scenarioParticipants({position:"dealer",scenario:"raised",players:8,straddle:false,currentPrice:3});
assert.equal(scenario.committed.length,1);
assert.equal(scenario.committed[0].role,"raiser");
assert.ok(scenario.unacted.length>=2);
const tree=participation.continuationTree({locked:scenario.committed,responders:scenario.unacted,responseFor:()=>({fold:.7,call:.2,raise:.1})});
assert.equal(tree.lockedSeats.length,1);
assert.ok(tree.paths.filter(path=>path.outcome==="call").every(path=>path.activeSeats.includes(scenario.committed[0].seat)));
assert.ok(tree.probabilities.raise>0);
assert.equal(participation.scenarioParticipants({position:"big_blind",scenario:"unopened",players:8}).reason,"no_action_after_everyone_folds");

assert.deepEqual(participation.actionOrder(8,true),[
  "under_the_gun_plus_one","middle","hijack","cutoff","dealer",
  "small_blind","big_blind","straddle",
]);
assert.deepEqual(participation.actionOrder(4,false),["cutoff","dealer","small_blind","big_blind"]);
assert.deepEqual(participation.actionOrder(5,false),["under_the_gun","cutoff","dealer","small_blind","big_blind"]);
assert.deepEqual(participation.actionOrder(4,true),["dealer","small_blind","big_blind","straddle"]);
assert.deepEqual(participation.actionOrder(3,true),["dealer","small_blind","big_blind"]);
assert.deepEqual(participation.actionOrder(2,true),["dealer","big_blind"]);
assert.equal(participation.straddleAllowed(3,true),false);
assert.equal(participation.straddleAllowed(4,true),true);
assert.equal(participation.scenarioParticipants({position:"straddle",players:3,straddle:true}).valid,false);
assert.equal(participation.scenarioParticipants({position:"straddle",scenario:"unopened",players:8,straddle:true}).reason,"straddle_action_requires_prior_call");
assert.equal(participation.positionForDealerRank(8,0),"dealer");
assert.equal(participation.positionForDealerRank(8,1),"small_blind");
assert.equal(participation.positionForDealerRank(8,2),"big_blind");
const straddleLimped=participation.scenarioParticipants({
  position:"straddle",scenario:"limped",players:8,straddle:true,live:2,currentPrice:2,
});
assert.equal(straddleLimped.valid,true);
assert.equal(straddleLimped.committed[0].invested,2);
assert.equal(straddleLimped.unacted.length,0);
const exact=participation.scenarioParticipants({position:"dealer",players:8,participants:{
  committed:[{seat:2,position:"under_the_gun",role:"raiser",invested:6}],
  unacted:[{seat:6,position:"small_blind",role:"unacted",invested:.5}],
}});
assert.deepEqual(exact.committed.map(item=>[item.seat,item.role,item.invested]),[[2,"raiser",6]]);
assert.deepEqual(exact.unacted.map(item=>[item.seat,item.position,item.invested]),[[6,"small_blind",.5]]);

const profiledOptions={position:"dealer",call:2,players:3,pot:5,effective:50,
  candidates:[{kind:"fold",amount:0},{kind:"call",amount:2}],trials:80,
  scenarioContext:{scenario:"raised",position:"dealer",players:3,straddle:false,live:1,posted:0,currentPrice:3,participants:{
    committed:[{seat:2,position:"under_the_gun",role:"raiser",invested:3,rangeType:"tight"}],unacted:[],
  }}};
const tightProfile=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Qh"]});
const looseProfile=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Qh"],scenarioContext:{...profiledOptions.scenarioContext,participants:{committed:[{seat:2,position:"under_the_gun",role:"raiser",invested:3,rangeType:"loose"}],unacted:[]}}});
assert.notEqual(tightProfile.evaluated.find(item=>item.kind==="call").ev,looseProfile.evaluated.find(item=>item.kind==="call").ev);
const observed=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Qh"],candidates:[{kind:"fold",amount:0},{kind:"minimum_raise",amount:8}],reactions:()=>({reliable:true,sampleCount:12,populationSampleCount:40,orderedSeats:[2],paths:[{probability:.9,outcome:"fold",callers:0,responses:[{seat:2,action:"fold"}]},{probability:.1,outcome:"call",callers:1,responses:[{seat:2,action:"call"}]}]})});
assert.equal(observed.evaluated.find(item=>item.kind==="minimum_raise").responseTree.source,"observed_ordered_reactions");
const sparse=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Qh"],candidates:[{kind:"minimum_raise",amount:8}],reactions:()=>({reliable:false,orderedSeats:[2],paths:[{probability:1,outcome:"fold",callers:0,responses:[{seat:2,action:"fold"}]}]})});
assert.equal(sparse.evaluated[0].responseTree.source,"position_role_prior");
const allinLocked=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Ah"],candidates:[{kind:"minimum_raise",amount:8}],scenarioContext:{...profiledOptions.scenarioContext,participants:{committed:[{seat:2,position:"under_the_gun",role:"allin",invested:3,rangeType:"tight"}],unacted:[]}}});
assert.equal(allinLocked.evaluated[0].responseTree.probabilities.fold,0);
const undercalled=core.comparePreflopScenarioActions({...profiledOptions,hero:["As","Qh"],call:3,candidates:[{kind:"call",amount:3}],scenarioContext:{...profiledOptions.scenarioContext,currentPrice:6,participants:{committed:[{seat:2,position:"under_the_gun",role:"caller",invested:3,rangeType:"medium"},{seat:3,position:"hijack",role:"raiser",invested:6,rangeType:"tight"}],unacted:[]}}});
assert.ok(undercalled.evaluated[0].responseTree.orderedSeats.includes(2),"a prior caller below the current price must still respond");
assert.ok(undercalled.evaluated[0].responseTree.lockedSeats.includes(3),"a player already at the current price stays committed");

const uncalibratedAllins=[
  {pot:.43,call:.1,effective:4.98,live:.1,amount:4.98},
  {pot:.53,call:0,effective:4.82,live:.1,amount:4.82},
  {pot:.33,call:.1,effective:5.81,live:.1,amount:5.81},
  {pot:.58,call:.45,effective:5.69,live:.1,amount:5.69},
  {pot:3.38,call:.45,effective:5.24,live:.1,amount:5.24},
  {pot:.33,call:.32,effective:6.16,live:.1,amount:6.16},
  {pot:.33,call:.1,effective:5.41,live:.1,amount:5.41},
  {pot:.33,call:.38,effective:5.17,live:.1,amount:5.17},
  {pot:1.86,call:.38,effective:5.17,live:.1,amount:5.17},
];
for(const item of uncalibratedAllins){
  const result=core.comparePreflopScenarioActions({hero:["7s","7d"],pot:item.pot,call:item.call,effective:item.effective,
    candidates:[{kind:"fold",amount:0},{kind:"call",amount:item.call},{kind:"allin",amount:item.amount}],trials:80,
    scenarioContext:{scenario:"raised",position:"dealer",players:8,straddle:true,live:item.live,posted:0,currentPrice:item.call,participants:{
      committed:[{seat:2,position:"straddle",role:"raiser",invested:item.call,rangeType:"medium"}],unacted:[],
    }}});
  assert.equal(result.evaluated.find(candidate=>candidate.kind==="allin").selectionEligible,false,
    "deep uncalibrated all-in must not win from position priors alone");
}
const shortAllin=core.comparePreflopScenarioActions({hero:["As","Kh"],pot:.3,call:.1,effective:.8,
  candidates:[{kind:"fold",amount:0},{kind:"allin",amount:.8}],trials:80,
  scenarioContext:{scenario:"raised",position:"dealer",players:8,straddle:true,live:.1,posted:0,currentPrice:.1,participants:{
    committed:[{seat:2,position:"straddle",role:"raiser",invested:.1,rangeType:"medium"}],unacted:[],
  }}});
assert.notEqual(shortAllin.evaluated.find(candidate=>candidate.kind==="allin").riskGateReason,
  "all-in response is not calibrated for this stack depth","a genuinely short stack remains eligible for normal EV comparison");

const candidates=[{kind:"fold",amount:0},{kind:"call",amount:3},{kind:"minimum_raise",amount:6},{kind:"custom_raise",amount:8.25}],base={position:"dealer",call:3,players:8,pot:4.5,effective:100,candidates,trials:600,scenarioContext:{scenario:"raised",position:"dealer",players:8,straddle:false,live:1,posted:0,currentPrice:3}};
const aq=core.comparePreflopRangeCell({...base,hero:["As","Qs"]}),suitedConnector=core.comparePreflopRangeCell({...base,hero:["Ts","9s"]});
assert.equal(aq.comparison.evaluated.find(item=>item.kind==="call").branchModel,"preflop_participation_v1");
assert.ok(aq.comparison.evaluated.find(item=>item.kind==="call").participantAudit.committed.length===1);
assert.equal(suitedConnector.primary,"弃牌");
const classes=[];for(const ranks of ["AKQJT98765432"])for(let row=0;row<13;row++)for(let column=0;column<13;column++){const high=ranks[Math.min(row,column)],low=ranks[Math.max(row,column)],hero=row===column?[high+"s",low+"h"]:row<column?[high+"s",low+"s"]:[high+"s",low+"h"],result=core.comparePreflopRangeCell({...base,hero});classes.push(result.primary)}
assert.ok(classes.includes("跟注"),"facing a raise must produce a call range");
assert.ok(classes.includes("加注"),"facing a raise must produce a raise range");
assert.ok(classes.includes("弃牌"),"facing a raise must produce a fold range");

const state={handId:11,street:"preflop",dealerIndex:0,layout:"8max",heroPosition:"dealer",heroCards:["As","Qs"],boardCards:[],pot:4.5,callAmount:3,minRaiseTo:6,blindBig:1,rakeRate:.05,rakeCap:3,seats:Array.from({length:8},(_,index)=>({index,name:`s${index+1}`,chips:100,action:index===1?"raise":index===4?"waiting":"waiting"})),actionLog:[{handId:11,street:"preflop",seat:2,action:"raise",amount:3,sequence:1}]};
const snapshot=v2.buildDecisionSnapshot(state),players=v2.rangeAudit(snapshot).players.map(player=>({seat:player.seat,position:snapshot.seats.find(seat=>seat.seat===player.seat).position,range:player.default}));
const passiveTree=v2.passivePreflopTree(snapshot,players,{kind:"call",amount:3});
assert.equal(passiveTree.lockedSeats.length,1);
assert.ok(passiveTree.orderedSeats.length>0);
const t1=v2.t1Decision({snapshot,candidates:[{kind:"fold",amount:0},{kind:"call",amount:3}],rangePlayers:players,effective:100,seed:"preflop-branches"});
assert.equal(t1.evaluated.find(item=>item.kind==="call").pathAggregation,"preflop_committed_plus_unacted_tree");
const t2=deep.deepDecision({snapshot,candidates:[{kind:"fold",amount:0},{kind:"call",amount:3}],rangePlayers:players,effective:100,tier:"T2",seed:"preflop-deep-branches",budget:{chanceBranches:2,equityTrials:12,maxNodes:50,timeMs:1000,responseGroups:6}});
assert.equal(t2.evaluated.find(item=>item.kind==="call").pathAggregation,"preflop_committed_plus_unacted_tree");
const allinSnapshot={...snapshot,seats:snapshot.seats.map(seat=>seat.seat===2?{...seat,action:"allin"}:seat),actions:[{handId:11,street:"preflop",seat:2,action:"allin",amount:100,sequence:1}]},allinPlayers=v2.rangeAudit(allinSnapshot).players.map(player=>({seat:player.seat,position:allinSnapshot.seats.find(seat=>seat.seat===player.seat).position,range:player.default})),allinTree=v2.candidateResponseTree(allinSnapshot,allinPlayers,{}, {kind:"minimum_raise",amount:6});
assert.ok(allinTree.lockedSeats.includes(2),"an all-in opponent must remain locked in the pot");
assert.ok(!allinTree.orderedSeats.includes(2),"an all-in opponent must not act again");
assert.equal(allinTree.probabilities.fold,0,"hero cannot win uncontested while an opponent is all-in");
console.log("unified preflop participation branches: OK");
