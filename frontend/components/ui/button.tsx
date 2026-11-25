import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-w-11 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius)] text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 min-[1024px]:min-w-0",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[var(--primary-hover)]",
        secondary: "bg-[var(--secondary)] text-[var(--secondary-foreground)] hover:opacity-90",
        outline:
          "border border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:bg-[var(--muted)]",
        ghost: "text-[var(--foreground)] hover:bg-[var(--muted)]",
        link: "text-[var(--primary-text)] underline-offset-4 hover:underline",
      },
      // 44px targets on phones and tablets; desktop sizes from lg.
      size: {
        default: "h-11 px-4 py-2 min-[1024px]:h-10",
        sm: "h-11 px-3 text-sm min-[1024px]:h-8 min-[1024px]:text-xs",
        lg: "h-12 px-6 text-base",
        icon: "h-11 w-11 min-[1024px]:h-10 min-[1024px]:w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export { Button, buttonVariants };
