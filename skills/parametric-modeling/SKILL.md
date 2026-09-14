---
name: parametric-modeling
description: >
  Best practices for building robust, reusable parametric CAD models with clear design intent.
  Use this skill whenever the agent is creating or modifying a 3D model, defining parameters,
  setting up equations or expressions between dimensions, choosing modeling strategies
  (horizontal, resilient, explicit reference), or needs to ensure that a model will update
  predictably when dimensions change. Also trigger for "parametric", "design intent", "reusable
  model", "parameter", "equation", "driver dimension", "design table", or any 3D solid modeling
  operation (extrude, revolve, loft, sweep, pad, pocket, cut, boss, shell, pattern, mirror).
---

# Parametric Modeling — Tool-Agnostic Best Practices

Parametric modeling means building geometry that is controlled by adjustable parameters and
relationships. When done correctly, changing a single dimension propagates intelligently through
the entire model. When done poorly, the same change causes rebuild failures and geometric nonsense.

---

## What Is Design Intent?

Design intent is the set of decisions about what should stay fixed, what should change, and
how changes should propagate. It answers questions like:

- If the overall width doubles, should the holes get bigger? Move outward? Stay the same?
- Is this part symmetric? Should it remain symmetric if one side changes?
- Which dimensions are "drivers" that control the part, and which are "driven" by relationships?

**Set design intent before adding detail.** Changing design intent after the model is mature
is far more expensive than getting it right early.

---

## Core Principles

### 1. Identify Driver Dimensions Early

Every model should have **2–5 key driver dimensions** that control its overall size, layout,
and proportions. All other geometry should follow from these drivers through constraints,
equations, or references.

- Make drivers easy to find in the feature tree (name them clearly, place them in early features).
- Avoid competing drivers — if two dimensions both try to control the same aspect of geometry,
  edits will push geometry sideways or cause solver conflicts.
- Test by changing each driver by ±20% and verifying the model updates logically.

### 2. Capture Relationships, Not Just Numbers

Instead of dimensioning two holes as each being 25mm from the left edge, consider:

- Are the holes symmetric about the centerline? → Use a **symmetry constraint**.
- Should they always be equally spaced? → Use an **equal constraint** or **equation**.
- Should the spacing scale with the part width? → Express spacing as a **ratio** of the width parameter.

This way, changing the part width automatically maintains the correct hole positions without
manual edits to every affected dimension.

### 3. Use Named Parameters and Equations

Most CAD systems support naming parameters (e.g., `Wall_Thickness = 3mm`,
`Hole_Diameter = 6mm`) and writing equations (e.g., `Boss_Height = Wall_Thickness * 2`).

Benefits:

- Self-documenting: the name tells you what the value controls.
- Centralized control: change the parameter once, all dependent geometry updates.
- Reduces errors: no need to manually update multiple dimensions.

### 4. Reference Stable Geometry

When creating new features, choose references carefully:

| Preferred References            | Avoid                                         |
|--------------------------------|-----------------------------------------------|
| Origin planes (XY, XZ, YZ)    | Faces created by fillets or chamfers          |
| Named datum planes             | Faces of features that are likely to change    |
| Stable base feature faces      | Edges that exist only because of a pattern     |
| Construction/layout sketches   | Faces from imported (non-parametric) geometry  |

A reference creates a **dependency**. If the referenced entity changes or disappears, the
dependent feature fails. Choose references that will survive design changes.

### 5. Choose the Right Modeling Strategy

Three formal strategies exist for structuring parametric models. All are tool-agnostic:

**Horizontal Modeling (Delphi)**
- Create many datum planes early, before any solid features.
- All features reference these datums rather than other feature faces.
- Produces a flat dependency graph (few parent-child chains).
- Trade-off: requires significant upfront planning; large number of datum planes can be visually cluttered.

