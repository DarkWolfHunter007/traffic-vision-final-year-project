"""FastAPI application wiring with Phase 10 manual review and human-in-the-loop endpoints."""

from __future__ import annotations

from typing import Any
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend import __version__
from backend.services.review import (
    create_manual_review,
    find_review_candidates,
    generate_snippet_for_review,
    get_manual_review_by_id,
    get_manual_reviews,
    update_manual_review,
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

    return app


app = create_app()
