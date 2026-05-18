# Spine iOS (placeholder)

> v1.1+ build plan. Per **#28** v1.0 is web-mobile-responsive only.

## Signing configuration (real even in placeholder)

All signing identifiers are wired via `Spine.xcconfig` so the native
build, when it lands in v1.1+, picks them up without code changes. **No
cert SHA, no provisioning profile bytes, no Team ID values live in this
repo** (per **#9** — vault-only secrets).

| Config key | Source | Where the real value lives |
|---|---|---|
| `PRODUCT_BUNDLE_IDENTIFIER` | env `SPINE_IOS_BUNDLE_ID` | committed default: `com.spine.hub` |
| `DEVELOPMENT_TEAM` | env `SPINE_IOS_TEAM_ID` | vendor's Apple Developer account; **set in CI from `vault://spine/ios/team_id`** |
| `CODE_SIGN_IDENTITY` | `Apple Distribution` | static |
| `CODE_SIGN_STYLE` | `Manual` | enterprise-grade builds require manual signing |
| `PROVISIONING_PROFILE_SPECIFIER` | env `SPINE_IOS_PROVISIONING_PROFILE` | vault-stored UUID |
| Signing certificate SHA-1 | — | **vault path** `spine/ios/signing_cert_sha1` (NEVER in repo) |

## CI signing flow (v1.1+ wiring; documented for future agents)

```sh
# Fetch from vendor's vault (per #9)
export SPINE_IOS_TEAM_ID="$(spine secret get spine/ios/team_id)"
export SPINE_IOS_PROVISIONING_PROFILE="$(spine secret get spine/ios/provisioning_profile_uuid)"

# Decrypt + install the .p12 signing cert at build time (vault-backed)
spine secret get spine/ios/signing_cert_p12 --b64 | base64 -D > /tmp/spine.p12
security import /tmp/spine.p12 -k login.keychain -P "$(spine secret get spine/ios/signing_cert_password)"
rm /tmp/spine.p12

# Now build — Spine.xcconfig reads the env vars
xcodebuild -project Placeholder.xcodeproj -scheme Spine -configuration Release archive
```

## Why an empty Xcode project ships today

* Files in the project structure prove the **wiring contract** — Team ID
  + bundle ID + signing style + provisioning-profile reference all
  resolve via env vars sourced from vault.
* v1.1+ teams replace `Placeholder/` source files with the real SwiftUI
  app without touching `Spine.xcconfig` or `.gitignore`.
* `project.pbxproj` is minimal — opens in Xcode without error but builds
  to an empty bundle. Replacement is expected.

## What native app v1.1+ will deliver

* SwiftUI views for: decision queue, approval card, role chat,
  briefings feed.
* `WidgetKit` lock-screen widget (TimelineProvider polls
  `/api/v2/mobile/status`).
* APNs push registration → backend at
  `POST /api/v2/notifications/devices`.
* `AppAuth-iOS` Keycloak OIDC flow (per **#25**).
* Background app refresh poll of `/api/v2/mobile/approvals` for
  notification badge accuracy.
