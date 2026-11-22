import { describe, expect, it } from "vitest"

import { resolveAnnotationReviewPanelVisibility } from "./mediaDetailSupport"

describe("resolveAnnotationReviewPanelVisibility", () => {
    it("shows review buttons when the user has review permission and has not reviewed yet, even if other users already reviewed", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: true,
                canCreateReview: true,
                hasOwnReview: false,
                isOwnReviewResolved: true,
                isEditingOwnReview: false,
            }),
        ).toEqual({
            showReviewForm: true,
            showEditButton: false,
        })
    })

    it("hides review buttons and shows Edit when the current user already reviewed the annotation", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: true,
                canCreateReview: true,
                hasOwnReview: true,
                isOwnReviewResolved: true,
                isEditingOwnReview: false,
            }),
        ).toEqual({
            showReviewForm: false,
            showEditButton: true,
        })
    })

    it("shows the review form and hides Edit when the current user clicks Edit on their existing review", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: true,
                canCreateReview: true,
                hasOwnReview: true,
                isOwnReviewResolved: true,
                isEditingOwnReview: true,
            }),
        ).toEqual({
            showReviewForm: true,
            showEditButton: false,
        })
    })

    it("hides both review buttons and Edit when the user is not authenticated", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: false,
                canCreateReview: true,
                hasOwnReview: false,
                isOwnReviewResolved: true,
                isEditingOwnReview: false,
            }),
        ).toEqual({
            showReviewForm: false,
            showEditButton: false,
        })
    })

    it("hides both review buttons and Edit when the user lacks review write permission", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: true,
                canCreateReview: false,
                hasOwnReview: false,
                isOwnReviewResolved: true,
                isEditingOwnReview: false,
            }),
        ).toEqual({
            showReviewForm: false,
            showEditButton: false,
        })
    })

    it("waits until current user identity is resolved before showing review buttons when existing reviews are present", () => {
        expect(
            resolveAnnotationReviewPanelVisibility({
                isAuthenticated: true,
                canCreateReview: true,
                hasOwnReview: false,
                isOwnReviewResolved: false,
                isEditingOwnReview: false,
            }),
        ).toEqual({
            showReviewForm: false,
            showEditButton: false,
        })
    })
})
