#!/usr/bin/env python3
"""Regenerate the exhaustive catalogue register and documentary JSON schemas.

Reads configuration only. Does not activate, fetch, licence or alter a source.
The mode notes are maintained against the implemented engine, not inferred from
the aspirational phase labels or an uploaded catalogue's operational claims.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

# Actual implementation for each signal. "Unavailable" means the named native
# analysis is absent; generic supplied context is explicitly not that analysis.
MODES = {
 "S001":("Reviewed structured", "Explicit case property confirmation and exact observation identity gates. No national candidate-search or automatic address reconciliation service."),
 "S002":("Reviewed structured", "Reviewed ownership/dwelling facts; no automated interpretation of title instruments."),
 "S003":("Reviewed structured", "Footprint attribution must be supplied and reviewed; no building extraction from aerial imagery."),
 "S004":("Reviewed structured", "Reviewed boundary/survey concordance; geometry validity and metric-CRS gates are available, but legal plan interpretation is external."),
 "S005":("Numerical", "Polygon overlay, positive area, touch, uncertainty and independent coverage gates. No water depth or loss model."),
 "S006":("Numerical", "Boundary sensitivity using supplied combined positional uncertainty in metres; accuracy is not inferred from the geometry."),
 "S007":("Reviewed structured", "A validated depth report/measure can be supplied as reviewed fact or context. No raster hydraulic model or colour-to-depth conversion."),
 "S008":("Reviewed structured", "Reviewed inspection findings and their scope; no automatic drainage diagnosis."),
 "S009":("Context", "Externally derived terrain context can be recorded. DEM acquisition, slope and low-point extraction are not implemented."),
 "S010":("Numerical", "Subtract supplied floor/flood heights only for matching declared vertical datum and metre units. No datum conversion or level survey."),
 "S011":("Numerical", "Designation polygon overlay with current covered evidence and uncertainty handling. No site BAL or fire probability model."),
 "S012":("Reviewed structured", "Reviewed site fire-resilience facts; area designation cannot substitute for site assessment."),
 "S013":("Reviewed structured", "Reviewed geotechnical/inspection facts, not a diagnosis from imagery or soil proxies."),
 "S014":("Reviewed structured", "Reviewed contamination/restriction evidence; no automatic parcel-history remediation interpretation."),
 "S015":("Reviewed structured", "Reviewed asbestos history or inspection evidence; no automated address-history reconciliation or laboratory inference."),
 "S016":("Context", "Externally sourced climate scenario context; no downscaled climate, ensemble or building-loss simulation."),
 "S017":("Reviewed structured", "Reviewed restrictions compared with a named declared requirement; legal interpretation remains supplied expert evidence."),
 "S018":("Reviewed structured", "Reviewed instrument/access conflicts; easement geometry is not invented."),
 "S019":("Reviewed structured", "Reviewed zoning/control compatibility. Automatic statutory text interpretation is not implemented."),
 "S020":("Reviewed structured", "Reviewed approval-versus-built-form discrepancy; no visual building-plan comparison model."),
 "S021":("Reviewed structured", "Reviewed material structural findings; optional repair amounts need reviewed source references."),
 "S022":("Reviewed structured", "Reviewed moisture/roof/waterproofing findings; no automated cause diagnosis."),
 "S023":("Reviewed structured", "Reviewed current pest findings and inspection scope; prior treatment is not a computed clearance."),
 "S024":("Reviewed structured", "Reviewed repair/maintenance evidence and referenced costs; no automatic bill-of-quantities or duplicate-work estimator."),
 "S025":("Reviewed structured", "Reviewed quote exclusions and named essential-cover conflicts; no live insurer quotation or market-wide insurability inference."),
 "S026":("Reviewed structured", "Supplied comparable quote reviews or scoped numeric context; no automatic cover/excess harmonisation."),
 "S027":("Reviewed structured", "Reviewed rebuild-cover adequacy; no quantity-surveyor replacement-cost model."),
 "S028":("Reviewed structured", "Reviewed common-property defect/liability facts; private scope and formal ownership applicability remain explicit."),
 "S029":("Reviewed structured", "Reviewed document completeness and known liability amounts. No automatic full strata financial-statement interpretation."),
 "S030":("Reviewed structured", "Canonical project IDs and independent milestone records can be supplied. Nearby relevance and project alias resolution are external."),
 "S031":("Numerical", "Deterministic comparison of supplied measured impact with an explicit threshold; potential impacts can be reviewed facts. No automatic 3D sunlight or privacy model."),
 "S032":("Reviewed structured", "Reviewed proposed/effective instrument facts with knowledge/effectivity gates; no automatic legal commencement interpretation."),
 "S033":("Numerical", "Canonical comparable project quantities and lifecycle filtering. Strategic growth boundaries, horizons and comparability must be supplied."),
 "S034":("Reviewed structured", "Independent known project milestones, explicit supersession, timing conflicts and cancellation evidence. No delivery probability model."),
 "S035":("Reviewed structured", "Supported, timing-qualified benefit attestation with dependencies and availability date. No built-in transport routing or property price uplift."),
 "S036":("Context", "Scoped construction/operating-impact evidence can be recorded; no automatic noise, access or disruption simulation."),
 "S037":("Numerical", "Deduplicate canonical project quantity, sum signed comparable net changes, exclude cancelled/completed future supply and compare a declared threshold."),
 "S038":("Context", "Reviewed/structured approvals context only. Stock-normalised intensity is not implemented; a generic project total is rejected as a substitute."),
 "S039":("Context", "Reviewed/structured conversion or delay context only. Time-series conversion analysis is not implemented; a generic project total is rejected."),
 "S040":("Context", "Reviewed/structured scarcity context only. Structural scarcity/substitute-market analysis is not implemented; a generic project total is rejected."),
 "S041":("Context", "Comparable externally prepared population/migration measures and definitions; no automated boundary/time-series reconciliation."),
 "S042":("Unavailable", "No native household-formation scenario calculator. A supplied reviewed analysis can be carried as labelled external context, not claimed as a calculated model."),
 "S043":("Context", "Employment/unemployment context with explicit definitions; no automatic industry-concentration or local resilience model."),
 "S044":("Reviewed structured", "Reviewed comparable-sale evidence quality; no licensed sales ingestion entitlement or automated comparable selection."),
 "S045":("Unavailable", "No native valuation or purchase-price comparison model. External professional evidence may be recorded as reviewed/context evidence."),
 "S046":("Context", "Supplied turnover/exit evidence and scope; no automatic listing-history or time-on-market reconstruction."),
 "S047":("Reviewed structured", "Property rent evidence must be supplied/reviewed. Finance can calculate net rent only after gross rent and deductions are explicit."),
 "S048":("Numerical", "Area count/denominator rate and declared threshold with period/definition/comparability gates. No automatic multiyear crime trend or household crime probability."),
 "S049":("Reviewed structured", "Reviewed address/year eligibility; no automated catchment routing or school-quality inference."),
 "S050":("Unavailable", "GTFS acquisition/parsing is separate; the engine has no native scheduled journey planner, walking network or reliability model. External context can be supplied."),
 "S051":("Context", "Reviewed/scoped crash or route context; no automated route-exposure accident probability."),
 "S052":("Reviewed structured", "Reviewed assessment validity and scope; no building energy simulation or automatic EER method verification."),
 "S053":("Context", "Supplied canopy/shade measures with vintage and definitions; no property solar-shade simulation or canopy extraction."),
 "S054":("Reviewed structured", "Reviewed measured/self-reported noise or air evidence; no sensor-network model or spatial interpolation."),
 "S055":("Context", "Macro-rate context is separate from the supplied contractual borrowing rate. No automatic cash-rate-to-mortgage pass-through forecast."),
 "S056":("Numerical", "Decimal P&I repayment and complete baseline monthly budget. Missing income leaves repayment visible but affordability unassessed."),
 "S057":("Numerical", "Separate finite-duration rate stress with reset balances/remaining terms and each monthly cash/reserve position."),
 "S058":("Numerical", "Income stress plus protected reserve and optional essential-outgoings buffer. Each scenario stays separate."),
 "S059":("Numerical", "Uses explicitly supplied recurring property costs in the complete monthly budget. Does not discover all liabilities or automatically deduplicate quoted work items."),
 "S060":("Numerical", "Conditional exit sale proceeds after actual modelled remaining principal, supplied selling costs and explicit tax treatment. No sale-price forecast or total-return model."),
 "S061":("Reviewed structured", "Every observation has an enforced current/source-date gate. Source-specific currency is an upstream attestation; no automatic universal age threshold. This standalone check needs scoped quality evidence."),
 "S062":("Reviewed structured", "Global quality, coverage, rights and conflict gates are implemented; a standalone scope-review check still needs evidence covering its declared audit scope."),
 "S063":("Unavailable", "No native assessment-diff/change-classification workflow. New inputs get a new hash; external reviewed change context can be supplied."),
 "S064":("Reviewed structured", "Captures declared essential/nonessential requirement IDs and gates conflict rules; the engine does not infer personal preferences."),
 "S065":("Numerical", "Separate day-one required versus confirmed allocated funding; explicit reserve reconciliation when total liquid cash is supplied.")
}


def read_config(name):
    raw=(ROOT/"config"/name).read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def plain(value):
    if value is None:return "Not recorded"
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)


def cell(value):
    return plain(value).replace("|","\\|").replace("\n","; ")


def bullets(values):
    return "; ".join(plain(v) for v in values) or "None recorded"


def field(lines,label,value):
    text=plain(value).replace("\n","; ")
    lines.append(f"- **{label}:** {text}")


def generate_register():
    source_config,source_hash=read_config("sources.json")
    check_config,check_hash=read_config("checks.json")
    signal_config,signal_hash=read_config("signals.json")
    schema_claims,claims_hash=read_config("input_schema_claims.json")
    sources=sorted(source_config["sources"],key=lambda r:r["source_id"])
    families=sorted(source_config["baseline_source_families"]["sources"],key=lambda r:r["source_id"])
    checks=sorted(check_config["checks"],key=lambda r:r["check_id"])
    signals={s["signal_id"]:s for s in signal_config["signals"]}
    fields=defaultdict(set)
    for row in schema_claims.get("rows",[]):
        if row.get("Dataset ID") and row.get("Field Name"):
            fields[str(row["Dataset ID"])].add(str(row["Field Name"]))
    enabled=[s["source_id"] for s in sources if s.get("enabled") is True]
    mode_counts=Counter(MODES.get(c["check_id"],("Unavailable","No reviewed implementation mapping"))[0] for c in checks)
    aliases=source_config.get("resolved_alias_relations",[])
    lines=["# Complete input and processing register", "",
        "This is the exhaustive inventory of what the prototype knows about its inputs, what must be supplied for each check, and what the current engine actually calculates.", "",
        f"It contains **{len(sources)} retained registry labels, {len(families)} baseline source families and {len(checks)} required checks**. These counts describe catalogue records and questions, **not independent active data feeds**. A source family can bundle several datasets; one underlying asset can have several labels, interfaces or copied records. A catalogue's `PULLED_AND_LIVE` claim is not proof that this build has activated it or validated a particular parcel.", "",
        f"At this generated configuration snapshot, **{len(enabled)} registry source(s) are enabled for collection**: {bullets(enabled)}. Enabled means the local collector is permitted to attempt the configured source; it does not mean a continuously running service or a complete property assessment. The current configuration is authoritative if this generated file is older.", "",
        "## How to read the register", "",
        "1. The **83-label inventory** lists connector-facing IDs, exact configured routes, acquisition modes, declared rights and catalogue provenance.",
        "2. The **40-family inventory** lists the original research families used by the check manifest (H01–H40), their access/coverage limits and native refresh policies. These family codes are not automatically runnable connector IDs.",
        "3. The **65-check register** gives every raw input, source-family reference, intended processing, current execution mode, missing-evidence rule and output scope.",
        "4. `schemas/case.schema.json` and `schemas/observation.schema.json` document normalised engine input shapes. They are not automatically enforced by the HTTP service; the engine and storage code enforce their own gates. Use a JSON Schema validator explicitly if you want this extra validation. The private HTTP upload template omits server-derived tenant/case/receipt fields; validate its stored, scope-bound envelope against the observation schema, not the unbound upload body.", "",
        "The source registry has no inferred licence entitlement. Historical catalogue assertions remain visible as assertions. Exact alias relations are recorded below; unresolved overlap still needs review. H-family references and registry IDs must be mapped deliberately during jurisdiction onboarding, not joined merely because names look similar.", "",
        "## Actual execution modes", "",
        "| Mode | Check count | Meaning |", "|---|---:|---|",
        f"| Numerical | {mode_counts['Numerical']} | A deterministic arithmetic, geometric or threshold operation exists for the specified inputs. This does not mean those inputs are collected automatically. |",
        f"| Reviewed structured | {mode_counts['Reviewed structured']} | A human-reviewed fact, scope, document or case assertion is the input. Rules classify the supplied facts; they do not perform the professional inspection or legal interpretation. |",
        f"| Context | {mode_counts['Context']} | Scoped source context can be shown, with defined measures and optional declared thresholds. No native model of the intended outcome is claimed. |",
        f"| Unavailable | {mode_counts['Unavailable']} | The named native analysis is absent. External reviewed/context evidence can still be recorded where supported, with its external method visible. Missing evidence remains NOT_ASSESSED. |", "",
        "S038–S040 are intentionally context-only: a project count cannot stand in for stock-normalised approvals intensity, construction conversion or structural scarcity. Generic project payloads for those signals are rejected. Source collection, raw parsing, observation normalisation and check calculation are distinct capabilities.", "",
        "## Configuration provenance", "",
        "This document is reproducibly generated by `python scripts/generate_input_register.py`; it performs no network access and activates no sources. The exact input file digests are:", "",
        f"- sources.json: `{source_hash}`",
        f"- checks.json: `{check_hash}`",
        f"- signals.json: `{signal_hash}`",
        f"- input_schema_claims.json: `{claims_hash}`", "",
        "## Reviewed alias relations", ""]
    if aliases:
        for a in aliases:
            lines += [f"- `{a.get('source_id')}` → `{a.get('alias_of')}`: {a.get('reason','Explicit reviewed alias')}. Evidence: {a.get('evidence_url','Not recorded')}."]
    else:lines.append("No explicit alias relationships are recorded; that does not prove all sources are independent.")
    lines += ["",source_config.get("unresolved_overlap_note","Unresolved semantic overlap must be reviewed."),"",
              "## A. All retained registry labels", "",
              "The Enabled column is the actual configuration flag. The catalogue access status is preserved separately and may be an unverified historical claim. A `manual` adapter requires authorised input; `discovery` yields metadata, not a parcel finding. Other adapter names identify implemented parser families, not proof that a particular configured endpoint is usable.","",
              "| Registry ID | Title | Adapter | Enabled | Canonical target |", "|---|---|---|---|---|"]
    for s in sources:
        lines.append(f"| {cell(s['source_id'])} | {cell(s.get('title'))} | {cell(s.get('adapter'))} | {'Yes' if s.get('enabled') else 'No'} | {cell(s.get('canonical_source_id',s['source_id']))} |")
    for s in sources:
        claims=s.get("source_claims",[])
        record_ids={s["source_id"]}|{str(c.get("source_record_id")) for c in claims if c.get("source_record_id")}
        observed=sorted(set().union(*(fields.get(i,set()) for i in record_ids)))
        lines += ["",f"### {s['source_id']} — {s.get('title','Untitled')}",""]
        for label,value in [
            ("Configured route",s.get("endpoint")),("Jurisdiction and category",f"{s.get('jurisdiction','Unknown')}; {s.get('category','Unknown')}"),
            ("Collector adapter",s.get("adapter")),("Actually enabled",bool(s.get("enabled"))),
            ("Canonical target",s.get("canonical_source_id",s["source_id"])),
            ("Catalogue access-status claim",s.get("access_status")),("Registry licence status",s.get("licence_status")),
            ("Current permission flags",s.get("rights",{})),("Refresh policy",s.get("refresh_policy")),
            ("Configured query/parser parameters",s.get("parameters",{})),("Collection bounds",s.get("limits",{})),
            ("Retained aliases",bullets(s.get("source_aliases",[]))),
            ("Claimed source field names",bullets(observed) if observed else "No observed-field catalogue attached; verify the real response schema before mapping observations"),
            ("Readiness and use limits",s.get("readiness_note"))]:field(lines,label,value)
        for claim in claims:
            record=claim.get("record",{})
            line=f"{claim.get('catalogue','Unknown catalogue')} / {claim.get('source_record_id','Unknown record')}; {claim.get('source_file','No file')}; provenance={claim.get('provenance_status','Not recorded')}; current review={claim.get('current_review_evidence_status','Not recorded')}"
            field(lines,"Catalogue provenance",line)
            for key in ("Publisher / Custodian","Publisher","Access Protocol","Auth / Query Pattern","Geometry / Format","Licence","Required Attribution","Notes & Caveats"):
                if record.get(key) is not None:field(lines,f"Recorded claim — {key}",record[key])
        if s.get("activation_review"):field(lines,"Recorded activation review",s["activation_review"])
        if s.get("licence_review"):field(lines,"Recorded licence review",s["licence_review"])
    lines += ["","## B. All baseline source families", "",
              source_config["baseline_source_families"].get("note",""), "",
              "These research records describe sources and fallback routes. Their original `tested_status` and `verified_on` fields are research provenance, not a guarantee that the runtime has just fetched the data. BUYER and INSPECTOR references in the check register mean authorised private input, not an API.","",
              "| Family | Name | Input family | Used by checks |", "|---|---|---|---|"]
    for f in families:
        used=[c["check_id"] for c in checks if f["source_id"] in c.get("source_ids",[])]
        lines.append(f"| {cell(f['source_id'])} | {cell(f.get('name'))} | {cell(f.get('input_family'))} | {cell(', '.join(used))} |")
    for f in families:
        used=[c["check_id"] for c in checks if f["source_id"] in c.get("source_ids",[])]
        lines += ["",f"### {f['source_id']} — {f.get('name','Unnamed family')}",""]
        for label,key in [("Publisher","publisher"),("Input family","input_family"),("Geographic and measurement scope","geography_resolution"),
                          ("Access route","access_route"),("Exact documented routes","endpoint_or_official_url"),("Official source","official_url"),
                          ("Original research status","tested_status"),("Limits","exact_limits"),("Native publication cadence","freshness"),
                          ("Refresh policy","refresh_policy"),("Authentication and cost","auth_cost"),("Licence and retention","licence_retention"),
                          ("Fallback","fallback"),("Research verification date","verified_on")]:field(lines,label,f.get(key))
        field(lines,"Referenced by checks",bullets(used))
    lines += ["","## C. All required checks and processing", "",
              "The intended processing below comes from the supplied architecture register. The actual mode and implementation scope are a separate implementation review; a V0/V1 phase label is not evidence that a feature has been built. Inputs marked unknown must remain null/missing, not be guessed as zero. All checks also require appropriate identity, knowledge dates, coverage, rights, source references and conflict resolution.","",
              "| Check | Name | Actual mode | Critical | Scope |", "|---|---|---|---|---|"]
    for c in checks:
        mode,_=MODES.get(c["check_id"],("Unavailable","No reviewed implementation mapping"))
        lines.append(f"| {c['check_id']} | {cell(c['label'])} | {mode} | {'Yes' if c.get('critical') else 'No'} | {'Public screen' if c.get('public_check') else 'Private / buyer'} |")
    for c in checks:
        s=signals.get(c["check_id"],{})
        mode,note=MODES.get(c["check_id"],("Unavailable","No reviewed implementation mapping"))
        lines += ["",f"### {c['check_id']} — {c['label']}",""]
        for label,value in [
            ("Domain",c.get("domain")),("Required / critical / public",f"{c.get('required')} / {c.get('critical')} / {c.get('public_check')}"),
            ("Raw inputs needed",bullets(c.get("raw_inputs",s.get("raw_inputs",[])))),
            ("Source-family and private-input references",bullets(c.get("source_ids",s.get("source_ids",[])))),
            ("Grain and units",s.get("grain_units")),("Intended processing",c.get("processing_specification",s.get("processing"))),
            ("Actual implemented mode",mode),("Actual implementation scope",note),
            ("Intended evidence output",s.get("output")),("Rule links",bullets(c.get("rule_ids",[]))),
            ("Missing-evidence handling",c.get("missing_evidence_handling",s.get("missing_evidence_handling"))),
            ("Original planning phase",c.get("phase",s.get("phase")))]:field(lines,label,value)
    lines += ["","## D. Loading and validation boundaries", "",
        "1. Choose the correct registry source record or authorised private document. Review its identity, coverage, query limits, rights, publication period and units.",
        "2. Collect immutable raw snapshots with the source adapter. Collection results are not observations until their meaning and coverage have been validated.",
        "3. Map actual source fields into one of the documented observation payloads. Preserve source/snapshot IDs, dates, evidence basis, scope and reviewer attestations. A raw field catalogue is not an executable mapping.",
        "4. Supply buyer finance and requirements in a tenant-scoped case. Validate using the documentary schemas if desired; semantic gates remain the engine's responsibility.",
        "5. Run the engine against the full check manifest. Inspect known findings, gaps, opportunities, complete monthly schedules and independent confidence. Do not average them into a fictional probability.",
        "6. Close gaps with newly reviewed evidence and rerun. Existing immutable assessments remain tied to their original inputs. A waiver records a decision without making missing evidence assessed.","",
        "The implementation intentionally distinguishes configured labels, enabled acquisition, parsed raw records, normalised evidence, supported calculations and completed buyer checks. None of those counts can substitute for another.",""]
    target=ROOT/"docs"/"COMPLETE_INPUT_REGISTER.md"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("\n".join(lines),encoding="utf-8")
    return {"registry_labels":len(sources),"baseline_families":len(families),"checks":len(checks),
            "enabled_registry_sources":enabled,"actual_modes":dict(sorted(mode_counts.items()))}


def decimal(nullable=True):
    value={"anyOf":[{"type":"string","pattern":r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"},{"type":"number"}]}
    if nullable:value["anyOf"].append({"type":"null"})
    value["description"]="Finite decimal value; decimal strings preserve intended precision. Non-negativity and specialised bounds are checked by the engine."
    return value


def date(nullable=False):
    value={"anyOf":[{"type":"string","format":"date"},{"type":"string","format":"date-time"}],
           "description":"ISO date, or timezone-aware timestamp. A date is midnight UTC. Enable format checking in a client validator."}
    if nullable:value["anyOf"].append({"type":"null"})
    return value


def text(nullable=False):
    return {"type":["string","null"] if nullable else "string","minLength":1}


def boolean(nullable=False):
    return {"type":["boolean","null"] if nullable else "boolean"}


def obj(properties,required=(),description=None):
    result={"type":"object","properties":properties,"additionalProperties":True}
    if required:result["required"]=list(required)
    if description:result["description"]=description
    return result


def array(items):return {"type":"array","items":items}


def geometry_schema(empty=False):
    types=["Polygon","MultiPolygon"]+(["GeometryCollection"] if empty else [])
    result=obj({"type":{"enum":types},"coordinates":{"type":"array"},"geometries":{"type":"array","maxItems":0}},["type"],
               "GeoJSON polygon geometry. GeometryCollection is permitted only as an explicitly empty hazard extent. Topology, finite coordinates and CRS are checked by the engine.")
    result["allOf"]=[{"if":{"properties":{"type":{"enum":["Polygon","MultiPolygon"]}}},"then":{"required":["coordinates"]}},
                     {"if":{"properties":{"type":{"const":"GeometryCollection"}}},"then":{"required":["geometries"]}}]
    return result


def base_schema(title,identifier,description):
    return {"$schema":"https://json-schema.org/draft/2020-12/schema","$id":identifier,"title":title,
            "description":description,"$comment":"Documentation and optional client validation only. These files are not automatically applied by the HTTP service. Engine/storage validation and semantic eligibility gates remain authoritative."}


def make_case_schema():
    reset=obj({"start_month":{"type":"integer","minimum":1,"maximum":1200},"annual_rate_decimal":decimal(False)},["start_month","annual_rate_decimal"])
    exit_=obj({"sale_month":{"type":"integer","minimum":0,"maximum":1200},"sale_price":decimal(),"selling_costs":decimal(),
               "tax_treatment":{"enum":["before_personal_tax","explicit_tax"]},"tax_costs":decimal()},description="Conditional sale proceeds, not a sale-price forecast. Incomplete inputs remain unassessed.")
    finance={name:decimal() for name in ["principal","annual_rate_decimal","annual_rate","income_monthly","living_monthly","other_debt_monthly",
        "property_costs_monthly","property_costs_annual","cash_after_settlement","protected_reserve","purchase_price","loan_funds","cash_allocated",
        "acquisition_costs","immediate_works","total_liquid_cash","gross_rent_monthly","vacancy_fraction","management_fraction","minimum_buffer_months","revert_rate","offset_balance"]}
    finance.update({"term_months":{"type":["integer","null"],"minimum":1,"maximum":1200},"rate_unit":{"enum":["decimal","percent","per_cent","%",None]},
        "repayment_type":{"type":"string","description":"Only principal_and_interest is implemented. Other declared structures produce NOT_ASSESSED."},
        "intended_use":{"type":"string"},"funding_confirmed":boolean(),"property_costs_include_management":boolean(),"rent_is_net":boolean(),
        "rate_schedule":array(reset),"fixed_expiry_months":{"type":["integer","null"],"minimum":0,"maximum":1200},
        "no_drawdown_requirement_id":text(True),"buffer_requirement_id":text(True),"received_at":date(True),"exit":exit_,
        "loan_splits":{"type":"array","description":"Not implemented; a non-empty value causes the loan calculation to be unassessed."}})
    requirement=obj({"requirement_id":text(),"essential":boolean(),"description":{"type":"string"}},["requirement_id","essential"])
    scenario=obj({"scenario_id":text(),"duration_months":{"type":"integer","minimum":1,"maximum":1200},
        "rate_delta_bps":decimal(False),"income_factor":decimal(False),"property_cost_factor":decimal(False),"rent_factor":decimal(False),
        "minimum_monthly_surplus":decimal(),"required_review":boolean(),"requirement_id":text(True),
        "start_month":{"type":"integer","minimum":0,"description":"Only zero is implemented. To model later stress, restate the cash and loan starting position."}},["scenario_id","duration_months"])
    property_=obj({"label":{"type":"string"},"jurisdiction":text(True),"property_type":text(True),"ownership_form":text(True),
        "identity_confirmed":boolean(),"ambiguous":boolean(),"unit_required":boolean(),"unit_id":text(True),"parcel_id":text(True),
        "parcel_geometry":geometry_schema(),"footprint_geometry":geometry_schema(),"crs":text()})
    result=base_schema("Property risk case input","urn:property-risk-engine:case:0.1.0",
        "A tenant-scoped buyer case. Missing financial values are valid unknowns and must not be replaced with zero. Additional metadata is preserved in the input hash but does not imply a supported calculation.")
    result.update(obj({"case_id":text(),"property_id":text(),"owner_tenant_id":text(True),"as_of":date(),
        "assessment_mode":{"type":"string","description":"A display/workflow mode. public_screen does not remove private due-diligence checks."},
        "property":property_,"finance":obj(finance),"requirements":array(requirement),"scenarios":array(scenario),
        "reviews":{"type":"array","description":"Review/waiver metadata never turns missing evidence into completed coverage."},
        "demonstration":boolean(),"input_note":{"type":"string"}},["case_id","property_id","as_of"]))
    result["allOf"]=[{"if":{"required":["finance"],"properties":{"finance":{"minProperties":1}}},
                       "then":{"required":["owner_tenant_id"],"properties":{"owner_tenant_id":text()}}}]
    result["$comment"] += " Requirement/scenario ID uniqueness, chronological eligibility, supported loan forms, rate units, cash reconciliation and mutually exclusive cost representations require semantic engine validation."
    return result


def payload_schema(kind,properties,required=()):
    return obj({"kind":{"const":kind},**properties},["kind",*required])


def make_observation_schema():
    review={"reviewed":boolean(),"extraction_reviewed":boolean(),"scope_complete":boolean(),"statement":{"type":"string"},
            "summary":{"type":"string"},"scope":{"type":"string"},"requirement_id":text(True),"conflict":boolean(True),"factor_id":text(True),"fact_key":text(True)}
    milestone=obj({"kind":text(),"date":date(),"published_at":date()},["kind","date"])
    impact=obj({"kind":text(),"description":{"type":"string"},"supported":boolean(),"material":boolean(),"requirement_id":text(True),
                "measured_value":decimal(),"threshold":decimal(),"method":text(True),"unit":text(True),"threshold_direction":{"enum":["above","below"]},
                "current_condition":boolean(),"factor_id":text(True)})
    project={"project_id":text(),"milestones":array(milestone),"impacts":array(impact),"expected_completion":date(True),
             "net_dwellings":decimal(),"scope_comparable":boolean(),"declared_net_dwellings_threshold":decimal(),
             "benefit":{"type":"string"},"benefit_supported":boolean(),"timing_known":boolean(),"dependencies":array({"type":"string"})}
    kinds={
        "spatial":payload_schema("spatial",{"subject_geometry":geometry_schema(),"hazard_geometry":geometry_schema(True),"crs":text(),
            "hazard_crs":text(),"metric_crs":text(),"coverage_geometry":geometry_schema(),"coverage_crs":text(),
            "positional_uncertainty_m":decimal(False),"subject_scope":text(),"mechanism":text(),"factor_id":text(),
            "resolution_reviewed":boolean(),"resolution_source_ref":text(),"consequence_resolved":boolean()},
            ["subject_geometry","hazard_geometry","crs","positional_uncertainty_m"]),
        "vertical_clearance":payload_schema("vertical_clearance",{"floor_height":decimal(),"flood_height":decimal(),"floor_datum":text(True),"flood_datum":text(True),"unit":{"const":"m"}}),
        "inspection":payload_schema("inspection",{**review,"material_defect":boolean(True),"minor_issue":boolean(),"cost_known":boolean(),"repair_cost":decimal(),"cost_source_ref":text(True)}),
        "document":payload_schema("document",{**review,"liability_amount":decimal(),"material_liability_unresolved":boolean(),"no_material_liability":boolean()}),
        "restriction":payload_schema("restriction",{**review,"material_question":boolean(),"nonessential_constraint":boolean()}),
        "insurance":payload_schema("insurance",{**review,"material_exclusion":boolean(),"material_question":boolean(),"nonessential_constraint":boolean()}),
        "unit_register":payload_schema("unit_register",{"records":{"type":"array","minItems":1,"items":{"type":"object"}}},["records"]),
        "reviewed_fact":payload_schema("reviewed_fact",{**review,"issue_present":boolean(True),"material":boolean(),"minor":boolean()}),
        "project":payload_schema("project",project,["project_id"]),
        "opportunity":payload_schema("opportunity",project,["project_id"]),
        "context":payload_schema("context",{"summary":{"type":"string"},"measure":decimal(),"unit":text(True),"definition":text(True),"threshold":decimal(),
            "threshold_basis":text(True),"threshold_direction":{"enum":["above","below"]},"comparable":boolean(),"factor_id":text(True),"fact_key":text(True),
            "count":decimal(),"denominator":decimal(),"rate_base":decimal(),"declared_rate_threshold":decimal(),
            "period_start":date(True),"period_end":date(True),"area_id":text(True),"boundary_version":text(True),"reference_period":text(True)})
    }
    rights=obj({"process":boolean(),"display_raw":boolean(),"display_derived":boolean(),"retain_raw":boolean(),"expires_at":date(True)},
               ["process","display_raw","display_derived","retain_raw"],"Independent permissions. Processing or derived-display false blocks a report finding; raw-display false does not.")
    quality=obj({"retrieval_status":text(),"coverage_status":text(),"complete":boolean(True),"current":boolean(True),"identity_match":boolean(True),
                 "schema_valid":boolean(),"units_valid":boolean(),"conflict":boolean()},
                ["retrieval_status","coverage_status","complete","current","identity_match"],
                "Eligibility requires SUCCESS, COVERED and true complete/current/identity_match. Other statuses or unknown flags preserve a gap; HTTP success alone is insufficient.")
    result=base_schema("Property risk observation input","urn:property-risk-engine:observation:0.1.0",
        "One normalised immutable property/check observation with source, knowledge dates, permissions and a supported structured payload. Private HTTP uploads may omit tenant, case and receipt fields that the service derives; this schema describes the stored, scope-bound engine envelope. Shape validation is not evidence validation; failed quality flags remain valid records but cannot support an assessed finding.")
    result.update(obj({"observation_id":text(),"check_id":text(),"property_id":text(),"source_id":text(),"snapshot_id":text(),
        "published_at":date(True),"effective_from":date(True),"effective_to":date(True),"received_at":date(True),
        "evidence_basis":text(),"confidence":{"enum":["High","Medium","Low"]},"visibility_scope":{"enum":["public","private"]},
        "owner_tenant_id":text(True),"case_scope_id":text(True),"origin_visibility_scope":{"enum":["public","private",None]},
        "rights":rights,"quality":quality,"payload":{"oneOf":[{"$ref":"#/$defs/"+name} for name in kinds]},
        "supersedes":{"type":"array","items":text(),"uniqueItems":True},"supersession_reviewed":boolean(),"demonstration":boolean()},
        ["observation_id","check_id","property_id","source_id","snapshot_id","evidence_basis","confidence","visibility_scope","rights","quality","payload"]))
    result["$defs"]=kinds
    result["allOf"]=[
        {"if":{"properties":{"visibility_scope":{"const":"public"}},"required":["visibility_scope"]},
         "then":{"required":["published_at"],"properties":{"published_at":date(),"owner_tenant_id":{"type":"null"},"case_scope_id":{"type":"null"}}}},
        {"if":{"properties":{"visibility_scope":{"const":"private"}},"required":["visibility_scope"]},
         "then":{"required":["owner_tenant_id","case_scope_id","received_at"],"properties":{"owner_tenant_id":text(),"case_scope_id":text(),"received_at":date()}}}
    ]
    result["$comment"] += " Property/tenant/case matching, as-of eligibility, source meaning, quality truth, rights, geometry topology/CRS, payload-to-rule suitability, reviewer attestation and supersession conflicts require semantic validation. Missing decision fields can be deliberately represented as unknown and produce NOT_ASSESSED."
    return result


def main():
    counts=generate_register()
    output=ROOT/"schemas";output.mkdir(parents=True,exist_ok=True)
    for name,schema in [("case.schema.json",make_case_schema()),("observation.schema.json",make_observation_schema())]:
        (output/name).write_text(json.dumps(schema,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(counts,sort_keys=True))


if __name__ == "__main__":main()
