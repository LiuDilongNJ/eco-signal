import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

const { api, dataPageProps, downloadFile, toast } = vi.hoisted(() => ({
    api: {
        list: vi.fn(),
        get: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn(),
        importCsv: vi.fn(),
        exportCsv: vi.fn(),
    },
    dataPageProps: { current: null as Record<string, unknown> | null },
    downloadFile: vi.fn(),
    toast: {
        error: vi.fn(),
        success: vi.fn(),
        warning: vi.fn(),
        loading: vi.fn(() => vi.fn()),
    },
}))

vi.mock("antd", async (importOriginal) => {
    const actual = await importOriginal<typeof import("antd")>()
    return { ...actual, message: toast }
})

vi.mock("../../../../api/endpoints/soundClassifications", () => ({
    soundClassificationsApi: api,
}))

vi.mock("@/store/useAppStore", () => ({
    useAppStore: (selector: (state: { effectiveTheme: string }) => unknown) => selector({ effectiveTheme: "light" }),
}))

vi.mock("../../../project/hooks/useAntdBrandConfig", () => ({
    useAppDefaultAntdBrandConfig: () => ({}),
}))

vi.mock("../../../project/components/data/DataPageLayout", () => ({
    DataPageLayout: (props: Record<string, unknown>) => {
        dataPageProps.current = props
        return <div data-testid="sounds-table">Sounds table</div>
    },
}))

vi.mock("@/components/ui", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/components/ui")>()
    const TestDrawer = ({ open, title, extra, children }: { open: boolean; title: ReactNode; extra: ReactNode; children: ReactNode }) => (
        open ? <section role="dialog">{title}{extra}{children}</section> : null
    )
    return {
        ...actual,
        CustomScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
        DetailDrawer: TestDrawer,
        FormDrawer: TestDrawer,
    }
})

vi.mock("@/utils/download", () => ({ downloadFile }))

import { SoundSettingsTab } from "./SoundSettingsTab"
import { ApiError } from "../../../../api/client"

beforeAll(() => {
    Object.defineProperty(window, "matchMedia", {
        writable: true,
        value: vi.fn().mockImplementation(() => ({
            matches: false,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        })),
    })
})

beforeEach(() => {
    vi.clearAllMocks()
    dataPageProps.current = null
    api.create.mockResolvedValue({ code: 0, message: "ok", data: {} })
    api.get.mockResolvedValue({
        code: 0,
        message: "ok",
        data: { sound_id: 7, soundscape_component: "geophony", sound_type: "rain" },
    })
    api.importCsv.mockResolvedValue({
        code: 0,
        message: "ok",
        data: { total: 1, succeeded: 1, skipped: 0, failed: 0, committed: true, rows: [], global_errors: [] },
    })
})

function menuAction(index: number) {
    const items = dataPageProps.current?.addDropdownItems as Array<{ onClick?: () => void }>
    act(() => items[index]?.onClick?.())
}

