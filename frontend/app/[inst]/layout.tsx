import { InstitutionProvider } from "@/hooks/use-institution";

export default async function InstLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ inst: string }>;
}) {
  const { inst } = await params;
  return <InstitutionProvider code={inst}>{children}</InstitutionProvider>;
}
