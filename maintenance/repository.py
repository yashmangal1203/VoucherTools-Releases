"""Local release maintenance and CI freshness renewal. No network writes.

Run from a separate clone of VoucherTools-Releases. This code never publishes.
Private keys are outside that clone. CI may sign ONLY snapshot and timestamp.
"""

import argparse
import copy
import getpass
import hashlib
import json
import os
import subprocess
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from packaging.version import Version
from securesystemslib.signer import CryptoSigner  # pyright: ignore[reportPrivateImportUsage]
from tuf.api.metadata import Metadata, MetaFile, TargetFile  # pyright: ignore[reportPrivateImportUsage]

REPOSITORY = "yashmangal1203/VoucherTools-Releases"
# Proposed defaults: owner reviews before activating CI or creating secrets.
OFFLINE_DAYS = 365
ONLINE_HOURS = 72
ROOT_RENEW_BELOW_DAYS = 335  # Avoid a new root version on every daily release.
SCOPE = {
    "app": "VoucherTools",
    "platform": "windows",
    "arch": "x64",
    "channel": "stable",
}


def hidden_password(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        value = getpass.getpass(prompt)
    if not value:
        raise ValueError("Empty password is not allowed.")
    return value.encode("utf-8")


def signer(path, password):
    data = Path(path).read_bytes()
    if not data.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"):
        raise ValueError("Expected an encrypted PKCS8 private key.")
    return CryptoSigner(load_pem_private_key(data, password))


def verify(root, role, metadata):
    root.signed.verify_delegate(role, metadata.signed_bytes, metadata.signatures)


def signed_bytes(root, role, metadata, key):
    metadata.signatures.clear()
    metadata.sign(key)
    verify(root, role, metadata)
    return metadata.to_bytes()


def load_repository(folder, now, *, allow_expired_online=False, allow_expired_offline=False):
    """Verify current role signatures and every referenced length/hash/version."""
    root = Metadata.from_file(str(folder / "root.json"))
    verify(root, "root", root)
    versioned_root = folder / f"{root.signed.version}.root.json"
    if versioned_root.read_bytes() != (folder / "root.json").read_bytes():
        raise ValueError("Current root must match its immutable versioned copy.")
    timestamp = Metadata.from_file(str(folder / "timestamp.json"))
    verify(root, "timestamp", timestamp)
    snapshot_bytes = (folder / f"{timestamp.signed.snapshot_meta.version}.snapshot.json").read_bytes()
    timestamp.signed.snapshot_meta.verify_length_and_hashes(snapshot_bytes)
    snapshot = Metadata.from_bytes(snapshot_bytes)
    verify(root, "snapshot", snapshot)
    if snapshot.signed.version != timestamp.signed.snapshot_meta.version:
        raise ValueError("Snapshot version mismatch.")
    if set(snapshot.signed.meta) != {"targets.json"}:
        raise ValueError("Delegations are not supported by this release tool.")
    target_ref = snapshot.signed.meta["targets.json"]
    target_bytes = (folder / f"{target_ref.version}.targets.json").read_bytes()
    target_ref.verify_length_and_hashes(target_bytes)
    targets = Metadata.from_bytes(target_bytes)
    verify(root, "targets", targets)
    if targets.signed.version != target_ref.version or targets.signed.delegations is not None:
        raise ValueError("Unexpected targets version/delegations.")
    for role, item in (
        ("root", root),
        ("targets", targets),
        ("snapshot", snapshot),
        ("timestamp", timestamp),
    ):
        if (
            item.signed.expires <= now
            and not allow_expired_offline
            and not (allow_expired_online and role in {"snapshot", "timestamp"})
        ):
            raise ValueError(f"{role} is expired. Offline owner maintenance is required.")
    return root, targets, snapshot, timestamp


def write_outputs(folder, files):
    """Validate first, then write immutable versions before mutable heads.

    Interruption may leave unreferenced versioned files. Never overwrite them;
    inspect/reset only unpublished local changes before retrying. Push as ONE
    commit, under the same repository concurrency lock as daily renewal.
    """
    for name, content in files.items():
        path = folder / name
        if path.exists() and name not in {"root.json", "timestamp.json"} and path.read_bytes() != content:
            raise FileExistsError(f"Immutable metadata already exists: {name}")
    for name, content in files.items():
        path = folder / name
        if path.exists() and path.read_bytes() == content:
            continue
        temporary = path.with_name(path.name + ".new")
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


def freshness(
    root,
    targets_bytes,
    target_version,
    snapshot,
    timestamp,
    snapshot_key,
    timestamp_key,
    now,
):
    snapshot.signed.version += 1
    snapshot.signed.expires = now + timedelta(hours=ONLINE_HOURS)
    snapshot.signed.meta = {"targets.json": MetaFile.from_data(target_version, targets_bytes, ["sha256"])}
    sb = signed_bytes(root, "snapshot", snapshot, snapshot_key)
    timestamp.signed.version += 1
    timestamp.signed.expires = now + timedelta(hours=ONLINE_HOURS)
    timestamp.signed.snapshot_meta = MetaFile.from_data(snapshot.signed.version, sb, ["sha256"])
    tb = signed_bytes(root, "timestamp", timestamp, timestamp_key)
    return {f"{snapshot.signed.version}.snapshot.json": sb, "timestamp.json": tb}


def renew_online(folder, snapshot_key, timestamp_key, now):
    # Recovery can refresh EXPIRED online metadata, but NEVER expired offline
    # authority. Clients still verify the newly signed, unexpired chain.
    root, targets, snapshot, timestamp = load_repository(folder, now, allow_expired_online=True)
    original_targets = (folder / f"{targets.signed.version}.targets.json").read_bytes()
    files = freshness(
        root,
        original_targets,
        targets.signed.version,
        snapshot,
        timestamp,
        snapshot_key,
        timestamp_key,
        now,
    )
    if targets.to_bytes() != Metadata.from_bytes(original_targets).to_bytes():
        raise AssertionError("Routine renewal must never approve/change installers.")
    write_outputs(folder, files)
    return root.signed.expires, targets.signed.expires


def make_online_keys(folder, password):
    if folder.exists() or any((p / ".git").exists() for p in (folder, *folder.parents)):
        raise ValueError("Choose a NEW private folder outside every Git repository.")
    folder.mkdir(parents=False, mode=0o700)
    for role in ("snapshot", "timestamp"):
        key = Ed25519PrivateKey.generate()
        content = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password),
        )
        with (folder / f"{role}.pem").open("xb") as handle:
            handle.write(content)
    # Password is NOT written. Use hidden local gh secret set input separately.


