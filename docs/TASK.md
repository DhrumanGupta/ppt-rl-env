# TASK: RL Environment for Prompt-to-PPT with Hybrid Benchmark Reward

## 0) Goal

Build a Torch OpenEnv-compatible reinforcement learning environment where an agent receives a presentation task and must generate a slide deck (`.pptx`, with rendered `.pdf`/images for scoring). The environment reward should combine:

- **PresentBench-style grounded rubric scoring** (fine-grained, instance-specific, strict anti-hallucination)
- **SlidesGen-Bench-style quantitative scoring** (QuizBank content retention, computational aesthetics, editability)

The environment must support training-time reward computation, eval-time full scoring, and stable MLLM-judge usage.

---

## 1) Paper References (local paths)

Use these files as the canonical references while implementing:

- `./PresentBench.pdf`
- `./SlidesGenBench.pdf`

---

## 2) Problem Setup

### 2.1 Task Definition

Each episode corresponds to one presentation-generation problem.

Given:

- a user prompt (topic + intent + audience + constraints), and
- a frozen source pack (documents and structured references),

the agent must produce a slide deck that is:

1. factually grounded in sources,
2. complete with respect to required sections/content,
3. visually usable and coherent,
4. sufficiently editable in native format.

### 2.2 Why a frozen source pack

Do not evaluate against live web retrieval during RL. Source retrieval must be performed before episode start and then frozen. This avoids reward non-stationarity and keeps credit assignment valid.

### 2.3 Episode I/O

Input at reset:

- `prompt_text`
- `source_pack` (PDF/text/images/tables)
- `task_constraints`
- `eval_spec` (frozen checklist + quiz bank + scoring config)

Output at termination:

- `deck.pptx`
- rendered slides (PNG and/or PDF)
- full reward breakdown JSON
- judge evidence logs

---

## 3) RL Formulation

Treat as a finite-horizon **POMDP** (partially observable, because the agent sees compressed source summaries and current deck state, not every raw token at each step unless explicitly queried).

### 3.1 State (internal)

- Scenario data (prompt, source docs, constraints)
- Deck IR (all slides with structured objects)
- Action history
- Evaluation progress (which checklist items are currently likely satisfied)
- Step budget usage

### 3.2 Observation (to policy)

Observation dictionary should include:

- `prompt_summary`: compact instruction text
- `constraints_vector`: normalized numeric constraints (slide min/max, required quantitative count, citation requirement, etc.)
- `source_index_features`: embeddings or retrieval-ready index statistics
- `deck_global_features`: current slide count, avg words/slide, chart count, image count, citation count, overlap warnings, style-consistency signals
- `deck_slide_features`: per-slide compact features (title present, text density, visual objects, references)
- `checklist_progress_estimate`: estimated pass vector (cheap heuristic estimate, not full judge each step)
- `remaining_budget`: normalized remaining steps

### 3.3 Action space

Use a **hierarchical action interface**:

1. **Macro action** (discrete):
   - `ADD_SLIDE`
   - `DELETE_SLIDE`
   - `REORDER_SLIDE`
   - `SET_SLIDE_LAYOUT`
   - `INSERT_TEXT`
   - `ADD_CHART`
   - `ADD_TABLE`
   - `ADD_IMAGE`
   - `ADD_CITATION`
   - `STYLE_UPDATE`
   - `VERIFY_FACT`
   - `STOP`

2. **Action arguments** (parameter head / structured payload):
   - slide indices
   - section labels
   - content snippets
   - source references
   - layout/style IDs
   - chart/table specs

Implementation detail: if direct free-form text action is too unstable, route macro actions to deterministic tool executors + constrained text generation modules.

### 3.4 Transition

`step(action)` mutates Deck IR through a deterministic executor whenever possible. If an action fails validation (invalid slide index, malformed chart spec), apply a small negative penalty and keep state unchanged.

### 3.5 Termination

Episode ends on:

- `STOP` action,
- max step budget reached,
- hard invalidity (cannot render/open deck),
- optional early-abort if repeated invalid actions exceed threshold.

---

## 4) Environment Architecture (detailed)

## 4.1 Core modules

1. **ScenarioManager**
   - samples scenario
   - returns prompt + source pack + constraints

2. **EvalSpecBuilder**
   - builds/fetches frozen per-scenario:
     - PresentBench-style atomic checklist
     - SlidesGen-style quiz bank
     - scoring weights

3. **SourceIndexer**
   - parses source docs
   - stores chunked retrieval index with source locations

4. **DeckIR + DeckExecutor**
   - canonical internal representation of slides
   - deterministic mutators for actions
   - export to `.pptx`

5. **Renderer**
   - converts `.pptx` to per-slide images/PDF
   - computes geometric diagnostics (overlap, font size proxies, density)

