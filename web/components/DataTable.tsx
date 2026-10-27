"use client";

/**
 * The one table in the app: a filter toolbar, sortable headers that stick while
 * the body scrolls, declared column widths, and pagination underneath.
 *
 * Columns declare a fixed `width` so headings never collide and a row's height
 * stays even; cells wrap instead of truncating unless a column opts into
 * `nowrap`. Leave exactly one column without a width and it absorbs the slack.
 *
 * Below the table's `minWidth` the wrapper scrolls sideways rather than letting
 * the columns crush each other — on a tablet that beats unreadable text.
 */
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState, Skeleton } from "@/components/States";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Sort key sent to the API; omit for a column the server cannot sort. */
  sortKey?: string;
  cell: (row: T) => ReactNode;
  /** A Tailwind width class, e.g. "w-[9rem]". Keeps columns stable. */
  width?: string;
  className?: string;
  align?: "left" | "right";
  /** Keep this column on one line (short codes, dates, numbers). */
  nowrap?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  loading,
  total,
  page,
  pageSize,
  sort,
  onSortChange,
  onPageChange,
  onRowClick,
  emptyTitle = "Nothing to show",
  emptyDescription,
  toolbar,
  caption,
  rowKey,
  minWidth = "min-w-[52rem]",
}: {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  sort?: string | null;
  onSortChange?: (sort: string) => void;
  onPageChange?: (page: number) => void;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyDescription?: string;
  toolbar?: ReactNode;
  caption?: ReactNode;
  rowKey?: (row: T, index: number) => string | number;
  /** Tailwind min-width for the table itself; below it the wrapper scrolls. */
  minWidth?: string;
}) {
  const totalPages = total && pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  const currentPage = page ?? 1;

  function toggleSort(column: Column<T>) {
    if (!column.sortKey || !onSortChange) return;
    const descending = sort === column.sortKey ? true : sort === `-${column.sortKey}` ? false : true;
    onSortChange(descending ? `-${column.sortKey}` : column.sortKey);
  }

  function sortIcon(column: Column<T>) {
    if (!column.sortKey) return null;
    if (sort === column.sortKey) return <ChevronUp className="h-3 w-3" />;
    if (sort === `-${column.sortKey}`) return <ChevronDown className="h-3 w-3" />;
    return <ChevronsUpDown className="h-3 w-3 opacity-40" />;
  }

  return (
    <div className="min-w-0 space-y-4">
      {toolbar && (
        <div className="rounded-lg border border-border bg-card p-3 shadow-card">{toolbar}</div>
      )}

      <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-card">
        {caption && (
          <p className="border-b border-border px-4 py-2.5 text-xs text-muted-foreground">{caption}</p>
        )}
        <p className="border-b border-border px-4 py-2 text-xs text-muted-foreground lg:hidden">
          Scroll sideways for the rest of the columns.
        </p>
        {/* A capped height is what makes the sticky header worth having. */}
        <div className="max-h-[70vh] min-w-0 overflow-auto">
          <table className={cn("w-full table-fixed text-sm", minWidth)}>
            <colgroup>
              {columns.map((column) => (
                <col key={column.key} className={column.width} />
              ))}
            </colgroup>
            <thead className="sticky top-0 z-10 bg-secondary/90 backdrop-blur">
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={cn(
                      "border-b border-border px-4 py-3 align-bottom text-[11px] font-semibold uppercase tracking-wider text-muted-foreground",
                      column.align === "right" ? "text-right" : "text-left",
                      column.sortKey && "cursor-pointer select-none hover:text-foreground",
                      column.className,
                    )}
                    onClick={() => toggleSort(column)}
                  >
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 leading-tight",
                        column.align === "right" && "justify-end",
                      )}
                    >
                      {column.header}
                      {sortIcon(column)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && (
                <tr>
                  <td colSpan={columns.length} className="p-4">
                    <Skeleton rows={6} />
                  </td>
                </tr>
              )}
              {!loading &&
                rows.map((row, index) => (
                  <tr
                    key={rowKey ? rowKey(row, index) : index}
                    className={cn(
                      "transition-colors",
                      onRowClick && "cursor-pointer hover:bg-secondary/60",
                    )}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "px-4 py-3 align-top",
                          column.align === "right" ? "text-right tabular-nums" : "text-left",
                          column.nowrap ? "whitespace-nowrap" : "break-words",
                        )}
                      >
                        {column.cell(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="p-0">
                    <EmptyState
                      title={emptyTitle}
                      description={emptyDescription}
                      className="rounded-none border-0"
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {onPageChange && total !== undefined && pageSize !== undefined && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} of{" "}
            {total.toLocaleString("en-IN")}
          </span>
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={currentPage <= 1}
              onClick={() => onPageChange(currentPage - 1)}
            >
              Previous
            </Button>
            <span className="tabular-nums">
              Page {currentPage} of {totalPages}
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={currentPage >= totalPages}
              onClick={() => onPageChange(currentPage + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The standard filter row inside a DataTable toolbar. */
export function TableFilters({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      {hint && <p className="w-full text-xs text-muted-foreground sm:ml-auto sm:w-auto">{hint}</p>}
    </div>
  );
}
