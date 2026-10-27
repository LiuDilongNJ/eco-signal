"""End-to-end test of the hybrid S3 media storage inside the backend container.

Exercises the real app.services.media_storage module against the bundled MinIO:
upload -> cache hit -> cache miss re-fetch -> dir sync -> remote delete -> local delete.
"""
import json
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.media_paths import media_root
from app.services import media_storage as ms

failures = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def force_stale(local_path: Path) -> None:
    """Write the meta file directly with an old mtime. (ms._write_meta always
    stamps mtime=now, so it cannot be used to simulate an expired cache entry.)"""
    meta = ms._read_meta(local_path)
    etag = meta.get("etag") if meta else ""
    ms._meta_path(local_path).write_text(
        json.dumps({"etag": etag, "mtime": time.time() - 9999}), encoding="utf-8"
    )


root = media_root()
print(f"media_root={root}  s3_enabled={settings.media_storage_is_s3}  bucket={settings.S3_BUCKET}")
check("S3 mode enabled", settings.media_storage_is_s3)

test_dir = root / "s3test"
test_dir.mkdir(parents=True, exist_ok=True)
f1 = test_dir / "hello.txt"
f2 = test_dir / "sub" / "nested.bin"
f2.parent.mkdir(parents=True, exist_ok=True)
f1.write_bytes(b"hello s3 world")
f2.write_bytes(bytes(range(256)))

# 1. upload both files
ms.upload(f1)
ms.upload(f2)
meta1 = ms._read_meta(f1)
check("upload f1 wrote meta", meta1 is not None and bool(meta1.get("etag")), str(meta1))
check("upload f2 wrote meta", ms._read_meta(f2) is not None)

# 2. cache hit: fresh local file is not re-downloaded
t0 = time.time()
ms.ensure_local(f1)
check("ensure_local fresh (no re-download)", f1.read_bytes() == b"hello s3 world" and time.time() - t0 < 1.0)

# 3. cache miss: delete local, re-fetch from S3
f1.unlink()
ms._delete_meta(f1)
ms.ensure_local(f1)
check("ensure_local re-fetch after local delete", f1.is_file() and f1.read_bytes() == b"hello s3 world")

# 4. stale + remote etag changed -> genuine re-download. Upload new content to
#    S3 (new etag), corrupt the local bytes, force the cache entry stale, and
#    verify ensure_local re-downloads the new content.
client = ms._client()
client.put_object(Bucket=settings.S3_BUCKET, Key="s3test/hello.txt", Body=b"v2 content")
f1.write_bytes(b"CORRUPTED")
force_stale(f1)
ms.ensure_local(f1)
check("ensure_local re-fetch when stale + etag changed", f1.is_file() and f1.read_bytes() == b"v2 content")

# 4b. stale but remote etag unchanged -> local file kept, only freshness
#     marker refreshed (no re-download). Corrupt the bytes; the module must
#     trust the cached etag and NOT re-download.
f1.write_bytes(b"CORRUPTED")
force_stale(f1)
ms.ensure_local(f1)
check("stale but etag unchanged keeps local file", f1.is_file() and f1.read_bytes() == b"CORRUPTED")
# restore correct content for the later tests
ms.invalidate_local(f1)
ms.ensure_local(f1)
check("re-fetch restores correct content", f1.read_bytes() == b"v2 content")

# 5. directory sync: delete local tree, re-fetch everything
for p in (f1, f2):
    p.unlink(missing_ok=True)
    ms._delete_meta(p)
ms.ensure_local(test_dir)
check("ensure_local dir re-fetch f1", f1.is_file() and f1.read_bytes() == b"v2 content")
check("ensure_local dir re-fetch f2", f2.is_file() and f2.read_bytes() == bytes(range(256)))

# 6. remote delete: while the local copy is still fresh (within TTL) it is
#    served from cache by design; once stale, ensure_local drops it (S3 404).
client = ms._client()
client.delete_object(Bucket=settings.S3_BUCKET, Key="s3test/hello.txt")
ms.ensure_local(f1)
check("fresh local copy served from cache (remote delete not yet propagated)", f1.is_file())
force_stale(f1)
ms.ensure_local(f1)
check("stale local copy dropped after remote delete", not f1.exists())

# 7. re-upload then delete() removes both local and S3
ms.upload(f1)
ms.delete(f1)
check("delete() removes local", not f1.exists())
try:
    client.head_object(Bucket=settings.S3_BUCKET, Key="s3test/hello.txt")
    check("delete() removes S3 object", False, "object still present")
except Exception:
    check("delete() removes S3 object", True)

# 8. delete_dir removes all S3 objects under the prefix. (Callers remove the
#    local tree themselves via shutil.rmtree; delete_dir is S3+meta only.)
ms.delete_dir(test_dir)
remaining = [
    o["Key"]
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=settings.S3_BUCKET, Prefix="s3test/")
    for o in page.get("Contents", [])
]
check("delete_dir removes all S3 objects", not remaining, str(remaining))
# caller-side local cleanup (mirrors maintenance.py / file_service.py)
import shutil

shutil.rmtree(test_dir, ignore_errors=True)
check("caller removes local tree after delete_dir", not test_dir.exists() or not any(test_dir.rglob("*")))

print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
