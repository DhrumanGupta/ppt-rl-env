# TASK_REWARD: Hybrid Reward Kernel Specification

## 0) Objective

Implement a reward kernel under `src/utils` for a prompt-to-PPT RL environment that combines:

- **PresentBench-style grounded rubric scoring** (fine-grained, source-faithful, item-level binary checks)
- **SlidesGen-Bench-style quantitative scoring** (QuizBank retention, computational aesthetics, editability)

The kernel must support a **closed-world setup**:

- Input prompt is given
- Source pack is given and complete
- No web search / external retrieval during reward computation

The kernel must be deterministic at the spec level, auditable at item level, and expose a scalar reward plus detailed diagnostics.

In addition to the **full-deck reward**, the kernel must also support an **intermediate per-slide reward** for slide-by-slide construction. In that setting, the prompt is assumed to contain an explicit ordered slide-wise breakdown (for example, `Slide 1: ...`, `Slide 2: ...`). Whenever a new slide is added, the kernel must be able to score that single slide against the target slide specification for its slot.

---

## 1) Canonical References

Use these papers as implementation references:

- `docs/PresentBench.pdf`
- `docs/SlidesGenBench.pdf`

Related design doc:

- `docs/TASK.md`

---

## 2) Target Implementation Location

Primary file to implement:

- `src/utils/reward_kernel.py`

Recommended companion files:

- `src/utils/reward_models.py` (dataclasses / typed models)
- `src/utils/reward_prompts.py` (judge prompt templates)

The implementation should be modular even if initially kept in a single file.

---

## 3) Reward Kernel Responsibilities

The reward kernel does **three major jobs**:

1. **Build a frozen evaluation spec** from `(prompt, source_pack, constraints)`
2. **Evaluate a candidate deck** (PPT/PDF/slides) against that spec
3. **Evaluate a newly added slide** against the target slide specification for its index

The evaluation spec must be frozen and reused for all candidate outputs under the same task.

The slide-level intermediate reward must be derived from the same frozen spec. The kernel must not re-interpret the prompt differently for each new slide.

The reward kernel does **not** generate slides, does not train policies, and does not browse the web.

---

## 4) Public API (Required)

Implement these entry points:

```python
def build_eval_spec(
    prompt: str,
    source_pack: SourcePack,
    task_constraints: TaskConstraints | None = None,
    *,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> EvalSpec:
    ...
```

```python
def evaluate_presentation(
    eval_spec: EvalSpec,
    pptx_path: str,
    *,
    rendered_slide_paths: list[str] | None = None,
    pdf_path: str | None = None,
    judge: MultimodalJudge,
    render_service: RenderService | None = None,
    extract_service: SlideExtractionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    editability_service: EditabilityService | None = None,
    mode: str = "eval",
) -> RewardResult:
    ...
```

```python
def evaluate_slide(
    eval_spec: EvalSpec,
    slide_index: int,
    *,
    slide_image_path: str | None = None,
    slide_pdf_path: str | None = None,
    slide_extraction: SlideExtraction | None = None,
    judge: MultimodalJudge,
    extract_service: SlideExtractionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    previous_slide_extractions: list[SlideExtraction] | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    ...
```

```python
def compute_presentation_reward(
    prompt: str,
    source_pack: SourcePack,
    pptx_path: str,
    *,
    task_constraints: TaskConstraints | None = None,
    rendered_slide_paths: list[str] | None = None,
    pdf_path: str | None = None,
    judge: MultimodalJudge,
    render_service: RenderService | None = None,
    extract_service: SlideExtractionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    editability_service: EditabilityService | None = None,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> RewardResult:
    ...
```

```python
def compute_intermediate_slide_reward(
    prompt: str,
    source_pack: SourcePack,
    *,
    slide_index: int,
    slide_image_path: str | None = None,
    slide_pdf_path: str | None = None,
    slide_extraction: SlideExtraction | None = None,
    task_constraints: TaskConstraints | None = None,
    judge: MultimodalJudge,
    extract_service: SlideExtractionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    previous_slide_extractions: list[SlideExtraction] | None = None,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    ...
```

