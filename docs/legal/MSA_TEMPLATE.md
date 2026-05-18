# Master Services Agreement (MSA) — TEMPLATE

> **⚠️ SKELETON for legal red-line, NOT a binding agreement and NOT
> legal advice.** For Enterprise-tier deployments of Spine Hub.
> Order Forms incorporate this MSA by reference. Engage qualified
> counsel before publishing. `// TODO: legal` marks substantive holes.

---

**Spine Master Services Agreement**
**Effective Date:** `[YYYY-MM-DD]`
**Spine:** `[Vendor Legal Entity Name]` ("Spine")
**Customer:** `[Customer Legal Entity Name]` ("Customer")

This Master Services Agreement ("MSA") governs Spine's provision of the
Software, support, and any Professional Services described in one or
more Order Forms executed by the parties referencing this MSA.

Defined terms not defined herein have the meanings given in the
[`EULA_TEMPLATE.md`](EULA_TEMPLATE.md) ("EULA"), which is incorporated
into and supplements this MSA. To the extent of conflict between this
MSA and the EULA, this MSA controls for Enterprise-tier deployments.

---

## 1. Scope; Order Forms

Spine will provide the products, support, and Professional Services
described in one or more mutually executed Order Forms. Each Order Form
identifies: (a) the Deployment Shape, (b) the activated feature flags +
quotas in Customer's License Bundle, (c) the term, (d) the fees and
payment schedule, and (e) any custom SLA, Professional Services
deliverables, or non-standard terms.

## 2. Self-Hosted Posture; Data Custody

Per design decision #15, the Hub is **self-hosted at every Tier**.
Spine does not access, copy, or take custody of:

- Customer source code
- Customer secrets or vault contents
- The Hub's hash-chained audit ledger (#24)
- Any data Customer processes through the Hub

The only data transmitted from the Hub to Spine is (a) License Bundle
heartbeat metadata per #23 + #31 and (b) anonymized Smart Spine
Telemetry, only when Customer has explicitly opted in per the EULA §6.

Customer remains the sole controller and processor of all Customer Data
for purposes of applicable data-protection law. Where Spine's limited
processing role (heartbeat + opt-in Telemetry) requires it, the parties
will execute a Data Processing Addendum in the form of
`docs/legal/DPA_TEMPLATE.md`.

## 3. License; Use Rights

