"use strict";

const fs=require("node:fs"),path=require("node:path"),v2=require("./v2-model.js");
const RANKS="23456789TJQKA";

function comboClass(cards){
  if(!Array.isArray(cards)||cards.length!==2||cards[0]===cards[1])return null;
  const normalized=cards.map(card=>String(card||"")).filter(card=>card.length===2&&RANKS.includes(card[0].toUpperCase())&&"shdc".includes(card[1].toLowerCase())).map(card=>card[0].toUpperCase()+card[1].toLowerCase()).sort((left,right)=>RANKS.indexOf(right[0])-RANKS.indexOf(left[0]));
  return normalized.length===2?`${normalized[0][0]}${normalized[1][0]}${normalized[0][0]===normalized[1][0]?"":normalized[0][1]===normalized[1][1]?"s":"o"}`:null;
}

function evidenceFromSamples(samples){
  const buckets=new Map(),valid=(samples||[]).filter(sample=>sample?.street&&sample?.action);
  for(const sample of valid){
    const ratioBucket=Number.isFinite(Number(sample.betPotRatio))?Math.round(Number(sample.betPotRatio)/.25)*.25:null,stackBucketBb=Number.isFinite(Number(sample.effectiveStackBb))?Math.min(200,Math.round(Number(sample.effectiveStackBb)/50)*50):null,playerCountBucket=Number.isFinite(Number(sample.playerCount))?Math.min(5,Math.max(2,Math.round(Number(sample.playerCount)))):null,key=JSON.stringify([sample.street,sample.facingAction||null,sample.position||"unknown",sample.boardClass||v2.boardClass(sample.board||[]),ratioBucket,stackBucketBb,playerCountBucket]),bucket=buckets.get(key)||{street:sample.street,facingAction:sample.facingAction||null,position:sample.position||"unknown",boardClass:sample.boardClass||v2.boardClass(sample.board||[]),ratioBucket,stackBucketBb,playerCountBucket,sampleCount:0,verifiedCount:0,actionCounts:{},verifiedClasses:{},matchTier:"personal_scene"},action=String(sample.action),combo=comboClass(sample.verifiedHoleCards);
    bucket.sampleCount++;bucket.actionCounts[action]=(bucket.actionCounts[action]||0)+1;
    if(combo){bucket.verifiedCount++;const byAction=bucket.verifiedClasses[action]||(bucket.verifiedClasses[action]={});byAction[combo]=(byAction[combo]||0)+1}
    buckets.set(key,bucket);
  }
  return {modelVersion:2,nAction:valid.length,nShow:valid.filter(sample=>comboClass(sample.verifiedHoleCards)).length,revealedHands:new Set(valid.filter(sample=>comboClass(sample.verifiedHoleCards)).map(sample=>sample.handKey)).size,buckets:[...buckets.values()],shadowOnly:true};
}

function predictionEvent(sample){
  const prior=(sample.priorActions||[]).map((item,index)=>typeof item==="string"?{street:sample.street,action:item,sequence:index+1}:item);
  return {street:sample.street,action:sample.action,position:sample.position||"unknown",priorActions:prior,handActions:prior,preflopRaiseCount:prior.filter(item=>["raise","reraise"].includes(item.action)).length,facingAction:sample.facingAction||null,boardClass:sample.boardClass||v2.boardClass(sample.board||[]),betPotRatio:sample.betPotRatio,effectiveStackBb:sample.effectiveStackBb,playerCount:sample.playerCount};
}

function sampleSignature(profile){
  const samples=profile?.decisionSamples||[],verified=samples.filter(sample=>comboClass(sample.verifiedHoleCards)),hands=new Set(verified.filter(sample=>sample.handKey).map(sample=>String(sample.handKey))),latest=Math.max(0,...samples.map(sample=>Number(sample.recordedAt)||0));
  return `${samples.length}:${verified.length}:${hands.size}:${Math.round(latest*1000)}`;
}

function scoreRange(range,cards){
  const actual=[...cards].sort().join(""),probabilities=(range?.combos||[]).map(item=>({key:[...item.cards].sort().join(""),probability:Number(item.probability)||0})).sort((left,right)=>right.probability-left.probability),actualProbability=probabilities.find(item=>item.key===actual)?.probability||0,brier=probabilities.reduce((sum,item)=>sum+item.probability*item.probability,0)-2*actualProbability+1;
  const coverage={};
  for(const target of [.10,.25,.50]){let cumulative=0,covered=false;for(const item of probabilities){if(cumulative>=target)break;cumulative+=item.probability;if(item.key===actual)covered=true}coverage[`top${Math.round(target*100)}`]=covered}
  return {actualProbability,brier,logLoss:-Math.log(Math.max(1e-12,actualProbability)),coverage};
}

