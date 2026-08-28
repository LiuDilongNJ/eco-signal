import { useEffect, useState } from "react"
import { usersApi, type UserOption } from "../../../../../api/endpoints/users"

type ScopeId = string | number | null | undefined

function hasProjectScope(projectId: ScopeId): boolean {
    return Boolean(projectId)
}

export function useCreatorOptions(projectId: ScopeId, collectionId: ScopeId) {
    const [creatorOptions, setCreatorOptions] = useState<UserOption[]>([])
    const [currentUser, setCurrentUser] = useState<UserOption | null>(null)

    useEffect(() => {
        let cancelled = false

        const load = async () => {
            try {
                if (!hasProjectScope(projectId)) {
                    setCreatorOptions([])
                    setCurrentUser(null)
                    return
                }

                const normalizedProjectId = Number(projectId)
                const normalizedCollectionId = collectionId && collectionId !== "all"
                    ? Number(collectionId)
                    : undefined
                const meResponse = await usersApi.getMe({
                    project_id: normalizedProjectId,
                    ...(normalizedCollectionId !== undefined ? { collection_id: normalizedCollectionId } : {}),
                })
                if (cancelled || !meResponse.data) return

                const me: UserOption = {
                    user_id: meResponse.data.user_id,
                    name: meResponse.data.name || meResponse.data.username || String(meResponse.data.user_id),
                    username: meResponse.data.username,
                }
                setCurrentUser(me)

                if (!meResponse.data.can_write_audio) {
                    setCreatorOptions([])
                    return
                }

                const response = await usersApi.getCreatorOptions({
                    project_id: normalizedProjectId,
                    ...(normalizedCollectionId !== undefined
                        ? { collection_id: normalizedCollectionId }
                        : {}),
                })
                if (cancelled) return

                const options: UserOption[] = (response.data ?? []).map((user) => ({
                    user_id: user.user_id,
                    name: user.name || user.username || String(user.user_id),
                    username: user.username,
                }))
                if (!options.some((user) => user.user_id === me.user_id)) {
                    options.unshift({
                        ...me,
                    })
                }
                setCreatorOptions(options)
            } catch (error) {
                if (cancelled) return
                console.error("Failed to fetch creator options:", error)
                setCreatorOptions([])
                setCurrentUser(null)
            }
        }

        void load()
        return () => {
            cancelled = true
        }
    }, [collectionId, projectId])

    return { creatorOptions, currentUserId: currentUser?.user_id ?? null }
}
