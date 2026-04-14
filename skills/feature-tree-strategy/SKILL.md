---
name: feature-tree-strategy
description: >
  Best practices for organizing and structuring the CAD feature tree (model history / design tree).
  Use this skill whenever the agent needs to plan the order of modeling operations, organize features
  into logical groups, manage parent-child dependencies, name features, or troubleshoot rebuild
  failures. Also trigger when the user mentions "feature tree", "model tree", "design tree",
  "history tree", "feature order", "rebuild failure", "parent-child", "rollback", or asks about
  how to structure a part model for editability and reuse.
---

# Feature Tree Strategy — Tool-Agnostic Best Practices

The feature tree is the recipe for how a part was built. It records every modeling step in sequence
and encodes all parent-child dependencies. A well-organized tree makes models easy to understand,
edit, and reuse. A poorly organized tree leads to rebuild failures, cascading errors, and parts
that only their creator can modify.

---

## Core Principles

### 1. Plan Before You Model

Before touching the CAD system, sketch a rough outline — on paper or mentally — of the part's
overall shape and its key driving parameters. Identify:

- The **base shape** (the primary extrusion or revolution that defines the part's core form)
- **Functional features** (holes, slots, pockets, bosses that serve a purpose)
- **Detail features** (fillets, chamfers, cosmetic text, decals)
- **2–5 driver dimensions** that control the part's overall size and layout

This planning prevents the most common failure mode: building features on top of arbitrary
geometry and creating an unpredictable dependency chain.

### 2. Follow a Logical Feature Ordering

Organize features in the tree by purpose and volatility, following this general sequence:

| Group (Top → Bottom)     | Contents                                                | Rationale                                        |
|--------------------------|---------------------------------------------------------|--------------------------------------------------|
| 1. Reference Geometry    | Datum planes, axes, coordinate systems, layout sketches | Available throughout; never depend on solid bodies |
| 2. Construction Geometry | Curves, paths, surfaces used as references              | Foundation for solid features                    |
| 3. Base Shape            | Primary extrusion, revolution, or loft                  | Defines the core form                            |
| 4. Functional Features   | Holes, cuts, bosses, pockets, ribs                      | Add function to the base shape                   |
| 5. Patterns & Repeats    | Linear patterns, circular patterns, mirrors             | Replicate functional geometry efficiently        |
| 6. Detail / Finish       | Fillets, chamfers, cosmetic features, text              | Last because they change most often and are most fragile |

This ordering is derived from the **Resilient Modeling Strategy** (Camba et al., 2016), which
groups features by importance, function, and volatility to minimize cascading failures.

### 3. Minimize Parent-Child Depth

Every feature that references another feature creates a dependency. Long chains of dependencies
(Feature A → B → C → D → E) mean that a change to A can break everything downstream.

- Reference **origin planes and stable datums** instead of faces created by recent features.
- Ask: "If I delete or modify the feature I'm referencing, should this feature change too?"
  If the answer is no, find a more stable reference.
- The **Horizontal Modeling** strategy advocates creating datum planes early and referencing
  those rather than feature faces, producing a flat (wide, not deep) dependency graph.

### 4. Keep Features Self-Contained

Each feature should represent one clear design intent:

- **Don't** combine a hole and a pocket into one sketch/extrude operation.
- **Do** create the pocket first, then add the hole as a separate feature.
- Separate features are easier to suppress, reorder, modify, or delete independently.
- Simple sketches rebuild faster and fail less often than complex multi-contour sketches.

### 5. Name Everything

Use descriptive, consistent names for features, sketches, and reference geometry:

- `Base_Plate_Extrude` instead of `Pad001`
- `Mounting_Hole_Pattern` instead of `PolarPattern`
- `Centerline_Axis` instead of `Axis`

Naming conventions make the feature tree self-documenting. Another engineer — or your future
self — should understand the model by reading the tree alone.

### 6. Use Folders / Groups for Organization

Most CAD systems support grouping features into folders or categories. Use them to:

- Collapse completed sections of the tree
- Provide a self-check: "Is this feature in the right group?"
- Navigate large trees (50+ features) without scrolling endlessly

### 7. Put Cosmetic Features Last

Fillets, chamfers, rounds, and cosmetic elements (embossed text, decals) should always appear
at the bottom of the feature tree because:

- They are the **most fragile** features — they depend on edges that may change.
- They are the **most likely to be revised** during development.
- Placing them late keeps rollback clean: you can roll back above all fillets to see the
  raw functional geometry.
- Never reference fillet or chamfer faces in subsequent sketches or features.

### 8. Clean Up As You Go

- **Delete obsolete features** that have been engulfed by later geometry.
- **Don't stack extrudes** to make a part longer — edit the original dimension instead.
- **Don't fill holes to remove them** — delete the hole feature.
- Remove unused reference geometry (work planes, axes) or hide them to reduce clutter.

### 9. Verify with the Rollback Test

Periodically roll back the feature tree to an earlier state and verify:

- The model rebuilds cleanly at each stage.
- Suppressing one functional block yields a clean rebuild.
- The base shape alone represents a valid, recognizable starting point.

### 10. Think About Downstream Users

CAD models often outlive their creators. A model may be revised by a colleague, analyzed by
simulation software, or exported for manufacturing. Design the tree so that:

- A new engineer can understand the model by reading the feature tree.
- Features can be suppressed or modified without needing to understand the entire history.
- Export to STEP/IGES preserves key faces and features.

---

## Quick-Check Diagnostics

| Check                          | How to Test                                               | Pass Criteria                          |
|--------------------------------|-----------------------------------------------------------|----------------------------------------|
| Driver dimension change        | Change 2–5 key dimensions by 20%; rebuild                 | No errors, geometry updates logically  |
| Rollback above fillets         | Roll back to just before the first fillet                  | Clean, functional geometry displayed   |
| Suppress functional block      | Suppress a group of related features                      | Remaining model rebuilds without error |
| Export/import round-trip       | Export STEP, re-import, verify key faces                  | Faces identifiable, geometry intact    |
| Feature tree readability       | Can a colleague understand the model from the tree alone? | Feature names are descriptive          |

---

## Anti-Patterns to Avoid

- **Monolith sketch**: One giant sketch that defines everything — impossible to edit or debug.
- **Random feature order**: Fillets before functional cuts, patterns before base shape.
- **Deep dependency chains**: Feature Z depends on Y depends on X depends on W...
- **Unnamed features**: `Pad`, `Pocket`, `Fillet` repeated 40 times with no context.
- **Hidden parents**: Suppressed or hidden features that are still referenced by visible features.
- **Convenience references**: Picking a face because it's easy to click, not because it's the right datum.

---

## References

1. Camba, J.D., Contero, M., Company, P. — "Parametric CAD Modeling: An Analysis of Strategies for Design Reusability" (Computer-Aided Design, 2016) — Horizontal, Explicit Reference, and Resilient Modeling strategies.
2. Engineers Rule — "Building an Unbreakable Model by Laying the Foundation" (engineersrule.com, Jul 2019)
3. Javelin Technologies — "Leave Errors Behind with SOLIDWORKS Feature Tree Organization" (javelin-tech.com, Oct 2017)
4. Simplexity — "The Top 10 Secrets CAD and SolidWorks Users Need to Know" (simplexitypd.com)
5. GaugeHow — "10 Essential CAD Modeling Tips and Best Practices" (gaugehow.com, Feb 2026)
6. CMU ME 24-688 — "Part Modeling Best Practices" (andrew.cmu.edu)
7. FRCDesign.org — "Feature Tree Best Practices" (frcdesign.org)
8. TechTalentUS — "Best Practices for CAD Design: Parts, Assemblies, and Surfaces" (techtalentus.com, Jan 2026)
