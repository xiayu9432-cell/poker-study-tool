(function(root){
  "use strict";
  const CORE=root.PokerCore||(typeof require!=="undefined"?require("./poker-core.js"):null);
  const PARTICIPATION=root.PreflopParticipation||(typeof require!=="undefined"?require("./preflop-participation.js"):null);
  const QUICK_RATIOS=Object.freeze([1/3,.5,2/3,1,1.2]);
  const SCENARIO_PRICES=Object.freeze({
    unopened:[1,0],limped:[1,0],raised:[3,1],raise_call:[3,1],reraised:[9,3],
  });
  const SCENARIO_POT_MULTIPLIERS=Object.freeze({unopened:[],limped:[1],raised:[3],raise_call:[3,3],reraised:[3,9]});
  function scenarioValues({position="dealer",scenario="unopened",effectiveBb=100,players=8,straddle=false,
    smallBlindBb=.5,straddleBb=2,anteBb=0,rakeRate=null,rakeCap=null}={}){
    const count=Math.max(2,Math.min(8,Math.round(Number(players)||8)));
    straddle=PARTICIPATION.straddleAllowed(count,straddle);
    const live=straddle&&Number(straddleBb)>1?Number(straddleBb):1;
    if(straddle&&position==="straddle"&&scenario==="unopened")scenario="limped";
    const prices=SCENARIO_PRICES[scenario];
    if(!prices)return{valid:false,reason:"unknown_scenario"};
    const currentPrice=prices[0]*live,previousPrice=prices[1]*live,
      smallBlind=Number.isFinite(Number(smallBlindBb))?Math.max(0,Number(smallBlindBb)):.5,
      posted=PARTICIPATION.postedFor(position,{straddle,live,smallBlind}),
      facing=Math.max(0,currentPrice-posted),
      minimumRaiseTo=currentPrice+Math.max(live,currentPrice-previousPrice),
      forcedPot=smallBlind+1+(straddle?live:0)+Math.max(0,Number(anteBb)||0)*count,
      pot=forcedPot+SCENARIO_POT_MULTIPLIERS[scenario].reduce((sum,multiple)=>sum+multiple*live,0),
      participantCheck=PARTICIPATION.scenarioParticipants({position,scenario,players:count,straddle,live,
        currentPrice,previousPrice,smallBlind});
    return{valid:participantCheck.valid,reason:participantCheck.reason||null,scenario,position,players:count,
      facing,pot,raises:scenario==="reraised"?2:["raised","raise_call"].includes(scenario)?1:0,
      minimumRaiseTo:Math.max(0,minimumRaiseTo-posted),effective:Math.max(0,Number(effectiveBb)||0),
      straddle,posted,live,currentPrice,previousPrice,smallBlind,freeCheck:facing<=1e-9,rakeRate,rakeCap};
  }
  function rangeCandidates(values={}){
    if(values.decision&&Array.isArray(values.decision.legalCandidates)&&values.decision.legalCandidates.length){
      return values.decision.legalCandidates;
    }
    const effective=Math.max(0,Number(values.effective)||0),facing=Math.max(0,Number(values.facing)||0),
      minimum=Math.min(effective,Math.max(facing,Number(values.minimumRaiseTo)||0)),pot=Math.max(0,Number(values.pot)||0),
      candidates=values.freeCheck?[{action:"让牌",kind:"check",amount:0}]:[{action:"弃牌",kind:"fold",amount:0}];
    if(facing>0)candidates.push(effective<=facing
      ?{action:"全下跟注",kind:"allin_call",amount:effective}
      :{action:"跟注",kind:"call",amount:facing});
    if(effective<=facing)return candidates;
    const quick=QUICK_RATIOS.map(ratio=>({action:"加注",kind:"quick_bet",ratio,
      amount:Math.min(effective,Math.max(minimum,CORE.platformAmount(facing+(pot+facing)*ratio)))}));
    candidates.push(...quick);
    if(minimum>facing&&!quick.some(item=>Math.abs(item.amount-minimum)<1e-9)){
      candidates.push({action:"加注",kind:"minimum_raise",amount:minimum});
    }
    if(effective>minimum&&!quick.some(item=>Math.abs(item.amount-effective)<1e-9)){
      candidates.push({action:"全下",kind:"allin",amount:effective});
    }
    return candidates;
  }
  function closestStackBucket(value){
    const buckets=[10,30,50,70,90,110,130,150,170,190],numeric=Number(value);
    return buckets.reduce((best,item)=>!Number.isFinite(numeric)||Math.abs(item-numeric)<Math.abs(best-numeric)?item:best,buckets[0]);
  }
  function resolveCell(name,result,decision){
    if(decision?.active&&decision.currentHandClass===name&&decision.officialAction){
      return{...result,primary:decision.officialAction,source:"formal_decision"};
    }
    return result;
  }
  function lifecycle(previousKey,decision){
    const key=decision?.available?decision.rangeKey||decision.decisionButtonKey||"":"";
    const handScope=value=>String(value||"").replace(/^baseline:/,"hand:").replace(/^decision:(.*):[^:]+$/,"hand:$1");
    if(decision?.mode==="baseline"&&String(previousKey).startsWith("decision:")&&handScope(key)===handScope(previousKey))return{phase:"holding",key:previousKey};
    if(key&&key!==previousKey)return{phase:"new",key};
    if(key)return{phase:decision.active?"active":"retained",key};
    return{phase:previousKey?"holding":"bootstrap",key:previousKey||""};
  }
  const api=Object.freeze({QUICK_RATIOS,scenarioValues,rangeCandidates,closestStackBucket,resolveCell,lifecycle});
  root.HeroRangeModel=api;
  if(typeof module!=="undefined")module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:window);
