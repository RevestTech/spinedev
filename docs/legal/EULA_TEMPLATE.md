# End-User License Agreement (EULA) — TEMPLATE

> **⚠️ This is a SKELETON for legal red-line, NOT a binding agreement and
> NOT legal advice.** Engage qualified counsel in your jurisdiction
> before publishing or signing. Bracketed `[…]` fields require
> finalization. Marked `// TODO: legal` lines flag substantive holes.

---

**Spine Software License**
**Effective Date:** `[YYYY-MM-DD]`
**Licensor:** `[Vendor Legal Entity Name]` ("Spine," "we," "us," "our")
**Licensee:** The individual or entity identified at order acceptance
("Customer," "you," "your")

This End-User License Agreement ("Agreement") governs your access to and
use of the Spine Hub software, container images, documentation, and any
related materials we make available (collectively, the "Software"). By
installing, deploying, or otherwise using the Software, you agree to be
bound by this Agreement.

---

## 1. Definitions

- **"Hub"** — the containerized Spine product per `docs/V3_DESIGN_DECISIONS.md` #3 that you deploy on your own infrastructure.
- **"Deployment Shape"** — one of the four deployment topologies enumerated in `docs/DEPLOYMENT_SHAPES.md`: (a) laptop, (b) bring-your-own-cloud (BYOC), (c) customer-cloud Kubernetes, (d) on-premises.
- **"Tier"** — one of the three license tiers: Solo, Startup, Enterprise, distinguished by the feature flags activated in your license bundle per `docs/LICENSING_GUIDE.md` and #23.
- **"License Bundle"** — the Ed25519-signed manifest issued by Spine that activates feature flags + sets quota limits + binds to your customer identifier.
- **"Customer Data"** — all data Customer ingests, generates, or causes the Hub to process, including source code, audit records, vault contents, and Hub configuration.
- **"Telemetry"** — anonymized usage signals optionally sent to Spine under the Smart Spine 3-tier learning loop per #27 + `learning/`.
- **"Documentation"** — the Markdown files under `docs/` distributed with the Software.

## 2. License Grant

Subject to your compliance with this Agreement and timely payment of all
applicable fees, Spine grants you a **limited, non-exclusive,
non-transferable, non-sublicensable, revocable** license, during the
term, to:

- (a) deploy and operate the Hub container images on infrastructure you
  own or lawfully control, in any Deployment Shape, for the number of
  end users + projects authorized by your active License Bundle;
- (b) make a reasonable number of backup copies of the Software solely
  for disaster recovery and operational continuity per the procedures in
  `docs/DR_RUNBOOK.md`;
- (c) integrate the Hub with your own systems through the documented
  REST API + MCP surfaces (`shared/api/`, `shared/mcp/`) per the rate
  limits + feature flags encoded in your License Bundle.

## 3. License Restrictions

You will not, and will not permit any third party to:

- (a) copy, modify, translate, or create derivative works of the
  Software, except as expressly permitted by this Agreement or by
  applicable law that cannot lawfully be waived;
- (b) reverse engineer, decompile, disassemble, or otherwise attempt to
  derive the source code, structure, or algorithms of any portion of the
  Software not distributed in source form, except to the extent
  applicable law expressly permits despite this restriction;
- (c) rent, lease, lend, sell, sublicense, time-share, host as a
  service, or otherwise commercially exploit the Software;
- (d) circumvent, disable, or interfere with the License Bundle
  verification logic, feature-flag gates, quota limits, or audit-ledger
  hash chain;
- (e) remove or alter any proprietary notices, branding, or trust
  anchors (including `TRUSTED_VENDOR_FINGERPRINT`) baked into the
  Software;
- (f) use the Software in any manner that violates applicable export-
  control or sanctions laws (see §13);
- (g) operate the Hub in a Deployment Shape, Tier, or capacity in
  excess of what your active License Bundle authorizes.

Per design decision #18, Spine v1.0 is **closed source**. No
source-code license is granted or implied.

## 4. Tier-Based Usage

