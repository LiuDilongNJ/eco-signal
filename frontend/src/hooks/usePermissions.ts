/**
 * Effective permissions for the current user, scoped to a project/collection.
 *
 * Action buttons must be gated on this instead of assuming access and letting
 * the API reject the write: a user without `review:write` should never reach an
 * edit form that cannot be saved.
 */

import { useQuery } from "@tanstack/react-query"
import { useCallback, useEffect, useState } from "react"

import { usersApi } from "@/api/endpoints/users"
import { authUtils } from "@/utils/auth"

export type PermissionAction = "read" | "write"
export type PermissionResource =
    | "project"
    | "collection"
    | "audio"
    | "site"
    | "annotation"
    | "review"
export type PermissionName = `${PermissionResource}:${PermissionAction}`

export const PERMISSIONS_QUERY_KEY = "current-user-permissions"

/** Data pages use "all" for the aggregate collection view, which has no single scope. */
function toScopeId(value: number | string | null | undefined): number | undefined {
    if (value == null || value === "" || value === "all") return undefined
    const parsed = Number(value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

export interface UsePermissionsResult {
    /** True only when the grant is confirmed; denies while loading. */
    can: (permission: PermissionName) => boolean
    isAdmin: boolean
    isLoading: boolean
    permissions: string[]
}

export function usePermissions(
    projectId?: number | string | null,
    collectionId?: number | string | null,
): UsePermissionsResult {
    const scopedProjectId = toScopeId(projectId)
    const scopedCollectionId = scopedProjectId != null ? toScopeId(collectionId) : undefined

    // Keyed by session so a logout drops to an empty cache entry instead of
    // briefly serving the previous user's grants while a refetch is in flight.
    const [authKey, setAuthKey] = useState(() => authUtils.getToken() ?? "")
    useEffect(() => {
        const syncAuth = () => setAuthKey(authUtils.getToken() ?? "")
        window.addEventListener("eco-auth-change", syncAuth)
        window.addEventListener("storage", syncAuth)
        return () => {
            window.removeEventListener("eco-auth-change", syncAuth)
            window.removeEventListener("storage", syncAuth)
        }
    }, [])

    const { data, isPending } = useQuery({
        queryKey: [
            PERMISSIONS_QUERY_KEY,
            authKey,
            scopedProjectId ?? null,
            scopedCollectionId ?? null,
        ],
        queryFn: async () => {
            const res = await usersApi.getMyPermissions({
                project_id: scopedProjectId,
                collection_id: scopedCollectionId,
            })
            return res.data
        },
    })

    const can = useCallback(
        (permission: PermissionName) =>
            data?.is_admin === true || (data?.permissions?.includes(permission) ?? false),
        [data],
    )

    return {
        can,
        isAdmin: data?.is_admin ?? false,
        isLoading: isPending,
        permissions: data?.permissions ?? [],
    }
}
