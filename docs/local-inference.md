# Local inference and profiles

The lightweight CPU default remains qwen3:1.7b with all-minilm embeddings. It caps weights at 2 GB, service RAM at 3 GiB, CPU at 3, threads at 1–3 and generation context at 4,096 tokens. It runs one request at a time and unloads after requests. These limits protect resources; they do not prove responsive multitasking or extraction accuracy.

The request timeout defaults to 180 seconds (MODEL_TIMEOUT_SECONDS, maximum 240). The investigation keeps its 20-minute analysis budget. Slow CPU responses may still exceed either budget; extending a timeout does not improve model quality or guarantee completion. No automatic retry or provider switch is made.

If extraction or relationship review stops after some passages were reviewed, earlier validated results are saved in a partial assessment. The analysis record and all exports retain actual reviewed counts, failed request counts, the stopped stage and its reason. A complete HTTP response is not proof of a valid finding: JSON, citation and structural checks still apply. A failure before any reviewed passage or explicit finding still fails the assessment while retaining supplied sources.

If requested semantic indexing cannot finish, the report explicitly records the incomplete index and uses lexical passage matching. Partial embedding vectors are never selected as a complete semantic index. Once a model stage fails, no subsequent model stage starts in that assessment; a timed-out server may still be finishing its request.

```bash
sudo docker compose --profile inference up -d ollama
sudo docker compose exec ollama ollama pull qwen3:1.7b
sudo docker compose exec ollama ollama pull all-minilm
sudo docker compose exec ollama ollama list
```

Select Local inference → Lightweight → Check availability. Analyze a small document before the full allowance. If the device feels crowded, explicitly choose a smaller compatible model, for example qwen3:0.6b, by changing OLLAMA_MODEL in .env, pulling that name, and recreating API/worker. No model is downloaded by the application.

## Larger optional profiles

Balanced and Advanced are initially disabled. They allow administrator-selected model names rather than claiming a universal best 3–7B model. To enable a tested installed model, set:

```dotenv
ALLOW_LARGE_LOCAL_MODELS=true
OLLAMA_BALANCED_MODEL=your-tested-model-tag
# Optional; leave empty until tested.
OLLAMA_ADVANCED_MODEL=
INFERENCE_MEMORY_BUDGET_BYTES=8000000000
OLLAMA_MEMORY_LIMIT=8g
OLLAMA_CPU_LIMIT=3
LOCAL_GPU_LAYERS=0
```

The 8 GB settings are an example for a deliberately reserved larger budget, not a recommendation for every laptop. Check available host memory, concurrent apps, model weight/quantization and peak working memory before changing them. Balanced weights cap at 5 GB and Advanced at 10 GB by default. The estimate reserves weight×1.35 plus 350 MB for context/activation overhead and refuses a model exceeding the configured budget. Actual peaks may be higher. GPU memory and host RAM are distinct budgets.

```bash
sudo docker compose --profile inference up -d --force-recreate ollama
sudo docker compose up -d --force-recreate api worker
```

Model settings are frozen per new report and its extraction cache. Research questions have separate hosted settings; see [research setup](research-queries.md). Changing the default does not change existing reports' selected model names. Removing an installed model or disabling larger profiles causes an explicit failure.

## NVIDIA GPU option

A GPU name such as RTX 3050 is not sufficient: variants have different VRAM, desktop use occupies memory, and drivers/container access must work. Install/configure NVIDIA Container Toolkit following the official Ollama/Docker instructions, then use the optional compose.nvidia.yaml override. Set LOCAL_GPU_LAYERS=-1 only after deciding to request GPU offload and recreate API/worker.

```bash
sudo docker compose -f compose.yaml -f compose.nvidia.yaml --profile inference up -d ollama
sudo docker compose exec ollama ollama ps
```

Continue using the same override when recreating the GPU service. The optional override is not automatically applied by the installer. This does not configure integrated Vega/ROCm support; CPU is the safe default here. Verify actual loaded-model VRAM/processor behavior during inference. An empty ollama ps after unload is expected and does not prove GPU readiness.

## Manual responsiveness benchmark

```bash
sudo docker stats
# In another terminal, during and after a model request:
free -h
sudo docker compose exec ollama ollama ps
sudo docker compose logs --tail=80 ollama worker
```

Keep VS Code and several browser tabs open while running the same saved sources through each explicitly enabled profile. Record latency, peak host/container RAM, VRAM if available, swap activity, typing/tab responsiveness, JSON failures, expected findings and exact citations. Idle stats cannot establish inference peaks. Reduce model size or collection size if multitasking suffers. Run docs/evaluation.md's comparison; no invented scores are provided.

## Hosted model option

Hosted assessment inference remains disabled by default. Set ALLOW_HOSTED_MODELS=true and GEMINI_API_KEY only after checking your account quota, selected GEMINI_MODEL and embedding availability. Recreate API/worker. This sends source text to that provider and consumes its quota. No automatic hosted fallback occurs.

Research questions use their own enabled-by-default transport, which needs a server API key before any question can run. See [research setup](research-queries.md). They do not require Ollama.

References: [Ollama Docker](https://docs.ollama.com/docker), [running models](https://docs.ollama.com/api/ps), [GPU reservations in Compose](https://docs.docker.com/compose/how-tos/gpu-support/).

## Researched candidate models

See [model-selection.md](model-selection.md) for lightweight candidates, larger options, exact tags, hardware reservations and comparison steps. The upgrade preserves the current default and downloads no weights.
