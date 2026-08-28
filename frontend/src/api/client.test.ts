// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

const auth = vi.hoisted(() => ({
    authUtils: {
        getToken: vi.fn(() => null),
        markSessionActivity: vi.fn(),
    },
    dispatchAuthChange: vi.fn(),
    dispatchLoginRequired: vi.fn(),
}))

vi.mock("../utils/auth", () => auth)

import { ApiError, apiClient } from "./client"

describe("apiClient authorization handling", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.stubGlobal("fetch", vi.fn())
    })

    it("throws a 403 without starting the login flow", async () => {
        vi.mocked(fetch).mockResolvedValue(
            new Response(JSON.stringify({ message: "Forbidden" }), {
                status: 403,
                statusText: "Forbidden",
                headers: { "Content-Type": "application/json" },
            }),
        )

        await expect(apiClient.get("/v1/users/creators")).rejects.toBeInstanceOf(ApiError)
        expect(auth.dispatchLoginRequired).not.toHaveBeenCalled()
    })
})