**Explicit Reference Modeling**
- Designate specific "reference features" that other features are allowed to depend on.
- Non-reference features must not be used as parents by other features.
- Produces a controlled, documented dependency structure.
- Trade-off: requires discipline to enforce the reference rules.

**Resilient Modeling Strategy**
- Organize features into ordered groups by importance and volatility.
- Uses simple, intuitive tree structures so minimal effort is needed to understand intent.
- Building errors and their sources can be easily identified because features are grouped logically.
- Trade-off: the grouping convention must be agreed upon and followed consistently.

In practice, most professional workflows use a **hybrid** approach, combining elements of
all three strategies as appropriate for the part's complexity.

### 6. Build the Function, Then Add the Form

Model the functional geometry first (the mechanical features that define how the part works),
then add cosmetic geometry (fillets, chamfers, textures) afterward. This follows the principle
that functional features are more stable than cosmetic ones, which are the most likely to change
during development iterations.

### 7. Use Configurations / Variants

When a family of parts shares the same basic shape but differs in size, hole count, or material:

- Use configurations (SolidWorks), design tables (Creo), configurations (Onshape), or
  spreadsheet-driven parameters rather than duplicating files.
- This ensures consistency: a fix to the base design propagates to all variants.

### 8. Keep the Model Testable

A parametric model should be treated like code: it needs testing.

- **Boundary test**: Set key dimensions to their minimum and maximum expected values. Does
  the model rebuild without errors or self-intersections?
- **Suppress test**: Suppress groups of features. Does the remaining model make sense?
- **Round-trip test**: Export to STEP, re-import. Are critical faces preserved?

---

## Modeling Operation Selection Guide

| Design Goal                    | Preferred Operation           | Notes                                    |
|-------------------------------|-------------------------------|------------------------------------------|
| Constant cross-section along straight path | Extrude (Pad)         | Simplest, most robust                   |
| Constant cross-section along curved path   | Sweep                | Profile must stay normal to path          |
| Axisymmetric shape            | Revolve                       | Use for shafts, rings, cups              |
| Varying cross-section         | Loft                          | Define guide curves for control          |
| Hollow out a solid            | Shell                         | Apply after extrusions, before fillets   |
| Duplicate features            | Pattern (linear/circular)     | Pattern features, not sketch entities    |
| Mirror half a part            | Mirror                        | Model one half, mirror about origin plane |
| Remove material               | Cut / Pocket                  | Use separate feature per functional cut  |

---

## Anti-Patterns

- **Magic numbers**: Dimensions with no named parameter, no equation, no explanation.
- **Copy-paste geometry**: Duplicating a part file instead of using configurations.
- **Over-constraining**: Adding redundant dimensions that conflict with geometric constraints.
- **Ignoring the origin**: Placing geometry far from the origin with no relational anchor.
- **Late design intent**: Trying to add parametric relationships after the model is 80% complete.

---

## References

1. Outsourcing CAD Works — "Best Practices for Creating Parametric CAD Models" (outsourcingcadworks.com, May 2023)
2. Siemens Blog — "Understanding Parametric and Direct Modeling in Modern CAD Tools" (blogs.sw.siemens.com, Jun 2025)
3. Onshape Blog — "How Onshape Has Fundamentally Improved Parametric CAD" (onshape.com, May 2024)
4. Camba, Contero, Company — "Parametric CAD Modeling: An Analysis of Strategies for Design Reusability" (ScienceDirect / Computer-Aided Design, 2016)
5. Novedge — "Mastering Advanced Parametric Modeling in Modern CAD Systems" (novedge.com, Mar 2025)
6. PTC Blog — "Parametric vs. Direct Modeling: Which Side Are You On?" (ptc.com, Sep 2025)
7. Alibre Blog — "Design Intent: A Guide to 3D Parametric Modeling" (alibre.com, Jan 2024)
8. Rynne & Gaughran — cited in Camba et al., on the importance of modeling strategies beyond tool proficiency.
