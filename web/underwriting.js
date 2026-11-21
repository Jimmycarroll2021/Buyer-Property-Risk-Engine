"use strict";

const previewMode = () => document.documentElement.dataset.access === "preview";
const workedCaseId = "jardine-first-home-example-v1";
const publicCaseId = "jardine-first-home-public-v1";

const householdInputs = [
  ["principal", "Loan principal ($)"], ["loan_funds", "Net loan advance at settlement ($)"],
  ["annual_rate_decimal", "Interest rate (%)", "percent"], ["term_months", "Loan term (months)", "integer"],
  ["cash_allocated", "Cash allocated to purchase ($)"], ["total_liquid_cash", "Total liquid cash before purchase ($)"],
  ["cash_after_settlement", "Cash after settlement and day-one works ($)"], ["protected_reserve", "Emergency reserve to protect ($)"],
  ["acquisition_costs", "Duty, legal and acquisition costs ($)"], ["immediate_works", "Works paid at settlement ($)"],
  ["income_monthly", "Monthly household take-home income ($)"], ["living_monthly", "Monthly living expenses ($)"],
  ["other_debt_monthly", "Monthly other debt payments ($)"], ["property_costs_monthly", "Monthly rates, levies, cover and upkeep ($)"],
  ["funding_confirmed", "Written funding confirmed", "yesno"]
];
const scenarioInputs = [
  ["rate_rise_bps", "Mortgage rate rise (percentage points)", "bps"], ["repair_cost", "Repair quote ($)"],
  ["repair_month", "Repair month (1–12)", "month"], ["repair_overrun_pct", "Repair overrun (%)"],
  ["lost_income_monthly", "Take-home pay lost each month ($)"], ["loss_months", "Months without that income (0–12)", "duration"],
  ["extra_expense_monthly","Extra monthly expenses during income loss ($)"],
  ["sale_price_3y","Assumed resale price in year 3 ($)"], ["sale_price_5y","Assumed resale price in year 5 ($)"],
  ["selling_cost_pct","Selling costs (% of resale price)"], ["selling_cost_fixed","Additional fixed selling costs ($)"]
];
const protectionInputs = {
  property: ["Building and contents", [
    ["scope","Building cover arrangement","scope"],["written_confirmed","Written policy verified","yesno"],
    ["annual_premium","Annual premium ($)"],["excess","Claim excess ($)"],["sum_insured","Building sum insured ($)"],["rebuild_cost","Estimated rebuild cost ($)"]]],
  illness: ["Income protection", [
    ["policy_confirmed","Cover verified","yesno"],["waiting_days","Waiting period (days)","integer"],
    ["net_benefit_monthly","Monthly after-tax benefit ($)"],["lost_income_monthly","Monthly take-home income lost ($)"]]],
  career: ["Career change and savings goals", [
    ["goal_monthly","Savings goal each month ($)"],["lost_income_monthly","Monthly income reduction ($)"],["duration_months","Months at reduced income","integer"]]]
};
for (const [id, label] of [["disability","Total and permanent disability"],["death","Death of an earner"]]) {
  protectionInputs[id] = [label, [
    ["policy_confirmed","Cover verified","yesno"],["benefit","Lump-sum benefit ($)"],["remaining_income_monthly","Remaining monthly take-home income ($)"],
    ["ongoing_costs_monthly","Monthly household costs after the event ($)"],["one_off_costs","One-off costs ($)"],
    ["horizon_months","Months of support to test","integer"],["payout_delay_months","Months before payout","integer"]]];
}

