# Local model selection

Reviewed 12 October 2026; selected Lightweight and Balanced artifacts rechecked 13 October 2026. This is a researched shortlist for PriSMA, not a measured ranking on the user's laptop. Public benchmark results below come from model publishers. Quantized extraction quality, CPU latency and peak memory still require the same-source comparison described below.

PriSMA needs reliable extraction from provided evidence, valid structured output, conservative handling of absent information, and useful relationships. Broad trivia knowledge, creative writing and competitive coding are secondary. Deterministic parsers handle explicit specifications, dependency lists, source declarations and markup. A larger language model does not repair a missing source or an incorrect parser.

## Recommended shortlist

| Profile | Candidate and exact download identifier | Published download size | Decision |
| --- | --- | --- | --- |
| Lightweight | `hf.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF:Q4_K_M` | 731 MB GGUF | First replacement candidate for the current Qwen3 1.7B. Strong fit for short evidence extraction with CPU headroom. |
| Lightweight alternate | `qwen3.5:2b-q4_K_M` | About 1.9 GB | More general technical/document capability, but close to the application's 2 GB weight ceiling. Use this exact quantization, not the default 2B download. |
| Lightweight alternate | `granite4:1b-h` | About 1.6 GB | IBM's hybrid model is a useful permissively licensed, enterprise-oriented comparison. |
| Balanced | `qwen3.5:4b-q4_K_M` | About 3.3 GB | First candidate for more difficult prose and relationships while retaining a manageable footprint. |
| Balanced economical alternate | `qwen3:4b-instruct-2507-q4_K_M` | About 2.5 GB | Text-only instruction model, smaller and operationally simpler; an important latency baseline. |
| Advanced | `qwen3.5:9b-q4_K_M` | About 6.6 GB | First candidate for complex documents when the machine can reserve substantially more memory. |
| Advanced efficiency alternate | `lfm2.5:8b-a1b-q4_K_M` | About 5.2 GB | Mixture-of-experts candidate with fewer active parameters; worth testing when CPU efficiency matters. Total resident weights still matter. |

Sizes are downloads/weights, not peak RAM or VRAM. Tags and artifacts can change: check the installed model's actual size and digest. The upgrade keeps `qwen3:1.7b` as the existing default. It neither downloads candidates nor enables larger profiles.

