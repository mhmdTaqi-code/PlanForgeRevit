# Plan-Generator Research: What Exists, What Fits, and How to Build Ours

*Survey date: July 2026. Written for TarkeebAI's specific requirements; sources at the end.*

## TL;DR

**Nothing off-the-shelf fits.** Every strong model is trained on Asian (RPLAN/LIFULL) or
European (MSD/ResPlan) apartments — no majlis, no hosh, no guest/family separation, no
single-facade plot logic. **The winning recipe in 2025-26 research is exactly the
architecture TarkeebAI already has**: an LLM that emits floor plans as JSON with absolute
coordinates, trained in two stages (supervised fine-tune → reinforcement learning with
*verifiable rewards*), where the rewards are automatic geometric/adjacency checks.
We already own the two hardest ingredients: a strict JSON schema (`plan_schema.json`)
and a battle-tested rule set (`skills/bim-best-practices` layout rules) that converts
directly into reward functions. What we lack is the dataset — and no one else has it
either, which is the moat.

**Recommendation: build "TarkeebLM" — Qwen2.5-3B/7B + LoRA, SFT on converted open data
(ResPlan/RPLAN → plan_schema.json) + 300-600 Iraqi plans, then GRPO with our validator
as the reward. Ship it as backend #3 inside the existing `plan_generator_server.py`.**

---

## 1. Our requirements (the scorecard)

| # | Requirement | Why |
|---|---|---|
| R1 | Output = exact JSON coordinates (meters) | must drive Revit, not make pictures |
| R2 | Iraqi/Gulf typology: majlis, hosh, hall circulation, blind neighbour walls | the entire point |
| R3 | Controllable: room list, plot size (e.g. 10×20), adjacencies | user briefs are specific |
| R4 | Runs/trains on hobbyist hardware (RTX 3070 Ti 8GB local, Kaggle/Colab free tier) | no budget |
| R5 | Trainable from a SMALL dataset (300-600 plans) | that's all we can collect |
| R6 | Editable/regeneratable (change one room, keep the rest) | review loops |

## 2. The landscape (2019 → 2026)

### Families

| Family | Representatives | Verdict for us |
|---|---|---|
| **GAN graph→plan** | House-GAN, House-GAN++ (2020-21) | superseded; raster output fails R1 |
| **Boundary+graph→plan** | Graph2Plan (2020), WallPlan | needs the boundary AND graph as input; rigid |
| **Diffusion (vector)** | HouseDiffusion (2023), MaskPLAN | vector corners ✓ but our own test: weak checkpoint = broken rooms; retraining needs 10k+ plans (fails R5); GPU-hungry |
| **Diffusion (latent/image)** | Floorplan-Diffusion (2025), ChatHouseDiffusion (2024) | image-space → vectorization loss, fails R1 |
| **LLM zero/few-shot + refiner** | HouseTune (2024-25): GPT-4o CoT → small diffusion refiner | strong results (+79% compatibility vs HouseDiffusion) but leans on a frontier API model (fails R4 for training the refiner: 10k paired samples) |
| **LLM hypergraph** | HypergraphFormer (2026) | editability ✓, but two-model pipeline |
| **LLM JSON + RLVR** ⭐ | *Generative Floor Plan Design with LLMs via RLVR* (2026): Llama-3.3-70B, SFT→GRPO, rewards = adjacency match + area accuracy; **-94% graph edit distance vs HouseDiffusion** | the blueprint. JSON in/out (R1✓), controllable prompt (R3✓). Caveat below on model size |
| **Seq2seq text→layout** | Tell2Design (ACL 2023): T5-base, 80k text-plan pairs | proof that SMALL models learn layout JSON when the format is tight and data is aligned |
| **What we run today** | Architext (GPT-J 162M, 2022) | tiny, works, but no typology control and no Iraqi data |

### The model-size question (critical for R4)

The RLVR paper reports Llama-3 **8B** produced invalid geometry/repetition in *their*
setup, needing 70B. But Tell2Design succeeded with **T5-base (220M)**, and Architext
works at 162M. The difference is task framing: tight output grammar + aligned training
data beats raw scale. For a 3B model we mitigate with:
1. **Constrained/grammar decoding** (JSON schema-guided generation — llama.cpp GBNF or `outlines`),
2. **Best-of-N sampling + auto-scoring** (we already built the scorer in this repo),
3. **A deterministic repair pass** (snap-to-grid, overlap resolution — like our `derive_walls` interval sweep),
4. **GRPO later** to push validity up.

## 3. Datasets

| Dataset | Size | Region | Format | Usable? |
|---|---|---|---|---|
| RPLAN | 80,788 | Asia | raster + vector labels | bootstrap pre-training ✓ |
| LIFULL | ~5M images | Japan | raster | too raw |
| MSD (Modified Swiss Dwellings) | 5.3k complexes / 18.9k apartments | Switzerland | geometry + access graphs | good graphs, wrong typology |
| **ResPlan (2025)** ⭐ | **17,000** | mixed | **JSON vector polygons + room/door/window annotations + adjacency graphs, permissive license** | **best bootstrap source — closest to plan_schema.json** |
| Iraqi/Gulf anything | **0** | — | — | **does not exist → our moat** |

## 4. Verdict

Buy: nothing. Adapt: the **LLM-JSON + RLVR recipe**, at small scale, on our schema.
This is also the strongest *research/publication* angle: first Iraqi/Gulf floor-plan
model + first RLVR whose rewards encode cultural/architectural rules (guest/family
separation, entry-via-hosh, blind party walls) rather than just geometry.

---

## 5. Build plan: TarkeebLM

### Phase A — Bootstrap on open data (2-3 weeks, free GPU)

