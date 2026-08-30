# Stateback

Stateback provides transactional safety around consequential external effects
performed by AI agents. Its product position is **Transactions for AI agents**.

Stateback durably records intent before attempting an effect, preserves
ambiguous outcomes as unknown, and supplies explicit verification,
reconciliation, policy, approval, compensation, and audit semantics.

The `0.1.0` release supports a self-hosted Python package and Docker Compose
topology with an API, outbox relay, workers, operator frontend, PostgreSQL 16,
and NATS 2.12 with JetStream. A focused GitHub issue/comment/label/pull-request
workflow is the first production-shaped provider surface. Optional semantic assistance uses local
Ollama and is non-authoritative.

Start with the [architecture](architecture.md), [safety model](safety-model.md),
and [development guide](development.md). Before operating consequential
effects, read the exact [guarantees and limitations](guarantees.md) and
[deployment guide](deployment.md).

For integration, see [API, SDK, and MCP](api.md). For reconstruction and
recovery controls, see the [operator guide](operator.md).

Normative lifecycle and machine-facing symbol definitions live at repository
paths `STATE_MACHINES.md`, `contracts/enums-v1.md`, and
`contracts/README.md`. They are outside the MkDocs `docs/` tree.
