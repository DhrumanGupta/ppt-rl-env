# TASK_REWARD: Hybrid Reward Kernel Specification

## 0) Objective

Implement a reward kernel under `src/utils` for a prompt-to-PPT RL environment that combines:

- **PresentBench-style grounded rubric scoring**
- **SlidesGen-Bench-style quantitative scoring**

The kernel must support a **closed-world setup**:

- input prompt is given
- source pack is given and complete
- no web search / external retrieval during reward computation
- a native PPT presentation object is the primary scoring artifact

The kernel must be deterministic at the spec level, auditable at item level, and expose:

- a scalar reward
- detailed diagnostics
- item-level evidence
- deterministic object-level metrics
- optional render/MLLM metrics

## 0.1 Evaluation Principle

This reward kernel is **object-first, render-second**.

Primary scoring path:

1. inspect the native PPT object graph directly
2. extract text, geometry, colors, charts, tables, images, and native presentation metadata
3. compute deterministic metrics from that object graph

Secondary scoring path:

4. if `use_mllm=True`, serialize the presentation to `.pptx`
5. render to PDF or per-slide images
6. use MLLM only for perceptual checks the object graph cannot answer well

Examples of MLLM-only or MLLM-augmented checks:

- perceived readability
- clipping after render
- visual clutter not obvious from bbox geometry alone
- image relevance to slide content
- whether a chart/table is understandable to a human viewer

The kernel must **not** use OCR-first extraction when native object data is available.

## 0.2 Native Tool Surface Assumption

This spec is grounded in the current presentation object surface in this repo:

- `src/utils/pptx_functions.py`
- `src/tools/pptx_tools.py`

The current tool surface supports these native shape kinds:

- `accent_bar`
- `text`
- `citation`
- `chart`
- `table`
- `image`

The reward kernel must score primarily against what this tool surface can actually express. It must not assume unsupported authoring features such as:

- animations
- embedded media
- SmartArt
- arbitrary grouping semantics
- arbitrary master-slide editing

unless those capabilities are explicitly added later.

## 0.3 Full Deck and Intermediate Slide Reward

In addition to the **full-deck reward**, the kernel must also support an **intermediate per-slide reward** for slide-by-slide construction.

The prompt is assumed to contain an explicit ordered slide-wise breakdown such as:

- `Slide 1: ...`
- `Slide 2: ...`

Whenever a new slide is added, the kernel must score that slide against the planned slot for that slide index.

---

## 1) Canonical References

Use these as design references:

- `docs/PresentBench.pdf`
- `docs/SlidesGenBench.pdf`

Related design doc:

- `docs/TASK.md`

Native PPT object references:

- `src/utils/pptx_functions.py`
- `src/tools/pptx_tools.py`

---

## 2) Target Implementation Location

Primary file to implement:

- `src/utils/reward_kernel.py`

Recommended companion files:

- `src/utils/reward_models.py`
- `src/utils/reward_prompts.py`
- `src/utils/reward_inspection.py`
- `src/utils/reward_metrics.py`

The implementation should be modular even if initially kept in a single file.

---

## 3) Reward Kernel Responsibilities

The reward kernel does **three major jobs**:

1. **Build a frozen evaluation spec** from `(prompt, source_pack, constraints)`
2. **Evaluate a candidate presentation** against that spec
3. **Evaluate a newly added slide** against the target slide specification for its index

The evaluation spec must be frozen and reused for all candidate outputs under the same task.

The slide-level intermediate reward must be derived from the same frozen spec. The kernel must not reinterpret the prompt differently for each new slide.

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
    presentation: PptxEditor | Presentation | str,
    *,
    use_mllm: bool = False,
    presentation_semantics: PresentationSemanticIndex | None = None,
    judge: MultimodalJudge | None = None,
    render_service: RenderService | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    mode: str = "eval",
) -> RewardResult:
    ...
