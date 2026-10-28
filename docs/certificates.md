# Verification certificates

A Veriq **certificate** is a small JSON file that records *what was checked, against what, under which
assumptions, with which tools, and with what result*, bound to the exact circuits by SHA-256 hashes and
optionally **signed with Ed25519**. Anyone with the public key can later confirm that the result was
not edited, that the circuit files are the ones that were checked, and (with `--recheck`) that the
proof still goes through.

## Producing certificates

```bash
veriq check cand.py -r ref.py --certificate cert.json            # also: veriq verify (alias)
veriq optimize circuit.py -o best.qasm --certificate opt.json     # output proven equal to input
veriq ci --certificates                                           # one <name>.cert.json per entry,
                                                                  # in <report-dir>/certificates
```

Add `--sign-key veriq-signing.key` (or set `VERIQ_SIGNING_KEY`) to sign at creation time, or sign later:

```bash
veriq certify cert.json --key veriq-signing.key      # in place; -o other.json to write elsewhere
```

From an AI assistant, the MCP tool `verify_circuit(..., certificate=true)` returns an **unsigned**
certificate in its result (the server never holds a signing key). Save it and run `veriq certify`.

## Verifying

```bash
veriq cert verify cert.json --key veriq-signing.pub \
     --circuit cand.py --circuit ref.py \
     --recheck
```

It checks these things in order:

| Check | What it verifies |
|---|---|
| signature | Ed25519 over the canonical payload, and that the signer is the `--key` you trust |
| semantics | the verdict, claim, proof status and checks are mutually consistent (rules below) |
| embedded circuits | the embedded canonical QASM matches its recorded `canonical_sha256` |
| circuit files (`--circuit`) | each file's bytes match `source_sha256`, and the circuit it builds matches `canonical_sha256` |
| recheck (`--recheck`) | re-runs the checks and compares the verdict and proof status with the certified ones |

Exit codes: `0` valid, `1` invalid, `3` the certificate could not be read. `--json out.json` writes the
detailed result. `--allow-unsigned` accepts unsigned certificates; they are then checked for
consistency and hashes only.

**Trust.** Only `--key` makes a result *trusted*. Without it, Veriq uses the public key embedded in the
certificate. That proves the file was not modified after signing, but not **who** signed it: an
attacker can re-sign a forged certificate with their own key. Always pin the public key.

`--recheck` uses the files from `--circuit` when they are given. In that case every check is re-run,
including the gate set, coupling and black-box constraints. Otherwise it uses the embedded canonical
QASM. The QASM export can rename or inline custom gates, so with embedded QASM only the proof is
re-run when the certificate has constraints. When it has none, the full verdict is compared.
Optimize certificates are re-proven as output against the unitary part of the input. This is skipped
when the proof depends on a layout (a coupling map or an allowed permutation).

## Schema (`veriq.certificate/1`)

| Field | Content |
|---|---|
| `schema`, `kind` | `veriq.certificate/1`; `verify`, `ci` or `optimize` |
| `verdict` | `PASS`, `FAIL` or `INCONCLUSIVE` |
| `claim` | what the certificate asserts (table below) |
| `inputs[]` | per circuit: `role` (candidate/reference, or input/output), `path`, `function`, `source_sha256` (file or code bytes), `canonical_format`, `canonical_sha256`, `canonical` (normalized OpenQASM, embedded up to 512 KB), `qpy_sha256` (informational; QPY bytes vary between versions), `num_qubits` |
| `assumptions` | `equivalence`, `mode`, `initial_state`, `qubits_initially_zero`, `allowed_gates`, `coupling` (+ scope), `permutation_allowed`, `black_boxes_allowed`, `expect`, statistical shots and seed, `timeout_s`, `backend` (optimize also has `proof_scope` and `layout_dependent`) |
| `proof` | `status` (`proven`, `refuted`, `undecided` or `none`), the deciding `check`, `method`, `engine`, `engine_details` (QCEC result and time, strategy, fallback...) |
| `checks[]` | name, status and summary of every check |
| `metrics` | circuit metrics (optimize: source, baseline and best CX/depth, savings) |
| `counterexample` | for `FAIL`: the input state and both outputs, or the failing evidence; `null` otherwise |
| `tool_versions` | veriq, qiskit, qiskit-aer, mqt.qcec, cryptography, python, platform |
| `timestamps` | `started`, `issued` (UTC, ISO-8601), `seconds` |
| `ci` | (CI only) entry name, `expect`, `as_expected`, and `GITHUB_REPOSITORY`/`SHA`/`REF`/`RUN_ID`/`WORKFLOW` when set |
| `signature` | `alg` (`Ed25519`), `key_id` (the first 16 hex characters of sha256 of the raw public key), `public_key` (base64), `payload_sha256`, `signed_at`, `value` (base64), `canonicalization` |