Subject to Customer's compliance with this MSA and timely payment,
Spine grants Customer the license described in EULA §2, extended for
Enterprise tier as specified in the applicable Order Form. Federation
across multiple Hubs (#10 + #16) is enabled at Enterprise tier and may
be exercised only between Hubs operated by Customer or by Customer's
Affiliates as defined in this MSA.

## 4. Professional Services

If the Order Form specifies Professional Services (e.g., onboarding
support, deployment-shape rehearsals, custom IDP integration, custom
charter authoring), Spine will perform them in a workmanlike manner in
accordance with the Statement of Work attached to or referenced by the
Order Form. Deliverables become Customer's property on full payment;
Spine retains rights in any Spine background IP incorporated.

## 5. Support; Service Levels

Spine will provide support per the support tier identified in the Order
Form. Default Enterprise support includes:

- `[24×7]` access to designated support contacts via `[email / ticket
  portal / Slack Connect channel]`
- `[Response time targets by severity]`  // TODO: legal — finalize
  table (P1 / P2 / P3 / P4 with response + resolution targets)
- Security patches per `docs/SECURITY_GUIDE.md`
- Quarterly business review at Customer's option

Service-level commitments (uptime, response times) apply only to
components Spine controls (the License Bundle service, the Telemetry
ingest endpoint when opted-in). The Hub itself runs on Customer
infrastructure and is not subject to Spine uptime SLA — Customer is
responsible for the operational availability of the deployment.

## 6. Fees; Payment; Taxes

- **Fees.** As specified in the Order Form. Annual subscription paid
  in advance by default; alternative payment cadences require Spine
  agreement.
- **Invoices.** Issued on the Order Form schedule. Payment due net
  `[30]` days from invoice date.
- **Late payment.** `[1.5%]` per month or the maximum permitted by
  law, plus reasonable collection costs.
- **Taxes.** Fees exclude taxes; Customer is responsible for all sales,
  use, VAT, GST, and similar taxes other than taxes on Spine's net
  income.
- **No refunds.** Pre-paid fees are non-refundable except as expressly
  provided in this MSA.
- **Auto-renewal.** Order Forms auto-renew for successive one-year
  terms unless either party gives `[60]` days' written notice of
  non-renewal.

## 7. Term and Termination

- **Term.** This MSA continues until terminated. Each Order Form has
  its own term as specified.
- **Termination for cause.** Either party may terminate this MSA or any
  Order Form for material breach uncured within `[30]` days of written
  notice. Spine may terminate immediately for breach of EULA §3 or for
  Customer's failure to maintain a valid License Bundle.
- **Termination for insolvency.** Either party may terminate
  immediately on the other's insolvency, assignment for the benefit of
  creditors, or filing for bankruptcy.
- **Effect.** On termination of an Order Form, Customer ceases use of
  Software covered by that Order Form per EULA §7. Surviving sections
  per §15 below.

## 8. Confidentiality

The confidentiality terms of EULA §12 apply. Each party will: (a) use
the other's Confidential Information only as necessary to perform under
this MSA, (b) limit access to personnel with a need-to-know bound by
written confidentiality obligations no less protective than this MSA,
and (c) protect Confidential Information with at least reasonable care.

Exclusions: information that is or becomes publicly known through no
breach, was rightfully known prior to disclosure, is rightfully
received from a third party without restriction, or is independently
developed without use of the other's Confidential Information.

Required disclosures (court order, regulatory request) are permitted
with prior notice to the disclosing party where lawful.

## 9. Security; Incident Response

Spine maintains the security controls described in
`docs/SECURITY_GUIDE.md` and the Evidence Store collectors under
`evidence/`. Spine will:

- Maintain a `[SOC 2 Type II]` report on the License Bundle service
  + Telemetry ingest endpoint; provide on request, under NDA, no more
  than annually.
- Notify Customer without undue delay (and in any event within
  `[72]` hours) of any confirmed Security Incident affecting Spine's
  systems that materially affects Customer Data Spine processes.
- Cooperate reasonably with Customer's incident response activities.

The Hub runs on Customer infrastructure. Customer is responsible for
the security of the deployment environment, including: vault rotation,
TLS certificates, Keycloak realm configuration, federation mTLS
material, and infrastructure-level access controls.

## 10. Warranties; Disclaimers

EULA §9 applies. In addition:

- **Spine warrants** that during the active subscription term, the
  Software will materially conform to the Documentation. Customer's
  sole remedy for breach is, at Spine's option, (a) modification of
  the Software to conform, (b) replacement of the affected component,
  or (c) refund of pre-paid fees for the affected portion of the term.
- **Spine warrants** that Professional Services will be performed in
  a workmanlike manner. Customer must report any non-conformance
  within `[30]` days of delivery.
- **AI-generated output disclaimer.** Spine does not warrant the
  accuracy, completeness, suitability, or non-infringement of any
  artifact generated by the Hub's LLM-backed roles. Customer must
  review all AI-generated artifacts (PRDs, TRDs, code, audit reports)
  before relying on them for production or regulated use.

## 11. Indemnification

EULA §11 applies, modified for Enterprise as follows:

- **Cap.** The cumulative indemnification obligations of each party
  under this MSA are subject to the liability limit in §12.
- **Procedure.** The indemnified party will: (a) promptly notify the
  indemnifying party in writing, (b) give the indemnifying party sole
  control of defense and settlement (provided no settlement that
  imposes non-monetary obligations or admits fault may be made without
  the indemnified party's consent, not unreasonably withheld), and
  (c) cooperate at the indemnifying party's expense.

## 12. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW:

- **General cap.** Each party's total cumulative liability under this
  MSA and all Order Forms will not exceed **the fees paid or payable
  by Customer to Spine during the twelve (12) months preceding the
  event giving rise to liability**.
- **Excluded damages.** Neither party will be liable for indirect,
  incidental, consequential, special, exemplary, or punitive damages,
  including lost profits, revenue, data, or goodwill, even if advised
  of the possibility.
- **Carve-outs.** The cap and the excluded-damages clause do not apply
  to: (a) Customer's payment obligations, (b) breach of EULA §3 or
  this MSA §8, (c) the indemnification obligations under §11, or
  (d) liabilities that cannot be limited under applicable law.
  // TODO: legal — confirm enforceability per jurisdiction

## 13. Insurance

Each party will maintain, at its own expense, commercially reasonable
insurance coverage appropriate to its obligations under this MSA,
including general liability, professional liability (errors and
omissions), and cyber liability coverage of not less than `[USD
$X,000,000]` per occurrence. Certificates available on request.
// TODO: legal — confirm coverage minimums

## 14. Compliance

- **Anti-corruption.** Each party complies with the US Foreign Corrupt
  Practices Act, UK Bribery Act, and other applicable anti-corruption
  laws.
- **Export control + sanctions.** EULA §13 applies.
- **Audit rights.** Spine may audit Customer's License Bundle quota
  compliance not more than once per year via heartbeat data; Customer
  may audit Spine's compliance with §2 (Data Custody) and §9
  (Security) once per year on `[30]` days' notice, during business
  hours, under NDA.

## 15. Survival

Sections 2 (Data Custody), 5 last paragraph, 6 (Fees through paid
period), 7 (Effect of termination), 8 (Confidentiality), 10
(Disclaimers), 11 (Indemnification), 12 (Limitation of Liability),
14, 15, and 16 survive termination.

## 16. General

- **Independent contractors.** EULA §16 applies.
- **Assignment.** Neither party may assign without the other's prior
  written consent, except either party may assign on notice in
  connection with a merger or sale of substantially all assets, to a
  party that assumes all obligations. Any other assignment is void.
- **Notices.** Written notices to the address in the Order Form, or to
  the legal addresses for record below. Email permitted for routine
  matters; notices of breach, termination, or indemnification require
  email + tracked physical delivery.
- **Governing law; venue.** EULA §14 applies.
- **Order of precedence.** If there is conflict among documents, the
  order is: (i) signed Order Form (most recent), (ii) this MSA,
  (iii) DPA, (iv) EULA, (v) Documentation.
- **Entire agreement; amendments.** This MSA + executed Order Forms +
  EULA + DPA constitute the entire agreement on the subject matter and
  supersede prior agreements. Amendments require a writing signed by
  both parties.
- **Counterparts; electronic signatures.** This MSA may be executed in
  counterparts; electronic signatures (DocuSign, Adobe Sign) are
  enforceable.

---

**Acknowledged and accepted:**

**`[Customer Legal Entity]`**          **`[Vendor Legal Entity]`**
By: ____________________               By: ____________________
Name: __________________               Name: __________________
Title: _________________               Title: _________________
Date: __________________               Date: __________________

**Customer notice address:**           **Spine notice address:**
`[Address line 1]`                     `[Address line 1]`
`[City, State ZIP]`                    `[City, State ZIP]`
`[Email]`                              `legal@spine.dev`

---

> **End of MSA template.** Companion documents:
> - `docs/legal/EULA_TEMPLATE.md` — End-User License Agreement
> - `docs/legal/DPA_TEMPLATE.md` — Data Processing Addendum