```

```python
def evaluate_slide(
    eval_spec: EvalSpec,
    slide_index: int,
    *,
    presentation: PptxEditor | Presentation | None = None,
    slide_extraction: SlideExtraction | None = None,
    presentation_semantics: PresentationSemanticIndex | None = None,
    use_mllm: bool = False,
    judge: MultimodalJudge | None = None,
    render_service: RenderService | None = None,
    inspection_service: PresentationInspectionService | None = None,
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
    presentation: PptxEditor | Presentation | str,
    *,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    presentation_semantics: PresentationSemanticIndex | None = None,
    judge: MultimodalJudge | None = None,
    render_service: RenderService | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: AestheticsService | None = None,
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
    presentation: PptxEditor | Presentation | None = None,
    slide_extraction: SlideExtraction | None = None,
    presentation_semantics: PresentationSemanticIndex | None = None,
    task_constraints: TaskConstraints | None = None,
    use_mllm: bool = False,
    judge: MultimodalJudge | None = None,
    render_service: RenderService | None = None,
    inspection_service: PresentationInspectionService | None = None,
    aesthetics_service: AestheticsService | None = None,
    previous_slide_extractions: list[SlideExtraction] | None = None,
    cache_dir: str | None = None,
    mode: str = "eval",
) -> IntermediateSlideRewardResult:
    ...
```

Notes:

- `presentation` is the primary input.
- A `str` path is allowed as a compatibility adapter.
- The implementation should prefer the live native presentation object whenever available.
- `use_mllm` is a runtime scoring option, not a task constraint.

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
    extra_constraints: dict[str, Any] = field(default_factory=dict)
```

Evaluation-time options such as `use_mllm` should not be stored in `TaskConstraints`.

## 5.3 Capability Profile

The reward must be capability-aware.

```python
@dataclass
class CapabilityProfile:
    supported_shape_kinds: set[str]
    supports_native_text: bool
    supports_native_chart: bool
    supports_native_table: bool
    supports_native_image: bool
    supports_runtime_theme_binding: bool
    supports_grouping: bool
    supports_master_editing: bool
    supports_animation: bool
    supports_embedded_media: bool
```

For the current environment, `supported_shape_kinds` should minimally include:

- `accent_bar`
- `text`
- `citation`
- `chart`
- `table`
- `image`

## 5.4 Object-First Presentation Inspection Models

Replace OCR-first extraction with native presentation inspection.

```python
@dataclass
class PresentationExtraction:
    slide_count: int
    slide_ids: list[int]
    slides: list[SlideExtraction]
    deck_metrics: dict[str, Any]
    theme_summary: dict[str, Any]
    metadata: dict[str, Any]
```

```python
@dataclass
class SlideExtraction:
    slide_index: int
    slide_id: int
    layout_name: str | None
    background_color_hex: str | None
    title_text: str | None
    all_text: str
    citations: list[str]
    shapes: list[ShapeExtraction]
    text_metrics: dict[str, Any]
    layout_metrics: dict[str, Any]
    color_metrics: dict[str, Any]
    metadata: dict[str, Any]
```

```python
@dataclass
class ShapeExtraction:
    shape_id: int
    shape_kind: str
    semantic_role: str | None
    name: str | None
    x: float
    y: float
    w: float
    h: float
    z_index: int
    fill_color_hex: str | None
    line_color_hex: str | None
    raw_text: str | None
    text_blocks: list[TextBlockExtraction]
    chart: ChartExtraction | None
    table: TableExtraction | None
    image: ImageExtraction | None
    metadata: dict[str, Any]
```

```python
@dataclass
class TextBlockExtraction:
    paragraph_texts: list[str]
    bullet_levels: list[int | None]
    font_names: list[str | None]
    font_sizes_pt: list[float | None]
    bold_flags: list[bool | None]
    italic_flags: list[bool | None]
    color_hexes: list[str | None]
```

```python
@dataclass
class ChartExtraction:
    chart_type: str
    title: str | None
    categories: list[str]
    series: list[dict[str, Any]]
    has_legend: bool
    axis_labels: dict[str, Any]
    style_metrics: dict[str, Any]
```

