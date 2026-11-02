/* shadcn/ui-style primitives (Radix + Tailwind + cva), written in-repo. */
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2, X } from "lucide-react";
import { forwardRef, useId, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ---------------- Button ----------------
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none select-none",
  {
    variants: {
      variant: {
        primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
        secondary: "bg-card text-ink border border-line-strong hover:bg-canvas",
        ghost: "text-ink-2 hover:bg-canvas hover:text-ink",
        danger: "bg-bad-700 text-white hover:bg-[#962020]",
        subtle: "bg-brand-50 text-brand-700 hover:bg-brand-100",
        link: "text-sky-700 hover:underline px-0 h-auto",
      },
      size: { sm: "h-8 px-3 text-[13px] rounded-lg", md: "h-9 px-4 text-sm rounded-lg", lg: "h-11 px-5 text-[15px] rounded-xl", icon: "h-9 w-9 rounded-lg" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { loading?: boolean };
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, loading, children, disabled, type = "button", ...props }, ref) {
  return (
    <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

// ---------------- Form controls ----------------
const controlBase =
  "w-full rounded-lg border border-line-strong bg-card px-3 text-sm text-ink placeholder:text-ink-3 transition-colors " +
  "focus:outline-none focus:ring-2 focus:ring-brand-600/25 focus:border-brand-600 disabled:bg-canvas disabled:text-ink-3 " +
  "aria-[invalid=true]:border-bad-700 aria-[invalid=true]:focus:ring-bad-700/20";

export const Input = forwardRef<HTMLInputElement, ComponentProps<"input">>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(controlBase, "h-9", className)} {...p} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, ComponentProps<"textarea">>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cn(controlBase, "py-2 min-h-[84px] resize-y", className)} {...p} />;
});
export const Select = forwardRef<HTMLSelectElement, ComponentProps<"select">>(function Select({ className, ...p }, ref) {
  return <select ref={ref} className={cn(controlBase, "h-9 pr-8 cursor-pointer", className)} {...p} />;
});

/** Label + control + hint/error, wired with ids for screen readers. */
export function Field({ label, error, hint, required, children, className }: {
  label: string; error?: string; hint?: string; required?: boolean; className?: string;
  children: (props: { id: string; "aria-invalid"?: boolean; "aria-describedby"?: string }) => ReactNode;
}) {
  const id = useId();
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-medium text-ink">
        {label}{required && <span className="text-bad-700" aria-hidden> *</span>}
      </label>
      {children({ id, "aria-invalid": error ? true : undefined, "aria-describedby": describedBy })}
      {error ? <p id={`${id}-err`} role="alert" className="text-[12.5px] text-bad-700">{error}</p>
        : hint ? <p id={`${id}-hint`} className="text-[12.5px] text-ink-3">{hint}</p> : null}
    </div>
  );
}

// ---------------- Card ----------------
export function Card({ className, ...p }: ComponentProps<"section">) {
  return <section className={cn("card", className)} {...p} />;
}
export function CardHeader({ title, description, action, className }: {
  title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {description && <p className="text-[13px] text-ink-3 mt-0.5">{description}</p>}
      </div>
      {action}
    </div>
  );
}

// ---------------- Badge ----------------
const toneClass = {
  neutral: "bg-canvas text-ink-2 ring-line-strong",
  ok: "bg-ok-50 text-ok-700 ring-ok-700/20",
  warn: "bg-warn-50 text-warn-700 ring-warn-700/20",
  bad: "bg-bad-50 text-bad-700 ring-bad-700/20",
  info: "bg-info-50 text-info-700 ring-info-700/20",
  teal: "bg-brand-50 text-brand-700 ring-brand-600/20",
} as const;
export type Tone = keyof typeof toneClass;

export function Badge({ tone = "neutral", dot, className, children }: {
  tone?: Tone; dot?: boolean; className?: string; children: ReactNode;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-medium ring-1 ring-inset whitespace-nowrap", toneClass[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

// ---------------- Dialog ----------------
export function Dialog({ open, onOpenChange, title, description, children, footer, wide }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string;
  children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/40 backdrop-blur-[1px] data-[state=open]:animate-in" />
        <DialogPrimitive.Content
          className={cn("fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-24px)] max-h-[calc(100vh-32px)] overflow-y-auto",
            "bg-card rounded-2xl shadow-[var(--shadow-pop)] border border-line focus:outline-none", wide ? "max-w-2xl" : "max-w-lg")}>
          <div className="flex items-start justify-between gap-4 px-6 pt-5">
            <div>
              <DialogPrimitive.Title className="text-[17px] font-semibold">{title}</DialogPrimitive.Title>
              {description ? <DialogPrimitive.Description className="text-[13px] text-ink-3 mt-1">{description}</DialogPrimitive.Description>
                : <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>}
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-ink-3 hover:text-ink hover:bg-canvas" aria-label="Close">
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="px-6 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 px-6 py-4 border-t border-line bg-canvas/50 rounded-b-2xl">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

// ---------------- Tabs ----------------
export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;
export function TabsList({ className, ...p }: ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("flex gap-1 border-b border-line overflow-x-auto", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn("relative -mb-px px-3 py-2 text-[13.5px] font-medium text-ink-3 border-b-2 border-transparent whitespace-nowrap",
        "hover:text-ink data-[state=active]:text-brand-700 data-[state=active]:border-brand-600", className)}
      {...p} />
  );
}

// ---------------- Misc ----------------
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} aria-hidden />;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-ink-3 text-sm py-8 justify-center">
      <Loader2 className="size-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}
