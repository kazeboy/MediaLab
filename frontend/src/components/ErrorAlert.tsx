import { PLATFORM_INFO } from "../lib/platform";
import type { ApiErrorBody, Platform } from "../lib/types";
import { Alert, Button, Disclosure, RetryIcon } from "./ui";

interface Props {
  title: string;
  error: ApiErrorBody;
  onRetry?: () => void;
  onSwitch?: (platform: Platform) => void;
}

/**
 * Structured error: what happened → what to do → the action. The machine-readable code and
 * details stay available under "Technical details" (useful for TROUBLESHOOTING.md / support).
 */
export function ErrorAlert({ title, error, onRetry, onSwitch }: Props) {
  const detected = error.details?.detected_platform as Platform | undefined;
  const canSwitch = error.code === "wrong_platform" && detected && onSwitch && PLATFORM_INFO[detected];
  const details = error.details ? Object.entries(error.details).filter(([k]) => k !== "url") : [];
  return (
    <Alert tone="error" title={title}>
      <p>{error.message}</p>
      {error.action && !canSwitch && <p className="mt-1 opacity-90">{error.action}</p>}
      {(canSwitch || (error.retryable && onRetry)) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {canSwitch && (
            <Button variant="primary" size="sm" onClick={() => onSwitch!(detected!)}>
              Switch to {PLATFORM_INFO[detected!].tab}
            </Button>
          )}
          {error.retryable && onRetry && (
            <Button variant="secondary" size="sm" icon={<RetryIcon className="h-4 w-4" />} onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      )}
      <Disclosure summary="Technical details" className="mt-3 [&_summary]:text-current [&_summary]:opacity-80">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono text-xs opacity-80">
          <dt>code</dt>
          <dd className="break-all">{error.code}</dd>
          <dt>retryable</dt>
          <dd>{String(error.retryable ?? false)}</dd>
          {details.map(([k, v]) => (
            <div key={k} className="contents">
              <dt>{k}</dt>
              <dd className="break-all">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      </Disclosure>
    </Alert>
  );
}
