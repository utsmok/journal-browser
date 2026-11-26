import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import type { ReactNode } from "react";

/**
 * Ships to the browser only the message namespaces that a section's client
 * components read with useTranslations. Server components keep reading every
 * namespace through getTranslations. "common" always rides along: the shell
 * and the shared widgets inside a section read it on every page.
 *
 * Note: NextIntlClientProvider replaces parent messages rather than merging,
 * so a nested SectionMessages defines the full client namespace set for its
 * subtree ("common" plus `namespaces`).
 */
export async function SectionMessages({
  namespaces = [],
  children,
}: {
  namespaces?: readonly string[];
  children: ReactNode;
}) {
  const all = await getMessages();
  const messages = Object.fromEntries(["common", ...namespaces].map((ns) => [ns, all[ns]]));
  return <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>;
}
