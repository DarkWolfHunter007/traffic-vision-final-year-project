"""FastAPI application wiring with Phase 10 manual review and human-in-the-loop endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend import __version__
from backend.config import load_config
from backend.services.dataset import (
    audit_dataset_leakage_from_path,
    build_active_learning_dataset,
    get_dataset_manifest,
)
from backend.services.review import (
    create_manual_review,
    find_review_candidates,
    generate_snippet_for_review,
    get_manual_review_by_id,
    get_manual_reviews,
    update_manual_review,
)
from backend.evaluation import EvaluationError, EvaluationLeakageError
from backend.services.evaluation import (
    compare_models,
    evaluate_counting,
    evaluate_detection,
    get_model_details,
    list_models,
    register_model,
    select_production_model,
)



class BoundingBoxModel(BaseModel):
    x1: float = Field(..., description="Top-left x coordinate in pixels")
    y1: float = Field(..., description="Top-left y coordinate in pixels")
    x2: float = Field(..., description="Bottom-right x coordinate in pixels")
    y2: float = Field(..., description="Bottom-right y coordinate in pixels")


class CandidateSearchRequest(BaseModel):
    parent_run_id: str
    confidence_threshold: float | None = None
    limit: int | None = None


class CreateReviewRequest(BaseModel):
    parent_run_id: str
    frame_number: int
    timestamp_s: float
    reason: str
    detection_id: str | None = None
    track_id: int | None = None
    reviewer: str = "analyst"
    original_class: str | None = None
    corrected_class: str | None = None
    original_bbox: BoundingBoxModel | None = None
    corrected_bbox: BoundingBoxModel | None = None
    status: str = "pending"
    generate_snippet: bool = False


class UpdateReviewRequest(BaseModel):
    status: str | None = None
    corrected_class: str | None = None
    corrected_bbox: BoundingBoxModel | None = None
    reviewer: str | None = None
    reason: str | None = None


class ExportDatasetRequest(BaseModel):
    output_dir: str | None = None
    dataset_version: str | None = None
    run_id: str | None = None
    video_id: str | None = None
    split_ratios: dict[str, float] | None = None
    split_strategy: str | None = None
    time_block_duration_s: float | None = None
    seed: int | None = None
    min_frame_interval_s: float | None = None
    export_images: bool | None = True


class AuditDatasetLeakageRequest(BaseModel):
    dataset_path: str


class RegisterModelRequest(BaseModel):
    model_version: str
    model_path: str
    dataset_version: str | None = None


class EvaluateDetectionRequest(BaseModel):
    model_version: str
    dataset_path: str
    split: str = "val"


class EvaluateCountingRequest(BaseModel):
    model_version: str
    run_id: str
    ground_truth_set_id: str | None = None


class CompareModelsRequest(BaseModel):
    model_version_a: str
    model_version_b: str


class SelectProductionModelRequest(BaseModel):
    model_version: str



def create_app() -> FastAPI:
    app = FastAPI(title="Traffic Vision", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "phase": "01", "version": __version__}

    @app.get("/status")
    def status_endpoint() -> dict[str, str]:
        return {"implementation_scope": "phase_01_foundation", "next_cv_phase": "phase_02_detection"}

    # Phase 10 Manual Review Endpoints

    @app.post("/reviews/candidates")
    def search_candidates(request: CandidateSearchRequest) -> dict[str, Any]:
        try:
            return find_review_candidates(
                parent_run_id=request.parent_run_id,
                confidence_threshold=request.confidence_threshold,
                limit=request.limit,
            )
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    @app.post("/reviews", status_code=status.HTTP_201_CREATED)
    def create_review(request: CreateReviewRequest) -> dict[str, Any]:
        try:
            orig_bbox_dict = request.original_bbox.model_dump() if request.original_bbox else None
            corr_bbox_dict = request.corrected_bbox.model_dump() if request.corrected_bbox else None
            return create_manual_review(
                parent_run_id=request.parent_run_id,
                frame_number=request.frame_number,
                timestamp_s=request.timestamp_s,
                reason=request.reason,
                detection_id=request.detection_id,
                track_id=request.track_id,
                reviewer=request.reviewer,
                original_class=request.original_class,
                corrected_class=request.corrected_class,
                original_bbox=orig_bbox_dict,
                corrected_bbox=corr_bbox_dict,
                status=request.status,
                generate_snippet=request.generate_snippet,
            )
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.get("/reviews")
    def list_reviews(
        run_id: str | None = Query(None),
        video_id: str | None = Query(None),
        review_status: str | None = Query(None),
        reviewer: str | None = Query(None),
        track_id: int | None = Query(None),
        detection_id: str | None = Query(None),
        limit: int | None = Query(None),
    ) -> dict[str, Any]:
        return get_manual_reviews(
            run_id=run_id,
            video_id=video_id,
            review_status=review_status,
            reviewer=reviewer,
            track_id=track_id,
            detection_id=detection_id,
            limit=limit,
        )

    @app.get("/reviews/{review_id}")
    def get_review(review_id: str) -> dict[str, Any]:
        review = get_manual_review_by_id(review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Manual review '{review_id}' not found",
            )
        return review

    @app.patch("/reviews/{review_id}")
    def patch_review(review_id: str, request: UpdateReviewRequest) -> dict[str, Any]:
        try:
            corr_bbox_dict = request.corrected_bbox.model_dump() if request.corrected_bbox else None
            return update_manual_review(
                review_id=review_id,
                status=request.status,
                corrected_class=request.corrected_class,
                corrected_bbox=corr_bbox_dict,
                reviewer=request.reviewer,
                reason=request.reason,
            )
        except ValueError as err:
            detail_msg = str(err)
            if "not found" in detail_msg.lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail_msg)
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail_msg)

    @app.post("/reviews/{review_id}/snippet")
    def trigger_snippet(review_id: str) -> dict[str, Any]:
        try:
            snippet_path = generate_snippet_for_review(review_id)
            return {"review_id": review_id, "snippet_path": str(snippet_path)}
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))
        except FileNotFoundError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))
        except RuntimeError as err:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(err))

    # Phase 11 Active-Learning Dataset Endpoints

    @app.post("/datasets/export", status_code=status.HTTP_201_CREATED)
    def export_dataset_endpoint(request: ExportDatasetRequest) -> dict[str, Any]:
        try:
            return build_active_learning_dataset(
                output_dir=request.output_dir,
                dataset_version=request.dataset_version,
                run_id=request.run_id,
                video_id=request.video_id,
                split_ratios=request.split_ratios,
                split_strategy=request.split_strategy,
                time_block_duration_s=request.time_block_duration_s,
                seed=request.seed,
                min_frame_interval_s=request.min_frame_interval_s,
                export_images=request.export_images,
            )
        except (ValueError, FileNotFoundError, RuntimeError) as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.get("/datasets/{dataset_version}/manifest")
    def get_manifest_endpoint(dataset_version: str, output_dir: str | None = Query(None)) -> dict[str, Any]:
        cfg = load_config()
        base_dir = output_dir or cfg.get("active_learning", {}).get("output_dir", "data/processed/datasets")
        ds_path = Path(base_dir) / dataset_version
        try:
            return get_dataset_manifest(ds_path)
        except FileNotFoundError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))

    @app.post("/datasets/audit-leakage")
    def audit_leakage_endpoint(request: AuditDatasetLeakageRequest) -> dict[str, Any]:
        try:
            return audit_dataset_leakage_from_path(request.dataset_path)
        except FileNotFoundError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))
        except (ValueError, RuntimeError) as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    # Phase 12 Model Evaluation Endpoints

    @app.post("/models/register", status_code=status.HTTP_201_CREATED)
    def register_model_endpoint(request: RegisterModelRequest) -> dict[str, Any]:
        try:
            return register_model(
                model_version=request.model_version,
                model_path=request.model_path,
                dataset_version=request.dataset_version,
            )
        except (EvaluationError, FileNotFoundError, ValueError) as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.get("/models")
    def list_models_endpoint() -> list[dict[str, Any]]:
        return list_models()

    @app.get("/models/{model_version}")
    def get_model_endpoint(model_version: str) -> dict[str, Any]:
        try:
            return get_model_details(model_version)
        except EvaluationError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))

    @app.post("/models/evaluate-detection")
    def evaluate_detection_endpoint(request: EvaluateDetectionRequest) -> dict[str, Any]:
        try:
            return evaluate_detection(
                model_version=request.model_version,
                dataset_path=request.dataset_path,
                split=request.split,
            )
        except EvaluationLeakageError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Leakage check failed: {err}")
        except FileNotFoundError as err:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err))
        except EvaluationError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.post("/models/evaluate-counting")
    def evaluate_counting_endpoint(request: EvaluateCountingRequest) -> dict[str, Any]:
        try:
            return evaluate_counting(
                model_version=request.model_version,
                run_id=request.run_id,
                ground_truth_set_id=request.ground_truth_set_id,
            )
        except EvaluationError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.post("/models/compare")
    def compare_models_endpoint(request: CompareModelsRequest) -> dict[str, Any]:
        try:
            return compare_models(
                model_version_a=request.model_version_a,
                model_version_b=request.model_version_b,
            )
        except EvaluationError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    @app.post("/models/select-production")
    def select_production_model_endpoint(request: SelectProductionModelRequest) -> dict[str, Any]:
        try:
            return select_production_model(model_version=request.model_version)
        except EvaluationError as err:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err))

    return app



app = create_app()
