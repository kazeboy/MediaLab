import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

/* ------------------------------------------------------------------ Button */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover", /* dark text on amber: ≥ 9.7:1 */
  secondary: "border border-line-strong bg-surface text-fg hover:bg-surface-muted",
  ghost: "text-muted hover:bg-surface-muted hover:text-fg",
  danger: "border border-red-300 bg-surface text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40",
  success: "bg-emerald-700 text-white shadow-sm hover:bg-emerald-800", /* 5.5:1 */
};
const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 gap-1.5 rounded-lg px-3 text-sm",
  md: "min-h-10 gap-2 rounded-xl px-4 text-sm",
  lg: "min-h-12 gap-2 rounded-xl px-6 text-base",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  busy?: boolean;
  icon?: ReactNode;
}

/** The only button style in the app: one primary action per area, secondary/ghost for the rest. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", busy, icon, className = "", children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex items-center justify-center font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    >
      {busy ? <Spinner /> : icon}
      {children}
    </button>
  );
});

/* ------------------------------------------------------------- Containers */
export function Card({ children, className = "", as: As = "section", ...rest }: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
} & Record<string, unknown>) {
  return (
    <As className={`rounded-2xl border border-line bg-surface p-5 shadow-sm sm:p-6 ${className}`} {...rest}>
      {children}
    </As>
  );
}

/* ----------------------------------------------------------------- Badges */
export type Tone = "neutral" | "accent" | "warn" | "success" | "danger";
const BADGE: Record<Tone, string> = {
  neutral: "bg-surface-muted text-muted",
  accent: "bg-accent-soft text-accent-fg",
  warn: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  danger: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
};

export function Badge({ children, tone = "neutral", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap ${BADGE[tone]} ${className}`}>
      {children}
    </span>
  );
}

/* ----------------------------------------------------------------- Alerts */
const ALERT: Record<"error" | "success" | "info" | "warn", string> = {
  error: "border-red-200 bg-red-50 text-red-900 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-100",
  success: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-100",
  info: "border-line bg-surface-muted text-fg",
  warn: "border-orange-200 bg-orange-50 text-orange-900 dark:border-orange-900/60 dark:bg-orange-950/40 dark:text-orange-100",
};

export function Alert({ tone, title, children, className = "" }: {
  tone: keyof typeof ALERT;
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm ${ALERT[tone]} ${className}`}>
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 break-words">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------- Disclosure */
export function Disclosure({ summary, children, className = "", defaultOpen = false }: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
  defaultOpen?: boolean;
}) {
  return (
    <details className={`group ${className}`} open={defaultOpen || undefined}>
      <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-1 rounded text-sm font-medium text-muted select-none hover:text-fg [&::-webkit-details-marker]:hidden">
        <ChevronIcon className="h-4 w-4 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

/* --------------------------------------------------------------- Progress */
export function ProgressBar({ value, label, size = "md" }: { value: number | null; label: string; size?: "sm" | "md" }) {
  const h = size === "sm" ? "h-1.5" : "h-2.5";
  return (
    <div
      className={`${h} w-full overflow-hidden rounded-full bg-surface-muted`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
    >
      {value != null ? (
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      ) : (
        <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-accent" />
      )}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function LoadingState({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted">
      <Spinner className="h-5 w-5" /> {children}
    </p>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      {icon && <div className="mb-3 text-subtle">{icon}</div>}
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-muted">{children}</div>}
    </div>
  );
}

/* ----------------------------------------------------------------- Fields */
export function Checkbox({ label, description, className = "", ...rest }: {
  label: ReactNode;
  description?: ReactNode;
  className?: string;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  return (
    <label className={`flex cursor-pointer items-start gap-2.5 text-sm ${rest.disabled ? "cursor-not-allowed opacity-60" : ""} ${className}`}>
      <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" {...rest} />
      <span>
        <span className="text-fg">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-muted">{description}</span>}
      </span>
    </label>
  );
}

export function SelectField({ label, children, className = "", ...rest }: {
  label: string;
  children: ReactNode;
  className?: string;
} & React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label className={`flex flex-col gap-1 text-sm ${className}`}>
      <span className="font-medium text-muted">{label}</span>
      <select className="min-h-10 rounded-lg border border-line-strong bg-surface px-3 text-fg" {...rest}>
        {children}
      </select>
    </label>
  );
}

/* ------------------------------------------------------------------ Icons */
type IconProps = { className?: string };
const icon = (path: ReactNode) =>
  function Icon({ className = "h-5 w-5" }: IconProps) {
    return (
      <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {path}
      </svg>
    );
  };

export const DownloadIcon = icon(<><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 19h14" /></>);
export const CloseIcon = icon(<><path d="M6 6l12 12" /><path d="M18 6 6 18" /></>);
export const ChevronIcon = icon(<path d="m9 6 6 6-6 6" />);
export const RetryIcon = icon(<><path d="M20 11a8 8 0 1 0-2.3 5.6" /><path d="M20 5v6h-6" /></>);
export const FolderIcon = icon(<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />);
export const SlidersIcon = icon(<><path d="M4 7h10" /><path d="M18 7h2" /><circle cx="16" cy="7" r="2" /><path d="M4 17h4" /><path d="M12 17h8" /><circle cx="10" cy="17" r="2" /></>);
export const FilmIcon = icon(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" /></>);
export const InboxIcon = icon(<><path d="M4 13h4l2 3h4l2-3h4" /><path d="M5 5h14l1 8v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5Z" /></>);
export const SunIcon = icon(
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
  </>,
);
export const PlusIcon = icon(<><path d="M12 5v14" /><path d="M5 12h14" /></>);
export const LinksIcon = icon(<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>);
export const MoonIcon = icon(<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />);
export const GearIcon = icon(
  <>
    <path d="M10.3 4.3c.4-1.7 3-1.7 3.4 0a1.7 1.7 0 0 0 2.6 1.1c1.5-.9 3.3.8 2.4 2.4a1.7 1.7 0 0 0 1 2.5c1.8.5 1.8 3 0 3.5a1.7 1.7 0 0 0-1 2.5c.9 1.6-.9 3.3-2.4 2.4a1.7 1.7 0 0 0-2.6 1.1c-.4 1.7-3 1.7-3.4 0a1.7 1.7 0 0 0-2.6-1.1c-1.5.9-3.3-.8-2.4-2.4a1.7 1.7 0 0 0-1-2.5c-1.8-.5-1.8-3 0-3.5a1.7 1.7 0 0 0 1-2.5c-.9-1.6.9-3.3 2.4-2.4a1.7 1.7 0 0 0 2.6-1.1Z" />
    <circle cx="12" cy="12" r="3" />
  </>,
);
