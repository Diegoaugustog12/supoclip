"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The round check on a clip's thumbnail. Put it in a `relative group/select` wrapper: it shows on hover
 * or focus, and stays visible once picked or while any clip is selected (`always`).
 */
export function SelectDot({ selected, onToggle, label, always, className }: {
  selected: boolean;
  onToggle: () => void;
  label: string;
  always?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={selected}
      aria-label={label}
      onClick={(event) => { event.stopPropagation(); onToggle(); }}
      className={cn(
        "absolute left-2 top-2 z-10 flex size-6 items-center justify-center rounded-full border-2 text-white shadow backdrop-blur transition-opacity",
        "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary text-primary-foreground opacity-100"
          : cn("border-white/90 bg-black/35 hover:bg-black/55", always ? "opacity-100" : "opacity-0 group-hover/select:opacity-100"),
        className,
      )}
    >
      {selected && <Check className="size-3.5" strokeWidth={3} />}
    </button>
  );
}
