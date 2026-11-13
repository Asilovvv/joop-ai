# Model providers

Joop talks to the language model through one small client. By default it is Anthropic (`ANTHROPIC_API_KEY`, `JOOP_MODEL=claude-haiku-5-5`). A second client, `joop/agent/openai_compat.py`, speaks the OpenAI Chat Completions API that many services offer, so the model can be switched without touching the rest of the code.

Whatever the provider, the model only proposes: a reply and, as JSON, a booking, an order or a hand-off. The code checks every action against the database before anything happens. A weaker model gives worse wording; it cannot book a taken slot or confirm an order that does not exist.

## Settings

| Variable | Anthropic (default) | Second provider |
| --- | --- | --- |
| `LLM_PROVIDER` | empty or `anthropic` | `openai` |
| key | `ANTHROPIC_API_KEY` | `LLM_API_KEY` |
| endpoint | — | `LLM_BASE_URL`, e.g. Gemini's OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai` |
| model | `JOOP_MODEL` | `JOOP_MODEL` = the provider's model id |

The client asks for JSON by schema; a service that does not accept that falls back to «any JSON object», then to plain text read by the same parser.

## When to use which

- **Development and the scripted evaluation on fictional businesses**: any provider, including free tiers.
- **Real customers**: only a paid tier whose terms the owner has read. Free tiers may use what is sent to improve the provider's products (Google states this for the Gemini free tier on its [pricing page](https://ai.google.dev/gemini-api/docs/pricing)); customers' names and phone numbers must not go there. `python -m joop check` shows a warning while `LLM_PROVIDER=openai` is set.
- **The thesis**: results are reported per model. A run on another provider is a separate row in the results table, not a replacement for the Anthropic numbers.

## Running the evaluation on a second provider

Locally:

```
LLM_PROVIDER=openai LLM_BASE_URL=<endpoint> LLM_API_KEY=<key> JOOP_MODEL=<model id> python -m eval.run_eval cleaning
```

On GitHub: add the repository secret `LLM_API_KEY`, then Actions → eval → Run workflow with `provider=openai`, `base_url` and `model` filled in. Cost in the results is shown only for models with a known price (`joop/pricing.py`).