def authorize_online(folder, offline_keys, operational_keys, offline_password, online_password, now):
    root, targets, snapshot, timestamp = load_repository(folder, now, allow_expired_offline=True)
    old_root = copy.deepcopy(root)
    root_key = signer(offline_keys / "root.pem", offline_password)
    verify(root, "root", root)
    sk = signer(operational_keys / "snapshot.pem", online_password)
    tk = signer(operational_keys / "timestamp.pem", online_password)
    protected = set(root.signed.roles["root"].keyids + root.signed.roles["targets"].keyids)
    if sk.public_key.keyid == tk.public_key.keyid or protected & {
        sk.public_key.keyid,
        tk.public_key.keyid,
    }:
        raise ValueError("Operational keys must be distinct from all offline authority.")
    for role, key in (("snapshot", sk), ("timestamp", tk)):
        for keyid in list(root.signed.roles[role].keyids):
            root.signed.revoke_key(keyid, role)
        root.signed.add_key(key.public_key, role)
        root.signed.roles[role].threshold = 1
    root.signed.version += 1
    root.signed.expires = now + timedelta(days=OFFLINE_DAYS)
    rb = signed_bytes(root, "root", root, root_key)
    verify(old_root, "root", root)  # Same offline root must authorize transition.
    files = {f"{root.signed.version}.root.json": rb, "root.json": rb}
    files.update(
        freshness(
            root,
            targets.to_bytes(),
            targets.signed.version,
            snapshot,
            timestamp,
            sk,
            tk,
            now,
        )
    )
    write_outputs(folder, files)


def github_release(version):
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/releases/tags/v{version}"],
        check=True,
        capture_output=True,
        text=True,
    )
    release = json.loads(result.stdout)
    if release.get("draft") or release.get("prerelease") or release.get("tag_name") != f"v{version}":
        raise ValueError("Publish the actual stable GitHub release first, then sign its installer.")
    return release


