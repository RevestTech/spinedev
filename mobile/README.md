# Spine — Mobile (SCAFFOLD)

> **Status:** v1.0 scaffold. Per V3 design decision **#28 (Mobile)**,
> v1.0 ships:
>
> 1. a **mobile-API surface** at `shared/api/routes/mobile.py` (compact JSON, fewer fields), and
> 2. a **mobile-responsive web Hub** served by `shared/ui/`,
>
> with **native iOS/Android applications deferred to v1.1+**, on demand.
>
> What lives in this directory is the placeholder project structure +
> signing-cert config + build plan needed so v1.1+ teams (or AI agents)
> can pick up the work without re-deciding scaffolding shape.

---

## v1.0 — what actually ships

| Surface | Where | Notes |
|---|---|---|
| **Mobile-responsive web Hub** | `shared/ui/` (responsive CSS) | Works in iOS Safari + Android Chrome + iPad Safari. Covers "approve on the go" use cases. |
| **Mobile-optimised REST API** | `shared/api/routes/mobile.py` | Compact JSON (short keys, unix seconds, `exclude_none=True`); 4 endpoints (`/approvals`, `/briefings`, `/status`, `/approvals/{id}/action`). |
| **Auth** | Keycloak Bearer JWT | Per **#25** — single identity provider; mobile clients use the standard OIDC refresh-token flow. No mobile-specific auth path. |
| **Placeholder projects** | `mobile/ios/`, `mobile/android/` | Signing-cert config + bundle/package IDs wired; no native code shipped. |

**Explicit v1.0 framing for the website:** *"v1.0 = web-mobile-responsive
Hub via browser; native iOS/Android = v1.1+."*

---

## v1.1+ — native app build plan

Activation trigger: customer demand for native push notifications + lock-screen widgets + offline approval queue.

### iOS

* **Framework:** SwiftUI + Combine; minimum target iOS 17.
* **Auth:** Keycloak via `AppAuth-iOS`; ASWebAuthenticationSession-backed.
* **Push:** APNs → backend webhook → notification with action buttons
  (`Approve` / `Reject`) that POST `/api/v2/mobile/approvals/{id}/action`.
* **Lock-screen widget:** `WidgetKit` poll of `/api/v2/mobile/status`
  (TimelineProvider, refresh every 15 min).
* **Signing:** see [`ios/README.md`](ios/README.md). Cert SHA stored in
  the vendor's vault — NOT in this repo (per **#9**).
* **Distribution:** Apple Business Manager (mid-market+) or App Store
  (solo/founder tier).

### Android

* **Framework:** Jetpack Compose + Kotlin Coroutines; minimum SDK 31.
* **Auth:** Keycloak via `AppAuth-Android`; Chrome Custom Tabs flow.
* **Push:** FCM → backend webhook → notification with action buttons.
* **Lock-screen widget:** Glance API poll of `/api/v2/mobile/status`.
* **Signing:** see [`android/README.md`](android/README.md). Keystore
  reference via vault path — NOT in this repo (per **#9**).
* **Distribution:** Managed Google Play (mid-market+) or Play Store
  (solo/founder tier).

---

## Why scaffold-only on Day 1

Per the **#28 decision rationale** in `docs/V3_DESIGN_DECISIONS.md`:

* Responsive web covers the dominant use case ("approve a card on the
  go") at zero native-app maintenance cost.
* Native apps amortise badly across the 4 deployment shapes (laptop /
  BYOC / customer-cloud / on-prem) — every Hub has a different URL, and
  enterprise tiers expect MDM-pushed app provisioning. Solving that
  ergonomics problem requires customer signal we don't yet have.
* The mobile-API contract (this scaffold) is what lets v1.1+ teams ship
  fast when demand surfaces. The hard part is the contract, not the
  shell.

---

## Directory layout

```
mobile/
├── README.md                 ← this file
├── ios/
│   ├── README.md             ← v1.1+ native iOS build plan
│   ├── Placeholder.xcodeproj/
│   │   ├── project.pbxproj   ← placeholder Xcode project
│   │   └── Spine.xcconfig    ← signing config (bundle ID + team ID env vars)
│   └── .gitignore            ← .xcuserdata, DerivedData, etc.
├── android/
│   ├── README.md             ← v1.1+ native Android build plan
│   ├── Placeholder/
│   │   ├── build.gradle      ← signing config (keystore via vault path)
│   │   └── settings.gradle
│   └── .gitignore            ← local.properties, .gradle/, etc.
└── tests/
    └── test_mobile_api_smoke.py   ← mobile-route registration smoke test
```

---

## How v1.1+ teams pick this up

1. Read this README + `docs/V3_DESIGN_DECISIONS.md` #28.
2. Confirm demand signal recorded in `docs/PRD.md` (post-v1.0 backlog
   item: *"native mobile apps (iOS/Android)"*).
3. Provision Apple Developer / Google Play accounts (vendor-owned, NOT
   customer-owned — the apps are vendor-distributed).
4. Populate vault paths called out in `ios/README.md` +
   `android/README.md` (signing cert SHA + keystore path + Apple Team ID
   + Google Play upload key).
5. Replace `Placeholder.xcodeproj` / `Placeholder/` with real
   SwiftUI / Compose projects; keep the `*.xcconfig` + `build.gradle`
   signing wiring untouched.
6. Wire native push registration to the Hub via
   `POST /api/v2/notifications/devices` (Wave-4 endpoint, exists today).

---

## References

* `docs/V3_DESIGN_DECISIONS.md` #28 (Mobile = SCAFFOLD for v1.0)
* `docs/V3_DESIGN_DECISIONS.md` #25 (Identity = Keycloak embedded)
* `docs/V3_DESIGN_DECISIONS.md` #9 (Vault-only secrets)
* `docs/V3_BUILD_SEQUENCE.md` Wave 6 Stream H
* `shared/api/routes/mobile.py` (the contract)
