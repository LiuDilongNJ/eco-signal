import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { mediaApi } from "@/api/endpoints/media"
import { ResampleAudioDrawer } from "./ResampleAudioDrawer"

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

describe("ResampleAudioDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it("displays warning alert and confirm message when annotations exceed the new max frequency", async () => {
        const overlay = addOverlayRoot()
        const onClose = vi.fn()
        const onSubmitted = vi.fn()

        vi.mocked(mediaApi.createAudioResamplingJob).mockResolvedValue({
            data: {
                queue_id: null,
                accepted_media_ids: [1, 2],
                rejected: [],
                affected_annotation_count: 3,
                affected_media_count: 2,
            },
        } as any)

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
        expect(
            await screen.findByText(/exceeds? the new maximum frequency of 8000 Hz and will be permanently removed/i),
        ).toBeInTheDocument()

        // Click resample button to open ConfirmDialog
        const resampleButtons = screen.getAllByRole("button", { name: "Resample" })
        fireEvent.click(resampleButtons[0]!)

        // Verify confirm dialog warning message
        expect(
            await screen.findByText(/Warning: 3 annotations exceed the new maximum frequency of 8000 Hz and will be permanently removed/i),
        ).toBeInTheDocument()

        overlay.remove()
    })
})