def approve_release(
    folder,
    offline_keys,
    operational_keys,
    offline_password,
    online_password,
    installer_path,
    version,
    now,
):
    parsed = Version(version)
    if (
        str(parsed) != version
        or parsed.is_prerelease
        or parsed.is_devrelease
        or parsed.local
        or parsed.post is not None
    ):
        raise ValueError("Use a canonical stable app version.")
    root, targets, snapshot, timestamp = load_repository(folder, now, allow_expired_offline=True)
    release = github_release(version)
    published = release.get("published_at")
    if not isinstance(published, str) or not published.endswith("Z") or datetime.fromisoformat(published) > now:
        raise ValueError("GitHub production publication time is missing or in the future.")
    assets = [a for a in release["assets"] if a.get("name") == installer_path.name and a.get("state") == "uploaded"]
    if len(assets) != 1:
        raise ValueError("Exactly one uploaded asset matching the tested installer filename is required.")
    asset = assets[0]
    url = asset["browser_download_url"]
    prefix = f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
    if not url.startswith(prefix) or "/" in url[len(prefix) :]:
        raise ValueError("Unexpected GitHub installer URL.")
    asset_time = asset.get("created_at")
    if not isinstance(asset_time, str) or not asset_time.endswith("Z"):
        raise ValueError("GitHub asset upload time is missing.")
    publication = max(datetime.fromisoformat(published), datetime.fromisoformat(asset_time))
    if publication > now:
        raise ValueError("Production publication time is in the future.")
    published = publication.isoformat().replace("+00:00", "Z")
    length = installer_path.stat().st_size
    if not 0 < length <= 1024**3 or asset.get("size") != length:
        raise ValueError("Uploaded installer size differs from tested local bytes.")
    with installer_path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    # Independently download published bytes. GitHub digest can be absent on old assets.
    remote_hash = hashlib.sha256()
    count = 0
    with urlopen(url, timeout=30) as response:
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > length:
                raise ValueError("Published installer exceeds expected length.")
            remote_hash.update(chunk)
    if count != length or remote_hash.hexdigest() != digest:
        raise ValueError("Published installer does not match tested local bytes.")
    for existing in targets.signed.targets.values():
        custom = existing.unrecognized_fields.get("custom", {})
        if (
            custom.get("version")
            and all(custom.get(key) == value for key, value in SCOPE.items())
            and Version(custom["version"]) >= parsed
        ):
            raise ValueError(
                "Version is already approved. Never replace/relabel release bytes; use offline-renew without an installer."
            )
    target = TargetFile(length=length, hashes={"sha256": digest}, path=installer_path.name)
    target.unrecognized_fields["custom"] = {
        **SCOPE,
        "version": version,
        "released_at": published,
        "download_url": url,
    }
    if target.path in targets.signed.targets:
        raise ValueError("Target filename already exists. Use a versioned filename.")
    targets.signed.targets[target.path] = target
    offline_renew(
        folder,
        offline_keys,
        operational_keys,
        offline_password,
        online_password,
        now,
        loaded=(root, targets, snapshot, timestamp),
    )


