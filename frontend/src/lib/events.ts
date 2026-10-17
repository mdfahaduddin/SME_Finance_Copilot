/** Fired whenever an approval request is created or decided, so counters can refresh immediately. */
export const APPROVALS_CHANGED = "approvals:changed";

export function notifyApprovalsChanged() {
  window.dispatchEvent(new Event(APPROVALS_CHANGED));
}
