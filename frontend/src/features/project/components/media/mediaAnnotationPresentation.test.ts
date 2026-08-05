import { describe, expect, it } from "vitest"

import type { AnnotationPublic } from "../../../../api/endpoints/annotations"
import type { AnnotationReviewRead } from "../../../../api/endpoints/reviews"
import {
    annotationHasActiveAssignedTask,
    getMediaAnnotationPresentation,
} from "./mediaAnnotationPresentation"

function annotationWithTask(reviews: AnnotationReviewRead[] = []): AnnotationPublic {
    return {
        annotation_id: 101,
        uuid: "annotation-101",
        media_id: 11,
        min_x: 0,
        max_x: 1,
        min_y: 100,
        max_y: 200,
        creator_id: 2,
        task: {
            task_id: 44,
            type: "review",
            status: "assigned",
        },
        reviews,
    }
}

function reviewBy(reviewerId: number): AnnotationReviewRead {
    return {
        annotation_id: 101,
        reviewer_id: reviewerId,
        annotation_review_status_id: 1,
        creation_date: "2026-08-05T00:00:00Z",
        reviewer_name: "Reviewer",
        status_name: "Accepted",
    }
}

describe("assigned annotation presentation", () => {
    it("removes the current user's Task presentation after they submit a review", () => {
        const annotation = annotationWithTask([reviewBy(7)])

        expect(annotationHasActiveAssignedTask(annotation, 7)).toBe(false)
        expect(getMediaAnnotationPresentation(annotation, "#3B82F6", 7)).toMatchObject({
            hasAnyReview: true,
            hasAssignedTask: false,
        })
    })

    it("keeps the Task presentation when only another user has reviewed", () => {
        const annotation = annotationWithTask([reviewBy(8)])

        expect(annotationHasActiveAssignedTask(annotation, 7)).toBe(true)
        expect(getMediaAnnotationPresentation(annotation, "#3B82F6", 7)).toMatchObject({
            hasAnyReview: true,
            hasAssignedTask: true,
        })
    })
})