Sources: [Liquid GGUF files](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/tree/main), [Qwen3.5 tags](https://ollama.com/library/qwen3.5/tags), [Granite tags](https://ollama.com/library/granite4/tags), [Qwen3 tags](https://ollama.com/library/qwen3/tags), [LFM2.5 tags](https://ollama.com/library/lfm2.5/tags).

## Why start with LFM2.5 1.2B Instruct

Liquid AI explicitly recommends this text model for data extraction, retrieval-augmented generation and agentic work. Its hybrid convolution/attention architecture is designed for CPU execution. Q4_K_M roughly halves the current Qwen3 1.7B download footprint. The publisher provides an Ollama-compatible GGUF, so no new inference transport is needed.

In Liquid AI's shared evaluation table, LFM2.5 1.2B Instruct scores 86.23 on IFEval versus 73.68 for Qwen3 1.7B Instruct, and 49.12 versus 46.30 on BFCL v3. These are publisher results with their evaluation settings and handler; they are not PriSMA citation accuracy or a measurement of the Q4 model. The result makes LFM a promising candidate, not a proven winner here.

Use the Instruct checkpoint for this workload. The Thinking version spends additional work on reasoning and is not the first choice for short, bounded extraction. The model's limitations in knowledge-heavy work and programming are less costly because PriSMA reads explicit code and contracts structurally. Retain Qwen as a comparison for less familiar technical prose. LFM uses the publisher's `lfm1.0` licence rather than Apache 2.0.

Sources: [Liquid AI model card](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct), [publisher introduction and comparison](https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai). The publisher's throughput measurements use other devices and frameworks; they do not establish throughput on a Ryzen 7 PRO 5875U with three CPU threads.

## Qwen3.5 for Balanced and Advanced

The 4B and 9B models use a hybrid attention architecture and support technical language, document understanding and structured workflows. Qwen publishes substantial instruction-following, coding and long-document results for both. This breadth is useful when sources combine product descriptions, documentation and architecture notes. The 9B candidate offers more capacity at roughly twice the 4B Q4 download size.

Those broad benchmarks are not a benchmark of PriSMA's source-unit contract, and reasoning-mode results do not establish performance with PriSMA's `think: false` requests. The production choice should follow the local evaluation, especially unsupported connections and invalid outputs. The current integration supplies text; candidate-family vision capability does not enable image/diagram ingestion in this upgrade.

Use explicit `q4_K_M` tags. Current default family/size aliases can select larger artifacts or a different backend. Qwen3.5 2B Q4 is about 1.9 GB, while the listed Q8 variant is about 2.7 GB and exceeds PriSMA's lightweight weight limit. Keep the application context at 4,096 tokens; a model's advertised large context is not a reason to reserve it on a laptop.

Sources: [Qwen3.5 2B model card](https://huggingface.co/Qwen/Qwen3.5-2B), [4B model card](https://huggingface.co/Qwen/Qwen3.5-4B), [9B model card](https://huggingface.co/Qwen/Qwen3.5-9B), [exact Ollama tags](https://ollama.com/library/qwen3.5/tags).

## Other families considered

| Family | Useful strengths | Why it is an alternate here |
| --- | --- | --- |
| Granite 4.0 H 1B / H 3B | Hybrid architecture, instruction following, tool use, Apache 2.0; H 3B is listed at about 1.9 GB. | Strong enterprise comparison. Publisher results do not establish better extraction than LFM or Qwen in PriSMA. Beware `granite4:1b`: its listed default is 3.3 GB; the H tag is different. |
| Qwen3 4B Instruct 2507 | Explicit non-thinking instruction model, about 2.5 GB Q4. | Particularly useful when latency and straightforward text generation matter more than newer multimodal capability. |
| Ministral 3 3B / 8B | Native function calling, JSON output, multilingual and vision capabilities, Apache 2.0. Listed Q4 downloads are about 3.0 / 6.0 GB. | Credible alternatives for the larger profiles. Neither is a replacement within the current lightweight weight budget. |
| Phi-4 Mini Instruct | Compact 3.8B instruction model, about 2.5 GB in Ollama's listed Q4 variant. | Useful text baseline, but exceeds the lightweight weight ceiling; evaluate technical domain coverage rather than treating math benchmarks as extraction quality. |
| SmolLM3 3B | Open training information, instruction following, reasoning and long context. | Worth a reproducible comparison. Prefer the publisher/ggml-org artifact over an unverified community model alias. |
| SmolLM2 1.7B, Llama 3.2 1B, Gemma 3 1B | Mature small models and straightforward local deployment. | Useful baselines. Available evidence does not justify replacing the current model with them ahead of the newer extraction-oriented shortlist. |
| Gemma 4 E2B / E4B | Strong edge-oriented multimodal models. | “Effective” parameter counts are not resident weight counts. Listed downloads start around 4.6 / 6.6 GB, outside the current lightweight budget. |
| LFM2.5 2.6B | Publisher targets extraction, tool use and CPU efficiency. | An interesting economical larger-profile candidate; its parameter class exceeds the deliberately chosen 1–2B default. |
| LFM2.5 8B-A1B | Hybrid MoE, tool use and efficient execution. | Keep as an Advanced efficiency comparison. Its model card states 8.3B total and 1.5B active parameters; it is not a 1 GB resident model. |

Sources: [IBM H 1B card](https://huggingface.co/ibm-granite/granite-4.0-h-1b), [Granite downloads](https://ollama.com/library/granite4/tags), [Qwen3 4B Instruct card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [Ministral 3B card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512), [Ministral downloads](https://ollama.com/library/ministral-3/tags), [Phi card](https://huggingface.co/microsoft/Phi-4-mini-instruct), [Phi downloads](https://ollama.com/library/phi4-mini/tags), [SmolLM3 card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B), [SmolLM2 card](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct), [Gemma 4 downloads](https://ollama.com/library/gemma4), [LFM 2.6B card](https://huggingface.co/LiquidAI/LFM2.5-2.6B), [LFM MoE card](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B).

## Specialist extractors

GLiNER2.5 is the most relevant separate architectural experiment. Its base encoder has 194M parameters and about 407 MB weights, with entity, record and relation extraction plus original character spans. This matches PriSMA's need for precise names and relationships. It requires its own Python/PyTorch inference adapter and domain labels; it is not an Ollama chat-model substitution and is not integrated here. Compare relationship precision, false positives and abstention before adopting it.

NuExtract 2.0 2B is trained specifically for structured extraction and accepts a JSON extraction template. Its verbatim-string fields and absent-value behaviour are relevant. It needs a specialised template/chat adapter rather than PriSMA's existing general prompt. The 2B and 8B cards list MIT; the 4B variant lists a restrictive Qwen Research licence. Do not treat the family as one interchangeable deployment choice.

FunctionGemma 270M is a specialised function-calling model. Small size alone does not make it suitable for broad architecture prose; it is a task-specific fine-tuning candidate, not the default reading model.

Sources: [GLiNER2.5 base card](https://huggingface.co/fastino/gliner2.5-base-v1), [GLiNER2 implementation](https://github.com/fastino-ai/GLiNER2), [NuExtract 2B card](https://huggingface.co/numind/NuExtract-2.0-2B), [FunctionGemma card](https://huggingface.co/google/functiongemma-270m-it).

## Try the lightweight candidate

From the project root, with the inference service running:

```bash
sudo docker compose exec ollama ollama pull hf.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF:Q4_K_M
sudo docker compose exec ollama ollama list
```

Set this value in the existing `.env`:

```dotenv
OLLAMA_MODEL=hf.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF:Q4_K_M
```

Keep the lightweight memory/CPU settings and `OLLAMA_EMBEDDING_MODEL=all-minilm`. Then recreate the consumers:

```bash
sudo docker compose up -d --force-recreate api worker
```

Select Local inference, Lightweight, and Check availability. Start a new assessment by reimporting the same saved report or README. Existing reports retain their original model snapshot, so Retry/Resume on an older report is not a model comparison. Embeddings and generation have separate jobs; keeping all-minilm does not select it for analysis.

Revert by setting `OLLAMA_MODEL=qwen3:1.7b` and recreating API/worker. Existing installed weights remain available.

## Configure larger profiles deliberately

Download only the chosen candidate; these commands are options, not required upgrade steps:

```bash
sudo docker compose exec ollama ollama pull qwen3.5:4b-q4_K_M
sudo docker compose exec ollama ollama pull qwen3.5:9b-q4_K_M
```

For an explicitly reserved Balanced service, an initial test configuration is:

```dotenv
ALLOW_LARGE_LOCAL_MODELS=true
OLLAMA_BALANCED_MODEL=qwen3.5:4b-q4_K_M
INFERENCE_MEMORY_BUDGET_BYTES=8000000000
OLLAMA_MEMORY_LIMIT=8g
OLLAMA_CPU_LIMIT=3
LOCAL_GPU_LAYERS=0
```

For the Advanced candidate, reserve a separate larger budget before enabling its profile, for example:

```dotenv
OLLAMA_ADVANCED_MODEL=qwen3.5:9b-q4_K_M
INFERENCE_MEMORY_BUDGET_BYTES=12000000000
OLLAMA_MEMORY_LIMIT=12g
```

These are initial service reservations, not measured working sets or a recommendation to allocate most of a 16 GB laptop. Recreate Ollama and API/worker after changes. With multiple profiles enabled, the inference service's shared memory limit must cover the largest selected profile. The one-loaded-model and three-thread defaults remain.

```bash
sudo docker compose --profile inference up -d --force-recreate ollama
sudo docker compose up -d --force-recreate api worker
```

A GPU name does not identify its available VRAM. A 4 GB or 6 GB RTX 3050 cannot fully hold a 6.6 GB model plus working memory. Partial offload is possible but requires driver/container support and a responsiveness measurement. Use docs/local-inference.md for the explicit NVIDIA override; integrated Vega remains CPU by default.

## Decide using the same sources

Reimport the same frozen exports for each candidate, leaving collection disabled for these comparisons. Use fresh assessments, the same source selection, 4,096 context tokens and identical retrieval settings. Record accepted components, technologies and connections; inspect whether citations establish the claimed role, not just whether quoted text matches. Include negative and ambiguous statements, product pages, technical prose, and independently annotated relationships.

Track elapsed time, failed JSON/contracts, rejected candidates, missing expected findings, unsupported additions, peak RAM, swap and VS Code/browser responsiveness. Separate cold load time from steady generation. Do not compare precision scores from differently selected documents or different publisher benchmark suites.

The existing synthetic evaluation runner can provide an additional controlled comparison:

```bash
sudo docker compose exec -T api python -m app.evaluate --provider ollama --profile light --split held_out > local-model-evaluation.json
```

This executes the configured model and a rules baseline without writing application history. Its small synthetic corpus is a regression exercise; it is not proof of general performance. A scored source corpus must annotate all acceptable findings, source capture information and relationship semantics. See docs/evaluation.md.

The first decision should be whether LFM2.5 Instruct improves PriSMA's accepted extraction and latency over Qwen3 1.7B on the same laptop. Promote a default only after that measurement. Qwen3.5 2B Q4 and Granite H 1B are the next comparisons. Larger profiles are optional capacity choices, not automatic upgrades.
