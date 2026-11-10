"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { editorRequest } from "@/components/editor/use-editor";

const BUILT_IN = ["auto", "reaction_top", "reaction_bottom", "reaction_dynamic", "stack", "speaker"] as const;

type Saved = { id: string; name: string };

/**
 * Choose how this clip's 9:16 frame is composed and rebuild the studio's source with it.
 * The draft (cuts, captions, B-roll) is kept: only the picture is redone.
 */
export function LayoutPicker({
  endpoint,
  layout,
  layoutId,
}: {
  endpoint: string;
  layout?: string;
  layoutId?: string | null;
}) {
  const t = useTranslations("editor");
  const tHome = useTranslations("home");
  const [saved, setSaved] = useState<Saved[]>([]);
  const current = layout === "custom" && layoutId ? `custom:${layoutId}` : layout || "auto";
  const [choice, setChoice] = useState(current);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/layouts", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : { layouts: [] }))
      .then((body) => setSaved(Array.isArray(body.layouts) ? body.layouts : []))
      .catch(() => setSaved([]));
  }, []);

  async function apply() {
    setBusy(true);
    try {
      const body = choice.startsWith("custom:")
        ? { layout: "custom", layout_id: choice.slice("custom:".length) }
        : { layout: choice };
      await editorRequest(`${endpoint}/layout`, "POST", body);
      // The preview is rebuilt on the server; reloading follows it until it is ready again.
      window.location.reload();
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : t("framing.layoutFailed"));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <p className="text-sm font-medium">{t("framing.layoutTitle")}</p>
      <p className="text-xs text-muted-foreground">{t("framing.layoutBody")}</p>
      <select
        aria-label={t("framing.layoutTitle")}
        className="h-9 w-full rounded-md border bg-background px-2 text-sm"
        value={choice}
        disabled={busy}
        onChange={(event) => setChoice(event.target.value)}
      >
        {BUILT_IN.map((id) => (
          <option key={id} value={id}>{tHome(`layoutOptions.${id}.label`)}</option>
        ))}
        {saved.length > 0 && (
          <optgroup label={tHome("myLayouts")}>
            {saved.map((item) => (
              <option key={item.id} value={`custom:${item.id}`}>{item.name}</option>
            ))}
          </optgroup>
        )}
      </select>
      <Button type="button" size="sm" className="w-full" disabled={busy || choice === current} onClick={() => void apply()}>
        {busy ? t("framing.layoutWorking") : t("framing.layoutApply")}
      </Button>
    </div>
  );
}
