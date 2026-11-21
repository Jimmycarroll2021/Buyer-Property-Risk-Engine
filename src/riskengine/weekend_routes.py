"""Local dashboard routes for the five illustrative owner-occupier studies."""
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .engine import canonical_hash
from .finance import FinanceInputError
from .storage import Conflict, Forbidden, NotFound, StoreError
from .weekend_study import capture, evaluate_study, examples


class StudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    example_id: str = Field(max_length=90)
    changes: dict = Field(default_factory=dict)
    source_notes: dict = Field(default_factory=dict)
    based_on: str | None = Field(default=None, max_length=160)


class SaveStudyRequest(StudyRequest):
    worksheet: UUID
    expected_version: int = Field(ge=0, strict=True)


def register_weekend(app, store, auth, dashboard):
    @app.get("/v1/weekend/examples")
    def catalog(tenant: str = Depends(auth)):
        return {"examples": examples(), "sample_workspace": bool(dashboard and dashboard.mode == "preview")}

    def resolve(body, tenant):
        if body.based_on:
            saved = store.get_assessment(tenant, body.based_on)
            if "weekend" not in saved:
                raise Conflict("This assessment has no saved weekend worksheet")
            example = saved["weekend"]["capture"]["example"]
            if example["id"] != body.example_id:
                raise Conflict("Select the example used in the saved worksheet")
        else:
            example = next((row for row in examples() if row["id"] == body.example_id), None)
            if example is None:
                raise NotFound("Weekend example not found")
        if dashboard and dashboard.mode == "preview" and body.source_notes:
            raise Forbidden("Record personal evidence in the private desktop workspace")
        return capture(example, body.changes, body.source_notes)

    @app.post("/v1/weekend/preview")
    def preview(body: StudyRequest, tenant: str = Depends(auth)):
        try:
            return evaluate_study(resolve(body, tenant))
        except FinanceInputError as exc:
            raise StoreError(str(exc)) from exc

    @app.post("/v1/weekend/assessments", status_code=201)
    def save(body: SaveStudyRequest, tenant: str = Depends(auth)):
        from .pipeline import assess_case

        study = resolve(body, tenant)
        # Validate and calculate before writing a new version.
        try:
            evaluate_study(study)
        except FinanceInputError as exc:
            raise StoreError(str(exc)) from exc
        example = study["example"]
        prop = example["property"]
        label = (prop.get("label") or prop.get("name") or prop.get("address")) if isinstance(prop, dict) else prop
        case_id = "weekend-" + str(body.worksheet)
        as_of = example["as_of"]
        if len(as_of) == 10:
            as_of += "T00:00:00+11:00"
        case = {"case_id": case_id, "property_id": "weekend-" + example["id"],
                "as_of": as_of,
                "property": {"label": label or example["name"], "jurisdiction": "ACT", "identity_confirmed": False},
                "demonstration": True, "assessment_mode": "buyer_assessment", "weekend_study": study}
        try:
            pinned = store.save_case(tenant, case, body.expected_version)
        except Conflict:
            # A repeated submit after a lost response may already have created this exact version.
            head = store.get_case(tenant, case_id)
            if head.get("weekend_study") != study or head["case_version"] != body.expected_version + 1:
                raise
            pinned = head
        result = assess_case(store, tenant, case_id, expected_version=pinned["case_version"])
        return {"assessment_id": result["assessment_id"], "case_id": case_id,
                "case_version": pinned["case_version"], "weekend": result["weekend"]}

    @app.get("/v1/weekend/history")
    def history(tenant: str = Depends(auth)):
        rows = []
        for case in store.list_cases(tenant):
            if "weekend_study" in case:
                for item in store.list_assessments(tenant, case["case_id"]):
                    if item["display_allowed"]:
                        rows.append({"name": case["weekend_study"]["example"]["name"],
                                     "case_id": case["case_id"], **item})
        return {"assessments": sorted(rows, key=lambda row: row["created_at"], reverse=True)}

    @app.post("/v1/weekend/assessments/{assessment_id}/replay")
    def replay(assessment_id: str, tenant: str = Depends(auth)):
        from .pipeline import replay_assessment

        saved, recomputed = replay_assessment(store, tenant, assessment_id)
        if "weekend" not in saved:
            raise HTTPException(422, "This assessment has no weekend worksheet")
        saved_hash, replay_hash = canonical_hash(saved), canonical_hash(recomputed)
        if saved_hash != replay_hash:
            raise Conflict("The current model differs from the pinned assessment")
        return {"assessment_id": assessment_id, "exact_match": True, "saved_hash": saved_hash, "replayed_hash": replay_hash}