`compute_presentation_reward(...)` is the convenience wrapper:

1. build/load spec
2. evaluate candidate deck
3. return final reward package

`compute_intermediate_slide_reward(...)` is the convenience wrapper for slide-by-slide construction:

1. build/load spec
2. resolve the target slide specification for `slide_index`
3. evaluate the new slide only
4. return the intermediate slide reward package

---

## 5) Data Contracts (Required Models)

Use typed dataclasses or strict pydantic models.

## 5.1 SourcePack

```python
@dataclass
class SourceDocument:
    doc_id: str
    title: str
    path: str | None
    mime_type: str
    text: str | None
    pages: list[str] | None
    images: list[str] | None
    metadata: dict[str, Any]
```

```python
@dataclass
class SourcePack:
    task_id: str
    documents: list[SourceDocument]
    metadata: dict[str, Any]
```

## 5.2 TaskConstraints

```python
@dataclass
class TaskConstraints:
    min_slides: int | None = None
    max_slides: int | None = None
    target_audience: str | None = None
    tone: str | None = None
    deck_type: str | None = None
    require_citations: bool = True
    require_quantitative_content: bool = False
    minimum_quantitative_slides: int | None = None
    require_native_pptx: bool = True
    minimum_pei_level: str | None = None
    extra_constraints: dict[str, Any] = field(default_factory=dict)
```

## 5.2.1 Slide extraction model

This model is the normalized representation of a single rendered slide used by the intermediate reward kernel.

```python
@dataclass
class SlideExtraction:
    slide_index: int
    title: str | None
    body_text: list[str]
    bullet_points: list[str]
    numbers: list[str]
    table_summaries: list[str]
    chart_summaries: list[str]
    visual_descriptions: list[str]
    citations: list[str]
    raw_text: str
    metadata: dict[str, Any]
```

For intermediate scoring, this representation should be considered the canonical extracted view of the newly added slide.

## 5.3 TaskSpec

```python
@dataclass
class RequiredSection:
    section_id: str
    title: str
    description: str
    order_index: int
    required: bool = True
```

```python
@dataclass
class RequiredContentUnit:
    unit_id: str
    section_id: str
    unit_type: str
    summary: str
    source_refs: list[str]
    source_quotes: list[str]
    quantitative: bool
    must_appear: bool
    must_be_exact: bool
    visual_recommended: bool
    metadata: dict[str, Any]
```

```python
@dataclass
class TaskSpec:
    task_id: str
    prompt: str
    audience: str
    tone: str
    deck_type: str
    min_slides: int | None
    max_slides: int | None
    required_sections: list[RequiredSection]
    required_content_units: list[RequiredContentUnit]
    required_slides: list[RequiredSlideSpec] | None
    citation_policy: str
    quantitative_policy: dict[str, Any]
    editability_policy: dict[str, Any]
    metadata: dict[str, Any]
```

### 5.3.1 Slide-wise plan models

The per-slide reward depends on an ordered slide plan extracted from the prompt.

```python
@dataclass
class RequiredSlideSpec:
    slide_index: int
    slide_role: str
    title_hint: str | None
    section_id: str | None
    instructions: str
    required_unit_ids: list[str]
    required_keywords: list[str]
    required_exact_values: list[str]
    visual_requirements: dict[str, Any]
    citation_required: bool
    metadata: dict[str, Any]
```

Recommended `slide_role` values include:

- `title`
- `agenda`
- `background`
- `definition`
- `comparison`
- `method`
- `result`
- `timeline`
- `summary`
- `conclusion`

`required_unit_ids` must point back to `RequiredContentUnit.unit_id` so the slide-level reward and deck-level reward are grounded in the same atomic evidence units.

## 5.4 Checklist and Quiz