function inputGroup(title, prefix, fields) {
  const details = text("details", "", "offer-options");
  details.append(text("summary",title));
  const grid = text("div","","offer-option-grid");
  for (const [id, label, kind] of fields) {
    const wrapper = text("label",label);
    const select = ["yesno","scope"].includes(kind);
    const input = document.createElement(select ? "select" : "input");
    input.name = prefix + id;
    if (select) {
      const choices = kind === "scope" ? [["","Unknown"],["owner","Owner policy"],["strata","Strata policy"]] : [["","Unknown"],["true","Yes"],["false","No"]];
      choices.forEach(([value, title])=>input.add(new Option(title,value)));
    } else {
      input.type = "number";
      input.min = kind === "month" ? "1" : "0";
      input.step = ["month","duration","integer"].includes(kind) ? "1" : "any";
      if (["duration","month"].includes(kind)) input.max = "12";
      input.placeholder = "Unknown";
    }
    wrapper.append(input); grid.append(wrapper);
  }
  details.append(grid);
  return details;
}
function setupPrivateInputs() {
  if (previewMode()) return;
  const panel = $("private-inputs");
  panel.append(inputGroup("Your household and settlement figures","fin_",householdInputs),
    inputGroup("Stress and resale assumptions","sc_",scenarioInputs));
  for (const [key,[label,fields]] of Object.entries(protectionInputs)) panel.append(inputGroup(label,"ins_"+key+"_",fields));
}
function groupValues(values, prefix, fields) {
  const out = {};
  for (const [key,,kind] of fields) {
    const raw = values.get(prefix+key);
    if (raw === null || raw === "") continue;
    if (kind === "percent") out[key] = String(Number(raw)/100);
    else if (kind === "bps") out[key] = Math.round(Number(raw)*100);
    else if (kind === "yesno") out[key] = raw === "true";
    else if (["month","duration","integer"].includes(kind)) out[key] = Number(raw);
    else out[key] = raw;
  }
  return out;
}
function fillGroup(prefix, fields, record) {
  for (const [key,,kind] of fields) {
    const input = offerField(prefix+key);
    if (!input) continue;
    const value = record?.[key];
    input.value = value == null ? "" : kind === "percent" ? Number(value)*100 : kind === "bps" ? Number(value)/100 : value;
  }
}
function readPrivateInputs(values) {
  if (previewMode()) return {finance:{}, settings:{}, protection:{}};
  const protection = {};
  for (const [key,[,fields]] of Object.entries(protectionInputs)) {
    const group = groupValues(values,"ins_"+key+"_",fields);
    if (Object.keys(group).length) protection[key] = group;
  }
  return {finance:groupValues(values,"fin_",householdInputs),settings:groupValues(values,"sc_",scenarioInputs),protection};
}
function fillPrivateInputs(record) {
  if (previewMode()) return;
  fillGroup("fin_",householdInputs,record.finance);
  fillGroup("sc_",scenarioInputs,record.preoffer);
  for (const [key,[,fields]] of Object.entries(protectionInputs)) fillGroup("ins_"+key+"_",fields,record.buyer_protection?.[key]);
}

async function readExample(id) {
  const items = (await api("/v1/cases/"+id+"/assessments")).assessments;
  const item = items.filter(a=>a.display_allowed!==false).at(-1);
  if (!item) throw Error("The worked brief has not yet been saved in this workspace.");
  const assessment = await api("/v1/assessments/"+encodeURIComponent(item.assessment_id));
  const saved = await api("/v1/cases/"+id+"?version="+assessment.preoffer_brief.case_version);
  return {assessment,saved};
}

function chartCash(base, stress, reserve) {
  const cash = row => Number(row.cash);
  const a = base?.timeline || [], b = stress?.timeline || [];
  if (!a.length || !b.length || reserve == null || [...a,...b].some(row=>row.cash == null || !Number.isFinite(cash(row)))) return null;
  const max = Math.max(1,Number(reserve),...a.map(cash),...b.map(cash)), min = Math.min(0,...a.map(cash),...b.map(cash));
  const width=700,height=210, x = i=>72+i*610/12, y=v=>18+(max-v)*155/(max-min);
  const ns="http://www.w3.org/2000/svg", svg=document.createElementNS(ns,"svg");
  svg.setAttribute("viewBox", "0 0 "+width+" "+height);
  svg.setAttribute("aria-label","Cash held from settlement through month twelve. Exact balances are available in the monthly table."); svg.setAttribute("role","img");
  function line(points, color, dash) {
    const path=document.createElementNS(ns,"polyline");
    for (const [key,value] of Object.entries({points,fill:"none",stroke:color,"stroke-width":3})) path.setAttribute(key,value);
    if (dash) path.setAttribute("stroke-dasharray",dash);
    svg.append(path);
  }
  function axisLabel(value,xPos,yPos,anchor) {
    const label=document.createElementNS(ns,"text");
    label.textContent=value;
    for (const [key,val] of Object.entries({x:xPos,y:yPos,"text-anchor":anchor,fill:"#45616c","font-size":12})) label.setAttribute(key,val);
    svg.append(label);
  }
  for (const tick of [max,0,...(min<0 ? [min] : [])]) {
    line(x(0)+","+y(tick)+" "+x(12)+","+y(tick),"#d3dedb","2 8");
    axisLabel(new Intl.NumberFormat("en-AU",{style:"currency",currency:"AUD",notation:"compact",maximumFractionDigits:1}).format(tick),x(0)-7,y(tick)+4,"end");
  }
  for (const month of [0,3,6,9,12]) axisLabel(month===0 ? "Settlement" : "Month "+month,x(month),196,month===0 ? "start" : month===12 ? "end" : "middle");
  line(x(0)+","+y(Number(reserve))+" "+x(12)+","+y(Number(reserve)), "#9b701f","6 6");
  line(a.map(r=>x(r.month)+","+y(cash(r))).join(" "), "#00796c");
  line(b.map(r=>x(r.month)+","+y(cash(r))).join(" "), "#ac4138");
  const fig = text("figure","","runway-chart"); fig.append(svg);
  fig.append(text("figcaption","Settlement → month 12   ·   Green: baseline   ·   Red: combined stress   ·   Dashed: protected reserve"));
  return fig;
}

