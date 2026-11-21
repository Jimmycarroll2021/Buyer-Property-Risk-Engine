"use strict";
const $ = id => document.getElementById(id);
const state = {token:"", case:null, assessment:null, sources:[], catalog:null};
const kingstonPreview = "kingston-purchase-decision";
const fullCoveragePreview = "synthetic-full-coverage";
let caseRequest = 0;
const text = (tag, value, className) => { const e=document.createElement(tag); e.textContent=value ?? "Not assessed"; if(className)e.className=className; return e; };
const pretty = value => JSON.stringify(value,null,2);
const money = value => value === null || value === undefined ? "Not assessed" : new Intl.NumberFormat("en-AU",{style:"currency",currency:"AUD",maximumFractionDigits:2}).format(Number(value));
const priority = value => value === null || value === undefined ? "Not assessed" : `Priority ${value}`;
function message(value,error=false){$("message").textContent=value;$("message").className=value?`notice${error?" error":""}`:"";}
async function api(path,options={}){
  const identity = state.token ? {Authorization:`Bearer ${state.token}`} : {"X-Risk-Dashboard":"1"};
  const response=await fetch(path,{...options,headers:{...identity,"Content-Type":"application/json",...(options.headers||{})},cache:"no-store"});
  if(response.status===401 && document.documentElement.dataset.access==="desktop")
    throw Error("Open the workspace from its local launcher to start your browser session.");
  if(!response.ok){let d;try{d=await response.json();}catch{d={detail:response.statusText};}throw Error(typeof d.detail==="string"?d.detail:pretty(d.detail));}
  return response.headers.get("content-type")?.includes("application/json")?response.json():response.text();
}
const post=(path,body)=>api(path,{method:"POST",body:JSON.stringify(body)});
async function task(button,fn){const old=button.textContent;button.disabled=true;button.textContent="Working…";message("");try{await fn();}catch(e){message(e.message,true);}finally{button.disabled=false;button.textContent=old;}}
function showTab(name){document.querySelectorAll(".tab-panel").forEach(e=>e.hidden=e.id!==`tab-${name}`);document.querySelectorAll("[data-tab]").forEach(e=>e.classList.toggle("active",e.dataset.tab===name));}
document.querySelectorAll("[data-tab]").forEach(e=>e.addEventListener("click",()=>showTab(e.dataset.tab)));

