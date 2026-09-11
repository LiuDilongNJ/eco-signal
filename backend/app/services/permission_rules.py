SUB_RESOURCE_TYPES: frozenset[str] = frozenset({
    "media", "site", "annotation", "review"
})
COLLECTION_SCOPED_RESOURCES: frozenset[str] = frozenset({"collection", *SUB_RESOURCE_TYPES})
ACCESS_ROLE_CODES: frozenset[str] = frozenset({"viewer", "annotator", "reviewer", "manager", "custom"})
OWNABLE_RESOURCE_TYPES: frozenset[str] = frozenset({"annotation", "review"})
OWN_ACTIONS: frozenset[str] = frozenset({"read_own", "write_own"})


def minimize_effective_permissions(permission_names: list[str]) -> list[str]:
    action_map: dict[str, set[str]] = {}
    for name in permission_names:
        if ":" not in name:
            continue
        resource_type, action = name.split(":", 1)
        action_map.setdefault(resource_type, set()).add(action)

    minimized: list[str] = []
    for resource_type, actions in action_map.items():
        if "write" in actions:
            minimized.append(f"{resource_type}:write")
        elif "read" in actions:
            minimized.append(f"{resource_type}:read")
            if "write_own" in actions:
                minimized.append(f"{resource_type}:write_own")
        elif "write_own" in actions:
            minimized.append(f"{resource_type}:write_own")
        elif "read_own" in actions:
            minimized.append(f"{resource_type}:read_own")
        else:
            minimized.extend(f"{resource_type}:{action}" for action in sorted(actions))
    return sorted(minimized)


def normalize_permissions(permission_names: list[str], scope_type: str) -> list[str]:
    names = set(permission_names)
    if names:
        scope_write = f"{scope_type}:write"
        scope_read = f"{scope_type}:read"
        if scope_write not in names and scope_read not in names:
            names.add(scope_read)

    scope_write = f"{scope_type}:write"
    if scope_write in names:
        names.discard(f"{scope_type}:read")
        for resource_type in SUB_RESOURCE_TYPES:
            names.discard(f"{resource_type}:read")
            names.discard(f"{resource_type}:write")
            names.discard(f"{resource_type}:read_own")
            names.discard(f"{resource_type}:write_own")

    for name in list(names):
        resource_type, action = name.split(":", 1)
        if action == "write":
            names.discard(f"{resource_type}:read")
            if resource_type in OWNABLE_RESOURCE_TYPES:
                names.discard(f"{resource_type}:read_own")
                names.discard(f"{resource_type}:write_own")
        if action == "read" and resource_type in OWNABLE_RESOURCE_TYPES:
            names.discard(f"{resource_type}:read_own")
        if action == "write_own" and resource_type in OWNABLE_RESOURCE_TYPES:
            names.discard(f"{resource_type}:read_own")
    return list(names)


def remove_cross_scope_redundancies(
    collection_permissions: list[str],
    parent_project_permissions: set[str],
) -> list[str]:
    if "project:write" in parent_project_permissions:
        return []

    remaining = []
    for permission_name in collection_permissions:
        resource_type, action = permission_name.split(":", 1)
        if permission_name in parent_project_permissions:
            continue
        if action in {"read", "read_own", "write_own"} and f"{resource_type}:write" in parent_project_permissions:
            continue
        if action == "read_own" and (
            f"{resource_type}:read" in parent_project_permissions
            or f"{resource_type}:write_own" in parent_project_permissions
        ):
            continue
        remaining.append(permission_name)
    return remaining
