"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

type Channel = {
  id: string;
  channel_url: string;
  platform?: "youtube" | "twitch" | "kick";
  title: string;
  allows_clips: boolean;
  active: boolean;
  last_checked_at: string | null;
  last_error: string | null;
  pending_count: number;
};

type Discovery = {
  id: string;
  watch_id: string;
  channel_title: string;
  allows_clips: boolean;
  video_id: string;
  url: string;
  title: string;
  duration_seconds: number | null;
  task_id: string | null;
};

const POLL_MS = 60_000;
const PLATFORM_LABEL = { youtube: "YouTube", twitch: "Twitch", kick: "Kick" } as const;

async function errorText(response: Response, fallback: string) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (typeof detail?.message === "string") return detail.message;
  } catch {
    // keep the fallback
  }
  return fallback;
}

export function AutomationsView() {
  const t = useTranslations("automations");
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [url, setUrl] = useState("");
  const [allowsClips, setAllowsClips] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [created, setCreated] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [channelResponse, discoveryResponse] = await Promise.all([
        fetch("/api/automations/channels", { cache: "no-store" }),
        fetch("/api/automations/discoveries?status=pending", { cache: "no-store" }),
      ]);
      if (channelResponse.ok) setChannels((await channelResponse.json()).channels ?? []);
      if (discoveryResponse.ok) setDiscoveries((await discoveryResponse.json()).discoveries ?? []);
    } catch {
      setChannels((current) => current ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  async function addChannel(event: React.FormEvent) {
    event.preventDefault();
    if (!url.trim() || adding) return;
    setAdding(true);
    try {
      const response = await fetch("/api/automations/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), allows_clips: allowsClips }),
      });
      if (!response.ok) {
        toast.error(await errorText(response, t("genericError")));
        return;
      }
      setUrl("");
      setAllowsClips(false);
      await load();
    } finally {
      setAdding(false);
    }
  }

  async function patchChannel(channel: Channel, changes: Partial<Pick<Channel, "allows_clips" | "active">>) {
    const response = await fetch(`/api/automations/channels/${channel.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    if (!response.ok) toast.error(await errorText(response, t("genericError")));
    await load();
  }

  async function removeChannel(channel: Channel) {
    if (!window.confirm(t("removeConfirm"))) return;
    const response = await fetch(`/api/automations/channels/${channel.id}`, { method: "DELETE" });
    if (!response.ok) toast.error(await errorText(response, t("genericError")));
    await load();
  }

  async function checkNow(channel: Channel) {
    setBusy(`check:${channel.id}`);
    try {
      const response = await fetch(`/api/automations/channels/${channel.id}/check`, { method: "POST" });
      if (!response.ok) {
        toast.error(await errorText(response, t("genericError")));
      } else {
        const { found } = await response.json();
        toast.message(found > 0 ? t("foundNew", { count: found }) : t("foundNone"));
      }
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function approve(discovery: Discovery) {
    if (!discovery.allows_clips && !window.confirm(t("confirmNotAllowed"))) return;
    setBusy(`clip:${discovery.id}`);
    try {
      // The task goes through the same checks and limits as one created on the home page.
      const start = await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: { url: discovery.url, title: discovery.title || null },
          caption_template: "default",
          processing_mode: "fast",
          output_format: "vertical",
          clip_length: "auto",
          add_subtitles: true,
        }),
      });
      if (!start.ok) {
        toast.error(await errorText(start, t("genericError")));
        return;
      }
      const { task_id: taskId } = await start.json();
      await fetch(`/api/automations/discoveries/${discovery.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId }),
      });
      setCreated((current) => ({ ...current, [discovery.id]: taskId }));
      toast.success(t("created"));
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function dismiss(discovery: Discovery) {
    setBusy(`dismiss:${discovery.id}`);
    try {
      await fetch(`/api/automations/discoveries/${discovery.id}/dismiss`, { method: "POST" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  if (channels === null) return <Skeleton className="h-40 w-full" />;

  const minutes = (seconds: number | null) => {
    if (!seconds) return "";
    const total = Math.max(1, Math.round(seconds / 60));
    return total < 60 ? t("minutes", { count: total }) : t("hoursMinutes", { hours: Math.floor(total / 60), minutes: total % 60 });
  };
  const checkedLabel = (iso: string | null) =>
    iso ? t("checkedAt", { time: new Date(iso).toLocaleString() }) : t("neverChecked");

  return (
    <div className="space-y-10">
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("waiting")}</h2>
        {discoveries.length === 0 && Object.keys(created).length === 0 ? (
          <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">{t("noWaiting")}</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {Object.entries(created).map(([id, taskId]) => (
              <li key={id} className="flex items-center justify-between gap-3 p-4 text-sm">
                <span>{t("created")}</span>
                <Button asChild size="sm" variant="outline"><Link href={`/tasks/${taskId}`}>{t("openTask")}</Link></Button>
              </li>
            ))}
            {discoveries.map((discovery) => (
              <li key={discovery.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate font-medium">{discovery.title || discovery.video_id}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {discovery.channel_title}
                    {discovery.duration_seconds ? ` · ${minutes(discovery.duration_seconds)}` : ""}
                    {!discovery.allows_clips ? ` · ${t("notAllowedBadge")}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" disabled={busy === `clip:${discovery.id}`} onClick={() => void approve(discovery)}>
                    {busy === `clip:${discovery.id}` ? t("creating") : t("clipIt")}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy === `dismiss:${discovery.id}`} onClick={() => void dismiss(discovery)}>
                    {t("dismiss")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("addTitle")}</h2>
        <form onSubmit={addChannel} className="space-y-3 rounded-xl border p-4">
          <label className="block text-sm font-medium" htmlFor="channel-url">{t("urlLabel")}</label>
          <Input id="channel-url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder={t("urlPlaceholder")} inputMode="url" />
          <label className="flex items-start gap-2 text-sm">
            <Checkbox checked={allowsClips} onCheckedChange={(value) => setAllowsClips(value === true)} className="mt-0.5" />
            <span>
              {t("allowsClips")}
              <span className="block text-xs text-muted-foreground">{t("allowsHint")}</span>
            </span>
          </label>
          <Button type="submit" disabled={adding || !url.trim()}>{adding ? t("adding") : t("add")}</Button>
        </form>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("following")}</h2>
        {channels.length === 0 ? (
          <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">{t("noChannels")}</p>
        ) : (
          <ul className="divide-y rounded-xl border">
            {channels.map((channel) => (
              <li key={channel.id} className="space-y-3 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <a href={channel.channel_url} target="_blank" rel="noreferrer" className="truncate font-medium hover:underline">
                      {channel.title || channel.channel_url}
                    </a>
                    <p className="text-xs text-muted-foreground">
                      {PLATFORM_LABEL[channel.platform ?? "youtube"]} · {checkedLabel(channel.last_checked_at)}
                      {!channel.active ? ` · ${t("paused")}` : ""}
                      {channel.pending_count > 0 ? ` · ${t("foundNew", { count: channel.pending_count })}` : ""}
                    </p>
                    {channel.last_error ? <p className="text-xs text-destructive">{channel.last_error}</p> : null}
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={busy === `check:${channel.id}`} onClick={() => void checkNow(channel)}>
                      {busy === `check:${channel.id}` ? t("checking") : t("checkNow")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void removeChannel(channel)}>{t("remove")}</Button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <label className="flex items-center gap-2">
                    <Checkbox checked={channel.allows_clips} onCheckedChange={(value) => void patchChannel(channel, { allows_clips: value === true })} />
                    {t("allowsClips")}
                  </label>
                  <label className="flex items-center gap-2">
                    <Checkbox checked={channel.active} onCheckedChange={(value) => void patchChannel(channel, { active: value === true })} />
                    {t("active")}
                  </label>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
