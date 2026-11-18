import json
import sqlite3
from pathlib import Path

from strategy_library_builder import read_gzip_json, sha256_file, sha256_value


def miss(reason, detail=None):
    value = {"hit": False, "reason": reason, "source": "formal_strategy_library"}
    if detail:
        value["detail"] = str(detail)[:300]
    return value


class RuntimeStrategyLibrary:
    """Read-only exact lookup for published strategy-library releases."""

    def __init__(self, root):
        self.root = Path(root)

    def lookup(self, scene_key):
        if not isinstance(scene_key, dict):
            return miss("invalid_scene_key")
        try:
            return self._lookup(scene_key)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, sqlite3.Error) as error:
            return miss("library_invalid", error)

    def _lookup(self, scene_key):
        pointer = self.root / "CURRENT"
        if not pointer.is_file():
            return miss("no_current_release")
        version = pointer.read_text(encoding="utf-8").strip()
        if not version or Path(version).name != version:
            return miss("invalid_current_release")
        release = self.root / "releases" / version
        manifest_path = release / "manifest.json"
        index_path = release / "index.sqlite"
        if not manifest_path.is_file() or not index_path.is_file():
            return miss("release_incomplete")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("release_version") != version:
            return miss("manifest_version_mismatch")
        if sha256_file(index_path) != manifest.get("index_checksum"):
            return miss("index_checksum_mismatch")
        expected_shards = {
            item["path"]: item["checksum"] for item in manifest.get("shards", [])
            if isinstance(item, dict) and item.get("path") and item.get("checksum")
        }
        scene_hash = sha256_value(scene_key)
        connection = sqlite3.connect(f"file:{index_path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT shard_path,artifact_checksum,scene_json FROM strategies WHERE scene_hash=?",
                (scene_hash,),
            ).fetchone()
        finally:
            connection.close()
        if not row:
            return miss("exact_scene_not_found")
        shard_name, artifact_checksum, indexed_scene = row
        if shard_name not in expected_shards:
            return miss("shard_not_in_manifest")
        if json.loads(indexed_scene) != scene_key:
            return miss("index_scene_mismatch")
        shard_path = (release / shard_name).resolve()
        try:
            shard_path.relative_to(release.resolve())
        except ValueError:
            return miss("invalid_shard_path")
        if not shard_path.is_file():
            return miss("shard_missing")
        if sha256_file(shard_path) != expected_shards[shard_name]:
            return miss("shard_checksum_mismatch")
        shard = read_gzip_json(shard_path)
        matches = [record for record in shard.get("records", []) if record.get("scene_hash") == scene_hash]
        if len(matches) != 1:
            return miss("shard_record_missing_or_duplicate")
        record = matches[0]
        if record.get("scene_key") != scene_key:
            return miss("shard_scene_mismatch")
        result = record.get("result")
        if not isinstance(result, dict) or record.get("checksum") != artifact_checksum:
            return miss("artifact_index_mismatch")
        if sha256_value(result) != artifact_checksum:
            return miss("artifact_checksum_mismatch")
        return {
            "hit": True,
            "source": "formal_strategy_library",
            "release_version": version,
            "scene_hash": scene_hash,
            "result": result,
        }
