# SAP WebGUI + Playwright Recorder Notes

## What Worked

- Launching SAP WebGUI with Python Playwright and enabling the recorder from a separate Node helper over CDP is stable.
- `start_recording` and `stop_recording` work when the Node helper stays alive and `stop_recording` asks that helper to disable the recorder before the browser/context is closed.
- The recorder can capture actions performed by automation while it is active. In the `YJRS_TEST_03` attempt it produced a Playwright script with the WebGUI clicks/fills.
- Direct transaction navigation works and is more reliable than depending on the OK-code field:

```text
https://host:port/sap/bc/gui/sap/its/webgui?sap-client=001&sap-language=EN&~transaction=SE11
```

This is useful because the OK-code field may be hidden and the settings dialog is not always reliable under the recorder overlay.

## Recorder Architecture

- Prefer this shape:
  - Python opens Chromium with `--remote-debugging-port`.
  - Python logs into SAP WebGUI.
  - Node connects with `chromium.connectOverCDP(...)`.
  - Node calls Playwright's internal `_enableRecorder(...)`.
  - `stop_recording` writes `stop` to the Node helper, the helper calls `_disableRecorder()`, then exits.
- Avoid enabling the recorder directly from the same long-lived Python MCP client. That was the path that froze or stopped publishing actions.
- If the browser/driver is killed externally, the MCP process may keep a stale `_browser`. `_get_or_start_browser()` should check `is_connected()` and recreate Playwright/browser when needed.
- Do not allow opening another SAP WebGUI session while a recording is active. A recorder can observe other pages/contexts created in the same Chromium instance and may capture their login sequence. The tool now rejects `session_open` with `409 Conflict` while any recording is active.
- `recording_stop` must sanitize configured SAP passwords before returning or rewriting the generated script.

## Login And Navigation

- The current MCP `session_open` check is too strict if it only waits for `User Menu`. A page can be usable even when that exact button is not found.
- Better post-login checks:
  - title contains `SAP Easy Access`, or
  - any top menu such as `Menu`, `System`, `Help` is visible, or
  - the URL remains under `/sap/bc/gui/sap/its/webgui` and the login form disappeared.
- For transactions, prefer `~transaction=SE11` URL navigation over opening the OK-code field.

## Useful Locators Observed

- Main menu button:

```ts
page.getByRole('button', { name: 'Menu', exact: true })
```

- SE11 table field:

```ts
page.getByRole('textbox', { name: 'Table name, 16 characters' })
```

- Create button:

```ts
page.getByRole('button', { name: 'Create' })
```

- Short description:

```ts
page.getByRole('textbox', { name: 'Short Description Required' })
```

- Delivery class:

```ts
page.getByRole('textbox', { name: 'Delivery Class Required' })
```

- Fields tab:

```ts
page.getByRole('tab', { name: 'Fields', exact: true })
```

## SE11 Table-Control Problems

- The fields grid is the hardest part. It is not a normal HTML table with stable editable inputs.
- Material from a Claude discussion matches what I observed, but should be treated as operational guidance rather than SAP documentation:
  - the visual grid and DOM do not always line up,
  - empty cells may not have the same interactable element as filled cells,
  - `_c` IDs are visual cell containers and may not be the actual editable control,
  - SAP roundtrips can discard frontend text that was not committed with the expected keyboard flow,
  - `Ctrl+A` inside a grid may act on the grid/rows instead of selecting the cell text,
  - slow typing appends unless the tool explicitly clears/fills the field.
- Visible cells may expose locators like:

```ts
page.locator('[id="M0:46:1:2B266:3[3,9]_c"]')
```

- These IDs are useful when recorded, but they are fragile:
  - the prefix can change between sessions,
  - row/column indexes depend on scroll position,
  - clicking a cell does not always focus the input that Playwright expects,
  - keyboard typing may remain focused in the previous field.
- Coordinate clicks are also fragile. They can be shifted by:
  - the recorder toolbar,
  - horizontal scroll in the SAP grid,
  - visible/hidden columns,
  - validation messages.

## YJRS_TEST_03 Attempt

- I reached SE11 and opened `YJRS_TEST_03` in create/change mode.
- I filled description and delivery class correctly once I switched from coordinates to accessible locators.
- I reached the `Fields` tab.
- I did not successfully fill the SE11 field grid. The final check still reported:

```text
YJRS_TEST_03 does not exist; check the name
```

- The table was not saved or activated.
- The generated recording is at:

```text
tmp/webgui_yjrs_test_03/recording.ts
```

- Screenshots for the attempts are at:

```text
tmp/webgui_yjrs_test_03/
```

## YJRS_TEST_04 Attempt

- The MCP WebGUI tools successfully opened the session, started the recorder, navigated to SE11, and stopped/closed cleanly afterwards.
- The recording was saved at:

```text
tmp/yjrs_test_04_recording.ts
```

- The normal SE11 fields were reliable with accessible locators:
  - table name: `input[title="Table name, 16 characters"]`
  - short description: `input[title="Short Description of Repository Objects"]`
  - delivery class: `input[title="Delivery class"]`
  - fields tab: `#M0\:46\:1\:\:0\:2-title` in this run
  - built-in type button: `#M0\:46\:1\:2B266\:\:0\:56` in this run
- After pressing `Built-In Type`, the grid exposed the technical columns as textbox-like controls:
  - field name: `[row,1]_c`
  - key checkbox: `[row,2]_c`
  - data element: `[row,4]_c`
  - data type: `[row,5]_c`
  - length: `[row,6]_c`
  - short description: `[row,9]_c`
