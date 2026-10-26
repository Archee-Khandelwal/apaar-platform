"use client";

/** A table with sorting, a filter slot and pagination, over server-paginated data. */
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState, LoadingSkeleton } from "@/components/States";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Sort key sent to the API; omit for a column the server cannot sort. */
  sortKey?: string;
  cell: (row: T) => ReactNode;
  className?: string;
  align?: "left" | "right";
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
    <div className="space-y-3">
      {toolbar}
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            {caption && <caption className="px-4 py-2 text-left text-xs text-muted-foreground">{caption}</caption>}
            <thead className="bg-muted/60">
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={cn(
                      "whitespace-nowrap px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                      column.align === "right" ? "text-right" : "text-left",
                      column.sortKey && "cursor-pointer select-none hover:text-foreground",
                      column.className,
                    )}
                    onClick={() => toggleSort(column)}
                  >
                    <span className="inline-flex items-center gap-1">
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
                    <LoadingSkeleton rows={5} />
                  </td>
                </tr>
              )}
              {!loading &&
                rows.map((row, index) => (
                  <tr
                    key={index}
                    className={cn(
                      "transition-colors",
                      onRowClick && "cursor-pointer hover:bg-muted/50",
                    )}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={cn(
                          "px-4 py-2.5 align-middle",
                          column.align === "right" ? "text-right tabular-nums" : "text-left",
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
                      className="rounded-none border-0 border-dashed"
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {onPageChange && total !== undefined && pageSize !== undefined && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            Showing {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} of{" "}
            {total.toLocaleString("en-IN")}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={currentPage <= 1}
              onClick={() => onPageChange(currentPage - 1)}
            >
              Previous
            </Button>
            <span>
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
