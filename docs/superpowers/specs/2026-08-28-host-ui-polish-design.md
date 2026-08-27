# Host UI Readability Polish Design

**Status:** Approved

## Goal

Improve the existing PyQt sensor dashboard at its 1440x900 target size without
changing acquisition, protocol, recording, or control behavior. The vibration
plot remains the primary focus; orientation, numeric attitude, and stream
health remain continuously visible.

## Chosen approach

Use a balanced engineering-dashboard hierarchy instead of either a dense
compact layout or a presentation-style oversized layout:

- raise the application base type from 12 px to 13 px;
- use 16 px monospaced type for live numeric values and 12 px labels;
- retain compact controls while increasing their height and spacing slightly;
- give the vibration pane about 70% of the horizontal live area;
- arrange the eight attitude values as two columns by four rows so labels and
  signed values remain readable in the narrower secondary pane;
- replace the stream-health sentence with seven evenly distributed metric
  cells, each with a short label and a clearly separated value;
- preserve the existing dark palette, cyan emphasis, card structure, tabs,
  and OpenGL/fallback orientation behavior.

## Responsive behavior

The window keeps its 1080x700 minimum. Splitters provide sensible initial
ratios but remain user-adjustable. Health metrics share available width evenly;
short labels and fixed metric values avoid truncation at the minimum size.

## Verification

- pytest-qt locks the two-column attitude grid, metric roles, health-cell count,
  and initial splitter proportions;
- the complete automated host suite must pass offscreen;
- regenerate the deterministic 1920x1080 visual baseline and inspect it;
- launch the real CDC application at 1440x900 to verify font rendering, spacing,
  live curves, orientation animation, and status readability;
- run final repository verification before merging the feature branch.
