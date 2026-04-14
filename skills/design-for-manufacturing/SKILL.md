---
name: design-for-manufacturing
description: >
  Best practices for designing parts that are feasible and economical to manufacture. Use this
  skill whenever the agent needs to create geometry intended for real-world production, evaluate
  manufacturability of a design, simplify geometry for a manufacturing process, select appropriate
  wall thickness, draft angles, radii, or tolerances, or when the user mentions "DFM", "DFA",
  "DFMA", "manufacturability", "moldability", "machinability", "printability", "wall thickness",
  "draft angle", "undercut", "tool access", "cost reduction", "production-ready", "CNC",
  "injection molding", "3D printing", "casting", "sheet metal", or "manufacturing constraints".
---

# Design for Manufacturing (DFM) — Tool-Agnostic Best Practices

DFM is the practice of designing parts so they are feasible to make and economical to produce.
It works best when applied early — during concept and initial CAD iterations — before design
freeze, tooling commitments, or supplier selection. A design that looks perfect in CAD can
encounter real-world roadblocks once production begins if manufacturing constraints are ignored.

**The Rule of 10:** The cost to fix a defect increases by roughly 10× at each stage.
A geometry error that costs $100 to fix in CAD costs ~$1,000 during prototyping and ~$10,000
once tooling is cut. DFM keeps you in the low-cost zone.

---

## Universal DFM Principles

These principles apply regardless of manufacturing process:

### 1. Simplify Geometry

- Use the simplest design that maintains the required functionality.
- Fewer features = fewer operations = lower cost and faster cycle time.
- Combine functions into single parts where possible to reduce part count.
- Avoid purely cosmetic complexity that adds manufacturing steps without functional benefit.

### 2. Use Generous Radii

- Internal corners should have the largest radii that function allows.
- Sharp internal corners require small tools, slow feeds, and multiple passes in machining.
- A change from 1mm to 3mm internal radius can cut machining cycle time significantly.
- In injection molding, sharp corners create stress concentrations and flow hesitation.

### 3. Maintain Uniform Wall Thickness

- Consistent wall thickness prevents warping, sink marks, and uneven cooling in molding.
- Avoid abrupt thickness transitions — use gradual tapers (3:1 ratio maximum).
- Recommended wall thickness varies by process (see process-specific tables below).

### 4. Design for Tool Access

- Deep, narrow pockets require long, thin tools that deflect and break easily.
- Ensure cutting tools, mold cores, and inspection probes can reach all features.
- Avoid internal features that can't be reached from the outside without disassembly.

### 5. Minimize Tight Tolerances

- Tolerance only what matters for function. Tighter tolerances = higher cost.
- Use GD&T to allocate tight tolerances to critical features and looser tolerances elsewhere
  (see the tolerancing-and-gdt skill for detailed guidance).
- Standard CNC tolerances of ±0.005" (±0.127mm) are achievable at baseline cost; tighter
  may require secondary operations or specialized inspection.

### 6. Select Appropriate Materials Early

- Material choice drives process selection, cost, lead time, and performance.
- Design to the properties of the chosen material, not the other way around.
- Consider availability: exotic materials have long lead times and limited suppliers.

### 7. Design for Assembly (DFA)

- Minimize the number of parts: fewer parts = simpler assembly = lower cost.
- Use self-locating features (snap fits, pins, alignment bosses) to reduce fixturing.
- Ensure parts can only be assembled in the correct orientation (poka-yoke / mistake-proofing).
- Prefer standard fasteners (M3, M4, M5, etc.) over custom or mixed sizes.

---

## Process-Specific Guidelines

### CNC Machining

| Guideline                     | Recommendation                                        |
|-------------------------------|-------------------------------------------------------|
| Internal corner radii         | ≥ 1/3 of pocket depth; prefer standard tool sizes      |
| Maximum pocket depth          | ≤ 4× tool diameter for stability                      |
| Minimum wall thickness        | ≥ 0.8mm (metals), ≥ 1.5mm (plastics)                  |
| Hole depth                    | ≤ 10× diameter for standard drills                     |
| Threaded hole depth           | ≤ 3× diameter for reliable thread engagement           |
| Avoid: features on multiple faces requiring re-fixturing | Consolidate operations |

