# Spine Android (placeholder)

> v1.1+ build plan. Per **#28** v1.0 is web-mobile-responsive only.

## Signing configuration (real even in placeholder)

`Placeholder/build.gradle` wires signing via env vars + vault paths.
**No keystore bytes, no keystore password, no upload-key SHA live in
this repo** (per **#9** — vault-only secrets).

| Gradle property | Source | Where the real value lives |
|---|---|---|
| `applicationId` | env `SPINE_ANDROID_PACKAGE` | committed default: `com.spine.hub` |
| `signingConfigs.release.storeFile` | env `SPINE_ANDROID_KEYSTORE_PATH` | path to file decrypted from vault at CI time |
| `signingConfigs.release.storePassword` | env `SPINE_ANDROID_KEYSTORE_PASSWORD` | vault path `spine/android/keystore_password` |
| `signingConfigs.release.keyAlias` | env `SPINE_ANDROID_KEY_ALIAS` | vault path `spine/android/key_alias` |
| `signingConfigs.release.keyPassword` | env `SPINE_ANDROID_KEY_PASSWORD` | vault path `spine/android/key_password` |
| Upload key SHA-256 | — | **vault path** `spine/android/upload_key_sha256` (NEVER in repo) |

## CI signing flow (v1.1+ wiring; documented for future agents)

```sh
# Fetch from vendor's vault (per #9)
export SPINE_ANDROID_KEYSTORE_PASSWORD="$(spine secret get spine/android/keystore_password)"
export SPINE_ANDROID_KEY_ALIAS="$(spine secret get spine/android/key_alias)"
export SPINE_ANDROID_KEY_PASSWORD="$(spine secret get spine/android/key_password)"

# Decrypt the keystore at build time (vault-backed)
spine secret get spine/android/upload_keystore --b64 | base64 -d > /tmp/spine-upload.keystore
export SPINE_ANDROID_KEYSTORE_PATH=/tmp/spine-upload.keystore

# Build (build.gradle reads the env vars)
./gradlew :Placeholder:bundleRelease
shred -u /tmp/spine-upload.keystore
```

## Why an empty Android project ships today

* Files prove the **wiring contract** — package ID, signing config,
  keystore path all flow from env vars sourced from vault.
* v1.1+ teams replace `Placeholder/src/main/` with the real Compose app
  without touching `build.gradle` signing wiring or `.gitignore`.
* No `app/` directory yet because the package is named `Placeholder` —
  v1.1+ activation renames to `app/` to match Android Studio convention.

## What native app v1.1+ will deliver

* Jetpack Compose UI for: decision queue, approval card, role chat,
  briefings feed.
* Glance API lock-screen widget polling `/api/v2/mobile/status`.
* FCM push registration → backend at
  `POST /api/v2/notifications/devices`.
* `AppAuth-Android` Keycloak OIDC flow (per **#25**) using Chrome
  Custom Tabs.
* WorkManager background polling of `/api/v2/mobile/approvals`.
