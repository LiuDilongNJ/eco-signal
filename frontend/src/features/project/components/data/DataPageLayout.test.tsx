import { act, render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useProjectStore } from "../../stores/useProjectStore"
import { DataPageLayout, type TableState } from "./DataPageLayout"

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
})
