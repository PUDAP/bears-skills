# bears-skills

Cursor/agent skill references for PUDA work at bears.

This repository contains local skill documentation for selecting machines, choosing experiment workflows, and loading the right reference material before generating commands or protocols.

## Skill Folders

### [`bears-machines`](bears-machines/SKILL.md)

Use this skill to choose the correct PUDA-connected machine and load its command reference before generating machine commands.

Covered machines include:
- `first` for liquid handling and deck operations
- `biologic` for electrochemical measurements such as OCV, CA, EIS, CV, and MPP
- `balance` for Arduino-based gravimetric mass measurement
- `opentrons` for OT-2 liquid handling, protocol generation, labware setup, and camera capture

### [`bears-workflows`](bears-workflows/README.md)

Use this skill to choose and run PUDA experiment workflows at bears.

Covered workflows include:
- `colour-mixing-opt` for RGB dye mixing optimization using OT-2 dispensing, camera feedback, image processing, RMSE scoring, and BO or LLM suggestions
- `viscosity-optimization` for tuning OT-2 liquid handling parameters with gravimetric balance feedback and BO or LLM suggestions

## How To Use

1. Identify whether the user needs machine-level command guidance or an experiment workflow.
2. Load the matching skill folder.
3. Read the linked reference file before generating commands, protocols, or reports.
4. Ask for required user inputs before execution.
5. Ask for clarification whenever the machine, workflow, hardware setup, deck slots, or optimization approach is unclear.

## Core Rule
**Do not assume**. If a decision affects machine choice, workflow selection, protocol execution, credentials, hardware setup, or experimental parameters, ask the user first.
