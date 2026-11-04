"""Offline, checksummed local-library backup and restore into a new directory."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from qdrant_client import QdrantClient

from vision_rag.storage.ownership import LibraryOwnership

MAX_BYTES = 8 * 1024**3
ROOTS = {"metadata.sqlite3", "qdrant", "originals", "incoming"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def collections(client: QdrantClient) -> dict[str, int]:
    return {
        c.name: client.count(c.name, exact=True).count
        for c in client.get_collections().collections
    }


def database(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        db.close()
        raise ValueError("Metadata integrity check failed")
    return db


def signature(manifest: dict[str, Any], key: bytes) -> str:
    if len(key) != 32:
        raise ValueError("Backup authentication key must contain exactly 32 bytes")
    value = {k: v for k, v in manifest.items() if k != "signature"}
    return hmac.new(
        key, json.dumps(value, sort_keys=True).encode(), hashlib.sha256
    ).hexdigest()


def create(source: Path, destination: Path, key: bytes) -> dict[str, Any]:
    source, destination = source.resolve(), destination.resolve()
    if not (source / "metadata.sqlite3").is_file() or not (source / "qdrant").is_dir():
        raise ValueError("Choose an existing persistent local library")
    if destination.is_relative_to(source) or destination.exists():
        raise ValueError("Backup output must be a new file outside the library")
    destination.parent.mkdir(parents=True, exist_ok=True)
    owner = LibraryOwnership(
        source
    )  # Refuses a running application, including memory mode.
    client = None
    try:
        client = QdrantClient(path=str(source / "qdrant"))
        with tempfile.TemporaryDirectory(
            prefix="vision-backup-", dir=destination.parent
        ) as folder:
            snapshot = Path(folder) / "metadata.sqlite3"
            db = database(source / "metadata.sqlite3")
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                with closing(sqlite3.connect(snapshot)) as target:
                    db.backup(target)
            finally:
                db.close()
            entries: dict[str, dict[str, Any]] = {}
            files = [("metadata.sqlite3", snapshot)]
            for root in ("qdrant", "originals", "incoming"):
                for file in sorted((source / root).rglob("*")):
                    if file.is_symlink() or not file.resolve().is_relative_to(source):
                        raise ValueError(
                            "Backup refuses symlinks or paths outside the library"
                        )
                    if file.is_file() and file.name != ".lock":
                        files.append((file.relative_to(source).as_posix(), file))
            manifest = {
                "format": 1,
                "schema": version,
                "collections": collections(client),
                "entries": entries,
                "includes_cache": False,
                "secrets": "Configuration and model caches are excluded",
            }
            temporary = Path(folder) / "backup.zip"
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name, file in files:
                    entries[name] = {
                        "bytes": file.stat().st_size,
                        "sha256": digest(file),
                    }
                    archive.write(file, name)
                manifest["signature"] = signature(manifest, key)
                archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            # Exclusive creation, never overwrite an existing backup.
            with destination.open("xb") as target, temporary.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    target.write(block)
            return manifest
    finally:
        if client:
            client.close()
        owner.close()


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and "\\" not in name
        and ":" not in name
        and bool(path.parts)
        and all(p not in (".", "..", "") for p in name.split("/"))
        and path.parts[0] in ROOTS
        and name != "manifest.json"
        and not any(
            part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *{f"COM{i}" for i in range(1, 10)},
                *{f"LPT{i}" for i in range(1, 10)},
            }
            or part.endswith((" ", "."))
            for part in path.parts
        )
    )


def restore(
    archive_path: Path, target: Path, key: bytes, max_bytes: int = MAX_BYTES
) -> dict[str, Any]:
    target = target.resolve()
    if target.exists():
        raise ValueError("Restore target must not exist; use a new library directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > 100000 or sum(i.file_size for i in infos) > max_bytes:
            raise ValueError("Backup exceeds extraction limits")
        if len({i.filename.casefold() for i in infos}) != len(infos):
            raise ValueError("Backup contains duplicate paths")
        if "manifest.json" not in archive.namelist():
            raise ValueError("Backup manifest is missing")
        info = archive.getinfo("manifest.json")
        if info.file_size > 8 * 1024 * 1024:
            raise ValueError("Backup manifest is too large")
        manifest = json.loads(archive.read(info))
        if not isinstance(manifest, dict) or not hmac.compare_digest(
            str(manifest.get("signature", "")), signature(manifest, key)
        ):
            raise ValueError(
                "Backup authentication failed; use the original separate key file"
            )
        if manifest.get("format") != 1 or manifest.get("schema") not in range(1, 7):
            raise ValueError("Unsupported backup or schema version")
        entries = manifest["entries"]
        if not isinstance(entries, dict) or not isinstance(
            manifest.get("collections"), dict
        ):
            raise ValueError("Invalid backup manifest structure")
        if set(entries) | {"manifest.json"} != set(archive.namelist()):
            raise ValueError("Backup files do not match the manifest")
        for name, value in entries.items():
            if not isinstance(value, dict) or not isinstance(value.get("bytes"), int):
                raise ValueError("Invalid backup entry metadata")
            file_info = archive.getinfo(name)
            mode = file_info.external_attr >> 16
            if (
                not safe_name(name)
                or stat.S_ISLNK(mode)
                or file_info.is_dir()
                or file_info.file_size != value["bytes"]
            ):
                raise ValueError("Unsafe or mismatched backup entry")
        if "metadata.sqlite3" not in entries:
            raise ValueError("Backup metadata is missing")
        with tempfile.TemporaryDirectory(
            prefix=target.name + "-restore-", dir=target.parent
        ) as folder:
            staging = Path(folder) / "library"
            staging.mkdir()
            for name, value in entries.items():
                path = staging.joinpath(*PurePosixPath(name).parts)
                if not path.resolve().is_relative_to(staging.resolve()):
                    raise ValueError("Restore path escapes the target")
                path.parent.mkdir(parents=True, exist_ok=True)
                sha = hashlib.sha256()
                with archive.open(name) as source, path.open("xb") as output:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        sha.update(block)
                        output.write(block)
                if sha.hexdigest() != value["sha256"]:
                    raise ValueError("Backup checksum mismatch")
            db = database(staging / "metadata.sqlite3")
            try:
                originals = db.execute(
                    "SELECT v.storage_key,v.content_hash FROM versions v "
                    "JOIN documents d ON d.id=v.document_id WHERE d.deleted_at IS NULL"
                ).fetchall()
                for storage_key, expected in originals:
                    if (
                        not safe_name(storage_key)
                        or storage_key not in entries
                        or entries[storage_key]["sha256"] != expected
                    ):
                        raise ValueError(
                            "Backup does not contain every live original PDF"
                        )
            finally:
                db.close()
            client = QdrantClient(path=str(staging / "qdrant"))
            try:
                if collections(client) != manifest["collections"]:
                    raise ValueError("Restored vector collection counts do not match")
            finally:
                client.close()
            if target.exists():
                raise ValueError("Restore target appeared during validation")
            os.rename(staging, target)
        return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("keygen", "create", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "keygen":
            args.source.parent.mkdir(parents=True, exist_ok=True)
            with args.source.open("xb") as stream:
                stream.write(secrets.token_bytes(32))
            if os.name != "nt":
                args.source.chmod(0o600)
            print("Backup key created; store it separately from archives")
            return
        if args.destination is None or args.key_file is None:
            raise ValueError("Create/restore require a destination and --key-file")
        if args.action == "create" and args.key_file.resolve().is_relative_to(
            args.source.resolve()
        ):
            raise ValueError("Keep the backup key outside the library")
        if args.key_file.stat().st_size != 32:
            raise ValueError("Backup key file must contain exactly 32 bytes")
        key = args.key_file.read_bytes()
        manifest = (
            create(args.source, args.destination, key)
            if args.action == "create"
            else restore(args.source, args.destination, key)
        )
        print(
            json.dumps(
                {
                    "status": "verified",
                    "files": len(manifest["entries"]),
                    "collections": manifest["collections"],
                }
            )
        )
    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
