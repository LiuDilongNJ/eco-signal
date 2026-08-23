import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { useProjectStore } from "../../stores/useProjectStore"
import { DataPageLayout, type TableState } from "./DataPageLayout"

function addOverlayRoot() {
    const overlay = document.createElement("div")
    overlay.id = APP_OVERLAY_ROOT_ID
    document.body.append(overlay)
    return overlay
}

describe("DataPageLayout collection context", () => {
    afterEach(() => {
        act(() => {
            useProjectStore.setState({
                currentProjectId: null,
                currentCollectionId: null,
            })
        })
    })

    it("requests table data again when the selected collection changes", () => {
        useProjectStore.setState({
            currentProjectId: 1,
            currentCollectionId: 10,
        })
        const onTableStateChange = vi.fn<(state: TableState) => void>()

        render(
            <DataPageLayout
                title="Collections"
                columns={[{ key: "collection_id", label: "ID", type: "number" }]}
                rows={[]}
                formFields={[]}
                serverSide
                showNavFilter
                onTableStateChange={onTableStateChange}
            />,
        )

        expect(onTableStateChange).toHaveBeenLastCalledWith(
            expect.objectContaining({
                filters: expect.objectContaining({ collection_id: "10" }),
            }),
        )

        act(() => {
            useProjectStore.setState({ currentCollectionId: 11 })
        })

        expect(onTableStateChange).toHaveBeenLastCalledWith(
            expect.objectContaining({
                filters: expect.objectContaining({ collection_id: "11" }),
            }),
        )
    })

    it("passes the selected record name to typed deletion confirmation", async () => {
        const overlay = addOverlayRoot()

        render(
            <DataPageLayout
                title="Projects"
                columns={[
                    { key: "id", label: "ID", type: "number" },
                    { key: "name", label: "Name", type: "text" },
                ]}
                rows={[{ id: 1, name: "Forest Sounds" }]}
                formFields={[]}
                deleteConfirmation={{ entityLabel: "project", nameField: "name" }}
            />,
        )

        const checkboxes = screen.getAllByRole("checkbox")
        await userEvent.click(checkboxes[1]!)
        await userEvent.click(screen.getByRole("button", { name: "Delete" }))

        expect(screen.getByText("Delete project", { selector: "h3" })).toBeInTheDocument()
        expect(overlay).toHaveTextContent("Type Forest Sounds to confirm")
        expect(overlay.querySelector("input")).toBeInTheDocument()
        overlay.remove()
    })

    it("disables protected deletion when multiple records are selected", async () => {
        render(
            <DataPageLayout
                title="Collections"
                columns={[
                    { key: "id", label: "ID", type: "number" },
                    { key: "name", label: "Name", type: "text" },
                ]}
                rows={[
                    { id: 1, name: "Forest" },
                    { id: 2, name: "Wetland" },
                ]}
                formFields={[]}
                deleteConfirmation={{ entityLabel: "collection", nameField: "name" }}
            />,
        )

        const checkboxes = screen.getAllByRole("checkbox")
        await userEvent.click(checkboxes[1]!)
        await userEvent.click(checkboxes[2]!)

        expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled()
    })

    it("keeps protected deletion disabled when the confirmation name is unavailable", async () => {
        render(
            <DataPageLayout
                title="Projects"
                columns={[{ key: "id", label: "ID", type: "number" }]}
                rows={[{ id: 1, name: "" }]}
                formFields={[]}
                deleteConfirmation={{ entityLabel: "project", nameField: "name" }}
            />,
        )

        const checkboxes = screen.getAllByRole("checkbox")
        await userEvent.click(checkboxes[1]!)

        const deleteButton = screen.getByRole("button", { name: "Delete" })
        expect(deleteButton).toBeDisabled()
        expect(deleteButton).not.toHaveAttribute("title")
        const tooltipTrigger = deleteButton.parentElement
        expect(tooltipTrigger).toHaveClass("data-toolbar-tooltip-trigger")
        await userEvent.hover(tooltipTrigger!)
        expect(await screen.findByText("This record has no name to confirm")).toBeInTheDocument()
    })

    it("selects and highlights a row when clicking its contents", async () => {
        render(
            <DataPageLayout
                title="Projects"
                columns={[
                    { key: "id", label: "ID", type: "number" },
                    { key: "name", label: "Name", type: "text" },
                ]}
                rows={[{ id: 1, name: "Forest Sounds" }]}
                formFields={[]}
            />,
        )

        const row = screen.getByText("Forest Sounds").closest("tr")
        expect(row).not.toBeNull()
        const checkbox = screen.getAllByRole("checkbox")[1]!
        expect(checkbox).not.toBeChecked()

        await userEvent.click(screen.getByText("Forest Sounds"))
        expect(checkbox).toBeChecked()
        expect(row).toHaveClass("dpl-row-selected")

        await userEvent.click(screen.getByText("Forest Sounds"))
        expect(checkbox).not.toBeChecked()
        expect(row).not.toHaveClass("dpl-row-selected")
    })

    it("clears date range inputs when the table is reset", async () => {
        render(
            <DataPageLayout
                title="Projects"
                columns={[{
                    key: "creation_date",
                    label: "Created",
                    type: "date",
                    filterable: true,
                    filterType: "dateRange",
                    filterShowTime: false,
                }]}
                rows={[]}
                formFields={[]}
            />,
        )

        const dateInputs = screen.getAllByRole("textbox")
        expect(dateInputs).toHaveLength(2)
        await userEvent.click(dateInputs[0]!)
        await userEvent.type(dateInputs[0]!, "2026-01-01")
        await userEvent.keyboard("{Enter}")
        await userEvent.click(dateInputs[1]!)
        await userEvent.type(dateInputs[1]!, "2026-01-31")
        await userEvent.keyboard("{Enter}")

        const resetButton = screen.getByRole("button", { name: "Reset" })
        await userEvent.hover(resetButton)
        expect(await screen.findByText("Clear filters, sorting, and selected rows")).toBeInTheDocument()
        await userEvent.click(resetButton)

        expect(dateInputs[0]).toHaveValue("")
        expect(dateInputs[1]).toHaveValue("")
    })

    it("uses Add for mixed pages and Import for import-only pages", async () => {
        const { rerender } = render(
            <MemoryRouter>
                <DataPageLayout
                    title="Queue"
                    columns={[{ key: "id", label: "ID", type: "number" }]}
                    rows={[]}
                    formFields={[]}
                />
            </MemoryRouter>,
        )

        expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument()

        rerender(
            <MemoryRouter>
                <DataPageLayout
                    title="Sites"
                    columns={[{ key: "id", label: "ID", type: "number" }]}
                    rows={[]}
                    formFields={[]}
                    importConfig={{ endpoint: "/v1/sites/imports", resourceKey: "sites" }}
                />
            </MemoryRouter>,
        )

        expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument()
        await userEvent.click(screen.getByRole("button", { name: "Add" }))
        expect(await screen.findByText("Add Site")).toBeInTheDocument()
        expect(screen.getByText("Import Data")).toBeInTheDocument()
        expect(screen.getByText("Import Instructions")).toBeInTheDocument()

        rerender(
            <MemoryRouter>
                <DataPageLayout
                    title="Annotations"
                    columns={[{ key: "id", label: "ID", type: "number" }]}
                    rows={[]}
                    formFields={[]}
                    importConfig={{ endpoint: "/v1/annotations/imports", resourceKey: "annotations", importOnly: true }}
                    hideAdd
                />
            </MemoryRouter>,
        )

        expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument()
        const importButton = screen.getByRole("button", { name: "Import" })
        expect(importButton.querySelector("svg")).toBeInTheDocument()
        await userEvent.click(importButton)
        expect(await screen.findByText("Import Data")).toBeInTheDocument()
        expect(screen.getByText("Import Instructions")).toBeInTheDocument()
    })
})