```python
@dataclass
class ChecklistItem:
    item_id: str
    dimension: str  # fundamentals | visual_layout | completeness | correctness | fidelity
    prompt_text: str
    item_kind: str
    required_slide_scope: list[int] | None
    relevant_sections: list[str]
    source_refs: list[str]
    binary: bool = True
    fail_if_partial: bool = True
    weight: float = 1.0
    evidence_policy: dict[str, Any] = field(default_factory=dict)
```

```python
@dataclass
class QuizQuestion:
    question_id: str
    question_type: str  # concept | data
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    source_refs: list[str]
    source_quotes: list[str]
```

## 5.5 EvalSpec + RewardResult

```python
@dataclass
class EvalSpec:
    task_spec: TaskSpec
    checklist: list[ChecklistItem]
    slide_checklists: dict[int, list[ChecklistItem]]
    quiz_bank: list[QuizQuestion]
    scoring_config: dict[str, Any]
    spec_version: str
    spec_hash: str
```

```python
@dataclass
class RewardResult:
    reward_total: float
    reward_breakdown: dict[str, float]
    hard_caps: dict[str, float]
    soft_penalties: dict[str, float]
    checklist_results: list[dict[str, Any]]
    quiz_results: list[dict[str, Any]]
    aesthetics_results: dict[str, Any]
    editability_results: dict[str, Any]
    artifacts: dict[str, Any]
    metadata: dict[str, Any]
```

```python
@dataclass
class IntermediateSlideRewardResult:
    slide_index: int
    reward_total: float
    reward_breakdown: dict[str, float]
    hard_caps: dict[str, float]
    soft_penalties: dict[str, float]
    checklist_results: list[dict[str, Any]]
    aesthetics_results: dict[str, Any]
    artifacts: dict[str, Any]
    metadata: dict[str, Any]
```

---

## 6) Building the Checklist and Rubric from Input

This section is the core algorithm for `build_eval_spec(...)`.

## 6.1 Inputs

- `prompt`
- `source_pack`
- `task_constraints`

No external context is allowed.

## 6.2 Step A: Prompt normalization

Extract normalized intent fields from prompt:

- topic
- purpose (lecture, investor update, product launch, report, etc.)
- target audience
- tone
- explicit structure constraints
- slide count constraints
- factual strictness constraints
- citation constraints
- quantitative requirements
- visual requirements
- editability requirements

Default inference policy when missing:

- audience: `general_professional`
- tone: `professional`
- citations: required for factual claims
- require native pptx: true

## 6.3 Step B: Source normalization and chunking

Build a source registry with addressable chunks.

Recommended chunk schema:

```json
{
  "chunk_id": "docA_p03_c07",
  "doc_id": "docA",
  "page": 3,
  "section": "Method",
  "chunk_type": "paragraph",
  "text": "..."
}
```

Extract structured evidence candidates:

- key definitions
- key claims
- entities
- dates and percentages
- table rows/columns
- chart values and labels
- equation/formula snippets

## 6.4 Step C: TaskSpec construction

From prompt + source evidence, derive:

1. required section skeleton
2. required content units
3. required slide-wise plan (if prompt contains slide-by-slide breakdown)
4. quantitative exactness policy
5. citation policy
6. editability policy

### 6.4.1 Required sections

Derive by deck type plus source structure.

Examples:

Academic:
- title, agenda, background, method, results, limitations, conclusion

Business:
- title, context/problem, strategy/product, evidence/metrics, plan/roadmap, conclusion

Teaching:
- title, objectives, core concepts, worked examples, recap, references

### 6.4.2 Required content units

Create atomic units from source evidence.

Each unit should be one verifiable requirement, for example:

- exact metric
- key definition
- mandatory comparison
- required timeline milestone
- required per-segment facts

Unit quality requirements:

- clear source refs
- clear source quote(s)
- unambiguous wording
- flagged as `must_be_exact=True` for hard numeric facts

### 6.4.3 Required slide specs

If the prompt contains an explicit ordered slide plan, extract it into `RequiredSlideSpec[]`.

