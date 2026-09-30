# Linux display and Hermes wrapper troubleshooting

## Diagnose before changing anything

1. Run `hermes computer-use doctor`. If tool captures consistently fail, ask the desktop user to run it too and share the output; a terminal and the running gateway can have different environments.
2. Inspect the active desktop with `loginctl list-sessions` and process discovery. Verify the App is running; do not restart it simply because `list_apps` is empty.
3. Read only these desktop variables from a confirmed GUI process environment: `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and `XDG_SESSION_TYPE`. Do not dump the full environment, which may contain secrets.
4. Test doctor with those discovered values in a command/session-local environment. Do not guess a display, hardcode an expiring Xauthority filename, grant broad X access, or change another user's desktop.

Completion: doctor can reach the actual user's accessibility bus and display. On Wayland, a green portal reachability check does not prove successful screenshot/input consent; the user must handle permission dialogs.

## Separate-process Hermes fallback

An environment export in a terminal does **not** repair the already-running conversation's `computer_use` process. In the verified session, terminal-local desktop settings allowed the installed Hermes handler to work without restarting the gateway.

For a read-only capture, after discovering the current Hermes checkout/runtime and setting the verified desktop variables:

```python
from tools.computer_use.tool import handle_computer_use

result = handle_computer_use({
    "action": "capture",
    "app": "Opentrons OT-2",
    "mode": "ax",
    "max_elements": 200,
})
print(result)
```

Run with the installed Hermes Python and the Hermes checkout on `PYTHONPATH`. On the tested machine those were `/home/opentron/.hermes/hermes-agent/venv/bin/python` and `/home/opentron/.hermes/hermes-agent`. Discover them again elsewhere. This is an internal API fallback, not a promised stable CLI.

For an authorized navigation click, perform **fresh capture → select reviewed role/label/region → handler click → separate capture** within one process. Do not carry element indices between independent Python invocations. Inspect the installed handler's approval behavior before programmatic dispatch; this entry point may lack the gateway's outer approval layer. Limit fallback dispatch to the user's already-authorized navigation scope, never use it to bypass a denied action, and preserve all safety/foreground/permission gates.

In this exploration, command-local `CUA_DRIVER_RS_ENABLE_WAYLAND=1` was also tested. It did not fix wrong App selectors; the exact `Opentrons OT-2` name did. Do not generalize that flag into a required global setting. Current documentation and installed-version support take precedence.

## Inspect capture payloads correctly

AX mode returned JSON with `elements`, roles, labels, bounds, and summary. SOM mode returned a multimodal object with `content`, `text_summary`, and `meta`. Do not dump base64 image data into chat. Inspect image bytes with the vision tool before trusting screenshot-based targeting or sharing them.

The tested background screenshot included overlapping windows. Semantic navigation remained successful, but screenshot-only or pixel-targeted work was not validated. Do not silently raise/close windows to improve the image. Ask for foreground consent if needed; use only escalation options exposed by the current tool schema. Never copy raw cua-driver parameters into Hermes calls without checking support.

## Sources

- [Hermes Computer Use documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use)
- Installed Hermes `tools/computer_use_tool.py` registration and `tools/computer_use/tool.py` handler.
- [Session exploration and verified limits](verified-exploration.md).
