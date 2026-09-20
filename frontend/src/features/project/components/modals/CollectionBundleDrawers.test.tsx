import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import {
    collectionBundleExportsApi,
    type CollectionBundleExport,
} from "@/api/endpoints/collectionBundleExports"
import { dataImportsApi, type DataImportStatus } from "@/api/endpoints/dataImports"
import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { ExportBundleDrawer, ImportBundleDrawer } from "./CollectionBundleDrawers"

function addOverlayRoot() {
    const overlay = document.createElement("div")
    overlay.id = APP_OVERLAY_ROOT_ID
    document.body.append(overlay)
    return overlay
}

vi.mock("@/api/endpoints/dataImports", () => ({
    dataImportsApi: {
        create: vi.fn(),
        uploadChunk: vi.fn(),
        getStatus: vi.fn(),
    },
}))

vi.mock("@/api/endpoints/collectionBundleExports", () => ({
    collectionBundleExportsApi: {
        create: vi.fn(),
        list: vi.fn(),
        get: vi.fn(),
        download: vi.fn(),
    },
}))

describe("ImportCollectionBundleDrawer verification & skip alerts", () => {
    it("renders drawer and file selector", () => {
        const overlay = addOverlayRoot()
        render(
            <MemoryRouter>
                <ImportBundleDrawer
                    open
                    projectId={1}
                    onClose={vi.fn()}
                    onImported={vi.fn()}
                />
            </MemoryRouter>
        )

        expect(screen.getByText("Import Bundle")).toBeInTheDocument()
        expect(screen.getByText("Select ZIP Bundle")).toBeInTheDocument()
        overlay.remove()
    })

    it("cancels import when Cancel is clicked on confirmation dialog", async () => {
        const overlay = addOverlayRoot()
        vi.mocked(dataImportsApi.create).mockClear()

        render(
            <MemoryRouter>
                <ImportBundleDrawer
                    open
                    projectId={1}
                    onClose={vi.fn()}
                    onImported={vi.fn()}
                />
            </MemoryRouter>
        )

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const file = new File(["test-zip-content"], "test-bundle.zip", {
            type: "application/zip",
        })
        fireEvent.change(fileInput, { target: { files: [file] } })

        const importButton = screen.getByRole("button", { name: /^import$/i })
        await userEvent.click(importButton)

        // Confirmation dialog appears
        expect(screen.getByText("Import Collection Bundle?")).toBeInTheDocument()
        expect(screen.getByText(/If this bundle is from an external or unsigned source/i)).toBeInTheDocument()

        // Click Cancel
        const cancelButton = screen.getByRole("button", { name: "Cancel" })
        await userEvent.click(cancelButton)

        expect(dataImportsApi.create).not.toHaveBeenCalled()
        overlay.remove()
    })

    it("displays 'Federation Verified' when signature_verified is true after confirmation", async () => {
        const overlay = addOverlayRoot()
        const mockStatus: DataImportStatus = {
            batch_id: "batch-1",
            project_id: 1,
            uploader_id: 1,
            file_upload_id: 1,
            status: "completed",
            error: null,
            summary_json: {
                project_id: 1,
                collection_id: 10,
                collection_uuid: "col-uuid-1",
                signature_verified: true,
                checksum_verified: true,
                created_counts: {
                    collections: 1,
                    project_links: 1,
                    sites: 1,
                    site_links: 1,
                    media: 2,
                    audio: 2,
                    photos: 0,
                    media_files: 2,
                    media_links: 2,
                    previews: 2,
                    annotations: 0,
                    reviews: 0,
                    labels: 0,
                    label_links: 0,
                },
                skipped_counts: {
                    collections: 0,
                    project_links: 0,
                    sites: 0,
                    site_links: 0,
                    media: 0,
                    audio: 0,
                    photos: 0,
                    media_files: 0,
                    media_links: 0,
                    previews: 0,
                    annotations: 0,
                    reviews: 0,
                    labels: 0,
                    label_links: 0,
                },
                conflicts: [],
                warnings: [],
            },
            queue_id: 123,
            cleanup_after: null,
            creation_date: "2026-09-20 12:00:00",
            update_date: "2026-09-20 12:00:00",
        }

        vi.mocked(dataImportsApi.create).mockResolvedValueOnce({
            data: { batch_id: "batch-1" },
        } as any)
        vi.mocked(dataImportsApi.uploadChunk).mockResolvedValue({
            data: {},
        } as any)
        vi.mocked(dataImportsApi.getStatus).mockResolvedValueOnce({
            data: mockStatus,
        } as any)

        render(
            <MemoryRouter>
                <ImportBundleDrawer
                    open
                    projectId={1}
                    onClose={vi.fn()}
                    onImported={vi.fn()}
                />
            </MemoryRouter>
        )

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const file = new File(["test-zip-content"], "test-bundle.zip", {
            type: "application/zip",
        })
        fireEvent.change(fileInput, { target: { files: [file] } })

        const importButton = screen.getByRole("button", { name: /^import$/i })
        expect(importButton).toBeEnabled()
        await userEvent.click(importButton)

        // Confirm in dialog
        const confirmButton = screen.getByRole("button", { name: "Confirm & Import" })
        expect(confirmButton).toBeInTheDocument()
        await userEvent.click(confirmButton)

        await waitFor(() => {
            expect(screen.getByText("Federation Verified")).toBeInTheDocument()
        })
        expect(screen.queryByText(/already exist in this database/i)).not.toBeInTheDocument()

        overlay.remove()
    })

    it("displays 'Checksums Verified (Unsigned)' and duplicate skip alert when items already exist", async () => {
        const overlay = addOverlayRoot()
        const mockStatus: DataImportStatus = {
            batch_id: "batch-2",
            project_id: 1,
            uploader_id: 1,
            file_upload_id: 2,
            status: "completed",
            error: null,
            summary_json: {
                project_id: 1,
                collection_id: 10,
                collection_uuid: "col-uuid-1",
                signature_verified: false,
                checksum_verified: true,
                created_counts: {
                    collections: 0,
                    project_links: 0,
                    sites: 0,
                    site_links: 0,
                    media: 0,
                    audio: 0,
                    photos: 0,
                    media_files: 0,
                    media_links: 0,
                    previews: 0,
                    annotations: 0,
                    reviews: 0,
                    labels: 0,
                    label_links: 0,
                },
                skipped_counts: {
                    collections: 1,
                    project_links: 1,
                    sites: 1,
                    site_links: 1,
                    media: 2,
                    audio: 2,
                    photos: 0,
                    media_files: 2,
                    media_links: 2,
                    previews: 0,
                    annotations: 1,
                    reviews: 0,
                    labels: 0,
                    label_links: 0,
                },
                conflicts: [],
                warnings: [
                    {
                        resource_type: "collection",
                        identifier: "col-uuid-1",
                        message: "Collection 'Test' already exists in this database; existing collection was reused.",
                    },
                    {
                        resource_type: "media",
                        identifier: "",
                        message: "2 media item(s) already exist in this database and were skipped to prevent duplicate records.",
                    },
                ],
            },
            queue_id: 124,
            cleanup_after: null,
            creation_date: "2026-09-20 12:05:00",
            update_date: "2026-09-20 12:05:00",
        }

        vi.mocked(dataImportsApi.create).mockResolvedValueOnce({
            data: { batch_id: "batch-2" },
        } as any)
        vi.mocked(dataImportsApi.uploadChunk).mockResolvedValue({
            data: {},
        } as any)
        vi.mocked(dataImportsApi.getStatus).mockResolvedValueOnce({
            data: mockStatus,
        } as any)

        render(
            <MemoryRouter>
                <ImportBundleDrawer
                    open
                    projectId={1}
                    onClose={vi.fn()}
                    onImported={vi.fn()}
                />
            </MemoryRouter>
        )

        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
        const file = new File(["test-zip-content"], "duplicate-bundle.zip", {
            type: "application/zip",
        })
        fireEvent.change(fileInput, { target: { files: [file] } })

        const importButton = screen.getByRole("button", { name: /^import$/i })
        await userEvent.click(importButton)

        const confirmButton = screen.getByRole("button", { name: "Confirm & Import" })
        await userEvent.click(confirmButton)

        await waitFor(() => {
            expect(screen.getByText("Checksums Verified (Unsigned)")).toBeInTheDocument()
        })
        expect(screen.getByText("All bundle items already exist in this database")).toBeInTheDocument()
        expect(
            screen.getByText(/All collections, sites, media, and annotations in this bundle already exist in the target database/i)
        ).toBeInTheDocument()

        overlay.remove()
    })
})

