# Datawright playbook — default lessons (seeded on install)

For the role that builds + runs ML pipelines, training jobs, and prompt-driven
labeling at scale. Lessons accumulated across projects that have used the
SpineDevelopment template for ML work.

## Local LLMs (Ollama, llama.cpp, vLLM)

- **2026-05-08 — Cold-start the model BEFORE timing real inference.** The first call to a freshly-loaded LLM triggers model loading from disk into RAM, which can take 30-120s for a 5-7GB model. If you `time` the first call, you'll get an absurd number that has nothing to do with steady-state throughput. Always do a throwaway warmup call, then time the second call.

- **2026-05-08 — `eval_duration` is what you want, not wall-clock.** Ollama's response includes `load_duration` (model load, possibly 30s+) and `eval_duration` (actual generation, usually <1s on Metal). For benchmarking, look at `eval_duration / 1e9` to get seconds. For end-to-end latency including load, use wall-clock. Mixing them produces wrong answers.

- **2026-05-08 — Trim the OCR text you send to the model.** A 50-page contract OCR'd produces 100KB+ of text. Sending that all to a 7B model means 30s+ inference and possibly hitting context limits. Heuristic: send the first 1500-3000 chars + last 500 chars. Most contract structure (parties, dates, governing law, signatures) is at the beginning and end; the middle is mostly boilerplate. Always document the trim heuristic in the prompt template.

- **2026-05-08 — Validate JSON output BEFORE parsing.** When asking an LLM to return structured output, always specify the schema explicitly AND validate the response shape after parsing. Models will helpfully include "Sure, here's the JSON:" prefixes, code-fence the output, or hallucinate keys not in the schema. A robust parser:
  ```python
  raw = response['response']
  json_str = raw.strip()
  # Strip code fences if present
  if json_str.startswith('```'): json_str = json_str.split('```')[1].lstrip('json').strip()
  parsed = json.loads(json_str)
  # Validate required keys + value types BEFORE using
  ```

- **2026-05-08 — `temperature: 0` is not strictly deterministic but close enough.** Same prompt + same model + same seed + temperature=0 = same output ~95% of the time on small inputs. For reproducibility (re-running yesterday's labels and getting the same answers), this matters. For diversity-of-output use cases, raise temperature. For classification, always use 0.

## Prompt design

- **Vocabulary control via the prompt > vocabulary control via post-processing.** If you want the model to output `service_agreement`, list `service_agreement` in the prompt as one of the allowed values, with explicit "case-sensitive copy verbatim" instructions. Don't try to fix it in post by mapping arbitrary outputs to your vocabulary.

- **Few-shot examples are cheap and high-leverage.** 1-2 examples in the prompt showing exact input → exact output dramatically improve format compliance. Don't write a 5000-token prompt; write a 1500-token prompt with 2 examples.

- **Disambiguation rules go BEFORE the vocabulary list.** When two categories are similar (e.g. `service_agreement` vs `execution_agreement`), explicit text like "X is the default for case Y unless feature Z is present" prevents 50% of the boundary mistakes.

- **The "uncertain" fallback is a feature, not a flaw.** Always include an explicit `unknown` or low-confidence path with rules for when to use it. Models that are forced to pick will pick poorly when the input is genuinely ambiguous; a properly-prompted model will say "this excerpt is too short" or similar.

- **Version your prompts.** `classify-document.v1.txt`, `v2.txt`, etc. Track changes per version with a one-line summary of what was different. When labels disagree across runs, you need to know which prompt version generated which labels.

## Auto-labeling at scale

- **Always validate on a sample before running on the full corpus.** A 20-doc sample reveals 80% of the issues you'd see on a 1000-doc run, in 1/50th of the time. Extrapolate the wall-clock budget from sample → full BEFORE you start the full run.

- **Persist results incrementally, not in a single big commit at the end.** If the run dies at doc 950 of 1000, you don't want to lose the previous 949 labels. Append to a JSONL file or COMMIT after every N docs.

- **Idempotency: re-running the labeler on the same corpus should produce the same labels.** Use temperature=0, capture the prompt version, and skip docs that already have a label for that prompt version. Don't blow away prior labels — append a new run.

- **Spot-check disagreements before trusting aggregate metrics.** If your auto-labeler disagrees with prior cascade output 25% of the time, that's interesting only if you know whether the disagreements are "auto-labeler is right" (improvement) or "auto-labeler is wrong" (regression). Sample 5-10 disagreements and read the actual contracts.

## Training + fine-tuning

- **Don't fine-tune until you have ≥ 500 high-quality labels and a held-out eval set.** Below that, you're memorizing noise. Auto-labeled training data is fine, but reserve ~10% as "validation" (auto-labeler ran on these too, but you don't train on them — they tell you whether the fine-tuned model is matching the auto-labeler's performance).

- **Class imbalance ruins fine-tuning if not addressed.** If 76% of your training data is `service_agreement` and 1% is `BAA`, the trained model will predict `service_agreement` for everything and look 76% accurate. Either downsample the majority class, upsample the minority, or use class weights in the loss function.

- **Save model checkpoints to a path that's NOT inside iCloud / Dropbox / network drives.** A large checkpoint syncing to the cloud during training will tank your throughput. Use a local-only path (for example under `~/.cache/<your-project>/models/`) excluded from sync.

- **Track training runs in a registry.** Each run gets a unique id, hyperparameters, training data version, validation metrics. Without this, you'll have 7 model files named `model.pt` and no idea which is best.

## Cost discipline at scale

- **Estimate the budget BEFORE the long run.** If a sample of 20 docs took 50 minutes, a full run of 1186 docs takes ~50h × (1186/20) ÷ 60 = ~50 hours. That's 2 days, not 2 hours. Plan accordingly — overnight, multi-day, or parallelize across workers.

- **Parallelize via multiple workers, not multiple model instances.** Ollama serves one request at a time per process (queueing internally). Running 5 worker scripts hitting the same Ollama gives you 1× throughput, not 5×. To get 5× either run 5 Ollama processes on different ports, or use a server that natively batches (vLLM).

- **The sub-1s inference latency on Metal is misleading for batches.** If a single doc takes 2s of inference + 1s of network/parsing = 3s/doc total, a 1000-doc run takes 50 minutes minimum. Inference rarely IS the bottleneck at scale; serialization/storage/network usually dominate.

## Reporting

- **Aggregate metrics + a sample of raw outputs > aggregate metrics alone.** "100% parse-success" is great; "100% parse-success and here are 5 sample outputs you can read" is much better. Architects spot prompt drift in the samples that aggregates would hide.

- **Always include wall-clock time and disk space used.** "It worked" tells me nothing. "It worked, took 35 minutes, wrote 240MB to disk, peaked at 8GB RAM" tells me whether to trust it for a 10× larger run.
