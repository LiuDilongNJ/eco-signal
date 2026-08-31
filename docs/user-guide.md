# ecoSignal User Guide

[中文](user-guide.zh.md) · [Documentation home](../README.md)

**For:** researchers, field workers, uploaders, annotators, and reviewers.  
**Before you begin:** sign in and obtain access to the project and collection you will use. Visible actions depend on your permissions.

## Contents

- [Work in a project](#work-in-a-project)
- [Upload and process media](#upload-and-process-media)
- [Annotate, review, and analyse](#annotate-review-and-analyse)
- [Import tabular data](#import-tabular-data)
- [Use offline collection bundles](#use-offline-collection-bundles)
- [Track background work](#track-background-work)

## Work in a project

Open a project, then select a collection to work with its audio, photos, sites, annotations, reviews, and related records. Use the available list, map, and detail views to filter and inspect records. A missing project, collection, or action normally means it is outside your current access scope.

Use collection-scoped work when recording, uploading, annotating, reviewing, or analysing data. Project and collection managers may expose additional management controls; see the [Administrator Guide](admin-guide.md).

## Upload and process media

Select one or more audio or photo files in the upload drawer, wait until their chunks finish uploading, then save the batch.

- Chunk upload creates staging records only; it does not create a Queue item for each file.
- Saving creates one `upload` Queue item for the accepted batch. Its `total` is the number of submitted files, and `completed` counts only media created successfully.
- The background job merges files, validates content, detects duplicates, creates media records, and generates previews sequentially.
- Duplicate files complete with a warning. Any failed file completes the batch with an error. Check Queue for the result of every submitted batch.

Do not close your browser to wait for completion: closing the drawer does not cancel a saved batch.

## Annotate, review, and analyse

Open a media record to inspect its preview and metadata. Where permitted, create or edit annotations and use reviews to record verification work. Image viewers can show or hide annotation overlays.

Analysis actions create background work. Follow their progress in Queue and open the completed media or result records to inspect the output. If an action is unavailable, request the matching collection-scoped permission from a manager.

## Import tabular data

For supported Data lists, choose an import option from the **Add** menu. Audio and Photo use their existing **Metadata** menu labels. Select **Import Instructions** or **Metadata Instructions** before preparing a file to see accepted fields and download a resource-specific CSV template.

Files may be `.csv`, `.txt`, or `.json`. Delimited text accepts comma, tab, semicolon, and pipe separators; a `.txt` file may also contain a JSON object array. CSV and delimited text require a header row.

The first submission validates every row without writing data. Review the browser report, correct failures, then confirm the same file to submit one atomic import. Duplicate rows are skipped; any other failed row prevents the batch from being committed. Select the target project and collection before importing collection-scoped resources.

## Use offline collection bundles

### Export

Open **Data > Collections**, select one collection, and choose **Export Bundle**. The application creates the complete media bundle in the background and provides a download when ready. The file remains available for 24 hours.

### Import

Select the target project, open **Data > Collections**, choose **Import Bundle**, and select one ZIP file. Progress, created and skipped counts, conflicts, and warnings remain available in Queue after the drawer closes.

The target `project_id` must already exist and the importer must have `project:write` on that project. Offline import batches accept `.zip` files only. The bundle signature and SHA-256 checksums are verified before data is imported. Media UUID is the identity key: matching UUID and binary content is reused and linked to the target collection, while matching UUID with different content aborts the import. Equal file hashes with different UUIDs remain separate media records. Existing files are never overwritten, and filename collisions receive a deterministic UUID suffix. Audio and photo previews are regenerated after import; preview-generation problems are reported as warnings without discarding successfully imported media. The export endpoint is `POST /api/v1/collection-bundle-exports`; import sessions use `POST /api/v1/data-imports`.

## Track background work

Use **Queue** to monitor upload, analysis, export, import, and similar background work. Open a row for its status and result counts. A warning means work completed with non-blocking findings; an error means at least one required operation failed. Share the Queue item details with a manager when you need help resolving a failure.

## Related documentation

- [Administrator Guide](admin-guide.md) for permissions, imports, and operations
- [README](../README.md) for local setup and tests
- [Documentation home](../README.md)