- Empty grid cells initially render as `span role="textbox"` with the `_c` suffix. A single click plus typing did not work. A double click can turn the same id into a real `input`, and then `fill()` can write to it.
- Only the first field name (`MANDT`) persisted reliably. Jumping directly between cells with double-click/fill caused SAP to open a modal `Maintain Field YJRS_TEST_04-MANDT` / `Data Element Attributes` screen and subsequent writes landed in the wrong modal fields.
- In this run `_c` was not merely a visual suffix. For editable cells it was the focusable textbox/span/input; the non-`_c` id was the gridcell container.
- The generated recording confirms that once the modal opens, locator quality deteriorates quickly: many actions become generic `getByRole('textbox', { name: 'Data Element' })`, `nth(...)`, or volatile ids such as `#u6245`.
- The table was not saved or activated. The attempt was stopped because the modal could not be dismissed cleanly through automation without risking more accidental changes.

### Table-Control Lessons

- Direct cell addressing is useful for discovery but not sufficient for robust editing. SAP may accept one cell, then route the next action into a modal detail screen.
- For built-in table fields, the safer approach is likely a dedicated state machine:
  1. enter a field name,
  2. explicitly detect whether SAP opened a detail/modal screen,
  3. fill that detail screen using stable labels if fields are editable,
  4. continue back to the grid,
  5. verify the row values before moving to the next row.
- Do not assume `fill()` is safe just because Playwright resolves a textbox. Some WebGUI inputs are readonly even though they expose `role="textbox"`.
- If SAP opens a modal detail screen, stop and inspect before sending toolbar actions. Toolbar ids change from `M0:*` to `M2:*`, and clicks on the main toolbar are intercepted by the modal block layer.
- The recorder remains stable and captures the automation, but the captured script is diagnostic rather than replay-ready when table-control focus has gone wrong.

## YJRS_TEST_04 Successful Attempt

- A second run successfully created and activated `YJRS_TEST_04`.
- ADT metadata confirmed the resulting fields:

```text
MANDT CLNT length 3
ID    CHAR length 10
NAME  CHAR length 40
```

- The recording was saved at:

```text
tmp/yjrs_test_04_table_control_probe.ts
```

- Important table-control behavior:
  - The first empty cell can be opened with double click, which turns the visible `span` into an `input` with the same id.
  - After filling a row, do not click another row directly. SAP often reopens the current row's `Table Field Attributes` popup and leaves the intended row untouched.
  - To move to the next row, keep tabbing through the row's native focus order until the next row's field cell becomes active. In this run, row 2 field became `M0:46:1:2B266:3[2,1]_c` as a real `input`.
  - From a row's field cell, the working focus order was:

```text
Field -> Key -> Initial Values -> Data element -> Data Type -> Length -> Decimal Places -> Coordinate -> Short Description -> Group -> next row
```

  - Checkboxes should be toggled with `Space` while focused, not by direct mouse click after jumping rows.
  - Leave the completed final row with `Tab` before pressing toolbar actions; this causes SAP to render the row values as committed spans instead of active inputs.
  - Multiline clipboard paste into the table-control did not work in this WebGUI session. It cleared the active field but did not distribute tabular data to the grid.
- After the fields were committed, `Check` asked to save the object. Choosing `Yes` then `Local Object` saved it under `$TMP`.
- `Activate` sent WebGUI to the technical settings screen (`SE13`). Required values used:

```text
Data Class: APPL0
Size Category: 0
Buffering: Buffering Not Allowed
```

- On the technical settings screen, the visible `Activate` button was disabled until the settings were saved with `Ctrl+S`.
- Returning with `F3` opened the inactive objects popup. Pressing `Continue` there activated the table and returned to SE11 with status `Active` and message `Object(s) activated`.

## Practical Guidance For Future Recordings

- Start recording only after login unless the login itself is the subject of the test.
- Never open a new SAP WebGUI session while a recorder is active.
- Navigate to transactions with `~transaction=<TCODE>` whenever possible.
- Take screenshots after every major SAP screen transition.
- Prefer ARIA locators for normal fields and buttons.
- For SAP table-controls, first do one manual/codegen pass to capture the exact cell locators, then generalize carefully.
- For SAP table-controls, try keyboard navigation from a reliably focusable first cell before relying on direct cell IDs. A promising pattern is: click the first real `Field` cell, type/commit, then use `Tab` to move through SAP's native focus order.
- Avoid `Ctrl+A -> type` in SAP grids until verified on that exact cell; it may select rows or act on the wrong focused control.
- Avoid `slowly=True` for replacement text. In these tools, slow typing uses sequential key presses and appends to current content. Use normal fill when you want replacement semantics.
- Do not trust a successful Playwright click as proof that SAP accepted the value. Always check the SAP status bar and a screenshot.
- After `stop_recording`, confirm the helper emitted `STOPPED` and no Node/Chromium processes remain.

## Validated Tool Behavior

- Validated through MCP tools after restarting the MCP server:
  - `sap_webgui_session_open` opens a logged-in SAP WebGUI session.
  - `sap_webgui_recording_start` starts the Node/CDP recorder and reports `READY`.
  - `sap_webgui_navigate` during recording is captured in the generated Playwright script.
  - `sap_webgui_recording_stop` reports `STOPPED` and returns the generated script.
  - `sap_webgui_session_open` returns `409 Conflict` while another WebGUI recording is active, preventing credential capture from parallel logins.