### Injection Molding

| Guideline                     | Recommendation                                        |
|-------------------------------|-------------------------------------------------------|
| Draft angle                   | ≥ 1° per side (2° preferred); textured surfaces need more |
| Wall thickness                | 1.0–3.5mm typical; uniform throughout                  |
| Rib thickness                 | ≤ 60% of adjoining wall thickness                      |
| Rib height                    | ≤ 3× rib thickness                                    |
| Boss outer diameter           | ≤ 2× hole diameter                                    |
| Avoid: undercuts (or design sliding/collapsing cores)   | Adds tooling cost        |
| Gate location                 | Thickest section; consider flow path and weld lines    |

### 3D Printing (FDM/SLA/SLS)

| Guideline                     | Recommendation                                        |
|-------------------------------|-------------------------------------------------------|
| Minimum wall thickness        | 0.8–1.2mm (FDM), 0.5–1.0mm (SLA), 0.7–1.0mm (SLS)   |
| Overhang angle                | ≤ 45° from vertical without supports (FDM)             |
| Minimum feature size          | ≥ 2× nozzle diameter (FDM), ≥ laser spot size (SLA)   |
| Hole diameter accuracy        | Undersize holes by ~0.1–0.2mm for FDM, test-fit first |
| Build orientation             | Optimize for strength, surface finish, and support     |
| Avoid: large flat surfaces (prone to warping)           | Add ribs or curvature   |

### Sheet Metal

| Guideline                     | Recommendation                                        |
|-------------------------------|-------------------------------------------------------|
| Minimum bend radius           | ≥ 1× material thickness (varies by material)          |
| Hole-to-edge distance         | ≥ 2× material thickness                               |
| Hole-to-bend distance         | ≥ 2.5× material thickness + bend radius               |
| Tab/slot width                | ≥ 2× material thickness                               |
| Bend relief                   | Add at intersecting bends to prevent tearing           |
| Grain direction               | Align bends perpendicular to grain for strength        |

---

## DFM Workflow in the CAD Agent Context

When the agent is generating CAD geometry for a part:

1. **Ask about the manufacturing process** early (or infer from context).
2. **Apply process-specific guidelines** from the tables above during geometry creation.
3. **Check wall thickness** — no section thinner than the process minimum.
4. **Check radii** — no internal corners sharper than the process allows.
5. **Check draft** (for molded parts) — add draft angles to all faces parallel to the pull direction.
6. **Check tool access** — can every feature be reached by the manufacturing tool?
7. **Minimize unique operations** — consolidate features that require separate setups.
8. **Verify tolerances** are appropriate for the process capability.

---

## References

1. Dassault Systèmes — "What is DFM, Design For Manufacturing?" (3ds.com)
2. Xometry — "Understanding Design for Manufacturing (DFM): Definition, Process, and Examples" (xometry.com, Mar 2024)
3. Fictiv — "Design for Manufacturing (DFM): A Guide for Smarter and More Efficient Production" (fictiv.com, Aug 2025)
4. Xometry Pro — "Design for Manufacturing (DfM)" (xometry.pro, Feb 2026) — includes the "Rule of 10" cost escalation principle.
5. DFMA.com — "What Is Design for Manufacturing (DFM)?" (dfma.com, Feb 2026)
6. Autodesk — "Design for Manufacturing Software" (autodesk.com)
7. Analogy Design — "DFM Complete Guide" (analogydesign.co, Mar 2026)
8. Wikipedia — "Design for manufacturability" (en.wikipedia.org)
9. 3ERP — "What is Design for Manufacturing: DFM Principles, Process and Techniques" (3erp.com, Jun 2024)
