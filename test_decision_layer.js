const fs=require("fs"),vm=require("vm"),assert=require("assert");
const context={window:{PokerCore:{buildSidePotContractFromState:()=>({contractVersion:1,requiresLayering:false,heroWinnableGross:1.2,legalActions:["fold","call","custom_raise"],rake:{rate:.05,cap:.2}})}}};vm.createContext(context);vm.runInContext(fs.readFileSync("decision-layer.js","utf8"),context);
const state={layout:"8max",runtimeId:"run-a",tableSession:2,handId:3,street:"flop",actionButtonSequence:4,
  heroCards:["As","Kh"],boardCards:["2c","7d","Ts"],pot:1.2,callAmount:.4,minRaiseTo:1,
  seats:Array.from({length:8},(_,index)=>({index,chips:index===4?5:3})),
  visualButtons:[{kind:"fold"},{kind:"call"},{kind:"custom_raise"}],tablePlay:{type:"德州扑克"},rakeRate:.05,rakeCap:.2};
const request=context.window.DecisionLayer.buildRequest(state);
assert.strictEqual(request.decisionKey,'["run-a",2,3,"flop",4]');
assert.strictEqual(request.heroStack,5);assert.deepStrictEqual([...request.legalActions],["fold","call","custom_raise"]);
assert.strictEqual(request.sidePotContract.heroWinnableGross,1.2);
assert.strictEqual(context.window.DecisionLayer.assertBound(request),request);
assert.throws(()=>context.window.DecisionLayer.assertBound({...request,legalActions:["fold"]}),/合法动作不一致/);
assert.strictEqual(context.window.DecisionLayer.presentation({primary:"加注",recommended:1.2,confidence:.9}).amount,1.2);
console.log("decision layer tests passed");
