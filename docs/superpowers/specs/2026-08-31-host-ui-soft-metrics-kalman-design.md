# Host UI soft metrics and display Kalman design

## Decision

Adopt the approved **B: soft tiles** visual direction for the attitude and
stream-health child metrics. In the same presentation pass, correct the top
row typography, remove the dark vibration-action background, replace the
orientation status strip with lightweight status pills, and add an optional
three-axis scalar Kalman display filter.

This is a host-only change. Firmware, SDF1 framing, device configuration, raw
recording and replay compatibility remain unchanged.

## Typography and alignment

- Use the UI sans-serif family for the application brand, `IIS3DWB`, sample
  rate and acquisition labels. Model identifiers remain semibold but no longer
  use font metrics that make them appear taller than adjacent text.
- Brand and sensor labels use 12 px text with explicit 32 px line boxes.
- Keep restrained letter spacing on the brand and model identifier only.
- Align every label and control in the application header and acquisition bar
  to the same vertical center. The visual baseline, rather than the text's
  native font ascent, determines row alignment.

## Vibration card actions

- The card action host is transparent and does not inherit the application
  background color.
- X, Y, Z, Auto Y and Kalman remain in the `3-Axis Vibration` card header.
- X, Y and Z keep compact soft chips. Auto Y and Kalman use the same 6 px
  rounded control shape.
- Kalman is off by default. Its checked state uses the existing cyan active
  treatment and the text `KALMAN`; no parameter controls are added in this
  iteration.

## Orientation status

- Remove the full-width dark `OPENGL 3D / LIVE` status strip.
- Show mode and freshness as two small translucent pills over the top-right of
  the orientation canvas. Mode text is `OPENGL 3D` or `2D FALLBACK`; freshness
  is `WAITING`, `LIVE` or `STALE`.
- The overlay must not resize the canvas, capture mouse interaction intended
  for the OpenGL view, or introduce an opaque rectangular background.
- A stacked overlay container is used so the same presentation works for the
  OpenGL and painter fallback canvases.

## Soft metric tiles

Attitude and Stream Health retain their outer cards. Their child fields use a
single softer surface rather than the current near-black blocks:

- background `#1C2D42`;
- no child border;
- 6 px corner radius;
- 8 px vertical and 9-10 px horizontal padding;
- muted labels and white semibold/monospace values;
- no shadows beyond a very subtle top highlight if Qt renders it cleanly.

Attitude keeps the current responsive grid: two columns normally and four
columns in the 1080 x 700 compact layout. Stream Health stays in one seven-cell
row at the supported minimum width.

Health coloring is semantic and limited to values:

- sample rate and uptime remain neutral;
- zero error/drop counters use the normal value color;
- nonzero CRC, sequence-gap and CDC error values use amber;
- nonzero source/transport drop values use red because they indicate lost
  samples or frames.

Large cumulative counters must not change tile size or cause clipping.

## IIS3DWB precision and display contract

The current firmware uses IIS3DWB at +/-2 g and transports the original signed
16-bit samples. The host conversion remains approximately
`raw * 0.000061 g`, or `0.061 mg/LSB`. The graph therefore preserves the
sensor's numeric quantization, although screen pixels and the 5,000-point
display budget cannot show every LSB or every 26.667 kHz sample simultaneously.

The existing raw-series envelope selection remains the default and continues
to retain strong peaks. Enabling Kalman explicitly switches to a smoothed
display series; the UI must not imply that this is the authoritative vibration
record.

## Kalman data flow

Each axis uses an independent scalar constant-state Kalman filter:

```text
prediction: x' = x
            P' = P + Q
update:     K  = P' / (P' + R)
            x  = x' + K * (z - x')
            P  = (1 - K) * P'
```

Initial parameters are fixed and documented in g units:

- `Q = 1e-6 g^2`;
- `R = 2.25e-4 g^2`;
- first estimate equals the first sample;
- initial covariance equals `R`.

`RealtimeSampleStore` maintains a filtered acceleration series alongside the
existing raw display retention. Filtering occurs as IIS batches are appended,
before display envelope selection, so the result is not an artefact of
filtering alternating peak-selected points. The additional 30-second,
three-axis float64 retention is bounded to roughly 19 MB.

The store always updates the filtered series so switching the view does not
start with an empty or partially warmed window. `snapshot()` receives a
`use_kalman` choice and performs the existing 5,000-point envelope selection on
the chosen series. The application controller owns this display preference;
the header button changes it through a Qt signal and the next UI snapshot
reflects the new mode.

Filter state resets when a host acquisition session starts, on non-monotonic
timestamps, or when the sample store is cleared. A filter failure falls back
to raw display data and reports an error without interrupting acquisition or
recording.

## Performance boundaries

Filtering is linear in newly appended samples, not in the full visible window
on every paint. At 26.667 kHz it adds three scalar updates per sample while
avoiding repeated filtering of as many as 800,000 retained samples for a
30-second window. UI snapshots remain capped at 5,000 points.

## Tests and visual review

- Pure tests cover the scalar update equation, first-sample initialization,
  three-axis independence, reset behavior and deterministic output.
- Sample-store tests prove raw snapshots remain unchanged, filtered snapshots
  are smoother, peak selection uses the chosen series, retention remains
  bounded and timestamps are preserved.
- Widget tests cover the transparent action host, Kalman default/off state and
  signal, font roles, status overlay roles, soft-tile roles and semantic health
  colors.
- The complete host/protocol suite must pass.
- Regenerate and inspect the 1920 x 1080 baseline and a 1080 x 700 preview for
  text clipping, action crowding, overlay opacity and large-counter overflow.
- Build the single-file EXE without skipping tests, run its smoke test, and run
  the firmware Stage 1 regression gate before requesting final merge approval.
