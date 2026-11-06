import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { StorageMonitorProvider, StorageWarningBanner, useStorageMonitor } from "./StorageMonitor"

const api = vi.hoisted(() => ({ me: vi.fn(), storage: vi.fn() }))
vi.mock("@/api/endpoints/users", () => ({ usersApi: { getMe: api.me } }))
vi.mock("@/api/endpoints/system", () => ({ systemApi: { getStorageStatus: api.storage } }))
const response = (status = "warning", percent = 80) => ({ code: 0, data: {
    checked_at: "2026-11-05 00:00:00", status, warning_percent: 80, critical_percent: 90,
    filesystems: [{ scope: "media", path: "/media", available: true, total_bytes: 100, used_bytes: percent, free_bytes: 100-percent, used_percent: percent, status }],
} })
function Consumer() {
    const { storage, refresh } = useStorageMonitor()
    return <><button onClick={refresh}>Refresh storage</button><span data-testid="status">{storage?.status}</span><StorageWarningBanner /></>
}
function mount() { return render(<StorageMonitorProvider><Consumer /></StorageMonitorProvider>) }

beforeEach(() => {
    localStorage.clear()
    localStorage.setItem("accessToken", "admin")
    api.me.mockReset().mockResolvedValue({ data: { is_admin: true } })
    api.storage.mockReset().mockResolvedValue(response())
    Object.defineProperty(document, "hidden", { configurable: true, value: false })
})
afterEach(() => { vi.useRealTimers() })

describe("filesystem warning", () => {
    it("does not request storage for anonymous visitors", async () => {
        localStorage.clear()
        mount()
        await act(async () => {})
        expect(api.me).not.toHaveBeenCalled()
        expect(api.storage).not.toHaveBeenCalled()
    })
    it("does not request storage for ordinary users", async () => {
        api.me.mockResolvedValue({ data: { is_admin: false } })
        mount()
        await waitFor(() => expect(api.me).toHaveBeenCalledOnce())
        expect(api.storage).not.toHaveBeenCalled()
    })
    it.each([["healthy", 79.9, false], ["warning", 80, true], ["warning", 89.9, true], ["critical", 90, true]])(
        "renders %s according to server status", async (status, percent, visible) => {
            api.storage.mockResolvedValue(response(status, percent))
            mount()
            await waitFor(() => expect(screen.getByTestId("status").textContent).toBe(status))
            expect(Boolean(screen.queryByRole("alert"))).toBe(visible)
            if (visible) expect(screen.getByRole("alert")).toHaveTextContent(`${percent.toFixed(1)}% used`)
        },
    )
    it("clears the warning when storage recovers", async () => {
        mount()
        await screen.findByRole("alert")
        api.storage.mockResolvedValue(response("healthy", 50))
        fireEvent.click(screen.getByText("Refresh storage"))
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
    })
    it("reports unavailable status when polling fails", async () => {
        api.storage.mockRejectedValue(new Error("offline"))
        mount()
        expect(await screen.findByRole("alert")).toHaveTextContent("Storage status is unavailable")
    })
    it("shares one request across multiple consumers", async () => {
        render(<StorageMonitorProvider><Consumer /><StorageWarningBanner /></StorageMonitorProvider>)
        await waitFor(() => expect(api.storage).toHaveBeenCalledOnce())
    })
    it("aborts polling and clears privileged data on logout", async () => {
        mount()
        await screen.findByRole("alert")
        const signal = api.storage.mock.calls[0]?.[0] as AbortSignal | undefined
        act(() => {
            localStorage.clear()
            window.dispatchEvent(new Event("eco-auth-change"))
        })
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument())
        expect(signal?.aborted).toBe(true)
    })
    it("polls after sixty seconds and pauses while hidden", async () => {
        vi.useFakeTimers()
        mount()
        await act(async () => {})
        expect(api.storage).toHaveBeenCalledOnce()
        await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
        expect(api.storage).toHaveBeenCalledTimes(2)
        Object.defineProperty(document, "hidden", { configurable: true, value: true })
        fireEvent(document, new Event("visibilitychange"))
        await act(async () => { await vi.advanceTimersByTimeAsync(120000) })
        expect(api.storage).toHaveBeenCalledTimes(2)
        Object.defineProperty(document, "hidden", { configurable: true, value: false })
        fireEvent(document, new Event("visibilitychange"))
        await act(async () => {})
        expect(api.storage).toHaveBeenCalledTimes(3)
    })
    it("ignores a previous account response", async () => {
        let resolve: (value: unknown) => void = () => {}
        api.storage.mockReturnValueOnce(new Promise(done => { resolve = done }))
        mount()
        await waitFor(() => expect(api.storage).toHaveBeenCalledOnce())
        api.me.mockResolvedValue({ data: { is_admin: false } })
        act(() => {
            localStorage.setItem("accessToken", "ordinary")
            window.dispatchEvent(new Event("eco-auth-change"))
        })
        await act(async () => { resolve(response()) })
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })
})
