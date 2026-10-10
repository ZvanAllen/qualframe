# Models and data

## Where your data goes

| What | Where it is kept | Leaves your computer? |
| --- | --- | --- |
| Transcripts, codebooks, participant information | `QualFrame/studies/<study>/` in your home folder | Only when you start a run with a hosted model, and only to that provider |
| Model responses, review decisions, results, exports | The same study folder | No |
| API keys | In memory while QualFrame runs, or in a `.env` file you create | Only to the provider, to authenticate requests |
| Usage and cost records | The study's `logs` and run folders | No |

QualFrame has no account, server or analytics. The browser page is served from your own computer at `127.0.0.1` and can't be reached from other machines. Fonts are bundled, so pages make no outside requests.

**Hosted models.** When you start a run, each request contains the coding instructions, your analysis settings, one transcript, and your codebook (or one part of it). The provider's terms decide what happens to that data, including whether it is retained or used for training. Check that your research ethics approval, consent forms, and data agreements allow this, and prefer de-identified transcripts. QualFrame asks you to confirm this before saving a hosted model, and again when you start a run.

**Local models.** With Ollama or LM Studio, requests go to a server on your own computer and transcripts never leave it. This is the simplest option for sensitive data, at the cost of speed and usually some quality.

**Institutional endpoints.** Many universities and health organisations approve AI use through Azure OpenAI or a similar service. Choose *Azure OpenAI or another compatible endpoint* and enter the address your institution gives you. For Azure OpenAI this is `https://YOUR-RESOURCE.openai.azure.com/openai/v1/`, and the model name is your deployment name.

## Choosing a model

There is no single best model for qualitative coding, and results vary with your codebook and data. Some practical guidance:

- **Start with the demo** to learn the workflow without spending anything.
- **Pilot on two or three transcripts** with a low-cost model, review the proposals, and look at what it gets wrong before coding everything.
- **Use a stronger model** for the full study if the pilot shows missed or misapplied codes, especially with long or subtle codebooks.
- **Try a second model** and use **Compare runs** to see where they disagree. Disagreements are often the passages most worth a careful read.

Model cards on the Run coding page show an estimate for your study. Presets are kept in `config/model_presets.yaml`, with the date prices were checked. You can edit every value under **Advanced settings**, including the model name, so newer models work without an update.

### Hosted presets (prices checked 10 October 2026, US dollars per million tokens)

| Preset | Model name | Input | Output |
| --- | --- | --- | --- |
| OpenAI GPT-6.1 Sol | `gpt-6.1-sol` | 2.00 | 10.00 |
| OpenAI GPT-6 Luna | `gpt-6-luna` | 0.10 | 0.50 |
| Anthropic Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 |
| Anthropic Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 (prompts under 100,000 tokens) |

Sources: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). Providers change prices; your bill is what counts.

**Rough cost.** Coding the six short demo interviews (about 4,100 words in all) with Claude Sonnet 5.5 used about 29,000 input and 16,000 output tokens, or $0.22, in October 2026. Most of the output was the model's hidden reasoning, which providers bill as output. Scaled up, a one-hour interview (8,000 to 10,000 words) costs very roughly 15 to 25 cents with a mid-priced model and about a cent with a low-cost model. Sending the codebook one category per request multiplies the number of requests. The estimate on the Run coding page is deliberately on the high side, and every request is checked against your spending limit before it is sent.

Hosted presets allow up to 32,000 output tokens per response, because a long interview can produce a long list of codings. You pay only for what is used. If a run stops because a response reached that limit, raise **Maximum output tokens** in the model settings or send one codebook category per request.

### Local models

1. Install [Ollama](https://ollama.com) (or [LM Studio](https://lmstudio.ai) and start its local server).
2. Download a model, for example `ollama pull gpt-oss:20b`. Larger models code better but need more memory; a 20-billion-parameter model needs roughly 16 GB.
3. In QualFrame, choose *Local model with Ollama* (or LM Studio), enter the model name, and save.

Local runs cost nothing but can take several minutes per transcript on a laptop.

**Set the context length first.** A request holds the whole transcript plus the codebook and instructions: about 5,000 tokens for a short interview and 20,000 or more for an hour-long one, before the model's answer. On most computers Ollama's [default context window](https://docs.ollama.com/context-length) is 4,000 tokens (it is larger only with 24 GB or more of graphics memory), and when a request doesn't fit, Ollama drops the beginning without an error. Before coding real transcripts, set the context length to at least 32,000 tokens: with the **Context length** slider in the Ollama app's settings, or by making a variant of the model with a [Modelfile](https://docs.ollama.com/modelfile) containing `FROM gpt-oss:20b` and `PARAMETER num_ctx 32768`. In LM Studio, set the context length when you load the model. QualFrame stops a run if a local model reports reading much less than it was sent.

## What the model is asked to do

The coding instructions are in [`prompts/directed/v3/directed_coding.md`](../prompts/directed/v3/directed_coding.md). In short, the model is asked to read the whole transcript, code participant speech only, apply codes only when a passage fits the definition and guidance, prefer the most specific code, copy each quotation exactly, and return its codings as JSON. For OpenAI and Anthropic models the response format is enforced, and code IDs are restricted to your codebook.

QualFrame then finds each quotation in the transcript. A quotation that appears exactly once becomes a located passage. One that can't be found, or appears more than once, is sent to you to resolve, so a paraphrased or invented quotation can't slip through as evidence.

Prompts are versioned files. Every run records the hash of the prompt it used, so changing a prompt never changes the record of an earlier run.
