// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

const auth = vi.hoisted(() => ({
    authUtils: {
        getToken: vi.fn<() => string | null>(() => null),
        setToken: vi.fn(),
        setIdleTimeoutSeconds: vi.fn(),
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

    it("triggers window reload when receiving a 503 system_maintenance response", async () => {
        const reloadMock = vi.fn()
        Object.defineProperty(window, "location", {
            writable: true,
            value: { ...window.location, reload: reloadMock },
        })
        sessionStorage.clear()

        vi.mocked(fetch).mockResolvedValue(
            new Response(
                JSON.stringify({
                    status: 503,
                    error: "system_maintenance",
                    message: "ecoSignal is currently undergoing maintenance. Please try again shortly.",
                }),
                {
                    status: 503,
                    statusText: "Service Unavailable",
                    headers: { "Content-Type": "application/json" },
                },
            ),
        )

        await expect(apiClient.get("/v1/users/creators")).rejects.toBeInstanceOf(ApiError)
        expect(reloadMock).toHaveBeenCalled()
    })

    it("refreshes and retries a 401 request even when ignoreUnauthorized is true", async () => {
        auth.authUtils.getToken.mockReturnValue("expired-token")
        vi.mocked(fetch)
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ message: "Unauthorized" }), {
                    status: 401,
                    statusText: "Unauthorized",
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ access_token: "fresh-token", session_idle_timeout_seconds: 1800 }), {
                    status: 200,
                    statusText: "OK",
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ code: 0, data: { is_admin: true } }), {
                    status: 200,
                    statusText: "OK",
                    headers: { "Content-Type": "application/json" },
                }),
            )

        const result = await apiClient.get<{ code: number; data: { is_admin: boolean } }>("/v1/current-user", {
            ignoreUnauthorized: true,
        })

        expect(result.data.is_admin).toBe(true)
        expect(auth.authUtils.setToken).toHaveBeenCalledWith("fresh-token")
        expect(auth.dispatchLoginRequired).not.toHaveBeenCalled()
        expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3)
    })

    it("throws without prompting login when ignoreUnauthorized is true and token refresh fails", async () => {
        auth.authUtils.getToken.mockReturnValue("expired-token")
        vi.mocked(fetch)
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ message: "Unauthorized" }), {
                    status: 401,
                    statusText: "Unauthorized",
                    headers: { "Content-Type": "application/json" },
                }),
            )
            .mockResolvedValueOnce(
                new Response(JSON.stringify({ message: "Refresh failed" }), {
                    status: 401,
                    statusText: "Unauthorized",
                    headers: { "Content-Type": "application/json" },
                }),
            )

        await expect(
            apiClient.get("/v1/current-user", { ignoreUnauthorized: true }),
        ).rejects.toBeInstanceOf(ApiError)
        expect(auth.dispatchLoginRequired).not.toHaveBeenCalled()
    })
})
