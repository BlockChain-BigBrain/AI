# AI Party integration bridge

This directory is an additive integration layer. Existing frontend, backend,
and blockchain files are intentionally unchanged.

The cross-source handoff is maintained in [Notion](https://app.notion.com/p/40b4167954e181ed9af6cba16ef22221) and is grounded in the repository's [blockchain handoff](../../BLOCKCHAIN_HANDOFF.md).

## Runtime wiring

```text
Frontend -> integrations/Backend API -> Track-AI FastAPI
                               \\-> existing provenance/settlement endpoints
```

The backend already owns upload persistence and verification state. The AI
service is called through `POST /verify` and polled through
`GET /verify/{jobId}`. `TRACK_AI_API_KEY` is sent only as
`X-Internal-API-Key`; it must never be exposed to the frontend or written to
the blockchain.

Set these values in the backend environment (do not commit secrets):

```dotenv
TRACK_AI_URL=http://127.0.0.1:8000
TRACK_AI_API_KEY=<shared-internal-key>
FRONTEND_URL=<existing-frontend-origin>
```

The response contract is frozen in `contract.json`. With the merged
TrackRegistry ABI, PASS/WARN/HOLD receive a `registerTrack` EIP-712 signature.
HOLD is recorded by `VerificationStatus.HOLD` and remains non-licensable;
`LicenseMarketplace.purchaseLicense` must reject it. Only BLOCK suppresses
signature issuance and blocks registration. The current contract does not
have explicit `isHold` or `manifestHash` fields: manifest evidence remains
in IPFS/MySQL, while the signed on-chain fields are listed in `contract.json`.
Adding explicit fields requires a new contract version and deployment.

## Verification

Run `powershell -ExecutionPolicy Bypass -File smoke-check.ps1` from this
directory after starting the AI API and the existing backend. The script is
read-only and checks health plus the required contract fields; it does not
create tracks, alter databases, or submit blockchain transactions.
