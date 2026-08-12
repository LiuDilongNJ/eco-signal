import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

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

        expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled()
        expect(screen.getByRole("button", { name: "Delete" })).toHaveAttribute(
            "title",
            "This record has no name to confirm",
        )
    })
})
