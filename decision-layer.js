(function(global){
  function heroIndex(state){return state?.layout==="6max"?3:4}
  function buttons(state){return state?.visualButtons?.length?state.visualButtons:state?.buttons||[]}
  function buildRequest(state){
    if(!state||!Number.isInteger(state.handId)||state.handId<=0)return null;
    const sequence=Number(state.actionButtonSequence)||0;
    if(!sequence)return null;
    const seats=state.seats||[],hero=seats[heroIndex(state)]||{};
    const play=typeof state.tablePlay==="string"?state.tablePlay:state.tablePlay?.type||null;
    const sidePotContract=window.PokerCore?.buildSidePotContractFromState?.(state,heroIndex(state)+1)||state.sidePotContract||null;
    return Object.freeze({
      decisionKey:JSON.stringify([state.runtimeId||null,state.tableSession,state.handId,state.street,sequence]),
      runtimeId:state.runtimeId||null,
      tableSession:Number(state.tableSession)||0,handId:state.handId,street:state.street,
      heroCards:Object.freeze([...(state.heroCards||[])]),
      boardCards:Object.freeze([...(state.boardCards||[])]),
      pot:Number.isFinite(state.pot)?state.pot:null,
      callAmount:Number.isFinite(state.callAmount)?state.callAmount:state.callAmount,
      minRaiseTo:Number.isFinite(state.minRaiseTo)?state.minRaiseTo:null,
      heroStack:Number.isFinite(hero.chips)?hero.chips:null,
      opponentStacks:Object.freeze(Object.fromEntries(seats.filter(seat=>seat.index!==heroIndex(state)&&Number.isFinite(seat.chips)).map(seat=>[seat.index+1,seat.chips]))),
      legalActions:Object.freeze(buttons(state).map(button=>button.kind).filter(Boolean)),
      tablePlay:play,rakeRate:Number.isFinite(state.rakeRate)?state.rakeRate:null,
      rakeCap:Number.isFinite(state.rakeCap)?state.rakeCap:null,
      sidePotContract:sidePotContract?Object.freeze(sidePotContract):null,
      frameSequence:Number(state.decisionDataFrameSequence)||null,
      buttonFrameSequence:Number(state.actionButtonFrameSequence)||null
    })
  }
  function assertBound(request){
    if(!request)throw Error("精算请求缺失");
    if(request.heroCards.length!==2)throw Error("精算请求缺少两张手牌");
    if(![0,3,4,5].includes(request.boardCards.length))throw Error("精算请求公共牌数量不合法");
    if(!Number.isFinite(request.pot)||request.pot<=0)throw Error("精算请求底池缺失");
    if(!request.legalActions.length)throw Error("精算请求合法动作缺失");
    const sidePot=request.sidePotContract;
    if(sidePot){
      if(sidePot.contractVersion!==1)throw Error("边池合同版本不兼容");
      const requestActions=[...new Set(request.legalActions)].sort(),contractActions=[...new Set(sidePot.legalActions||[])].sort();
      if(JSON.stringify(requestActions)!==JSON.stringify(contractActions))throw Error("边池合同与合法动作不一致");
      if(sidePot.rake?.rate!==request.rakeRate||sidePot.rake?.cap!==request.rakeCap)throw Error("边池合同与抽成规则不一致");
      if(sidePot.requiresLayering&&sidePot.exact!==true)throw Error("边池合同尚未精确对账");
    }
    return request
  }
  function presentation(decision){
    if(!decision?.primary)return null;
    return Object.freeze({primary:String(decision.primary),amount:Number.isFinite(decision.recommended)?decision.recommended:null,reasons:Object.freeze([...(decision.reasons||decision.decisionReasons||[])]),confidence:Number(decision.confidence)||0})
  }
  global.DecisionLayer=Object.freeze({buildRequest,assertBound,presentation});
})(window);