6. **ExtractionPipeline**
   - OCR/text extraction
   - chart/table extraction where possible
   - per-slide structured markdown for judge input

7. **JudgeClient (MLLM)**
   - executes item-level binary judgments
   - executes quiz answering calls
   - returns verdict + evidence

8. **AestheticMetricsEngine**
   - computational metrics (harmony, engagement, usability, rhythm)

9. **EditabilityEvaluator (PEI)**
   - inspects file format and object structure
   - maps to PEI level L0..L5

10. **RewardAggregator**
    - combines all branch scores
    - applies hard caps and soft penalties
    - outputs scalar reward + breakdown

11. **ReplayLogger**
    - logs transitions, action payloads, artifacts, reward traces, judge evidence

## 4.2 Recommended code layout

```text
.
├── TASK.md
├── PresentBench.pdf
├── SlidesGenBench.pdf
├── env/
│   ├── openenv_slidegen.py
│   ├── scenario_manager.py
│   ├── eval_spec_builder.py
│   ├── source_indexer.py
│   ├── deck_ir.py
│   ├── deck_executor.py
│   ├── renderer.py
│   ├── extraction_pipeline.py
│   ├── judge_client.py
│   ├── aesthetics.py
│   ├── editability.py
│   ├── reward.py
│   └── logging_utils.py
├── configs/
│   ├── reward_default.yaml
│   ├── judge_prompts.yaml
│   ├── env_default.yaml
│   └── curriculum.yaml
└── data/
    ├── scenarios/
    ├── eval_specs/
    ├── caches/
    └── runs/
```

---

## 5) Hybrid Reward Function (production default)

Use this as the default scalar reward:

`R_total = C_hard * (0.60 * R_PB + 0.40 * R_SG) - P_soft`

Clamp to `[0, 1]` after penalties.

## 5.1 PresentBench branch

`R_PB = 0.15*Fund + 0.10*Visual + 0.20*Complete + 0.25*Correct + 0.30*Fidelity`

Where each dimension is mean of binary checklist items.

- **Fund**: flow, conciseness, language quality, audience suitability, safety
- **Visual**: consistency, readability, overlap checks, layout quality
- **Complete**: required sections and key points present
- **Correct**: required items accurate
- **Fidelity**: slide-by-slide source-grounding; no fabricated claims

Binary rule: partial pass is `0`, full pass is `1`.

## 5.2 SlidesGen branch

`R_SG = 0.45*Quiz + 0.35*Aesthetic + 0.20*Editability`

- `Quiz = 0.50*QuizConcept + 0.50*QuizData`
- `Aesthetic = 0.20*Harmony + 0.20*Engagement + 0.35*Usability + 0.25*Rhythm`
- `Editability = map(PEI level)` with nonlinear mapping:
  - `L0:0.00, L1:0.20, L2:0.45, L3:0.70, L4:0.90, L5:1.00`

## 5.3 Hard caps (`C_hard`)

`C_hard = min(C_open, C_safety, C_fidelity_critical, C_editability_req, C_blankness)`

Defaults:

- `C_open = 0` if deck cannot be opened/rendered
- `C_safety = 0` for severe unsafe content
- `C_fidelity_critical = 0.5` if critical unsupported claim on key slides
- `C_editability_req = 0.7` if editability requirement unmet
- `C_blankness = 0.6` if blank/title-only rate exceeds threshold

## 5.4 Soft penalties (`P_soft`)

`P_soft = 0.02*slide_count_violation + 0.01*overlap + 0.01*missing_citations + 0.01*tiny_text`

---

## 6) Reward computation protocol (MLLM judge)

To reduce variance and hallucinated scoring:

1. One checklist item per judge call (not one giant prompt).
2. One fidelity call per slide.
3. One quiz call per question or small fixed batch.
4. Require evidence:
   - referenced slide number(s)
   - source location(s)
   - brief rationale
5. If evidence missing/weak, mark item fail.
6. Judge params: low temperature (ideally 0), deterministic decoding settings.
7. For critical failures, run adjudication pass with second prompt template.

---

## 7) Episode lifecycle in OpenEnv

## 7.1 `reset(seed, options)`

1. sample scenario
2. load frozen source pack
3. load/build eval spec
4. initialize empty deck or required template skeleton
5. return initial observation + info (`scenario_id`, constraints summary)

## 7.2 `step(action)`

1. validate action
2. mutate Deck IR via executor
3. update cheap diagnostics
4. optional shaping reward (small)
5. if terminal condition met:
   - export `.pptx`
   - render slides
   - run extraction
   - compute full reward branches
6. return `(obs, reward, terminated, truncated, info)`

## 7.3 `info` payload fields