The signed payload is the certificate **without** `signature`, serialized as JSON with sorted keys,
separators `(",", ":")` and `ensure_ascii`.

### Claims

| claim | when |
|---|---|
| `PROVEN_EQUIVALENT` | verdict PASS **and** the equivalence proof succeeded (QCEC, Operator, Clifford, exact MPS) |
| `NOT_EQUIVALENT` | verdict FAIL **and** the proof refuted equivalence (with a counterexample) |
| `CHECKS_PASSED_NO_PROOF` | verdict PASS without a proof (no reference: distribution or constraint checks only). **This is not a proof.** |
| `CHECK_FAILED` | verdict FAIL for another reason (constraint, distribution, build) |
| `NONE` | verdict INCONCLUSIVE: the certificate asserts nothing |

### Semantic rules

Veriq enforces these rules when it builds, signs and verifies a certificate. A certificate that
breaks one cannot be produced, is refused by `certify`, and fails `cert verify`, even if its
signature is valid.

- **INCONCLUSIVE is never certified as PASS.** `PASS` requires every applicable check to be `PASS`.
- `PASS` with a simulation-only (`PROBABLY_EQUIVALENT`) result has proof status `undecided`, so its
  claim is at most `CHECKS_PASSED_NO_PROOF`.
- `FAIL` requires a failing check and a counterexample or failing evidence.
- `claim` must follow from `verdict` and `proof.status` (table above). A proven proof alongside an
  INCONCLUSIVE verdict (e.g. a borderline sampling test) gives claim `NONE`.
- `certify` refuses to sign when the embedded QASM no longer matches its hash.

## Key handling

```bash
veriq keygen -o veriq-signing.key           # writes veriq-signing.key (mode 600) + veriq-signing.pub
veriq keygen -o k.key --passphrase-env PW   # encrypted PKCS8, passphrase read from $PW
```

- The private key is PKCS8 PEM and the public key SPKI PEM. `keygen` refuses to overwrite files without `--force`.
- `VERIQ_SIGNING_KEY` may hold the PEM **text** (as from a CI secret) or a path.
  `VERIQ_SIGNING_KEY_PASSPHRASE` holds the passphrase of an encrypted key.
- **Never commit private keys.** The repo's `.gitignore` excludes `*.key`, `*.pem` and `veriq-signing.key*`.
  The tests generate throwaway keys in a temporary directory at run time. Publish only the `.pub` file,
  for example in your README or release notes, and give verifiers its `key_id`.
- To rotate a key, generate a new pair, publish the new `.pub`, and keep the old public key to verify
  older certificates.

## GitHub Action

```yaml
      - uses: <owner>/veriq@v0
        with:
          config: .veriq.yml
          certificates: "true"                          # default
          signing-key: ${{ secrets.VERIQ_SIGNING_KEY }} # optional; PEM text from `veriq keygen`
```

The action passes the key to `veriq ci` through the environment only, so it is never written to disk
or to the log. It uploads the certificates as the `<artifact-name>-certificates` artifact (default
`veriq-reports-certificates`) and exposes the `certificate-dir` output. Pull requests from forks get
no secrets, so their certificates are unsigned. To verify a downloaded artifact:

```bash
veriq cert verify qft.cert.json --key veriq-signing.pub --circuit circuits/qft.py --circuit circuits/qft_reference.py
```

## Limitations

- The canonical hash comes from Qiskit's OpenQASM exporter after normalizing generated gate names. A
  different Qiskit version may serialize the same circuit differently, so re-hashing with `--circuit`
  can report a canonical mismatch even when the source hash matches. The source hash is the stable
  anchor.
- Signatures with an embedded key prove integrity, not identity. Pin the key with `--key`. There is no
  sigstore, keyless signing or transparency log yet.
- `CHECKS_PASSED_NO_PROOF` and every statistical result are evidence, not proofs.
- When `--recheck` uses embedded QASM, it does not re-check constraints such as gate set, coupling or
  black boxes. Pass `--circuit` for a full recheck. Optimize rechecks are skipped for layout-dependent
  proofs.
- A certificate covers the circuit **as built** by the recorded source and function. It does not
  cover the Python environment, randomness inside the builder, or files that the builder imports.
- The Action's certificate upload and signing have not yet been run on github.com.
