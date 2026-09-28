# Model providers

The default `meridian-local` provider implements `/v1/models` and
`/v1/chat/completions`. It extracts retrieved passages and translates structured
action cards into tool calls when tools are offered. This makes integration runs
deterministic and free of external dependencies. It does **not** measure a language
model's susceptibility to arbitrary natural-language prompt injection.

The API and worker can use an OpenAI-compatible provider through `MODEL_URL`,
`MODEL_NAME`, and `MODEL_API_KEY`. The URL includes `/v1`. Model selection is explicit;
there is no pinned external model. Provider requests use a bounded timeout and do
not trust proxy environment variables.

The default internal network intentionally cannot reach an internet model API.
For a local gateway, attach that gateway to the Compose `services` network and use
its Docker DNS name. For example, a separately managed gateway listening at port
4000 can be attached under alias `research-model`, then configured as
`MODEL_URL=http://research-model:4000/v1`. Restart API and worker after changing `.env`.

An external provider requires an explicit network override that grants API and
worker egress. Keep that deployment separate from the default offline instance.
Record the provider, model revision, sampling settings, and repeated-run results.
Tool execution still belongs to the application; model output is only a proposal.
