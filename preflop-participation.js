(function(root){
  "use strict";

  const DEALER_ORDERS={
    2:["dealer","big_blind"],
    3:["dealer","small_blind","big_blind"],
    4:["dealer","small_blind","big_blind","cutoff"],
    5:["dealer","small_blind","big_blind","under_the_gun","cutoff"],
    6:["dealer","small_blind","big_blind","under_the_gun","hijack","cutoff"],
    7:["dealer","small_blind","big_blind","under_the_gun","middle","hijack","cutoff"],
    8:["dealer","small_blind","big_blind","under_the_gun","under_the_gun_plus_one","middle","hijack","cutoff"],
  };
  const NORMAL_ORDERS={
    2:["dealer","big_blind"],
    3:["dealer","small_blind","big_blind"],
    4:["cutoff","dealer","small_blind","big_blind"],
    5:["under_the_gun","cutoff","dealer","small_blind","big_blind"],
    6:["under_the_gun","hijack","cutoff","dealer","small_blind","big_blind"],
    7:["under_the_gun","middle","hijack","cutoff","dealer","small_blind","big_blind"],
    8:["under_the_gun","under_the_gun_plus_one","middle","hijack","cutoff","dealer","small_blind","big_blind"],
  };
  const SCENARIO_ROLES={
    unopened:[],
    limped:["caller"],
    raised:["raiser"],
    raise_call:["raiser","caller"],
    reraised:["raiser","reraiser"],
  };
  const clamp=(value,minimum=0,maximum=1)=>Math.max(minimum,Math.min(maximum,Number(value)||0));
  const straddleAllowed=(players,requested=true)=>Math.max(2,Math.min(8,Math.round(Number(players)||8)))>=4&&requested===true;
  const postedFor=(position,{straddle=false,live=1,smallBlind=.5}={})=>position==="small_blind"?smallBlind:position==="big_blind"?1:straddle&&position==="straddle"?live:0;
  function positionForDealerRank(players,rank){
    const count=Math.max(2,Math.min(8,Math.round(Number(players)||8))),order=DEALER_ORDERS[count]||DEALER_ORDERS[8];
    return Number.isInteger(rank)&&rank>=0&&rank<order.length?order[rank]:"unknown";
  }
  function actionOrder(players=8,straddle=false){
    const count=Math.max(2,Math.min(8,Math.round(Number(players)||8))),normal=[...(NORMAL_ORDERS[count]||NORMAL_ORDERS[8])];
    if(!straddleAllowed(count,straddle))return normal;
    const straddleIndex=Math.max(0,normal.indexOf("under_the_gun"));
    normal[straddleIndex]="straddle";
    return [...normal.slice(straddleIndex+1),...normal.slice(0,straddleIndex+1)];
  }
  function scenarioParticipants({position,scenario="unopened",players=8,straddle=false,live=1,currentPrice=0,previousPrice=0,smallBlind=.5,participants=null}={}){
    straddle=straddleAllowed(players,straddle);
    const order=actionOrder(players,straddle),heroIndex=order.indexOf(position);
    if(heroIndex<0)return{valid:false,reason:"position_not_in_action_order",order,committed:[],unacted:[]};
    if(straddle&&position==="straddle"&&scenario==="unopened")return{valid:false,reason:"straddle_action_requires_prior_call",order,committed:[],unacted:[]};
    if(Array.isArray(participants?.committed)&&Array.isArray(participants?.unacted))return{
      valid:true,order,heroIndex,
      committed:participants.committed.map(item=>({...item,invested:Math.max(0,Number(item.invested)||0)})),
      unacted:participants.unacted.map(item=>({...item,invested:Math.max(0,Number(item.invested)||0)})),
    };
    const before=order.slice(0,heroIndex),after=order.slice(heroIndex+1),roles=SCENARIO_ROLES[scenario];
    if(!roles)return{valid:false,reason:"unknown_scenario",order,committed:[],unacted:[]};
    if(!roles.length&&!after.length)return{valid:false,reason:"no_action_after_everyone_folds",order,committed:[],unacted:[]};
    if(roles.length>before.length)return{valid:false,reason:"scenario_impossible_before_position",order,committed:[],unacted:[]};
    const actorPositions=before.slice(before.length-roles.length),committed=roles.map((role,index)=>({
      id:`committed-${index+1}`,seat:-(index+1),position:actorPositions[index]||"unknown",role,
      invested:Math.max(postedFor(actorPositions[index],{straddle,live,smallBlind}),
        role==="raiser"&&scenario==="reraised"?Number(previousPrice)||Math.max(live,(Number(currentPrice)||0)/3):Number(currentPrice)||0),
      rangeType:role==="reraiser"?"tight":role==="raiser"?"medium":"loose",
    }));
    const unacted=after.map((actorPosition,index)=>({
      id:`unacted-${index+1}`,seat:index+1,position:actorPosition,role:actorPosition==="straddle"?"forced_straddle":"unacted",
      invested:postedFor(actorPosition,{straddle,live,smallBlind}),rangeType:"medium",
    }));
    return{valid:true,order,heroIndex,committed,unacted};
  }
  function responsePrior(participant,{mode="aggressive",sizeRatio=0,priceIncrease=0}={}){
    const role=participant?.role||"unacted",late=["dealer","cutoff","hijack"].includes(participant?.position),blind=["small_blind","big_blind","straddle"].includes(participant?.position),pressure=Math.max(0,Math.log2(1+Math.max(0,Number(sizeRatio)||0))),freeOption=Number(priceIncrease)<=1e-9;
    let call=.20,raise=.055;
    if(mode==="passive"){
      call=blind?.30:late?.25:.20;raise=blind?.08:late?.065:.045;
      if(freeOption){raise=role==="forced_straddle"?.16:raise;call=1-raise}
    }else if(role==="raiser"){call=.48;raise=.18}
    else if(role==="reraiser"||role==="allin"){call=.58;raise=.28}
    else if(role==="caller"){call=.37;raise=.045}
    else if(role==="forced_straddle"){call=.28;raise=.09}
    else{call=late?.23:blind?.27:.18;raise=late?.07:blind?.08:.05}
    const decay=Math.exp(-(mode==="passive"?.24:.38)*pressure);call*=decay;raise*=Math.exp(-(mode==="passive"?.30:.45)*pressure);
    call=clamp(call,.01,freeOption?1:.85);raise=clamp(raise,.005,.45);if(call+raise>(freeOption?1:.92))call=(freeOption?1:.92)-raise;
    return{fold:freeOption?0:1-call-raise,call,raise,source:"position_role_prior",calibrated:false};
  }
  function continuationTree({locked=[],responders=[],responseFor,maxPaths=256}={}){
    const initialSeats=locked.map(item=>Number(item.seat)).filter(Number.isFinite);
    let paths=[{probability:1,responses:[],activeSeats:initialSeats,outcome:initialSeats.length?"call":"fold",callers:initialSeats.length}],prunedProbability=0;
    for(const opponent of responders){
      const next=[];
      for(const path of paths){
        if(path.outcome==="raise"){next.push(path);continue}
        const response=responseFor(opponent,path)||{},values={fold:Number(response.fold)||0,call:Number(response.call)||0,raise:Number(response.raise)||0},total=values.fold+values.call+values.raise;
        if(total<=0)continue;
        for(const [action,value] of Object.entries(values))if(value>0){
          const activeSeats=action==="fold"?[...path.activeSeats]:[...path.activeSeats,Number(opponent.seat)];
          next.push({probability:path.probability*value/total,responses:[...path.responses,{seat:Number(opponent.seat),role:opponent.role||"unacted",action}],activeSeats,outcome:action==="raise"?"raise":activeSeats.length?"call":"fold",callers:activeSeats.length});
        }
      }
      const ordered=next.sort((left,right)=>right.probability-left.probability),discarded=ordered.slice(maxPaths);
      prunedProbability+=discarded.reduce((sum,path)=>sum+path.probability,0);paths=ordered.slice(0,maxPaths);
    }
    if(prunedProbability>0)paths.push({probability:prunedProbability,responses:[],activeSeats:[],outcome:"raise",callers:0,pruned:true});
    const total=paths.reduce((sum,path)=>sum+path.probability,0)||1;
    paths=paths.map(path=>({...path,probability:path.probability/total}));
    const probabilities={fold:0,call:0,raise:0},callCountDistribution={};
    paths.forEach(path=>{probabilities[path.outcome]+=path.probability;if(path.outcome==="call")callCountDistribution[path.callers]=(callCountDistribution[path.callers]||0)+path.probability});
    const callTotal=probabilities.call||1;Object.keys(callCountDistribution).forEach(key=>callCountDistribution[key]/=callTotal);
    return{sequential:true,lockedSeats:initialSeats,orderedSeats:responders.map(item=>Number(item.seat)),probabilities,callCountDistribution,paths,prunedProbability:prunedProbability/total,prunedAs:prunedProbability>0?"raise_conservative":null};
  }
  function snapshotParticipants(snapshot,rangePlayers=[]){
    const hero=snapshot?.seats?.find(seat=>seat.isHero),count=snapshot?.seats?.length||8,actions=snapshot?.actions||[],bySeat=new Map((rangePlayers||[]).map(player=>[Number(player.seat),player])),committed=[],unacted=[],folded=[];
    for(const seat of snapshot?.seats||[]){
      const seatNumber=Number(seat.seat??Number(seat.index)+1),player=bySeat.get(seatNumber);if(seat.isHero||seat.empty||!player)continue;
      const own=actions.filter(event=>Number(event.seat)===seatNumber),last=own.filter(event=>["call","bet","raise","reraise","allin","fold"].includes(event.action)).at(-1)?.action||seat.action,forced=own.some(event=>event.action==="straddle"),order=hero?(seatNumber-Number(hero.seat)+count)%count:seatNumber,item={...player,seat:seatNumber,order,role:"unacted"};
      if(last==="fold"||seat.action==="fold"){folded.push(item);continue}
      if(last==="allin"||seat.action==="allin")item.role="allin";
      else if(["raise","reraise","bet"].includes(last))item.role=last==="reraise"?"reraiser":"raiser";
      else if(last==="call")item.role="caller";
      else if(forced)item.role="forced_straddle";
      if(["raiser","reraiser","caller","allin"].includes(item.role))committed.push(item);else unacted.push(item);
    }
    return{committed:committed.sort((a,b)=>a.order-b.order),unacted:unacted.sort((a,b)=>a.order-b.order),folded};
  }

  const api=Object.freeze({straddleAllowed,actionOrder,positionForDealerRank,scenarioParticipants,responsePrior,continuationTree,snapshotParticipants,postedFor});
  root.PreflopParticipation=api;if(typeof module!=="undefined")module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:window);
