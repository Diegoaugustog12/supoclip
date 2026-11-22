import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { isLocale, LOCALE_COOKIE, negotiateLocale } from "./config";
import { loadMessages } from "./load-messages";

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE)?.value;
  // APP_LOCALE fixes the language for everyone who hasn't picked one in the
  // language menu, instead of following the browser.
  const fixedLocale = process.env.APP_LOCALE?.trim().toLowerCase();
  const locale = isLocale(cookieLocale)
    ? cookieLocale
    : isLocale(fixedLocale)
      ? fixedLocale
      : negotiateLocale((await headers()).get("accept-language"));

  return {
    locale,
    messages: await loadMessages(locale),
  };
});