This is mandatory for the intermediate slide reward.

Expected prompt patterns include examples like:

- `Slide 1: Title slide introducing ...`
- `Slide 2: Market overview with TAM/SAM/SOM`
- `Slide 3: Product architecture with components A/B/C`

The parser should normalize each slide instruction into:

- `slide_index`
- `slide_role`
- optional `title_hint`
- `instructions`
- list of linked `required_unit_ids`
- `required_keywords`
- `required_exact_values`
- `visual_requirements`
- whether citations are required on this slide

Mapping rules:

1. `slide_index` is taken from the prompt order, not inferred from source pack.
2. `required_unit_ids` should contain the minimal set of content units needed for this slide to be considered complete.
3. `required_exact_values` should include only high-value exact numbers that belong on that slide.
4. `visual_requirements` should capture expectations like chart/table/image/diagram when the prompt or source pack makes them clearly appropriate.
5. If the prompt says a slide should be a summary or agenda, do not force raw source-detail density onto that slide.

If the prompt does **not** contain a slide-wise breakdown, `required_slides` may be `None`, and the intermediate slide reward API should either:

- raise a clear exception, or
- return a documented unsupported-mode result

For this project, assume slide-wise breakdown **is available**.

## 6.5 Step D: Difficulty/richness scaling

Scale checklist and quiz size by source richness.

Signals:

- source token volume
- page count
- number of figures/tables
- quantitative density
- number of required units

Suggested bins:

- Low: checklist 25-35, quiz 10-12
- Medium: checklist 35-50, quiz 12-18
- High: checklist 50-70, quiz 18-25

## 6.6 Step E: PresentBench-style checklist generation

Checklist must include 5 dimensions:

- `fundamentals`
- `visual_layout`
- `completeness`
- `correctness`
- `fidelity`

### 6.6.1 Fundamentals items

Mostly template-driven, lightly task-conditioned.

Typical items:

- slide count in range
- central theme clarity
- logical progression
- title-content alignment
- conciseness
- audience/tone suitability
- language quality
- no non-slide artifacts

Target count: 8-12.

### 6.6.2 Visual/layout items

Mostly template-driven.

Typical items:

- design consistency
- readable text size
- no harmful overlap/clipping
- text/visual balance
- charts/tables where needed
- visual annotation clarity
- no placeholder/blank misuse

Target count: 8-14.

### 6.6.3 Completeness items

Task-specific and source-specific.

Generation rule:

- each required section gets >=1 item
- each `must_appear` content unit gets one item

Target count: 8-18.

### 6.6.4 Correctness items

Accuracy counterpart to completeness.

Generation rule:

- for each important unit, check factual correctness
- if required item is missing, correctness fails too

Target count: 8-18.

### 6.6.5 Fidelity items

Strong anti-hallucination checks.

Generation rule:

- one base item per slide
- extra items for quantitative/chart-heavy slides

Base item template:

"Is all content on Slide N fully supported by source pack (claims, numbers, references, chart elements), with no fabrication or contradiction?"

Target count: number_of_slides + extras.

### 6.6.6 Slide-level checklist generation

For every `RequiredSlideSpec`, precompute a slide-local checklist and store it in `EvalSpec.slide_checklists[slide_index]`.

These slide-level checklists are used by the intermediate reward kernel.

Slide-local checklist dimensions should be:

- `prompt_alignment`
- `local_completeness`
- `local_correctness`
- `local_fidelity`
- `local_usability`

Recommended generation rules per target slide:

1. **Prompt alignment**
   - 1 item checking that the slide topic/role matches the target slide instruction
   - 1 item checking that the slide title, if present, matches the intended slide purpose

2. **Local completeness**
   - 1 item per linked `required_unit_id` where `must_appear=True`
   - 1 item if a required visual form is expected (chart/table/diagram)

3. **Local correctness**
   - 1 item per exact fact/value that should appear on this slide
   - if a required fact is missing, correctness fails for that fact as well

