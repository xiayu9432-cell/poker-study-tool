(function(root){
  "use strict";

  const RANKS="23456789TJQKA",SUITS="shdc",MODEL_VERSION="2.0.0",CORE=root.PokerCore||(typeof require==="function"?require("./poker-core.js"):null),PREFLOP=root.PreflopParticipation||(typeof require==="function"?require("./preflop-participation.js"):null);
  const FORMAL_V2_SCENES=Object.freeze(["隔离加注"]);
  const FEATURES=Object.freeze({
    snapshotV2:true,sceneV2:true,rangeV2Shadow:false,deepT2T3Shadow:false,opponentHandUi:true,
    sequentialEvV2Shadow:false,formalV2:false,formalV2Mode:"disabled",
    formalV2Scenes:FORMAL_V2_SCENES,rangeUi:true,
  });
  const ACTION_WEIGHTS=[[60,.8,"S4"],[30,.6,"S3"],[15,.35,"S2"],[5,.15,"S1"],[0,0,"S0"]];
  const SHOW_WEIGHTS=[[60,.65,"H4"],[30,.45,"H3"],[15,.25,"H2"],[5,.10,"H1"],[0,0,"H0"]];

  const fullDeck=()=>[...RANKS].flatMap(rank=>[...SUITS].map(suit=>rank+suit));
  const exactKey=cards=>[...cards].sort().join("");
  const cardValue=card=>RANKS.indexOf(card[0])+2;
  function classKey(cards){
    const sorted=[...cards].sort((left,right)=>cardValue(right)-cardValue(left));
    const pair=sorted[0][0]===sorted[1][0];
    return `${sorted[0][0]}${sorted[1][0]}${pair?"":sorted[0][1]===sorted[1][1]?"s":"o"}`;
  }
  const ALL_COMBOS=Object.freeze((()=>{
    const deck=fullDeck(),result=[];
    for(let first=0;first<deck.length-1;first++)for(let second=first+1;second<deck.length;second++){
      const cards=Object.freeze([deck[first],deck[second]]);
      result.push(Object.freeze({cards,key:exactKey(cards),classKey:classKey(cards)}));
    }
    return result;
  })());
  const ALL_CLASSES=Object.freeze([...new Set(ALL_COMBOS.map(item=>item.classKey))]);
  const MATRIX_RANKS="AKQJT98765432";

  function deepFreeze(value){
    if(!value||typeof value!=="object"||Object.isFrozen(value))return value;
    Object.values(value).forEach(deepFreeze);
    return Object.freeze(value);
  }
  const clone=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
  function tier(count,table){
    const numeric=Math.max(0,Number(count)||0),row=table.find(([minimum])=>numeric>=minimum)||table.at(-1);
    return {count:numeric,weight:row[1],tier:row[2]};
  }
  const actionTier=count=>tier(count,ACTION_WEIGHTS);
  const showTier=count=>tier(count,SHOW_WEIGHTS);

  function voluntary(action){return !["blind","post_blind","straddle","check","fold"].includes(action)}
  function normalizeAction(action){return action==="reraise"?"raise":action}
  function classifyScene({street="preflop",action,priorActions=[],handActions=[],heroSeat=null,heroPosition="unknown",preflopRaiseCount=0,currentShowdownValue=null,futurePressurePlan=false,opponentCount=null,inPosition=false,actsLast=false}={}){
    const normalized=priorActions.map(item=>typeof item==="string"?{action:item,seat:null,street}:item).filter(item=>item?.action).map(item=>item.action==="allin"&&item.fullRaise===true?{...item,action:"raise"}:item);
    const prior=normalized.map(item=>normalizeAction(item.action)),raises=Math.max(Number(preflopRaiseCount)||0,prior.filter(item=>item==="raise").length);
    const firstRaise=prior.findIndex(item=>item==="raise"),callsAfterRaise=firstRaise>=0&&prior.slice(firstRaise+1).includes("call");
    const heroCall=normalized.findIndex(item=>Number(item.seat)===heroSeat&&item.action==="call");
    const heroLimped=heroCall>=0&&(firstRaise<0||heroCall<firstRaise);
    if(street==="preflop"&&["bet","raise","reraise","allin"].includes(action)){
      if(heroLimped&&raises>0)return "Limp-reraise";
      if(raises>2)return "再次加注";
      if(raises===2)return "4下注";
      if(raises===1&&callsAfterRaise)return "挤压加注";
      if(raises===1)return "3下注";
      if(prior.some(item=>item==="call"))return "隔离加注";
      if(["dealer","cutoff"].includes(heroPosition))return "偷盲开局加注";
      return "开局加注";
    }
    if(street==="preflop"&&action==="call"){
      if(heroPosition==="big_blind"&&raises>0)return "大盲防守";
      if(raises>0)return "冷跟";
      if(prior.includes("straddle"))return "跟注Straddle";
      return "Limp";
    }
    const hand=(handActions.length?handActions:priorActions).map(item=>typeof item==="string"?{action:item,street,seat:null}:item).filter(item=>item?.action);
    const aggressive=item=>["bet","raise","reraise","allin"].includes(item.action),streets=["preflop","flop","turn","river"],index=streets.indexOf(street),previous=streets[index-1];
    const preflopAggressor=[...hand].reverse().find(item=>item.street==="preflop"&&aggressive(item))?.seat;
    const priorAggressor=[...hand].reverse().find(item=>item.street===previous&&aggressive(item))?.seat??preflopAggressor;
    const currentAggression=normalized.filter(aggressive),heroChecked=normalized.some(item=>Number(item.seat)===heroSeat&&item.action==="check");
    if(street!=="preflop"&&["bet","raise","reraise","allin"].includes(action)){
      if(heroChecked&&currentAggression.length)return "过牌加注";
      if(currentAggression.length)return "翻牌后再次加注";
      const flop=hand.filter(item=>item.street==="flop");
      if(street==="flop"&&preflopAggressor===heroSeat)return "持续下注";
      if(street==="turn"&&preflopAggressor===heroSeat&&flop.some(item=>Number(item.seat)===heroSeat&&item.action==="check")&&!flop.some(aggressive))return "延迟持续下注";
      if(priorAggressor!==heroSeat&&hand.some(item=>item.street===previous&&item.seat===priorAggressor&&item.action==="check"))return "探路下注";
      if(street==="flop"&&preflopAggressor!==heroSeat)return "领先下注";
      const previousHeroPassive=hand.some(item=>item.street===previous&&Number(item.seat)===heroSeat&&["call","check"].includes(item.action));
      if(priorAggressor!==heroSeat&&previousHeroPassive)return "反主动下注";
      return null;
    }
    if(street!=="preflop"&&action==="call"&&currentAggression.length){
      if(currentShowdownValue==="weak"&&futurePressurePlan===true&&Number(opponentCount)===1&&inPosition===true)return "浮动跟注";
      return "面对下注跟注";
    }
    if(street!=="preflop"&&action==="fold"&&currentAggression.length)return "面对下注弃牌";
    if(street!=="preflop"&&action==="check")return heroPosition==="dealer"||actsLast===true?"后位让牌":"让牌";
    return null;
  }

  function snapshotPositionContext(snapshot){
    const hero=snapshot?.seats?.find(item=>item.isHero),tableSize=snapshot?.seats?.length||8,dealerSeat=Number(snapshot?.dealerSeat);
    if(!hero||!Number.isInteger(dealerSeat))return{opponentCount:null,inPosition:false,actsLast:false};
    const order=seat=>{const distance=(Number(seat)-dealerSeat+tableSize)%tableSize;return distance===0?tableSize:distance};
    const opponents=(snapshot?.seats||[]).filter(item=>!item.isHero&&!item.empty&&item.inHand!==false&&!['fold','empty','allin'].includes(item.action));
    const heroOrder=order(hero.seat),actsLast=opponents.length>0&&opponents.every(item=>order(item.seat)<heroOrder);
    return{opponentCount:opponents.length,inPosition:actsLast,actsLast};
  }

  function candidateScene(snapshot,candidate){
    const current=(snapshot?.actions||[]).filter(item=>item.street===snapshot?.street),hero=snapshot?.seats?.find(item=>item.isHero),position=snapshotPositionContext(snapshot),aggressive=["quick_bet","custom_raise","minimum_raise","allin"].includes(candidate?.kind),action=aggressive?(Number(snapshot?.callAmount)>0||current.some(item=>["bet","raise","reraise","allin"].includes(item.action))?"raise":"bet"):["call","allin_call"].includes(candidate?.kind)?"call":candidate?.kind;
    const scene=classifyScene({street:snapshot?.street,action,priorActions:current,handActions:snapshot?.actions||[],heroSeat:hero?.seat,heroPosition:snapshot?.heroPosition,preflopRaiseCount:snapshot?.preflopFullRaiseCount,...position});
    if(scene)return scene;
    if(action==="fold"&&snapshot?.street!=="preflop")return Number(snapshot?.callAmount)>0?"面对下注弃牌":"可让牌时弃牌";
    if(action!=="fold")return null;
    const raises=Math.max(Number(snapshot?.preflopFullRaiseCount)||0,current.filter(item=>["raise","reraise"].includes(item.action)||item.action==="allin"&&item.fullRaise===true).length);
    if(raises>=3)return "面对4下注弃牌";
    if(raises===2)return "面对3下注弃牌";
    if(raises===1)return "面对开局加注弃牌";
    if(current.some(item=>item.action==="straddle"))return "面对Straddle弃牌";
    return "翻牌前弃牌";
  }

  function decisionContext(snapshot,candidates=[]){
    return {decisionId:snapshot?.decisionId||null,street:snapshot?.street||null,actionRound:Number(snapshot?.actionRound)||0,candidateScenes:(candidates||[]).map((candidate,index)=>({candidateIndex:Number.isInteger(candidate?.candidateIndex)?candidate.candidateIndex:index,kind:candidate?.kind||null,amount:Number.isFinite(Number(candidate?.amount))?Number(candidate.amount):null,scene:candidateScene(snapshot,candidate)}))};
  }

  function decisionCandidates(candidates=[]){
    return (candidates||[]).map((candidate,index)=>({...candidate,candidateIndex:Number.isInteger(candidate?.candidateIndex)?candidate.candidateIndex:index}));
  }

  function preflopScore(cards){
    const values=cards.map(cardValue).sort((a,b)=>b-a),pair=values[0]===values[1],suited=cards[0][1]===cards[1][1],gap=values[0]-values[1];
    let score=(values[0]*2.2+values[1]*1.2+(suited?3.2:0)-Math.max(0,gap-1)*1.5)/52;
    if(pair)score=.38+values[0]/22;
    if(values[0]===14)score+=.05;
    return Math.max(0,Math.min(1,score));
  }
  let preflopScoreDistribution=null;
  function preflopPercentile(cards){
    if(!Array.isArray(cards)||cards.length!==2)return null;
    if(!preflopScoreDistribution)preflopScoreDistribution=ALL_COMBOS.map(item=>preflopScore(item.cards)).sort((left,right)=>left-right);
    const score=preflopScore(cards),index=preflopScoreDistribution.findLastIndex(item=>item<=score);
    return index<0?0:index/(preflopScoreDistribution.length-1);
  }
  function madeScore(cards,board){
    if(board.length<3||!CORE?.evaluate)return preflopScore(cards);
    const rank=CORE.evaluate([...cards,...board]);
    if(!Array.isArray(rank))return preflopScore(cards);
    const made=Math.max(0,Math.min(1,(Number(rank[0])||0)/8+((Number(rank[1])||0)/14)/12));
    if(board.length>=5)return made;
    const all=[...cards,...board],bySuit=new Map();
    all.forEach(card=>bySuit.set(card[1],[...(bySuit.get(card[1])||[]),cardValue(card)]));
    let draw=0;
    for(const [suit,values] of bySuit){
      if(values.length===4){
        const holeValues=cards.filter(card=>card[1]===suit).map(cardValue),nutBlocker=holeValues.includes(14);
        draw=Math.max(draw,.38+(nutBlocker?.08:Math.max(0,...holeValues)/14*.04));
      }else if(values.length>=3&&cards.some(card=>card[1]===suit))draw=Math.max(draw,.12);
    }
    const unique=[...new Set(all.map(cardValue))];if(unique.includes(14))unique.push(1);
    let straightDraw=0;
    for(let low=1;low<=10;low++){
      const hits=[low,low+1,low+2,low+3,low+4].filter(value=>unique.includes(value)).length;
      if(hits===4)straightDraw=Math.max(straightDraw,low===1||low===10?.24:.31);
      else if(hits===3)straightDraw=Math.max(straightDraw,.10);
    }
    draw=Math.max(draw,straightDraw);
    if(draw>=.30&&straightDraw>=.24&&[...bySuit.values()].some(values=>values.length===4))draw=Math.min(.58,draw+.10);
    const boardHigh=Math.max(...board.map(cardValue)),overcards=cards.filter(card=>cardValue(card)>boardHigh).length;
    draw=Math.max(draw,overcards*.055);
    return Math.max(made,Math.min(1,made+draw*.55),draw);
  }
  function comboScores(combos,board){
    const values=combos.map(item=>madeScore(item.cards,board)),ordered=[...values].sort((a,b)=>a-b);
    return values.map(value=>({raw:value,percentile:ordered.length<=1?1:ordered.findLastIndex(item=>item<=value)/(ordered.length-1)}));
  }
  const boardPercentileCache=new Map();
  function boardPercentiles(board){
    const key=(board||[]).join("");
    if(boardPercentileCache.has(key))return boardPercentileCache.get(key);
    const blocked=new Set(board||[]),combos=ALL_COMBOS.filter(item=>item.cards.every(card=>!blocked.has(card))),scores=comboScores(combos,board||[]),result=new Map(combos.map((item,index)=>[item.key,scores[index].percentile]));
    boardPercentileCache.set(key,result);while(boardPercentileCache.size>64)boardPercentileCache.delete(boardPercentileCache.keys().next().value);
    return result;
  }
  const sigmoid=value=>1/(1+Math.exp(-value));
  function baselineActionLikelihood({action,percentile,street,scene,position,sizeRatio,platform,actionEvidence,actionWeight=0}={}){
    const vpip=Number(platform?.vpipRate),pfr=Number(platform?.pfrRate),late=["dealer","cutoff","hijack","late"].includes(position);
    let continueShare=Number.isFinite(vpip)?Math.max(.08,Math.min(.85,vpip)):late?.36:.25;
    let raiseShare=Number.isFinite(pfr)?Math.max(.04,Math.min(.60,pfr)):late?.24:.15;
    if(scene==="3下注"||scene==="挤压加注")raiseShare=Math.min(raiseShare,.12);
    if(scene==="4下注"||scene==="再次加注")raiseShare=Math.min(raiseShare,.055);
    if(street!=="preflop"){continueShare=.48;raiseShare=.24}
    const counts=actionEvidence?.actionCounts||{},sampleCount=Number(actionEvidence?.sampleCount)||0;
    if(sampleCount>0&&actionWeight>0){
      const observedContinue=["call","bet","raise","reraise","allin"].reduce((sum,key)=>sum+Number(counts[key]||0),0)/sampleCount;
      const observedRaise=["bet","raise","reraise","allin"].reduce((sum,key)=>sum+Number(counts[key]||0),0)/sampleCount;
      continueShare=continueShare*(1-actionWeight)+observedContinue*actionWeight;
      raiseShare=raiseShare*(1-actionWeight)+observedRaise*actionWeight;
    }
    const continueLine=1-continueShare,raiseLine=1-raiseShare,steepness=street==="preflop"?11:8;
    const continueChance=sigmoid((percentile-continueLine)*steepness),raiseChance=sigmoid((percentile-raiseLine)*steepness);
    const sizePenalty=Math.max(0,(Number(sizeRatio)||0)-.75)*.35;
    if(action==="fold")return Math.max(.01,1-continueChance+sizePenalty);
    if(action==="check")return .35+.45*(1-raiseChance);
    if(action==="call")return Math.max(.01,continueChance*(1-.72*raiseChance)-sizePenalty);
    if(["bet","raise","reraise"].includes(action))return Math.max(.01,raiseChance*(1-sizePenalty));
    if(action==="allin")return Math.max(.005,sigmoid((percentile-.94)*18));
    return .25;
  }
  function evidenceBucket(evidence,event){
    const buckets=evidence?.buckets||[],street=event.street||"preflop",facing=event.facingAction||null,position=event.position||"unknown";
    const scored=buckets.map(bucket=>{
      if(bucket.street!==street)return null;
      let score=0;
      if((bucket.facingAction||null)===(facing||null))score+=4;
      if(bucket.position===position)score+=2;
      if(bucket.boardClass===(event.boardClass||"preflop"))score+=1;
      return {bucket,score};
    }).filter(Boolean).sort((a,b)=>b.score-a.score||b.bucket.sampleCount-a.bucket.sampleCount);
    return scored[0]?.bucket||null;
  }
  function normalizedDistribution(items){
    const total=items.reduce((sum,item)=>sum+Math.max(0,item.weight),0)||1;
    return items.map(item=>({...item,probability:Math.max(0,item.weight)/total}));
  }
  function rangeConcentration(combos,coverageTarget=.8){
    const ordered=[...(combos||[])].sort((left,right)=>Number(right.probability)-Number(left.probability)),target=Math.max(.5,Math.min(.95,Number(coverageTarget)||.8));let cumulative=0,coreComboCount=0;
    for(const item of ordered){if(cumulative>=target)break;cumulative+=Number(item.probability)||0;coreComboCount++}
    const legalComboCount=ordered.length,corePercent=legalComboCount?coreComboCount/legalComboCount:0,label=corePercent<=.3?"很集中":corePercent<=.5?"较集中":corePercent<=.7?"中等":"较宽";
    return {coverageTarget:target,legalComboCount,coreComboCount,corePercent,label};
  }
  function matrixClass(row,column){
    if(row===column)return MATRIX_RANKS[row]+MATRIX_RANKS[column];
    return row<column?MATRIX_RANKS[row]+MATRIX_RANKS[column]+"s":MATRIX_RANKS[column]+MATRIX_RANKS[row]+"o";
  }
  function strongDraw(cards,board){
    const all=[...cards,...board],suits=new Map();all.forEach(card=>suits.set(card[1],(suits.get(card[1])||0)+1));
    if([...suits].some(([suit,count])=>count===4&&cards.some(card=>card[1]===suit)))return true;
    const values=[...new Set(all.map(cardValue))];if(values.includes(14))values.push(1);
    for(let low=1;low<=10;low++){const run=[low,low+1,low+2,low+3,low+4],hits=run.filter(value=>values.includes(value));if(hits.length===4&&cards.some(card=>run.includes(cardValue(card))&&!board.some(boardCard=>cardValue(boardCard)===cardValue(card))))return true}
    return false;
  }
  function rangeStatistics(range,board=[],coverageTarget=.8){
    const byClass=new Map();
    for(const item of range?.combos||[]){const row=byClass.get(item.classKey)||{probability:0,legalCombos:0};row.probability+=Number(item.probability)||0;row.legalCombos++;byClass.set(item.classKey,row)}
    const maxAverage=Math.max(0,...[...byClass.values()].map(item=>item.legalCombos?item.probability/item.legalCombos:0)),matrix=[];
    for(let row=0;row<13;row++)for(let column=0;column<13;column++){const combo=matrixClass(row,column),item=byClass.get(combo)||{probability:0,legalCombos:0},average=item.legalCombos?item.probability/item.legalCombos:0,relativeWeight=maxAverage?average/maxAverage:0;matrix.push({combo,probability:item.probability,legalCombos:item.legalCombos,relativeWeight,level:!item.legalCombos?"blocked":relativeWeight>=.65?"high":relativeWeight>=.3?"medium":relativeWeight>=.12?"low":"trace"})}
    const preflopShape={pair:0,suited:0,offsuit:0},postflop={strongMade:0,onePair:0,strongDraw:0,highCard:0};
    for(const item of range?.combos||[]){const probability=Number(item.probability)||0;if(item.classKey.length===2)preflopShape.pair+=probability;else if(item.classKey.endsWith("s"))preflopShape.suited+=probability;else preflopShape.offsuit+=probability;if(board.length>=3){const made=CORE?.evaluate?.([...item.cards,...board]);if(Number(made?.[0])>=2)postflop.strongMade+=probability;else if(Number(made?.[0])===1)postflop.onePair+=probability;else if(strongDraw(item.cards,board))postflop.strongDraw+=probability;else postflop.highCard+=probability}}
    return {concentration:rangeConcentration(range?.combos,coverageTarget),matrix,preflopShape,postflop:board.length>=3?postflop:null};
  }
  function buildRange({knownCards=[],board=[],actions=[],profile={},evidence=null,profileEnabled=true,collectStages=false}={}){
    const known=new Set(knownCards),combos=ALL_COMBOS.filter(item=>item.cards.every(card=>!known.has(card))),scores=comboScores(combos,board);
    let current=combos.map((combo,index)=>({...combo,weight:1,score:scores[index].raw,percentile:scores[index].percentile}));
    const platform=profileEnabled?profile.platformStatistics||{}:{},nAction=Number(evidence?.nAction??profile.decisionSampleCount)||0,nShow=Number(evidence?.nShow??profile.verifiedDecisionSampleCount??profile.revealedHands)||0;
    let aTier=actionTier(nAction),hTier=showTier(nShow);const steps=[],rangeStages=[];
    for(const rawEvent of actions){
      const event={...rawEvent,action:normalizeAction(rawEvent.action)},scene=classifyScene({street:event.street,action:event.action,priorActions:event.priorActions||[],handActions:actions,heroSeat:event.seat,heroPosition:event.position,preflopRaiseCount:event.preflopRaiseCount});
      const sceneEvidence=profileEnabled&&CORE?.matchingSceneEvidence?CORE.matchingSceneEvidence({...profile,modelEvidence:evidence||profile.modelEvidence||{}},event):null,bucket=sceneEvidence?.bucket||(profileEnabled?evidenceBucket(evidence,event):null),shown=bucket?.verifiedClasses?.[event.action]||{},shownTotal=Object.values(shown).reduce((sum,value)=>sum+Number(value||0),0),classBase=shownTotal+ALL_CLASSES.length;
      const eventActionTier=actionTier(bucket?.sampleCount||0),eventShowTier=showTier(shownTotal);aTier=eventActionTier;hTier=eventShowTier;
      current=current.map(item=>{
        const base=baselineActionLikelihood({action:event.action,percentile:item.percentile,street:event.street,scene,position:event.position,sizeRatio:event.betPotRatio,platform,actionEvidence:bucket,actionWeight:eventActionTier.weight});
        const empirical=shownTotal?(Number(shown[item.classKey]||0)+1)/classBase:base;
        const likelihood=base*(1-eventShowTier.weight)+empirical*eventShowTier.weight;
        return {...item,weight:item.weight*Math.max(.000001,likelihood)};
      });
      current=normalizedDistribution(current).map(item=>({...item,weight:item.probability}));
      steps.push({action:event.action,scene,bucketMatch:bucket?.matchTier||bucket?.key||null,nAction:bucket?.sampleCount||0,nShow:shownTotal,actionTier:eventActionTier.tier,showTier:eventShowTier.tier});
      if(collectStages)rangeStages.push({street:event.street,action:event.action,scene,...rangeConcentration(current,.8)});
    }
    current=normalizedDistribution(current);
    const cells=new Map();
    current.forEach(item=>cells.set(item.classKey,(cells.get(item.classKey)||0)+item.probability));
    const topClasses=[...cells].sort((a,b)=>b[1]-a[1]).slice(0,10).map(([combo,probability])=>({combo,probability}));
    const topCombos=[...current].sort((a,b)=>b.probability-a.probability).slice(0,10).map(item=>({cards:item.cards,combo:item.classKey,probability:item.probability}));
    return {modelVersion:MODEL_VERSION,comboCount:current.length,totalProbability:current.reduce((sum,item)=>sum+item.probability,0),combos:current,cells:Object.fromEntries(cells),topClasses,topCombos,steps,rangeStages,actionTier:aTier,showTier:hTier,source:actions.length?profileEnabled?"baseline_plus_profile_evidence":"reviewed_baseline":"unconditioned_legal_combos",calibrated:false};
  }
  function eventContexts(snapshot,seat){
    const hand=snapshot.actions||[],actions=hand.filter(item=>Number(item.seat)===Number(seat));
    return actions.map(event=>{
      const rawPrior=hand.filter(item=>item.street===event.street&&Number(item.sequence)<Number(event.sequence)),prior=[],bigBlind=Math.max(.000001,Number(snapshot.blindBig)||.01);let highest=0,minimumIncrement=bigBlind,raises=0;
      for(const item of rawPrior){
        const amount=Number(item.amount),action=item.action;
        if(["blind","post_blind","straddle"].includes(action)&&Number.isFinite(amount)&&amount>highest){highest=amount;if(action==="straddle")minimumIncrement=Math.max(minimumIncrement,amount);prior.push(item);continue}
        if(["raise","reraise","allin"].includes(action)&&Number.isFinite(amount)&&amount>highest){const increase=Number.isFinite(Number(item.increase))?Number(item.increase):amount-highest,fullRaise=increase+1e-9>=minimumIncrement;if(fullRaise){raises++;minimumIncrement=increase}highest=amount;prior.push({...item,fullRaise});continue}
        if(Number.isFinite(amount))highest=Math.max(highest,amount);prior.push(item);
      }
      const facing=[...prior].reverse().find(item=>["bet","raise","reraise","allin"].includes(item.action));
      const increase=Number(event.increase),potBefore=Number(event.potBefore),betPotRatio=Number(event.betPotRatio),derivedRatio=Number.isFinite(increase)&&Number.isFinite(potBefore)&&potBefore>0?increase/potBefore:null,boardCount={preflop:0,flop:3,turn:4,river:5}[event.street],fallbackBoard=Number.isInteger(boardCount)&&(snapshot.boardCards||[]).length>=boardCount?(snapshot.boardCards||[]).slice(0,boardCount):[];
      return {...event,position:event.position||snapshot.seats?.find(item=>Number(item.seat)===Number(seat))?.position||"unknown",priorActions:prior,handActions:hand,preflopRaiseCount:raises,facingAction:facing?.action||null,betPotRatio:Number.isFinite(betPotRatio)?betPotRatio:derivedRatio,boardClass:event.boardClass||boardClass(event.boardAtAction||fallbackBoard)};
    });
  }
  function boardClass(board){
    if(!board?.length)return "preflop";
    const ranks=board.map(card=>card[0]),suits=board.map(card=>card[1]),paired=new Set(ranks).size<ranks.length,maxSuit=Math.max(...[...new Set(suits)].map(suit=>suits.filter(item=>item===suit).length));
    return `${paired?"paired":"unpaired"}_${maxSuit>=3?"monotone":maxSuit===2?"two_tone":"rainbow"}`;
  }
  function rangeAudit(snapshot){
    const known=[...(snapshot.heroCards||[]),...(snapshot.boardCards||[])],result=[];
    for(const seat of snapshot.seats||[]){
      if(seat.isHero||seat.empty||["fold","empty"].includes(seat.action))continue;
      const profile=snapshot.opponentProfiles?.[String(seat.index)]||{},evidence=profile.modelEvidence||null,actions=eventContexts(snapshot,Number(seat.index)+1);
      const baseline=buildRange({knownCards:known,board:snapshot.boardCards,actions,profile,evidence,profileEnabled:false});
      const profiled=buildRange({knownCards:known,board:snapshot.boardCards,actions,profile,evidence,profileEnabled:true});
      result.push({seat:Number(seat.index)+1,name:seat.name||profile.name||"",platformHands:Number(profile.platformStatistics?.levelHands)||0,default:baseline,profiled,applied:baseline,shadowOnly:true,allowedToChangeAction:false,reason:"画像范围当前仅旁路审计，尚未通过留出亮牌校准"});
    }
    return {modelVersion:MODEL_VERSION,generatedAt:Date.now(),shadowOnly:true,players:result};
  }

  function compactRangeAudit(audit,decisionId){
    const probabilityDistance=(left,right)=>{
      const keys=new Set([...Object.keys(left||{}),...Object.keys(right||{})]);
      return [...keys].reduce((sum,key)=>sum+Math.abs(Number(left?.[key]||0)-Number(right?.[key]||0)),0)/2;
    };
    const bands=range=>{
      const ordered=Object.entries(range?.cells||{}).sort((left,right)=>right[1]-left[1]);
      return Object.fromEntries([.10,.25,.50].map(target=>{
        let cumulative=0,index=0;
        while(index<ordered.length&&cumulative<target){cumulative+=ordered[index][1];index++}
        return [`top${Math.round(target*100)}`,{classes:ordered.slice(0,index).map(([combo])=>combo),probability:cumulative}];
      }));
    };
    return {
      modelVersion:audit?.modelVersion||MODEL_VERSION,
      decisionId:decisionId||null,
      generatedAt:audit?.generatedAt||Date.now(),
      shadowOnly:true,
      players:(audit?.players||[]).map(player=>({
        seat:player.seat,name:player.name||"",platformHands:Number(player.platformHands)||0,shadowOnly:true,
        allowedToChangeAction:false,reason:player.reason,
        difference:probabilityDistance(player.default?.cells,player.profiled?.cells),
        defaultTop:player.default?.topClasses||[],
        profiledTop:player.profiled?.topClasses||[],
        remainingCombos:Number(player.profiled?.comboCount)||0,
        defaultCells:clone(player.default?.cells||{}),
        profiledCells:clone(player.profiled?.cells||{}),
        topCombos:clone(player.profiled?.topCombos||[]),
        defaultBands:bands(player.default),profiledBands:bands(player.profiled),
        actionTier:player.profiled?.actionTier||actionTier(0),
        showTier:player.profiled?.showTier||showTier(0),
        steps:player.profiled?.steps||[],
      })),
    };
  }

  function opponentHandPredictions(snapshot,{displayDecimals=1,maxCombos=48,maxGroups=8,coverageTarget=.9}={}){
    const known=[...(snapshot?.heroCards||[]),...(snapshot?.boardCards||[])],folded=new Set((snapshot?.actions||[]).filter(item=>item.action==="fold").map(item=>Number(item.seat))),players=[];
    for(const seat of snapshot?.seats||[]){
      if(seat.isHero||seat.empty||seat.action==="empty")continue;
      const seatNumber=Number(seat.seat??Number(seat.index)+1),profile=snapshot.opponentProfiles?.[String(seat.index)]||{},actions=eventContexts(snapshot,seatNumber),isFolded=folded.has(seatNumber)||seat.action==="fold",common={seat:seatNumber,name:seat.name||profile.name||"",position:seat.position||"unknown",currentAction:isFolded?"fold":actions.at(-1)?.action||seat.action||"waiting",street:snapshot.street||"waiting",folded:isFolded,calibrated:false,source:"baseline_plus_profile_evidence_shadow",actionHistory:actions.map(item=>({street:item.street,action:item.action,amount:Number.isFinite(Number(item.amount))?Number(item.amount):null,betPotRatio:Number.isFinite(Number(item.betPotRatio))?Number(item.betPotRatio):null,sequence:Number(item.sequence)||0,facingAction:item.facingAction||null,position:item.position||"unknown",boardClass:item.boardClass||null,effectiveStackBb:Number.isFinite(Number(item.effectiveStackBb))?Number(item.effectiveStackBb):null,playerCount:Number.isFinite(Number(item.playerCount))?Number(item.playerCount):null}))};
      if(isFolded){players.push({...common,status:"folded",groups:[],displayedCoverage:0,remainingCombos:0,coreCoverageCombos:0,steps:[]});continue}
      if(seat.inHand===false){players.push({...common,status:"not_in_hand",groups:[],displayedCoverage:0,remainingCombos:0,coreCoverageCombos:0,steps:[]});continue}
      const evidence=profile.modelEvidence||null,range=buildRange({knownCards:known,board:snapshot.boardCards||[],actions,profile,evidence,profileEnabled:true}),ordered=[...range.combos].sort((left,right)=>right.probability-left.probability),groups=[],byDisplay=new Map();
      for(const item of ordered){
        const percent=Number((item.probability*100).toFixed(displayDecimals)),key=percent.toFixed(displayDecimals),group=byDisplay.get(key)||{displayPercent:percent,combos:[],probability:0};
        group.combos.push({cards:[...item.cards],combo:item.classKey,probability:item.probability});group.probability+=item.probability;group.totalCombos=group.combos.length;
        if(!byDisplay.has(key)){byDisplay.set(key,group);groups.push(group)}
      }
      let cumulative=0,coreCoverageCombos=0;
      for(const item of ordered){if(cumulative>=coverageTarget)break;cumulative+=item.probability;coreCoverageCombos++}
      const visibleCount=Math.max(1,Math.min(maxGroups,groups.length)),perGroupLimit=Math.max(1,Math.floor(maxCombos/visibleCount)),visibleGroups=groups.slice(0,maxGroups).map(group=>({...group,combos:group.combos.slice(0,perGroupLimit),hiddenCombos:Math.max(0,group.totalCombos-perGroupLimit)})),visibleCombos=visibleGroups.flatMap(group=>group.combos);
      players.push({...common,status:"active",remainingCombos:range.comboCount,coreCoverageCombos,coverageTarget,displayedComboCount:visibleCombos.length,displayedCoverage:visibleCombos.reduce((sum,item)=>sum+item.probability,0),groups:visibleGroups,hiddenGroupCount:Math.max(0,groups.length-maxGroups),actionTier:range.actionTier,showTier:range.showTier,steps:range.steps,topClasses:range.topClasses});
    }
    return {modelVersion:MODEL_VERSION,generatedAt:Date.now(),handId:snapshot?.handId||0,street:snapshot?.street||"waiting",boardCards:[...(snapshot?.boardCards||[])],calibrated:false,probabilityLabel:"模型推定概率（未校准）",players};
  }

  function opponentRangeStatistics(snapshot,{coverageTarget=.8}={}){
    const known=[...(snapshot?.heroCards||[]),...(snapshot?.boardCards||[])],folded=new Set((snapshot?.actions||[]).filter(item=>item.action==="fold").map(item=>Number(item.seat))),players=[];
    for(const seat of snapshot?.seats||[]){
      if(seat.isHero||seat.empty||seat.action==="empty")continue;
      const seatNumber=Number(seat.seat??Number(seat.index)+1),profile=snapshot.opponentProfiles?.[String(seat.index)]||{},actions=eventContexts(snapshot,seatNumber),isFolded=folded.has(seatNumber)||seat.action==="fold",common={seat:seatNumber,name:seat.name||profile.name||"",position:seat.position||"unknown",currentAction:isFolded?"fold":actions.at(-1)?.action||seat.action||"waiting",street:snapshot.street||"waiting",folded:isFolded,actionHistory:actions.map(item=>({street:item.street,action:item.action,amount:Number.isFinite(Number(item.amount))?Number(item.amount):null,betPotRatio:Number.isFinite(Number(item.betPotRatio))?Number(item.betPotRatio):null,sequence:Number(item.sequence)||0,facingAction:item.facingAction||null,position:item.position||"unknown",boardClass:item.boardClass||null,effectiveStackBb:Number.isFinite(Number(item.effectiveStackBb))?Number(item.effectiveStackBb):null,playerCount:Number.isFinite(Number(item.playerCount))?Number(item.playerCount):null}))};
      if(isFolded){players.push({...common,status:"folded"});continue}
      if(seat.inHand===false){players.push({...common,status:"not_in_hand"});continue}
      const range=buildRange({knownCards:known,board:snapshot.boardCards||[],actions,profile,evidence:profile.modelEvidence||null,profileEnabled:true,collectStages:true}),statistics=rangeStatistics(range,snapshot.boardCards||[],coverageTarget);
      players.push({...common,status:"active",...statistics,rangeStages:range.rangeStages,actionTier:range.actionTier,showTier:range.showTier,steps:range.steps,calibrated:false});
    }
    return {modelVersion:MODEL_VERSION,generatedAt:Date.now(),handId:snapshot?.handId||0,street:snapshot?.street||"waiting",boardCards:[...(snapshot?.boardCards||[])],calibrated:false,label:"范围统计（模型估计）",players};
  }

  function buildDecisionSnapshot(state){
    const sourceSeats=state?.seats||[],occupied=sourceSeats.filter(seat=>!seat.empty&&seat.action!=="empty"),handPlayers=Array.isArray(state?.handParticipants)&&state.handParticipants.length>=2?state.handParticipants.length:Number.isInteger(state?.activePlayerCount)?state.activePlayerCount:occupied.length,dealer=Number.isInteger(state?.dealerIndex)?state.dealerIndex:Number.isInteger(state?.dealerSeat)?state.dealerSeat-1:null,ordered=Number.isInteger(dealer)?[...occupied].sort((left,right)=>((Number(left.index)-dealer+sourceSeats.length)%sourceSeats.length)-((Number(right.index)-dealer+sourceSeats.length)%sourceSeats.length)):occupied,labels={2:["dealer","big_blind"],3:["dealer","small_blind","big_blind"],4:["dealer","small_blind","big_blind","cutoff"],5:["dealer","small_blind","big_blind","under_the_gun","cutoff"],6:["dealer","small_blind","big_blind","under_the_gun","hijack","cutoff"],7:["dealer","small_blind","big_blind","under_the_gun","middle","hijack","cutoff"],8:["dealer","small_blind","big_blind","under_the_gun","under_the_gun_plus_one","middle","hijack","cutoff"]},positionMap=new Map(ordered.map((seat,index)=>[Number(seat.index),labels[ordered.length]?.[index]||"unknown"])),straddleEvent=state?.actionLog?.find(item=>item.handId===state.handId&&item.action==="straddle"),straddleIndex=Number(straddleEvent?.seat)-1,forcedStraddle=PREFLOP?.straddleAllowed(handPlayers,true)&&(Number(state?.blindStraddle)>0||Number.isInteger(straddleIndex)),fallbackStraddlePosition=["under_the_gun","cutoff","dealer"].find(position=>[...positionMap.values()].includes(position)),fallbackStraddleSeat=ordered.find(seat=>positionMap.get(Number(seat.index))===fallbackStraddlePosition);if(forcedStraddle&&Number.isInteger(straddleIndex)&&positionMap.has(straddleIndex))positionMap.set(straddleIndex,"straddle");else if(forcedStraddle&&fallbackStraddleSeat)positionMap.set(Number(fallbackStraddleSeat.index),"straddle");
    const participants=Array.isArray(state?.handParticipants)&&state.handParticipants.length>=2?new Set(state.handParticipants.map(Number)):null,seats=sourceSeats.map(seat=>({index:Number(seat.index),seat:Number(seat.index)+1,name:seat.name||"",chips:Number.isFinite(seat.chips)?seat.chips:null,streetBet:Number.isFinite(seat.streetBet)?seat.streetBet:null,action:seat.action||null,empty:!!seat.empty,inHand:!participants||participants.has(Number(seat.index)+1),isHero:Number(seat.index)===(state.layout==="6max"?3:4),position:positionMap.get(Number(seat.index))||"unknown"}));
    const actions=(state?.actionLog||[]).filter(item=>item.handId===state.handId).map(item=>clone(item)),heroSeat=(state?.layout==="6max"?3:4)+1,sidePotContract=CORE?.buildSidePotContractFromState?.(state,heroSeat)||null;
    return deepFreeze({snapshotVersion:2,modelVersion:MODEL_VERSION,features:FEATURES,runtimeId:state?.runtimeId||null,tableSession:Number(state?.tableSession)||0,tableNumber:state?.tableNumber||null,handId:Number(state?.handId)||0,decisionId:JSON.stringify([state?.runtimeId||null,state?.tableSession,state?.handId,state?.street,Number(state?.actionButtonSequence)||0]),street:state?.street||"waiting",actionRound:Number(state?.actionRound)||0,frameCapturedAt:Number(state?.decisionDataFrameCapturedAt)||null,frameSequence:Number.isInteger(state?.decisionDataFrameSequence)?state.decisionDataFrameSequence:null,buttonDetectedAt:Number(state?.actionButtonDetectedAt)||null,buttonFrameSequence:Number.isInteger(state?.actionButtonFrameSequence)?state.actionButtonFrameSequence:null,dealerSeat:Number.isInteger(state?.dealerSeat)?state.dealerSeat:Number.isInteger(state?.dealerIndex)?state.dealerIndex+1:null,heroPosition:forcedStraddle?state?.heroPosition||"unknown":state?.heroPosition==="straddle"?(positionMap.get(sourceSeats.find(seat=>Number(seat.index)===(state.layout==="6max"?3:4))?.index)||"unknown"):state?.heroPosition||"unknown",heroCards:[...(state?.heroCards||[])],boardCards:[...(state?.boardCards||[])],pot:Number.isFinite(state?.pot)?state.pot:null,callAmount:Number.isFinite(state?.callAmount)?state.callAmount:null,minRaiseTo:Number.isFinite(state?.minRaiseTo)?state.minRaiseTo:null,preflopFullRaiseCount:Number.isInteger(state?.preflopFullRaiseCount)?state.preflopFullRaiseCount:null,rakeRate:Number.isFinite(state?.rakeRate)?state.rakeRate:null,rakeCap:Number.isFinite(state?.rakeCap)?state.rakeCap:null,rakePlayers:Number.isInteger(state?.rakePlayers)?state.rakePlayers:null,sidePotContract,blindTextRaw:state?.blindTextRaw||null,blindCurrency:state?.blindCurrency||state?.currency||null,blindSmall:Number.isFinite(state?.blindSmall)?state.blindSmall:null,blindBig:Number.isFinite(state?.blindBig)?state.blindBig:null,blindStraddle:forcedStraddle&&Number.isFinite(state?.blindStraddle)?state.blindStraddle:null,blindAnte:Number.isFinite(state?.blindAnte)?state.blindAnte:null,activePlayerCount:handPlayers,tablePlay:clone(state?.tablePlay),seats,actions:forcedStraddle?actions:actions.filter(item=>item.action!=="straddle"),decisionChipStacks:clone(state?.decisionChipStacks||{}),opponentProfiles:clone(state?.opponentProfiles||{}),legalButtons:clone(state?.visualButtons||state?.buttons||[]),fieldStatus:clone(state?.fieldStatus||{}),chainClosed:Number(state?.expectedActionSeat)===(state?.layout==="6max"?4:5),reliable:state?.reliable===true});
  }

  function snapshotIssues(snapshot){
    const issues=[],expectedBoard={preflop:0,flop:3,turn:4,river:5}[snapshot?.street];
    if(!Array.isArray(snapshot?.heroCards)||snapshot.heroCards.length!==2||new Set(snapshot.heroCards).size!==2)issues.push("hero_cards_invalid");
    if(expectedBoard===undefined||!Array.isArray(snapshot?.boardCards)||snapshot.boardCards.length!==expectedBoard||new Set(snapshot.boardCards).size!==snapshot.boardCards.length)issues.push("board_cards_invalid");
    if(!Number.isInteger(snapshot?.dealerSeat)||snapshot.dealerSeat<1||snapshot.dealerSeat>(snapshot?.seats?.length||8))issues.push("dealer_invalid");
    if(snapshot?.chainClosed!==true)issues.push("action_chain_open");
    if(!Number.isFinite(snapshot?.pot)||snapshot.pot<0||!Number.isFinite(snapshot?.callAmount)||snapshot.callAmount<0)issues.push("money_invalid");
    if(!Number.isFinite(snapshot?.blindBig)||snapshot.blindBig<=0)issues.push("blind_invalid");
    if(!Number.isFinite(snapshot?.rakeRate)||snapshot.rakeRate<0||!Number.isFinite(snapshot?.rakeCap)||snapshot.rakeCap<0)issues.push("rake_invalid");
    if(snapshot?.sidePotContract?.requiresLayering&&snapshot.sidePotContract.exact!==true)issues.push("side_pot_contract_unresolved");
    if(snapshot?.sidePotContract?.requiresLayering&&snapshot.sidePotContract.evPolicy?.t2T3Supported!==true)issues.push("side_pot_t2t3_unsupported");
    if(!snapshot?.tablePlay?.type)issues.push("table_play_invalid");
    if(!Array.isArray(snapshot?.legalButtons)||!snapshot.legalButtons.length)issues.push("legal_buttons_missing");
    if(snapshot?.reliable!==true)issues.push("recognition_unreliable");
    return issues;
  }

  function formalSceneGate(snapshot,decision,reference=null,errors=[]){
    const best=decision?.best||null,scene=best?candidateScene(snapshot,best):null;
    const family=kind=>kind==="fold"?"fold":kind==="check"?"check":["call","allin_call"].includes(kind)?"call":["quick_bet","custom_raise","minimum_raise","allin"].includes(kind)?"raise":kind||null;
    const hardGateIssues=snapshotIssues(snapshot),amount=Number.isFinite(Number(best?.amount))?Number(best.amount):null,referenceAmount=Number.isFinite(Number(reference?.amount))?Number(reference.amount):null,tolerance=Math.max(.01,Math.abs(Number(snapshot?.pot)||0)*.02),actionMatches=Boolean(best&&reference?.family===family(best.kind)),amountMatches=reference?.family!=="raise"||Number.isFinite(amount)&&Number.isFinite(referenceAmount)&&Math.abs(amount-referenceAmount)<=tolerance,complete=decision?.complete===true&&!errors.length,sceneAllowed=FEATURES.formalV2Scenes.includes(scene),riskClear=!best?.riskGateReason&&best?.selectionEligible!==false,hardGatePassed=!hardGateIssues.length,eligible=Boolean(sceneAllowed&&complete&&actionMatches&&amountMatches&&riskClear&&hardGatePassed);
    const reason=!hardGatePassed?`V2关键输入未通过：${hardGateIssues.join(",")}`:!sceneAllowed?`${scene||"未分类场景"}尚未通过真实回放灰度验收`:!complete?"V2候选或线程结果不完整":!actionMatches?"V2与当前正式动作不一致":!amountMatches?"V2与当前正式加注金额不一致":!riskClear?best?.riskGateReason||"低样本风险门未通过":"V2与当前正式建议一致，进入确认层";
    return{mode:FEATURES.formalV2Mode,scene,sceneAllowed,eligible,applied:false,complete,actionMatches,amountMatches,riskClear,hardGatePassed,hardGateIssues,tolerance,reason};
  }

  function opponentRoles(snapshot){
    const actions=snapshot?.actions||[],hero=snapshot?.seats?.find(seat=>seat.isHero),count=snapshot?.seats?.length||8;
    const active=(snapshot?.seats||[]).filter(seat=>!seat.isHero&&!seat.empty&&!["fold","empty"].includes(seat.action));
    return active.map(seat=>{
      const own=actions.filter(event=>Number(event.seat)===Number(seat.seat)),voluntaryActions=own.filter(event=>voluntary(normalizeAction(event.action)));
      const forcedStraddle=own.some(event=>event.action==="straddle"),last=voluntaryActions.at(-1)?.action;
      const role=last==="allin"||seat.action==="allin"?"allin":["raise","reraise","bet"].includes(last)?"raiser":last==="call"?"caller":forcedStraddle?"forced_straddle":"unacted";
      return {seat:seat.seat,name:seat.name,role,order:hero?(seat.seat-hero.seat+count)%count:seat.seat};
    }).sort((left,right)=>left.order-right.order);
  }

  function participationResponseTree(snapshot,rangePlayers,candidate,responseFor){
    if(snapshot?.street!=="preflop"||!PREFLOP)return null;
    const participants=PREFLOP.snapshotParticipants(snapshot,rangePlayers),responsiveCommitted=participants.committed.filter(player=>player.role!=="allin"),locked=participants.committed.filter(player=>player.role==="allin"),responders=[...participants.unacted,...responsiveCommitted].sort((left,right)=>left.order-right.order);
    const tree=PREFLOP.continuationTree({locked,responders,responseFor});
    return{...tree,participants};
  }

  function responseTreeFromEstimate(estimate){
    if(!estimate)return null;
    const personalSampleCount=Math.max(Number(estimate.minPersonalSamples)||0,Number(estimate.sampleCount)||0),populationSampleCount=Math.max(Number(estimate.minPopulationSamples)||0,Number(estimate.populationSampleCount)||0),sampleMetadata={personalSampleCount,populationSampleCount,conditionalEquitySource:estimate.conditionalEquitySource||null};
    if(Array.isArray(estimate.paths)&&estimate.paths.length){
      const retained=Math.max(0,Number(estimate.retainedPathProbability))||estimate.paths.reduce((sum,path)=>sum+Math.max(0,Number(path.probability)||0),0),pruned=Math.max(0,Number(estimate.prunedPathProbability)||0),scale=retained>0?Math.min(1,Math.max(0,1-pruned))/retained:0;
      if(retained<=0)return null;
      const paths=estimate.paths.map(path=>({probability:Math.max(0,Number(path.probability)||0)*scale,outcome:path.outcome,callers:Number(path.callers)||0,responses:clone(path.responses||[])}));
      if(pruned>0)paths.push({probability:Math.min(1,pruned),outcome:"raise",callers:0,responses:[],pruned:true});
      const probabilities={fold:0,call:0,raise:0},callCountDistribution={};
      paths.forEach(path=>{if(path.outcome in probabilities)probabilities[path.outcome]+=path.probability;if(path.outcome==="call")callCountDistribution[path.callers]=(callCountDistribution[path.callers]||0)+path.probability});
      const callTotal=probabilities.call||1;
      Object.keys(callCountDistribution).forEach(key=>callCountDistribution[key]/=callTotal);
      const samples=Math.max(Number(estimate.minPersonalSamples)||0,Number(estimate.minPopulationSamples)||0,Number(estimate.sampleCount)||0,Number(estimate.populationSampleCount)||0);
      return {modelVersion:MODEL_VERSION,sequential:true,orderedSeats:clone(estimate.orderedSeats||[]),probabilities,callCountDistribution,paths,retainedProbability:Math.max(0,1-pruned),prunedProbability:pruned,prunedAs:"raise_conservative",sampleCount:samples,...sampleMetadata,responseMargin:samples>0?Math.min(.5,.98/Math.sqrt(samples)):.5};
    }
    const source=estimate.probabilities||estimate,fold=Math.max(0,Number(source.fold)||0),call=Math.max(0,Number(source.call)||0),raise=Math.max(0,Number(source.raise)||0),total=fold+call+raise;
    if(total<=0)return null;
    const paths=[["fold",fold,0],["call",call,Math.max(1,Math.round(Number(estimate.expectedCallers)||1))],["raise",raise,0]].filter(([,value])=>value>0).map(([outcome,value,callers])=>({outcome,probability:value/total,callers,responses:[]}));
    const samples=Math.max(Number(estimate.minPersonalSamples)||0,Number(estimate.minPopulationSamples)||0,Number(estimate.sampleCount)||0,Number(estimate.populationSampleCount)||0);
    return {modelVersion:MODEL_VERSION,sequential:estimate.sequential===true,orderedSeats:clone(estimate.orderedSeats||[]),probabilities:{fold:fold/total,call:call/total,raise:raise/total},callCountDistribution:clone(estimate.callCountDistribution||{}),paths,prunedProbability:0,summaryFallback:true,sampleCount:samples,...sampleMetadata,responseMargin:samples>0?Math.min(.5,.98/Math.sqrt(samples)):.5};
  }

  function baselineResponseTree(snapshot,rangePlayers,candidate){
    const roles=new Map(opponentRoles(snapshot).map(item=>[Number(item.seat),item]));
    const players=(rangePlayers||[]).filter(player=>player?.range&&roles.has(Number(player.seat))).map(player=>({...player,role:roles.get(Number(player.seat)).role,order:roles.get(Number(player.seat)).order})).sort((left,right)=>left.order-right.order);
    const increment=Math.max(0,Number(candidate?.amount)-Number(snapshot?.callAmount||0)),sizeRatio=increment/Math.max(.000001,Number(snapshot?.pot)||0);
    const responseFor=player=>{
      const response=rangeResponse(player.range,{street:snapshot?.street||"preflop",position:player.position||"unknown",sizeRatio,board:snapshot?.boardCards||[]});
      return candidate?.kind==="allin"?{fold:response.fold,call:response.call+response.raise,raise:0}:response;
    },tree=participationResponseTree(snapshot,players,candidate,responseFor)||sequentialTree({opponents:players,responseFor});
    return {...tree,sampleTier:"S0",sampleCount:0,source:"reviewed_default_combo_range_prior",uncalibrated:true,responseMargin:.5,opponentSources:players.map(player=>({seat:player.seat,source:player.range?.source||"reviewed_baseline"}))};
  }

  function candidateResponseTree(snapshot,rangePlayers,reactions,candidate){
    const estimate=reactionForCandidate(reactions,candidate),tree=responseTreeFromEstimate(estimate);
    if(tree&&tree.sampleCount>0)return {...tree,sampleTier:actionTier(tree.sampleCount).tier,source:estimate?.source||"historical_ordered_response",uncalibrated:estimate?.calibrated!==true};
    return baselineResponseTree(snapshot,rangePlayers,candidate);
  }

  function seededRandom(seed){
    let value=2166136261;
    for(const character of String(seed||MODEL_VERSION)){value^=character.charCodeAt(0);value=Math.imul(value,16777619)}
    return()=>{value+=0x6D2B79F5;let mixed=value;mixed=Math.imul(mixed^mixed>>>15,mixed|1);mixed^=mixed+Math.imul(mixed^mixed>>>7,mixed|61);return((mixed^mixed>>>14)>>>0)/4294967296};
  }

  function decisionSeed(snapshot){
    return JSON.stringify([snapshot?.tableNumber||null,snapshot?.tableSession||0,snapshot?.handId||0,snapshot?.street||"waiting",snapshot?.actionRound||0,snapshot?.heroCards||[],snapshot?.boardCards||[],snapshot?.pot??null,snapshot?.callAmount??null,snapshot?.minRaiseTo??null,(snapshot?.actions||[]).map(item=>[item.street,item.seat,item.action,item.amount,item.increase,item.sequence])]);
  }

  function prepareRange(range){
    let cumulative=0;
    const items=(range?.combos||[]).filter(item=>Number(item.probability)>0).map(item=>({cards:item.cards,combo:item.classKey,probability:Number(item.probability),cumulative:cumulative+=Number(item.probability)}));
    return {items,total:cumulative};
  }

  function pickRange(prepared,blocked,random){
    for(let attempt=0;attempt<32;attempt++){
      const target=random()*prepared.total;let low=0,high=prepared.items.length-1;
      while(low<high){const middle=(low+high)>>1;if(prepared.items[middle].cumulative<target)low=middle+1;else high=middle}
      const cards=prepared.items[low]?.cards;if(cards&&cards.every(card=>!blocked.has(card)))return cards;
    }
    return prepared.items.find(item=>item.cards.every(card=>!blocked.has(card)))?.cards||null;
  }

  function weightedEquity({hero,board,players,trials=240,seed="v2"}={}){
    const random=seededRandom(seed),prepared=(players||[]).map(player=>({seat:player.seat,range:prepareRange(player.range)})),known=new Set([...(hero||[]),...(board||[])]),deck=fullDeck().filter(card=>!known.has(card));
    let share=0,accepted=0;
    for(let sample=0;sample<Math.max(1,Number(trials)||1);sample++){
      const blocked=new Set(known),hands=[];let valid=true;
      for(const player of prepared){const cards=pickRange(player.range,blocked,random);if(!cards){valid=false;break}cards.forEach(card=>blocked.add(card));hands.push({seat:player.seat,cards})}
      if(!valid)continue;
      const available=deck.filter(card=>!blocked.has(card)),missing=Math.max(0,5-board.length),runout=[];
      for(let index=0;index<missing;index++){const pick=index+Math.floor(random()*(available.length-index));[available[index],available[pick]]=[available[pick],available[index]];runout.push(available[index])}
      const finalBoard=[...board,...runout],heroRank=CORE.evaluate([...hero,...finalBoard]),opponentRanks=hands.map(item=>CORE.evaluate([...item.cards,...finalBoard])),all=[heroRank,...opponentRanks],best=all.reduce((winner,item)=>CORE.compareRanks(item,winner)>0?item:winner,all[0]),winners=all.filter(item=>CORE.compareRanks(item,best)===0);
      if(CORE.compareRanks(heroRank,best)===0)share+=1/winners.length;
      accepted++;
    }
    const equity=accepted?share/accepted:null,margin=accepted&&Number.isFinite(equity)?1.96*Math.sqrt(Math.max(.000001,equity*(1-equity))/accepted):1;
    return {equity,samples:accepted,interval:[Math.max(0,(equity??0)-margin),Math.min(1,(equity??0)+margin)],source:"weighted_combo_monte_carlo"};
  }

  function conditionedRange(range,{action,street,scene,position,sizeRatio,board}={}){
    const legal=(range?.combos||[]).filter(item=>item.cards.every(card=>!(board||[]).includes(card))),percentiles=boardPercentiles(board||[]),weighted=legal.map(item=>({...item,weight:Number(item.probability||0)*baselineActionLikelihood({action,percentile:percentiles.get(item.key)??.5,street,scene,position,sizeRatio})}));
    return {...range,combos:normalizedDistribution(weighted).map(item=>({...item,probability:item.probability})),source:`${range?.source||"range"}_conditioned_${action}`};
  }

  function rangeResponse(range,{street,position,sizeRatio,board,mode="facing"}={}){
    const legal=(range?.combos||[]).filter(item=>item.cards.every(card=>!(board||[]).includes(card))),percentiles=boardPercentiles(board||[]),totals=mode==="first"?{check:0,bet:0}:{fold:0,call:0,raise:0},preflop=street==="preflop",late=["dealer","cutoff","hijack","late"].includes(position),straddle=position==="straddle",bigBlind=position==="big_blind",smallBlind=position==="small_blind",pressure=Math.log2(1+Math.max(0,Number(sizeRatio)||0)),baseContinue=preflop?(late?.32:straddle?.31:bigBlind?.29:smallBlind?.27:.24):.48,baseRaise=preflop?(straddle?.11:bigBlind?.10:late?.09:smallBlind?.08:.07):.14,continueShare=Math.max(.025,Math.min(.70,baseContinue*Math.exp(-.34*pressure))),raiseShare=Math.max(.008,Math.min(continueShare*.65,baseRaise*Math.exp(-.42*pressure))),continueLine=1-continueShare,raiseLine=1-raiseShare;
    legal.forEach(item=>{
      const probability=Number(item.probability)||0,percentile=percentiles.get(item.key)??.5,continueChance=sigmoid((percentile-continueLine)*(preflop?13:10)),raiseChance=Math.min(continueChance,sigmoid((percentile-raiseLine)*(preflop?18:13)));
      if(mode==="first"){totals.bet+=probability*raiseChance;totals.check+=probability*(1-raiseChance)}
      else{totals.fold+=probability*(1-continueChance);totals.call+=probability*Math.max(0,continueChance-raiseChance);totals.raise+=probability*raiseChance}
    });
    const total=Object.values(totals).reduce((sum,value)=>sum+value,0)||1;
    return Object.fromEntries(Object.entries(totals).map(([action,value])=>[action,value/total]));
  }

  function nextBoards(snapshot,seed,limit=12){
    const known=new Set([...(snapshot.heroCards||[]),...(snapshot.boardCards||[])]),available=fullDeck().filter(card=>!known.has(card)),random=seededRandom(seed);
    if(snapshot.boardCards.length===3||snapshot.boardCards.length===4)return available.map(card=>[...snapshot.boardCards,card]);
    if(snapshot.boardCards.length===0){
      const boards=[],seen=new Set();
      while(boards.length<Math.min(limit,19600)){
        const copy=[...available];for(let index=0;index<3;index++){const pick=index+Math.floor(random()*(copy.length-index));[copy[index],copy[pick]]=[copy[pick],copy[index]]}
        const board=copy.slice(0,3),key=[...board].sort().join("");if(!seen.has(key)){seen.add(key);boards.push(board)}
      }
      return boards;
    }
    return [snapshot.boardCards];
  }

  function futureResponseTree(players,board,snapshot,sizeRatio){
    return sequentialTree({opponents:players,responseFor:opponent=>rangeResponse(opponent.range,{street:snapshot.street==="preflop"?"flop":snapshot.street==="flop"?"turn":"river",position:opponent.position,sizeRatio,board})});
  }

  function rolloutInterval(values,lows,highs){
    if(!values.length)return {value:null,low:null,high:null,samplingMargin:null};
    const value=values.reduce((sum,item)=>sum+item,0)/values.length,low=lows.reduce((sum,item)=>sum+item,0)/lows.length,high=highs.reduce((sum,item)=>sum+item,0)/highs.length;
    const variance=values.length>1?values.reduce((sum,item)=>sum+(item-value)**2,0)/(values.length-1):0,samplingMargin=values.length>1?1.96*Math.sqrt(variance/values.length):0;
    return {value,low:low-samplingMargin,high:high+samplingMargin,samplingMargin};
  }

  function nextStreetRollout({snapshot,players,pot,investment,effective,seed}={}){
    const boards=nextBoards(snapshot,seed),net=gross=>gross-Math.min(Math.max(0,gross)*Math.max(0,Number(snapshot.rakeRate)||0),Number.isFinite(snapshot.rakeCap)?snapshot.rakeCap:Infinity),positionOrder={small_blind:0,big_blind:1,straddle:2,under_the_gun:2,under_the_gun_plus_one:3,middle:4,hijack:5,cutoff:6,dealer:7},heroOrder=positionOrder[snapshot.heroPosition]??4,heroLast=(players||[]).every(player=>(positionOrder[player.position]??4)<heroOrder),values=[],lows=[],highs=[];
    for(let index=0;index<boards.length;index++){
      const board=boards[index],equity=weightedEquity({hero:snapshot.heroCards,board,players,trials:Math.max(6,Math.floor(240/Math.max(1,boards.length))),seed:`${seed}:${index}`});
      if(!Number.isFinite(equity.equity))continue;
      const bet=Math.min(Math.max(0,effective-investment),Math.max(snapshot.blindBig||0,pot*.5));
      if(snapshot.boardCards.length>=5||bet<=0){const gross=net(pot);values.push(equity.equity*gross);lows.push(equity.interval[0]*gross);highs.push(equity.interval[1]*gross);continue}
      if(heroLast){
        const first=(players||[]).map(player=>({player,response:rangeResponse(player.range,{street:snapshot.street==="preflop"?"flop":snapshot.street==="flop"?"turn":"river",position:player.position,sizeRatio:.5,board,mode:"first"})})),noBet=first.reduce((value,item)=>value*(1-item.response.bet),1),bettor=[...first].sort((left,right)=>right.response.bet-left.response.bet)[0]?.player,betRange=bettor?conditionedRange(bettor.range,{action:"bet",street:snapshot.street,position:bettor.position,sizeRatio:.5,board}):null,betPlayers=betRange?(players||[]).map(player=>player.seat===bettor.seat?{...player,range:betRange}:player):players,betEquity=weightedEquity({hero:snapshot.heroCards,board,players:betPlayers,trials:Math.max(5,Math.floor(160/Math.max(1,boards.length))),seed:`${seed}:bet:${index}`}),callValue=Number.isFinite(betEquity.equity)?betEquity.equity*net(pot+2*bet)-bet:0;
        const showdown=net(pot),callLow=Number.isFinite(betEquity.interval?.[0])?betEquity.interval[0]*net(pot+2*bet)-bet:callValue,callHigh=Number.isFinite(betEquity.interval?.[1])?betEquity.interval[1]*net(pot+2*bet)-bet:callValue;
        values.push(noBet*equity.equity*showdown+(1-noBet)*Math.max(0,callValue));lows.push(noBet*equity.interval[0]*showdown+(1-noBet)*Math.max(0,callLow));highs.push(noBet*equity.interval[1]*showdown+(1-noBet)*Math.max(0,callHigh));
      }else{
        const tree=futureResponseTree(players,board,snapshot,.5),betResult=compareActions({candidates:[{kind:"bet",amount:bet}],pot,call:0,effective:Math.max(0,effective-investment),equity:equity.equity,equityInterval:equity.interval,rakeRate:snapshot.rakeRate||0,rakeCap:snapshot.rakeCap,responseTrees:{[`bet:${bet}`]:tree},solveTier:"T1"});
        values.push(Math.max(equity.equity*net(pot),Number(betResult.best?.ev)||-Infinity));lows.push(Math.max(equity.interval[0]*net(pot),Number(betResult.best?.evLow)||-Infinity));highs.push(Math.max(equity.interval[1]*net(pot),Number(betResult.best?.evHigh)||-Infinity));
      }
    }
    const interval=rolloutInterval(values,lows,highs);
    return {ev:Number.isFinite(interval.value)?interval.value-investment:null,evLow:Number.isFinite(interval.low)?interval.low-investment:null,evHigh:Number.isFinite(interval.high)?interval.high-investment:null,routes:values.length,nextBoardMode:snapshot.boardCards.length>=5?"river_showdown":snapshot.boardCards.length===0?"sampled_flops":"exact_next_cards",heroActs:snapshot.boardCards.length>=5?"terminal_showdown":heroLast?"responds_after_opponents":"acts_before_opponents",uncertainty:{method:"equity_interval_plus_board_sampling",samplingMargin:interval.samplingMargin},assumptions:["下一街下注候选为半池","后续终值使用范围加权摊牌权益","只展开下一街首轮动作"]};
  }

  function representativeCallers(tree,rangePlayers,snapshot,candidate){
    const callPaths=(tree.paths||[]).filter(path=>path.outcome==="call"),total=callPaths.reduce((sum,path)=>sum+Number(path.probability||0),0),weights=new Map();
    for(const path of callPaths)for(const response of path.responses||[])if(response.action==="call")weights.set(Number(response.seat),(weights.get(Number(response.seat))||0)+Number(path.probability||0));
    const expected=tree.callCountDistribution&&Object.keys(tree.callCountDistribution).length?Object.entries(tree.callCountDistribution).reduce((sum,[count,probability])=>sum+Number(count)*Number(probability),0):callPaths.reduce((sum,path)=>sum+Number(path.probability||0)*Math.max(1,Number(path.callers)||1),0)/(total||1),count=Math.max(1,Math.min(rangePlayers.length,Math.round(expected)||1));
    return [...rangePlayers].sort((left,right)=>(weights.get(Number(right.seat))||0)-(weights.get(Number(left.seat))||0)).slice(0,count).map(player=>({...player,callPathWeight:(weights.get(Number(player.seat))||0)/(total||1),range:conditionedRange(player.range,{action:"call",street:snapshot.street,scene:"面对下注跟注",position:player.position,sizeRatio:(Number(candidate.amount)-Number(snapshot.callAmount||0))/Math.max(.000001,Number(snapshot.pot)),board:snapshot.boardCards})}));
  }

  function mostLikelyRaiser(tree,rangePlayers){
    const weights=new Map();for(const path of tree.paths||[])for(const response of path.responses||[])if(response.action==="raise")weights.set(Number(response.seat),(weights.get(Number(response.seat))||0)+Number(path.probability||0));
    return [...rangePlayers].sort((left,right)=>(weights.get(Number(right.seat))||0)-(weights.get(Number(left.seat))||0))[0]||null;
  }

  function streetInvestment(snapshot,seat){
    const money=new Set(["blind","post_blind","straddle","call","bet","raise","reraise","allin"]),street=snapshot?.street||"preflop";
    return (snapshot?.actions||[]).filter(item=>item.street===street&&Number(item.seat)===Number(seat)&&money.has(item.action)&&Number.isFinite(Number(item.amount))).reduce((maximum,item)=>Math.max(maximum,Number(item.amount)),0);
  }

  function responsePathGroups(tree,maxNonFoldGroups=16){
    const calls=new Map(),raises=new Map();let foldProbability=0;
    for(const path of tree?.paths||[]){
      const probability=Math.max(0,Number(path.probability)||0),responses=path.responses||[];
      if(path.outcome==="fold"){foldProbability+=probability;continue}
      if(path.outcome==="call"){
        const seats=(path.activeSeats||responses.filter(item=>item.action==="call").map(item=>Number(item.seat))).map(Number).filter(Number.isFinite).sort((a,b)=>a-b),key=seats.join(",");
        const current=calls.get(key)||{probability:0,seats};current.probability+=probability;calls.set(key,current);continue;
      }
      const raiseIndex=responses.findIndex(item=>item.action==="raise"),raiserSeat=raiseIndex>=0?Number(responses[raiseIndex].seat):null,priorCallerSeats=(path.activeSeats||responses.slice(0,Math.max(0,raiseIndex)).filter(item=>item.action==="call").map(item=>Number(item.seat))).map(Number).filter(seat=>Number.isFinite(seat)&&seat!==raiserSeat).sort((a,b)=>a-b),key=`${raiserSeat||"unknown"}:${priorCallerSeats.join(",")}`;
      const current=raises.get(key)||{probability:0,raiserSeat,priorCallerSeats,pruned:path.pruned===true};current.probability+=probability;raises.set(key,current);
    }
    const ordered=[...[...calls.values()].map(item=>({...item,outcome:"call"})),...[...raises.values()].map(item=>({...item,outcome:"raise"}))].sort((left,right)=>right.probability-left.probability),retained=ordered.slice(0,maxNonFoldGroups),discarded=ordered.slice(maxNonFoldGroups),prunedProbability=discarded.reduce((sum,item)=>sum+item.probability,0),callGroups=retained.filter(item=>item.outcome==="call"),raiseGroups=retained.filter(item=>item.outcome==="raise");
    if(prunedProbability>0)raiseGroups.push({probability:prunedProbability,raiserSeat:null,priorCallerSeats:[],pruned:true});
    return{foldProbability,callGroups,raiseGroups,prunedProbability,retainedGroups:retained.length,totalGroups:ordered.length};
  }

  function conditionedPlayers(rangePlayers,seats,snapshot,candidate,action="call"){
    const wanted=new Set(seats.map(Number)),sizeRatio=(Number(candidate.amount)-Number(snapshot.callAmount||0))/Math.max(.000001,Number(snapshot.pot)||0);
    return (rangePlayers||[]).filter(player=>wanted.has(Number(player.seat))).map(player=>({...player,range:conditionedRange(player.range,{action,street:snapshot.street,scene:action==="raise"?"翻牌后再次加注":"面对下注跟注",position:player.position,sizeRatio,board:snapshot.boardCards})}));
  }

  function passivePreflopTree(snapshot,rangePlayers,candidate){
    if(snapshot?.street!=="preflop"||!PREFLOP)return null;
    const participants=PREFLOP.snapshotParticipants(snapshot,rangePlayers),investment=Math.max(0,Number(candidate?.amount)||0),hero=snapshot?.seats?.find(seat=>seat.isHero),heroPrior=streetInvestment(snapshot,hero?.seat),heroTo=heroPrior+investment,currentPrice=heroPrior+Math.max(0,Number(snapshot?.callAmount)||0),sizeRatio=Math.max(0,currentPrice-heroTo)/Math.max(.000001,Number(snapshot?.pot)||0);
    const tree=PREFLOP.continuationTree({locked:participants.committed,responders:participants.unacted,responseFor:player=>PREFLOP.responsePrior(player,{mode:"passive",sizeRatio,priceIncrease:Math.max(0,currentPrice-streetInvestment(snapshot,player.seat))})});
    return{...tree,sampleTier:"S0",sampleCount:0,source:"preflop_position_role_prior",uncalibrated:true,responseMargin:.5,participants};
  }

  function passivePreflopGroups(snapshot,rangePlayers,candidate){
    const tree=passivePreflopTree(snapshot,rangePlayers,candidate);if(!tree)return null;
    const groups=responsePathGroups(tree),committedSeats=tree.lockedSeats||[];
    groups.callGroups=groups.callGroups.map(group=>({...group,seats:[...new Set([...committedSeats,...group.seats])]}));
    groups.raiseGroups=groups.raiseGroups.map(group=>({...group,priorCallerSeats:[...new Set([...committedSeats,...group.priorCallerSeats])]}));
    return{tree,groups};
  }

  function selectBest(evaluated,pot){
    const eligible=(evaluated||[]).filter(item=>item.eligible&&item.selectionEligible!==false&&Number.isFinite(item.ev)),rawBest=eligible.reduce((winner,item)=>!winner||item.ev>winner.ev?item:winner,null);
    if(!rawBest)return {best:null,rawBest:null,tolerance:Math.max(.02*Math.max(0,Number(pot)||0),.05)};
    const tolerance=Math.max(.02*Math.max(0,Number(pot)||0),.05),aggressive=new Set(["quick_bet","custom_raise","minimum_raise","allin"]);
    if(!aggressive.has(rawBest.kind))return {best:rawBest,rawBest,tolerance};
    const near=eligible.filter(item=>aggressive.has(item.kind)&&Number.isFinite(item.amount)&&rawBest.ev-item.ev<=tolerance+1e-12&&Number(item.evHigh)>=Number(rawBest.evLow)&&Number(rawBest.evHigh)>=Number(item.evLow));
    const best=near.length?near.reduce((lower,item)=>Number(item.amount)<Number(lower.amount)?item:lower):rawBest;
    if(best!==rawBest)best.selectionReason="收益区间重叠且均值接近，选择较低投入尺度";
    return {best,rawBest,tolerance};
  }

  const AGGRESSIVE_KINDS=new Set(["bet","raise","quick_bet","custom_raise","minimum_raise","allin"]);

  function classifyProfitSources(snapshot,evaluated){
    const candidates=(evaluated||[]).map(item=>({...item})),pot=Math.max(0,Number(snapshot?.pot)||0),tolerance=Math.max(.02*pot,.05),passive=candidates.filter(item=>!AGGRESSIVE_KINDS.has(item.kind)&&item.eligible&&Number.isFinite(item.ev)),bestPassiveEV=passive.reduce((best,item)=>Math.max(best,item.ev),-Infinity),opponentCount=(snapshot?.seats||[]).filter(seat=>!seat.isHero&&!seat.empty&&!['fold','empty'].includes(seat.action)).length;
    let potential={improvementProbability:0,protectionGain:0,exact:false};
    if(CORE?.analyzeBoardPotential&&[3,4].includes(snapshot?.boardCards?.length))try{potential=CORE.analyzeBoardPotential(snapshot.heroCards,snapshot.boardCards)}catch{}
    for(const item of candidates){
      if(!AGGRESSIVE_KINDS.has(item.kind)||!Number.isFinite(item.ev))continue;
      const calls=(item.pathAudits||[]).filter(path=>path.outcome==="call"&&Number.isFinite(path.rollout?.ev)),callProbability=calls.reduce((sum,path)=>sum+(Number(path.probability)||0),0),calledEV=callProbability>0?calls.reduce((sum,path)=>sum+(Number(path.probability)||0)*Number(path.rollout.ev),0)/callProbability:null,foldProbability=Number(item.responseTree?.probabilities?.fold??item.pathAudits?.find(path=>path.outcome==="fold")?.probability??0),raiseProbability=Number(item.responseTree?.probabilities?.raise||0),continueProbability=Math.max(0,1-foldProbability),nonFoldAudits=(item.pathAudits||[]).filter(path=>path.outcome!=="fold"),noFoldEV=continueProbability>0?nonFoldAudits.reduce((sum,path)=>sum+(Number(path.probability)||0)*(path.outcome==="call"?Number(path.rollout?.ev):Number.isFinite(path.ev)?Number(path.ev):-(Number(item.amount)||0)),0)/continueProbability:-Infinity,valueEdge=Number.isFinite(calledEV)&&Number.isFinite(bestPassiveEV)?calledEV-bestPassiveEV:-Infinity,improvementProbability=Number(potential.improvementProbability)||0,protectionGain=Number(potential.protectionGain)||0,protectionBenefit=protectionGain*pot,betLabel=snapshot?.street!=="preflop"&&Number(snapshot?.callAmount||0)<=.000001,sampleTier=item.responseTree?.sampleTier||"S0",sampleReady=["S3","S4"].includes(sampleTier),responseMargin=Math.max(0,Number(item.responseTree?.responseMargin)||0),conservativeFoldProbability=Math.max(0,foldProbability-responseMargin),pureBluffBreakEven=Number.isFinite(noFoldEV)&&noFoldEV<0&&pot-noFoldEV>0?-noFoldEV/(pot-noFoldEV):0,pureBluffRequiredFold=Math.min(1,pureBluffBreakEven+.05);
      const hasPassiveBaseline=Number.isFinite(bestPassiveEV),hasPathEvidence=Array.isArray(item.pathAudits)&&item.pathAudits.length>0,classificationReady=hasPassiveBaseline&&(Number.isFinite(calledEV)||hasPathEvidence&&callProbability===0),classificationBasis=Number.isFinite(calledEV)?"called_path_value_edge":hasPathEvidence&&callProbability===0?"no_call_path_fold_or_raise_profit":"insufficient_path_evidence";
      let classification=!classificationReady?"收益来源待审计":callProbability===0?(improvementProbability>=.12?"半诈唬":"纯诈唬"):valueEdge>=0?(protectionBenefit>=tolerance?(betLabel?"保护性下注":"保护性加注"):valueEdge<=tolerance?(betLabel?"薄价值下注":"薄价值加注"):(betLabel?"价值下注":"价值加注")):improvementProbability>=.12?"半诈唬":"纯诈唬";
      let safetyReason="";
      if(classification==="纯诈唬"){
        if(opponentCount>1)safetyReason="多人底池禁用纯诈唬";
        else if(!sampleReady)safetyReason="仅S3/S4样本层允许纯诈唬";
        else if(conservativeFoldProbability<pureBluffRequiredFold)safetyReason="保守弃牌率未超过完整路径盈亏线5个百分点";
      }
      item.classification=classification;
      item.classificationEvidence={classificationReady,classificationBasis,bestPassiveEV,calledEV,calledValueEdge:valueEdge,callProbability,raiseProbability,foldProbability,conservativeFoldProbability,noFoldEV,improvementProbability,semiBluffMinImprovement:.12,protectionGain,protectionBenefit,engineeringTolerance:tolerance,pureBluffBreakEven,pureBluffRequiredFold,sampleTier,pureBluffSampleReady:sampleReady,opponentCount,potentialExact:potential.exact===true};
      if(safetyReason){item.selectionEligible=false;item.riskGateReason=safetyReason}
    }
    return candidates;
  }

  function attachAuditReasons(snapshot,evaluated,selection){
    const best=selection?.best;
    if(!best)return;
    const scene=best.scene||candidateScene(snapshot,best)||"未分类场景",evidence=best.classificationEvidence||{},alternatives=(evaluated||[]).filter(item=>item!==best&&item.eligible&&item.selectionEligible!==false&&Number.isFinite(item.ev)),runnerUp=alternatives.reduce((winner,item)=>!winner||item.ev>winner.ev?item:winner,null),interval=Number.isFinite(best.evLow)&&Number.isFinite(best.evHigh)?`，区间${best.evLow.toFixed(3)}至${best.evHigh.toFixed(3)}`:"",comparison=!runnerUp?"":best.ev>=runnerUp.ev?`，比次优候选高${(best.ev-runnerUp.ev).toFixed(3)}`:`，原始最高均值候选高${(runnerUp.ev-best.ev).toFixed(3)}，但${best.selectionReason||"风险门禁后未采用"}`;
    const source=best.classification?`${best.classification}；被跟注路径相对最佳被动动作${Number.isFinite(evidence.calledValueEdge)?evidence.calledValueEdge.toFixed(3):"未知"}，改善率${((evidence.improvementProbability||0)*100).toFixed(1)}%，保守弃牌率${((evidence.conservativeFoldProbability||0)*100).toFixed(1)}%`:`${best.kind}的完整路径期望收益为${Number(best.ev).toFixed(3)}`;
    best.auditReasons=[`场景：${scene}。`,`收益来源：${source}。`,`金额：投入${Number(best.amount||0).toFixed(3)}，期望收益${Number(best.ev).toFixed(3)}${interval}${comparison}。`];
  }

  function applyLowSampleRiskGates(evaluated,snapshot){
    const pot=Math.max(.000001,Number(snapshot?.pot)||0),call=Math.max(0,Number(snapshot?.callAmount)||0),effective=Math.max(0,...(evaluated||[]).filter(item=>item.kind==="allin").map(item=>Number(item.amount)||0)),alreadyCommitted=effective>0&&call/effective>=.25;
    const actions=(snapshot?.actions||[]).filter(item=>item.street===(snapshot?.street||"preflop")),hero=snapshot?.seats?.find(item=>item.isHero),scene=snapshot?.street==="preflop"?classifyScene({street:"preflop",action:"raise",priorActions:actions,handActions:snapshot.actions||[],heroSeat:hero?.seat,heroPosition:snapshot?.heroPosition}):null,percentile=preflopPercentile(snapshot?.heroCards),thresholds={"隔离加注":.94,"3下注":.965,"挤压加注":.975,"4下注":.985,"再次加注":.99,"Limp-reraise":.985},threshold=thresholds[scene];
    for(const item of evaluated||[]){
      const aggressive=["quick_bet","custom_raise","minimum_raise","allin"].includes(item.kind),s0=item.responseTree?.sampleTier==="S0";
      if(aggressive&&s0&&Number.isFinite(threshold)&&Number.isFinite(percentile)&&percentile<threshold){
        item.selectionEligible=false;
        item.riskGateReason=`S0${scene}仅开放价值核心；当前组合百分位${(percentile*100).toFixed(1)}%，门槛${(threshold*100).toFixed(1)}%`;
        continue;
      }
      const personalSamples=Number(item.responseTree?.personalSampleCount)||0,populationSamples=Number(item.responseTree?.populationSampleCount)||0,lowSample=personalSamples<30||populationSamples<30,deepAllin=item.kind==="allin"&&Number(item.amount)>Math.max(1.5*pot,2*call),independentlyCalibrated=item.responseTree?.conditionalEquitySource&&item.responseTree.conditionalEquitySource!=="conservative_all_continue_baseline",valueEdge=Number(item.classificationEvidence?.calledValueEdge),strongCalledValue=independentlyCalibrated&&Number.isFinite(valueEdge)&&valueEdge>=Math.max(.05,.10*pot);
      if(deepAllin&&lowSample&&!strongCalledValue&&!alreadyCommitted){
        item.selectionEligible=false;
        item.riskGateReason="低样本深筹码超池全下缺少被跟注价值优势";
      }
    }
    return evaluated;
  }

  function mergeT1Decisions(partials,candidates,snapshot){
    const byIndex=new Map();
    for(const partial of partials||[])for(const item of partial?.evaluated||[])if(Number.isInteger(item.candidateIndex))byIndex.set(item.candidateIndex,item);
    let evaluated=(candidates||[]).map((candidate,index)=>byIndex.get(index)||{...candidate,candidateIndex:index,ev:null,evLow:null,evHigh:null,eligible:false,solveTier:"T1",reason:"并行候选结果缺失"});
    evaluated=classifyProfitSources(snapshot,evaluated);
    applyLowSampleRiskGates(evaluated,snapshot);
    const selection=selectBest(evaluated,snapshot?.pot),complete=evaluated.length===(candidates||[]).length&&evaluated.every(item=>item.eligible||item.reason);
    attachAuditReasons(snapshot,evaluated,selection);
    return {modelVersion:MODEL_VERSION,shadowOnly:true,solveTier:"T1",complete,best:selection.best,rawBest:selection.rawBest,selectionTolerance:selection.tolerance,evaluated,decisionContext:decisionContext(snapshot,evaluated),rangeSource:"default_v2_combo_ranges",parallelParts:(partials||[]).length,assumptions:clone((partials||[]).find(item=>item?.assumptions)?.assumptions||[])};
  }

  function unsupportedSidePotDecision(snapshot,candidates,tier){
    const reason=snapshot?.sidePotContract?.evPolicy?.reason||"V2/T2/T3未支持复杂多人边池逐层EV";
    return {modelVersion:MODEL_VERSION,shadowOnly:true,solveTier:tier,complete:false,best:null,rawBest:null,
      evaluated:decisionCandidates(candidates).map(item=>({...item,ev:null,evLow:null,evHigh:null,eligible:false,selectionEligible:false,reason})),
      decisionContext:decisionContext(snapshot,[]),sidePotContract:snapshot.sidePotContract,unsupported:true,reason};
  }

  function t1Decision({snapshot,candidates=[],rangePlayers=[],reactions={},effective=Infinity,seed=decisionSeed(snapshot)}={}){
    candidates=decisionCandidates(candidates);
    if(snapshot?.sidePotContract?.requiresLayering)return unsupportedSidePotDecision(snapshot,candidates,"T1");
    const evaluated=[];
    for(const rawCandidate of candidates){
      const candidate={...rawCandidate,scene:candidateScene(snapshot,rawCandidate)};
      if(candidate.kind==="fold"){evaluated.push({...candidate,ev:0,evLow:0,evHigh:0,eligible:true,solveTier:"T1"});continue}
      if(["check","call","allin_call"].includes(candidate.kind)){
        const passive=candidate.kind==="call"?passivePreflopGroups(snapshot,rangePlayers,candidate):null;
        if(passive){
          const hero=snapshot.seats?.find(seat=>seat.isHero),heroPrior=streetInvestment(snapshot,hero?.seat),heroAdditional=Math.max(0,Number(candidate.amount)-heroPrior),groups=passive.groups,tree=passive.tree,pathAudits=[],pathMeans=[];let value=0,weightedLow=0,weightedHigh=0,valid=true;
          for(const group of groups.callGroups){
            const callers=conditionedPlayers(rangePlayers,group.seats,snapshot,candidate),opponentAdditional=group.seats.reduce((sum,seat)=>sum+Math.max(0,Number(candidate.amount)-streetInvestment(snapshot,seat)),0),rollout=callers.length?nextStreetRollout({snapshot,players:callers,pot:Number(snapshot.pot)+heroAdditional+opponentAdditional,investment:heroAdditional,effective,seed:`${seed}:passive:${group.seats.join(",")}`}):null;
            if(!Number.isFinite(rollout?.ev)){valid=false;continue}value+=group.probability*rollout.ev;weightedLow+=group.probability*(rollout.evLow??rollout.ev);weightedHigh+=group.probability*(rollout.evHigh??rollout.ev);pathMeans.push(rollout.ev);pathAudits.push({outcome:"call",probability:group.probability,callerSeats:group.seats,opponentAdditional,rollout});
          }
          for(const group of groups.raiseGroups){
            const raiser=rangePlayers.find(player=>Number(player.seat)===Number(group.raiserSeat)),raiseRange=raiser?conditionedRange(raiser.range,{action:"raise",street:"preflop",position:raiser.position,sizeRatio:1,board:[]}):null,raiseTo=Math.min(Number(effective),Math.max(Number(candidate.amount)*2.2,Number(candidate.amount)+Math.max(Number(snapshot.blindBig)||0,Number(snapshot.callAmount)||0))),heroTotal=Math.max(0,raiseTo-heroPrior),raiserAdditional=Number.isFinite(group.raiserSeat)?Math.max(0,raiseTo-streetInvestment(snapshot,group.raiserSeat)):0,priorCallerAdditional=group.priorCallerSeats.reduce((sum,seat)=>sum+Math.max(0,Number(candidate.amount)-streetInvestment(snapshot,seat)),0),equity=raiseRange?weightedEquity({hero:snapshot.heroCards,board:[],players:[{...raiser,range:raiseRange}],trials:120,seed:`${seed}:passive-squeeze:${group.raiserSeat}`}):{equity:null,interval:[0,1]},net=gross=>gross-Math.min(Math.max(0,gross)*Math.max(0,Number(snapshot.rakeRate)||0),Number.isFinite(snapshot.rakeCap)?snapshot.rakeCap:Infinity),gross=Number(snapshot.pot)+priorCallerAdditional+raiserAdditional+heroTotal,callValue=Number.isFinite(equity.equity)?equity.equity*net(gross)-heroTotal:-Infinity,foldValue=-heroAdditional,useCall=callValue>foldValue,branchValue=useCall?callValue:foldValue,branchLow=useCall?equity.interval[0]*net(gross)-heroTotal:foldValue,branchHigh=useCall?equity.interval[1]*net(gross)-heroTotal:foldValue;
            value+=group.probability*branchValue;weightedLow+=group.probability*branchLow;weightedHigh+=group.probability*branchHigh;pathMeans.push(branchValue);pathAudits.push({outcome:"raise",probability:group.probability,raiserSeat:group.raiserSeat,priorCallerSeats:group.priorCallerSeats,heroResponse:useCall?"call":"fold",ev:branchValue});
          }
          if(groups.prunedProbability){value-=groups.prunedProbability*heroAdditional;weightedLow-=groups.prunedProbability*heroAdditional;weightedHigh-=groups.prunedProbability*heroAdditional}
          const spread=pathMeans.length?Math.max(...pathMeans)-Math.min(...pathMeans):0,responseUncertainty=Number(tree.responseMargin||0)*spread;
          evaluated.push({...candidate,ev:valid?value:null,evLow:valid?weightedLow-responseUncertainty:null,evHigh:valid?weightedHigh+responseUncertainty:null,eligible:valid&&Number.isFinite(value),solveTier:"T1",responseTree:{...tree,evPrunedProbability:groups.prunedProbability},pathAudits,pathAggregation:"preflop_committed_plus_unacted_tree",reason:valid?"":"passive_preflop_path_incomplete"});continue
        }
        const investment=Number(candidate.amount)||0,rollout=nextStreetRollout({snapshot,players:rangePlayers,pot:Number(snapshot.pot)+investment,investment,effective,seed:`${seed}:${candidate.kind}`});
        evaluated.push({...candidate,ev:rollout.ev,evLow:rollout.evLow,evHigh:rollout.evHigh,eligible:Number.isFinite(rollout.ev),solveTier:"T1",rollout,reason:Number.isFinite(rollout.ev)?"":"下一街范围权益无法计算"});continue
      }
      const tree=candidateResponseTree(snapshot,rangePlayers,reactions,candidate),groups=responsePathGroups(tree),hero=snapshot.seats?.find(seat=>seat.isHero),heroPrior=streetInvestment(snapshot,hero?.seat),heroAdditional=Math.max(0,Number(candidate.amount)-heroPrior),net=gross=>gross-Math.min(Math.max(0,gross)*Math.max(0,Number(snapshot.rakeRate)||0),Number.isFinite(snapshot.rakeCap)?snapshot.rakeCap:Infinity),pathAudits=[{outcome:"fold",probability:groups.foldProbability}],pathMeans=[Number(snapshot.pot)];
      let value=groups.foldProbability*Number(snapshot.pot),weightedLow=value,weightedHigh=value,valid=true;
      for(const group of groups.callGroups){
        const callers=conditionedPlayers(rangePlayers,group.seats,snapshot,candidate),opponentAdditional=group.seats.reduce((sum,seat)=>sum+Math.max(0,Number(candidate.amount)-streetInvestment(snapshot,seat)),0),rollout=callers.length?nextStreetRollout({snapshot,players:callers,pot:Number(snapshot.pot)+heroAdditional+opponentAdditional,investment:heroAdditional,effective,seed:`${seed}:${candidate.kind}:${candidate.amount}:call:${group.seats.join(",")}`}):null;
        if(!Number.isFinite(rollout?.ev)){valid=false;continue}
        value+=group.probability*rollout.ev;weightedLow+=group.probability*(rollout.evLow??rollout.ev);weightedHigh+=group.probability*(rollout.evHigh??rollout.ev);pathMeans.push(rollout.ev);pathAudits.push({outcome:"call",probability:group.probability,callerSeats:group.seats,opponentAdditional,rollout});
      }
      for(const group of groups.raiseGroups){
        const raiser=rangePlayers.find(player=>Number(player.seat)===Number(group.raiserSeat)),raiseRange=raiser?conditionedRange(raiser.range,{action:"raise",street:snapshot.street,position:raiser.position,sizeRatio:1,board:snapshot.boardCards}):null,raiseTo=Math.min(Number(effective),Math.max(Number(candidate.amount)*2.2,Number(candidate.amount)+(Number(candidate.amount)-Number(snapshot.callAmount||0)))),priorCallerAdditional=group.priorCallerSeats.reduce((sum,seat)=>sum+Math.max(0,Number(candidate.amount)-streetInvestment(snapshot,seat)),0),raiserAdditional=Number.isFinite(group.raiserSeat)?Math.max(0,raiseTo-streetInvestment(snapshot,group.raiserSeat)):0,heroCallInvestment=Math.max(0,raiseTo-heroPrior),raiseEquity=raiseRange?weightedEquity({hero:snapshot.heroCards,board:snapshot.boardCards,players:[{...raiser,range:raiseRange}],trials:120,seed:`${seed}:reraise:${group.raiserSeat}`}):{equity:null,interval:[0,1]},gross=Number(snapshot.pot)+priorCallerAdditional+raiserAdditional+heroCallInvestment,callRaiseValue=Number.isFinite(raiseEquity.equity)?raiseEquity.equity*net(gross)-heroCallInvestment:-Infinity,callRaiseLow=Number.isFinite(raiseEquity.interval?.[0])?raiseEquity.interval[0]*net(gross)-heroCallInvestment:callRaiseValue,callRaiseHigh=Number.isFinite(raiseEquity.interval?.[1])?raiseEquity.interval[1]*net(gross)-heroCallInvestment:callRaiseValue,foldValue=-heroAdditional,raiseValue=Math.max(foldValue,callRaiseValue),raiseLow=raiseValue===callRaiseValue?callRaiseLow:foldValue,raiseHigh=raiseValue===callRaiseValue?callRaiseHigh:foldValue;
        value+=group.probability*raiseValue;weightedLow+=group.probability*raiseLow;weightedHigh+=group.probability*raiseHigh;pathMeans.push(raiseValue);pathAudits.push({outcome:"raise",probability:group.probability,raiserSeat:group.raiserSeat,priorCallerSeats:group.priorCallerSeats,priorCallerAdditional,raiseTo,heroResponse:raiseValue===callRaiseValue?"call":"fold",ev:raiseValue,evLow:raiseLow,evHigh:raiseHigh,pruned:group.pruned});
      }
      const responseUncertainty=Number(tree.responseMargin||0)*(Math.max(...pathMeans)-Math.min(...pathMeans));
      evaluated.push({...candidate,ev:valid?value:null,evLow:valid?weightedLow-responseUncertainty:null,evHigh:valid?weightedHigh+responseUncertainty:null,eligible:valid&&Number.isFinite(value),solveTier:"T1",responseTree:{...tree,evPrunedProbability:groups.prunedProbability,evRetainedGroups:groups.retainedGroups,evTotalGroups:groups.totalGroups,evPrunedAs:groups.prunedProbability>0?"raise_conservative":null},pathAudits,pathAggregation:"sequential_exact_caller_sets",uncertainty:{method:"equity_interval_plus_response_margin",responseMargin:Number(tree.responseMargin)||0},reason:valid?"":"下一街路径无法完整计算"});
    }
    const classified=classifyProfitSources(snapshot,evaluated);
    applyLowSampleRiskGates(classified,snapshot);
    const eligible=classified.filter(item=>item.eligible&&Number.isFinite(item.ev)),selection=selectBest(classified,snapshot.pot);
    attachAuditReasons(snapshot,classified,selection);
    return {modelVersion:MODEL_VERSION,shadowOnly:true,solveTier:"T1",complete:eligible.length===candidates.length,best:selection.best,rawBest:selection.rawBest,selectionTolerance:selection.tolerance,evaluated:classified,decisionContext:decisionContext(snapshot,classified),rangeSource:"default_v2_combo_ranges",assumptions:["翻牌前固定种子抽样12种翻牌","翻牌后逐张枚举下一张牌","下一街只展开首轮动作","顺序路径按结果概率合并并保留代表性跟注者","再加注按2.2倍候选并比较本人弃牌或继续"]};
  }

  function reactionForCandidate(reactions,candidate){
    const items=reactions?.candidates||reactions||{},amount=Number.isFinite(candidate.amount)?String(candidate.amount):"",ratio=Number.isFinite(candidate.ratio)?String(candidate.ratio):"";
    return items[`${candidate.kind}:${amount}`]||(ratio&&items[`${candidate.kind}:${ratio}`])||Object.values(items).find(item=>item?.kind===candidate.kind&&Number.isFinite(Number(item.amount))&&Math.abs(Number(item.amount)-Number(candidate.amount))<1e-6)||null;
  }

  function shadowDecision({snapshot,candidates=[],rangePlayers=[],reactions={},equity,equityInterval=null,conditionalEquityByCandidate={},effective=Infinity,solveTier="T0"}={}){
    if(snapshot?.sidePotContract?.requiresLayering)return unsupportedSidePotDecision(snapshot,candidates,solveTier);
    candidates=decisionCandidates(candidates);
    const responseTrees={},equityByCallers={};
    for(const rawCandidate of candidates){
      const candidate={...rawCandidate,scene:candidateScene(snapshot,rawCandidate)};
      if(!["quick_bet","custom_raise","minimum_raise","allin"].includes(candidate.kind))continue;
      const tree=candidateResponseTree(snapshot,rangePlayers,reactions,candidate),key=`${candidate.kind}:${candidate.amount}`;
      if(tree)responseTrees[key]=tree;
      const conditional=conditionalEquityByCandidate[key]||conditionalEquityByCandidate[`${candidate.kind}:${Number(candidate.amount).toFixed(6)}`];
      if(conditional?.equityByCallers)equityByCallers[key]=clone(conditional.equityByCallers);
    }
    const evaluated=[];
    for(const candidate of candidates){
      const key=`${candidate.kind}:${candidate.amount}`,candidateEquities=equityByCallers[key]||{};
      const result=compareActions({candidates:[candidate],pot:snapshot.pot,call:snapshot.callAmount||0,effective,equity,equityInterval,rakeRate:snapshot.rakeRate||0,rakeCap:Number.isFinite(snapshot.rakeCap)?snapshot.rakeCap:Infinity,responseTrees,equityByCallers:candidateEquities,solveTier});
      evaluated.push(...result.evaluated);
    }
    const classified=classifyProfitSources(snapshot,evaluated);
    applyLowSampleRiskGates(classified,snapshot);
    const selection=selectBest(classified,snapshot.pot),eligible=classified.filter(item=>item.eligible&&Number.isFinite(item.ev)),best=selection.best;
    if(best){
      const alternatives=eligible.filter(item=>item!==best),strict=alternatives.every(item=>Number(best.evLow)>=Number(item.evHigh));
      best.bestProbabilityEstimate=strict?1:alternatives.length?.5:null;
    }
    attachAuditReasons(snapshot,classified,selection);
    return {modelVersion:MODEL_VERSION,shadowOnly:true,solveTier,complete:classified.every(item=>item.eligible||item.reason),best,rawBest:selection.rawBest,selectionTolerance:selection.tolerance,evaluated:classified,decisionContext:decisionContext(snapshot,classified),uncertaintyMethod:"equity_interval_plus_response_margin",responseTrees:Object.fromEntries(Object.entries(responseTrees).map(([key,tree])=>[key,{orderedSeats:tree.orderedSeats,probabilities:tree.probabilities,pathCount:tree.paths.length,prunedProbability:tree.prunedProbability,sampleTier:tree.sampleTier,sampleCount:tree.sampleCount,source:tree.source,uncalibrated:tree.uncalibrated===true,responseMargin:tree.responseMargin,summaryFallback:tree.summaryFallback===true}]))};
  }

  function sequentialTree({opponents=[],responseFor,maxPaths=256}={}){
    let paths=[{probability:1,responses:[],outcome:"fold",callers:0}],prunedProbability=0;
    for(const opponent of opponents){
      const next=[];
      for(const path of paths){
        if(path.outcome==="raise"){next.push(path);continue}
        const response=responseFor(opponent,path)||{},values={fold:Number(response.fold)||0,call:Number(response.call)||0,raise:Number(response.raise)||0},total=values.fold+values.call+values.raise;
        if(total<=0)continue;
        for(const [action,value] of Object.entries(values))if(value>0)next.push({probability:path.probability*value/total,responses:[...path.responses,{seat:opponent.seat,role:opponent.role||"unacted",action}],outcome:action==="raise"?"raise":action==="call"||path.outcome==="call"?"call":"fold",callers:path.callers+(action==="call"?1:0)});
      }
      const ordered=next.sort((a,b)=>b.probability-a.probability),discarded=ordered.slice(maxPaths);
      prunedProbability+=discarded.reduce((sum,path)=>sum+path.probability,0);
      paths=ordered.slice(0,maxPaths);
    }
    const retainedProbability=paths.reduce((sum,path)=>sum+path.probability,0);
    if(prunedProbability>0)paths.push({probability:prunedProbability,responses:[],outcome:"raise",callers:0,pruned:true});
    const total=paths.reduce((sum,path)=>sum+path.probability,0)||1;
    paths=paths.map(path=>({...path,probability:path.probability/total}));
    const probabilities={fold:0,call:0,raise:0},callCountDistribution={};
    paths.forEach(path=>{probabilities[path.outcome]+=path.probability;if(path.outcome==="call")callCountDistribution[path.callers]=(callCountDistribution[path.callers]||0)+path.probability});
    const callTotal=probabilities.call||1;
    Object.keys(callCountDistribution).forEach(key=>callCountDistribution[key]/=callTotal);
    return {modelVersion:MODEL_VERSION,sequential:true,orderedSeats:opponents.map(item=>item.seat),probabilities,callCountDistribution,paths,retainedProbability:retainedProbability/total,prunedProbability:prunedProbability/total,prunedAs:prunedProbability>0?"raise_conservative":null};
  }

  function compareActions({candidates=[],pot,call=0,effective=Infinity,equity,equityInterval=null,rakeRate=0,rakeCap=Infinity,responseTrees={},equityByCallers={},raiseResponseEV={},solveTier="T0"}={}){
    const net=gross=>gross-Math.min(Math.max(0,gross)*Math.max(0,Number(rakeRate)||0),Number.isFinite(rakeCap)?rakeCap:Infinity),bounded=Math.max(0,Math.min(1,Number(equity))),low=Math.max(0,Math.min(bounded,Number(equityInterval?.[0]??bounded))),high=Math.min(1,Math.max(bounded,Number(equityInterval?.[1]??bounded))),evaluated=[];
    for(const candidate of candidates){
      if(candidate.kind==="fold"){evaluated.push({...candidate,ev:0,evLow:0,evHigh:0,eligible:true,solveTier});continue}
      if(candidate.kind==="check"){const legal=Number(call)<=0,gross=net(pot);evaluated.push({...candidate,ev:legal?bounded*gross:null,evLow:legal?low*gross:null,evHigh:legal?high*gross:null,eligible:legal,solveTier,reason:legal?"":"面对下注时不能让牌"});continue}
      if(["call","allin_call"].includes(candidate.kind)){const amount=Number(candidate.amount),legal=Number.isFinite(amount)&&amount>=Number(call||0)&&amount<=Number(effective),gross=net(pot+amount);evaluated.push({...candidate,ev:legal?bounded*gross-amount:null,evLow:legal?low*gross-amount:null,evHigh:legal?high*gross-amount:null,eligible:legal,solveTier,reason:legal?"":"跟注金额不合法"});continue}
      const amount=Number(candidate.amount),legal=Number.isFinite(amount)&&amount>Number(call||0)&&amount<=Number(effective);
      if(!legal){evaluated.push({...candidate,ev:null,eligible:false,solveTier,reason:"主动金额不合法"});continue}
      const tree=responseTrees[`${candidate.kind}:${candidate.amount}`]||responseTrees[candidate.kind];
      if(!tree){evaluated.push({...candidate,ev:null,eligible:false,solveTier,reason:"缺少该金额的顺序响应树"});continue}
      let value=0,lowerValue=0,upperValue=0,pathValues=[];
      for(const path of tree.paths||[]){
        if(path.outcome==="fold"){value+=path.probability*pot;lowerValue+=path.probability*pot;upperValue+=path.probability*pot;pathValues.push(pot)}
        else if(path.outcome==="call"){
          const callers=Math.max(1,path.callers),pathEquity=Number(equityByCallers[callers]??bounded),opponentCall=Math.max(0,Number(candidate.amount)-Number(call||0)),gross=net(pot+Number(candidate.amount)+opponentCall*callers),mean=pathEquity*gross-Number(candidate.amount),pathLow=Math.max(0,pathEquity-(bounded-low))*gross-Number(candidate.amount),pathHigh=Math.min(1,pathEquity+(high-bounded))*gross-Number(candidate.amount);
          value+=path.probability*mean;lowerValue+=path.probability*pathLow;upperValue+=path.probability*pathHigh;pathValues.push(mean);
        }else{const raised=Number(raiseResponseEV[`${candidate.kind}:${candidate.amount}`]??-Number(candidate.amount));value+=path.probability*raised;lowerValue+=path.probability*raised;upperValue+=path.probability*raised;pathValues.push(raised)}
      }
      const responseSpread=pathValues.length?Math.max(...pathValues)-Math.min(...pathValues):0,responseUncertainty=Number(tree.responseMargin||0)*responseSpread;
      evaluated.push({...candidate,ev:value,evLow:lowerValue-responseUncertainty,evHigh:upperValue+responseUncertainty,eligible:Number.isFinite(value),solveTier,responseTree:tree,uncertainty:{equity:[low,high],responseMargin:Number(tree.responseMargin)||0}});
    }
    const eligible=evaluated.filter(item=>item.eligible&&Number.isFinite(item.ev)),best=eligible.reduce((winner,item)=>!winner||item.ev>winner.ev?item:winner,null);
    return {modelVersion:MODEL_VERSION,solveTier,best,evaluated,complete:solveTier!=="T0"};
  }

  root.PokerV2=Object.freeze({MODEL_VERSION,FEATURES,ALL_COMBOS,ALL_CLASSES,deepFreeze,actionTier,showTier,classKey,classifyScene,snapshotPositionContext,candidateScene,decisionContext,decisionCandidates,snapshotIssues,formalSceneGate,buildDecisionSnapshot,opponentSceneEvents:eventContexts,buildRange,rangeStatistics,rangeAudit,compactRangeAudit,opponentHandPredictions,opponentRangeStatistics,opponentRoles,responseTreeFromEstimate,baselineResponseTree,candidateResponseTree,weightedEquity,conditionedRange,rangeResponse,nextStreetRollout,passivePreflopTree,t1Decision,shadowDecision,sequentialTree,compareActions,selectBest,classifyProfitSources,applyLowSampleRiskGates,mergeT1Decisions,unsupportedSidePotDecision,decisionSeed,preflopPercentile,boardClass});
  if(typeof module!=="undefined")module.exports=root.PokerV2;
})(typeof globalThis!=="undefined"?globalThis:window);
