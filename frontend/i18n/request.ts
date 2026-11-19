import { getRequestConfig } from "next-intl/server";

import about from "../messages/en/about.json";
import admin from "../messages/en/admin.json";
import authors from "../messages/en/authors.json";
import common from "../messages/en/common.json";
import dataPipeline from "../messages/en/dataPipeline.json";
import deals from "../messages/en/deals.json";
import docs from "../messages/en/docs.json";
import funders from "../messages/en/funders.json";
import home from "../messages/en/home.json";
import journals from "../messages/en/journals.json";
import orgunits from "../messages/en/orgunits.json";
import publishers from "../messages/en/publishers.json";
import search from "../messages/en/search.json";

// Single locale for now; translations plug in by adding messages/<locale>/
// files and reading the locale from the route here.
const LOCALE = "en";

export default getRequestConfig(async () => ({
  locale: LOCALE,
  // One top-level namespace per file; a page reads its slice with
  // getTranslations("journals") etc.
  messages: {
    common,
    home,
    journals,
    authors,
    orgunits,
    publishers,
    funders,
    deals,
    docs,
    about,
    dataPipeline,
    admin,
    search,
  },
}));