Your License Bundle declares one or more active feature flags + quota
limits. The Hub enforces these via the feature-flag middleware
(`shared/api/feature_flag.py`) and the per-org rate limiter
(`shared/api/rate_limit.py`).

You will not attempt to access features or exceed quotas not authorized
by your active Bundle. Spine may, at its option, downgrade or suspend
service if our remote heartbeat (per #31) or evidence-store metrics
indicate use materially exceeds the licensed envelope.

- **Solo tier:** single end user, single project workspace, up to
  `[N]` agent-hours/month.  // TODO: legal — finalize cap
- **Startup tier:** up to `[N]` end users, up to `[N]` projects, up to
  `[N]` agent-hours/month, federation disabled.  // TODO: legal
- **Enterprise tier:** unlimited end users + projects within your
  organization, federation enabled, custom SLA per separate Order Form
  or Master Services Agreement.

## 5. Customer Data Ownership; Self-Hosted Posture

You retain all right, title, and interest in and to Customer Data.
Spine does not access, copy, or take custody of Customer Data; per #15
the Hub is self-hosted at every Tier and Spine holds no customer
secrets, source code, or audit-ledger contents.

The only data that may transit to Spine is:
- (a) License Bundle heartbeat metadata (license ID, timestamps,
  feature-flag fingerprint, quota counters) per #23 + #31; and
- (b) Telemetry, only if you have explicitly enabled the Smart Spine
  3-tier learning loop opt-in (§9).

You are solely responsible for the lawful collection, processing, and
retention of all Customer Data, including compliance with applicable
data-protection law (e.g., GDPR, CCPA, HIPAA where applicable).

## 6. Telemetry; Smart Spine Learning Loop

The Hub ships with a 3-tier learning loop per #27 implemented under
`learning/`. **All three tiers are OFF by default.** No Customer Data
or Telemetry is sent to Spine unless you enable one or more tiers
through the Hub admin UI + confirm via the on-screen consent flow.

Tier definitions and the categories of data each transmits are
documented in `learning/README.md` and reproduced in your Data
Processing Addendum (DPA). All transmitted Telemetry is anonymized at
the source by the in-Hub anonymizer (`learning/anonymizer.py`) prior to
egress.

You may revoke consent for any tier at any time through the Hub admin
UI. Revocation is immediate; previously transmitted Telemetry that has
been incorporated into anonymized aggregate models is not retroactively
removable.

## 7. Term and Termination

- **Term.** This Agreement commences on the Effective Date and continues
  for the period your License Bundle is valid, unless earlier terminated
  per this §7.
- **Termination for breach.** Either party may terminate immediately on
  written notice if the other materially breaches and fails to cure
  within `[30]` days of notice.
- **Termination for non-payment.** Spine may suspend or revoke your
  License Bundle (which disables feature flags via #23) if invoices are
  not paid within `[30]` days of due date.
- **Effect of termination.** On termination, you will (a) cease all use
  of the Software within `[7]` days, (b) destroy all copies, and
  (c) certify destruction in writing on request. Sections that by their
  nature survive (4, 5, 8–14) survive termination.

## 8. Updates and Patches

Spine may, at its option, make available patches, minor releases, and
major version upgrades. Customer is responsible for deploying security
patches in accordance with `docs/SECURITY_GUIDE.md` and our published
support window. Spine has no obligation to support End-of-Life versions
beyond the dates published at `[support URL]`.  // TODO: legal —
finalize support-window policy

## 9. Warranties; Disclaimers

EXCEPT AS EXPRESSLY SET FORTH HEREIN OR IN A SEPARATE ORDER FORM, THE
SOFTWARE IS PROVIDED **"AS IS" AND "AS AVAILABLE"** WITHOUT WARRANTY OF
ANY KIND. SPINE DISCLAIMS ALL WARRANTIES, EXPRESS, IMPLIED, OR
STATUTORY, INCLUDING WITHOUT LIMITATION ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, AND
NON-INFRINGEMENT.

Spine does not warrant that the Software will be uninterrupted,
error-free, or that LLM-generated output will be accurate, complete,
suitable for your purposes, or free of bias. **You are responsible for
reviewing all AI-generated artifacts before deploying them to
production.**

## 10. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT WILL EITHER PARTY'S
TOTAL CUMULATIVE LIABILITY UNDER THIS AGREEMENT EXCEED **THE FEES PAID
OR PAYABLE BY YOU TO SPINE FOR THE TWELVE (12) MONTHS PRECEDING THE
EVENT GIVING RISE TO LIABILITY**.

NEITHER PARTY WILL BE LIABLE FOR ANY INDIRECT, INCIDENTAL,
CONSEQUENTIAL, SPECIAL, EXEMPLARY, OR PUNITIVE DAMAGES, INCLUDING LOST
PROFITS, REVENUE, DATA, OR GOODWILL, EVEN IF ADVISED OF THE POSSIBILITY.

The above limitations do not apply to: (a) Customer's payment
obligations, (b) breach of §3 (License Restrictions), (c) Customer's
indemnification obligations under §11, or (d) liabilities that cannot
be limited under applicable law.  // TODO: legal — confirm enforceable
in target jurisdictions

## 11. Indemnification

- **By Spine:** Spine will defend Customer against any third-party claim
  alleging that the Software, as delivered and used in accordance with
  this Agreement, infringes a third party's `[copyright / patent /
  trade-secret]` rights, and indemnify Customer for damages awarded in
  such claim. Exclusions: claims arising from (i) Customer Data, (ii)
  modifications not made by Spine, (iii) use combined with non-Spine
  products where the Software alone would not infringe, (iv) use of an
  EOL version after a non-infringing version was made available.
- **By Customer:** Customer will defend Spine against any third-party
  claim arising from Customer Data or Customer's use of the Software in
  violation of this Agreement, and indemnify Spine for damages awarded.

## 12. Confidentiality

Each party will treat the other's non-public information disclosed under
this Agreement (including License Bundle contents, pricing, roadmaps,
and security incident details) as confidential, use it only for purposes
of this Agreement, and protect it with no less than reasonable care.

## 13. Export Control; Sanctions

You represent that you are not located in, and will not provide access
to the Software to any party located in, a jurisdiction subject to
comprehensive US or EU sanctions, and that you are not on any
US-restricted-party list. You will not export, re-export, or transfer
the Software in violation of applicable export-control law.

## 14. Governing Law; Venue; Dispute Resolution

This Agreement is governed by the laws of `[State / Country]`, without
regard to conflict-of-laws principles. The parties consent to the
exclusive jurisdiction of the state and federal courts located in
`[County, State]` for any dispute not subject to arbitration.

`[Optional arbitration clause]`  // TODO: legal — JAMS / AAA / ICDR?

## 15. Notices

Notices to Spine must be sent to `[legal@spine.dev]`. Notices to
Customer will be sent to the email address on Customer's most recent
Order Form. Notices are effective upon delivery confirmation.

## 16. General

- **Entire agreement.** This Agreement (together with any Order Form,
  MSA, or DPA) is the complete agreement between the parties and
  supersedes prior agreements on the same subject.
- **Amendments.** Modifications require a writing signed by both
  parties.
- **Assignment.** Customer may not assign without Spine's prior written
  consent; Spine may assign in connection with a merger or sale of
  substantially all assets.
- **Severability.** If any provision is held unenforceable, the
  remaining provisions remain in effect.
- **No waiver.** A party's failure to enforce a provision is not a
  waiver of future enforcement.
- **Force majeure.** Neither party is liable for failures caused by
  events beyond reasonable control (war, pandemic, sustained
  cloud-provider outage, etc.).
- **Independent contractors.** The parties are independent contractors;
  this Agreement creates no agency, partnership, or joint venture.

---

**Acknowledged and accepted:**

`[Customer Legal Entity]`           `[Vendor Legal Entity]`
By: ____________________            By: ____________________
Name: __________________            Name: __________________
Title: _________________            Title: _________________
Date: __________________            Date: __________________

---

> **End of EULA template.** Companion documents:
> - `docs/legal/MSA_TEMPLATE.md` — Master Services Agreement for
>   Enterprise tier
> - `docs/legal/DPA_TEMPLATE.md` — Data Processing Addendum
