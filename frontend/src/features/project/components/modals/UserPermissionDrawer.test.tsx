import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi, beforeEach } from "vitest"

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
    beforeEach(() => {
        vi.clearAllMocks()
    })

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

    it("inherits named project role to all collections and omits redundant collection entries on save", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    assigned_role: "viewer",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        inherited_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        assigned_role: null,
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                {
                    code: "viewer",
                    name: "Viewer",
                    kind: "access",
                    display_order: 1,
                    project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                },
                {
                    code: "custom",
                    name: "Custom",
                    kind: "access",
                    display_order: 2,
                    project_permissions: [],
                    collection_permissions: [],
                },
            ],
        })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        const collectionRow = await screen.findByText("Collection One")
        const collectionElement = collectionRow.closest(".upd-collection-row")
        if (!collectionElement) throw new Error("Collection row is missing")

        // Collection role select should be disabled and show Viewer
        const collectionSelect = collectionElement.querySelector(".ant-select-disabled")
        expect(collectionSelect).not.toBeNull()

        // Checkbox should be checked and disabled
        const disabledCheckbox = collectionElement.querySelector(".upd-checkbox--disabled")
        expect(disabledCheckbox).not.toBeNull()

        // Save and verify payload
        await user.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        expect(payload).toEqual({
            projects: [{
                project_id: 1,
                role: "viewer",
                stored_permissions: [],
                collections: [],
            }],
        })
    })

    it("displays warning icon on custom role for project and collection", async () => {
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
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        await user.click(screen.getByRole("button", { name: "Project One" }))
        await screen.findByText("Collection One")

        const warnings = screen.getAllByLabelText("Custom role warning")
        expect(warnings).toHaveLength(2)
    })

    it("displays divergence indicator 'C' and dashed border when custom collection differs from project", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: ["media:read"],
                    effective_permissions: ["media:read"],
                    assigned_role: "custom",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: ["media:write"],
                        effective_permissions: ["media:write"],
                        inherited_permissions: ["media:read"],
                        assigned_role: "custom",
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                { code: "custom", name: "Custom", kind: "access", display_order: 1, project_permissions: [], collection_permissions: [] },
            ],
        })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        await screen.findByText("Collection One")

        // Markers with 'C' text
        const markers = screen.getAllByText("C")
        expect(markers.length).toBeGreaterThanOrEqual(2)

        const divergentIcons = document.querySelectorAll(".upd-icon-item--divergent")
        expect(divergentIcons.length).toBeGreaterThanOrEqual(2)
    })

    it("allows switching project from named role to custom, making collections editable", async () => {
        mocks.getUserPermissionConfig.mockResolvedValue({
            data: {
                is_admin: false,
                can_manage_admin_role: false,
                projects: [{
                    project_id: 1,
                    project_name: "Project One",
                    can_manage_project: true,
                    stored_permissions: [],
                    effective_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    assigned_role: "viewer",
                    collections: [{
                        project_id: 1,
                        collection_id: 10,
                        collection_name: "Collection One",
                        can_manage_collection: true,
                        stored_permissions: [],
                        effective_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        inherited_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                        assigned_role: null,
                    }],
                }],
            },
        })
        mocks.listAccessRoles.mockResolvedValue({
            data: [
                {
                    code: "viewer",
                    name: "Viewer",
                    kind: "access",
                    display_order: 1,
                    project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
                    collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
                },
                {
                    code: "custom",
                    name: "Custom",
                    kind: "access",
                    display_order: 2,
                    project_permissions: [],
                    collection_permissions: [],
                },
            ],
        })
        mocks.syncUserPermissions.mockResolvedValue({ code: 0, message: "success" })

        const user = userEvent.setup()
        render(
            <MemoryRouter>
                <UserPermissionDrawer open userId={2} onClose={vi.fn()} />
            </MemoryRouter>,
        )

        await screen.findByText("Project One")
        if (!screen.queryByText("Collection One")) {
            await user.click(screen.getByRole("button", { name: "Project One" }))
        }
        await screen.findByText("Collection One")

        // Switch project role to Custom
        const projectSelect = screen.getByRole("combobox", { name: "Project role for Project One" })
        await user.click(projectSelect)
        const customOption = await screen.findByText("Custom")
        await user.click(customOption)

        // Now collection role select should be enabled
        const collectionSelect = screen.getByRole("combobox", { name: "Collection role for Collection One" })
        expect(collectionSelect).not.toHaveProperty("disabled", true)

        // Save
        await user.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(mocks.syncUserPermissions).toHaveBeenCalledOnce())
        const payload = mocks.syncUserPermissions.mock.calls[0]?.[1]
        expect(payload).toEqual({
            projects: [{
                project_id: 1,
                role: "custom",
                stored_permissions: [],
                collections: [{
                    project_id: 1,
                    collection_id: 10,
                    role: "custom",
                    stored_permissions: [],
                }],
            }],
        })
    })
})