4. **Local fidelity**
   - 1 broad item: all content on this slide must be source-supported
   - extra item for exact chart/table correctness if the slide is data-heavy

5. **Local usability**
   - 1 item for readability and absence of major clutter/overlap
   - 1 item for visual appropriateness if this slide is meant to include a visual explanation

Typical slide-local checklist size:

- simple agenda/summary slide: 4-7 items
- concept slide: 6-10 items
- quantitative/result slide: 8-14 items

## 6.7 Step F: SlidesGen-style QuizBank generation

Create concept/data MCQs from source pack.

Split:

- 50% concept
- 50% data

Every question must include:

- 4 options (A/B/C/D)
- single correct answer
- explanation
- source refs + source quote

Question quality filters:

- avoid trivial wording
- avoid ambiguous distractors
- prioritize high-value facts and central concepts

## 6.8 Step G: Scoring config in EvalSpec

Embed default scoring weights and constraints:

```json
{
  "branch_weights": {"pb": 0.60, "sg": 0.40},
  "pb_dimension_weights": {
    "fundamentals": 0.15,
    "visual_layout": 0.10,
    "completeness": 0.20,
    "correctness": 0.25,
    "fidelity": 0.30
  },
  "sg_dimension_weights": {
    "quiz": 0.45,
    "aesthetics": 0.35,
    "editability": 0.20
  },
  "quiz_split": {"concept": 0.50, "data": 0.50},
  "aesthetic_weights": {
    "harmony": 0.20,
    "engagement": 0.20,
    "usability": 0.35,
    "rhythm": 0.25
  }
}
```

Also include hard-cap and soft-penalty parameters (Section 8).

---

## 7) Evaluating a PPT against the frozen spec

This section defines `evaluate_presentation(...)`.

## 7.1 Artifact preparation

Input preference:

1. `.pptx`
2. optional pre-rendered PDF/images
3. optional pre-extracted content

If renders are missing, use injected render service.

Required outputs from prep stage:

- `slide_images[]`
- `num_slides`
- open/render status

If deck cannot be opened/rendered, apply hard cap `C_open=0` and return minimal result.

## 7.2 Slide extraction

Use injected extraction service to build per-slide structured content.

Required extracted fields:

- title
- body text
- bullets
- chart/table data (if detectable)
- visual descriptions with semantic relevance
- citation-like text

This extracted representation is used by checklist and quiz scoring.

## 7.3 Cheap deterministic diagnostics

Compute before judge calls:

- slide count and violations
- blank/title-only slide ratio
- text density stats
- chart/table/image counts
- citation coverage proxies
- overlap/clipping proxies (if available)
- tiny text proxies (if available)

These drive:

- part of fundamentals/visual checks
- hard caps
- soft penalties

## 7.4 Checklist scoring protocol (MLLM)

Evaluate each checklist item independently.

Judge call input must include:

- one item prompt
- relevant slide context
- source snippets/references for grounded items
- strict response schema

Required response schema:

```json
{
  "item_id": "correctness_07",
  "verdict": "yes",
  "slide_refs": [4],
  "source_refs": ["docA:p3"],
  "rationale": "...",
  "confidence": 0.88
}
```

Evaluation rules:

- binary yes/no only
- partial satisfaction counts as no
- missing evidence => no
- missing required item => correctness no
- any unsupported detail on a fidelity item => no

## 7.5 Quiz scoring protocol

Critical rule: quiz is answered using **slides only** (not source pack).

Purpose: measure information retention in generated deck.

Per-question output:

```json
{
  "question_id": "quiz_12",
  "selected_answer": "B",
  "correct": true,
  "reasoning": "..."
}
```

Scores:

- `S_quiz_concept = correct_concept / total_concept`
- `S_quiz_data = correct_data / total_data`
- `S_quiz = 0.5*S_quiz_concept + 0.5*S_quiz_data`

## 7.6 Aesthetics scoring

Prefer deterministic service (SlidesGen-style computational metrics):

