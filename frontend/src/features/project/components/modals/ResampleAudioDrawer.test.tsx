import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { mediaApi } from "@/api/endpoints/media"
import { ResampleAudioDrawer } from "./ResampleAudioDrawer"

type ResamplingApiResponse = Awaited<ReturnType<typeof mediaApi.createAudioResamplingJob>>

vi.mock("@/api/endpoints/media", () => ({
    mediaApi: {
        createAudioResamplingJob: vi.fn(),
    },
}))

function addOverlayRoot() {
    const overlay = document.createElement("div")
    overlay.id = APP_OVERLAY_ROOT_ID
    document.body.append(overlay)
    return overlay
}

function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe("ResampleAudioDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    afterEach(() => {
        document.getElementById(APP_OVERLAY_ROOT_ID)?.remove()
    })

    it("displays warning alert and confirm message when annotations exceed the new max frequency", async () => {
        const overlay = addOverlayRoot()
        const onClose = vi.fn()
        const onSubmitted = vi.fn()

        vi.mocked(mediaApi.createAudioResamplingJob).mockResolvedValue({
            code: 200,
            message: "Audio resampling preview completed",
            data: {
                queue_id: null,
                accepted_media_ids: [1, 2],
                rejected: [],
                annotation_impact: {
                    max_frequency_hz: 8000,
                    removed_annotation_count: 1,
                    clipped_annotation_count: 2,
                    affected_media_count: 2,
                },
            },
        } as ResamplingApiResponse)

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1, 2]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    onClose={onClose}
                    onSubmitted={onSubmitted}
                />
            </MemoryRouter>,
        )

        expect(screen.getByText("Resample Recordings")).toBeInTheDocument()

        const combobox = screen.getByRole("combobox")
        fireEvent.mouseDown(combobox)

        // Find the 16000 option in document body
        const option = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent?.includes("16000")
            )
            if (!el) throw new Error("16000 option not found")
            return el
        })
        fireEvent.click(option)

        // Wait for preview API to be called with dryRun = true
        await waitFor(() => {
            expect(mediaApi.createAudioResamplingJob).toHaveBeenCalledWith(
                10,
                { media_ids: [1, 2], target_sampling_rate_hz: 16000 },
                true,
            )
        })

        // Check warning alert
        await screen.findByText("Annotations will be adjusted")
        expect(document.querySelector(".resample-audio-warning-alert__desc")).toHaveTextContent(
            /3 affected annotations on 2 recordings/i,
        )
        expect(
            await screen.findByText(/1 annotation entirely above 8000 Hz will be permanently removed/i),
        ).toBeInTheDocument()
        expect(
            screen.getByText(/2 overlapping annotations will be kept and capped at 8000 Hz/i),
        ).toBeInTheDocument()

        // Click resample button to open ConfirmDialog
        const resampleButtons = screen.getAllByRole("button", { name: "Resample" })
        fireEvent.click(resampleButtons[0]!)

        // Verify confirm dialog warning message
        expect(
            await screen.findAllByText(/1 annotation entirely above 8000 Hz will be permanently removed.*2 overlapping annotations will be kept and capped at 8000 Hz/i),
        ).toHaveLength(2)

        expect(overlay).toBeInTheDocument()
    })

    it("shows permanent removal without a clipping warning when only removals are affected", async () => {
        addOverlayRoot()
        vi.mocked(mediaApi.createAudioResamplingJob).mockResolvedValue({
            code: 200,
            message: "Audio resampling preview completed",
            data: {
                queue_id: null,
                accepted_media_ids: [1],
                rejected: [],
                annotation_impact: {
                    max_frequency_hz: 8000,
                    removed_annotation_count: 2,
                    clipped_annotation_count: 0,
                    affected_media_count: 1,
                },
            },
        } as ResamplingApiResponse)

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    onClose={vi.fn()}
                    onSubmitted={vi.fn()}
                />
            </MemoryRouter>,
        )

        fireEvent.mouseDown(screen.getByRole("combobox"))
        const option = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent?.includes("16000"),
            )
            if (!el) throw new Error("16000 option not found")
            return el
        })
        fireEvent.click(option)

        expect(await screen.findByText(/2 annotations entirely above 8000 Hz will be permanently removed/i)).toBeInTheDocument()
        expect(screen.queryByText(/overlapping annotation/i)).not.toBeInTheDocument()

        await userEvent.click(screen.getByRole("button", { name: "Resample" }))
        expect(
            await screen.findAllByText(/2 annotations entirely above 8000 Hz will be permanently removed/i),
        ).toHaveLength(2)
    })

    it("hides rates that the selected audio codecs cannot encode", async () => {
        addOverlayRoot()

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    selectedAudioCodecs={["opus"]}
                    onClose={vi.fn()}
                    onSubmitted={vi.fn()}
                />
            </MemoryRouter>,
        )

        fireEvent.mouseDown(screen.getByRole("combobox"))

        await waitFor(() => {
            expect(screen.getByText("24000")).toBeInTheDocument()
        })
        expect(screen.queryByText("44100")).not.toBeInTheDocument()
        expect(screen.queryByText("22050")).not.toBeInTheDocument()
    })

    it("blocks resampling when the annotation preview fails and retries it", async () => {
        addOverlayRoot()
        vi.mocked(mediaApi.createAudioResamplingJob)
            .mockRejectedValueOnce(new Error("preview unavailable"))
            .mockResolvedValueOnce({
                code: 200,
                message: "Audio resampling preview completed",
                data: {
                    queue_id: null,
                    accepted_media_ids: [1],
                    rejected: [],
                    annotation_impact: {
                        max_frequency_hz: 8000,
                        removed_annotation_count: 0,
                        clipped_annotation_count: 0,
                        affected_media_count: 0,
                    },
                },
            } as ResamplingApiResponse)

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    onClose={vi.fn()}
                    onSubmitted={vi.fn()}
                />
            </MemoryRouter>,
        )

        fireEvent.mouseDown(screen.getByRole("combobox"))
        const option = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent?.includes("16000"),
            )
            if (!el) throw new Error("16000 option not found")
            return el
        })
        fireEvent.click(option)

        expect(await screen.findByText("Annotation preview failed")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Resample" })).toBeDisabled()

        await userEvent.click(screen.getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(mediaApi.createAudioResamplingJob).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(screen.getByRole("button", { name: "Resample" })).toBeEnabled())
    })

    it("keeps the annotation warning hidden when the preview has no impact", async () => {
        addOverlayRoot()
        vi.mocked(mediaApi.createAudioResamplingJob).mockResolvedValue({
            code: 200,
            message: "Audio resampling preview completed",
            data: {
                queue_id: null,
                accepted_media_ids: [1],
                rejected: [],
                annotation_impact: {
                    max_frequency_hz: 8000,
                    removed_annotation_count: 0,
                    clipped_annotation_count: 0,
                    affected_media_count: 0,
                },
            },
        } as ResamplingApiResponse)

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    onClose={vi.fn()}
                    onSubmitted={vi.fn()}
                />
            </MemoryRouter>,
        )

        fireEvent.mouseDown(screen.getByRole("combobox"))
        const option = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent?.includes("16000"),
            )
            if (!el) throw new Error("16000 option not found")
            return el
        })
        fireEvent.click(option)

        await waitFor(() => expect(screen.getByRole("button", { name: "Resample" })).toBeEnabled())
        expect(screen.queryByText("Annotations will be adjusted")).not.toBeInTheDocument()
    })

    it("ignores a stale preview response after the target rate changes", async () => {
        addOverlayRoot()
        const firstPreview = deferred<ResamplingApiResponse>()
        vi.mocked(mediaApi.createAudioResamplingJob)
            .mockImplementationOnce(() => firstPreview.promise)
            .mockResolvedValueOnce({
                code: 200,
                message: "Audio resampling preview completed",
                data: {
                    queue_id: null,
                    accepted_media_ids: [1],
                    rejected: [],
                    annotation_impact: {
                        max_frequency_hz: 4000,
                        removed_annotation_count: 0,
                        clipped_annotation_count: 1,
                        affected_media_count: 1,
                    },
                },
            } as ResamplingApiResponse)

        render(
            <MemoryRouter>
                <ResampleAudioDrawer
                    open
                    mediaIds={[1]}
                    projectId={10}
                    maxTargetSamplingRate={48000}
                    onClose={vi.fn()}
                    onSubmitted={vi.fn()}
                />
            </MemoryRouter>,
        )

        fireEvent.mouseDown(screen.getByRole("combobox"))
        const firstOption = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent === "16000",
            )
            if (!el) throw new Error("16000 option not found")
            return el
        })
        fireEvent.click(firstOption)
        await waitFor(() => expect(mediaApi.createAudioResamplingJob).toHaveBeenCalledTimes(1))

        fireEvent.mouseDown(screen.getByRole("combobox"))
        const secondOption = await waitFor(() => {
            const el = Array.from(document.querySelectorAll(".ant-select-item-option-content")).find(
                (node) => node.textContent === "8000",
            )
            if (!el) throw new Error("8000 option not found")
            return el
        })
        fireEvent.click(secondOption)

        expect(await screen.findByText(/1 overlapping annotation will be kept and capped at 4000 Hz/i)).toBeInTheDocument()
        firstPreview.resolve({
            code: 200,
            message: "Audio resampling preview completed",
            data: {
                queue_id: null,
                accepted_media_ids: [1],
                rejected: [],
                annotation_impact: {
                    max_frequency_hz: 8000,
                    removed_annotation_count: 9,
                    clipped_annotation_count: 0,
                    affected_media_count: 1,
                },
            },
        })

        await waitFor(() => {
            expect(screen.queryByText(/9 annotations entirely above 8000 Hz/i)).not.toBeInTheDocument()
            expect(screen.getByText(/1 overlapping annotation will be kept and capped at 4000 Hz/i)).toBeInTheDocument()
        })
    })
})
