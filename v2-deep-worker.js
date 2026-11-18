"use strict";
importScripts("preflop-participation.js","poker-core.js","v2-model.js","v2-deep-model.js");

function compactCandidate(candidate){
  if(!candidate)return null;
  const audit=candidate.deepAudit||{};
  return {candidateIndex:candidate.candidateIndex,action:candidate.action,kind:candidate.kind,amount:candidate.amount,ratio:candidate.ratio,ev:candidate.ev,evLow:candidate.evLow,evHigh:candidate.evHigh,eligible:candidate.eligible,selectionEligible:candidate.selectionEligible,riskGateReason:candidate.riskGateReason,classification:candidate.classification,solveTier:candidate.solveTier,reason:candidate.reason,deepAudit:{nodes:audit.nodes,truncatedNodes:audit.truncatedNodes,boardBranches:audit.boardBranches,equitySamples:audit.equitySamples,prunedProbability:audit.prunedProbability,routes:audit.routes,elapsedMs:audit.elapsedMs}};
}

function compactDecision(decision){
  if(!decision)return null;
  return {modelVersion:decision.modelVersion,shadowOnly:true,solveTier:decision.solveTier,complete:decision.complete,best:compactCandidate(decision.best),rawBest:compactCandidate(decision.rawBest),evaluated:(decision.evaluated||[]).map(compactCandidate),calculationMs:decision.calculationMs,budget:decision.budget,audit:decision.audit,assumptions:decision.assumptions||[]};
}

self.onmessage=event=>{
  const {key,snapshot,decision,warmup}=event.data||{};
  try{
    if(warmup){self.postMessage({key,warmed:true});return}
    const audit=PokerV2.rangeAudit(snapshot),rangePlayers=audit.players.map(player=>({seat:player.seat,name:player.name,position:snapshot.seats.find(seat=>seat.seat===player.seat)?.position||"unknown",range:player.default})),input={snapshot,candidates:decision.candidates,rangePlayers,reactions:decision.reactions,effective:decision.effective};
    const t2=PokerV2Deep.deepDecision({...input,tier:"T2"});
    self.postMessage({key,stage:"T2",result:compactDecision(t2)});
    const t3=PokerV2Deep.deepDecision({...input,tier:"T3"});
    self.postMessage({key,stage:"T3",result:compactDecision(t3)});
  }catch(error){self.postMessage({key,error:error?.message||String(error)})}
};