function summarize(records,field){
  const items=records.map(record=>record[field]);
  if(!items.length)return {samples:0,uniqueHands:0,brier:null,logLoss:null,top10:null,top25:null,top50:null};
  const mean=selector=>items.reduce((sum,item)=>sum+selector(item),0)/items.length;
  return {samples:items.length,uniqueHands:new Set(records.map(record=>record.handKey)).size,brier:mean(item=>item.brier),logLoss:mean(item=>item.logLoss),top10:mean(item=>Number(item.coverage.top10)),top25:mean(item=>Number(item.coverage.top25)),top50:mean(item=>Number(item.coverage.top50))};
}

function calibrateProfile(profileKey,profile){
  const all=profile.decisionSamples||[],verified=all.filter(sample=>sample.handKey&&comboClass(sample.verifiedHoleCards)),records=[];
  for(const sample of verified){
    const training=all.filter(item=>item.handKey!==sample.handKey),evidence=evidenceFromSamples(training),event=predictionEvent(sample),known=sample.board||[],input={knownCards:known,board:sample.board||[],actions:[event],profile,evidence},baseline=v2.buildRange({...input,profileEnabled:false}),profiled=v2.buildRange({...input,profileEnabled:true});
    records.push({handKey:sample.handKey,street:sample.street,action:sample.action,actionTier:profiled.actionTier?.tier||"S0",showTier:profiled.showTier?.tier||"H0",trainingSamples:training.length,default:scoreRange(baseline,sample.verifiedHoleCards),profiled:scoreRange(profiled,sample.verifiedHoleCards)});
  }
  const baseline=summarize(records,"default"),profiled=summarize(records,"profiled"),minimumHands=30,improved=records.length>0&&profiled.brier<=baseline.brier&&profiled.logLoss<=baseline.logLoss&&profiled.top25+0.02>=baseline.top25,eligible=baseline.uniqueHands>=minimumHands&&improved;
  return {profileKey,name:profile.name||profileKey,sampleSignature:sampleSignature(profile),heldOutHands:baseline.uniqueHands,heldOutDecisions:records.length,minimumHands,baseline,profiled,delta:{brier:profiled.brier===null?null:profiled.brier-baseline.brier,logLoss:profiled.logLoss===null?null:profiled.logLoss-baseline.logLoss,top10:profiled.top10===null?null:profiled.top10-baseline.top10,top25:profiled.top25===null?null:profiled.top25-baseline.top25,top50:profiled.top50===null?null:profiled.top50-baseline.top50},improved,eligibleToAffectAdvice:eligible,reason:baseline.uniqueHands<minimumHands?`独立留出亮牌${baseline.uniqueHands}手，少于工程门槛${minimumHands}手`:!improved?"画像留出评分未同时优于默认范围":"达到整手留出校准门槛",records};
}

function calibrateProfiles(profiles){
  const players=Object.entries(profiles||{}).map(([key,profile])=>calibrateProfile(key,profile)).filter(item=>item.heldOutDecisions).sort((left,right)=>right.heldOutHands-left.heldOutHands||right.heldOutDecisions-left.heldOutDecisions),records=players.flatMap(player=>player.records.map(record=>({...record,profileKey:player.profileKey}))),baseline=summarize(records,"default"),profiled=summarize(records,"profiled");
  const qualified=players.filter(player=>player.eligibleToAffectAdvice),rejected=players.filter(player=>!player.eligibleToAffectAdvice);
  const generatedAt=new Date().toISOString();players.forEach(player=>player.generatedAt=generatedAt);
  return {modelVersion:"2.0.0",method:"leave-one-whole-hand-out",generatedAt,profilesScored:players.length,distinctTableHands:new Set(records.map(record=>record.handKey)).size,heldOutPlayerHands:new Set(records.map(record=>`${record.profileKey}:${record.handKey}`)).size,heldOutDecisions:records.length,baseline,profiled,eligibleProfiles:qualified.length,qualifiedProfileKeys:qualified.map(player=>player.profileKey),rejectedProfileKeys:rejected.map(player=>player.profileKey),formalProfileInfluenceEnabled:qualified.length>0,activationRule:{provisional:true,minimumIndependentHandsPerProfile:30,requirements:["画像Brier不高于默认范围","画像对数损失不高于默认范围","Top25覆盖率下降不超过2个百分点","固定回归全部通过"]},players};
}

