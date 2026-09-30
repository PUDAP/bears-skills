# Verified exploration — 2026-09-30

## Method and environment

Exploration used Hermes' installed `tools.computer_use.tool.handle_computer_use`, the same implementation registered by the `computer_use` tool, with cua-driver 0.23.2. The main conversation tool initially had no display connection. A terminal subprocess with the actual desktop session environment successfully invoked the Hermes implementation; no alternative GUI automation runtime, CDP, or robot API was used.

The running AppImage path identified Opentrons OT-2 v26.6.0. This version was obtained from process discovery, not an About dialog. Host diagnostics reported Ubuntu 24.04.4 LTS and GNOME Wayland. The successful App selector was `Opentrons OT-2`; process-name and numeric-PID-string selectors returned no matched window.

## Exercised transitions

Every listed click returned `ok: true` and was followed by an independent AX capture showing changed page content.

| Transition | Verified destination |
|---|---|
| Initial protocol detail → sidebar Devices | Devices heading, Available/Not Available groups, robot card and Instruments |
| Devices → sidebar Labware | Labware heading, Import, Category, Sort by, library definition cards with API names |
| Labware → sidebar Protocols | Protocols heading, Import, sorting and an existing protocol card |
| Existing protocol-title paragraph → detail | Protocol breadcrumb, metadata, Hardware/Labware/Parameters/Liquids buttons |
| Detail → Labware button | Labware name/Quantity table and a 1000 µL OT-2 tip rack requirement |
| Labware tab → Hardware button | Robot and left/right mount requirement fields; restored starting tab |

The inspected protocol declared P1000 Single-Channel GEN2 on the left and an empty right mount. Devices listed P1000 and P300 instruments on the available robot. These represent protocol requirements versus device inventory, not contradictory measurements.

## Observed failure modes

- Initial built-in `list_apps`: empty list. Initial `capture`: 0×0, no elements.
- Initial doctor: X11 unreachable and missing desktop environment.
- Doctor with discovered desktop variables: overall OK; portal reachability did not establish input consent.
- Correct App selector: nonempty 936×680 AX capture and working semantic navigation.
- Sidebar labels occurred as both links and headings; protocol tabs reused labels.
- AX included closed drawers beyond the content viewport's right edge and library entries far below the viewport. These were not clicked.
- SOM screenshot pixels contained covering Files and software-update windows, although the accompanying AX tree was Opentrons. This is not evidence of an unobstructed App screenshot. The image was not added to the repository to avoid unrelated desktop content.

## Deliberately untested

Import/upload, Parameters/Liquids tab contents, Visualize, device details/settings, overflow actions, Go to Run, light toggles, protocol setup/send/run controls, calibration, homing, firmware changes, networking changes, and all physical robot motion.

No App/gateway restart, foreground raise, permission approval, or persistent desktop configuration change was performed. Navigation ended on the initial protocol's Hardware tab. This record documents one tested version; always rediscover live controls.
