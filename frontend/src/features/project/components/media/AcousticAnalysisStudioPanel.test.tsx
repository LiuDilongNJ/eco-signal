import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { AcousticAnalysisStudioPanel } from "./AcousticAnalysisStudioPanel"

const { pollAnalysisQueues, runAcousticIndices } = vi.hoisted(() => ({
    pollAnalysisQueues: vi.fn(),
    runAcousticIndices: vi.fn(),
}))

vi.mock("../../../../api/endpoints/analysis", () => ({
    analysisApi: { runAcousticIndices },
}))

vi.mock("../modals/utils/analysisQueuePolling", () => ({
    isAbortError: () => false,
    pollAnalysisQueues,
}))

vi.mock("@/components/ui", async (importOriginal) => ({
    ...await importOriginal<typeof import("@/components/ui")>(),
    CustomScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

vi.mock("../modals/AnalysisResultModal", () => ({
    AnalysisResultModal: ({
        items,
        open,
        title,
    }: {
        items: Array<{ label: string; value: string }>
        open: boolean
        title: string
    }) => open ? (
        <div role="dialog" aria-label={title}>
            {items.map((item) => <div key={item.label}>{item.label}: {item.value}</div>)}
        </div>
    ) : null,
}))

const selection = {
    min_time: 10,
    max_time: 20,
    min_frequency: 100,
    max_frequency: 8000,
}

beforeAll(() => {
    class ResizeObserverMock {
        disconnect() {}
        observe() {}
        unobserve() {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverMock)
    const getComputedStyle = window.getComputedStyle.bind(window)
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) => getComputedStyle(element))
    Object.defineProperty(window, "matchMedia", {
        configurable: true,
        value: vi.fn().mockImplementation(() => ({
            matches: false,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        })),
    })
})

beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, "isSecureContext", {
        configurable: true,
        value: true,
    })
    Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
    Object.defineProperty(document, "execCommand", {
        configurable: true,
        value: vi.fn().mockReturnValue(true),
    })
    runAcousticIndices.mockResolvedValue({
        data: { queued: [{ queue_id: 9 }], failed: [] },
    })
    pollAnalysisQueues.mockResolvedValue({
        completed: [{
            queue_id: 9,
            completed: 1,
            message: "Frequency of maximum energy: 609",
        }],
        failed: [],
    })
})

function renderPanel(onProcessingChange = vi.fn()) {
    const rendered = render(
        <AcousticAnalysisStudioPanel
            mediaId={7}
            projectId={3}
            selection={selection}
            isFullTimeWindow={false}
            channel="left"
            onBack={vi.fn()}
            onProcessingChange={onProcessingChange}
        />,
    )
    return { ...rendered, onProcessingChange }
}

async function runMaximumFrequencyAnalysis() {
    fireEvent.click(screen.getByRole("radio", { name: "Frequency of Maximum Energy" }))
    fireEvent.click(screen.getByRole("button", { name: "Run" }))
    await waitFor(() => expect(pollAnalysisQueues).toHaveBeenCalled())
}

describe("AcousticAnalysisStudioPanel maximum frequency", () => {
    it("uses the historical NumPy contract and displays and copies the integer result", async () => {
        renderPanel()

        expect(screen.getByText("Return the maximum of an array or maximum along an axis.")).toBeInTheDocument()
        expect(screen.getByTitle("Frequency of Maximum Energy documentation")).toHaveAttribute(
            "href",
            "https://numpy.org/doc/stable/reference/generated/numpy.max.html",
        )
        expect(screen.queryByText("min_distance")).not.toBeInTheDocument()
        expect(screen.queryByText("threshold_abs (dB)")).not.toBeInTheDocument()

        await runMaximumFrequencyAnalysis()

        expect(await screen.findByText("Frequency of maximum energy: 609 Hz")).toBeInTheDocument()
        expect(navigator.clipboard.writeText).toHaveBeenCalledWith("609")
        expect(runAcousticIndices).toHaveBeenCalledWith(expect.objectContaining({
            indices: [{ analysis_type: "max_frequency", params: {} }],
        }))
    })

    it("falls back to legacy copy when the HTTPS clipboard API rejects", async () => {
        vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error("Not allowed"))
        renderPanel()

        await runMaximumFrequencyAnalysis()

        await waitFor(() => expect(document.execCommand).toHaveBeenCalledWith("copy"))
        expect(document.querySelector("textarea")).toBeNull()
    })

    it("uses legacy copy directly on HTTP", async () => {
        Object.defineProperty(window, "isSecureContext", {
            configurable: true,
            value: false,
        })
        renderPanel()

        await runMaximumFrequencyAnalysis()

        await waitFor(() => expect(document.execCommand).toHaveBeenCalledWith("copy"))
        expect(navigator.clipboard.writeText).not.toHaveBeenCalled()
        expect(document.querySelector("textarea")).toBeNull()
    })

    it("locks controls while polling and aborts and unlocks on unmount", async () => {
        let pollingSignal: AbortSignal | undefined
        pollAnalysisQueues.mockImplementation((_queueIds: number[], signal: AbortSignal) => {
            pollingSignal = signal
            return new Promise(() => undefined)
        })
        const { unmount, onProcessingChange } = renderPanel()

        fireEvent.click(screen.getByRole("radio", { name: "Frequency of Maximum Energy" }))
        fireEvent.click(screen.getByRole("button", { name: "Run" }))
        await waitFor(() => expect(pollAnalysisQueues).toHaveBeenCalled())

        expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
        expect(screen.getByRole("radio", { name: "Frequency of Maximum Energy" })).toBeDisabled()
        expect(onProcessingChange).toHaveBeenCalledWith(true)

        unmount()

        expect(pollingSignal?.aborted).toBe(true)
        expect(onProcessingChange).toHaveBeenLastCalledWith(false)
    })
})