```python
@dataclass
class TableExtraction:
    rows: int
    cols: int
    cells: list[list[str]]
    header_present: bool
    style_metrics: dict[str, Any]
```

```python
@dataclass
class ImageExtraction:
    width_px: int | None
    height_px: int | None
    content_hash: str | None
    metadata: dict[str, Any]
```

This extraction is the canonical candidate-deck representation.

## 5.5 Optional Semantic Sidecar

Some authoring intent exists only at tool-call time and may not be perfectly recoverable from a saved `.pptx`. Support an optional semantic sidecar.

```python
@dataclass
class PresentationSemanticIndex:
    slide_semantics: dict[int, dict[str, Any]]
    shape_semantics: dict[tuple[int, int], dict[str, Any]]
    metadata: dict[str, Any]
```

This may contain:

- declared tool shape type
- user-defined shape name
- inferred semantic role
- action provenance

If absent, the kernel should fall back to deterministic heuristics.

## 5.6 TaskSpec

Keep the task spec intentionally simple.

The goal is not to build a perfect planning ontology. The goal is to freeze a small, stable task description that the reward kernel can reuse for all candidate decks.

```python
@dataclass
class RequiredSlideSpec:
    slide_index: int
    slide_role: str
    title_hint: str | None
    instructions: str
    required_points: list[str]
    required_exact_values: list[str]
    required_shape_kinds: list[str]
    citation_required: bool
    metadata: dict[str, Any]
```

```python
@dataclass
class TaskSpec:
    task_id: str
    prompt: str
    audience: str | None
    tone: str | None
    min_slides: int | None
    max_slides: int | None
    required_sections: list[str]
    required_points: list[str]
    required_slides: list[RequiredSlideSpec] | None
    citation_required: bool
    require_quantitative_content: bool
    capability_profile: CapabilityProfile
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

`required_sections` should be short labels such as:

- `title`
- `agenda`
- `background`
- `results`
- `conclusion`

`required_points` should be the key facts or ideas the deck must cover at deck level.

`required_shape_kinds` should use only supported shape kinds such as:

- `text`
- `citation`
- `chart`
- `table`
- `image`
- `accent_bar`

Do not encode unsupported forms as hard requirements.

## 5.7 Checklist and Quiz

```python
@dataclass
class ChecklistItem:
    item_id: str
    dimension: str
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
    question_type: str
    question: str
    options: list[str]
    correct_answer: str
    explanation: str
    source_refs: list[str]
    source_quotes: list[str]
