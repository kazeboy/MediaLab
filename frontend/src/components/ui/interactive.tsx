import { useEffect, useId, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { CloseIcon } from "./primitives";

/* ------------------------------------------------------------------- Tabs */
export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  /** Shorter label shown below the `sm` breakpoint (no wrapping on phones). */
  shortLabel?: ReactNode;
  badge?: ReactNode;
}

/**
 * WAI-ARIA tabs: one tab stop (roving tabIndex), Left/Right move and activate,
 * Home/End jump to the first/last tab. Panels use `tabPanelProps`.
 */
export function Tabs<T extends string>({ items, value, onChange, label, idPrefix, variant = "primary" }: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  idPrefix: string;
  variant?: "primary" | "segmented";
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = items.findIndex((t) => t.id === value);
    let next = -1;
    if (e.key === "ArrowRight") next = (i + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    if (next < 0) return;
    e.preventDefault();
    onChange(items[next].id);
    refs.current[next]?.focus();
  }
  const outer =
    variant === "primary"
      ? "grid gap-1 rounded-2xl border border-line bg-surface p-1 shadow-sm"
      : "inline-grid gap-1 rounded-xl bg-surface-muted p-1";
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className={outer}
      style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map((t, n) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[n] = el;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${t.id}`}
            aria-selected={active}
            aria-controls={`${idPrefix}-panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            // With a short label, the accessible name is always the full label (independent of CSS breakpoints).
            aria-label={t.shortLabel && typeof t.label === "string" ? t.label : undefined}
            onClick={() => onChange(t.id)}
            className={`flex min-h-10 items-center justify-center gap-1.5 truncate rounded-xl px-3 text-sm font-semibold whitespace-nowrap transition-colors ${
              active
                ? variant === "primary"
                  ? "bg-accent text-on-accent"
                  : "bg-surface text-fg shadow-sm ring-1 ring-accent-line"
                : "text-muted hover:bg-surface-muted hover:text-fg"
            }`}
          >
            {t.shortLabel ? (
              <>
                <span className="sm:hidden">{t.shortLabel}</span>
                <span className="hidden sm:inline">{t.label}</span>
              </>
            ) : (
              t.label
            )}
            {t.badge}
          </button>
        );
      })}
    </div>
  );
}

export function tabPanelProps(idPrefix: string, id: string, active: boolean) {
  return {
    role: "tabpanel" as const,
    id: `${idPrefix}-panel-${id}`,
    "aria-labelledby": `${idPrefix}-tab-${id}`,
    hidden: !active,
  };
}

/* ------------------------------------------------------- Focus management */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.closest("[hidden], [inert]"));
}

/** Keep Tab/Shift+Tab inside `root`, close on Escape, restore focus and page scroll on close. */
export function useModal(open: boolean, root: React.RefObject<HTMLElement | null>, onClose: () => void) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useLayoutEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const el = root.current;
    (el?.querySelector<HTMLElement>("[data-autofocus]") ?? el)?.focus();
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !root.current) return;
      const items = focusables(root.current);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === root.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open, root]);
}

/* ---------------------------------------------------------------- Dialogs */
/**
 * Modal dialog. `placement="center"` is a centred dialog that becomes a full-height sheet on
 * phones; `placement="right"` is a side drawer (full width on phones).
 */
export function Dialog({ open, onClose, title, description, children, placement = "center", footer, wide }: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  placement?: "center" | "right";
  footer?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useModal(open, ref, onClose);
  if (!open) return null;
  const panel =
    placement === "right"
      ? "fixed inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-line bg-surface shadow-xl"
      : `fixed inset-0 flex flex-col bg-surface sm:inset-auto sm:top-1/2 sm:left-1/2 sm:max-h-[85vh] sm:w-full ${wide ? "sm:max-w-2xl" : "sm:max-w-lg"} sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:border sm:border-line sm:shadow-xl`;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-scrim" onClick={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined} tabIndex={-1} className={`${panel} outline-none`}>
        <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-surface px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-lg font-bold">{title}</h2>
            {description && <p id={descId} className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="-m-1 rounded-lg p-2 text-muted hover:bg-surface-muted hover:text-fg">
            <CloseIcon />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="border-t border-line px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Popover */
/** Non-modal panel anchored to a trigger; closes on Escape or an outside click. */
export function Popover({ open, onClose, children, label, align = "right" }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  label: string;
  align?: "left" | "right";
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    ref.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest("[data-popover-trigger]")) onClose();
    }
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" aria-label={label}
      className={`absolute bottom-full z-30 mb-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-4 shadow-xl ${align === "right" ? "right-0" : "left-0"}`}>
      {children}
    </div>
  );
}
