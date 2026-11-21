"use strict";

function externalLink(label, address) {
  if (!address || !/^https?:\/\//i.test(address)) return null;
  const link = text("a", label);
  link.href = address;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function decisionItem(row) {
  const item = document.createElement("li");
  item.append(text("h5", row.title));
  if (row.illustrative) item.append(text("span", "Illustrative scenario", "badge neutral"));
  if (row.detail) item.append(text("p", row.detail));
  if (row.action) item.append(text("p", row.action, "item-action"));
  if (Number.isFinite(row.distance_m)) item.append(text("p", `${Math.round(row.distance_m).toLocaleString("en-AU")} m from address point`, "muted"));
  if (row.references?.length || row.as_of || row.changes_outcome) {
    const provenance = document.createElement("details");
    provenance.append(text("summary", "Evidence and what would change this"));
    if (row.changes_outcome) provenance.append(text("p", row.changes_outcome));
    if (row.as_of) provenance.append(text("p", `As of ${row.as_of}`));
    if (row.references?.length) {
      const refs = document.createElement("ul");
      for (const ref of row.references) {
        const entry = document.createElement("li");
        entry.append(externalLink(ref, ref) || document.createTextNode(ref));
        refs.append(entry);
      }
      provenance.append(refs);
    }
    item.append(provenance);
  }
  return item;
}

function decisionGroup(heading, rows, empty) {
  const section = text("section", "", "decision-group");
  section.append(text("h4", heading));
  if (!rows?.length) {
    section.append(text("p", empty, "muted"));
    return section;
  }
  const list = document.createElement("ol");
  rows.slice(0, 3).forEach(row => list.append(decisionItem(row)));
  section.append(list);
  if (rows.length > 3) {
    const more = document.createElement("details");
    more.append(text("summary", `Show ${rows.length - 3} more`));
    const remaining = document.createElement("ol");
    remaining.start = 4;
    rows.slice(3).forEach(row => remaining.append(decisionItem(row)));
    more.append(remaining);
    section.append(more);
  }
  return section;
}

function renderPurchaseDecision(assessment) {
  const decision = assessment?.purchase_decision;
  $("purchase-decision").dataset.state = decision?.state || "unscored";
  const actions = $("decision-action");
  const groups = $("decision-lists");
  actions.replaceChildren();
  groups.replaceChildren();
  $("decision-reassess").hidden = Boolean(decision);
  if (!decision) {
    $("decision-title").textContent = assessment ? "This assessment predates the purchase decision" : "This case has no saved assessment";
    $("decision-summary").textContent = assessment
      ? "Reassess this case to record a purchase decision against its evidence and buyer inputs."
      : "Run the first assessment to see the material issues and checks for this purchase.";
    $("decision-basis").textContent = assessment ? `Earlier assessment as of ${assessment.as_of}.` : "";
    $("decision-reassess").textContent = assessment ? "Reassess case" : "Run first assessment";
    return;
  }
  $("decision-title").textContent = decision.headline;
  $("decision-summary").textContent = decision.summary;
  const basis = [`Saved for case version ${state.case.case_version} as of ${decision.as_of}. Decision rules ${decision.rule_version}.`];
  if (decision.rule_version === "1.0.0" && decision.drivers?.some(row => row.rule_id === "LG01" && row.priority === 3)) {
    basis.push("This earlier rule version quotes the source review. A conveyancer must verify its effect on the unit against the title and the relevant instrument.");
    $("decision-reassess").textContent = "Reassess case";
    $("decision-reassess").hidden = false;
  }
  if (decision.illustrative_finance) basis.push("Buyer amounts and purchase terms are illustrative.");
  $("decision-basis").textContent = basis.join(" ");
  if (decision.next_action) actions.append(text("h4", "Next action"), text("p", decision.next_action));
  const open = decision.open_checks || [];
  const nearby = row => row.reasons?.includes("NEARBY_APPLICATION");
  groups.append(
    decisionGroup("Material issues", decision.drivers, "No supported material issue was identified in the assessed evidence."),
    decisionGroup("Checks before committing", open.filter(row => !nearby(row)), "No additional check was listed for this decision.")
  );
  const applications = open.filter(nearby);
  if (applications.length) {
    const planning = decisionGroup("Nearby applications to check", applications);
    planning.classList.add("decision-planning");
    groups.append(planning);
  }
  if (decision.context_notes?.length) {
    const context = document.createElement("details");
    context.className = "decision-context";
    context.append(text("summary", "Context considered in the decision"));
    const list = document.createElement("ul");
    decision.context_notes.forEach(row => list.append(decisionItem(row)));
    context.append(list);
    groups.append(context);
  }
}

$("decision-reassess").addEventListener("click", () => $("assess").click());

function signalCard(row, group) {
  const article = document.createElement("article");
  if (row.status) article.append(text("span", row.status.replaceAll("_", " "), "badge"));
  article.append(text("h5", row.title), text("p", row.detail));
  const info = [];
  if (Number.isFinite(row.distance_m)) info.push(`${Math.round(row.distance_m).toLocaleString("en-AU")} m from address point`);
  if (row.as_of) info.push(`${group === "finance" ? "Case date" : "Evidence date"} ${String(row.as_of).slice(0, 10)}`);
  if (row.attribution) info.push(row.attribution);
  if (info.length) article.append(text("p", info.join(" · "), "muted"));
  const source = externalLink("View source", row.source_url);
  if (source) article.append(source);
  const licence = externalLink("Licence", row.licence_url);
  if (licence) article.append(document.createTextNode(" · "), licence);
  if (row.distance_method || row.geometry_source_url || row.coverage) {
    const evidence = document.createElement("details");
    evidence.append(text("summary", "Coverage and measurement"));
    if (row.coverage) evidence.append(text("p", row.coverage));
    if (row.distance_method) evidence.append(text("p", row.distance_method));
    const geometry = externalLink("Mapped location source", row.geometry_source_url);
    if (geometry) evidence.append(geometry);
    article.append(evidence);
  }
  return article;
}

async function loadBuyerContext(purchaseCase, assessment) {
  const signals = $("buyer-signals");
  showFinanceInputs(purchaseCase);
  $("buyer-location").replaceChildren();
  $("buyer-scope").textContent = "Loading the buyer brief…";
  signals.replaceChildren();
  const params = new URLSearchParams({version: purchaseCase.case_version});
  if (assessment) params.set("assessment_id", assessment.assessment_id);
  try {
    const brief = assessment?.decision_evidence || await api(`/v1/cases/${encodeURIComponent(purchaseCase.case_id)}/buyer-context?${params}`);
    if (state.case !== purchaseCase || state.assessment !== assessment) return;
    const point = brief.location;
    const where = [point.label, point.basis];
    if (Number.isFinite(point.latitude) && Number.isFinite(point.longitude))
      where.push(`${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`);
    if (point.source_date) where.push(`Address record ${point.source_date}`);
    $("buyer-location").append(document.createTextNode(where.join(" · ")));
    const source = externalLink("ACT address register", point.source_url);
    if (source) $("buyer-location").append(document.createTextNode(" · "), source);
    const boundary = externalLink("ACT suburb boundaries", point.division_source_url);
    if (boundary) {
      boundary.title = point.division_attribution;
      $("buyer-location").append(document.createTextNode(" · "), boundary);
    }
    $("buyer-scope").textContent = `Case version ${brief.case_version}, as of ${brief.as_of.slice(0, 10)}. ${assessment?.decision_evidence ? "These source extracts and buyer scenarios were saved with this purchase decision." : "Current source extracts are shown for reference. This view has no saved purchase decision."} ${brief.illustrative_finance ? "The buyer amounts and purchase terms are illustrative." : "The financial scenarios use the inputs saved for this case."}`;
    const groups = [["planning", "Nearby planning"], ["spatial", "Land use at this point"],
                    ["crime", "Reported crime in the suburb"], ["finance", "Buyer finances"]];
    for (const [key, heading] of groups) {
      const section = text("section", "", "signal-group");
      section.dataset.group = key;
      section.append(text("h4", heading));
      const rows = brief[key] || [];
      if (!rows.length) section.append(text("p", "No source result is available for this case.", "muted"));
      rows.forEach(row => section.append(signalCard(row, key)));
      signals.append(section);
    }
  } catch (error) {
    if (state.case === purchaseCase && state.assessment === assessment)
      $("buyer-scope").textContent = `Buyer brief unavailable. ${error.message}`;
  }
}

const financeFields = [
  ["purchase_price","Purchase price (A$)"], ["principal","Loan principal (A$)"],
  ["annual_rate_decimal","Annual interest rate (decimal, e.g. 0.06 for 6%)"], ["term_months","Loan term (months)"],
  ["income_monthly","Monthly household income (A$)"], ["living_monthly","Monthly living expenses (A$)"],
  ["other_debt_monthly","Monthly payments on other debt (A$)"], ["property_costs_monthly","Monthly property costs (A$)"],
  ["cash_after_settlement","Cash remaining after settlement (A$)"], ["protected_reserve","Cash reserve to protect (A$)"],
  ["loan_funds","Loan funds at settlement (A$)"], ["cash_allocated","Cash committed to purchase (A$)"],
  ["acquisition_costs","Acquisition costs (A$)"], ["immediate_works","Immediate works (A$)"]
];

function showFinanceInputs(purchaseCase) {
  $("buyer-finance-editor").open = false;
  $("buyer-finance-editor").hidden = document.documentElement.dataset.access === "preview";
  $("funding-confirmed").checked = purchaseCase.finance?.funding_confirmed === true;
  const fields = $("finance-fields");
  fields.replaceChildren();
  for (const [key, name] of financeFields) {
    const label = text("label", name);
    const input = document.createElement("input");
    input.name = key;
    input.type = "number";
    input.step = key === "term_months" ? "1" : "any";
    input.min = key === "term_months" ? "1" : "0";
    input.value = purchaseCase.finance?.[key] ?? "";
    label.append(input);
    fields.append(label);
  }
}

$("finance-entry").addEventListener("submit", event => {
  event.preventDefault();
  const inputs = new FormData(event.currentTarget);
  const original = state.case;
  task(event.submitter, async () => {
    if (!original) throw Error("Select a purchase case first.");
    const savedFinance = {...original.finance, funding_confirmed: inputs.has("funding_confirmed")};
    inputs.delete("funding_confirmed");
    for (const [key, value] of inputs) {
      if (String(savedFinance[key] ?? "") === value) continue;
      savedFinance[key] = value === "" ? null : key === "term_months" ? Number(value) : value;
    }
    const now = new Date().toISOString();
    const updated = {...original, finance: {...savedFinance, received_at: now}, as_of: now};
    const saved = await post(`/v1/cases?expected_version=${original.case_version}`, updated);
    await openLocation(saved, true);
    message(`Saved buyer inputs and assessed case version ${saved.case_version}.`);
  });
});

async function openLocation(purchaseCase, existing = false) {
  if (!existing) await post("/v1/cases?expected_version=0", purchaseCase);
  await post(`/v1/cases/${encodeURIComponent(purchaseCase.case_id)}/assessments`, {});
  await loadCases(purchaseCase.case_id);
  $("location-tools").open = false;
  showTab("assessment");
  $("assessment-title").scrollIntoView({block:"start"});
}

function blankAddressCase(location) {
  const purchaseCase = newCase();
  purchaseCase.property_id = location.address_id ? `act-address-${location.address_id}` : `point-${crypto.randomUUID()}`;
  purchaseCase.property = {jurisdiction: "ACT", identity_confirmed: false, ...location};
  // A location search supplies no buyer loan terms.
  purchaseCase.finance = document.documentElement.dataset.access === "preview" ? {} : {...purchaseCase.finance,term_months:null};
  return purchaseCase;
}

$("address-search").addEventListener("submit", event => {
  event.preventDefault();
  const values = new FormData(event.currentTarget);
  const output = $("address-matches");
  output.replaceChildren();
  $("address-feedback").textContent = "Searching the ACT Government address register…";
  task(event.submitter, async () => {
    try {
      const result = await api(`/v1/locations/search?${new URLSearchParams(values)}`);
      $("address-feedback").textContent = result.matches.length
        ? `Select the matching address to create its purchase case.${result.truncated ? " Showing the first 20 matches. Add a unit number to narrow the search." : ""}`
        : "No assigned address matched. Check the unit, street name and suburb, or enter a known address point.";
      for (const point of result.matches) {
        const button = text("button", point.label, "secondary");
        button.type = "button";
        button.addEventListener("click", () => task(button, () => openLocation(blankAddressCase(point))));
        output.append(button);
      }
    } catch (error) {
      $("address-feedback").textContent = error.message;
    }
  });
});

$("manual-address").addEventListener("submit", event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  values.latitude = Number(values.latitude);
  values.longitude = Number(values.longitude);
  task(event.submitter, () => openLocation(blankAddressCase(values)));
});

$("kingston-example").addEventListener("click", event => task(event.currentTarget, async () => {
  if (document.documentElement.dataset.access === "preview" &&
      Array.from($("case-select").options).some(option => option.value === kingstonPreview)) {
    await loadCases(kingstonPreview);
    $("location-tools").open = false;
    showTab("assessment");
    return;
  }
  const example = await api("/v1/locations/kingston-example");
  const existing = (await api("/v1/cases")).cases.find(c => c.case_id === example.case_id);
  if (existing && (existing.property_id !== example.property_id || existing.finance_is_illustrative !== true))
    throw Error("The Kingston example identifier is already used by a different case.");
  await openLocation(existing || example, Boolean(existing));
}));
