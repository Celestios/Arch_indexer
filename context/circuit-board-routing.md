# Circuit Board Routing

## Hierarchical multi-level orthogonal routing architecture

**Id:** 8c849027-1127-48fa-b949-4401ab2bb3fd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture specification, 2026-11-16
**Revisit when:** the board visualizer transitions from 2D hierarchical containment to a different geometric layout engine

The circuit diagram engine routes all inter-component connections through a strictly bounded five-level hierarchy: Level 1 (intra-class stubs exiting right), Level 2 (intra-file escape corridors), Level 3 (intra-zone multi-lane horizontal row highways and vertical buses), Level 4 (intra-column vertical highways), and Level 5 (inter-column vertical departure/arrival highways and horizontal crossbar bridges). Every trace remains confined within the rectangular boundary of its corresponding lowest common ancestor (LCA) container until reaching its designated exit highway.

**Reason:** Unconstrained point-to-point Manhattan routing on large boards (11,400px by 19,600px with 101 IC packages) caused 3,240 vertical track overlaps and 21 package body clippings. Hierarchical containment guarantees that local connections never traverse external zones or foreign columns, establishing deterministic boundaries and clean visual separation.

**Rejected alternative:** Unconstrained A* grid maze routing was rejected because it scales poorly on massive resolutions, produces chaotic jagged bends, lacks semantic hierarchy, and ignores architectural containment boundaries.

**Rejected alternative:** A single global shared bus was rejected because routing all levels into a single shared backbone created severe traffic bottlenecks, line collisions, and completely obscured package ownership.

## Horizontal trunk crossbar bridges for cross-column traffic

**Id:** cd121aeb-0472-449d-906a-d160f2461822
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer review request, 2026-11-16
**Revisit when:** board layout supports horizontal column stacking rather than vertical directory funnels

All Level 5 cross-column lines must route through structured horizontal trunk bridges (`trunk_y`) spanning across the column gap. Traces travel vertically along their source column exit highway to the nearest horizontal trunk bridge, cross the column boundary horizontally along the bridge's assigned track, and then travel vertically along the target column arrival highway before branching into the target row highway.

**Reason:** In previous implementations, adjacent column traces jumped horizontally across the inter-column corridor at their local row highway heights. Because dozens of packages had independent row heights, this produced scattered horizontal lines cutting across the vertical highways at unpredictable coordinates, visually cluttering the inter-column channel. The crossbar bridge bundles these crossings into structured, multi-lane parallel ribbons at dedicated horizontal channels.

**Rejected alternative:** Arbitrary point-to-point horizontal transitions at row heights were rejected because they scattered horizontal segments across the entire vertical height of the board, overlapping zone banners and clipping adjacent package margins.

**Rejected alternative:** A single universal center bridge for the entire board was evaluated (`trunk_highway_mode = "center"`). While functional, forcing all cross-column traffic through one point caused 127 vertical overlaps and large vertical detours for packages near the top or bottom. The `"spaced"` mode (providing 3 bridges across the board height) was chosen as default to distribute traffic and minimize detours.

**Rejected alternative:** A permanent visual canvas overlay (dashed cyan band and label) for the trunk bridge was implemented and then removed per maintainer request to avoid visual noise on the circuit background.

## Dynamic highway gap allocation based on connection traffic

**Id:** c7050dfd-e4a4-435f-bfbe-b3115d761ce1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer instruction, 2026-11-16
**Revisit when:** track step spacing (8px) or clearance rules change

Corridor clearances between columns (`col_gap_w`), between rows within folder zones (`row_gaps`), and zone bottom paddings (`zone_pad_bottom`) are calculated dynamically based on the exact count of passing connections: $\text{Gap} = \max(\text{min\_gap},\, (N_{\text{links}} + k) \times \text{track\_step})$.

**Reason:** Fixed static clearances (such as 144px column gaps or 80px row gaps) were insufficient for high-fanout modules (such as `analyzer.py` with 39 outgoing lines). When connection count exceeded the static track capacity, the track search loop exhausted its offsets and collapsed parallel traces onto identical coordinates, resulting in 3,240 overlapping vertical segment pairs and 3,704 horizontal overlap pairs. Dynamic sizing guarantees sufficient physical lane width for obstacle-free parallel routing.

**Rejected alternative:** Uniformly enlarging all board gaps to a static maximum was rejected because it would inflate board dimensions past 50,000px, leaving sparse components isolated in vast empty space. Dynamic sizing expands only crowded corridors.

## Full-span obstacle collision detection and row highway channel clamping

**Id:** b49a92f2-0361-461c-9f02-7c909855d471
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** bug investigation and fix, 2026-11-16
**Revisit when:** package bounding box clearance padding (8px) is revised

`find_clear_h_track` and `find_clear_v_track` check package obstacle boxes across the full coordinate span $[\min(x_1, x_2), \max(x_1, x_2)]$ from departure point to arrival point, and candidate row highway tracks are strictly clamped to the specific inter-row gap channel (`[row_bot + 6, row_bot + gap - 6]`).

**Reason:** Previously, the track finder evaluated obstacle collisions only across a dummy 60px window and permitted candidate tracks to drift across the entire zone height. Traces spanning 1,300px horizontally across multi-package grid rows (such as `src/db/connection.py`) were blind to intermediate packages, slicing directly through package bodies (21 distinct clipping collisions). Full-span checking and strict channel clamping completely eliminated all 21 clipping collisions.

**Rejected alternative:** Post-routing obstacle push/shove rerouting was rejected due to risk of oscillation and high algorithmic complexity; proactive clearance verification during track allocation guarantees valid paths upfront.
