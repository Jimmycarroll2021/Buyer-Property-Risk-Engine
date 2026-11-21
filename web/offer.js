"use strict";

const offerPage = {homes: [], selected: 0, examples: [], choices: {}, records: new Map()};
const offerField = name => $("offer-form").elements.namedItem(name);
const readable = value => String(value ?? "Unknown").replaceAll("_", " ");
const displayAmount = value => value === null || value === undefined ? "Unknown" : money(value);

function offerStatus(value, error = false) {
  $("offer-status").textContent = value;
  $("offer-status").dataset.error = String(error);
}

function offerAddress(slot, point) {
  const prefix = slot === "second" ? "second_" : "";
  offerField(prefix + "street").value = point.label.split(",")[0].trim();
  offerField(prefix + "suburb").value = point.suburb;
  offerPage.choices[slot] = point;
  $("offer-matches").replaceChildren();
}

function offerExampleButtons(slot, id) {
  const container = $(id);
  container.replaceChildren();
  if (!offerPage.examples.length) return;
  container.append(text("span", "Try a retained ACT address"));
  for (const point of offerPage.examples) {
    const button = text("button", point.label);
    button.type = "button";
    button.addEventListener("click", () => offerAddress(slot, point));
    container.append(button);
  }
}

function toggleComparison() {
  const active = $("compare-homes").checked;
  $("compare-fields").hidden = !active;
  for (const name of ["second_street", "second_suburb"]) offerField(name).required = active;
}

async function openOfferView() {
  const view = $("offer-view");
  $("workspace").hidden = true;
  $("welcome").hidden = true;
  $("switch-view").textContent = "Evidence workspace";
  document.title = "Before you make an offer | Property Risk";
  if (!view.firstElementChild) {
    const response = await fetch("/static/offer-form.html", {cache:"no-store"});
    if (!response.ok) throw Error("Could not load the offer form.");
    view.innerHTML = await response.text();
    setupPrivateInputs();
    $("choose-property").addEventListener("click", () => {
      const panel = $("offer-editor");
      panel.hidden = !panel.hidden;
      if (!panel.hidden) {
        $("offer-form").reset(); offerPage.choices={}; offerPage.editing=null;
        toggleComparison(); offerField("street").focus();
      }
    });
    $("privacy-route").addEventListener("click", () => {
      if (previewMode()) { $("private-launch").hidden = !$("private-launch").hidden; return; }
      $("offer-editor").hidden = false;
      const selected=offerPage.homes[offerPage.selected];
      if (selected) fillOfferForm([selected]);
      offerPage.editing=selected?.saved.finance_is_illustrative ? null : selected?.saved;
      offerField("sample_finance").checked = false;
      if (selected?.saved.finance_is_illustrative) {
        fillPrivateInputs({});
        offerField("offer_price").value = "";
      }
      const panel = $("private-inputs").querySelector("details");
      panel.open = true; panel.querySelector("input").focus();
    });
    $("compare-homes").addEventListener("change", toggleComparison);
    for (const [slot, prefix] of [["first", ""], ["second", "second_"]]) {
      for (const suffix of ["street", "suburb"]) offerField(prefix + suffix).addEventListener("input", () => {
        delete offerPage.choices[slot];
        $("offer-matches").replaceChildren();
      });
    }
    $("offer-form").addEventListener("submit", submitOffer);
    offerField("sample_finance").addEventListener("change", () => {
      if (!offerField("sample_finance").checked && offerField("selling_costs").value === "18000")
        offerField("selling_costs").value = "";
    });
    const preview = document.documentElement.dataset.access === "preview";
    $("offer-mode-note").textContent = preview ? "Shared local preview. Use sample amounts only." : "Saved in your local workspace.";
    try {
      const result = await api("/v1/locations/examples");
      offerPage.examples = result.matches;
      if (preview && !offerPage.examples.some(point=>String(point.address_id)==="140619")) {
        try {
          const publicRecord=await api("/v1/cases/"+publicCaseId);
          if (publicRecord.property?.identity_confirmed===true) offerPage.examples = [publicRecord.property,...offerPage.examples];
        } catch { /* Other preview installs may have only the original retained addresses. */ }
      }
      offerExampleButtons("first", "offer-examples");
      offerExampleButtons("second", "second-examples");
    } catch (error) {
      offerStatus("Address examples unavailable. You can still search by street and suburb. " + error.message, true);
    }
    $("jardine-demo").hidden = !preview;
    $("jardine-public").hidden = !preview;
    const url = new URLSearchParams(location.search);
    const ids = [url.get("brief"), url.get("compare")].filter(Boolean);
    if (ids.length) {
      try {
        offerPage.homes = await Promise.all(ids.map(async id => {
          const assessment = await api("/v1/assessments/" + encodeURIComponent(id));
          if (!assessment.preoffer_brief) throw Error("This assessment predates the offer brief.");
          const saved = await api("/v1/cases/" + encodeURIComponent(assessment.preoffer_brief.case_id) + "?version=" + assessment.preoffer_brief.case_version);
          return {assessment, saved};
        }));
        fillOfferForm(offerPage.homes);
        renderOfferResults();
      } catch (error) { offerStatus("Could not open the saved brief. " + error.message, true); }
    } else if (preview) {
      try {
        const id = url.get("example") === "jardine-address" ? publicCaseId : workedCaseId;
        offerPage.homes = [await readExample(id)];
        fillOfferForm(offerPage.homes);
        renderOfferResults();
      } catch (error) { offerStatus("Choose an address to begin. " + error.message); }
    }
  }
  view.hidden = false;
  message("");
}

