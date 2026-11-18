"use strict";
importScripts("preflop-participation.js","poker-core.js","v2-model.js");

function compactTree(tree){
  if(!tree)return null;
  return {orderedSeats:tree.orderedSeats,probabilities:tree.probabilities,pathCount:Array.isArray(tree.paths)?tree.paths.length:null,prunedProbability:tree.prunedProbability,sampleTier:tree.sampleTier,sampleCount:tree.sampleCount,source:tree.source,uncalibrated:tree.uncalibrated===true,responseMargin:tree.responseMargin,summaryFallback:tree.summaryFallback===true};
}

function compactCandidate(candidate){
  if(!candidate)return null;
  return {candidateIndex:candidate.candidateIndex,action:candidate.action,kind:candidate.kind,amount:candidate.amount,ratio:candidate.ratio,ev:candidate.ev,evLow:candidate.evLow,evHigh:candidate.evHigh,eligible:candidate.eligible,selectionEligible:candidate.selectionEligible,riskGateReason:candidate.riskGateReason,classification:candidate.classification,classificationEvidence:candidate.classificationEvidence,solveTier:candidate.solveTier,reason:candidate.reason,responseTree:compactTree(candidate.responseTree)};
}

function compactDecision(decision){
  if(!decision)return null;
  return {modelVersion:decision.modelVersion,shadowOnly:true,solveTier:decision.solveTier,complete:decision.complete,best:compactCandidate(decision.best),rawBest:compactCandidate(decision.rawBest),selectionTolerance:decision.selectionTolerance,evaluated:(decision.evaluated||[]).map(compactCandidate),decisionContext:decision.decisionContext,rangeSource:decision.rangeSource,parallelParts:1,assumptions:decision.assumptions||[]};
}

self.onmessage=event=>{
  const {key,snapshot,decision,formalReference,warmup}=event.data||{},startedAt=performance.now();
  try{
    if(warmup){
      const snapshot=PokerV2.buildDecisionSnapshot({runtimeId:"warmup",handId:1,street:"preflop",dealerIndex:0,layout:"8max",heroPosition:"big_blind",heroCards:["As","Kh"],boardCards:[],pot:.5,callAmount:.05,minRaiseTo:.2,blindBig:.05,seats:[{index:0,name:"caller",chips:8,action:"call"},{index:4,name:"hero",chips:4,action:"waiting"},{index:5,name:"straddle",chips:8,action:"straddle"}],actionLog:[{handId:1,street:"preflop",seat:6,action:"straddle",amount:.1,sequence:1},{handId:1,street:"preflop",seat:1,action:"call",amount:.1,sequence:2}]});
      const audit=PokerV2.rangeAudit(snapshot),players=audit.players.map(player=>({seat:player.seat,position:snapshot.seats.find(seat=>seat.seat===player.seat)?.position||"unknown",range:player.default}));
      PokerV2.t1Decision({snapshot,candidates:[{kind:"call",amount:.05},{kind:"custom_raise",amount:.5}],rangePlayers:players,reactions:{},effective:4,seed:"t1-worker-warmup"});
      self.postMessage({key,warmed:true,calculationMs:performance.now()-startedAt});
      return;
    }
    const audit=PokerV2.rangeAudit(snapshot),players=audit.players.map(player=>({seat:player.seat,name:player.name,position:snapshot.seats.find(seat=>seat.seat===player.seat)?.position||"unknown",range:player.default}));
    const fullResult=PokerV2.t1Decision({snapshot,candidates:decision.candidates,rangePlayers:players,reactions:decision.reactions,effective:decision.effective});
    self.postMessage({key,result:compactDecision(fullResult),formalGate:PokerV2.formalSceneGate(snapshot,fullResult,formalReference,[]),calculationMs:performance.now()-startedAt});
  }catch(error){
    self.postMessage({key,error:error?.message||String(error)});
  }
};
