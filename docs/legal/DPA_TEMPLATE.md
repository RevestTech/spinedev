# Data Processing Addendum (DPA) — TEMPLATE

> **⚠️ SKELETON for legal red-line, NOT a binding agreement and NOT
> legal advice.** Addendum to the EULA + MSA. The self-hosted posture
> per #15 means Customer is overwhelmingly Controller AND Processor for
> Customer Data; Spine is a Sub-processor only for the narrow
> heartbeat + opt-in Telemetry surfaces. Engage qualified privacy
> counsel. `// TODO: legal/privacy` marks substantive holes.

---

**Data Processing Addendum**
**Effective Date:** `[YYYY-MM-DD]`
**Controller / Data Exporter:** `[Customer Legal Entity Name]` ("Customer")
**Processor / Data Importer:** `[Vendor Legal Entity Name]` ("Spine")

This Data Processing Addendum ("DPA") supplements the EULA + MSA
between the parties and governs the limited Personal Data that Spine
processes on behalf of Customer in connection with the Spine Hub.

Capitalized terms not defined herein have the meanings given in the
EULA, MSA, or the data-protection law applicable to a given processing
activity (e.g., GDPR Article 4, CCPA §1798.140).

---

## 1. Scope; Self-Hosted Posture

Per design decision #15, the Spine Hub is **self-hosted at every
Tier**. As between the parties:

- **Customer Data inside the Hub** (source code, secrets, audit
  ledger, vault contents, Hub configuration, all data Customer
  ingests or generates through the Hub): Customer is the sole
  Controller and the sole Processor. Spine has no access, no custody,
  no copy, and no decryption capability over this data. This DPA does
  not cover Spine processing of Customer Data inside the Hub because
  no such processing occurs.