function qualificationManifest(report){
  return {modelVersion:report.modelVersion,method:report.method,generatedAt:report.generatedAt,
    formalProfileInfluenceEnabled:report.formalProfileInfluenceEnabled,activationRule:report.activationRule,
    qualified:(report.players||[]).filter(player=>player.eligibleToAffectAdvice).map(player=>({profileKey:player.profileKey,name:player.name,sampleSignature:player.sampleSignature,heldOutHands:player.heldOutHands,heldOutDecisions:player.heldOutDecisions,delta:player.delta})),
    rejected:(report.players||[]).filter(player=>!player.eligibleToAffectAdvice).map(player=>({profileKey:player.profileKey,name:player.name,sampleSignature:player.sampleSignature,heldOutHands:player.heldOutHands,heldOutDecisions:player.heldOutDecisions,reason:player.reason}))};
}

function markdown(report){
  const percent=value=>value===null?"—":`${(value*100).toFixed(1)}%`,number=value=>value===null?"—":value.toFixed(4),lines=["# V2画像留出校准报告","",`- 方法：按整手牌留出；评分某手时，该手所有动作和亮牌均不进入训练证据。`,`- 可评分：${report.profilesScored}名对手，来自${report.distinctTableHands}手牌局的${report.heldOutPlayerHands}个对手底牌样本，共${report.heldOutDecisions}个决策。`,`- 当前允许受控影响正式建议：${report.eligibleProfiles}名；每名对手只对生成报告时的样本版本有效。`,"","| 模型 | Brier | 对数损失 | Top10覆盖 | Top25覆盖 | Top50覆盖 |","|---|---:|---:|---:|---:|---:|",`| 默认范围 | ${number(report.baseline.brier)} | ${number(report.baseline.logLoss)} | ${percent(report.baseline.top10)} | ${percent(report.baseline.top25)} | ${percent(report.baseline.top50)} |`,`| 画像范围 | ${number(report.profiled.brier)} | ${number(report.profiled.logLoss)} | ${percent(report.profiled.top10)} | ${percent(report.profiled.top25)} | ${percent(report.profiled.top50)} |`,"","## 结论","",report.eligibleProfiles?"达到门槛的对手可在原有剥削上限内受控参与；样本新增后旧资格自动失效。":"现有单人独立亮牌样本不足或画像评分未优于默认范围，因此继续旁路，不得改变正式建议。","","## 对手摘要","","| 对手 | 留出手数 | 决策数 | 结果 |","|---|---:|---:|---|",...report.players.slice(0,30).map(player=>`| ${String(player.name).replaceAll("|","/")} | ${player.heldOutHands} | ${player.heldOutDecisions} | ${player.reason} |`)];return lines.join("\n")+"\n";
}

if(require.main===module){
  const input=process.argv[2]||path.join(process.env.USERPROFILE||process.env.HOME,".poker-study-tool","opponent_profiles.json"),output=process.argv[3]||path.join("outputs","v2-profile-calibration");
  if(!fs.existsSync(input))throw new Error(`画像文件不存在：${input}`);
  fs.mkdirSync(output,{recursive:true});const report=calibrateProfiles(JSON.parse(fs.readFileSync(input,"utf8"))),compact={...report,players:report.players.map(({records,...player})=>player)};
  fs.writeFileSync(path.join(output,"profile-calibration.json"),JSON.stringify(compact,null,2));fs.writeFileSync(path.join(output,"profile-qualification.json"),JSON.stringify(qualificationManifest(report),null,2));fs.writeFileSync(path.join(output,"profile-calibration.md"),markdown(report));
  console.log(JSON.stringify({profilesScored:report.profilesScored,distinctTableHands:report.distinctTableHands,heldOutPlayerHands:report.heldOutPlayerHands,heldOutDecisions:report.heldOutDecisions,eligibleProfiles:report.eligibleProfiles,baseline:report.baseline,profiled:report.profiled}));
}

module.exports={comboClass,evidenceFromSamples,predictionEvent,sampleSignature,scoreRange,summarize,calibrateProfile,calibrateProfiles,qualificationManifest,markdown};
