# ecoSignal Administrator Guide

[中文](admin-guide.zh.md) · [Documentation home](../README.md)

**For:** system administrators, project managers, and collection managers.  
**Before you begin:** sign in with the management permission required for the project or collection you will administer. Some settings are limited to system administrators.

## Contents

- [Choose the right management scope](#choose-the-right-management-scope)
- [Manage projects and collections](#manage-projects-and-collections)
- [Manage users and permissions](#manage-users-and-permissions)
- [Configure public access](#configure-public-access)
- [Maintain settings and data](#maintain-settings-and-data)
- [Use batch data import](#use-batch-data-import)
- [Operate Queue and monitoring](#operate-queue-and-monitoring)

## Choose the right management scope

Access is evaluated on a project and collection path. Grant the narrowest scope that supports the member's work.

| Role or permission | Management capability |
| --- | --- |
| System administrator | Bypasses access checks and manages system-wide settings and users |
| `project:write` | Manages the project, its collections, and all collection-scoped resources |
| `collection:write` | Manages one collection path and its collection-scoped resources |
| Resource permission, such as `audio:write` | Manages only that resource type in the granted scope |
| Read permission | Views the granted resource; write permission also satisfies read access |

Project-level resource permissions apply to every collection in that project. `project:write` includes collection and resource access in the project; `collection:write` includes access to its child resources. Do not store duplicate lower-level grants that are already covered by a parent write grant.

Only a system administrator may grant `project:write`. A project or collection manager may delegate only permissions within the scope they manage.

## Manage projects and collections

Create projects and collections in their respective Data views. A collection may be linked to a project only by a user with project management access. Keep media, sites, annotations, reviews, and tasks in their intended collection scope.

When assigning users, distinguish explicit grants from inherited access:

- A project read grant makes the project visible but does not select every collection as a collection reader.
- A collection read grant also requires parent project read access.
- A project management grant already covers every collection; do not add duplicate collection management grants.

Use the project and collection views to review links and correct the scope before granting access.

## Manage users and permissions

Use the Users and permissions controls to add members and assign project or collection access. The permission editor presents both the saved grants and the access that follows from inheritance; save only the explicit grants selected for that project or collection.

For regular work, grant only the resource read or write permissions required. Use collection management where the member must manage all collection resources, and use project management only where the member must manage the full project. Recheck access after changing project-to-collection links because a collection grant is scoped to that project path.

## Configure public access

Public access is read-only and requires both levels to be configured correctly:

- A public project alone does not publish its collections or media.
- `public_access` on a collection within a public project allows anonymous reading of that collection, its audio, and its sites.
- `public_tags` on a collection within a public project allows anonymous reading of annotations.
- Neither public option grants write access.

Review these settings before sharing a public project link, especially where annotations may contain sensitive observations.

## Maintain settings and data

The Settings area contains profile and preference controls, sensor records, recorders, microphones, cameras, lenses, taxa, sounds, server settings, and system logs. System-only tabs are visible only to system administrators.

Maintain shared reference data before it is needed in project work. Prefer updating an existing record over creating near-duplicates, and use filters and exports to review the data set. Network settings are operational controls and should be changed only by authorised administrators.

## Use batch data import

The user-facing workflow is in the [User Guide](user-guide.md). This section provides the operational contract for troubleshooting and permissions.

Supported resources are projects, collections, sites, media, annotations, reviews, index logs, tasks, users, recorders, microphones, cameras, lenses, taxons, and sound classification records. Queue is not importable. Standard imports use `POST /api/v1/{resource}/imports` as `multipart/form-data`; collection bundles use their dedicated import flow.

| Field | Required | Meaning |
| --- | --- | --- |
| `file` | Yes | UTF-8 or UTF-8-BOM `.csv`, `.txt`, or `.json`; maximum 20 MiB, 50,000 records, and 256 columns |
| `dry_run` | No; defaults to `true` | `true` validates only; `false` commits only when all non-skipped rows are valid |
| `project_id` | Scope-dependent | Positive project ID used for access checks |
| `collection_id` | Scope-dependent | Positive collection ID; required by collection-scoped resources |
| `media_type` | Media only | `audio` or `photo`, selecting the metadata schema |

A validation response reports the source format, total, succeeded, skipped, failed, committed state, per-row results, and global errors. Validation reports are transient and are not stored. Projects require a system administrator; collections require `project:write`; collection-scoped imports require the matching resource write permission on the selected project and collection path. Public read access never allows imports.

For example, a semicolon-delimited file can look like this:

```text
name;brand;version
Forest recorder;Example;2
```

TXT files may also contain a JSON object array:

```json
[
  {"name": "Forest recorder", "brand": "Example", "version": "2"}
]
```

A successful validation returns HTTP 200 with a transient report similar to:

```json
{
  "code": 0,
  "message": "Import validation completed",
  "data": {
    "source_format": "delimited_text",
    "delimiter": ";",
    "dry_run": true,
    "total": 1,
    "succeeded": 1,
    "skipped": 0,
    "failed": 0,
    "committed": false,
    "rows": [{"row_number": 2, "status": "succeeded", "field": null, "reason": null}],
    "global_errors": []
  }
}
```

The endpoints never return imported password values or include them in row errors. Templates contain the exact accepted headers and an example row. Settings master-data imports remain administrator-only. The offline collection-bundle endpoint is `POST /api/v1/data-imports`.

## Operate Queue and monitoring

Queue is the operational source for background upload, analysis, import, export, and similar work. Use its status, counts, warnings, and errors to determine whether intervention is required. Do not infer completion from an upload drawer alone.

For service health, error reporting, metrics, and dashboards, follow the [Observability Guide](observability.md). Keep metrics behind an internal network or gateway protection in production. Deployment, migration, and recovery procedures are in the [Operations Guide](operations-guide.md).

## Related documentation

- [User Guide](user-guide.md) for the daily application workflow
- [Operations Guide](operations-guide.md) for deployment, migration, and recovery
- [Observability Guide](observability.md) for monitoring setup
- [Documentation home](../README.md)