- **License Bundle Heartbeat Metadata** (license ID, timestamps,
  feature-flag fingerprint, quota counters): transmitted from the Hub
  to Spine to sustain the License Bundle (per #23) and remote
  heartbeat (per #31). Spine acts as Processor on Customer's behalf
  for this narrow purpose only.

- **Smart Spine Telemetry** (anonymized usage signals per #27 +
  `learning/`): transmitted from the Hub to Spine **only when
  Customer has explicitly enabled one or more learning-loop tiers
  through the Hub admin UI**. All Telemetry is anonymized in-Hub by
  `learning/anonymizer.py` prior to egress.

This DPA governs Spine's processing for the two narrow surfaces above.
The Hub itself is not within scope.

## 2. Roles and Responsibilities

- **Customer is the Controller** (and where applicable, the
  Business per CCPA) for all Personal Data processed inside the Hub
  or contained in the License Bundle metadata. Customer determines the
  purposes and means of processing.
- **Spine is a Processor** (and where applicable, a Service Provider
  per CCPA) for the limited surfaces in §1. Spine processes only on
  documented instructions from Customer, which the parties agree are
  embodied in the EULA, MSA, this DPA, and any subsequent written
  instruction.

## 3. Categories of Data; Categories of Data Subjects

**License Bundle Heartbeat Metadata:**
- License identifier (UUID)
- Customer organization identifier
- Feature-flag manifest fingerprint
- Quota counters (calls / agent-hours / projects)
- Hub version + deployment-shape identifier
- Heartbeat timestamps + source IP at egress

  *Data subjects:* the natural person(s) listed as administrative
  contacts on the Order Form. No end-user, project, or content data is
  transmitted in heartbeat metadata.

**Smart Spine Telemetry (opt-in only):**
- Tier 1 (anonymized usage events): event type, role identifier,
  duration, error class
- Tier 2 (anonymized prompt/response shapes): token counts, model
  identifier, redacted/hashed token-class signatures
- Tier 3 (federated learning gradients): model gradients with
  differential-privacy noise

  *Data subjects:* end users of the Hub. All identifiers are
  hashed/pseudonymized at source; Spine cannot re-identify individual
  end users without combination with data Spine does not hold.

`// TODO: legal/privacy` — finalize the precise field list per tier
against `learning/anonymizer.py` schema; align with PIA findings.

## 4. Sub-Processors

Spine engages the following sub-processors for the surfaces in §1.
Current list maintained at `[https://spine.dev/legal/subprocessors]`.

| Sub-processor | Purpose | Location |
|---|---|---|
| `[Cloud provider]` | License Bundle service hosting | `[Region]` |
| `[Email provider]` | Notice + support correspondence | `[Region]` |
| `[Status page provider]` | Status communication | `[Region]` |

Spine will notify Customer at least `[30]` days before adding or
replacing a sub-processor. Customer may object on reasonable
data-protection grounds; if the parties cannot resolve the objection,
Customer may terminate the affected Order Form without further
liability.

## 5. International Transfers

Where Personal Data subject to EU/UK/Swiss data-protection law is
transferred to a third country without an adequacy decision, the
transfer is governed by the European Commission's Standard Contractual
Clauses (Decision 2021/914) Module Two (Controller-to-Processor),
incorporated by reference and completed as follows:

- **Module:** Two
- **Docking clause:** applies
- **Optional clauses (7, 11):** apply
- **Annex I.A (parties):** as listed at the top of this DPA
- **Annex I.B (categories of data, frequency, retention):** §3 + §9
- **Annex I.C (competent supervisory authority):** the supervisory
  authority of the Member State in which Customer is established
- **Annex II (technical and organizational measures):** §8 + Spine's
  `docs/SECURITY_GUIDE.md`
- **Annex III (sub-processors):** §4

For UK transfers, the UK International Data Transfer Addendum to the
EU SCCs is incorporated. For Swiss transfers, references in the SCCs
to GDPR are deemed to include the Swiss FADP where applicable.

`// TODO: legal/privacy` — confirm whether Customer requires execution
of separate SCC document vs. incorporation by reference.

## 6. Customer Instructions; Lawfulness

Customer instructs Spine to process the data in §3 for:

- (a) verifying license validity, enforcing feature-flag gates,
  monitoring quota consumption (#23);
- (b) remote-heartbeat health monitoring + license revocation if
  fraud or compromise is suspected (#31);
- (c) if and only if Customer opts in, improving the Smart Spine
  learning models and Spine's hosted aggregate analytics (#27).

Spine will not process Personal Data for any other purpose without
Customer's prior written instruction. Spine will inform Customer
without undue delay if it cannot follow an instruction or believes an
instruction violates applicable law.

## 7. Personnel; Confidentiality

Spine ensures personnel authorized to process Personal Data: (a) are
bound by written confidentiality obligations, (b) receive appropriate
data-protection training, and (c) access Personal Data only on a
need-to-know basis aligned with the limited scope of §1.

## 8. Security Measures

Spine maintains the technical and organizational measures described in
`docs/SECURITY_GUIDE.md`, including (without limitation):

- TLS 1.2+ in transit for all heartbeat + Telemetry endpoints
- Encryption at rest (AES-256) for stored heartbeat metadata
- Strict RBAC + audit logging on Spine's License Bundle service
- Annual penetration test + `[SOC 2 Type II]` report on the
  License Bundle service + Telemetry ingest
- Vendor-key custody under Shamir 3-of-5 split per `license/shamir.py`
- Incident response per `docs/SECURITY_GUIDE.md` Section `[X]`

Customer acknowledges that the Hub itself runs on Customer
infrastructure; the security of Customer Data inside the Hub depends
on Customer's deployment-environment controls.

## 9. Data Retention; Return; Deletion

- **Heartbeat metadata:** retained `[24 months]` from receipt, then
  deleted or anonymized.
- **Telemetry (opt-in):** retained per the tier the Customer enabled,
  as described in `learning/README.md`; revocable at any time via the
  Hub admin UI.
- **On termination of all Order Forms:** Spine deletes or anonymizes
  all Personal Data covered by this DPA within `[60]` days, unless
  retention is required by applicable law. Spine certifies deletion on
  request.

## 10. Data Subject Rights

Spine will, to the extent legally permissible, assist Customer in
responding to verifiable data-subject requests (access, deletion,
correction, portability, objection, restriction). Because Spine
processes only pseudonymized/anonymized data per §3, fulfilling
individual requests may require Customer to provide additional
identifiers; Spine will use commercially reasonable efforts to assist.

Spine will not respond directly to a data subject regarding Customer
Data without Customer's prior consent, except as required by law.

## 11. Personal Data Breach Notification

Spine will notify Customer **without undue delay and in any event
within 72 hours** of becoming aware of a Personal Data Breach
affecting Personal Data Spine processes under this DPA. Notice will
include, to the extent known: (a) nature of the breach + categories +
approximate number of records affected, (b) likely consequences,
(c) measures taken or proposed, (d) Spine contact for further info.

The Hub itself runs on Customer infrastructure; breaches of the Hub
deployment are Customer's responsibility to detect, respond to, and
notify regulators about as Controller.

## 12. Audits

Customer may audit Spine's compliance with this DPA not more than
once per calendar year, on `[30]` days' written notice, during
business hours, under NDA. Audit may be satisfied by Spine providing
its then-current `[SOC 2 Type II]` report or equivalent certification.
On-site audits are at Customer's expense unless the audit reveals a
material breach by Spine.

## 13. Liability; Damages

Liability arising out of or relating to this DPA is subject to the
limitations in the MSA §12. The SCCs provisions on liability (Module
Two, Clause 12) supplement this section solely as to claims by EU/UK
data subjects.

## 14. Conflict; Term

In case of conflict between this DPA and the MSA or EULA on a
data-protection matter, this DPA controls. In case of conflict between
this DPA and the SCCs on transfers covered by the SCCs, the SCCs
control.

This DPA remains in effect for as long as Spine processes Personal
Data under the EULA + MSA. Sections on retention (§9), audits (§12),
liability (§13), and surviving obligations of confidentiality survive
termination.

---

**Acknowledged and accepted:**

**`[Customer Legal Entity]`**          **`[Vendor Legal Entity]`**
By: ____________________               By: ____________________
Name: __________________               Name: __________________
Title: _________________               Title: _________________
Date: __________________               Date: __________________

---

> **End of DPA template.** Companion documents:
> - `docs/legal/EULA_TEMPLATE.md` — End-User License Agreement
> - `docs/legal/MSA_TEMPLATE.md` — Master Services Agreement
