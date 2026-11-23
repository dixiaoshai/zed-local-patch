> [!IMPORTANT]
> Remove this line to confirm you've reviewed this PR before submitting.

# Zed

## Zed Local Patch on macOS

Build the app with the repository's Rust toolchain and the macOS toolchain on your `PATH`:

```sh
env -u ZED_RELEASE_CHANNEL \
  ZED_UPDATE_EXPLANATION='Local build: apply patch and rebuild to update' \
  cargo build --locked --release --target-dir target -p zed --bin zedlocalpatch &&
  script/bundle-local-patch-mac
```

The script packages the optimized binary as `.local-build/Zed Local Patch Release.app` without installing it or overwriting an existing bundle. It uses separate default settings and data directories from official Zed. The build uses the dev release channel for isolation; the dev channel stores credentials in a local JSON file rather than Keychain by default. Leave `ZED_RELEASE_CHANNEL` unset when launching the app. Use the optimized bundle rather than a debug build when comparing scrolling performance with official Zed.

Local fixes and their investigation notes live in [`local-notes/`](local-notes/). Most recently, the Call Hierarchy panel no longer re-requests the language server on progress notifications that its own request caused; see [local-notes/call-hierarchy-progress-loop.md](local-notes/call-hierarchy-progress-loop.md) for the root cause, the ~80 requests/second loop it used to trigger with jdtls, and the regression test that guards it.

[![Zed](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/zed-industries/zed/main/assets/badge/v0.json)](https://zed.dev)
[![CI](https://github.com/zed-industries/zed/actions/workflows/run_tests.yml/badge.svg)](https://github.com/zed-industries/zed/actions/workflows/run_tests.yml)

Welcome to Zed, a high-performance, multiplayer code editor from the creators of [Atom](https://github.com/atom/atom) and [Tree-sitter](https://github.com/tree-sitter/tree-sitter).

---

### Installation

On macOS, Linux, and Windows you can [download Zed directly](https://zed.dev/download) or install Zed via your local package manager ([macOS](https://zed.dev/docs/installation#macos)/[Linux](https://zed.dev/docs/linux#installing-via-a-package-manager)/[Windows](https://zed.dev/docs/windows#package-managers)).

Other platforms are not yet available:

- Web ([tracking discussion](https://github.com/zed-industries/zed/discussions/26195))

### Developing Zed

- [Building Zed for macOS](./docs/src/development/macos.md)
- [Building Zed for Linux](./docs/src/development/linux.md)
- [Building Zed for Windows](./docs/src/development/windows.md)

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for ways you can contribute to Zed.

Also... we're hiring! Check out our [jobs](https://zed.dev/jobs) page for open roles.

### Licensing

Zed source code is licensed primarily under GPL-3.0-or-later, with Apache-2.0 components where marked.

License information for third party dependencies must be correctly provided for CI to pass.

We use [`cargo-about`](https://github.com/EmbarkStudios/cargo-about) to automatically comply with open source licenses. If CI is failing, check the following:

- Is it showing a `no license specified` error for a crate you've created? If so, add `publish = false` under `[package]` in your crate's Cargo.toml.
- Is the error `failed to satisfy license requirements` for a dependency? If so, first determine what license the project has and whether this system is sufficient to comply with this license's requirements. If you're unsure, ask a lawyer. Once you've verified that this system is acceptable add the license's SPDX identifier to the `accepted` array in `script/licenses/zed-licenses.toml`.
- Is `cargo-about` unable to find the license for a dependency? If so, add a clarification field at the end of `script/licenses/zed-licenses.toml`, as specified in the [cargo-about book](https://embarkstudios.github.io/cargo-about/cli/generate/config.html#crate-configuration).

## Sponsorship

Zed is developed by **Zed Industries, Inc.**, a for-profit company.

If you’d like to financially support the project, you can do so via GitHub Sponsors.
Sponsorships go directly to Zed Industries and are used as general company revenue.
There are no perks or entitlements associated with sponsorship.
