# Shamir secret-sharing (3-of-5) — operator runbook

> Applies to Spine v3 deployment shapes (#17): **laptop**, optionally **on-prem**
> when no cloud KMS is desired. For BYOC / customer-cloud, KMS auto-unseal is
> strongly preferred — see `kms-config-{aws,azure,gcp}.md`.

## What Shamir gives you

Per `V3_DESIGN_DECISIONS #32 layer 8`: the master key is split into N shares
(default 5); any K (default 3) reconstruct it. Vault is sealed at rest; it
must be unsealed after every restart by submitting K shares.

**Trade-off vs KMS:** Shamir requires humans to be present at every unseal
(after reboot, crash, container restart). KMS automates this at the cost of
trusting a cloud KMS.

## Recommended defaults

| Parameter | Default | Why |
|---|---|---|
| `secret_shares` | 5 | Allows 2 lost shares before unseal becomes impossible. |
| `secret_threshold` | 3 | Requires a majority; no single person can unilaterally unseal. |
| `root token` | revoke after initial setup | Generate per-task scoped tokens; never reuse root. |

## Share distribution best practices

Treat each share as if it were the entire master key — because in combination
with K-1 other shares, it is.

1. **Five distinct humans**, each with a clear role:
   - CEO / founder
   - CTO / engineering lead
   - Head of security
   - Head of operations / SRE lead
   - Trusted external custodian (legal counsel, board member, escrow agent)

2. **Five distinct storage media** — never two shares in the same place:
   - Hardware token in a bank safe-deposit box
   - Encrypted USB in a home safe (encryption key written separately)
   - Paper printout in a tamper-evident envelope
   - Password manager entry under a personal account (NOT shared workspace)
   - Sealed envelope with the external custodian

3. **No share holder has the password to another share holder's storage.**
   Otherwise a single compromise leaks two shares.

4. **No share via email, Slack, SMS, or any cloud doc** — these are NOT
   acceptable distribution channels. Distribute in person or via signed,
   encrypted, single-use channels (e.g. Magic Wormhole one-shot transfer
   immediately destroyed).

5. **Rotate share holders** when anyone leaves the company. Use
   `bao operator rekey` to regenerate shares without changing the master key,
   then physically destroy old shares.

6. **Document who holds which share** in a separate physical record kept by
   the CEO + Head of Security. The record names the holders but NEVER the
   share material.

## Unseal procedure (post-restart)

```bash
# Each of K holders runs:
export BAO_ADDR=https://vault.your-spine.example:8200
bao operator unseal
# (prompted for their share)

# After K successful submissions, Vault unseals automatically.
bao status   # Sealed: false
```

For laptop / dev: the init-wizard auto-unseals using captured keys at first
init, then the keys are discarded — subsequent restarts require manual unseal
exactly as in production.

## Rekey (rotate the master key + share set)

Do this:
- Annually as standard hygiene
- Immediately when any share holder leaves
- Immediately on suspected compromise

```bash
bao operator rekey -init -key-shares=5 -key-threshold=3
# Each existing holder contributes their old share
bao operator rekey   # prompts for old share
# After K old shares: NEW shares are issued. Distribute per the
# best-practices list above. Destroy old shares physically.
```

## Failure modes (see also `../dr-runbook.md`)

| Lost shares | Outcome |
|---|---|
| 0–2 of 5 | Acceptable. Rekey immediately to restore N=5. |
| 3+ of 5 | **Catastrophic.** Threshold no longer reachable. Vault data is unrecoverable. Restore from snapshot using a DIFFERENT initialized Vault (snapshot encryption keys travel with the snapshot only if you've been rotating + escrowing them — which you should be, see DR runbook layer 3). |

## References

- OpenBao Shamir docs: <https://openbao.org/docs/concepts/seal/>
- Spine DR runbook: `../dr-runbook.md`
- DR layer 8 spec: `docs/V3_DESIGN_DECISIONS.md` §32
