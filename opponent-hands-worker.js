"use strict";
importScripts("preflop-participation.js","poker-core.js","v2-model.js");
self.onmessage=event=>{
  const {key,state}=event.data||{};
  try{
    const snapshot=PokerV2.buildDecisionSnapshot(state);
    const result=PokerV2.opponentRangeStatistics(snapshot,{coverageTarget:.8});
    self.postMessage({key,result});
  }catch(error){self.postMessage({key,error:error?.message||String(error)})}
};