function fillOfferForm(homes) {
  const c = homes[0].saved;
  const opt = c.preoffer;
  const prefs = c.buyer_preferences || {};
  offerAddress("first", c.property);
  $("compare-homes").checked = homes.length === 2;
  toggleComparison();
  if (homes[1]) offerAddress("second", homes[1].saved.property);
  for (const key of ["offer_price","price_basis","intended_use","horizon_months","alternative_offer_price","selling_costs","special_levy","levy_month"]) {
    const el = offerField(key);
    el.value = opt[key] ?? (el.tagName === "SELECT" ? el.options[0].value : el.defaultValue);
  }
  offerField("planned_works").value = prefs.planned_works || "as_is";
  offerField("priority").value = prefs.priorities?.[0] || "";
  offerField("rate_rise").value = Number(opt.rate_delta_bps ?? 200) / 100;
  offerField("income_loss").value = Number(((1 - Number(opt.income_factor ?? .8)) * 100).toFixed(2));
  offerField("cost_rise").value = Number(((Number(opt.property_cost_factor ?? 1.2) - 1) * 100).toFixed(2));
  fillPrivateInputs(c);
  offerField("sample_finance").checked = c.finance_is_illustrative === true;
}

async function resolveOfferPoint(slot, values) {
  const prefix = slot === "second" ? "second_" : "";
  const street = values.get(prefix + "street").trim();
  const suburb = values.get(prefix + "suburb").trim();
  const chosen = offerPage.choices[slot];
  if (chosen && street === chosen.label.split(",")[0].trim() && suburb === chosen.suburb) return chosen;
  const normalize = value => value.trim().replace(/\s+/g," ").toLowerCase();
  const exact = offerPage.examples.find(point=>normalize(point.label.split(",")[0])===normalize(street) && normalize(point.suburb)===normalize(suburb));
  if (exact) return exact;
  const result = await api("/v1/locations/search?" + new URLSearchParams({street, suburb}));
  if (result.matches.length === 1) {
    const candidate = result.matches[0];
    const returnedUnit = candidate.label.match(/^(\w+)\s*\//)?.[1];
    const typedUnit = street.match(/^(?:unit\s+)?(\w+)\s*\//i)?.[1];
    if (!returnedUnit || returnedUnit.toLowerCase() === typedUnit?.toLowerCase()) return candidate;
  }
  if (!result.matches.length) throw Error("No ACT register match for " + street + ", " + suburb + ". Check the number, street and suburb.");
  const matches = $("offer-matches");
  matches.replaceChildren(text("p", "Choose the matching " + (slot === "second" ? "second " : "") + "address."));
  for (const point of result.matches) {
    const button = text("button", point.label, "secondary");
    button.addEventListener("click", () => { offerAddress(slot, point); $("offer-form").requestSubmit(); });
    matches.append(button);
  }
  return null;
}

function offerSettings(values) {
  const options = {};
  for (const k of ["offer_price","price_basis","intended_use","alternative_offer_price","selling_costs","special_levy"])
    if (values.get(k)) options[k] = values.get(k);
  options.horizon_months = Number(values.get("horizon_months"));
  options.levy_month = Number(values.get("levy_month"));
  options.rate_delta_bps = Math.round(Number(values.get("rate_rise")) * 100);
  options.income_factor = (1 - Number(values.get("income_loss")) / 100).toFixed(4);
  options.property_cost_factor = (1 + Number(values.get("cost_rise")) / 100).toFixed(4);
  return options;
}

async function assessOfferPoint(point, values, example) {
  const privateData = readPrivateInputs(values);
  const settings = {...offerSettings(values),...privateData.settings};
  const sample = Boolean(example);
  const finance = sample ? {...example.finance} : privateData.finance;
  if (sample && !settings.offer_price) throw Error("Enter a hypothetical price to apply the fictional household.");
  if (!sample && settings.offer_price && Object.keys(finance).length) finance.purchase_price = settings.offer_price;
  if (sample) {
    Object.assign(settings, {lost_income_monthly:(Number(finance.income_monthly)*.45).toFixed(2), loss_months:4, repair_cost:"15000", repair_month:2, repair_overrun_pct:30, rate_rise_bps:150}, privateData.settings);
    // Keep the sample household's total cash fixed as the buyer changes the offer.
    const advance = Math.round(Number(settings.offer_price) * Number(finance.loan_funds) / Number(finance.purchase_price) * 100) / 100;
    const principal = Math.round(Number(settings.offer_price) * Number(finance.principal) / Number(finance.purchase_price) * 100) / 100;
    const cash = Number(finance.cash_allocated) + Number(finance.cash_after_settlement);
    const required = Number(settings.offer_price) + Number(finance.acquisition_costs) + Number(finance.immediate_works) - advance;
    Object.assign(finance, {principal:principal.toFixed(2), loan_funds:advance.toFixed(2),
      cash_allocated:Math.min(cash,required).toFixed(2), cash_after_settlement:Math.max(0,cash-required).toFixed(2),
      funding_confirmed:false});
  }
  if (sample) finance.purchase_price = settings.offer_price;
  const when = new Date().toISOString();
  const record = {
    case_id:"offer-" + crypto.randomUUID(), property_id:"act-address-" + point.address_id,
    assessment_mode:"buyer_assessment", as_of:when, property:{...point, jurisdiction:"ACT", identity_confirmed:point.identity_confirmed===true || point.retained_address_match===true || offerPage.examples.some(home => String(home.address_id) === String(point.address_id) && home.label === point.label)},
    preoffer:settings, buyer_preferences:{priorities:values.get("priority") ? [values.get("priority")] : [], planned_works:values.get("planned_works")},
    finance, buyer_protection:sample ? {} : privateData.protection, finance_is_illustrative:sample, requirements:[], scenarios:[]
  };
  const unit = point.label.match(/^(\d+[a-z]?)\//i);
  if (unit) record.property.unit_id = unit[1];
  const editing=offerPage.editing;
  if (!previewMode() && !sample && editing && String(editing.property.address_id)===String(point.address_id)) {
    const mergedFinance={...editing.finance,...finance};
    for (const [key] of householdInputs) {
      if (!Object.hasOwn(finance,key)) delete mergedFinance[key];
    }
    const scopedSettings={...editing.preoffer,...settings};
    for (const [key] of scenarioInputs) {
      if (!Object.hasOwn(privateData.settings,key)) delete scopedSettings[key];
    }
    const saved=await post("/v1/cases?expected_version="+editing.case_version,
      {...editing,preoffer:scopedSettings,finance:mergedFinance,buyer_protection:privateData.protection,buyer_preferences:record.buyer_preferences,as_of:when});
    offerPage.editing=saved;
    return {saved,assessment:await post("/v1/cases/"+encodeURIComponent(saved.case_id)+"/assessments",{})};
  }
  const signature = JSON.stringify([record.property, record.preoffer, record.buyer_preferences, finance, record.buyer_protection, sample]);
  let saved = offerPage.records.get(signature);
  if (!saved) {
    saved = await post("/v1/cases?expected_version=0", record);
    offerPage.records.set(signature,saved);
  }
  const assessment = await post("/v1/cases/" + encodeURIComponent(saved.case_id) + "/assessments",{});
  if (!assessment.preoffer_brief) throw Error("The running engine has no saved pre-offer brief. Restart the current local build.");
  return {saved, assessment};
}

async function submitOffer(event) {
  event.preventDefault();
  const values = new FormData(event.currentTarget);
  const compare = $("compare-homes").checked;
  $("offer-controls").disabled = true;
  $("offer-matches").replaceChildren();
  $("offer-results").hidden = true;
  offerStatus("Checking the address register…");
  try {
    const first = await resolveOfferPoint("first", values);
    if (!first) { offerStatus("Select the exact registered address."); return; }
    const points = [first];
    if (compare) {
      const second = await resolveOfferPoint("second", values);
      if (!second) { offerStatus("Select the second registered address."); return; }
      if (String(first.address_id) === String(second.address_id)) throw Error("Choose two different registered addresses to compare.");
      points.push(second);
    }
    offerStatus("Building the brief from the saved evidence and offer assumptions…");
    const example = values.has("sample_finance") ? await api("/v1/locations/kingston-example") : null;
    const homes = [];
    for (const point of points) homes.push(await assessOfferPoint(point, values, example));
    offerPage.homes = homes;
    offerPage.selected = 0;
    const query = new URLSearchParams({brief:homes[0].assessment.assessment_id});
    if (homes[1]) query.set("compare",homes[1].assessment.assessment_id);
    history.replaceState(null, "", "?" + query);
    renderOfferResults();
    offerStatus("Saved. Bookmark this brief to return to these assumptions.");
    $("offer-results").scrollIntoView({block:"start"});
  } catch (error) { offerStatus(error.message, true); }
  finally { $("offer-controls").disabled = false; }
}
function offerSection(title, id) {
  const section = text("section","","panel");
  if (id) section.id = id;
  section.append(text("h3",title));
  return section;
}

function labelledFact(label, value) {
  const row = text("p","");
  row.append(text("strong",label + " ","fact-label"), document.createTextNode(value ?? "Unknown"));
  return row;
}

function offerTable(headings, rows) {
  const wrapper = text("div","","offer-table");
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  headings.forEach(heading => { const th = text("th",heading); th.scope = "col"; head.append(th); });
  const body = table.createTBody();
  for (const values of rows) {
    const tr = body.insertRow();
    const title = text("th",values[0]); title.scope = "row"; tr.append(title);
    values.slice(1).forEach(value => tr.append(text("td",value)));
  }
  wrapper.append(table);
  return wrapper;
}

function offerSources(refs, assessment) {
  const info = text("details","","offer-source");
  info.append(text("summary","Sources and evidence references"));
  const list = document.createElement("ul");
  for (const ref of refs || []) {
    const entry = document.createElement("li");
    const finding = (assessment.findings || []).find(f => f.finding_id === ref);
    const savedSource = assessment.preoffer_capture?.home?.property?.public_sources?.find(source => "sha256:" + source.response_sha256 === ref);
    const check = assessment.check_results?.find(row => row.check_id === ref);
    const link = externalLink("", ref);
    if (link) { link.textContent = new URL(link.href).hostname; entry.append(link); }
    else if (savedSource) {
      const original = externalLink(readable(savedSource.source_id).toUpperCase() + " ? ACT register",savedSource.query_url);
      if (original) entry.append(original);
      entry.append(text("small"," ? captured " + savedSource.retrieved_at.slice(0,10)));
    }
    else if (check) entry.textContent = ref + " ? " + check.label;
    else if (ref === "financial_scenarios") entry.textContent = "Household and loan scenario inputs saved with this assessment";
    else if (finding) entry.append(text("span",finding.check_id + " · " + finding.summary), text("p",[...(finding.evidence_ids || []), ...(finding.snapshot_ids || [])].join(" · "),"muted"));
    else entry.textContent = ref;
    list.append(entry);
  }
  if (list.childElementCount) info.append(list);
  else info.append(text("p","No source reference was supplied for this open question."));
  return info;
}

function issueCards(brief, assessment) {
  const section = offerSection("Top three issues for this offer","offer-issues");
  const list = text("ol","","issue-list");
  for (const item of brief.top_three) {
    const card = document.createElement("li");
    card.dataset.kind = /unknown|open question|unverified|to verify/i.test(item.kind+" "+item.confidence) ? "unknown" : item.illustrative || /scenario|conditional|model/i.test(item.kind) ? "scenario" : "supported";
    card.append(text("p",item.kind,"eyebrow"),text("h4",item.title), text("p",item.detail),labelledFact("Next action",item.action));
    const basis=text("details","","offer-source");
    basis.append(text("summary","What could change the decision"),text("p",item.changes_outcome),
      text("p",[item.geography,item.confidence,item.as_of?.slice(0,10)].filter(Boolean).join(" · ")),offerSources(item.references,assessment));
    card.append(basis);
    list.append(card);
  }
  section.append(list);
  return section;
}

function priceEvidence(evidence) {
  const section = offerSection("What supports the price?","offer-sales");
  section.append(text("p",evidence.summary));
  for (const sale of evidence.comparables || []) {
    const card = document.createElement("article");
    card.append(text("h4",sale.address), text("p",displayAmount(sale.price) + " settled " + sale.settled_on),
      labelledFact("Offer less settled price",displayAmount(sale.difference_from_offer)),
      labelledFact("Matches",(sale.matches || []).join(" · ")),
      labelledFact("Differences",(sale.differences || []).join(" · ") || "None recorded"));
    if (sale.unverified_attributes?.length) card.append(labelledFact("Unverified",sale.unverified_attributes.join(", ")));
    const source = externalLink("Settled sale source",sale.source_url);
    if (source) card.append(source);
    section.append(card);
  }
  if (evidence.coverage) section.append(text("p",evidence.coverage));
  section.append(labelledFact("Next action",evidence.action));
  const source = externalLink("View sale evidence source",evidence.source_url);
  if (source) section.append(source);
  if (evidence.selection) section.append(text("p",evidence.selection,"offer-note"));
  return section;
}

function reserveText(row) {
  if (row.reserve_status === "breached") return Number(row.first_breach_month) === 0 ? "Breached at settlement" : "Breach in month " + row.first_breach_month;
  if (row.reserve_status === "held") return "Held for " + row.horizon_months + " months";
  return "Unknown";
}

function offerCosts(brief, saved) {
  const section = offerSection("Cost to buy, hold and sell","offer-costs");
  const costs = brief.costs, rows = costs.offer_comparison;
  const sample = brief.illustrative_finance;
  section.append(text("p",sample ? "Illustrative household and loan assumptions, in Australian dollars." : "Calculations use the available case amounts. Unknown amounts need buyer input."));
  const fields = [["Offer","offer_price"],["Cash needed at settlement","cash_required"],["Funding shortfall","settlement_funding_gap"],
    ["Cash left after settlement","cash_after_settlement"],["Monthly mortgage","monthly_repayment"],
    ["Month one household surplus","monthly_surplus"],["Lowest cash held","minimum_cash"],["Break-even resale price","break_even_resale"]];
  const metrics = fields.map(([label,key]) => [label,...rows.map(r=>displayAmount(r[key]))]);
  metrics.push(["Protected reserve",...rows.map(reserveText)]);
  section.append(offerTable(["Scenario",...rows.map(r=>r.label)],metrics));
  const s = saved.preoffer;
  section.append(text("p","Holding period " + s.horizon_months + " months · stressed rate +" + (Number(s.rate_delta_bps)/100) +
    " percentage points · income retained " + Math.round(Number(s.income_factor)*100) + "% · property costs " +
    Math.round(Number(s.property_cost_factor)*100) + "% of baseline · one-off levy " + displayAmount(s.special_levy) + " in month " + s.levy_month + ".","offer-note"));
  const missing = [...new Set(rows.flatMap(r=>r.missing_inputs || []))];
  if (missing.length) section.append(labelledFact("Needed to complete the figures",missing.map(readable).join(", ")));
  const details = text("details","");
  details.append(text("summary","Calculation basis and break-even components"));
  const assumptions = document.createElement("ul");
  for (const note of costs.assumptions || []) assumptions.append(text("li",note));
  details.append(assumptions);
  const components = [...new Set(rows.flatMap(row => Object.keys(row.break_even_detail || {})))];
  if (components.length) details.append(offerTable(["Component",...rows.map(r=>r.label)],
    components.map(key=>[readable(key),...rows.map(r=>displayAmount(r.break_even_detail?.[key]))])));
  const finance = saved.finance || {};
  const budget = ["principal","purchase_price","income_monthly","living_monthly","other_debt_monthly","property_costs_monthly","protected_reserve","acquisition_costs","immediate_works"];
  details.append(labelledFact("Loan assumptions",(finance.annual_rate_decimal == null ? "Unknown rate" : (Number(finance.annual_rate_decimal)*100) + "% annual interest") +
    " · " + (finance.term_months || "unknown") + " months"));
  details.append(offerTable(["Buyer input","Amount"], budget.map(key=>[readable(key),displayAmount(finance[key])])));
  section.append(details);
  return section;
}

function areaEvidence(assessment) {
  const section = offerSection("Planning, access and area conditions","offer-area");
  const ctx = assessment.decision_evidence || {};
  const decision = assessment.purchase_decision || {};
  const grid = text("div","","offer-data");
  for (const [key,label] of [["retained_location_evidence","Registered block and nearby designations"],["spatial","Land use at the address"],["planning","Nearby proposals and routes"],["crime","Reported offences in the suburb"]]) {
    const group = document.createElement("section");
    group.append(text("h4",label));
    const rows = key === "spatial" && ctx.retained_location_evidence?.some(r=>r.kind==="zoning") ? [] : ctx[key] || [];
    if (key === "spatial" && !rows.length && ctx.retained_location_evidence?.some(r=>r.kind==="zoning")) continue;
    rows.forEach((row,i) => {
      const detail = document.createElement("details");
      detail.open = i === 0;
      detail.append(text("summary",row.title),text("p",row.detail));
      const matched = [...(decision.open_checks || []),...(decision.context_notes || [])].find(item=>item.title===row.title);
      if (matched?.action) detail.append(labelledFact("Check",matched.action));
      if (matched?.changes_outcome) detail.append(labelledFact("What would change this",matched.changes_outcome));
      if (row.coverage) detail.append(text("p",row.coverage,"offer-note"));
      const s = externalLink("View source", row.source_url);
      if (s) detail.append(s);
      if (row.as_of) detail.append(text("small"," · " + row.as_of.slice(0,10),"muted"));
      group.append(detail);
    });
    if (!rows.length) group.append(text("p","No saved result for this address and date."));
    grid.append(group);
  }
  section.append(grid);
  return section;
}

function offerCoverage(brief,assessment) {
  const section = offerSection("Evidence coverage","offer-coverage");
  const c = brief.coverage;
  section.append(text("p",c.total + " catalogue checks evaluated. Each recorded state is shown below."));
  const stats = text("div","","offer-coverage");
  for (const [k,n] of Object.entries(c.states)) stats.append(text("span",readable(k).toLowerCase() + " · " + n));
  section.append(stats);
  const details = text("details","");
  details.append(text("summary","Inspect all " + c.total + " checks"));
  const gaps = assessment.gaps || [];
  const findings = assessment.findings || [];
  details.append(offerTable(["Check","State","Evidence or reason","Next action"],
    (assessment.check_results || c.checks).map(row => [
      row.check_id + " · " + row.label,readable(row.state),findings.find(f=>f.check_id===row.check_id)?.summary || row.detail || readable(row.reason),
      gaps.find(g=>g.check_id===row.check_id)?.next_action || row.next_action || "See the saved evidence for this check."])));
  section.append(details);
  return section;
}

function comparisonPanel(homes) {
  const panel = offerSection("Compare the two homes","offer-side-by-side");
  const briefs = homes.map(h=>h.assessment.preoffer_brief);
  const decisions = homes.map(h=>h.assessment.decision_evidence || {});
  panel.append(text("p","Both use the same household assumptions, holding period and " + displayAmount(homes[0].saved.preoffer.offer_price) + " price."));
  const rows = [["Decision",...briefs.map(b=>b.headline)],
    ...[0,1,2].map((i)=>["Issue " + (i+1),...briefs.map(b=>b.top_three[i]?.title || "No further issue listed")]),
    ["Mapped land use",...decisions.map(ctx=>ctx.retained_location_evidence?.find(row=>row.kind==="zoning")?.title || ctx.spatial?.[0]?.title || "Unknown")],
    ["Bushfire designation near the address",...decisions.map(ctx=>ctx.retained_location_evidence?.find(row=>row.kind==="bushfire_proximity")?.detail || "Unknown")],
    ["Closest saved proposal",...decisions.map(ctx=>ctx.planning?.[0]?.title || "Unknown")],
    ["Price evidence",...briefs.map(b=>b.costs.price_evidence.summary)],
    ["Stressed month one surplus",...briefs.map(b=>displayAmount(b.costs.offer_comparison.at(-1).monthly_surplus))],
    ["Break-even resale",...briefs.map(b=>displayAmount(b.costs.offer_comparison[0].break_even_resale))],
    ["Next action",...briefs.map(b=>b.next_action)]];
  panel.append(offerTable(["At the common price",...homes.map(h=>h.saved.property.label)],rows));
  const nav = text("nav","","offer-nav");
  nav.setAttribute("aria-label","Choose a property brief");
  homes.forEach((home,i)=>{
    const b = text("button",home.saved.property.label,"secondary");
    b.setAttribute("aria-pressed",String(i===offerPage.selected));
    b.addEventListener("click",()=>{ offerPage.selected=i; renderOfferResults(); $("offer-summary").scrollIntoView({block:"start"}); });
    nav.append(b);
  });
  panel.append(nav);
  return panel;
}

function renderOfferResults() {
  const homes = offerPage.homes;
  const {saved, assessment} = homes[offerPage.selected];
  const brief = assessment.preoffer_brief;
  $("offer-comparison").replaceChildren();
  if (homes.length>1) $("offer-comparison").append(comparisonPanel(homes));
  $("offer-editor").hidden = true;
  const summary = text("div","","offer-lead");
  summary.append(text("p","Pre-offer brief · " + brief.as_of.slice(0,10),"eyebrow"),text("h2",saved.property.label),
    text("p",(saved.preoffer.price_basis === "asking" ? "Asking price " : "Proposed offer ") + displayAmount(saved.preoffer.offer_price)),
    text("p",brief.headline,"lead"),labelledFact("Next action",brief.next_action));
  $("offer-summary").replaceChildren(brief.survival ? survivalLead(saved,brief) : summary);
  const actions = text("div","","offer-nav");
  const download = text("button","Save pinned assessment JSON","secondary");
  download.addEventListener("click",()=> saveBlob(saved.case_id + ".json",pretty(assessment),"application/json"));
  const caseLink = text("a","Open full evidence workspace","button secondary");
  caseLink.href = "?case=" + encodeURIComponent(saved.case_id);
  actions.append(download,caseLink);
  const issues = issueCards(brief,assessment);
  const sales = priceEvidence({...brief.costs.price_evidence,coverage:assessment.preoffer_capture?.sales_capture?.coverage});
  if (brief.survival) {
    $("offer-detail").replaceChildren(issues,stressPanel(saved,brief),exitAndProtection(brief),propertyUnderwriting(brief),
      expandSection("Offer price and eligible comparable sales",sales),expandSection("Alternative offer and long-hold costs",offerCosts(brief,saved)),
      expandSection("Planning and neighbourhood evidence",areaEvidence(assessment)),expandSection("Full evidence register",offerCoverage(brief,assessment)),actions);
  } else $("offer-detail").replaceChildren(issues,sales,offerCosts(brief,saved),areaEvidence(assessment),offerCoverage(brief,assessment),actions);
  $("offer-results").hidden = false;
}
