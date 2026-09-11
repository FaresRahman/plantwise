import React from "react";

/** Consistent Edit/Delete icon buttons for every config table in the app
 * (asset registry, lines, items, characteristics, users) — one component so
 * they never drift apart in styling. Click events stop propagation so
 * clicking an action inside a clickable row doesn't also open its drill-down.
 */
export function RowActions({
  onEdit,
  onDelete,
  editLabel = "Edit",
  deleteLabel = "Delete",
}: {
  onEdit?: () => void;
  onDelete?: () => void;
  editLabel?: string;
  deleteLabel?: string;
}) {
  return (
    <span className="row-actions" onClick={(e) => e.stopPropagation()}>
      {onEdit && (
        <button type="button" className="btn-icon btn-icon--edit" onClick={onEdit} title={editLabel} aria-label={editLabel}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
        </button>
      )}
      {onDelete && (
        <button type="button" className="btn-icon btn-icon--delete" onClick={onDelete} title={deleteLabel} aria-label={deleteLabel}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 6h18" />
            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
          </svg>
        </button>
      )}
    </span>
  );
}
