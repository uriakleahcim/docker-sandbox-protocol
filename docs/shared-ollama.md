# Shared Ollama Service

The active `ollama` Sandbox target supplies a single local inference endpoint
for agent services. Its model data is owned only by:

```text
/home/uriak/sandbox/groups/agent-models/ollama/
```

The Compose service mounts that directory as `/root/.ollama` *inside its own
container* and publishes `http://127.0.0.1:11434` only on the host loopback
interface. Agent containers use the dedicated internal `agent-services` Docker
network and resolve it as `http://ollama:11434`. They must never mount or write
the model cache themselves.

The short-lived `ollama-model-init` service ensures the shared profile is
available at every start:

- `qwen2.5:3b-instruct` for quality summaries and deep reports;
- `qwen2.5:1.5b-instruct` for fast grouping, topic, headline, and bias work;
- `nomic-embed-text:v1.5` for embeddings.

Start it before a consumer:

```bash
sandbox explain ollama
sandbox start ollama
sandbox logs ollama ollama-model-init
sandbox start bias-graph-feed
```

On the first start, wait for `ollama-model-init` to complete successfully
before starting a consumer. Later starts reuse the same blobs.

To consume the endpoint from another Compose project, attach its consumer to
the external `agent-services` Docker network and set
`OLLAMA_HOST=http://ollama:11434`. This keeps host access loopback-only while
allowing selected containers to share one Ollama server. Do not start two
Ollama servers against the same writable cache.