describe("ExportBundleDrawer", () => {
    it("loads and displays recent exports on drawer open", async () => {
        const overlay = addOverlayRoot()
        const mockExports: CollectionBundleExport[] = [
            {
                export_id: "export-uuid-1",
                project_id: 1,
                collection_id: 10,
                queue_id: 88,
                status: "completed",
                filename: "collection-10.zip",
                size_b: 1024 * 1024 * 5,
                counts: { media: 10, sites: 2 },
                warnings: null,
                error: null,
                creation_date: "2026-09-20 10:00:00",
                completion_date: "2026-09-20 10:02:00",
                expires_at: "2026-09-21 10:02:00",
            },
        ]
        vi.mocked(collectionBundleExportsApi.list).mockResolvedValueOnce({
            code: 200,
            message: "Success",
            data: mockExports,
        })

        render(
            <MemoryRouter>
                <ExportBundleDrawer
                    open
                    projectId={1}
                    collection={{ collection_id: 10, name: "Test Collection" }}
                    onClose={vi.fn()}
                />
            </MemoryRouter>
        )

        expect(screen.getByRole("button", { name: "Export Bundle" })).toBeInTheDocument()
        await waitFor(() => {
            expect(screen.getByText("collection-10.zip")).toBeInTheDocument()
        })
        expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument()
        expect(collectionBundleExportsApi.list).toHaveBeenCalledWith(1, 10)

        overlay.remove()
    })

    it("resumes polling when there is an active running/queued export", async () => {
        const overlay = addOverlayRoot()
        const runningExport: CollectionBundleExport = {
            export_id: "export-uuid-running",
            project_id: 1,
            collection_id: 10,
            queue_id: 89,
            status: "queued",
            filename: null,
            size_b: null,
            counts: null,
            warnings: null,
            error: null,
            creation_date: "2026-09-20 10:10:00",
            completion_date: null,
            expires_at: null,
        }
        vi.mocked(collectionBundleExportsApi.list).mockResolvedValueOnce({
            code: 200,
            message: "Success",
            data: [runningExport],
        })
        vi.mocked(collectionBundleExportsApi.get).mockResolvedValueOnce({
            code: 200,
            message: "Success",
            data: {
                ...runningExport,
                status: "completed",
                filename: "completed-bundle.zip",
            },
        })

        render(
            <MemoryRouter>
                <ExportBundleDrawer
                    open
                    projectId={1}
                    collection={{ collection_id: 10, name: "Test Collection" }}
                    onClose={vi.fn()}
                />
            </MemoryRouter>
        )

        await waitFor(() => {
            expect(collectionBundleExportsApi.get).toHaveBeenCalledWith(
                "export-uuid-running",
                expect.any(AbortSignal)
            )
        })

        await waitFor(() => {
            expect(screen.getByText("completed-bundle.zip")).toBeInTheDocument()
        })

        overlay.remove()
    })
})
