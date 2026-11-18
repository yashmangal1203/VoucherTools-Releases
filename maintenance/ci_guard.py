"""Guard the only CI write paths and open one owner-visible maintenance issue."""

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import repository

TITLE = "VoucherTools update service needs maintenance"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def check_changes(*, stage=False):
    paths = set(filter(None, git("diff", "--name-only", "HEAD").splitlines()))
    paths.update(
        filter(None, git("ls-files", "--others", "--exclude-standard").splitlines())
    )
    if "timestamp.json" not in paths:
        raise ValueError("Expected a newly signed timestamp.")
    _root, _targets, snapshot, timestamp = repository.load_repository(
        Path("."), datetime.now(UTC)
    )
    expected = {"timestamp.json", f"{snapshot.signed.version}.snapshot.json"}
    if paths != expected:
        raise ValueError(
            "CI may write only the newly referenced snapshot and timestamp."
        )
    new_snapshot = f"{snapshot.signed.version}.snapshot.json"
    existing = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{new_snapshot}"],
        capture_output=True,
        check=False,
    )
    if existing.returncode == 0:
        raise ValueError("CI must never replace an existing versioned snapshot.")
    before = json.loads(git("show", "HEAD:timestamp.json"))
    if (
        timestamp.signed.version != before["signed"]["version"] + 1
        or snapshot.signed.version
        != before["signed"]["meta"]["snapshot.json"]["version"] + 1
    ):
        raise ValueError("Expected consecutive freshness versions.")
    if stage:
        subprocess.run(["git", "add", "--", *sorted(paths)], check=True)


def notify():
    problem = os.environ.get("VT_JOB_STATUS") != "success"
    reason = "The scheduled renewal workflow failed. Check its run log, signed expiry and repository state."
    try:
        root, targets, _, _ = repository.load_repository(
            Path("."), datetime.now(UTC), allow_expired_online=True
        )
        if min(root.signed.expires, targets.signed.expires) < datetime.now(
            UTC
        ) + timedelta(days=60):
            problem = True
            reason = "Offline root/installer-approval metadata expires within60days. Run owner offline-renew or make an approved release before expiry. Routine CI cannot extend that authority."
    except Exception:  # noqa: BLE001 - an unreadable catalogue itself needs attention
        problem = True
    query = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repository.REPOSITORY,
            "--state",
            "open",
            "--search",
            TITLE + " in:title",
            "--json",
            "number,title",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    existing = [x for x in json.loads(query.stdout) if x["title"] == TITLE]
    if problem:
        print("::warning::" + reason)
        if not existing:
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    repository.REPOSITORY,
                    "--title",
                    TITLE,
                    "--body",
                    reason
                    + "\n\nWatch this issue and Actions failure notifications. Check the live timestamp before closing. This alert cannot detect Actions being completely disabled; the independent expiry check must cover that.",
                ],
                check=True,
            )
    else:
        print(
            "Renewal succeeded. No offline-expiry warning. Any earlier issue remains open until the owner verifies recovery."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    if args.notify:
        notify()
    else:
        check_changes(stage=args.stage)
