// @vitest-environment jsdom

import { render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
    applyAccountTheme: vi.fn(),
    getPreference: vi.fn(),
    getToken: vi.fn(),
    getSessionVersion: vi.fn(),
    startMonitor: vi.fn(),
    stopMonitor: vi.fn(),
}))

vi.mock("@/api/endpoints/users", () => ({
    userPreferenceApi: { get: mocks.getPreference },
}))

vi.mock("@/store/useAppStore", () => ({
    normalizeTheme: (value: unknown) =>
        value === "light" || value === "dark" || value === "auto" ? value : "auto",
    useAppStore: { getState: () => ({ applyAccountTheme: mocks.applyAccountTheme }) },
}))

vi.mock("@/utils/auth", () => ({
    AUTH_LANDING_PATH: "/",
    AUTH_SESSION_VERSION_KEY: "authSessionVersion",
    authUtils: { getToken: mocks.getToken, getSessionVersion: mocks.getSessionVersion },
}))

vi.mock("@/utils/sessionActivityMonitor", () => ({
    startSessionActivityMonitor: mocks.startMonitor,
    stopSessionActivityMonitor: mocks.stopMonitor,
}))

import { AuthSessionWatcher } from "./AuthSessionWatcher"

describe("AuthSessionWatcher theme synchronization", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        mocks.getSessionVersion.mockReturnValue(null)
    })

    it("applies the signed-in account theme", async () => {
        mocks.getToken.mockReturnValue("token-a")
        mocks.getPreference.mockResolvedValue({ theme: "dark" })

        render(<AuthSessionWatcher />)

        await waitFor(() => expect(mocks.applyAccountTheme).toHaveBeenCalledWith("dark"))
    })

    it("keeps the current theme after logout", async () => {
        mocks.getToken.mockReturnValue(null)

        render(<AuthSessionWatcher />)
        window.dispatchEvent(new CustomEvent("eco-auth-change"))

        await Promise.resolve()
        expect(mocks.getPreference).not.toHaveBeenCalled()
        expect(mocks.applyAccountTheme).not.toHaveBeenCalled()
    })

    it("ignores a previous account response after switching accounts", async () => {
        let resolveFirst: ((value: { theme: string }) => void) | undefined
        const firstPreference = new Promise<{ theme: string }>((resolve) => {
            resolveFirst = resolve
        })

        mocks.getToken.mockReturnValue("token-a")
        mocks.getPreference
            .mockImplementationOnce(() => firstPreference)
            .mockResolvedValueOnce({ theme: "light" })

        render(<AuthSessionWatcher />)
        mocks.getToken.mockReturnValue("token-b")
        window.dispatchEvent(new CustomEvent("eco-auth-change"))

        await waitFor(() => expect(mocks.applyAccountTheme).toHaveBeenCalledWith("light"))
        resolveFirst?.({ theme: "dark" })
        await Promise.resolve()

        expect(mocks.applyAccountTheme).toHaveBeenCalledTimes(1)
    })

    it("clears account-scoped cache and broadcasts an external session change", async () => {
        mocks.getToken.mockReturnValue("token-a")
        mocks.getSessionVersion.mockReturnValueOnce("session-a").mockReturnValue("session-b")
        mocks.getPreference.mockResolvedValue({ theme: "light" })
        const onAuthChange = vi.fn()
        window.addEventListener("eco-auth-change", onAuthChange)

        render(<AuthSessionWatcher />)
        window.dispatchEvent(new StorageEvent("storage", { key: "authSessionVersion", newValue: "session-b" }))

        await waitFor(() => expect(onAuthChange).toHaveBeenCalledTimes(1))
        window.removeEventListener("eco-auth-change", onAuthChange)
    })
})