async function loadCases(selected){
  const data=await api("/v1/cases");$("case-select").replaceChildren();
  const preview = document.documentElement.dataset.access === "preview";
  const examples = $("preview-examples");
  examples.replaceChildren();
  if (preview) {
    for (const [id, label] of [[kingstonPreview, "Kingston public evidence"], [fullCoveragePreview, "Fictional worked example"]]) {
      if (data.cases.some(c => c.case_id === id)) {
        const link = text("a", label);
        link.href = "?case=" + encodeURIComponent(id);
        examples.append(link);
      }
    }
  }
  examples.hidden = !examples.childElementCount;
  for(const c of data.cases){
    let label = c.property?.label || c.case_id;
    if (preview && c.case_id === "kingston-buyer-example") label += " (earlier example)";
    const option = text("option", label);
    option.value = c.case_id;
    $("case-select").append(option);
  }
  const requested=selected||new URLSearchParams(location.search).get("case")||(preview ? kingstonPreview : null);
  if(requested&&data.cases.some(c=>c.case_id===requested))$("case-select").value=requested;
  if($("case-select").value)await loadCase($("case-select").value);
  else{state.case=null;$("case-json").value=pretty(newCase());showTab("inputs");}
}
async function loadCase(id){
  const request = ++caseRequest;
  const [c,a,o,d]=await Promise.all([api(`/v1/cases/${encodeURIComponent(id)}`),api(`/v1/cases/${encodeURIComponent(id)}/assessments`),api(`/v1/cases/${encodeURIComponent(id)}/observations`),api(`/v1/cases/${encodeURIComponent(id)}/documents`)]);
  const last=a.assessments.filter(x=>x.display_allowed!==false&&x.case_version===c.case_version).at(-1);
  const assessment = last ? await api(`/v1/assessments/${encodeURIComponent(last.assessment_id)}`) : null;
  if (request !== caseRequest) return;
  state.case=c;$("case-json").value=pretty(c);renderEvidence(o.observations,d.documents);
  const link = new URL(location.href);
  link.searchParams.set("case", id);
  history.replaceState(null, "", link);
  if(assessment)renderAssessment(assessment);
  else{state.assessment=null;$("saved-offer-link").hidden=true;renderPurchaseDecision(null);$("assessment-title").textContent=c.property?.label||c.property_id;for(const id of ["metrics","findings","gaps","finance","opportunities","checks","provenance"])$(id).replaceChildren();$("assessment-note").textContent="Run an assessment for this case version to show supported findings and missing required checks.";$("download-json").disabled=true;$("open-report").disabled=true;}
  await loadBuyerContext(c,state.assessment);
}
function newCase(){return {case_id:`case-${crypto.randomUUID()}`,property_id:"REPLACE-PROPERTY-ID",as_of:new Date().toISOString(),assessment_mode:"buyer_assessment",property:{label:"New purchase case",jurisdiction:"ACT",property_type:"house",identity_confirmed:false},finance:{principal:null,annual_rate_decimal:null,term_months:360,income_monthly:null,living_monthly:null,other_debt_monthly:null,property_costs_monthly:null,cash_after_settlement:null,protected_reserve:null,purchase_price:null,loan_funds:null,cash_allocated:null,acquisition_costs:null,immediate_works:null,funding_confirmed:false},scenarios:[{scenario_id:"rate_and_income_12m",duration_months:12,rate_delta_bps:200,income_factor:"0.70",property_cost_factor:"1",required_review:true}],requirements:[]};}
async function openWorkspace(){
  $("offer-view").hidden=true;
  $("switch-view").textContent="Start an offer brief";
  await Promise.all([
    api("/static/check-inputs.json").then(catalog => { state.catalog = catalog; }).catch(() => {}),
    loadSources()
  ]);
  await loadCases();
  $("welcome").hidden=true;
  $("workspace").hidden=false;
  message("");
}
async function openInitialView(){
  const params = new URLSearchParams(location.search);
  if (params.has("case") || params.has("workspace")) await openWorkspace();
  else await openOfferView();
  $("switch-view").hidden = false;
}
$("switch-view").addEventListener("click", event => task(event.currentTarget, async () => {
  if ($("offer-view").hidden) {
    history.replaceState(null, "", location.pathname);
    await openOfferView();
  } else {
    history.replaceState(null, "", "?workspace=1");
    await openWorkspace();
  }
}).then(() => {
  $("switch-view").textContent = $("offer-view").hidden ? "Start an offer brief" : "Evidence workspace";
}));
document.addEventListener("DOMContentLoaded",()=>{
  if(document.documentElement.dataset.access==="bearer"){
    const template=$("key-login");
    template.replaceWith(template.content.cloneNode(true));
    $("connect-form").addEventListener("submit",event=>{
      event.preventDefault();
      task(event.submitter,async()=>{
        state.token=$("token").value.trim();
        await openInitialView();
        $("token").value="";
        $("login").hidden=true;
        $("disconnect").hidden=false;
      });
    });
    return;
  }
  $("key-login").remove();
  if (document.documentElement.dataset.access==="preview") {
    for (const id of ["save-case","new-case","upload-document","import-observations"]) $(id).hidden=true;
    $("case-json").readOnly=true;
    $("observation-json").disabled=true;
    $("document-file").disabled=true;
  }
  message("Opening your workspace…");
  openInitialView().catch(error=>message(error.message,true));
});
$("disconnect").addEventListener("click",()=>{state.token="";location.reload();});
$("case-select").addEventListener("change",e=>task($("assess"),()=>loadCase(e.target.value)));
$("new-case").addEventListener("click",()=>{$("case-json").value=pretty(newCase());message("New template ready. Replace the property identifier and complete the known inputs before saving.");});
$("save-case").addEventListener("click",e=>task(e.target,async()=>{const c=JSON.parse($("case-json").value);const version=c.case_version;delete c.owner_tenant_id;const saved=await post(`/v1/cases${version?`?expected_version=${version}`:""}`,c);await loadCases(saved.case_id);message(`Saved case version ${saved.case_version}.`);}));
$("assess").addEventListener("click",e=>task(e.target,async()=>{
  if(!state.case)throw Error("Save a case first.");
  if($("latest").checked){const c={...state.case,as_of:new Date().toISOString()};state.case=await post(`/v1/cases?expected_version=${c.case_version}`,c);$("case-json").value=pretty(state.case);}
  const a=await post(`/v1/cases/${encodeURIComponent(state.case.case_id)}/assessments`,{});renderAssessment(a);showTab("assessment");await loadBuyerContext(state.case,a);message(`Assessment saved. Evidence supports ${a.coverage.assessed}/${a.coverage.required_applicable} applicable checks.`);
}));

