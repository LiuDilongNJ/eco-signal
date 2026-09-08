import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
    getUserPermissionConfig: vi.fn(),
    listAccessRoles: vi.fn(),
    syncUserPermissions: vi.fn(),
}))

vi.mock("../../../../api/endpoints/permissions", () => ({
    permissionsApi: mocks,
}))

import { UserPermissionDrawer } from "./UserPermissionDrawer"

describe("UserPermissionDrawer", () => {
    it("assigns annotation read-own permission at collection scope", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: [],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: [],
                        inherited_permissions: [],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({ data: [{
            code: "custom",
            name: "Custom",
            kind: "access",
            display_order: 1,
            project_permissions: [],
            collection_permissions: [],
        }] })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        await user.click(screen.getByRole("button", { name: "Project One" }))
        const collectionRow = await screen.findByText("Collection One")
        const collectionElement = collectionRow.closest(".upd-collection-row")
        if (!collectionElement) throw new Error("Collection row is missing")
        const icons = collectionElement.querySelectorAll(".upd-icon-item")
        expect(icons).toHaveLength(4)
        const annotationIcon = icons.item(2)
        if (!annotationIcon) throw new Error("Annotation permission icon is missing")

        await user.click(annotationIcon)
        await user.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        if (!payload) throw new Error("Permission payload is missing")
        expect(payload).toMatchObject({
            projects: [{
                project_id: 1,
                collections: [{
                    collection_id: 10,
                    stored_permissions: ["annotation:read_own"],
                    role: "custom",
                }],
            }],
        })
    })
})
