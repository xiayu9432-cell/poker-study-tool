(function(global){
  function actionWord(decision){
    const situation=String(decision?.situation||"");
    if(situation.includes("下注")&&!/[34]下注/.test(situation))return"下注";
    return String(decision?.primary||"动作");
  }
  function situationPrefix(situation){
    return String(situation||"")
      .replace("偷盲开局加注","偷盲").replace("延迟持续下注","延迟持续")
      .replace("持续下注","持续").replace("隔离加注","隔离")
      .replace("挤压加注","挤压").replace("开局加注","开局")
      .replace("过牌加注","过牌").replace("领先下注","领先")
      .replace("探路下注","探路").replace("反主动下注","反主动")
      .replace("再次加注","再次").replace("3下注","3次").replace("4下注","4次");
  }
  function primaryTitle(decision,precision=2){
    if(!decision?.primary)return"";
    if(["弃牌","跟注","全下跟注","让牌"].includes(decision.primary))return String(decision.primary);
    const prefix=situationPrefix(decision.situation),classification=String(decision.classification||"");
    let classified=classification;
    if(decision.primary==="全下"&&classification)classified=classification.replace(/(?:加注|下注)$/u,"")+"全下";
    else if(classification&&!/(?:加注|下注)$/u.test(classification))classified+=actionWord(decision);
    const action=actionWord(decision),scene=String(decision.situation||"");
    const body=classified?prefix+classified:scene&&scene!==decision.primary?`${scene}：${decision.primary}`:String(decision.primary);
    const amount=Number(decision.recommended);
    return Number.isFinite(amount)&&["加注","全下","下注"].includes(action)
      ?`${body}至${amount.toFixed(precision)}`:body;
  }
  function closeAlternative(decision,pot){
    const best=decision?.comparison?.best;
    if(!best||!Number.isFinite(best.ev))return null;
    const next=(decision.comparison.evaluated||[])
      .filter(item=>item!==best&&item.eligible&&Number.isFinite(item.ev))
      .sort((left,right)=>right.ev-left.ev)[0];
    if(!next)return null;
    const gap=best.ev-next.ev,absoluteLimit=Math.max(0,Number(pot)||0)*.03;
    const relativeLimit=Math.max(.001,Math.abs(best.ev)*.10);
    if(gap<0||gap>absoluteLimit||gap>relativeLimit)return null;
    return Object.freeze({action:String(next.action),amount:Number.isFinite(next.amount)?next.amount:null,ev:next.ev,gap});
  }
  function normalize(decision){
    if(!decision?.primary)return null;
    return Object.freeze({
      primary:String(decision.primary),
      amount:Number.isFinite(decision.recommended)?Number(decision.recommended):null,
      confidence:Number.isFinite(decision.confidence)?Number(decision.confidence):0,
      reasons:Object.freeze([...(decision.reasons||decision.decisionReasons||[]).map(String)]),
      situation:decision.situation||null,
      classification:decision.classification||null,
      target:decision.target||null
    })
  }
  global.PresentationLayer=Object.freeze({normalize,primaryTitle,closeAlternative});
})(window);
