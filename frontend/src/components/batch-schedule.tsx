"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { CalendarClock, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SocialConnection, SocialProviderStatus } from "@/lib/social";

const GAPS = [60, 180, 360, 720, 1440, 2880] as const;

function defaultStart() {
  const date = new Date(Date.now() + 60 * 60 * 1000);
  date.setMinutes(0, 0, 0);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:00`;
}

async function errorText(response: Response, fallback: string) {
  try {
    const detail = (await response.json())?.detail;
    if (typeof detail === "string") return detail;
  } catch {
    // keep the fallback
  }
  return fallback;
}

type Props = {
  taskId: string;
  clipIds: string[];
  connections: SocialConnection[];
  providers: SocialProviderStatus[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
};

/** Which connected accounts can take scheduled posts. */
export function schedulableConnections(connections: SocialConnection[], providers: SocialProviderStatus[]) {
  return connections.filter(
    (connection) =>
      connection.status === "active" &&
      providers.some((provider) => provider.provider === connection.provider && provider.configured && !provider.paused),
  );
}

export function BatchScheduleDialog({ taskId, clipIds, connections, providers, open, onOpenChange, onDone }: Props) {
  const t = useTranslations("social.batch");
  const accounts = useMemo(() => schedulableConnections(connections, providers), [connections, providers]);
  const [accountId, setAccountId] = useState("");
  const [start, setStart] = useState(defaultStart);
  const [gap, setGap] = useState<number>(1440);
  const [submitting, setSubmitting] = useState(false);

  const chosenAccount = accounts.find((account) => account.id === accountId) ?? accounts[0];

  async function submit() {
    if (!chosenAccount || submitting) return;
    const startDate = new Date(start);
    if (Number.isNaN(startDate.getTime())) {
      toast.error(t("badDate"));
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch("/api/social/posts/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: taskId,
          clip_ids: clipIds,
          social_account_id: chosenAccount.id,
          start: startDate.toISOString(),
          interval_minutes: gap,
        }),
      });
      if (!response.ok) {
        toast.error(await errorText(response, t("failed")));
        return;
      }
      const result = (await response.json()) as { posts?: unknown[]; failures?: { error: string }[] };
      const done = result.posts?.length ?? 0;
      const failed = result.failures ?? [];
      if (done > 0) toast.success(t("done", { count: done }));
      if (failed.length > 0) toast.error(t("someFailed", { count: failed.length, reason: failed[0].error }));
      if (done > 0) {
        onDone();
        onOpenChange(false);
      }
    } catch {
      toast.error(t("failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("title", { count: clipIds.length })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>{t("account")}</Label>
            <Select value={chosenAccount?.id ?? ""} onValueChange={setAccountId}>
              <SelectTrigger className="w-full"><SelectValue placeholder={t("noAccount")} /></SelectTrigger>
              <SelectContent>
                {accounts.map((account) => (
                  <SelectItem key={account.id} value={account.id}>
                    {account.provider} · {account.display_name || account.username || account.external_account_id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-start">{t("start")}</Label>
            <Input id="batch-start" type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>{t("gap")}</Label>
            <Select value={String(gap)} onValueChange={(value) => setGap(Number(value))}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {GAPS.map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>{t(`gaps.${minutes}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">{t("hint")}</p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button onClick={() => void submit()} disabled={submitting || !chosenAccount}>
            {submitting ? <Loader2 className="size-4 animate-spin" /> : <CalendarClock className="size-4" />}
            {t("submit", { count: clipIds.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