- harmony
- engagement
- usability
- rhythm

Aggregate:

`S_aesthetic = 0.20*Harmony + 0.20*Engagement + 0.35*Usability + 0.25*Rhythm`

If deterministic pipeline is unavailable, allow temporary judge-based proxy via injected service, but keep API stable.

## 7.7 Editability scoring

Use PEI-style level from injected service:

- L0 static
- L1 patchwork
- L2 vector
- L3 structural
- L4 parametric
- L5 cinematic

Map to score:

- L0=0.00, L1=0.20, L2=0.45, L3=0.70, L4=0.90, L5=1.00

## 7.8 Intermediate per-slide evaluation protocol

This section defines `evaluate_slide(...)`.

This protocol is used when an agent builds slides incrementally and a reward is needed immediately after a new slide is added.

### 7.8.1 Inputs

Required:

- `eval_spec`
- `slide_index`
- one of:
  - `slide_image_path`
  - `slide_pdf_path`
  - `slide_extraction`
- `judge`

Optional:

- `previous_slide_extractions`

`previous_slide_extractions` is used only for secondary penalties like duplication and wrong-slot behavior. The core slide reward must remain anchored to the target slide spec and source pack.

### 7.8.2 Target slide resolution

Resolve `target_slide_spec` from `eval_spec.task_spec.required_slides` using the given `slide_index`.

Rules:

- if `slide_index` is outside the planned range, return a low-reward result with explicit metadata
- if the prompt planned `Slide N`, the newly added slide should be compared only against `RequiredSlideSpec(slide_index=N)`
- do not compare the new slide against the entire deck checklist

### 7.8.3 Slide extraction

If `slide_extraction` is not provided, create it from the slide artifact using the injected extraction service.

Minimum extracted fields:

- title
- body/bullets
- tables/charts if present
- visible numbers
- citation-like text
- visual descriptions

### 7.8.4 Slide-local evaluation dimensions

The intermediate reward should not use deck-level metrics like full quiz bank, deck-wide harmony, full visual rhythm, or PEI.

Instead, score the new slide using five local dimensions:

1. `S_prompt_alignment`
2. `S_local_completeness`
3. `S_local_correctness`
4. `S_local_fidelity`
5. `S_local_usability`

#### A) Prompt alignment

Checks whether the slide matches the intended role for that slot.

Examples:

- if target is an agenda slide, the new slide should not be a results slide
- if target is a title slide, the slide should behave like a title slide
- if target slide instruction names a specific theme, the slide should center on that theme

Judge prompt should reference only the target slide spec and the current slide.

#### B) Local completeness

Checks whether the current slide includes the required units for its slot.

Examples:

- required bullet points present
- required comparison covered
- required visual element included when explicitly expected

#### C) Local correctness

Checks whether slide facts that appear are correct relative to the source pack and target slide spec.

Examples:

- exact values match
- definitions are not distorted
- required timeline order is correct

#### D) Local fidelity

Checks for hallucination at slide level.

This should use a broad question like:

"Is all substantive content on this slide supported by the source pack and consistent with the target slide instruction, with no fabricated claims, unsupported numbers, or contradictory details?"

If one unsupported detail appears, fidelity should fail.

#### E) Local usability

Checks readability and local visual quality, but only at single-slide scope.

Examples:

- text legible
- no major overlap/clipping
- not overloaded with dense unreadable content
- required chart/table is understandable if present

### 7.8.5 Optional previous-slide context penalties

If `previous_slide_extractions` are provided, compute soft penalties for:

- severe redundancy with earlier slides
- obvious wrong-slot content leakage (for example, this slide repeats prior slide instead of fulfilling its own target slot)

These should be **soft penalties**, not core dimensions, because the main purpose is to evaluate whether the new slide satisfies its own planned role.

### 7.8.6 Intermediate slide output schema

Each slide-local checklist item should return evidence just like the full-deck checklist.

Result must include:

