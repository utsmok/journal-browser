/** Public origin of this deployment. The Docker build passes it in as NEXT_PUBLIC_SITE_URL. */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL || "https://journalbrowser.samuelmok.cc"
).replace(/\/+$/, "");
