import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { api, cameraOptions, dataPageProps, fetchLensListAll, toast } = vi.hoisted(() => ({
    api: {
        cameras: { get: vi.fn() },
        microphones: { getOptions: vi.fn() },
        recorders: { get: vi.fn(), getOptions: vi.fn() },
        sensors: {
            create: vi.fn(),
            delete: vi.fn(),
            exportCsv: vi.fn(),
            get: vi.fn(),
            list: vi.fn(),
            update: vi.fn(),
        },
    },
    cameraOptions: {
        loadFirst: vi.fn().mockResolvedValue(undefined),
        loadNext: vi.fn(),
        loading: false,
        options: [] as Array<{ value: number; label: string }>,
        reset: vi.fn(),
        search: vi.fn(),
        setCurrentOption: vi.fn(),
    },
    dataPageProps: { current: null as Record<string, unknown> | null },
    fetchLensListAll: vi.fn(),
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

vi.mock("../../../../api/endpoints/cameras", () => ({ camerasApi: api.cameras }))
vi.mock("../../../../api/endpoints/lenses", () => ({ fetchLensListAll }))
vi.mock("../../../../api/endpoints/microphones", () => ({ microphonesApi: api.microphones }))
vi.mock("../../../../api/endpoints/recorders", () => ({ recordersApi: api.recorders }))
vi.mock("../../../../api/endpoints/sensors", () => ({ sensorsApi: api.sensors }))

vi.mock("@/hooks/usePagedSelectOptions", () => ({
    isSelectScrollNearBottom: () => false,
    usePagedSelectOptions: () => cameraOptions,
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
        return <div data-testid="sensors-table">Sensors table</div>
    },
}))

vi.mock("@/components/ui", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/components/ui")>()
    const TestDrawer = ({
        children,
        extra,
        open,
        title,
    }: {
        children: ReactNode
        extra: ReactNode
        open: boolean
        title: ReactNode
    }) => open ? <section role="dialog">{title}{extra}{children}</section> : null

    return {
        ...actual,
        CustomScrollArea: ({ children }: { children: ReactNode }) => <div>{children}</div>,
        FormDrawer: TestDrawer,
    }
})

import { SensorSettingsTab } from "./SensorSettingsTab"

beforeEach(() => {
    vi.clearAllMocks()
    dataPageProps.current = null
    api.recorders.getOptions.mockResolvedValue({
        code: 0,
        message: "ok",
        data: [
            { recorder_id: 1, name: "Recorder A" },
            { recorder_id: 2, name: "Recorder B" },
        ],
    })
    api.microphones.getOptions.mockResolvedValue({
        code: 0,
        message: "ok",
        data: [{ microphone_id: 10, name: "Microphone A" }],
    })
    fetchLensListAll.mockResolvedValue({ data: [], errorMessage: null })
    api.cameras.get.mockResolvedValue({
        code: 0,
        message: "ok",
        data: { camera_id: 20, uuid: "camera-20", name: "Camera A", lenses: [] },
    })
    api.sensors.get.mockResolvedValue({
        code: 0,
        message: "ok",
        data: {
            sensor_id: 7,
            uuid: "sensor-7",
            name: "Audio Sensor",
            sensor_type: "audio",
            recorder_id: 1,
            recorder_name: "Recorder A",
            microphone_id: 10,
            microphone_name: "Microphone A",
            description: null,
            creation_date: "2026-08-04 09:00:00",
        },
    })
})

describe("SensorSettingsTab form", () => {
    it("loads the sensor and refreshes microphones after changing recorder", async () => {
        render(<SensorSettingsTab />)

        await act(async () => {
            const edit = dataPageProps.current?.onEditCustom as (keys: unknown[]) => Promise<void>
            await edit([7])
        })

        expect(api.sensors.get).toHaveBeenCalledWith(7)
        expect(screen.queryByRole("switch")).not.toBeInTheDocument()

        fireEvent.mouseDown(screen.getByLabelText(/Recorder/))
        fireEvent.click(await screen.findByText("Recorder B"))

        await waitFor(() => {
            expect(screen.queryByText("Default combination")).not.toBeInTheDocument()
        })
        expect(api.microphones.getOptions).toHaveBeenLastCalledWith({ recorder_id: 2 })
    })
})