- `reward_total`
- `reward_breakdown` (all sub-scores)
- `hard_caps`
- `soft_penalties`
- `checklist_failures`
- `quiz_failures`
- `judge_evidence_refs`
- artifact paths

---

## 8) Shaping rewards (for training stability)

Use sparse terminal reward for correctness plus light shaping:

- `+` for satisfying required section skeleton early
- `+` for adding citation to unsupported slide
- `-` for repeated invalid actions
- `-` for deleting required content
- `-` for large style inconsistency spikes

Keep shaping small (for example <= 20% of expected terminal scale) to avoid policy gaming.

---

## 9) Eval spec generation details

For each scenario precompute and cache:

1. **TaskSpec JSON**
   - audience, tone, required sections, key claims, quantitative obligations, visual requirements

2. **AtomicChecklist JSON**
   - grouped into 5 PresentBench dimensions
   - includes item text, type, and source anchor hints

3. **QuizBank JSON**
   - concept/data split
   - options + answer + source quote + source location

4. **ScoringConfig JSON/YAML**
   - branch weights
   - hard cap thresholds
   - penalty coefficients

Caching is mandatory for speed and reproducibility.

---

## 10) Observability and diagnostics

For each run, persist:

- action trace with timestamps
- intermediate deck snapshots
- final deck artifacts
- judge requests/responses
- per-item pass/fail vectors
- final reward decomposition

This is required for debugging reward hacking and non-robust behavior.

---

## 11) Reproducibility requirements

1. Fixed seed handling in scenario sampling.
2. Versioned eval specs (hash by source pack + task spec).
3. Deterministic rendering pipeline version pinning.
4. Judge prompt templates versioned and immutable per experiment.
5. Reward config committed as experiment artifact.

---

## 12) Curriculum and training phases

Suggested curriculum:

1. **Phase A (easy)**
   - short source docs
   - low slide counts
   - fewer required sections

2. **Phase B (medium)**
   - mixed domains
   - stricter checklist
   - add quiz-data emphasis

3. **Phase C (hard)**
   - long-context sources
   - high quantitative density
   - strict fidelity caps
   - editability constraints enforced

Promote agent to next phase only when threshold reached on both `R_PB` and `R_SG`.

---

## 13) Baselines to implement first

1. Template-fill heuristic agent
2. Retrieval + summarization heuristic agent
3. Rule-based section-first agent
4. LLM planner + deterministic deck executor

Use these baselines to validate reward sensitivity before RL optimization.

---

## 14) Minimum acceptance criteria (MVP)

The environment is considered usable when:

1. End-to-end episode runs and produces deck artifacts.
2. Full hybrid reward computed with breakdown JSON.
3. Judge evidence logged for every failed critical item.
4. Hard caps correctly suppress pretty-but-ungrounded decks.
5. At least one baseline policy shows monotonic improvement under PPO/A2C.

---

## 15) Risks and mitigations

1. **Judge variance**
   - Mitigation: low temperature, item-level prompts, adjudication for critical items.

2. **Reward hacking via superficial style improvements**
   - Mitigation: fidelity-heavy weighting + hard caps.

3. **High compute cost**
   - Mitigation: two-mode scoring:
     - training mode: sampled checklist + reduced quiz
     - eval mode: full checklist + full quiz

4. **Action-space explosion**
   - Mitigation: hierarchical actions + constrained payload schema.

5. **Non-editable but beautiful outputs**
   - Mitigation: PEI term + editability hard requirement for target tasks.

---

## 16) Open questions to finalize before coding

1. Must every task require native `.pptx`, or allow image/PDF-only outputs?
2. What is max step budget per episode?
3. Which OpenEnv API version should be targeted exactly?
4. Should training use full MLLM judge online, or hybrid with offline approximators?
5. Which domains are in-scope for first scenario pack (academic, business, education, marketing, mixed)?

---

## 17) Immediate implementation order

1. Implement `ScenarioManager` + `EvalSpecBuilder` cache format.
2. Implement `DeckIR` + deterministic `DeckExecutor` with minimal action subset.
3. Implement renderer + extraction pipeline.
4. Implement PresentBench branch scoring first.
5. Add QuizBank scoring.
6. Add aesthetics + PEI scoring.
7. Integrate `RewardAggregator` and OpenEnv class.
8. Add baseline agent and run smoke training.

---

## 18) Deliverables

1. `env/openenv_slidegen.py` with reset/step API and artifact-rich info dict.
2. Configurable reward pipeline implementing this TASK spec.
3. Scenario/eval-spec cache artifacts.
4. Training script and baseline policy.
5. Evaluation report containing branch-wise reward trends and failure analysis.

This document is the authoritative blueprint for implementation.
