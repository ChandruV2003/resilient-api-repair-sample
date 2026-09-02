# Resilient API Repair Sample

A small, dependency-free Python portfolio sample showing how a brittle paginated API workflow can be repaired without hiding the failure modes.

This is a transparent AI-assisted demonstration project, not client work. Before publishing it or using it in a proposal, Chandru should review every line, run the tests personally, and be able to explain the retry, pagination, validation, and atomic-write choices.

## The failure pattern

The imagined original workflow assumed every request returned HTTP 200, every response contained a list of records, and every pagination cursor eventually terminated. In production, that creates four common failures:

- transient `429` and `5xx` responses abort the run;
- malformed payloads silently produce bad output;
- repeated cursors create an infinite loop; and
- a crash during CSV generation leaves a partial destination file.

## The repair

`ResilientApiClient` adds:

- bounded retry behavior for `429`, `500`, `502`, `503`, and `504`;
- capped `Retry-After` or exponential delays;
- strict JSON and record-shape validation;
- a maximum page count and repeated-cursor detection; and
- an atomic CSV exporter that replaces the destination only after a complete write.

The transport and sleeper are injected, so tests remain deterministic and never call a real service.

## Run the proof

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m api_repair_sample
```

Expected demo result:

```text
Fetched 3 records after 3 HTTP calls.
IDs: 101, 102, 103
```

## What this demonstrates

- focused Python fault isolation;
- API boundary validation;
- safe retry and pagination behavior;
- testable dependency injection;
- deterministic regression coverage, including preservation of known-good output when generation fails; and
- a concise client-facing explanation of what failed and how the repair is proven.

## Scope boundaries

This sample does not contain customer data, credentials, proprietary code, browser automation, financial orders, or code copied from JVT, NTC, an employer, or another project. It is not a claim that every API needs the same retry policy: production behavior must follow the service contract and its idempotency and rate-limit rules.