```

## 5.8 EvalSpec + Results

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

The builder must also be **capability-aware**.

## 6.2 Step A: Prompt normalization

Extract normalized intent fields from prompt:

- topic
- purpose
- target audience
- tone
- explicit structure constraints
- slide count constraints
- factual strictness constraints
- citation constraints
- quantitative requirements
- requested slide roles or structure
- requested supported visual forms

Default inference policy:

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

Source normalization is separate from presentation inspection.

## 6.4 Step C: TaskSpec construction

From prompt + source evidence, derive only the fields the runtime scorer needs:

1. short required section labels
2. required deck-level points
3. required slide-wise plan if the prompt provides one
4. citation policy
5. whether quantitative content is required
6. capability-aware supported shape expectations

### 6.4.1 Required sections

`required_sections` should stay short and generic. Prefer labels that are easy to check from slide titles and content, for example:

- `title`
- `agenda`
- `background`
- `method`
- `results`
- `timeline`
- `summary`
- `conclusion`

Do not create a deep ontology here. If the prompt is vague, keep `required_sections` sparse and let `required_points` carry the substantive requirements.

### 6.4.2 Required deck-level points

Create a short list of important required points from source evidence.

Each point should represent one verifiable requirement, such as:

- exact metric
- key definition
- mandatory comparison
- required timeline milestone
- required per-segment facts

Point quality requirements:

- clear source refs
- clear source quote(s)
- unambiguous wording
- explicit exact values only when they matter for scoring

### 6.4.3 Required slide specs

If the prompt contains an explicit ordered slide plan, extract it into `RequiredSlideSpec[]`.

Expected prompt patterns include:

- `Slide 1: Title slide introducing ...`
- `Slide 2: Market overview with TAM/SAM/SOM`
- `Slide 3: Product architecture with components A/B/C`

Normalize each slide instruction into:

- `slide_index`
- `slide_role`
- optional `title_hint`
- `instructions`
- `required_points`
- `required_exact_values`
- `required_shape_kinds`
- whether citations are required on this slide

Mapping rules:

1. `slide_index` comes from the prompt order.
2. `required_points` should be the minimal set of facts or ideas needed for the slide to count as complete.
3. `required_exact_values` should contain only high-value exact numbers belonging on that slide.
4. `required_shape_kinds` should use only supported kinds such as `chart`, `table`, `image`, `citation`, `accent_bar`, `text`.
5. If the prompt requests an unsupported visual form, record it in metadata and downgrade it to the nearest supported proxy when reasonable.

Keep each `RequiredSlideSpec` lightweight. It should be something a small model can reliably produce and a deterministic scorer can reliably consume.

For this project, assume slide-wise breakdown **is available**.

## 6.5 Step D: Difficulty/richness scaling

Scale checklist and quiz size by source richness.

Signals:

- source token volume
- page count
- number of figures/tables
- quantitative density
- number of required points

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

Typical items:

- slide count in range
- central theme clarity
- logical progression
- title-content alignment
- conciseness
- audience/tone suitability
- language quality
- no non-slide artifacts

Use deterministic object checks where possible. Reserve judge reasoning for discourse quality.

### 6.6.2 Visual/layout items

Mostly deterministic and object-driven.

Typical items:

- design consistency
- readable text size
- no harmful overlap/clipping
- text/visual balance
- charts/tables where needed
- visual annotation clarity
- no placeholder/blank misuse

Use native inspection for:

- font size
- geometry overlap
- object density
- color contrast
- supported visual presence

Use rendered PDF/MLLM only for residual perceptual checks.

### 6.6.3 Completeness items

Generation rule:

- each required section gets >=1 item
- each important required point gets one item

These should be scored from object-extracted text/chart/table content.

### 6.6.4 Correctness items

Generation rule:

- for each important unit, check factual correctness
- if required item is missing, correctness fails too

Use native text, table cells, and chart series values as canonical candidate content.

### 6.6.5 Fidelity items

Generation rule:

- one base item per slide
- extra items for quantitative/chart-heavy slides

Base item template:

"Is all content on Slide N fully supported by source pack (claims, numbers, references, chart elements), with no fabrication or contradiction?"

Object-first fidelity surface includes:

- text boxes
- citations
- table cells
- chart titles/categories/series values

Image semantics may require optional MLLM assistance.

### 6.6.6 Slide-level checklist generation

For every `RequiredSlideSpec`, precompute a slide-local checklist in `EvalSpec.slide_checklists[slide_index]`.

Slide-local dimensions:

- `prompt_alignment`
- `local_completeness`
- `local_correctness`
- `local_fidelity`
- `local_usability`

Recommended rules:

1. **Prompt alignment**
   - 1 item for slide topic/role matching the target instruction
   - 1 item for title alignment with intended purpose

2. **Local completeness**
   - 1 item per linked `required_point`
   - 1 item if a supported required visual form is expected

3. **Local correctness**
   - 1 item per exact fact/value expected on the slide

4. **Local fidelity**
   - 1 broad item requiring all slide content to be source-supported
   - extra item for exact chart/table correctness if data-heavy

5. **Local usability**
   - 1 item for readability and absence of major clutter/overlap
   - 1 item for visual appropriateness if the slide is supposed to explain content visually

## 6.7 Step F: SlidesGen-style QuizBank generation

Create concept/data MCQs from source pack.

Split:

- 50% concept
- 50% data

Each question must include:

- 4 options
- single correct answer
- explanation
- source refs
- source quote

During evaluation, the "slides-only" answer context should be built from `PresentationExtraction`.

## 6.8 Step G: Scoring config in EvalSpec

Embed default scoring weights and constraints:

```json
{
  "branch_weights": { "pb": 0.6, "sg": 0.4 },
  "pb_dimension_weights": {
    "fundamentals": 0.15,
    "visual_layout": 0.1,
    "completeness": 0.2,
    "correctness": 0.25,
    "fidelity": 0.3
  },
  "sg_dimension_weights": {
    "quiz": 0.55,
    "aesthetics": 0.45
  },
  "quiz_split": { "concept": 0.5, "data": 0.5 },
  "aesthetic_weights": {
    "harmony": 0.2,
    "engagement": 0.2,
    "usability": 0.35,
    "rhythm": 0.25
  }
}
```

Also include:

- hard-cap parameters
- soft-penalty parameters
- capability metadata
- whether render/MLLM paths are allowed for certain dimensions

---

## 7) Evaluating a Presentation Against the Frozen Spec

This section defines `evaluate_presentation(...)`.

## 7.1 Artifact preparation

Input preference:

1. live `PptxEditor` object or native `Presentation`
2. `.pptx` path as compatibility fallback
3. render artifacts only when perceptual checks are requested

Evaluation order:

1. inspect native presentation object directly
2. serialize temp `.pptx` if needed
3. render to PDF/images only if `use_mllm=True`

Required outputs:

- `presentation_extraction`
- `num_slides`
- open/inspection/render status

If deck cannot be inspected or opened, apply hard cap `C_open=0` and return minimal result.

If deck can be inspected but rendering fails, continue deterministic object-first scoring and mark render-dependent sub-scores unavailable.

## 7.2 Presentation inspection

Use `PresentationInspectionService` to build `PresentationExtraction`.

Required extracted fields:

- slide/background/layout metadata
- native text content
- font families, sizes, styles, colors
- shape geometry and z-order
- native chart/table content
- image objects
- citation-like text
- semantic roles when available

This representation is canonical for:

- checklist scoring
- quiz scoring
- deterministic aesthetics
- object-level diagnostics

## 7.3 Cheap deterministic diagnostics

Compute before any judge calls:

- slide count and violations
- blank/title-only slide ratio
- text density
- chart/table/image counts
- citation coverage
- min/median/max font size
- unique font family count
- text/background contrast
- shape overlap from geometry
- occupied area ratio
- title prominence ratio
- chart/table consistency
- quantitative slide count

These drive:

- part of fundamentals/visual checks
- hard caps
- soft penalties

## 7.4 Checklist scoring protocol

Evaluate each checklist item independently.

Important rule:

- do not send deterministic checks to the MLLM if the object graph already answers them exactly

Judge call input should include:

- one item prompt
- relevant slide context
- source snippets/references
- relevant object-level extraction summary
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

Recommended split:

- deterministic/object-only checks: exact numbers, table values, chart values, citation presence, font thresholds, overlap proxies, supported shape presence
- judge-assisted checks: logical progression, audience suitability, image relevance, render-time readability, clutter not fully captured by geometry

## 7.5 Quiz scoring protocol

Critical rule: quiz is answered using **slides only**.

"Slides only" means a flattened deck context derived from `PresentationExtraction`, including:

- native text
- table cell contents
- chart titles/categories/series values
- citation text
- optional image descriptions if `use_mllm=True`

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

Prefer deterministic object-derived metrics.

Target dimensions:

- harmony
- engagement
- usability
- rhythm

Examples of deterministic inputs:

- palette consistency from fills/fonts/backgrounds
- contrast and font-size readability
- slide-to-slide density variation
- visual richness from object composition

Aggregate:

`S_aesthetic = 0.20*Harmony + 0.20*Engagement + 0.35*Usability + 0.25*Rhythm`

If `use_mllm=True`, allow an optional perceptual supplement for:

- readability after render
- perceived clutter
- chart/table legibility
- image helpfulness

## 7.8 Intermediate per-slide evaluation protocol

This section defines `evaluate_slide(...)`.

Required inputs:

- `eval_spec`
- `slide_index`
- either `presentation` or `slide_extraction`

Optional:

- `presentation_semantics`
- `previous_slide_extractions`
- `use_mllm`

### 7.8.1 Target slide resolution

Resolve `target_slide_spec` from `eval_spec.task_spec.required_slides` using the given `slide_index`.

Rules:

- if `slide_index` is outside the planned range, return a low-reward result with explicit metadata
- compare only against `RequiredSlideSpec(slide_index=N)`
- do not compare the new slide against the entire deck checklist

### 7.8.2 Slide extraction

If `slide_extraction` is not provided, create it from the native presentation using `PresentationInspectionService`.

Minimum fields:

- title
- native text content
- chart/table objects if present
- visible numbers from text/chart/table
- citation text
- geometry/font/color metrics

### 7.8.3 Slide-local evaluation dimensions

Use five local dimensions:

1. `S_prompt_alignment`
2. `S_local_completeness`
3. `S_local_correctness`
4. `S_local_fidelity`
5. `S_local_usability`

#### A) Prompt alignment

Check whether the slide matches the intended role for that slot.

#### B) Local completeness

Check whether the slide includes the required points and supported required visual forms.

#### C) Local correctness

Check whether slide facts are correct relative to the source pack.

#### D) Local fidelity

Check for hallucination at slide level.

#### E) Local usability

Check readability and local visual quality.

Use deterministic object metrics first. If `use_mllm=True`, add a render-based perceptual check for the single slide.

### 7.8.4 Optional previous-slide context penalties

If `previous_slide_extractions` are provided, compute soft penalties for:

- severe redundancy with earlier slides
- obvious wrong-slot content leakage

These are **soft penalties**, not core dimensions.

---

## 8) Reward Aggregation Formula

## 8.1 Branch scores

PresentBench branch:

`R_PB = 0.15*Fund + 0.10*Visual + 0.20*Complete + 0.25*Correct + 0.30*Fidelity`

SlidesGen branch:

`R_SG = 0.55*Quiz + 0.45*Aesthetic`

Total:

`R_total = C_hard * (0.60*R_PB + 0.40*R_SG) - P_soft`

Clamp final score to `[0,1]`.

Object-first policy:

- correctness and fidelity should be dominated by native object-derived evidence
- render/MLLM should influence only perception-oriented subcomponents unless no native data exists

## 8.2 Hard caps

`C_hard = min(C_open, C_safety, C_fidelity_critical, C_blankness)`

Defaults:

- `C_open = 0` if unopenable/uninspectable
- `C_safety = 0` for severe unsafe content
- `C_fidelity_critical = 0.5` if unsupported critical claim on key slides
- `C_blankness = 0.6` if blank/title-only ratio > threshold

## 8.3 Soft penalties

`P_soft = 0.02*slide_count_violation + 0.01*overlap + 0.01*missing_citations + 0.01*tiny_text`

## 8.4 Intermediate slide reward formula

`R_slide = C_slide_hard * (0.35*S_prompt_alignment + 0.20*S_local_completeness + 0.15*S_local_correctness + 0.20*S_local_fidelity + 0.10*S_local_usability) - P_slide_soft`

Clamp to `[0,1]`.

## 8.5 Intermediate slide hard caps

`C_slide_hard = min(C_slide_open, C_slide_safety, C_slide_fidelity_critical, C_slide_blankness)`

Defaults:

- `C_slide_open = 0` if slide artifact cannot be inspected
- `C_slide_safety = 0` for severe unsafe content
- `C_slide_fidelity_critical = 0.5` if a critical unsupported number/claim appears
- `C_slide_blankness = 0.4` if the slide is effectively blank or title-only when the target requires substance

## 8.6 Intermediate slide soft penalties

`P_slide_soft = 0.03*missing_citation + 0.03*redundancy + 0.02*wrong_slot_behavior + 0.02*tiny_text + 0.02*overlap`

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

Judge prompts should explicitly state:

- native object extraction is canonical candidate content
- rendered PDF/image inspection is only for perceptual or image-semantics questions

If judge output is invalid JSON:

- retry once
- then mark fail with error metadata

---

## 10) Train vs Eval Modes

Kernel must support `mode in {"train", "eval"}`.

## 10.1 Eval mode

- full checklist
- full quiz bank
- full fidelity checks
- full deterministic aesthetics
- optional MLLM perception if enabled

## 10.2 Train mode

Use stratified sampling for judge-assisted checks.

Deterministic object-first checks should still run in full where cheap.

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

Candidate-deck scoring should also optionally persist:

- `presentation_extraction.json`
- `presentation_digest.json`
- temp serialized `.pptx`
- rendered PDF/image paths if generated

`spec_hash` must be returned in result metadata.

---

## 12) Error Handling Requirements

- malformed source pack => explicit exception
- missing page-level source text => fallback to doc-level references with warning
- inspection failure => zero-capped reward result with diagnostic metadata
- render failure => continue object-first scoring where possible
- partial native inspection failure => continue with recorded failure counters
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
- `deterministic_visual_score`

If applicable, also include:

- `vision_visual_score`

`RewardResult.metadata` should include:

- task id
- spec hash/version
- mode
- slide count
- item/question counts
- judge call count
- failure counts
- `used_mllm`
- `inspection_mode`
- `presentation_digest`

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
- `slide_id`
- `target_slide_role`
- `target_title_hint`
- `required_points`
- `judge_call_count`
- `used_previous_slide_context`
- `used_mllm`
- `spec_hash`

---

## 14) Implementation Checklist

1. Create typed models
2. Implement prompt/source normalization
3. Implement capability-aware TaskSpec builder
4. Implement slide-plan parser for prompt slide-wise breakdown
5. Implement native `PresentationInspectionService`
6. Implement rich object-first extraction contracts
7. Implement checklist generator
8. Implement quiz bank generator
9. Implement eval spec caching
10. Implement deck evaluation orchestration
11. Implement intermediate slide evaluation orchestration
12. Implement optional render + MLLM perceptual path
13. Implement branch score aggregation
14. Implement hard cap and penalty application
15. Add deterministic JSON output + diagnostics

---

## 15) Acceptance Criteria

Implementation is accepted when:

1. Same input task always produces same `spec_hash`
2. Checklist contains all 5 full-deck dimensions
3. Slide-wise prompt breakdown is parsed into ordered `RequiredSlideSpec[]`
4. Quiz contains both concept and data questions
5. Grounded factual deck outranks prettier hallucinated deck
6. A correct slide that matches its planned slot scores higher than a topic-mismatched or hallucinated slide
7. Reward output includes item-level evidence and subscore decomposition
8. Both train/eval modes run successfully
9. Native object inspection is the default extraction path
10. Rendering/MLLM is optional and used only for perceptual checks when enabled

---

## 16) Minimal Example Calls

```python
result = compute_presentation_reward(
    prompt=prompt,
    source_pack=source_pack,
    presentation=editor,
    task_constraints=constraints,
    use_mllm=True,
    judge=judge_client,
    render_service=render_service,
    inspection_service=inspection_service,
    aesthetics_service=aesthetics_service,
    cache_dir=cache_dir,
    mode="eval",
)
```

Intermediate slide example:

```python
slide_result = compute_intermediate_slide_reward(
    prompt=prompt,
    source_pack=source_pack,
    slide_index=3,
    presentation=editor,
    task_constraints=constraints,
    use_mllm=False,
    judge=judge_client,
    inspection_service=inspection_service,
    aesthetics_service=aesthetics_service,
    previous_slide_extractions=previous_slide_extractions,
    cache_dir=cache_dir,
    mode="train",
)
```

This document is the authoritative implementation spec for the hybrid reward kernel.
