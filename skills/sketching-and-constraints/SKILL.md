---
name: sketching-and-constraints
description: >
  Best practices for creating robust, fully constrained 2D sketches in any CAD system. Use this skill
  whenever the agent needs to create a sketch, add geometry to a sketch plane, apply constraints or
  dimensions, or troubleshoot under-constrained or over-constrained sketch states. Also trigger when
  the user mentions "sketch", "constrain", "dimension", "profile", "2D geometry", "sketch plane",
  or any sketch-level operation such as lines, arcs, circles, rectangles, splines, or construction geometry.
---

# Sketching and Constraints — Tool-Agnostic Best Practices

Sketches are the foundation of every 3D CAD model. A well-constrained sketch produces stable,
predictable geometry that survives design changes. A poorly constrained sketch introduces fragility
that cascades through the entire feature tree.

---

## Core Principles

### 1. Always Fully Constrain Sketches

A fully constrained sketch has exactly one valid geometric configuration — no element can be
dragged or repositioned without first removing a constraint. This is the single most important
sketching rule.

- **Under-constrained** geometry can shift unexpectedly during rebuilds or parametric updates,
  causing downstream feature failures.
- **Over-constrained** geometry creates conflicting rules that the solver cannot satisfy,
  leading to errors or silent dimension overrides.
- Most CAD systems use color coding: blue = under-constrained, black/green = fully constrained,
  red = over-constrained. Always aim for fully constrained (black/green) before exiting a sketch.

### 2. Prefer Geometric Constraints Over Dimensional Constraints

There is a general rule: the fewer datum (dimensional) constraints, the better. Use a geometric
constraint in place of a dimensional one whenever possible. Geometric constraints are more
computationally efficient for the solver and express design intent more clearly.

**Common geometric constraints (available across all major CAD platforms):**

| Constraint      | Purpose                                                         |
|-----------------|-----------------------------------------------------------------|
| Coincident      | Lock two points or a point to a curve at the same location      |
| Horizontal      | Force a line or pair of points to be horizontal                 |
| Vertical        | Force a line or pair of points to be vertical                   |
| Parallel        | Make two lines equidistant and non-intersecting                 |
| Perpendicular   | Force two lines to meet at 90°                                  |
| Tangent         | Ensure smooth contact between a line and arc or two arcs        |
| Equal           | Make two lines equal length or two arcs equal radius            |
| Symmetric       | Mirror two points or entities about a centerline                |
| Midpoint        | Lock a point to the midpoint of a line                          |
| Concentric      | Share center points between circles/arcs                        |
| Collinear       | Force two lines onto the same infinite line                     |
| Fix / Lock      | Pin an entity at an absolute position (use sparingly)           |

### 3. Constrain First, Dimension Second

Apply geometric relationships (parallel, perpendicular, symmetric, equal) first to capture the
shape intent, then add dimensional constraints (lengths, angles, radii) to lock down size. This
order produces cleaner, more readable sketches with fewer total constraints.

### 4. Keep Sketches Simple

- Target roughly **20 sketch lines and 3–10 dimensions per sketch** as a guideline.
- Avoid modeling fillets, chamfers, and complex detail within sketches — apply these as
  separate 3D features after extrusion. They are easier to edit, less likely to cause failures,
  and keep the sketch solver fast.
- If a sketch is growing overly complex, split it into multiple simpler features.

### 5. Use Construction Geometry Strategically

Construction lines (reference/auxiliary geometry) help define relationships without contributing
to the final profile. Use them for:

- Centerlines for symmetry constraints
- Angular references
- Tangent guides for complex curves
- Layout lines that other sketches can reference

### 6. Anchor Sketches to Stable References

- Prefer the **origin point** and **origin planes** as primary anchors for your first sketch.
  The origin is the most stable reference in any model — it never moves and never gets deleted.
- Avoid anchoring sketch geometry to edges or faces created by downstream features, as these
  can move or be removed.
- When possible, use **symmetry about the origin** to reduce the number of required dimensions
  and make the model easier to mirror or pattern.

### 7. Be Intentional with References

Every reference you pick creates a parent-child dependency. Ask: "If this referenced face or
edge changes or disappears, should my sketch change too?" If the answer is no, reference the
origin or a stable datum instead.

---

## Constraint Application Workflow

1. **Rough sketch** — Draw approximate geometry without worrying about precision.
2. **Apply geometric constraints** — Horizontal, vertical, parallel, perpendicular, symmetric, equal, tangent, coincident.
3. **Add dimensional constraints** — Lengths, radii, angles. Use meaningful values (parametric names if the CAD system supports them).
4. **Verify fully constrained state** — Check the constraint indicator (color or status bar).
5. **Test by dragging** — If any geometry moves freely, you have remaining degrees of freedom to lock down.

---

## Common Pitfalls

| Pitfall                          | Why It's a Problem                                    | Fix                                                    |
|----------------------------------|-------------------------------------------------------|--------------------------------------------------------|
| Relying only on dimensions       | Creates cluttered, hard-to-edit sketches               | Replace with geometric constraints where possible      |
| Using Fix/Lock excessively       | Hides real constraint problems, blocks parametric updates | Use proper relational constraints instead             |
| Ignoring inferred constraints    | Auto-constraints may apply silently, causing over-constraint later | Review applied constraints; disable auto-constraints for precision work |
| Dimensioning from unstable edges | Creates fragile parent-child links                     | Dimension from origin planes or stable datums          |
| Putting fillets in sketches      | Adds complexity, slows solver, harder to edit           | Apply as 3D fillet/chamfer features after extrusion    |
| Overly complex single sketch     | Difficult to debug, slow to solve, hard for others to read | Split into multiple features with simple sketches    |

---

## References

1. FreeCAD Documentation — "Sketcher Micro Tutorial: Constraint Practices" (wiki.freecadweb.org)
2. Onshape Help — "Working with Constraints" (cad.onshape.com/help)
3. Alibre Design Blog — "Design Intent: A Guide to 3D Parametric Modeling" (alibre.com/blog, Jan 2024)
4. Autocad Everything — "Fusion 360 Constraints & Dimensions" (autocadeverything.com, Sep 2025)
5. Scan2CAD — "Boosting Design Accuracy with Geometric Constraints in CAD" (scan2cad.com, May 2025)
6. Course Sidekick — "Constraining a Sketch in CAD: Importance and Techniques" (coursesidekick.com)
7. Epectec Blog — "What Does It Mean to Constrain a SolidWorks Sketch?" (blog.epectec.com, Feb 2026)
8. MakerLessons — "Onshape: Sketching & Constraints" (makerlessons.com)
9. LinkedIn Engineering — "How can you use constraints in CAD software to ensure accurate models?" (linkedin.com, Mar 2024)
10. Shen et al. — "Aligning Constraint Generation with Design Intent in Parametric CAD" (arxiv.org, Apr 2025)