1. **Converter**: ResPlan JSON → `plan_schema.json` (rooms/walls/doors/windows are all
   there; write `tools/resplan_to_tarkeeb.py`, reuse `validate_plan` as the gate).
   Optionally add RPLAN via existing public vector extractions.
2. **Serialization**: one training sample =
   - *prompt*: room program + plot size + adjacency list (exactly our bubble-diagram
     schema, rendered as compact text),
   - *target*: the plan JSON, canonicalized (sorted rooms, 2-decimal coords, no
     whitespace) to keep sequences short (~1-2k tokens).
3. **SFT**: Qwen2.5-3B-Instruct + LoRA (r=16, alpha=32) on Kaggle T4/P100 (16GB —
   fits with 4-bit base + LoRA). Framework: LLaMA-Factory or axolotl. ~15k samples,
   2-3 epochs.
4. **Decode-time guardrails**: schema-constrained decoding + best-of-6 with the scorer
   from this repo (overlap/area/degenerate checks) + repair pass.
5. **Eval harness**: `validate_plan` pass-rate, room-count fidelity, adjacency match
   (graph edit distance), area MAE — scripted, so every checkpoint gets a number.

### Phase B — The Iraqi dataset (the real work, 4-8 weeks, parallelizable)

Target: **300-600 plans** in `plan_schema.json`. Sources, in order of yield:
1. **Redraw from local practice**: engineering offices' archives, municipality permit
   drawings, your own family/friends' house plans — redrawn (not scanned) directly into
   the schema. This is legally cleanest: you're capturing the *layout topology*, and the
   redrawn geometry is your own work (still: get permission where drawings are private,
   and never include owner-identifying data).
2. **Real-estate listings** (iraqi sites publish plan sketches): use as *reference* to
   redraw typologies; do not copy images into the dataset.
3. **Synthesis**: take the 21 canonical Iraqi typologies (10×20 single-facade, corner
   plot, hosh-front vs hosh-back...), write a parametric generator (plot size, room
   count jitter) → hundreds of rule-valid variants. Mix ~50/50 with real redraws so the
   model learns real irregularity, not just the generator's habits.
4. **Annotation tool**: fastest path — draw in Revit (walls+rooms only) and export via
   a pyRevit script to plan_schema.json (we already have all the API patterns), or a
   50-line matplotlib click-tool. 10-15 plans/day is realistic once fluent.
5. **Augmentation**: mirror (x/y), plot-dimension scaling within typology bounds,
   room-label-preserving jitter → 300 real → ~2-3k effective samples.

### Phase C — Fine-tune + RLVR (2-3 weeks)

1. **SFT round 2**: continue Phase-A checkpoint on the Iraqi set (upweighted 5-10×).
2. **GRPO with verifiable rewards** (TRL library implements it): sample 8 plans per
   prompt, reward =
   - 0 for unparseable/overlapping (hard gate),
   - adjacency-graph match to the prompt,
   - area-program accuracy,
   - **the skill's layout rules as bonuses**: entrance-not-into-bedroom, bathroom
     3-6 m², majlis nearest entrance, openings only street/hosh — every rule in
     `SKILL.md` §Layout is a checkable function. This is the novel part.
3. **Ship**: add `generate_plan_v2` backend to `plan_generator_server.py` (llama.cpp
   GGUF for CPU/8GB-GPU inference — a 3B Q4 runs comfortably on the 3070 Ti), keep
   Architext as fallback, A/B them with the eval harness.
4. **Publish**: model + dataset (the synthetic + license-clean parts) on HuggingFace,
   before/after comparison vs Architext/HouseDiffusion — that's the case study.

### Effort & risk summary

| Risk | Mitigation |
|---|---|
| 3B too weak for valid geometry | constrained decoding + best-of-N + repair (already proven in this repo's pipeline); escalate to 7B Q4 if needed |
| Dataset too small | Phase-A bootstrap carries geometry skills; Iraqi set only has to teach *typology*; augmentation ×5-10 |
| RLVR complexity | it's optional polish — SFT + guardrails alone should already beat Architext decisively |
| Sequence length (big plans) | canonical compact JSON, 2-decimal coords, room-first ordering; 10×20 house ≈ 1.5k tokens ✓ |

## 6. Sources

- [Generative Floor Plan Design with LLMs via RLVR (2026)](https://arxiv.org/html/2605.14117v1)
- [HouseTune: Two-Stage Floorplan Generation with LLM Assistance](https://arxiv.org/html/2411.12279v4)
- [HypergraphFormer: Editable Floor Plan Generation (2026)](https://arxiv.org/html/2605.18932v2)
- [ChatHouseDiffusion](https://arxiv.org/html/2410.11908v1)
- [Floorplan-Diffusion (ICMR 2025)](https://dl.acm.org/doi/10.1145/3731715.3733343)
- [ResPlan: 17,000 vector residential plans (2025)](https://arxiv.org/html/2508.14006v1)
- [MSD: Modified Swiss Dwellings benchmark](https://arxiv.org/abs/2407.10121) · [dataset](https://data.4tu.nl/datasets/e1d89cb5-6872-48fc-be63-aadd687ee6f9)
- [Floor plan generation survey (2025)](https://journals.sagepub.com/doi/10.1177/14780771241290649)
- [Tokenization lets MLLMs understand/generate/edit floor plans (2026)](https://arxiv.org/html/2603.11640)
- [Iraqi courtyard-house typology study](https://www.academia.edu/96655163/Typology_of_traditional_courtyard_houses_as_muslim_functional_spaces_in_low_rise_residential_units_Iraq)
- [Adapting HouseDiffusion to MSD](https://arxiv.org/pdf/2312.03938)
