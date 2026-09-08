# Remove Offline Wi-Fi Device Design

## Goal

Allow an operator to remove a disconnected Wi-Fi device from the left-hand
device list without stopping the Wi-Fi listener or disturbing other devices.

## Interaction

- Right-clicking an offline or reconnecting Wi-Fi row opens a context menu with
  `REMOVE DEVICE`.
- Online rows and non-Wi-Fi rows do not offer the removal action.
- Selecting the action removes only that stale inventory entry. It does not stop
  the listener, disconnect another device, delete recordings, or erase the
  UUID-based saved alias.

## Architecture and data flow

`NodeSidebar` determines whether a row is eligible from immutable
`NodeSummary` data stored on the list item. It emits the node identifier through
a dedicated `remove_requested` signal. `AppController.remove_offline_node`
performs the authoritative validation: the node must exist in the session index,
must be a Wi-Fi node in an offline/reconnecting state, and must not have an active
managed session. After removal it emits the refreshed node summaries.

This keeps presentation code from mutating controller state and protects against
a stale UI event racing with a reconnect.

## Error handling

Requests for unknown, active, non-Wi-Fi, or otherwise non-removable nodes leave
state unchanged and emit a descriptive controller error. Normal UI use does not
expose those paths because the action is only shown for eligible rows.

## Testing

- Widget tests verify that the context action is available only for disconnected
  Wi-Fi rows and emits the expected node identifier.
- Controller tests verify successful removal, preservation of the listener and
  other sessions, and rejection of active-node removal.
- Existing connection, sidebar selection, and complete repository tests remain
  green before packaging.

