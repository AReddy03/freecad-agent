---
name: assembly-design
description: >
  Best practices for designing multi-part assemblies in CAD, including top-down vs bottom-up
  strategies, constraint/mate planning, sub-assembly structure, and assembly performance.
  Use this skill whenever the agent needs to assemble multiple parts, add mates or assembly
  constraints, structure sub-assemblies, create a skeleton or layout sketch for an assembly,
  or manage large assemblies. Also trigger for "assembly", "mate", "sub-assembly",
  "top-down design", "bottom-up design", "master model", "skeleton model", "assembly constraint",
  "fit", "clearance", "interference check", or "BOM" (bill of materials).
---

# Assembly Design — Tool-Agnostic Best Practices

An assembly brings individual parts together into a functioning product. How you structure,
constrain, and manage that assembly determines whether design changes propagate cleanly or
cause cascading failures across dozens of components.

---

## Assembly Design Strategies

### Bottom-Up Design

Build individual parts independently, then combine them into assemblies.

**When to use:**
- Most components are off-the-shelf, purchased, or reused from prior projects.
- The product is small enough for one or a few designers.
- Parts have well-defined interfaces from an existing specification.
- Team members can work independently on separate components.

**Strengths:**
- Each part is self-contained and reusable across projects.
- Parts can be developed in parallel by different team members.
- Simpler file management — each part stands alone.

**Weaknesses:**
- Fit issues may not be discovered until assembly time.
- No central mechanism to propagate assembly-level changes to parts.
- Modifying one part may require manual adjustment of mating parts.

### Top-Down Design

Start at the assembly level, define the overall layout and interfaces, then derive
individual part geometry from that context.

**When to use:**
- Components are custom-designed and their shapes depend on the assembly context.
- The product has complex interfaces where parts must match precisely.
- A large team needs a common reference to work from.
- The product will undergo significant iteration (the overall shape may change).

**Strengths:**
- All parts reference a common layout, ensuring consistent interfaces.
- Assembly-level changes propagate automatically to derived parts.
- Reduces fit errors: parts are designed to fit from the start.

**Weaknesses:**
- Requires significant upfront planning.
- Dependencies between parts can create circular reference issues if not managed.
- More complex file relationships and version control.

### Hybrid Approach (Most Common in Practice)

Use top-down design for critical custom sub-assemblies where part interfaces are tightly
coupled, and bottom-up for standard components (fasteners, bearings, motors, etc.) and
modules that are reused across projects.

**Best practice:** The top-level assembly is generally bottom-up (composed of sub-assemblies),
but critical unique sub-assemblies use top-down techniques internally.

---

## Top-Down Techniques

### Layout / Skeleton Sketches

Create a 2D layout sketch at the assembly level that defines:

- Overall envelope dimensions
- Key interface locations (mounting points, mating surfaces)
- Movement ranges for mechanisms
- Clearance zones

Individual parts then reference this layout sketch for their critical dimensions. When the
layout changes, all parts update accordingly.

### Master Model

A single master part or reference model contains:

- All shared surfaces (exterior shell, parting lines, split lines)
- Interface geometry that multiple parts must match

Individual parts extract (copy or reference) the relevant surfaces from the master model.
This is particularly effective for products with complex organic surfaces that span multiple
parts (e.g., consumer electronics enclosures, automotive body panels).

### Skeleton Models

A lightweight reference model (containing only datums, axes, and key dimensions — no solid
geometry) that defines the spatial relationships of the assembly. Parts reference the skeleton
rather than each other, preventing circular dependencies.

---

## Assembly Constraints / Mates

### Constraint Types (Universal Across CAD Platforms)

| Constraint Type | Effect                                               | Common Names                        |
|-----------------|------------------------------------------------------|--------------------------------------|
| Coincident      | Two faces or planes touch / share a location          | Mate, Flush, Coincident             |
| Concentric      | Two cylindrical axes align                            | Insert, Concentric, Axial           |
| Parallel        | Two faces remain parallel at a specified distance     | Parallel, Offset                     |
| Perpendicular   | Two faces at 90°                                      | Perpendicular, Angle (90°)          |
| Tangent         | A face touches a curved surface smoothly              | Tangent                              |
| Fixed           | Component locked at an absolute position              | Ground, Fix, Anchor                 |
| Distance        | Maintain a specified gap between faces                | Distance, Offset Mate               |
| Angle           | Maintain a specified angle between faces              | Angle                                |
| Gear / Rack     | Link rotations between components                     | Gear, Rack and Pinion, Mechanical   |

