# Public EDI Claim Samples

These files are public sample/synthetic EDI artifacts for local testing. Do not use real patient claims or PHI in this repository.

## Raw 837 Claim Files

- `raw-837/databricks-837p.txt`
- `raw-837/databricks-cc-837p.txt`
- `raw-837/databricks-cc-837i.txt`
- `raw-837/databricks-chpw-claimdata.txt`
- `raw-837/databricks-molina-mock-837p.txt`

## Raw 835 Remittance Files

- `raw-835/databricks-835-sample.txt`
- `raw-835/databricks-835-sample-services.txt`
- `raw-835/databricks-835-plb-sample.txt`

## App-Ready Claim JSON

`claims.normalized.json` is extracted from `raw-837/databricks-chpw-claimdata.txt` and shaped for the current `ClaimStore`.

Use it with:

```bash
CLAIMS_JSON_PATH=./sample/edi-claims/claims.normalized.json uv run server.py
```

Source: `databricks-industry-solutions/x12-edi-parser`, `sampledata/837` and `sampledata/835`.
