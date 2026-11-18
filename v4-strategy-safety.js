(function(root){
  "use strict";

  function actionRisk(primary,item=null){
    const kind=item?.kind;
    if(primary==="弃牌"||primary==="让牌"||kind==="fold"||kind==="check")return 0;
    if(["跟注","全下跟注"].includes(primary)||["call","allin_call"].includes(kind))return 1;
    return 2;
  }

  function sameActionFamily(primary,item){
    if(!item)return false;
    if(primary==="弃牌")return item.kind==="fold";
    if(primary==="让牌")return item.kind==="check";
    if(["跟注","全下跟注"].includes(primary))return["call","allin_call"].includes(item.kind);
    return["quick_bet","custom_raise","minimum_raise","allin"].includes(item.kind);
  }

  function conservativeBaselineCandidate(baseline,candidates){
    const legal=Array.isArray(candidates)?candidates:[];
    if(actionRisk(baseline.primary)>=2)return legal.find(item=>item.kind==="check")||legal.find(item=>["call","allin_call"].includes(item.kind))||legal.find(item=>item.kind==="fold")||null;
    const baselineAllin=["全下","All-in候选"].includes(baseline.primary);
    const same=legal.filter(item=>sameActionFamily(baseline.primary,item)&&(item.kind!=="allin"||baselineAllin));
    if(same.length)return same.sort((left,right)=>Math.abs(Number(left.amount)||0)-Math.abs(Number(right.amount)||0))[0];
    return legal.sort((left,right)=>actionRisk(null,left)-actionRisk(null,right)||Math.abs(Number(left.amount)||0)-Math.abs(Number(right.amount)||0))[0]||null;
  }

  function conservativeRangeCandidate(hypothesisActions,candidates){
    const actions=new Set(Object.values(hypothesisActions||{}).filter(Boolean));
    const legal=(Array.isArray(candidates)?candidates:[]).filter(item=>
      item?.eligible!==false&&item?.selectionEligible!==false&&Number.isFinite(item?.ev));
    for(const action of ["弃牌","让牌","跟注","加注"]){
      if(!actions.has(action))continue;
      const matching=legal.filter(item=>sameActionFamily(action,item));
      if(matching.length)return matching.sort((left,right)=>
        actionRisk(null,left)-actionRisk(null,right)||
        Math.abs(Number(left.amount)||0)-Math.abs(Number(right.amount)||0))[0];
    }
    return null;
  }

  function conservativeOfficialCandidate(candidates,callAmount){
    const legal=Array.isArray(candidates)?candidates:[];
    if(typeof callAmount!=="number"||!Number.isFinite(callAmount))return legal.find(item=>item?.kind==="fold")||null;
    return Number(callAmount)>0
      ?legal.find(item=>item?.kind==="fold")||null
      :legal.find(item=>item?.kind==="check")||null;
  }

  function conservativeOfficialMathCandidates(candidates){
    return (Array.isArray(candidates)?candidates:[]).filter(item=>
      ["fold","check","call","allin_call"].includes(item?.kind));
  }

  const api=Object.freeze({actionRisk,conservativeBaselineCandidate,conservativeRangeCandidate,conservativeOfficialCandidate,conservativeOfficialMathCandidates});
  root.V4StrategySafety=api;
  if(typeof module!=="undefined")module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:window);
