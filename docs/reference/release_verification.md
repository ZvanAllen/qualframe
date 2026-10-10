# Release installation verification

The release is currently a screened source ZIP, not a signed Windows or macOS
installer. Python 3.11 or newer and dependency installation are required. The
archive includes application code, configuration assets, documentation and
fictional demonstration fixtures. Research studies, generated runs, private
workbooks, credentials and Git history are excluded.

## Create a local candidate

From the checkout root:

```bash
python scripts/package_public_release.py --dry-run
python scripts/package_public_release.py --output artifacts/release/candidate.zip
```

Choose a new output filename for each candidate. The adjacent manifest lists
every selected file, its size and SHA-256, plus the archive checksum. Files are
screened and archived from the same captured bytes. Links to files omitted from
the archive fail screening, even when those files exist in the working checkout.
Root-file links, unsupported file types and personal paths are also rejected.

An optional local `--private-fingerprints` JSON array adds known private file and
text hashes to the screen. Neither these values nor that input file are copied
into the candidate. The receipt records only how many fingerprints were checked.
This supplements the allowlist and manual inventory review; it is not proof that
arbitrary prose contains no sensitive information. Screenshots need visual review.

## Exercise an isolated installation offline

Prepare a wheelhouse with the runtime dependencies already available locally.
Dependency collection may require internet access on a connected development
machine; the preflight itself never downloads packages. The invoking Python must
already have setuptools 69 or newer and wheel build support.

```bash
python scripts/release_preflight.py --archive artifacts/release/candidate.zip --wheelhouse artifacts/local-wheelhouse --work-dir artifacts/release/trial-1 --dry-run
python scripts/release_preflight.py --archive artifacts/release/candidate.zip --wheelhouse artifacts/local-wheelhouse --work-dir artifacts/release/trial-1
```

The work directory must be new. The preflight:

1. Verifies the archive and every inventoried member before extraction.
2. Builds an application wheel using the invoking Python's existing build tools.
3. Creates an isolated virtual environment and installs only from local wheels.
4. Checks dependency consistency, the installed CLI and bundled browser assets.
5. Runs both synthetic demonstrations with mock/cached providers.
6. Starts the installed application's loopback server, checks its workspace,
   review and comparison pages, stops that owned process, and reopens the same
   study on the same port.
7. Confirms that sources and model artifacts are unchanged and no human decisions
   were recorded. Writes a receipt naming the tested archive and platform.

Provider credentials, proxy settings and user pip configuration are not passed to
the trial. It does not open a browser, use existing services, or stop other app
processes. Its shutdown check uses a private test process control channel; the
researcher's normal console shutdown remains Ctrl+C.

The runtime environment is isolated; building with already installed tools is
recorded separately. A passing receipt applies to that archive and dependency
set. Changes after packaging require a new candidate and verification.

## Platform and publication boundaries

CI is configured to run the source tests and this archive installation check on
Windows, macOS and Linux with Python 3.11 and 3.12. A configured CI job is not a
successful platform trial. Record actual job results and test Python installation,
browser use, terminal shutdown and permissions on a physical macOS machine before
claiming macOS end-user verification.

This check establishes installation and synthetic application behavior. It does
not validate paid providers, research accuracy, usability, signed installers or
clean-machine dependency acquisition. Publishing requires the owner's approval
and review of the final inventory. Keep the MIT notice and consistent software
version in the package metadata and citation file; a local candidate does not
change the software's release date.