describe("SoundSettingsTab interactions", () => {
    it("configures the standard table and creates a normalized sound", async () => {
        const { container } = render(<SoundSettingsTab />)

        expect(screen.getByTestId("sounds-table")).toBeInTheDocument()
        expect(dataPageProps.current).toMatchObject({
            title: "Sounds",
            hideView: true,
            serverSide: true,
            defaultSortKey: "sound_id",
        })
        expect((dataPageProps.current?.addDropdownItems as Array<{ label: string }>).map((item) => item.label)).toEqual([
            "New Sound",
            "Import CSV",
            "CSV Instructions",
        ])

        menuAction(0)
        expect(await screen.findByText("New Sound")).toBeInTheDocument()
        expect(container.querySelector(".form-drawer-required-suffix")).toHaveTextContent("*")

        const componentInput = screen.getByLabelText(/Soundscape Component/)
        const typeInput = screen.getByLabelText("Sound Type")
        expect(componentInput).not.toHaveAttribute("placeholder")
        expect(typeInput).not.toHaveAttribute("placeholder")

        fireEvent.change(componentInput, { target: { value: "  biophony  " } })
        fireEvent.change(typeInput, { target: { value: "   " } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(api.create).toHaveBeenCalledWith({
                soundscape_component: "biophony",
                sound_type: null,
            })
        })
    })

    it("loads current values before editing", async () => {
        render(<SoundSettingsTab />)

        await act(async () => {
            const edit = dataPageProps.current?.onEditCustom as (keys: unknown[]) => Promise<void>
            await edit([7])
        })

        expect(api.get).toHaveBeenCalledWith(7)
        expect(screen.getByLabelText(/Soundscape Component/)).toHaveValue("geophony")
        expect(screen.getByLabelText("Sound Type")).toHaveValue("rain")
        expect(screen.getByLabelText(/Soundscape Component/)).not.toHaveAttribute("placeholder")
        expect(screen.getByLabelText("Sound Type")).not.toHaveAttribute("placeholder")
    })

    it("opens separate CSV instructions with the exact format guidance and template", () => {
        render(<SoundSettingsTab />)

        menuAction(2)

        expect(screen.getByText("CSV Upload Instructions")).toBeInTheDocument()
        expect(screen.getByText("soundscape_component")).toBeInTheDocument()
        expect(screen.queryByText(/Duplicate rows are preserved/)).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "template CSV file" }))
        expect(downloadFile).toHaveBeenCalledWith(
            expect.objectContaining({ blob: expect.any(Blob) }),
            "sounds_template.csv",
        )
        expect(screen.queryByText("Choose or drop a CSV file here")).not.toBeInTheDocument()
    })

    it("opens the hidden CSV chooser directly from the Add menu", () => {
        const { container } = render(<SoundSettingsTab />)
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')
        expect(input).not.toBeNull()
        const click = vi.spyOn(input!, "click")

        menuAction(1)

        expect(click).toHaveBeenCalledOnce()
        expect(screen.queryByText("Import Sounds")).not.toBeInTheDocument()
    })

    it("rejects a non-CSV file before upload", async () => {
        const { container } = render(<SoundSettingsTab />)
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')
        expect(input).not.toBeNull()

        fireEvent.change(input!, {
            target: { files: [new File(["not csv"], "sounds.txt", { type: "text/plain" })] },
        })

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Select a CSV file"))
        expect(api.importCsv).not.toHaveBeenCalled()
    })

    it("disables Add while importing and allows the same CSV to be selected again", async () => {
        let finishImport: ((value: unknown) => void) | undefined
        api.importCsv.mockImplementationOnce(() => new Promise((resolve) => {
            finishImport = resolve
        }))
        const { container } = render(<SoundSettingsTab />)
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
        const file = new File([
            "soundscape_component,sound_type\nbiophony,bird\n",
        ], "sounds.csv", { type: "text/csv" })

        fireEvent.change(input, { target: { files: [file] } })
        await waitFor(() => expect(api.importCsv).toHaveBeenCalledWith(file))
        expect(dataPageProps.current?.addDisabled).toBe(true)

        await act(async () => {
            finishImport?.({
                code: 0,
                message: "ok",
                data: { total: 1, succeeded: 1, skipped: 0, failed: 0, committed: true, rows: [], global_errors: [] },
            })
        })
        await waitFor(() => expect(dataPageProps.current?.addDisabled).toBe(false))
        expect(toast.success).toHaveBeenCalledWith("Imported 1 of 1 row(s)")

        fireEvent.change(input, { target: { files: [file] } })
        await waitFor(() => expect(api.importCsv).toHaveBeenCalledTimes(2))
    })

    it("shows the original backend CSV validation error", async () => {
        api.importCsv.mockRejectedValueOnce(new ApiError(422, "Unprocessable Entity", {
            message: "CSV row 3: soundscape_component is required",
        }))
        const { container } = render(<SoundSettingsTab />)
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')!

        fireEvent.change(input, {
            target: {
                files: [new File(["bad"], "sounds.csv", { type: "text/csv" })],
            },
        })

        await waitFor(() => {
            expect(toast.error).toHaveBeenCalledWith("CSV row 3: soundscape_component is required")
        })
    })

    it("keeps the edit drawer open and shows the backend conflict message", async () => {
        api.update.mockRejectedValueOnce(new ApiError(409, "Conflict", {
            message: "Sound classification is referenced by annotation records",
        }))
        render(<SoundSettingsTab />)

        await act(async () => {
            const edit = dataPageProps.current?.onEditCustom as (keys: unknown[]) => Promise<void>
            await edit([7])
        })
        fireEvent.change(screen.getByDisplayValue("rain"), { target: { value: "storm" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(toast.error).toHaveBeenCalledWith("Sound classification is referenced by annotation records")
        })
        expect(screen.getByText("Edit Sound")).toBeInTheDocument()
    })

    it("reports partial batch-delete failures and refreshes the current table", async () => {
        api.delete
            .mockResolvedValueOnce({ code: 0, message: "ok", data: null })
            .mockRejectedValueOnce(new ApiError(409, "Conflict", { message: "Sound #8 is referenced" }))
        render(<SoundSettingsTab />)
        const state = {
            page: 1,
            pageSize: 10,
            searchQuery: "",
            filters: {},
            sortKey: "sound_id",
            sortDir: "asc",
        }

        act(() => {
            const tableChange = dataPageProps.current?.onTableStateChange as (value: typeof state) => void
            tableChange(state)
        })
        await act(async () => {
            const remove = dataPageProps.current?.onDeleteCustom as (keys: unknown[]) => Promise<void>
            await remove([7, 8])
        })

        expect(api.delete).toHaveBeenNthCalledWith(1, 7)
        expect(api.delete).toHaveBeenNthCalledWith(2, 8)
        expect(toast.success).toHaveBeenCalledWith("Deleted 1 record(s)")
        expect(toast.error).toHaveBeenCalledWith("Sound #8 is referenced")
    })

    it("shows the administrator permission state on a 403 list response", async () => {
        api.list.mockRejectedValueOnce(new ApiError(403, "Forbidden"))
        render(<SoundSettingsTab />)
        const state = {
            page: 1,
            pageSize: 10,
            searchQuery: "",
            filters: {},
            sortKey: "sound_id",
            sortDir: "asc",
        }

        act(() => {
            const tableChange = dataPageProps.current?.onTableStateChange as (value: typeof state) => void
            tableChange(state)
        })

        expect(await screen.findByText(/admin required/i, {}, { timeout: 1000 })).toBeInTheDocument()
    })
})
