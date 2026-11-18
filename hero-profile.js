const $=id=>document.getElementById(id),RANGE_MODEL=window.HeroRangeModel,RANKS="AKQJT98765432";
let currentView="all",enteredOnly=false,lastState=null,lastDecisionKey="",lastHistoryKey="",lastStatisticsKey="",lastCurrentHand="",lastStrategyKey="",lastCompleteRangeDecision=null;

function apiMethod(name){
  const api=window.pywebview?.api,camel=name.replace(/_([a-z])/g,(_,letter)=>letter.toUpperCase());
  return typeof api?.[name]==="function"?api[name].bind(api):typeof api?.[camel]==="function"?api[camel].bind(api):null;
}
function call(name,...args){
  const method=apiMethod(name);
  if(!method)throw Error(`后端方法未就绪：${name}`);
  return method(...args);
}
const pct=value=>Number.isFinite(value)?`${Math.round(value*100)}%`:"--",number=value=>Number.isFinite(value)?String(value):"--";

function handClass(row,column){
  if(row===column)return RANKS[row]+RANKS[column];
  return row<column?RANKS[row]+RANKS[column]+"s":RANKS[column]+RANKS[row]+"o";
}
function renderStatistics(stats={}){
  const fields=[["levelHands","本级别手数",number],["vpipRate","主动入池率",pct],["totalHands","总手数",number],["pfrRate","加注入池率",pct],["threeBetRate","3次下注率",pct],["cBetRate","持续下注率",pct],["showdownRate","摊牌率",pct],["showdownWinRate","摊牌胜率",pct],["aggressionFactor","激进度",number],["averageBuyIn","场均带入",number],["averageResult","场均战绩",number],["bbPer100","每百手盈亏",number]];
  $("statistics").innerHTML=fields.map(([key,label,format])=>`<article class="stat"><span>${label}</span><b>${format(stats[key])}</b></article>`).join("");
}
function renderStrategyLeaks(data={}){
  const total=Number(data.sampleCount)||0,minimum=Number(data.minimumComparable)||15;
  $("leakSummary").textContent=data.status==="ready"?`已配对${total}次正式建议与实际动作`:`已配对${total}次；同类机会满${minimum}次后才判断`;
  $("strategyLeaks").innerHTML=(data.issues||[]).map(item=>{
    const result=!item.eligible?`证据不足 ${item.opportunities}/${minimum}`:item.flagged?`需要关注 ${(Number(item.rate)*100).toFixed(0)}%`:`未见明显异常 ${(Number(item.rate)*100).toFixed(0)}%`;
    return `<article class="leak ${item.flagged?"flagged":""}"><b>${item.label}</b><span>${result}；偏离${item.count}/${item.opportunities}${item.topPosition?`；主要在${item.topPosition}`:""}</span></article>`;
  }).join("");
}
const actionClass=action=>["加注","隔离加注","价值三下注","价值四下注"].includes(action)?"raise":action==="跟注"?"call":["让牌","过牌"].includes(action)?"check":action==="弃牌"?"fold":["实时精算","加注或跟注"].includes(action)?"math":"unknown";
const POSITION_LABELS={"BTN/SB":"庄家兼小盲","BTN":"庄家位","SB":"小盲位","BB":"大盲位","UTG":"枪口位","UTG+1":"枪口后一位","MP":"中位","HJ":"劫持位","CO":"关煞位"};
function renderScenarioSummary(decision){
  const summary=$("strategyScenario");
  if(!summary)return;
  const scene=decision?.rangeContext||{};
  if(!decision||!Object.keys(scene).length){summary.innerHTML="<span><b>等待同步</b>：翻牌前牌局条件尚未完整</span>";return}
  summary.innerHTML=[
    `<span>人数：<b>${scene.activePlayers}人</b></span>`,
    `<span>本人位置：<b>${POSITION_LABELS[scene.heroPosition]||scene.heroPosition}</b></span>`,
    `<span>前序行动：<b>${scene.priorActionPattern}</b></span>`,
    `<span>有效筹码：<b>${scene.effectiveStackBucket}</b></span>`,
    `<span>抽成：<b>${scene.rakePolicy}</b></span>`,
    `<span>压力：<b>${scene.pressureBucket}</b></span>`,
  ].join("");
}
function showRangeDetail(cell){
  const detail=$("rangeDetail");
  if(!detail||!cell)return;
  const action=cell.dataset.action,reason=cell.dataset.reason,level=cell.dataset.level,needsMath=cell.dataset.math==="true";
  detail.innerHTML=`<strong>${cell.dataset.hand}</strong>：基础动作 <strong>${action}</strong>。${reason}；依据${level}级。${needsMath?"真实跟注额、抽成和对手范围可能改变最终行动，轮到本人时由实时精算确认。":"该格不要求实时精算才能形成基础动作。"}`;
}
function renderStrategy(state){
  const liveDecision=state?.rangeDecision,liveActions=liveDecision?.rangeActions||{},retained=Object.keys(liveActions).length!==169&&lastCompleteRangeDecision;
  const decision=Object.keys(liveActions).length===169?liveDecision:retained;
  if(Object.keys(liveActions).length===169)lastCompleteRangeDecision=liveDecision;
  renderScenarioSummary(decision);
  const actions=decision?.rangeActions||{};
  if(Object.keys(actions).length!==169){$("strategySummary").textContent="等待首个完整场景";$("strategyContext").textContent="取得第一份完整的人数、位置、前序行动、有效筹码、抽成和压力后，169格会持续保留显示。";return}
  let html="",counts={raise:0,call:0,check:0,fold:0,math:0,unknown:0};
  for(let row=0;row<13;row++)for(let column=0;column<13;column++){
    const name=handClass(row,column);
    const action=actions[name],kind=actionClass(action),reason=decision.rangeReasons?.[name]||"当前场景基础规则",needsMath=decision.rangeRequiresRealtimeMath?.[name]===true,level=decision.rangeEvidenceLevels?.[name]||"--";
    counts[kind]++;html+=`<article class="hand ${kind}" data-hand="${name}" data-action="${action}" data-reason="${reason}" data-math="${needsMath}" data-level="${level}" title="点击查看详情"><b>${name}</b><span>${action}</span></article>`;
  }
  $("strategyMatrix").innerHTML=html;
  $("strategyMatrix").onclick=event=>showRangeDetail(event.target.closest(".hand"));
  highlightCurrentHand(lastState?.currentHandClass||"");
  $("strategySummary").textContent=`共169格｜加注${counts.raise}｜跟注${counts.call}｜让牌${counts.check}｜弃牌${counts.fold}｜条件动作${counts.math}${retained?"｜暂时保留上一完整场景":""}`;
  $("strategyContext").textContent=retained?"当前牌局处于换手或识别过渡帧，先保留上一张完整范围；取得下一份完整场景后自动替换。":"这张表与当前牌局共用同一份人数、位置、前序行动、有效筹码、抽成和压力数据，并随状态变化自动更新。跟注只会出现在需要补筹码的场景，让牌只会出现在可以免费继续的场景。灰色“条件动作”需由正式精算确认。";
}
function sampleTier(dealt){
  return dealt>=60?["S4",.8]:dealt>=30?["S3",.6]:dealt>=15?["S2",.35]:dealt>=5?["S1",.15]:["S0",0];
}
function renderHistory(){
  const data=lastState?.matrix?.[currentView]||{};
  let html="";
  for(let row=0;row<13;row++)for(let column=0;column<13;column++){
    const name=handClass(row,column),cell=data[name]||{},dealt=Number(cell.dealt||0),entered=Number(cell.entered||0),rate=dealt?entered/dealt:0,[tier,weight]=sampleTier(dealt),hidden=enteredOnly&&!entered;
    html+=`<article class="hand ${entered?"history-active":"unknown"} ${hidden?"hidden":""}" data-hand="${name}" style="--rate:${rate.toFixed(3)};--sample-weight:${weight}" title="${name}：实际入池${entered}次，发到${dealt}次；样本层级${tier}"><b>${name}</b><span>${entered}/${dealt} · ${tier}</span></article>`;
  }
  $("historyMatrix").innerHTML=html;
  const summary=lastState?.matrixSummary||{},active=lastState?.rangeCollectionActive!==false;
  $("historySummary").textContent=`169类 / 1326组合｜记录${summary.observedDeals||0}手，入池${summary.enteredHands||0}手｜${active?"统计中":"已停止"}`;
  $("startRange").textContent=active?"暂停统计":"开始统计";
  $("startRange").classList.toggle("selected",active);
}
function highlightCurrentHand(handClass){
  document.querySelectorAll(".hand.current-hand").forEach(cell=>cell.classList.remove("current-hand"));
  if(!handClass)return;
  document.querySelectorAll(`[data-hand="${handClass}"]`).forEach(cell=>cell.classList.add("current-hand"));
}
function render(state){
  lastState=state;
  const lifecycle=RANGE_MODEL.lifecycle(lastDecisionKey,state.rangeDecision),historyKey=JSON.stringify([state.matrix,state.matrixSummary,state.rangeCollectionActive]),statisticsKey=JSON.stringify([state.name,state.capturedAt,state.statistics,state.observations,state.strategyLeaks,state.windowTopmost]);
  lastDecisionKey=lifecycle.key;
  $("heroName").textContent=state.name||"尚未采集本人资料";
  $("capturedAt").textContent=state.capturedAt?`采集时间 ${new Date(state.capturedAt*1000).toLocaleString("zh-CN")}`:"请打开本人资料弹窗后采集";
  $("profileTopmost").dataset.topmost=String(state.windowTopmost===true);
  $("profileTopmost").textContent=state.windowTopmost?"取消置顶":"置顶";
  const strategyKey=JSON.stringify([state.rangeDecision?.rangeKey,state.rangeDecision?.rangeContext,state.rangeDecision?.rangeSource]);
  if(strategyKey!==lastStrategyKey){lastStrategyKey=strategyKey;renderStrategy(state)}
  const historyChanged=historyKey!==lastHistoryKey;
  if(historyChanged){lastHistoryKey=historyKey;renderHistory()}
  const currentHand=lifecycle.phase!=="holding"&&state.rangeDecision?.highlightHand?state.rangeDecision.currentHandClass||"":"";
  if(historyChanged||currentHand!==lastCurrentHand){lastCurrentHand=currentHand;highlightCurrentHand(currentHand)}
  if(statisticsKey!==lastStatisticsKey){
    lastStatisticsKey=statisticsKey;renderStatistics(state.statistics);renderStrategyLeaks(state.strategyLeaks);
    $("observations").innerHTML=(state.observations||[]).map(text=>`<div>• ${text}</div>`).join("");
  }
}
async function captureHero(){
  const button=$("captureHero");button.disabled=true;$("captureStatus").textContent="正在分析当前桌面快照……";
  try{
    const result=await call("capture_hero_statistics");
    $("captureStatus").textContent=result.status==="hero_ok"?`采集成功：${result.player}${result.missingAdvancedFields?.length?`；仍缺少${result.missingAdvancedFields.length}项高级数据`:"；12项数据完整"}`:`采集失败：${result.message}`;
    render(await call("hero_profile_state"));
  }catch(error){$("captureStatus").textContent=`采集失败：${error}`}finally{button.disabled=false}
}

