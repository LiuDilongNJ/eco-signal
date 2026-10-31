import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { AudioMetadataDrawer } from "./AudioMetadataDrawer"

const { getAudioMetadata, downloadAudioMetadata, downloadFile } = vi.hoisted(() => ({
    getAudioMetadata: vi.fn(),
    downloadAudioMetadata: vi.fn(),
    downloadFile: vi.fn(),
}))
vi.mock("@/api/endpoints/media", () => ({ mediaApi: { getAudioMetadata, downloadAudioMetadata } }))
vi.mock("@/utils/download", () => ({ downloadFile }))

afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    getAudioMetadata.mockResolvedValue({
        media_id: 201, schema_version: 1,
        source: { filename: "source.wav" },
        stored: { size_b: 153604158, codec: "flac" }, tags: {}, warnings: [],
    })
})

it("shows the exact file size with an explicit byte label", async () => {
    render(<MemoryRouter><AudioMetadataDrawer open mediaId={201} projectId={1} onClose={vi.fn()} /></MemoryRouter>)
    expect(await screen.findByText("Size (Bytes)")).toBeVisible()
    expect(screen.getByText("153604158")).toBeVisible()
    expect(screen.queryByText("size_b")).not.toBeInTheDocument()
    expect(screen.getByText("codec")).toBeVisible()
})

it("downloads the original metadata response without renaming its keys", async () => {
    const file = new Blob([JSON.stringify({ stored: { size_b: 153604158 } })], { type: "application/json" })
    downloadAudioMetadata.mockResolvedValue(file)
    render(<MemoryRouter><AudioMetadataDrawer open mediaId={201} projectId={1} onClose={vi.fn()} /></MemoryRouter>)
    await screen.findByText("Size (Bytes)")
    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }))
    await waitFor(() => expect(downloadFile).toHaveBeenCalledWith(file))
    expect(downloadAudioMetadata).toHaveBeenCalledWith(201, 1)
})