function card(row,kind){
 const article=text("article","");const badge=text("span",kind==="gap"?`${row.critical?"Critical gap":"Evidence gap"} · ${row.check_id}`:`${priority(row.priority)} · ${row.check_id||row.rule_id||"Evidence"}`,`badge ${kind==="gap"?"gap":row.priority>=3?"concern":"neutral"}`);article.append(badge);
 const legalReview = kind === "finding" && row.rule_id === "LG01" && row.priority === 3;
 if (legalReview) {
   article.append(text("h4", "Verify the legal effect on this property"));
   if (row.summary) article.append(text("p", `Reviewed source statement: "${row.summary}"`));
   article.append(text("p", "Ask the conveyancer to match the reviewed area to the unit, title and relevant instrument."));
 } else {
   article.append(text("h4",row.summary||row.benefit||row.reason||row.label));
 }
 if(row.reason)article.append(text("p",row.reason.replaceAll("_"," ").toLowerCase()));
 if(row.next_action)article.append(text("p",`Next action: ${row.next_action}`));
 if(row.confidence)article.append(text("p",`Confidence: ${row.confidence}`));
 if(row.evidence_ids?.length)article.append(text("p",`Evidence: ${row.evidence_ids.join(", ")}`));
 const details=document.createElement("details");details.append(text("summary","Details and provenance"),text("pre",pretty(row)));article.append(details);return article;
}
function cards(id,rows,kind,empty){const container=$(id);container.replaceChildren();if(!rows?.length){container.append(text("p",empty,"muted"));return;}rows.slice(0,6).forEach(r=>container.append(card(r,kind)));if(rows.length>6){const more=document.createElement("details");more.append(text("summary",`Show ${rows.length-6} more`));rows.slice(6).forEach(r=>more.append(card(r,kind)));container.append(more);}}
function metric(label,value,note){const m=text("div","","metric");m.append(text("span",label),text("strong",value),text("span",note));return m;}
function renderCheckRegister(a) {
  const catalog = state.catalog?.manifest_hash === a.manifest_hash ? state.catalog.inputs : {};
  const body = $("checks");
  body.replaceChildren();
  for (const check of a.check_results) {
    const id = check.check_id;
    const findings = a.findings.filter(item => item.check_id === id);
    const gaps = a.gaps.filter(item => item.check_id === id);
    const decisions = [...(a.purchase_decision?.drivers || []), ...(a.purchase_decision?.open_checks || [])]
      .filter(item => item.references?.includes(id));
    const stateLabel = check.state === "NOT_APPLICABLE" ? "Outside scope" :
      check.complete ? "Supported" : check.state === "ASSESSED" ? "Partially supported" : "Unresolved";
    const row = document.createElement("tr");
    row.dataset.checkId = id;
    const title = text("th", check.label);
    title.scope = "row";
    title.prepend(text("small", id));
    row.append(title, text("td", stateLabel));
    const reason = text("td", "");
    const notes = [...new Set([...findings.map(f => f.summary), check.detail,
      ...gaps.map(g => g.reason?.replaceAll("_", " ").toLowerCase())].filter(Boolean))];
    reason.append(text("p", notes.join(" · ") || check.reason || "Recorded in the saved assessment."));
    const refs = [...(check.evidence_ids || []), ...(check.snapshot_ids || [])];
    if (refs.length) {
      const evidence = document.createElement("details");
      evidence.append(text("summary", "Evidence references"), text("p", refs.join(" · ")));
      reason.append(evidence);
    }
    const action = text("td", "");
    const actions = [...new Set([...decisions.map(d => d.action), ...gaps.map(g => g.next_action), check.next_action].filter(Boolean))];
    action.append(text("p", actions.join(" ") || (check.complete ? "No outstanding evidence request." : check.state === "NOT_APPLICABLE" ? "No action for this case." : "Review the evidence for this check.")));
    if (!check.complete && check.state !== "NOT_APPLICABLE" && catalog[id]?.length)
      action.append(text("p", "Catalogue inputs: " + catalog[id].join(", "), "muted"));
    row.append(reason, action, text("td", priority(check.priority)), text("td", check.confidence));
    body.append(row);
  }
}
function renderAssessment(a){
 const savedOffer = $("saved-offer-link");
 savedOffer.hidden = !a.weekend && (!a.preoffer_brief || !state.case?.preoffer);
 savedOffer.textContent = a.weekend ? "Open saved weekend worksheet" : "Open saved offer brief";
 if (!savedOffer.hidden) savedOffer.href = (a.weekend ? "/weekend?assessment=" : "?brief=") + encodeURIComponent(a.assessment_id);
 state.assessment=a;renderPurchaseDecision(a);$("assessment-title").textContent=state.case?.property?.label||a.property_id;
 $("metrics").replaceChildren(metric("Evidence supports",`${a.coverage.assessed}/${a.coverage.required_applicable}`,"Applicable checks with sufficient evidence"),metric("Catalogue checks evaluated",a.check_results.length,"Each row has a recorded result"),metric("Unresolved checks",a.coverage.not_assessed,`${a.coverage.critical_gaps.length} critical`),metric("Known concern",a.priority??"—","Highest supported action priority"));
 const scope = state.case?.demonstration ? "Fictional case. All property and buyer evidence is synthetic." : state.case?.finance_is_illustrative ? "Public address. Purchase terms and household amounts are illustrative." : "";
 $("assessment-note").textContent=`${scope} Saved assessment as of ${a.as_of}.`.trim();
 cards("findings",a.findings,"finding","No supported findings in the available evidence.");cards("gaps",a.gaps,"gap","No recorded gaps; confirm the scope of required checks.");cards("opportunities",a.opportunities,"opportunity","No supported potential benefits in the supplied evidence.");
 renderCheckRegister(a);
 $("provenance").textContent=pretty({assessment_id:a.assessment_id,input_hash:a.input_hash,engine_version:a.engine_version,purchase_rule_version:a.purchase_rule_version,rule_version:a.rule_version,manifest_hash:a.manifest_hash,snapshot_ids:a.input_snapshot_ids,limitations:a.limitations});
 renderFinance(a.financial_scenarios);$("download-json").disabled=false;$("open-report").disabled=false;
}
function renderFinance(fin){
 const container=$("finance");container.replaceChildren();if(!fin){container.append(text("p","Financial inputs are incomplete."));return;}
 const base=document.createElement("div");base.className="metrics";base.append(metric("Monthly mortgage",money(fin.repayment?.monthly_payment),"At the supplied borrower rate"),metric("Base monthly surplus",money(fin.baseline?.monthly_surplus),"After declared living, debt and property costs"),metric("Settlement funding gap",money(fin.settlement?.funding_gap),"Separate from ongoing cash flow"));container.append(base);
 const table=document.createElement("table"),head=document.createElement("thead"),hr=document.createElement("tr");["Scenario","Duration","Lowest cash","Protected reserve","First breach"].forEach(x=>hr.append(text("th",x)));head.append(hr);table.append(head);const body=document.createElement("tbody");
 for(const s of fin.scenarios||[]){const tr=document.createElement("tr");[s.scenario_id,s.duration_months?`${s.duration_months} months`:s.state,money(s.minimum_cash),money(s.protected_reserve),s.state!=="ASSESSED"?s.reason:s.first_breach_month===null?"No breach in this period":`Month ${s.first_breach_month}`].forEach(x=>tr.append(text("td",x)));body.append(tr);}table.append(body);const wrap=text("div","","table-wrap");wrap.append(table);container.append(wrap);
 const longest=(fin.scenarios||[]).filter(s=>s.state==="ASSESSED").sort((a,b)=>b.duration_months-a.duration_months)[0];if(longest)container.append(cashChart(longest));
 const d=document.createElement("details");d.append(text("summary","All calculation inputs and monthly schedules"),text("pre",pretty(fin)));container.append(d);
}
function cashChart(s){
 const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox","0 0 900 260");svg.setAttribute("role","img");svg.setAttribute("aria-label",`Cash trajectory for ${s.scenario_id}, protected reserve ${money(s.protected_reserve)}`);svg.style.width="100%";svg.style.margin="24px 0";
 const values=[Number(s.initial_cash),...s.monthly_schedule.map(r=>Number(r.closing_cash))],reserve=Number(s.protected_reserve);const lo=Math.min(0,...values,reserve),hi=Math.max(...values,reserve,1)*1.1;const x=i=>85+i/(values.length-1||1)*765,y=v=>210-(v-lo)/(hi-lo)*170;
 const line=(points,colour,dash)=>{const el=document.createElementNS(ns,"polyline");el.setAttribute("points",points);el.setAttribute("fill","none");el.setAttribute("stroke",colour);el.setAttribute("stroke-width","3");if(dash)el.setAttribute("stroke-dasharray","7 5");svg.append(el);};
 const label=(value,px,py,colour)=>{const el=document.createElementNS(ns,"text");el.textContent=value;el.setAttribute("x",px);el.setAttribute("y",py);el.setAttribute("fill",colour||"#536c76");el.setAttribute("font-size","13");svg.append(el);};
 line(`${x(0)},${y(reserve)} ${x(values.length-1)},${y(reserve)}`,"#ac6e16",true);line(values.map((v,i)=>`${x(i)},${y(v)}`).join(" "),"#096b64");label(`${s.scenario_id}: cash held`,85,20,"#096b64");label(`Reserve ${money(reserve)}`,620,20,"#8b5705");label(money(values[0]),0,y(values[0])+5);label(money(values.at(-1)),745,y(values.at(-1))+23);label("Month 0",85,245);label(`Month ${values.length-1}`,785,245);return svg;
}
function saveBlob(name,body,type){const url=URL.createObjectURL(new Blob([body],{type}));const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
$("download-json").addEventListener("click",()=>saveBlob("property-assessment.json",pretty(state.assessment),"application/json"));
$("open-report").addEventListener("click",e=>task(e.target,async()=>{const html=await api(`/v1/assessments/${encodeURIComponent(state.assessment.assessment_id)}/report`);saveBlob("property-assessment.html",html,"text/html");message("Report saved as a standalone HTML file. Open it in your browser or print it to PDF.");}));

function renderEvidence(obs,docs){$("observations").replaceChildren();for(const o of obs){const a=text("article","");a.append(text("h4",`${o.check_id} · ${o.source_id}`),text("p",`${o.visibility_scope} · ${o.observation_id}`));const d=document.createElement("details");d.append(text("summary","Inspect captured evidence"),text("pre",pretty(o)));a.append(d);$("observations").append(a);}$("documents").replaceChildren();for(const d of docs){const a=text("article","");a.append(text("h4",d.filename||d.document_id),text("p",`Review: ${d.extraction_status}`),text("p",`Snapshot: ${d.snapshot_id}`));$("documents").append(a);}}
$("import-observations").addEventListener("click",e=>task(e.target,async()=>{if(!state.case)throw Error("Save a case first.");let rows=JSON.parse($("observation-json").value);if(!Array.isArray(rows))rows=rows.observations||[rows];for(const row of rows)await post(`/v1/cases/${encodeURIComponent(state.case.case_id)}/observations`,row);await loadCase(state.case.case_id);message(`Imported ${rows.length} observations. Run a new assessment to include eligible evidence.`);}));
$("upload-document").addEventListener("click",e=>task(e.target,async()=>{if(!state.case)throw Error("Save a case first.");const f=$("document-file").files[0];if(!f)throw Error("Choose a document.");if(f.size>5000000)throw Error("Document exceeds the 5 MB limit.");const bytes=new Uint8Array(await f.arrayBuffer());let binary="";for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));const result=await post(`/v1/cases/${encodeURIComponent(state.case.case_id)}/documents`,{filename:f.name,media_type:f.type||"text/plain",content_base64:btoa(binary)});await loadCase(state.case.case_id);message(`Document captured for review. Snapshot ${result.snapshot_id}`);}));
async function loadSources(){const result=await api("/v1/sources");state.sources=result.sources;$("source-select").replaceChildren();$("source-table").replaceChildren();for(const s of result.sources){const o=text("option",`${s.source_id} — ${s.title}`);o.value=s.source_id;$("source-select").append(o);const tr=document.createElement("tr");[s.title,s.adapter,s.access_status,s.licence_status].forEach(v=>tr.append(text("td",v)));$("source-table").append(tr);}}
$("collect-source").addEventListener("click",e=>task(e.target,async()=>{if(!state.case)throw Error("Save a case first.");const result=await post(`/v1/cases/${encodeURIComponent(state.case.case_id)}/collect`,{source_id:$("source-select").value,max_records:Number($("max-records").value),bounds:JSON.parse($("bounds").value),max_bytes:20000000});$("collection-result").textContent=pretty(result);message(`Collection status: ${result.status}. Captured rows do not establish property coverage.`);}));