- per-dimension local scores
- failed local checklist items
- source refs and rationale
- hard caps and penalties

---

## 8) Reward Aggregation Formula

## 8.1 Branch scores

PresentBench branch:

`R_PB = 0.15*Fund + 0.10*Visual + 0.20*Complete + 0.25*Correct + 0.30*Fidelity`

SlidesGen branch:

`R_SG = 0.45*Quiz + 0.35*Aesthetic + 0.20*Editability`

Total:

`R_total = C_hard * (0.60*R_PB + 0.40*R_SG) - P_soft`

Clamp final score to `[0,1]`.

## 8.2 Hard caps

`C_hard = min(C_open, C_safety, C_fidelity_critical, C_editability_req, C_blankness)`

Default cap values:

- `C_open = 0` if unopenable/unrenderable else 1
- `C_safety = 0` for severe unsafe content else 1
- `C_fidelity_critical = 0.5` if unsupported critical claim on key slides
- `C_editability_req = 0.7` if editability requirement unmet
- `C_blankness = 0.6` if blank/title-only ratio > 10%

## 8.3 Soft penalties

`P_soft = 0.02*slide_count_violation + 0.01*overlap + 0.01*missing_citations + 0.01*tiny_text`

Penalties should be normalized/clipped and reported separately.

## 8.4 Intermediate slide reward formula

The intermediate slide reward is separate from the full-deck reward and should be optimized for immediate local feedback.

Use:

`R_slide = C_slide_hard * (0.35*S_prompt_alignment + 0.20*S_local_completeness + 0.15*S_local_correctness + 0.20*S_local_fidelity + 0.10*S_local_usability) - P_slide_soft`

Clamp to `[0,1]`.

Rationale for weights:

- `prompt_alignment` is highest because the main goal is to reward whether the new slide matches the planned slot in the prompt
- `local_completeness` rewards covering the required content for that slide
- `local_correctness` and `local_fidelity` enforce factual reliability
- `local_usability` provides quick single-slide design feedback without over-weighting aesthetics

## 8.5 Intermediate slide hard caps

`C_slide_hard = min(C_slide_open, C_slide_safety, C_slide_fidelity_critical, C_slide_blankness)`

Defaults:

- `C_slide_open = 0` if slide artifact cannot be read/extracted
- `C_slide_safety = 0` for severe unsafe content
- `C_slide_fidelity_critical = 0.5` if a critical unsupported number/claim appears
- `C_slide_blankness = 0.4` if the slide is effectively blank, placeholder-only, or title-only when the target slide requires substantive content

## 8.6 Intermediate slide soft penalties

`P_slide_soft = 0.03*missing_citation + 0.03*redundancy + 0.02*wrong_slot_behavior + 0.02*tiny_text + 0.02*overlap`

Notes:

- `missing_citation` applies only when `RequiredSlideSpec.citation_required=True`
- `redundancy` and `wrong_slot_behavior` require `previous_slide_extractions`
- penalties should be clipped and reported separately

---

## 9) Judge Prompting and Reliability Rules

To reduce judge variance:

1. one checklist item per call
2. one slide fidelity check per slide
3. one quiz item or small fixed batch per call
4. enforce JSON schema
5. require explicit slide/source refs
6. low temperature / deterministic params
7. optional adjudication retry for critical items only

If judge output is invalid JSON:

- retry once
- then mark fail with error metadata

---

## 10) Train vs Eval Modes

Kernel must support `mode in {"train", "eval"}`.

## 10.1 Eval mode (full)

- full checklist
- full quiz bank
- full fidelity checks
- full aesthetics + editability

## 10.2 Train mode (cheaper)

Use stratified sampling:

- fundamentals: 3-4 items
- visual_layout: 3-4 items
- completeness/correctness: 4-6 items
- fidelity: 4-8 items
- quiz: 8-12 questions

Sampling must be deterministic under seed.

Hard caps should remain active when possible.

---

## 11) Caching and Reproducibility

`build_eval_spec(...)` must cache outputs.

