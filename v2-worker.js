"use strict";
importScripts("preflop-participation.js","poker-core.js","v2-model.js");

self.onmessage=event=>{
  const {key,snapshot,decision,includeMatrices=true,warmup}=event.data||{},startedAt=performance.now();
  try{
    if(warmup){
      const warmSnapshot=PokerV2.buildDecisionSnapshot({runtimeId:"warmup",handId:1,street:"preflop",dealerIndex:0,layout:"8max",heroPosition:"big_blind",heroCards:["As","Kh"],boardCards:[],pot:.5,callAmount:.05,minRaiseTo:.2,blindBig:.05,seats:[{index:0,name:"caller",chips:8,action:"call"},{index:4,name:"hero",chips:4,action:"waiting"},{index:5,name:"straddle",chips:8,action:"straddle"}],actionLog:[{handId:1,street:"preflop",seat:6,action:"straddle",amount:.1,sequence:1},{handId:1,street:"preflop",seat:1,action:"call",amount:.1,sequence:2}]});
      const warmAudit=PokerV2.rangeAudit(warmSnapshot),warmPlayers=warmAudit.players.map(player=>({seat:player.seat,position:warmSnapshot.seats.find(seat=>seat.seat===player.seat)?.position||"unknown",range:player.default})),warmCandidates=[{kind:"fold",amount:0},{kind:"call",amount:.05},{kind:"minimum_raise",amount:.2},{kind:"custom_raise",amount:.5},{kind:"allin",amount:4}];
      PokerV2.shadowDecision({snapshot:warmSnapshot,candidates:warmCandidates,rangePlayers:warmPlayers,reactions:{},equity:.6,equityInterval:[.55,.65],effective:4});
      PokerV2.t1Decision({snapshot:warmSnapshot,candidates:warmCandidates,rangePlayers:warmPlayers,reactions:{},effective:4,seed:"worker-warmup"});
      self.postMessage({key,warmed:true,calculationMs:performance.now()-startedAt});
      return;
    }
    const audit=PokerV2.rangeAudit(snapshot),rangeFinishedAt=performance.now();
    const defaultPlayers=audit.players.map(player=>({seat:player.seat,name:player.name,position:snapshot.seats.find(seat=>seat.seat===player.seat)?.position||"unknown",range:player.default}));
    const shadow=decision?PokerV2.shadowDecision({snapshot,rangePlayers:defaultPlayers,...decision}):null,t0FinishedAt=performance.now();
    const nextStreet=decision&&!decision.skipT1?PokerV2.t1Decision({snapshot,candidates:decision.candidates,rangePlayers:defaultPlayers,reactions:decision.reactions,effective:decision.effective}):null,t1FinishedAt=performance.now();
    const rangeAudit=PokerV2.compactRangeAudit(audit,snapshot?.decisionId);
    if(!includeMatrices)rangeAudit.players=rangeAudit.players.map(({defaultCells,profiledCells,topCombos,...player})=>player);
    self.postMessage({key,result:{...rangeAudit,opponentRoles:PokerV2.opponentRoles(snapshot),decision:shadow,nextStreetDecision:nextStreet,calculationMs:t1FinishedAt-startedAt,stageMs:{range:rangeFinishedAt-startedAt,t0:t0FinishedAt-rangeFinishedAt,t1:t1FinishedAt-t0FinishedAt}}});
  }catch(error){
    self.postMessage({key,error:error?.message||String(error)});
  }
};