### Constraint Best Practices

1. **Ground exactly one component.** Typically the base or frame part. This anchors the
   entire assembly. All other components are positioned relative to this grounded component.

2. **Constrain using planes and axes, not random faces.** Datum planes and axes are stable
   references. Feature faces may change if the part is edited.

3. **Fully constrain every component.** An under-constrained component can drift during
   rebuilds. If a component should be free to move (e.g., a hinge), use motion-limiting
   constraints rather than leaving it under-constrained.

4. **Use the minimum number of constraints.** Over-constraining (redundant mates) causes
   solver conflicts. Each component in 3D space has 6 degrees of freedom (3 translation,
   3 rotation) — apply exactly enough constraints to remove the unwanted degrees.

5. **Test with the 20% change.** After constraining, change a key dimension of one part
   by 20%. Does the assembly update logically? Do mating parts adjust correctly?

---

## Sub-Assembly Structure

### When to Create a Sub-Assembly

- A group of parts forms a **functional unit** (e.g., a motor + gearbox + mounting bracket).
- The same group is **reused** in multiple places (e.g., a wheel assembly used 4×).
- The group is **designed by a separate team** or has its own revision cycle.
- The assembly is **too large** to manage as a flat structure (50+ components).

### Structure Best Practices

- Sub-assemblies should be **self-contained**: they should constrain correctly on their own
  without needing the parent assembly context.
- Use a **hierarchical BOM structure** that matches the sub-assembly structure.
- Keep the hierarchy **3–4 levels deep maximum** for most products. Deeper nesting becomes
  hard to navigate.
- Name sub-assemblies by function, not part number: `Drive_Train_Assy` not `SA-0042`.

---

## Assembly Performance

Large assemblies can become slow to open, rebuild, and navigate. Optimize by:

- Using **lightweight or simplified representations** where full detail isn't needed.
- Suppressing components that aren't relevant to the current task.
- Avoiding in-context references between unrelated sub-assemblies.
- Using **envelope parts** (simplified bounding shapes) for visualization of neighboring
  systems without loading full geometry.
- Minimizing the number of assembly-level features (cuts, holes made at the assembly level
  rather than in individual parts).

---

## Verification Checklist

| Check                     | What to Look For                                          |
|---------------------------|-----------------------------------------------------------|
| Interference detection    | Run collision/interference check — no unintended overlaps |
| Motion simulation         | Moving parts operate through full range without collision  |
| BOM accuracy              | Every part appears exactly once with correct quantity      |
| Under-constrained parts   | No components free to drift (unless intentionally mobile)  |
| Reference stability       | Assembly rebuilds cleanly after part-level changes         |
| File dependencies         | No broken links or missing components                     |

---

## References

1. 3HTi — "Bottom-Up vs Top-Down Design: Choose the Best CAD Strategy" (3hti.com, Feb 2025)
2. Medium (Zein) — "Solidworks 3D CAD Assembly Design with Top-Down Design Method" (medium.com, Sep 2023)
3. Solid Edge Documentation — "Top-down and Bottom-up Assembly Design" (soliddna.com)
4. CAE University — "Organizing a design project: Bottom-Up and Top-Down approach" (caeuniversity.com, May 2024)
5. M3 Design — "Guide to Top-Down Design in 3D CAD Modeling" (m3design.com, Dec 2020)
6. Autodesk Fusion Blog — "Top-down Modeling vs. Bottom-up Modeling in Autodesk Fusion" (autodesk.com, Aug 2025)
7. NXRev — "Understanding Assembly Design: Top-Down vs Bottom-Up Modeling" (nxrev.com, Feb 2025)
8. PTC / Creo Documentation — Top-down design with skeleton models and Advanced Assembly Extension.