def offline_renew(
    folder,
    offline_keys,
    operational_keys,
    offline_password,
    online_password,
    now,
    *,
    loaded=None,
):
    root, targets, snapshot, timestamp = loaded or load_repository(folder, now, allow_expired_offline=True)
    root_key = signer(offline_keys / "root.pem", offline_password)
    target_key = signer(offline_keys / "targets.pem", offline_password)
    sk = signer(operational_keys / "snapshot.pem", online_password)
    tk = signer(operational_keys / "timestamp.pem", online_password)
    files = {}
    if root.signed.expires < now + timedelta(days=ROOT_RENEW_BELOW_DAYS):
        previous = copy.deepcopy(root)
        root.signed.version += 1
        root.signed.expires = now + timedelta(days=OFFLINE_DAYS)
        rb = signed_bytes(root, "root", root, root_key)
        verify(previous, "root", root)
        files.update({f"{root.signed.version}.root.json": rb, "root.json": rb})
    targets.signed.version += 1
    targets.signed.expires = now + timedelta(days=OFFLINE_DAYS)
    tb = signed_bytes(root, "targets", targets, target_key)
    files[f"{targets.signed.version}.targets.json"] = tb
    files.update(freshness(root, tb, targets.signed.version, snapshot, timestamp, sk, tk, now))
    write_outputs(folder, files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "make-online-keys",
            "authorize-online",
            "online-renew",
            "offline-renew",
            "release",
            "status",
            "install-ci-secrets",
        ],
    )
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--offline-keys", type=Path)
    parser.add_argument("--operational-keys", type=Path)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--version")
    parser.add_argument(
        "--confirm-online-custody",
        action="store_true",
        help="Explicit consent to put ONLY the NEW operational keys/password in GitHub Secrets",
    )
    args = parser.parse_args()
    now = datetime.now(UTC)
    if args.command == "make-online-keys":
        if args.operational_keys is None:
            parser.error("--operational-keys NEW_PRIVATE_FOLDER is required")
        password = hidden_password("NEW operational-key password (hidden): ")
        if password != hidden_password("Repeat new password (hidden): "):
            raise ValueError("Passwords differ.")
        make_online_keys(args.operational_keys.resolve(), password)
        print("Created two encrypted operational keys locally. No upload. Keep these out of Git/chat.")
        return
    if args.repository is None:
        parser.error("--repository is required")
    folder = args.repository.resolve()
    if args.command == "status":
        root, targets, snapshot, timestamp = load_repository(folder, now, allow_expired_online=True)
        for role, item in (
            ("root", root),
            ("targets", targets),
            ("snapshot", snapshot),
            ("timestamp", timestamp),
        ):
            remaining = (item.signed.expires - now).total_seconds() / 3600
            print(f"{role}: v{item.signed.version}, expires {item.signed.expires.isoformat()}, {remaining:.1f}h left")
        return
    if args.command == "install-ci-secrets":
        if args.operational_keys is None or not args.confirm_online_custody:
            parser.error(
                "Requires --operational-keys and --confirm-online-custody after reviewing the custody/TTL choices"
            )
        password = hidden_password("NEW operational key password (hidden): ")
        root, _, _, _ = load_repository(folder, now, allow_expired_online=True)
        values = {}
        for role in ("snapshot", "timestamp"):
            path = args.operational_keys / f"{role}.pem"
            key = signer(path, password)
            if root.signed.roles[role].threshold != 1 or key.public_key.keyid not in root.signed.roles[role].keyids:
                raise ValueError("Current signed root does not authorize this operational key.")
            values[f"VT_{role.upper()}_PEM"] = path.read_bytes()
        values["VT_ONLINE_PASSWORD"] = password
        for name, content in values.items():
            subprocess.run(
                ["gh", "secret", "set", name, "--repo", REPOSITORY],
                input=content,
                check=True,
            )
        print(
            "Three operational Secrets installed. Root/targets keys were not read or uploaded. Review and enable the workflow separately."
        )
        return
    if args.command == "online-renew":
        # CI-only secrets are environment values; never echo them or include
        # exception objects containing key data in logs.
        password = os.environ["VT_ONLINE_PASSWORD"].encode("utf-8")
        sk = CryptoSigner(load_pem_private_key(os.environ["VT_SNAPSHOT_PEM"].encode("utf-8"), password))
        tk = CryptoSigner(load_pem_private_key(os.environ["VT_TIMESTAMP_PEM"].encode("utf-8"), password))
        root_expiry, targets_expiry = renew_online(folder, sk, tk, now)
        print(
            f"Freshness renewed for {ONLINE_HOURS}h. Offline expiry: root={root_expiry.isoformat()}, targets={targets_expiry.isoformat()}"
        )
        if min(root_expiry, targets_expiry) - now < timedelta(days=60):
            print(
                "::warning::Offline root/targets have under60days left. Owner must renew them. Routine freshness renewal cannot extend offline authority."
            )
        return
    if args.offline_keys is None or args.operational_keys is None:
        parser.error("--offline-keys and --operational-keys are required")
    op = hidden_password("Existing OFFLINE key password (hidden): ")
    online = hidden_password("NEW operational key password (hidden): ")
    if args.command == "authorize-online":
        authorize_online(folder, args.offline_keys, args.operational_keys, op, online, now)
    elif args.command == "offline-renew":
        offline_renew(folder, args.offline_keys, args.operational_keys, op, online, now)
    else:
        if args.installer is None or args.version is None:
            parser.error("release requires --installer and --version")
        approve_release(
            folder,
            args.offline_keys,
            args.operational_keys,
            op,
            online,
            args.installer.resolve(),
            args.version,
            now,
        )
    print("Signed PUBLIC metadata locally. Nothing uploaded. Review then publish all changed metadata as one commit.")


if __name__ == "__main__":
    try:
        main()
    except Exception, KeyboardInterrupt:  # noqa: BLE001 - no secret exception details in terminal logs
        # Never risk secret material in exception text or traceback.
        raise SystemExit(
            "Maintenance did not complete. No automatic publish. Inspect local changes; never overwrite published metadata. Check local paths/passwords and signed expiry without sharing secrets."
        ) from None