function metric(label,value,detail) {
  const el = text("div","","cash-metric"); el.append(text("span",label),text("strong",value),text("small",detail)); return el;
}
function formatRate(number) { return number == null ? "Unknown" : Number(number).toLocaleString("en-AU",{maximumFractionDigits:2})+"%"; }
function monthLabel(value, known) {
  return value == null ? known ? "None in year one" : "Unknown" : Number(value)===0 ? "At settlement" : "Month "+value;
}
function sourceRows(section, rows) {
  for (const row of rows || []) {
    const detail = text("details","","underwriting-row");
    const summary = text("summary","");
    summary.append(text("span", row.title),text("small",readable(row.status),"row-state"));
    detail.append(summary);
    if (row.detail) detail.append(text("p",row.detail));
    if (row.action) detail.append(labelledFact("Next step",row.action));
    const metrics=Object.entries(row.metrics || {}).filter(([,val])=>val!=null && (typeof val!=="object" || Object.keys(val).length));
    if (metrics.length) {
      const measured=text("details","","metric-detail");
      measured.append(text("summary","Figures and source records"));
      for (const [k,v] of metrics) {
        if (typeof v==="object") {
          const group=text("details",""); group.append(text("summary",readable(k)),text("pre",JSON.stringify(v,null,2))); measured.append(group);
        } else measured.append(labelledFact(readable(k),String(v)));
      }
      detail.append(measured);
    }
    const urls = [...new Set([row.source_url,...(row.references || [])].filter(ref=>typeof ref==="string" && /^https?:\/\//.test(ref)))];
    for (const url of urls) {const link=externalLink(new URL(url).hostname,url); if (link) detail.append(link,document.createTextNode(" "));}
    section.append(detail);
  }
}
function expandSection(label, content) {
  const shell=text("details","","panel underwrite-drawer"); shell.append(text("summary",label),content); return shell;
}

function survivalLead(saved,brief) {
  const survival = brief.survival, s = survival.settlement, base = survival.baseline.first_year, stressed = survival.combined.first_year;
  const lead = text("section","","survival-lead");
  const label = survival.illustrative ? "Worked example · Fictional household" : Object.keys(saved.finance || {}).length ? "Your household assessment" : "Public address evidence · Household unknown";
  lead.append(text("p",label+" · "+brief.as_of.slice(0,10),"eyebrow"),text("h2",saved.property.label));
  const marketing=brief.underwriting?.public_marketing;
  if (marketing) {
    const line = text("p","Agent guide "+displayAmount(marketing.guide_low)+"–"+displayAmount(marketing.guide_high)+" · "+marketing.as_of+" · ");
    const source=externalLink("Selling agent",marketing.guide_source_url); if (source) line.append(source);
    lead.append(line);
  }
  if (s.offer_price != null) lead.append(text("p",(survival.illustrative ? "Fictional offer " : "Price entered ")+displayAmount(s.offer_price)));
  const low=survival.combined;
  const leadDetail=low.minimum_cash==null ? survival.detail : "Lowest cash "+displayAmount(low.minimum_cash)+" in month "+low.minimum_cash_month+". "+
    (Number(low.cash_shortfall)>0 ? "The household needs "+displayAmount(low.cash_shortfall)+" more to meet its payments." :
      Number(low.reserve_shortfall)>0 ? "Protecting the emergency reserve takes "+displayAmount(low.reserve_shortfall)+" more." : "Year-end cash "+displayAmount(low.ending_cash)+".");
  lead.append(text("h3",survival.headline),text("p",leadDetail));
  const metrics = text("div","","cash-strip");
  metrics.append(metric("Cash to close",displayAmount(s.cash_required),"Deposit, fees and day-one works"),
    metric("Total year-one cash out",displayAmount(base.total_cash_out),"Includes closing, mortgage and living costs"),
    metric("Year-one cash out under stress",displayAmount(stressed.total_cash_out),"Includes the extra repair and expenses"),
    metric("Starting mortgage debt",displayAmount(brief.costs?.offer_comparison?.[0]?.principal),"Loan balance at purchase"));
  lead.append(metrics);
  const ledger=text("details","","cash-ledger");
  ledger.append(text("summary","See the cash breakdown and income offsets"),
    offerTable(["Year one, AUD","Baseline","Combined stress"],
      [["Deposit","deposit"],["Acquisition costs","acquisition_costs"],["Works at settlement","immediate_works"],["Mortgage repayments","mortgage"],
       ["Living costs and other debt payments","living_and_other_debt"],["Property running costs","property_running_costs"],
       ["Additional expenses","extra_expenses"],["Separate urgent repair","urgent_repair"],["Total cash out","total_cash_out"],
       ["Take-home income and net rent","income_and_net_rent"],["Net cash used including settlement","net_cash_used_including_settlement"]]
        .map(([label,key])=>[label,displayAmount(base[key]),displayAmount(stressed[key])])));
  lead.append(ledger);
  const jump=text("a","Test the rate rise, repair bill and lost income →","stress-jump"); jump.href="#offer-stress"; lead.append(jump);
  if (survival.missing_inputs.length) {
    const missing=text("details"); missing.append(text("summary","Missing or unconfirmed inputs ("+survival.missing_inputs.length+")"),text("p",survival.missing_inputs.map(readable).join(", ")));
    lead.append(missing);
  }
  return lead;
}

function scenarioComparison(s) {
  const rows = [
    ["Cash after settlement", b => displayAmount(b.opening_cash)],
    ["Lowest balance", b => displayAmount(b.minimum_cash)+(b.minimum_cash_month == null ? "" : " · month "+b.minimum_cash_month)],
    ["Protected reserve first breached", b=>monthLabel(b.first_reserve_breach_month,b.timeline?.length && s.settlement.protected_reserve!=null)],
    ["Payments first exceed available cash", b=>monthLabel(b.first_shortfall_month,b.timeline?.length)],
    ["Extra cash needed to cover payments", b=>displayAmount(b.cash_shortfall)],
    ["Extra cash needed to protect reserve", b=>displayAmount(b.reserve_shortfall)],
    ["Cash at end of year", b=>displayAmount(b.ending_cash)],
    ["Opening buffer rebuilt", b=>b.rebuild_month!=null ? "Month "+b.rebuild_month : !b.timeline?.length ? "Unknown" : Number(b.minimum_cash)>=Number(b.opening_cash) ? "Opening buffer held" : "Beyond modelled year"]
  ];
  return offerTable(["Cash runway","Baseline","Combined stress"],rows.map(([label,fn])=>[label,fn(s.baseline),fn(s.combined)]));
}
function stressPanel(saved,brief) {
  const s=brief.survival, terms=s.assumptions;
  const section=offerSection("Could you get through the first year?","offer-stress");
  const summary = text("p",terms.lost_income_monthly==null || terms.repair_cost==null
    ? "Provide the income at risk, repair estimate and household budget to calculate payment shortfalls and the protected reserve."
    : "Lose "+displayAmount(terms.lost_income_monthly)+" a month for "+terms.loss_months+" months. Mortgage rates rise "+(Number(terms.rate_rise_bps)/100)+" percentage points. A "+displayAmount(terms.repair_cost)+" repair in month "+terms.repair_month+" runs "+formatRate(terms.repair_overrun_pct)+" over budget.");
  section.append(summary);
  const result=text("div","","stress-output");
  if (saved.finance && Object.keys(saved.finance).length && (!previewMode() || s.illustrative)) section.append(stressControls(saved,brief,result,summary));
  section.append(result);
  showStressOutput(result,s);
  return section;
}
function showStressOutput(section,s) {
  section.replaceChildren();
  const chart = chartCash(s.baseline,s.combined,s.settlement.protected_reserve); if (chart) section.append(chart);
  section.append(scenarioComparison(s));
  const lifeline = s.combined;
  if (lifeline.cash_shortfall != null && Number(lifeline.cash_shortfall)>0) section.append(text("p","Lifeline to price before committing: "+displayAmount(lifeline.cash_shortfall)+" extra liquid cash would cover the modelled payments. Keeping the reserve intact takes "+displayAmount(lifeline.reserve_shortfall)+". Confirm a source or rerun with a smaller offer or lower repair exposure.","lifeline"));
  else if (lifeline.reserve_shortfall!=null && Number(lifeline.reserve_shortfall)>0) section.append(text("p","Keeping the reserve intact takes "+displayAmount(lifeline.reserve_shortfall)+" more cash. Compare a lower offer or a written repair cap before committing.","lifeline"));
  section.append(labelledFact("Mortgage rate where normal monthly cash flow reaches zero",s.break_even_rate_state==="calculated" ? formatRate(s.break_even_rate_pct) : readable(s.break_even_rate_state)));
  const table=text("details","","cash-ledger"); table.append(text("summary","Monthly balances, payments and assumptions"));
  if (lifeline.timeline.length) table.append(offerTable(["Month","Baseline cash","Stress cash","Income","Mortgage","Other outgoings","Repair","Monthly surplus"],
    lifeline.timeline.map((r,i)=>[r.month===0 ? "Settlement" : r.month,displayAmount(s.baseline.timeline?.[i]?.cash),displayAmount(r.cash),
      ...["income","mortgage","outgoings","repair","net"].map(k=>r.month===0 ? "—" : displayAmount(r[k]))])));
  const notes=text("ul",""); for (const note of s.basis || []) notes.append(text("li",note));
  table.append(text("p",s.detail),notes); section.append(table);
}

function stressControls(saved,brief,result,summary) {
  const survival=brief.survival;
  const form=text("form","","stress-form");
  const group=text("fieldset","","dial-grid"); group.append(text("legend","Change the combined scenario"));
  const specs=[
    ["rate_rise_bps","Rate rise (percentage points)",Number(survival.assumptions.rate_rise_bps)/100,0,20,.1],
    ["repair_cost","Additional repair estimate ($)",survival.assumptions.repair_cost,0,null,1],
    ["repair_overrun_pct","Repair overrun (%)",survival.assumptions.repair_overrun_pct,0,null,1],
    ["lost_income_monthly","Monthly take-home pay lost ($)",survival.assumptions.lost_income_monthly,0,saved.finance.income_monthly,.01],
    ["loss_months","Months without the income",survival.assumptions.loss_months,0,12,1]
  ];
  for (const [id,label,value,min,max,step] of specs) {
    const wrap=text("label",label), input=document.createElement("input");
    input.name=id; input.type="number"; input.value=value ?? ""; input.min=min;
    if (max!=null) input.max=max;
    input.step=step; input.required=true; input.id="stress-"+id; wrap.htmlFor=input.id; wrap.append(input);
    if (id==="rate_rise_bps" || id==="repair_overrun_pct") {
      const range=document.createElement("input");
      range.type="range"; range.min=0; range.max=id==="rate_rise_bps" ? Math.max(6,Number(value)) : Math.max(100,Number(value)); range.step=step;
      range.setAttribute("aria-label",label+" slider"); range.value=value;
      range.addEventListener("input",()=>{input.value=range.value;});
      input.addEventListener("input",()=>{if (Number(input.value)>Number(range.max)) range.max=input.value;range.value=input.value;});
      wrap.append(range);
    }
    group.append(wrap);
  }
  const button=text("button","Save scenario"); button.type="submit"; group.append(button);
  const status=text("p","","offer-note"); status.setAttribute("role","status");
  form.append(group,status);
  function changesFromForm() {
    const changes={};
    for (const [key,value] of new FormData(form)) changes[key]=key==="rate_rise_bps" ? Math.round(Number(value)*100) : key==="loss_months" ? Number(value) : value;
    return changes;
  }
  let timer, revision=0;
  form.addEventListener("input",()=>{
    clearTimeout(timer);
    const request=++revision; result.replaceChildren(); summary.hidden=true; button.disabled=true;
    if (!form.checkValidity()) {status.textContent="Enter valid scenario amounts to estimate the new runway.";return;}
    status.textContent="Recalculating unsaved scenario…";
    timer=setTimeout(async ()=>{
      try {
        const next=await post("/v1/cases/"+encodeURIComponent(saved.case_id)+"/survival-preview",{
          assessment_id:brief.assessment_id,case_version:saved.case_version,changes:changesFromForm()});
        if (request!==revision || !form.isConnected) return;
        showStressOutput(result,next);
        status.textContent="Unsaved scenario · "+next.headline+". Lowest cash "+displayAmount(next.combined.minimum_cash)+" (saved "+displayAmount(survival.combined.minimum_cash)+"). First-year cash out "+displayAmount(next.combined.first_year.total_cash_out)+". Save to update the whole brief.";
        button.disabled=false;
      } catch (error) {
        if (request===revision && form.isConnected) status.textContent="Scenario unavailable. "+error.message;
      }
    },200);
  });
  form.addEventListener("submit",async e=>{
    e.preventDefault(); clearTimeout(timer); ++revision;
    const changes=changesFromForm();
    group.disabled=true; status.textContent="Recalculating the year…";
    try {
      // A shared demo creates a new copy. A private edit retains this case's evidence and version history.
      const fork = previewMode(), when = new Date().toISOString();
      const record={...saved,case_id:fork ? "stress-"+crypto.randomUUID() : saved.case_id,preoffer:{...saved.preoffer,...changes},as_of:when};
      const updated=await post("/v1/cases?expected_version="+(fork ? 0 : saved.case_version),record);
      const assessment=await post("/v1/cases/"+encodeURIComponent(updated.case_id)+"/assessments",{});
      offerPage.homes[offerPage.selected]={saved:updated,assessment};
      const params=new URLSearchParams({brief:offerPage.homes[0].assessment.assessment_id});
      if (offerPage.homes[1]) params.set("compare",offerPage.homes[1].assessment.assessment_id);
      history.replaceState(null,"","?"+params);
      const before=survival.combined.minimum_cash, after=assessment.preoffer_brief.survival.combined.minimum_cash;
      renderOfferResults();
      const result=text("p","Lowest balance before "+displayAmount(before)+" · revised "+displayAmount(after)+".","lifeline");
      result.setAttribute("role","status"); result.tabIndex=-1;
      $("offer-stress").querySelector("h3").after(result); result.focus();
    } catch (error) {status.textContent=error.message;} finally {group.disabled=false;}
  });
  return form;
}
function exitAndProtection(brief) {
  const s=offerSection("If you need to leave, change jobs or claim","offer-protection");
  s.append(text("h4","Sell in three or five years"),text("p","Sale prices are scenarios. The baseline mortgage schedule determines the remaining debt."));
  const exits=brief.survival.exit_scenarios || [];
  s.append(offerTable(["At sale",...exits.map(e=>"Year "+e.years)],
    [["Assumed resale price","sale_price"],["Debt still owing","remaining_debt"],["Gross equity","gross_equity"],["Cost to sell","selling_costs"],
     ["Cash left after sale","net_proceeds"],["Resale price to recover purchase and holding costs","break_even_resale"]].map(([label,k])=>[label,...exits.map(e=>displayAmount(e[k]))])));
  s.append(text("h4","Household protection and flexibility"));
  if (brief.protection?.assumptions) s.append(text("p",brief.protection.assumptions,"offer-note"));
  sourceRows(s,brief.protection?.rows); return s;
}
function propertyUnderwriting(brief) {
  const panel=offerSection("The home, the price and the exit","offer-underwriting");
  sourceRows(panel,brief.underwriting?.sections);
  return panel;
}


