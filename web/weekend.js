"use strict";
const el = id => document.getElementById(id);
const amountFields = ["purchase_price", "cash_before_settlement", "first_year_works"];
const evidenceLabels = {insurable:"Can the home be insured?", primary_works_approved:"Are the main building works approved?", structural_clear:"Has structural safety been cleared?", illiquid:"Would this property be difficult to sell?"};
const state = {examples:[], example:null, sample:true, saved:null, worksheet:null, version:0, busy:false, current:null, dirty:false, revision:0};
const labels = {
  purchase_price:"Proposed offer", deposit:"Cash deposit", acquisition_costs:"Duty and acquisition costs",
  capitalized_lmi:"Lenders mortgage insurance added to loan", cash_before_settlement:"Liquid cash before settlement",
  annual_rate_decimal:"Annual mortgage rate", term_months:"Loan term", urgent_works:"Urgent works",
  first_year_works:"Total first-year works, including urgent works", earner_incomes_monthly:"Monthly take-home income by earner",
  normal_living_monthly:"Normal monthly living costs", lean_living_monthly:"Lean monthly living costs",
  locked_commitments_monthly:"Other locked monthly commitments in an income loss", property_costs_monthly:"Monthly property costs including insurance",
  insurance_annual:"Annual home insurance premium", loss_duration_months:"Assumed time out of work",
  redundancy_available:"Accessible net redundancy pay", leave_available:"Accessible net leave payout",
  ip_wait_months:"Income-protection waiting period", death_cover:"Death benefit", tpd_cover:"Total and permanent disability benefit",
  illiquid:"Hard-to-sell property", insurable:"Insurable", primary_works_approved:"Main works approved", structural_clear:"Structural safety cleared",
  principal:"Mortgage including financed premium", cash_after_settlement:"Cash after settlement",
  wealth_loss_fraction_undefined_at_zero_cash:"Wealth loss as a share of starting cash (zero starting balance)"
};
const rules = {
  V1:["Insurance, approvals and structure","Get written confirmation for insurance, approvals and any structural concern."],
  V2:["Two months of cash after settlement","Lower the offer or retain enough liquid cash for two months of lean expenses."],
  V3:["One month of cash after urgent works","Obtain a firm quote for urgent works and keep one month of lean expenses available afterwards."],
  V4:["Income covers lean expenses","Reconcile take-home pay and lean costs, then test a lower mortgage."],
  A:["Higher rates, insurance and works","Price the works and rerun the offer with the cash you could actually retain."],
  B:["The largest income stops","Check net leave and redundancy entitlements, the insurance waiting period, and each policy benefit."],
  C:["A forced sale in two years","Allow for a weaker sale price, selling costs and mortgage balance. Recheck cash before the sale."]
};
const verdictWords = {green:"Green", amber:"Amber", red:"Red", unresolved:"Unresolved"};
const verdictHead = {green:"The household clears all three storms.", amber:"The offer leaves a weak spot.", red:"This offer fails a household check.", unresolved:"The result needs more evidence."};
const unknown = "Unknown";
const usd = new Intl.NumberFormat("en-AU",{style:"currency",currency:"AUD",currencyDisplay:"code",minimumFractionDigits:2,maximumFractionDigits:2});
const cash = n => n == null ? unknown : usd.format(Number(n));
const pct = n => n == null ? unknown : (Number(n)*100).toLocaleString("en-AU",{maximumFractionDigits:2})+"%";
const months = n => n == null ? unknown : Number(n).toLocaleString("en-AU",{maximumFractionDigits:1})+" months";
const readable = key => labels[key] || key.replaceAll("_"," ");
const node = (tag,text,cls) => {const x=document.createElement(tag); if(text!=null)x.textContent=text; if(cls)x.className=cls; return x;};
const tag = status => node("span",verdictWords[status] || unknown,"pill "+(verdictWords[status] ? status : "unresolved"));
function stats(rows) {
  const list=node("dl",null,"stats");
  for(const [label,value] of rows)list.append(node("dt",label),node("dd",value ?? unknown));
  return list;
}
function bullets(values) {
  const list=node("ul"); for(const value of values)list.append(node("li",value)); return list;
}
function disclosure(title,body) {
  const detail=node("details");detail.append(node("summary",title),body);return detail;
}
async function api(path,body,html=false) {
  const opts={headers:{"X-Risk-Dashboard":"1"},cache:"no-store"};
  if(body!==undefined){opts.method="POST";opts.headers["Content-Type"]="application/json";opts.body=JSON.stringify(body);}
  const r=await fetch(path,opts);
  if(!r.ok){
    if(r.status===401)throw Error("Open the local sample preview or start the private desktop launcher to use this worksheet.");
    let reason;try{reason=(await r.json()).detail;}catch{reason=r.statusText;}
    throw Error(typeof reason==="string"?reason:"The worksheet inputs could not be read.");
  }
  return html?r.text():r.json();
}
const basePath=id=>"/v1/assessments/"+encodeURIComponent(id);
function notice(text="",error=false){el("notice").textContent=text;el("notice").className=error?"error":"";}
function controls(){
  el("inputs").disabled=state.busy || !state.example;
  el("calculate").textContent=state.busy?"Testing / loading…":"Test this offer";
  const valid=state.current && !state.dirty && !state.busy;
  el("save").disabled=!valid;
  for(const key of ["download","replay","print"])el(key).disabled=!valid || !state.saved;
}
async function run(work){
  if(state.busy)return;
  state.busy=true;controls();notice();
  try{await work();}catch(e){notice(e.message,true);el("save-notice").textContent=e.message;}
  finally{state.busy=false;controls();}
}
function fill(example,changes={},notes={}){
  state.revision++;
  state.example=example;
  const p={...example.profile,...changes};
  el("example").value=example.id;
  el("description").textContent=example.description;
  for(const k of amountFields)el(k).value=p[k] ?? "";
  worksGuidance();
  const fields=el("evidence-fields");fields.replaceChildren();
  for(const [key,title] of Object.entries(evidenceLabels)){
    const l=node("label",title);l.htmlFor=key;
    const s=node("select");s.id=key;
    for(const [v,t] of [["","Unknown"],["true","Yes"],["false","No"]]){const opt=node("option",t);opt.value=v;s.append(opt);}
    s.value=p[key]==null?"":String(p[key]);fields.append(l,s);
    const hint=node("small",key==="illiquid"?"Stress assumption: Yes uses a 15% sale-price fall; No uses 10%; Unknown leaves the sale stress unresolved. These are declared scenarios, not sourced market predictions.":"Yes records clearance; No fails this property check at every price; Unknown means the evidence is still missing. Editing an answer alone does not supply evidence.");
    hint.id=key+"-help";s.setAttribute("aria-describedby",hint.id);fields.append(hint);
    if(!state.sample){
      const lab=node("label","Source reference (optional)");lab.htmlFor="src-"+key;
      const ref=node("input");ref.id="src-"+key;ref.maxLength=240;ref.placeholder="e.g. inspection report and date";ref.value=notes[key] || "";fields.append(lab,ref);
    }
  }
  el("privacy").textContent=state.sample?"Use fictional figures here. To record personal evidence, open start-windows.cmd on your computer.":"You are working in your private local workspace. An edited check without a source reference is an assumption.";
}
function worksGuidance(){
  const input=el("first_year_works"), urgent=Number(state.example.profile.urgent_works);
  const missing=input.value==="", invalid=!missing && Number(input.value)<urgent;
  input.setCustomValidity(invalid?"Enter a total including at least "+cash(urgent)+" of urgent works, or leave blank if unknown.":"");
  input.setAttribute("aria-invalid",String(invalid));
  el("works-status").textContent=missing?"Works cost unknown. Blank does not mean zero; the works checks and offer limit may be unresolved.":invalid?input.validationMessage:"Includes "+cash(urgent)+" urgent works. Remaining non-urgent works: "+cash(Number(input.value)-urgent)+".";
}
function checkExplanation(key,row){
  if(key!=="B")return rules[key][0]+". "+rules[key][1];
  const gaps=[["tpd_cover_gap","Disability cover shortfall","Confirm the disability benefit with the insurer or test a lower offer."],["death_cover_gap","Death cover shortfall","Confirm the death benefit with the insurer or test a lower offer."],["illness_wait_gap","Illness waiting-period cash shortfall","Confirm accessible cash and the policy waiting period."]];
  const reasons=gaps.filter(([field])=>Number(row[field])>0).map(([field,label,action])=>label+" "+cash(row[field])+". "+action);
  return reasons.length?reasons.join(" "):rules.B[0]+". "+rules.B[1];
}
function request(){
  const changes={}, source_notes={};
  for(const key of amountFields){
    const value=el(key).value===""?null:el(key).value;
    if((value===null)!=(state.example.profile[key]==null) || (value!==null && Number(value)!==Number(state.example.profile[key])))changes[key]=value;
  }
  for(const key of Object.keys(evidenceLabels)){
    const v=el(key).value;const value=v===""?null:v==="true";
    const ref=el("src-"+key)?.value.trim();
    if(value!==(state.example.profile[key]??null) || ref)changes[key]=value;
    if(ref)source_notes[key]=ref;
  }
  return {example_id:state.example.id,changes,source_notes,based_on:state.saved?.assessment_id || null};
}
function showSaved(saved){
  state.saved=saved;
  state.version=saved?.case_version || 0;
  if(saved)state.worksheet=saved.case_id.slice("weekend-".length);
  const u=new URL(location.href);u.search="";
  u.searchParams.set(saved?"assessment":"example",saved?saved.assessment_id:state.example.id);
  history.replaceState(null,"",u);
  el("save-info").textContent=saved?"Saved version "+saved.case_version+". This link opens the exact recorded worksheet.":"Save the tested inputs, calculation rules, bid policy and result together in this workspace.";
}
function showExample(example){
  state.current=null;state.saved=null;state.dirty=false;state.version=0;state.worksheet=crypto.randomUUID();
  el("outcome").hidden=true;el("save-notice").textContent="";
  fill(example);showSaved(null);
}
function valueOf(key,value) {
  if(value==null)return unknown;
  if(typeof value==="boolean")return value?"Yes":"No";
  if(key.endsWith("months"))return months(value);
  if(key.endsWith("decimal") || key.endsWith("fraction"))return pct(value);
  if(Array.isArray(value))return value.map(cash).join(" + ");
  return cash(value);
}
function timeline(array){
  if(!Array.isArray(array))return node("p","Cash path unknown");
  return stats(array.map((v,i)=>[i===0?"At settlement":"Month "+i,cash(v)]));
}
function checkRows(result){
  const v=el("vetoes"),s=el("storms");v.replaceChildren();s.replaceChildren();
  const {A,B,C}=result.storms;
  const moneyValues=(r,entries)=>entries.map(([label,key])=>[label,cash(r[key])]);
  const amounts={
    A:[...moneyValues(A,[["Stressed monthly mortgage","stressed_payment"],["Month 3 works shock","works_month3"],["Monthly surplus, lean budget","lean_surplus"],["Monthly surplus, normal budget","normal_surplus"],["Cash in month 3","cash_month3"],["Cash in month 12","cash_month12"]]),
       ["Break-even interest rate",({no_loan:"No mortgage",deficit_without_debt:"Deficit even without a mortgage",deficit_even_at_zero_rate:"Deficit even at 0%",above_100_percent:"Above the 100% model limit"}[A.break_even_state] || pct(A.break_even_rate_decimal))],["Rate headroom",A.rate_margin_decimal==null?unknown:(Number(A.rate_margin_decimal)*100).toFixed(2)+" percentage points"]],
    B:[["Income removed",B.nominated_earner_index==null?unknown:"Earner "+(B.nominated_earner_index+1)],["Assumed loss duration",months(B.loss_duration_months)],
       ...moneyValues(B,[["Remaining monthly income","remaining_income"],["Monthly shortfall","monthly_gap"],["Cash plus confirmed job-loss payments","job_loss_cash"]]),
       ["Runway",B.runway_state==="self_funding"?"Remaining income covers the budget":months(B.runway_months)],
       ...moneyValues(B,[["Cash short during illness waiting period","illness_wait_gap"],["Death cover shortfall","death_cover_gap"],["Disability cover shortfall","tpd_cover_gap"]])],
    C:[["Sale-price fall",pct(C.dip_decimal)],...moneyValues(C,[["Sale price","sale_price"],["Selling costs","selling_costs"],["Mortgage balance at sale","balance_month24"],["Net sale equity","net_sale_equity"],["Lowest cash before sale","minimum_presale_cash"],["Cash immediately before sale","cash_month24"],["Cash after sale","cash_after_sale"]]),
       ["First cash shortfall before sale",C.first_presale_shortfall_month!=null?(C.first_presale_shortfall_month===0?"At settlement":"Month "+C.first_presale_shortfall_month):Array.isArray(C.monthly_cash)?"None through month 24":unknown],["Loan-to-value at sale",pct(C.lvr_decimal)],["Wealth loss / initial liquid cash",pct(C.wealth_loss_fraction)]]
  };
  for(const [key,r] of Object.entries({...result.vetoes,...result.storms})){
    const heading=rules[key];const card=node("article",null,"check-row"), header=node("header");
    header.append(node("h3",key+" · "+heading[0]),tag(r.status));card.append(header);
    if(key==="B" && r.status!=="green")card.append(node("p",checkExplanation(key,r)));
    if(key==="V1"){
      if(result.assumptions.V1)card.append(node("p",result.assumptions.V1));
      card.append(stats(Object.entries(r.flags).map(([k,val])=>[readable(k),val==null?unknown:val?"Yes":"No"])));
    }
    else if(key.startsWith("V"))card.append(stats([["Available",cash(r.available)],["Required",cash(r.required)]]));
    else{
      card.append(node("p",result.assumptions[key]),stats(amounts[key]));
      if(key==="A" || key==="C")card.append(disclosure("Monthly cash balances",timeline(r.monthly_cash)));
    }
    if(r.status!=="green")card.append(node("p",heading[1]));
    if(r.missing_inputs?.length)card.append(node("p","Unknown inputs — "+r.missing_inputs.map(readable).join(", "),"muted"));
    (key.startsWith("V")?v:s).append(card);
  }
}
function showBid(c,p){
  const heading={qualified:"Highest tested offer avoiding red (includes Amber): "+cash(c.highest_passing_price),range_ceiling:"Search stopped at "+cash(c.highest_passing_price)+"; higher offers untested",no_qualifying_bid:"No offer avoids red in this range",unknown:"Offer ceiling unknown"};
  el("bid-head").textContent=heading[c.status] || heading.unknown;
  const qualification=" Green and Amber both qualify for this search. Amber retains a weak spot; this is not a safe-offer recommendation.";
  el("bid-detail").textContent=(c.status==="qualified"?"The next tested offer at "+cash(c.next_failing_price)+" is Red. These binding figures belong to that offer, not the offer above.":c.status==="range_ceiling"?"This is the highest price on the tested grid. Higher offers are untested; it is not an established maximum.":c.status==="unknown"?"The available evidence cannot establish a highest qualifying offer.":"The model found a red result at every tested price in the search range.")+qualification;
  const reason=el("bid-reason");reason.replaceChildren(node("p",c.binding_reason));
  if(c.first_unresolved)reason.append(node("p","Unresolved offer at "+cash(c.first_unresolved.price)+". "+c.first_unresolved.reason));
  const grid=el("grid");grid.replaceChildren();
  if(c.grid)grid.append(stats([["Search range",cash(c.grid.min_price)+" to "+cash(c.grid.max_price)],["Offer increment",cash(c.grid.increment)],["Offers evaluated",String(c.evaluations)]]));
  grid.append(node("p","Deposit "+(p.deposit.mode==="ratio"?pct(p.deposit.value)+" of each offer":cash(p.deposit.value)+" fixed")+"."));
  for(const b of p.costs){
    grid.append(node("p","Up to "+cash(b.up_to_price)+": duty "+cash(b.duty.fixed)+" + "+pct(b.duty.price_ratio)+" of price; other costs "+cash(b.acquisition.fixed)+" + "+pct(b.acquisition.price_ratio)+" of price; financed LMI "+cash(b.lmi.fixed)+" + "+pct(b.lmi.loan_ratio)+" of the pre-LMI loan."));
  }
  grid.append(bullets(c.assumptions || []));
}
function render(study){
  state.current=study;state.dirty=false;el("outcome").hidden=false;
  const {result,profile,ceiling,capture}=study, x=capture.example;
  const t=result.verdict,combined={...result.vetoes,...result.storms},first=Object.entries(combined).find(([,v])=>v.status===t);
  el("property").textContent=x.name+" · "+(x.property.label || x.property)+" · "+x.as_of;
  el("verdict-card").dataset.tone=t;el("status-pill").replaceChildren(tag(t));el("verdict").textContent=verdictHead[t];
  el("action").textContent=t==="green"?"The modelled cash buffers hold at this offer. Confirm the deposit, settlement costs and property evidence before deciding.":first?first[0]+" · "+checkExplanation(first[0],first[1]):"Confirm the missing figures before making an offer.";
  const metrics=el("metrics");metrics.replaceChildren();
  for(const [lbl,value] of [["Tested offer",profile.purchase_price],["Cash after settlement",result.baseline.cash_after_settlement],["Normal monthly surplus",result.baseline.normal_surplus]]){
    const d=node("div");d.append(node("small",lbl),node("strong",cash(value)));metrics.append(d);
  }
  showBid(ceiling,x.bid_policy);checkRows(result);
  const gaps=el("unknowns");gaps.replaceChildren();
  if(study.price_issue)gaps.append(node("p","Offer costs unresolved. "+study.price_issue));
  if(result.missing_inputs.length)gaps.append(node("p","Missing inputs"),bullets(result.missing_inputs.map(readable)));
  const actions=[...new Set(Object.entries(combined).filter(([,v])=>v.status!=="green").map(([k])=>rules[k][1]))];
  gaps.append(bullets(actions.length?actions:["Get the lender’s price-specific loan and premium figures.","Confirm insurance, approvals and structural condition against written records."]));
  const a=el("profile");a.replaceChildren(node("p","The example starts with fictional figures and property conditions. Changes entered here are worksheet assumptions unless a source reference is recorded."));
  const notes=capture.source_notes || {}, changes=capture.changes || {};
  a.append(stats(Object.entries(profile).map(([k,v])=>[readable(k),valueOf(k,v)+(notes[k]?" · Source supplied: "+notes[k]:Object.hasOwn(changes,k)?" · Edited assumption":"")])));
  a.append(node("p",result.assumptions.cash),node("p",result.assumptions.living),node("p",result.assumptions.loan),node("small","Model "+result.rule_version+" · Worksheet "+study.version+" · "+study.input_hash));
}
async function preview(){
  const revision=state.revision, payload=request();
  el("outcome").hidden=true;state.current=null;
  notice("Testing "+state.example.name+" at "+cash(el("purchase_price").value===""?null:el("purchase_price").value)+". Waiting for the current inputs…");
  const study=await api("/v1/weekend/preview",payload);
  if(revision!==state.revision){notice("Inputs changed while testing. Test this offer again for the current inputs.");return;}
  render(study);
  if(state.saved){
    const same=study.input_hash===state.saved.weekend.input_hash;
    if(!same){state.dirty=false;el("save-info").textContent="Changed inputs. Save a new version to export or replay this result.";}
  }
  el("save-notice").textContent="";notice();
}
function savedCurrent(){return state.saved && state.current?.input_hash===state.saved.weekend.input_hash && !state.dirty;}
function savedControls(){
  controls();for(const key of ["download","replay","print"])el(key).disabled=state.busy || !savedCurrent();
}
async function historyList(){
  const list=el("history");const data=await api("/v1/weekend/history");list.replaceChildren();
  if(!data.assessments.length)list.append(node("p","No saved worksheets yet.","muted"));
  for(const row of data.assessments){
    const a=node("a",row.name+" · version "+row.case_version+" · "+new Date(row.created_at).toLocaleString("en-AU"));
    a.href="/weekend?assessment="+encodeURIComponent(row.assessment_id);list.append(a);
  }
}
async function reopen(id){
  const saved=await api(basePath(id));if(!saved.weekend)throw Error("This saved assessment has no weekend worksheet.");
  const cap=saved.weekend.capture;
  if(![...el("example").options].some(o=>o.value===cap.example.id))el("example").add(new Option(cap.example.name,cap.example.id));
  fill(cap.example,cap.changes,cap.source_notes);showSaved(saved);render(saved.weekend);el("save-notice").textContent="Opened saved version "+saved.case_version+".";
}
el("worksheet").addEventListener("submit",event=>{event.preventDefault();run(preview).finally(savedControls);});
el("worksheet").addEventListener("input",event=>{
  if(event.target.id==="example")return;
  state.revision++;worksGuidance();
  state.dirty=true;notice("Inputs changed. Test this offer to update the result.");el("outcome").hidden=true;controls();
});
el("example").addEventListener("change",()=>run(async()=>{
  showExample(state.examples.find(x=>x.id===el("example").value));await preview();
}).finally(savedControls));
el("reset").addEventListener("click",()=>run(async()=>{
  fill(state.example);await preview();
}).finally(savedControls));
el("save").addEventListener("click",()=>run(async()=>{
  const saved=await api("/v1/weekend/assessments",{...request(),worksheet:state.worksheet,expected_version:state.version});
  render(saved.weekend);showSaved(saved);el("save-notice").textContent="Saved version "+saved.case_version+".";await historyList();
}).finally(savedControls));
el("replay").addEventListener("click",()=>run(async()=>{
  if(!savedCurrent())return;
  const r=await api("/v1/weekend/assessments/"+encodeURIComponent(state.saved.assessment_id)+"/replay",{});
  el("save-notice").textContent=r.exact_match?"Exact replay. The recomputed assessment matches the saved version.":"Replay differs from the saved version.";
}).finally(savedControls));
el("download").addEventListener("click",()=>run(async()=>{
  if(!savedCurrent())return;
  const r=await api(basePath(state.saved.assessment_id)),a=node("a");const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:"application/json"}));
  a.href=url;a.download=state.example.id+"-v"+state.version+".json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}).finally(savedControls));
el("print").addEventListener("click",()=>run(async()=>{
  if(!savedCurrent())return;
  const tab=window.open("about:blank","_blank");if(!tab)throw Error("Allow a new tab to open the printable report.");
  tab.opener=null;try{const html=await api(basePath(state.saved.assessment_id)+"/report",undefined,true);
    const url=URL.createObjectURL(new Blob([html],{type:"text/html"}));tab.location.replace(url);setTimeout(()=>URL.revokeObjectURL(url),60000);
  }catch(e){tab.close();throw e;}
}).finally(savedControls));
run(async()=>{
  const data=await api("/v1/weekend/examples");state.examples=data.examples;state.sample=data.sample_workspace;
  const picker=el("example");for(const x of state.examples){const o=node("option",x.name+" · "+x.property.suburb);o.value=x.id;picker.append(o);}
  const params=new URLSearchParams(location.search);
  if(params.has("assessment"))await reopen(params.get("assessment"));
  else{const x=state.examples.find(x=>x.id===params.get("example")) || state.examples[0];showExample(x);await preview();}
  await historyList();
}).finally(savedControls);
