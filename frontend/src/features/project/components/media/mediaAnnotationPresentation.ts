import type { AnnotationPublic } from "../../../../api/endpoints/annotations"

export type MediaAnnotationPresentation = {
    creatorColor: string
    hasAnyReview: boolean
    hasAssignedTask: boolean
    label: string
}

export function normalizeUserColorHex(raw: unknown): string | null {
    if (typeof raw !== "string") return null
    const value = raw.trim()
    return /^#[0-9a-fA-F]{6}$/.test(value) ? value.toUpperCase() : null
}

export function annotationHasAnyReview(annotation: AnnotationPublic): boolean {
    return Array.isArray(annotation.reviews) && annotation.reviews.length > 0
}

export function annotationHasAssignedTask(annotation: AnnotationPublic): boolean {
    const taskId = Number(annotation.task?.task_id)
    return Number.isFinite(taskId) && taskId > 0
}

export function annotationHasUserReview(
    annotation: AnnotationPublic,
    reviewerId: number | null,
): boolean {
    return (
        reviewerId != null &&
        Array.isArray(annotation.reviews) &&
        annotation.reviews.some((review) => Number(review.reviewer_id) === reviewerId)
    )
}

export function annotationHasActiveAssignedTask(
    annotation: AnnotationPublic,
    reviewerId: number | null,
): boolean {
    return annotationHasAssignedTask(annotation) && !annotationHasUserReview(annotation, reviewerId)
}

export function getMediaAnnotationPresentation(
    annotation: AnnotationPublic,
    fallbackColor: string,
    reviewerId: number | null = null,
): MediaAnnotationPresentation {
    return {
        creatorColor:
            normalizeUserColorHex(annotation.creator_color) ??
            normalizeUserColorHex(fallbackColor) ??
            "#3B82F6",
        hasAnyReview: annotationHasAnyReview(annotation),
        hasAssignedTask: annotationHasActiveAssignedTask(annotation, reviewerId),
        label:
            annotation.sound_type?.trim() ||
            annotation.soundscape_component?.trim() ||
            "Annotation",
    }
}

export function mediaAnnotationClassName(
    presentation: Pick<MediaAnnotationPresentation, "hasAnyReview" | "hasAssignedTask">,
    linked: boolean,
): string {
    return [
        "media-annotation-box",
        presentation.hasAnyReview
            ? "media-annotation-box--has-review"
            : "media-annotation-box--no-review",
        presentation.hasAssignedTask ? "media-annotation-box--has-task" : "",
        linked ? "media-annotation-box--linked" : "",
    ]
        .filter(Boolean)
        .join(" ")
}
