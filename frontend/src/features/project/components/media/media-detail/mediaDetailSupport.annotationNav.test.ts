import { describe, expect, it } from "vitest"

import type { AnnotationPublic } from "../../../../../api/endpoints/annotations"
import {
    annotationAtEdge,
    annotationZoomToggleLabel,
    orderedMediaIdsOfType,
    readAnnotationZoomToggle,
    taskToggleLabel,
    writeAnnotationZoomToggle,
} from "./mediaDetailSupport"

function annotation(id: number, minX: number, minY = 0): AnnotationPublic {
    return { annotation_id: id, min_x: minX, max_x: minX + 1, min_y: minY, max_y: minY + 1 } as AnnotationPublic
}

describe("orderedMediaIdsOfType", () => {
    const options = [
        { media_id: 8, media_type: "photo" },
        { media_id: 3, media_type: "audio" },
        { media_id: 1, media_type: "Audio" },
        { media_id: 5, media_type: "audio" },
    ]

    it("keeps the same media type in media_id order", () => {
        expect(orderedMediaIdsOfType(options, "audio")).toEqual([1, 3, 5])
    })
})

describe("annotationAtEdge", () => {
    const list = [annotation(4, 10), annotation(2, 1), annotation(9, 1, 50)]

    it("uses the earliest annotation when moving onto the next recording", () => {
        expect(annotationAtEdge(list, 1)?.annotation_id).toBe(2)
    })

    it("keeps annotation zoom on when the next media link or this tab already enabled it", () => {
        writeAnnotationZoomToggle(false)
        expect(readAnnotationZoomToggle("?annotation_zoom=1")).toBe(true)
        expect(readAnnotationZoomToggle("?annotation_zoom=0")).toBe(false)
        writeAnnotationZoomToggle(true)
        expect(readAnnotationZoomToggle("")).toBe(true)
        expect(annotationZoomToggleLabel(true)).toContain("select and zoom into annotations")
        expect(taskToggleLabel(true)).toContain("jump to those in other media")
    })

    it("uses the latest annotation when moving onto the previous recording", () => {
        expect(annotationAtEdge(list, -1)?.annotation_id).toBe(4)
    })
})
