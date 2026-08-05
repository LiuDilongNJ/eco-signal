import { beforeEach, describe, expect, it, vi } from "vitest"

const { get, post, put, deleteRequest, download } = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    deleteRequest: vi.fn(),
    download: vi.fn(),
}))

vi.mock("../client", () => ({
    apiClient: {
        get,
        post,
        put,
        delete: deleteRequest,
        download,
    },
}))

import { soundClassificationsApi } from "./soundClassifications"

describe("soundClassificationsApi", () => {
    beforeEach(() => vi.clearAllMocks())

    it("maps management CRUD requests to the dedicated resource", () => {
        const body = { soundscape_component: "biophony", sound_type: null }
        soundClassificationsApi.list({ page: 2, page_size: 20, sound_type: "  ", order_by: "sound_id" })
        soundClassificationsApi.get(7)
        soundClassificationsApi.create(body)
        soundClassificationsApi.update(7, body)
        soundClassificationsApi.delete(7)

        expect(get).toHaveBeenNthCalledWith(1, "/v1/sound-classification-records", {
            params: { page: 2, page_size: 20, order_by: "sound_id" },
            ignoreUnauthorized: true,
        })
        expect(get).toHaveBeenNthCalledWith(2, "/v1/sound-classification-records/7")
        expect(post).toHaveBeenCalledWith("/v1/sound-classification-records", body)
        expect(put).toHaveBeenCalledWith("/v1/sound-classification-records/7", body)
        expect(deleteRequest).toHaveBeenCalledWith("/v1/sound-classification-records/7")
    })

    it("uploads CSV with the file field and exports sorting only", () => {
        const file = new File(["soundscape_component,sound_type\nbiophony,bird\n"], "sounds.csv", { type: "text/csv" })
        soundClassificationsApi.importCsv(file)
        soundClassificationsApi.exportCsv({ order_by: "sound_type", order_dir: "desc" })

        const formData = post.mock.calls[0]?.[1] as FormData
        expect(post.mock.calls[0]?.[0]).toBe("/v1/sound-classification-records/imports")
        expect(formData.get("file")).toBe(file)
        expect(download).toHaveBeenCalledWith("/v1/sound-classification-records/exports", {
            params: { order_by: "sound_type", order_dir: "desc" },
        })
    })
})
