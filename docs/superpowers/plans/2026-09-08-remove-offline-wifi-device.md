# Remove Offline Wi-Fi Device Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe right-click action that removes one disconnected Wi-Fi device while leaving the listener and other devices untouched.

**Architecture:** `NodeSidebar` exposes a removal request but never mutates application state. `AppController` validates the current authoritative session/inventory state, removes only eligible stale Wi-Fi nodes, and republishes summaries.

**Tech Stack:** Python 3.12, PyQt6 widgets/signals, pytest, pytest-qt, PyInstaller

---

### Task 1: Sidebar context action

**Files:**
- Modify: `tests/test_connection_widgets.py`
- Modify: `src/sensor_host/presentation/connection_view.py`

- [ ] **Step 1: Write failing widget tests**

Add tests that construct offline Wi-Fi, online Wi-Fi, and offline CDC summaries.
Call a small context-menu factory for each row, assert only the offline Wi-Fi row
returns a menu containing `REMOVE DEVICE`, trigger it, and assert
`remove_requested` emits that row's node ID.

- [ ] **Step 2: Verify the tests fail for the missing signal/menu behavior**

Run:

```powershell
python -m pytest tests/test_connection_widgets.py -k "remove" -q
```

Expected: failure because `NodeSidebar.remove_requested` and the menu factory do
not exist.

- [ ] **Step 3: Implement the minimal sidebar behavior**

Store each row's `TransportKind`, configure the list for a custom context menu,
and add a factory equivalent to:

```python
def _context_menu_for_item(self, item: QListWidgetItem | None) -> QMenu | None:
    if item is None or item.data(_CONNECTED_ROLE):
        return None
    if item.data(_TRANSPORT_ROLE) != TransportKind.WIFI.value:
        return None
    menu = QMenu(self.node_list)
    action = menu.addAction("REMOVE DEVICE")
    action.triggered.connect(
        lambda: self.remove_requested.emit(str(item.data(_NODE_ID_ROLE)))
    )
    return menu
```

The custom-context-menu slot pops up this menu at the requested global position.

- [ ] **Step 4: Run the widget tests**

Run:

```powershell
python -m pytest tests/test_connection_widgets.py -q
```

Expected: all widget tests pass.

### Task 2: Authoritative controller removal

**Files:**
- Modify: `tests/test_app_smoke.py`
- Modify: `src/sensor_host/presentation/app_controller.py`
- Modify: `src/sensor_host/app.py`

- [ ] **Step 1: Write failing controller tests**

Create one failed Wi-Fi transport and one live Wi-Fi transport, wait for the
failed node to become `RECONNECTING`, call `remove_offline_node`, and assert the
stale node disappears while the live session and listener state remain. Add a
separate test asserting an active node is retained and produces an error.

- [ ] **Step 2: Verify the tests fail for the missing controller method**

Run:

```powershell
python -m pytest tests/test_app_smoke.py -k "remove_offline" -q
```

Expected: failure because `AppController.remove_offline_node` does not exist.

- [ ] **Step 3: Implement and wire the controller boundary**

Add `remove_offline_node(node_id: str)` that rejects IDs present in
`_sessions`, loads the summary from `_session_index`, accepts only Wi-Fi
`OFFLINE`/`RECONNECTING` summaries, removes it, and calls `_emit_nodes()`.
Connect `window.node_sidebar.remove_requested` to the method in `_run_interactive`.

- [ ] **Step 4: Run focused integration tests**

Run:

```powershell
python -m pytest tests/test_app_smoke.py -k "remove_offline or offline_node" -q
```

Expected: all selected tests pass.

### Task 3: Documentation, regression, merge, and package

**Files:**
- Modify: `docs/USER_MANUAL_zh-CN.md`

- [ ] **Step 1: Document the operator action**

State that an offline Wi-Fi row can be removed through `REMOVE DEVICE`, and that
this does not stop the listener or erase recordings and aliases.

- [ ] **Step 2: Run the complete source verification**

Run:

```powershell
python -m pytest tests -q
```

Expected: zero failures.

- [ ] **Step 3: Commit and merge locally**

Commit the focused implementation on `codex/remove-offline-wifi-device`, switch
to `master`, merge the feature branch, and rerun the complete tests on the merged
result.

- [ ] **Step 4: Reuse the existing build environment and package**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

Expected: source tests pass, PyInstaller succeeds, packaged smoke test exits 0,
and a versioned executable plus SHA-256 manifest is written under `dist/host/`.