Cache key must hash:

- normalized prompt
- source pack digest
- task constraints
- reward spec version

Persist:

- `task_spec.json`
- `checklist.json`
- `quiz_bank.json`
- `scoring_config.json`
- `eval_spec.json`

`spec_hash` must be returned in result metadata.

---

## 12) Error Handling Requirements

- malformed source pack => explicit exception
- missing page-level source text => fallback to doc-level references with warning
- render failure => zero-capped reward result with diagnostic metadata
- partial extraction failure => continue with recorded failure counters
- judge failure => retry policy then deterministic fail

The kernel must never silently swallow major scoring failures.

---

## 13) Required Output Structure

`RewardResult.reward_breakdown` should include at minimum:

- `R_total`
- `R_pb`, `R_sg`
- `S_fundamentals`, `S_visual_layout`, `S_completeness`, `S_correctness`, `S_fidelity`
- `S_quiz`, `S_quiz_concept`, `S_quiz_data`
- `S_aesthetic`, `S_harmony`, `S_engagement`, `S_usability`, `S_rhythm`
- `S_editability`, `pei_level`

`RewardResult.metadata` should include:

- task id
- spec hash/version
- mode
- slide count
- item/question counts
- judge call count
- failure counts

`RewardResult.artifacts` should include path references where available.

`IntermediateSlideRewardResult.reward_breakdown` should include at minimum:

- `R_slide`
- `S_prompt_alignment`
- `S_local_completeness`
- `S_local_correctness`
- `S_local_fidelity`
- `S_local_usability`

`IntermediateSlideRewardResult.metadata` should include:

- `slide_index`
- `target_slide_role`
- `target_title_hint`
- `required_unit_ids`
- `judge_call_count`
- `used_previous_slide_context` (bool)
- `spec_hash`

---

## 14) Implementation Checklist

1. Create typed models
2. Implement prompt/source normalization
3. Implement TaskSpec builder
4. Implement slide-plan parser for prompt slide-wise breakdown
5. Implement checklist generator (5 full-deck dimensions + slide-local checklists)
6. Implement quiz bank generator
7. Implement eval spec caching
8. Implement deck evaluation orchestration
9. Implement intermediate slide evaluation orchestration
10. Implement branch score aggregation
11. Implement hard cap and penalty application
12. Add deterministic JSON output + diagnostics

---

## 15) Acceptance Criteria

Implementation is accepted when:

1. Same input task always produces same `spec_hash`
2. Checklist contains all 5 dimensions
3. Slide-wise prompt breakdown is parsed into ordered `RequiredSlideSpec[]`
4. Quiz contains both concept and data questions
5. Grounded factual deck outranks prettier hallucinated deck
6. A correct slide that matches its planned slot scores higher than a topic-mismatched or hallucinated slide
7. Reward output includes item-level evidence and subscore decomposition
8. Both train/eval modes run successfully

---

## 16) Minimal Example Call

```python
result = compute_presentation_reward(
    prompt=prompt,
    source_pack=source_pack,
    pptx_path=pptx_path,
    task_constraints=constraints,
    judge=judge_client,
    render_service=render_service,
    extract_service=extract_service,
    aesthetics_service=aesthetics_service,
    editability_service=editability_service,
    cache_dir=cache_dir,
    mode="eval",
)
```

This should return a complete `RewardResult` without requiring external context.

Intermediate slide example:

```python
slide_result = compute_intermediate_slide_reward(
    prompt=prompt,
    source_pack=source_pack,
    slide_index=3,
    slide_image_path=slide_image_path,
    task_constraints=constraints,
    judge=judge_client,
    extract_service=extract_service,
    aesthetics_service=aesthetics_service,
    previous_slide_extractions=previous_slide_extractions,
    cache_dir=cache_dir,
    mode="train",
)
```

This should return a complete `IntermediateSlideRewardResult` for the newly added slide.

---

This document is the authoritative implementation spec for the hybrid reward kernel.