document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>{currentView=button.dataset.view;document.querySelectorAll("[data-view]").forEach(item=>item.classList.toggle("selected",item===button));renderHistory()});
$("enteredOnly").onclick=()=>{enteredOnly=!enteredOnly;$("enteredOnly").classList.toggle("selected",enteredOnly);renderHistory()};
$("clearRange").onclick=async()=>{await call("clear_hero_range_statistics");lastHistoryKey="";render(await call("hero_profile_state"))};
$("startRange").onclick=async()=>{await call("set_hero_range_collection",lastState?.rangeCollectionActive===false);lastHistoryKey="";render(await call("hero_profile_state"))};
$("clearLeaks").onclick=async()=>{await call("clear_hero_strategy_comparisons");lastStatisticsKey="";render(await call("hero_profile_state"))};
$("profileTopmost").onclick=async()=>{
  const result=await call("set_auxiliary_window_topmost","hero",$("profileTopmost").dataset.topmost!=="true");
  $("profileTopmost").dataset.topmost=String(result.topmost);$("profileTopmost").textContent=result.topmost?"取消置顶":"置顶";
};
async function refresh(){
  try{render(await call("hero_profile_state"));setTimeout(refresh,500)}catch{setTimeout(refresh,200)}
}
window.addEventListener("pywebviewready",refresh);
setTimeout(refresh,150);
