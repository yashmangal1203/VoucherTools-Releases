# VoucherTools

Focused accounting tools. Less repetitive work.

VoucherTools is a growing set of small utilities for accounting and bookkeeping. Each tool has a specific job, with review kept in the workflow where it matters.

This repository hosts the Windows installers and signed update metadata. You don't need to clone it to use the app.

## Download

**Current release: 0.1.0 · Windows 10 or later · x64**

### [Download VoucherTools for Windows](https://github.com/yashmangal1203/VoucherTools-Releases/releases/download/v0.1.0/VoucherTools-Setup-0.1.0-x64.exe)

EXE installer, 63.1 MB. [Read the release notes](https://github.com/yashmangal1203/VoucherTools-Releases/releases/tag/v0.1.0) or [browse all releases](https://github.com/yashmangal1203/VoucherTools-Releases/releases).

> **Early release:** Installation, startup and use with TallyPrime have been tested on the developer's PC. Clean-PC installation and cross-version updates haven't been verified yet. This is a limited test release, not yet ready for wider use.

## Available now

### Bank statements to TallyPrime

Import HDFC bank statements in **PDF or Excel** format, review the transactions, choose ledgers and post the reviewed entries to TallyPrime on the same Windows PC.

1. **Choose a statement.** Upload a supported HDFC PDF or Excel file.
2. **Review the entries.** Check the transactions and assign the appropriate ledgers.
3. **Post when ready.** Send the reviewed entries to TallyPrime.

HDFC is the supported bank in this release. Other banks and document types aren't listed as supported.

More tools will be added here as they become available, rather than listed as features before they're built.

## Before you install

- Use a **Windows 10 or later x64 PC**.
- For posting entries, **TallyPrime must be running on the same PC**.
- Setup needs an **internet connection** if Microsoft WebView2 or .NET Framework prerequisites are missing.
- Installing a missing .NET Framework prerequisite may require **admin approval and a restart**. Save your work first.

## Getting started

1. Download the installer linked above.
2. Close any running copy of VoucherTools normally. Let active work finish before installing or updating.
3. Run the installer and choose a writable local program folder. This is a per-user installation, not an all-users installation.
4. Open VoucherTools while connected to the internet for its first signed-release check.
5. Try the importer with a test company and a known statement first. Review the results before choosing to post anything.

Keep backups of your Tally data before using a new tool with working books.

Choosing a different program folder doesn't make the app portable. Application data and update state remain separately under `%LOCALAPPDATA%\VoucherTools`.

## Updates and verification

VoucherTools checks signed release metadata before accepting an update. That metadata identifies the approved installer and its SHA256 fingerprint. A downloaded installer must match the approved bytes.

Hosting an installer on GitHub and approving it for the updater are separate steps. An installer may appear on the Releases page before its signed approval is published.

### Verify the 0.1.0 download manually

This is optional. In PowerShell, run the following from the folder containing the downloaded installer:

```powershell
Get-FileHash -LiteralPath '.\VoucherTools-Setup-0.1.0-x64.exe' -Algorithm SHA256
```

Expected SHA256:

```text
5e93485c74859754738e1bd695c3f6cc539b9ae94582b6830e12f9162cd24dea
```

The installer is **63,148,675 bytes**. This fingerprint applies only to the linked 0.1.0 installer. A checksum comparison alone isn't a substitute for the app's signed metadata checks.

## What's in this repository?

| Item                                                                                | Purpose                                                      |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| [GitHub Releases](https://github.com/yashmangal1203/VoucherTools-Releases/releases) | Downloadable, versioned Windows installers and release notes |
| Numbered root, targets and snapshot JSON files                                      | The signed trust chain and approved installer information    |
| `timestamp.json`                                                                    | Signed freshness information used by the updater             |
| Maintenance files and workflow                                                      | Tools for maintaining the release metadata                   |

These JSON files are public update metadata, not settings to edit when installing the app. Normal users only need the installer. Don't delete or alter metadata to get around a failed verification check.

## Reporting a problem

Use the repository's [Issues page](https://github.com/yashmangal1203/VoucherTools-Releases/issues). Include:

- The VoucherTools version and your Windows version.
- What you were doing, what you expected and what happened instead.
- The exact error message or a redacted screenshot.

**Don't attach real bank statements, account numbers, company data, passwords or signing keys to a public issue.** Use a small anonymized example if a file is needed to explain the problem.

## Independent project

VoucherTools is not affiliated with or endorsed by Tally Solutions or HDFC Bank. Product names belong to their respective owners.
