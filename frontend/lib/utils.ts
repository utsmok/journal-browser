import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Scraped openaccess.nl prose carries Cloudflare "[email protected]" placeholders;
// the real addresses only exist on the linked deal pages.
export function cleanProse(text: string): string {
  return text.replace(/\[email(?:\s+protected)?\]/gi, "the publisher contact");
}
