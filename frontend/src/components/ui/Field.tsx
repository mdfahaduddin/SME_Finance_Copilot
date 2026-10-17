import { Eye, EyeOff, type LucideIcon } from "lucide-react";
import { forwardRef, useId, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

export const inputClass =
  "block w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted " +
  "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none disabled:opacity-60";

interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  /** Leading icon inside the input (used on the sign-in pages). */
  icon?: LucideIcon;
}

function LeadingIcon({ icon: Icon }: { icon?: LucideIcon }) {
  return Icon ? <Icon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" aria-hidden /> : null;
}

/** Taller, rounder inputs with room for the leading icon. */
const withIcon = "h-11 rounded-xl! pl-10";

export const TextField = forwardRef<HTMLInputElement, FieldProps & InputHTMLAttributes<HTMLInputElement>>(
  function TextField({ label, hint, error, className, icon, ...props }, ref) {
    return (
      <label className={cn("block text-sm font-medium text-ink", className)}>
        {label}
        <span className="relative mt-1.5 block">
          <LeadingIcon icon={icon} />
          <input ref={ref} className={cn(inputClass, icon && withIcon, error && "border-danger")} aria-invalid={!!error} {...props} />
        </span>
        {error ? <span className="mt-1 block text-xs text-danger">{error}</span>
          : hint ? <span className="mt-1 block text-xs font-normal text-muted">{hint}</span> : null}
      </label>
    );
  },
);

/** Password input with a show/hide toggle. */
export function PasswordField({ label, hint, error, className, icon, labelAction, ...props }:
  FieldProps & { labelAction?: ReactNode } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  const autoId = useId();
  const id = props.id ?? autoId;
  return (
    <div className={cn("text-sm font-medium text-ink", className)}>
      {/* labelAction: e.g. a "Forgot password?" link on the right of the label row. */}
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id}>{label}</label>
        {labelAction}
      </div>
      <div className="relative mt-1.5">
        <LeadingIcon icon={icon} />
        <input id={id} type={visible ? "text" : "password"}
          className={cn(inputClass, "pr-10", icon && withIcon, error && "border-danger")} aria-invalid={!!error} {...props} />
        <button type="button" onClick={() => setVisible((v) => !v)} aria-label={visible ? "Hide password" : "Show password"}
          className="absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-lg text-muted hover:text-ink">
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      {error ? <span className="mt-1 block text-xs text-danger">{error}</span>
        : hint ? <span className="mt-1 block text-xs font-normal text-muted">{hint}</span> : null}
    </div>
  );
}

export function SelectField({ label, hint, className, icon, children, ...props }: FieldProps & SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <label className={cn("block text-sm font-medium text-ink", className)}>
      {label}
      <span className="relative mt-1.5 block">
        <LeadingIcon icon={icon} />
        <select className={cn(inputClass, icon && withIcon)} {...props}>{children}</select>
      </span>
      {hint && <span className="mt-1 block text-xs font-normal text-muted">{hint}</span>}
    </label>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{message}</p>;
}
