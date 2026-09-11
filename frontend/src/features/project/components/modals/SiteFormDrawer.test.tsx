import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

const geoMocks = vi.hoisted(() => ({
    getGadmOptions: vi.fn(),
    getIhoOptions: vi.fn(),
    getIucnRealms: vi.fn(),
    getIucnBiomes: vi.fn(),
    getIucnFunctionalTypes: vi.fn(),
    getCoordinateMatches: vi.fn(),
}))

vi.mock("@/api/endpoints/geo", () => ({
    geoApi: geoMocks,
}))

import { SiteFormDrawer } from "./SiteFormDrawer"

const TEST_FORM_FIELDS = [
    { key: "name", label: "Name", type: "text" as const, required: true },
    {
        key: "location_method",
        label: "Geographic data entry mode",
        type: "select" as const,
        options: [
            { value: "coordinates", label: "Precise XY geolocation" },
            { value: "administrative", label: "Broad administrative location" },
        ],
    },
    { key: "latitude", label: "Latitude", type: "number" as const },
    { key: "longitude", label: "Longitude", type: "number" as const },
    { key: "topography_m", label: "Topography (m)", type: "number" as const },
    { key: "freshwater_depth_m", label: "Water Depth (m)", type: "number" as const },
    { key: "gadm0_gid", label: "GADM0", type: "select" as const },
    { key: "gadm1_gid", label: "GADM1", type: "select" as const },
    { key: "gadm2_gid", label: "GADM2", type: "select" as const },
    { key: "iho_id", label: "IHO", type: "select" as const },
]

describe("SiteFormDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        geoMocks.getGadmOptions.mockResolvedValue({ data: [], page_info: { total_pages: 1 } })
        geoMocks.getIhoOptions.mockResolvedValue({ data: [], page_info: { total_pages: 1 } })
        geoMocks.getIucnRealms.mockResolvedValue({ data: [], page_info: { total_pages: 1 } })
        geoMocks.getIucnBiomes.mockResolvedValue({ data: [], page_info: { total_pages: 1 } })
        geoMocks.getIucnFunctionalTypes.mockResolvedValue({ data: [], page_info: { total_pages: 1 } })
    })

    it("displays required asterisks only on Latitude and Longitude in coordinates mode, not on GADM0 or IHO", async () => {
        render(
            <MemoryRouter>
                <SiteFormDrawer
                    open
                    mode="add"
                    fields={TEST_FORM_FIELDS}
                    onClose={vi.fn()}
                    onSubmit={vi.fn()}
                />
            </MemoryRouter>,
        )

        // Name is required
        const nameLabel = screen.getByText("Name").closest("label")
        expect(nameLabel).toHaveTextContent("*")

        // In default coordinates mode: Latitude and Longitude must have *
        const latLabel = screen.getByText("Latitude").closest("label")
        expect(latLabel).toHaveTextContent("*")
        const lonLabel = screen.getByText("Longitude").closest("label")
        expect(lonLabel).toHaveTextContent("*")

        // GADM0 and IHO must NOT have *
        const gadm0Label = screen.getByText("GADM0").closest("label")
        expect(gadm0Label?.querySelector(".form-drawer-required-suffix")).toBeNull()
        const ihoLabel = screen.getByText("IHO").closest("label")
        expect(ihoLabel?.querySelector(".form-drawer-required-suffix")).toBeNull()
    })

    it("displays Auto-detected from coordinates before coordinates are entered and does not call geo API with 0", async () => {
        render(
            <MemoryRouter>
                <SiteFormDrawer
                    open
                    mode="add"
                    fields={TEST_FORM_FIELDS}
                    onClose={vi.fn()}
                    onSubmit={vi.fn()}
                />
            </MemoryRouter>,
        )

        const autoDetectPlaceholders = screen.getAllByText("Auto-detected from coordinates")
        expect(autoDetectPlaceholders.length).toBeGreaterThanOrEqual(2)
        expect(geoMocks.getCoordinateMatches).not.toHaveBeenCalled()
    })

    it("clears IHO when coordinate lookup is unmatched (terrestrial coordinates)", async () => {
        geoMocks.getCoordinateMatches.mockResolvedValue({
            code: 200,
            data: {
                gadm: {
                    status: "matched",
                    gadm0: { gid: "FRA", name: "France" },
                    gadm1: { gid: "FRA.11_1", name: "Occitanie" },
                    gadm2: { gid: "FRA.11.4_1", name: "Gard" },
                },
                iho: {
                    status: "unmatched",
                    option: null,
                },
            },
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <SiteFormDrawer
                    open
                    mode="add"
                    fields={TEST_FORM_FIELDS}
                    onClose={vi.fn()}
                    onSubmit={vi.fn()}
                />
            </MemoryRouter>,
        )

        const latInput = screen.getByRole("spinbutton", { name: /latitude/i })
        const lonInput = screen.getByRole("spinbutton", { name: /longitude/i })

        await user.type(latInput, "44.1")
        await user.type(lonInput, "3.5")

        await waitFor(() => {
            expect(geoMocks.getCoordinateMatches).toHaveBeenCalledWith(3.5, 44.1, true)
        })

        await waitFor(() => {
            expect(screen.getByText("France")).toBeInTheDocument()
            expect(screen.getByText("Occitanie")).toBeInTheDocument()
            expect(screen.getByText("Gard")).toBeInTheDocument()
        })

        // IHO should stay cleared with the terrestrial placeholder
        expect(screen.getByText("None (terrestrial)")).toBeInTheDocument()
    })
})
