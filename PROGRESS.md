# Progress

## Goal
Split reward handling into disjoint PresentBench and SlidesGenBench modules, with `server/utils/reward_kernel.py` acting only as the orchestrator that calls each branch once and combines their rewards.

## Current Status
- [x] Implement native PPT inspection
- [x] Implement shared `TaskSpec` building
- [x] Implement LLM-backed SlidesGenBench QuizBank generation
- [x] Implement partial repair for invalid generated quiz questions
- [x] Split SlidesGenBench into its own utils package
- [x] Split PresentBench into its own utils package
- [x] Refactor `reward_kernel.py` to orchestrate two disjoint branch calls
- [x] Update tests to the split spec structure

## Current Layout
- `server/utils/slidesgenbench/`
  - `prompts.py`
  - `quizbank_service.py`
  - `spec_builder.py`
  - `scoring.py`
- `server/utils/presentbench/`
  - `spec_builder.py`
  - `scoring.py`
- Shared modules still in `server/utils/`
  - `reward_models.py`
  - `reward_inspection.py`
  - `reward_metrics.py`
  - `reward_prompts.py`
  - `reward_kernel.py`

## Current Design
- `reward_kernel.build_eval_spec(...)` now:
  - builds one shared `TaskSpec`
  - builds one `SlidesGenBenchEvalSpec`
  - builds one `PresentBenchEvalSpec`
  - combines them into a top-level `EvalSpec`
- `reward_kernel.evaluate_presentation(...)` now:
  - inspects the presentation once
  - calls PresentBench scoring once
  - calls SlidesGenBench scoring once
  - combines the two branch rewards using branch weights
- `reward_kernel.evaluate_slide(...)` now delegates only to PresentBench slide scoring

## Models Added
- `PresentBenchEvalSpec`
- `SlidesGenBenchEvalSpec`
- `PresentBenchScoreResult`
- `SlidesGenBenchScoreResult`

## Removed / Replaced
- Removed old `server/utils/reward_quizbank_service.py`
- Replaced monolithic hybrid reward logic inside `reward_kernel.py` with benchmark-specific modules

## Validation
- `uv run python -m pytest tests/tools tests/reward -q`
- Result: `38 passed`

## Next Steps
- Continue simplifying shared modules so benchmark-specific code no longer lives in `reward_prompts.py`
- Add a dedicated SlidesGenBench-only scalar API from `TaskSpec + PresentationExtraction + SlidesGenBenchEvalSpec`
- Add benchmark-specific tests beyond the current reward-kernel integration coverage
