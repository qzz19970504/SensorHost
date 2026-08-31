# Host UI compact navigation design

## Decision

Use the approved compact top-tab layout rather than a left navigation rail. The
dashboard must retain the full horizontal plot area at the supported 1080 px
minimum window width while reducing the navigation strip's vertical footprint.

## Layout changes

- Fix the tab bar at 38 px and use 8 px by 18 px tab padding.
- Reduce the live page's top inset to 8 px.
- Move the X, Y, Z, and Auto Y controls into the right side of the
  `3-Axis Vibration` card header.
- Keep all header and acquisition-toolbar controls vertically centered.
- Flatten the acquisition toolbar: retain only the toolbar outline and the
  borders of interactive inputs and buttons. Use thin separators between the
  sensor identity, window, and FIFO sections instead of framed groups.
- Integrate the combo-box chevron into the input surface with no independent
  drop-down background or rectangular subcontrol frame.

## Responsive behavior

At 1080 x 700, the compact top tabs must preserve the existing 7:3 primary
split, keep all acquisition controls visible, and avoid clipping the card title
actions. The existing short-window four-column attitude metric reflow remains
unchanged.

## Scope

This change is presentation-only. It does not modify serial discovery,
protocol parsing, acquisition, recording, firmware commands, or package entry
points.

## Verification

- Qt widget tests cover tab dimensions, flattened toolbar hierarchy, header
  action ownership, combo chevron geometry, and the channel-toggle role.
- Regenerate and inspect the deterministic 1920 x 1080 baseline.
- Inspect a temporary 1080 x 700 rendering for clipping and compression.
- Run the complete host/protocol suite, full single-file package build and
  packaged smoke test, followed by the firmware Stage 1 regression gate.
