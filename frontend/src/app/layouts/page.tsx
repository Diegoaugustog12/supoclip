"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { LayoutEditor } from "@/components/app/layout-editor";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth-client";

export default function LayoutsPage() {
  const t = useTranslations("layouts");
  const { data: session, isPending } = useSession();

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-10">
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (!session?.user) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-24 text-center">
        <p className="mb-4 text-muted-foreground">{t("signIn")}</p>
        <Button asChild><Link href="/sign-in">{t("signInAction")}</Link></Button>
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-8 md:py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="mb-8 mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
      <LayoutEditor />
    </main>
  );
}
