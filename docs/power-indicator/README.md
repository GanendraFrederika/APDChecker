# Power Indicator Supply - dimensioned placement concept

Status: DRAFT / NOT FOR FABRICATION OR ASSEMBLY.

This is a component-placement preview, NOT a routed PCB, verified schematic,
Gerber package, or electrically validated design. Existing circuit_image.svg
and the Cirkit Designer project have not been modified.

Preview: placement-preview.png (regenerate with make_preview.py / Pillow).
No copper routing, certified current capacity, confirmed drill sizes, or real
component footprints are supplied at this stage.

## User-requested mechanical update

Board outline: **50 x 60 mm (5 x 6 cm)**.
Preview orientation: horizontal = 50 mm, vertical = 60 mm.
The board outline uses a uniform 10 preview pixels per mm in both directions;
it is dimensionally proportional, but the on-screen image is NOT a 1:1 print.

Output and switch connection areas have exchanged locations:
- J1: DC input, left upper area.
- J3: external panel switch, left lower area, adjacent to J1 on the same edge.
- J2: DC load output, right upper area.

Illustrative center coordinates, measured from the top-left board corner:

| Part | X (mm) | Y (mm) |
| --- | ---: | ---: |
| J1 input | 6.5 | 17.5 |
| J3 switch terminal | 6.5 | 43.5 |
| J2 output | 43 | 17.5 |
| LED1 | 19 | 17.5 |
| R1 | 30 | 17.5 |
| C1 unmeasured placeholder | 31 | 43.5 |

These are concept placement coordinates, not verified footprint positions.
Mounting holes are omitted until their diameters and positions are confirmed.
J3 is only a proposed terminal for an external switch, not a switch footprint.

## Exact capacitor size: pending measurement

Known: C1 capacitance is 4700 uF.
Unknown: manufacturer/series, voltage rating, body diameter, body height,
lead center-to-center spacing, lead diameter and required mechanical clearance.
4700 uF alone cannot identify those mechanical dimensions.

Do not treat the drawn capacitor circle as a selected or measured diameter.
The generator stores its actual body diameter, height and lead pitch as None.
Obtain the real capacitor's markings and measurements (or exact model datasheet)
before drawing its final footprint and checking the board/case fit.

## User-specified components

- One LED
- Resistor: 2.2 kOhm
- Polarized electrolytic capacitor: 4700 uF
- Switch
- Low-voltage DC power supply context; NOT mains AC wiring

## Required before schematic / copper routing / fabrication files

1. Verified electrical netlist: switch purpose; LED indicates raw input present
   or switched output enabled; capacitor before or after switch; load output.
2. Photo/model of each physical component, capacitor voltage marking,
   body diameter/height and lead pitch; switch terminals and DC ratings;
   preferred input/output connectors.
3. DC input voltage range, adapter current rating, actual continuous and peak
   output current, board/case clearance, upstream protection and inrush budget.

Any capacitor must be connected with correct polarity and remain below its rated
voltage. Large capacitance is not voltage regulation or a UPS. Do not connect
this board directly to PLN/mains AC.
