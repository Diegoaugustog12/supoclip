"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ChevronDown, Download, Loader2, Play, Scissors, Timer } from "lucide-react";
import { ClipCover } from "@/components/app/clip-cover";
import { PostCopyPanel, type WallClip } from "@/components/app/clip-wall";
import { SelectDot } from "@/components/app/select-dot";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { getClipUrl } from "@/lib/clip-actions";
import { formatClipDuration } from "@/lib/generations";
import type { WorkflowPlan } from "@/lib/workflows";

/** Lengths a compilation can be shortened to, when the plan doesn't say. */
export const DEFAULT_SHORTEN_CHOICES = [15, 30, 60, 120] as const;

/** A shortened copy's parent: the compilation it was cut from. */
export function parentOf(clip: Pick<WallClip, "workflow_meta">): string | null {
  return clip.workflow_meta?.parent_clip_id ?? null;
}

/** Compilations in clip order, each followed by the shorter copies made from it. */
export function groupSubjects<C extends Pick<WallClip, "id" | "clip_order" | "workflow_meta">>(clips: C[]) {
  const ordered = [...clips].sort((a, b) => a.clip_order - b.clip_order);
  const ids = new Set(ordered.map((clip) => clip.id));
  const originals = ordered.filter((clip) => {
    const parent = parentOf(clip);
    return !parent || !ids.has(parent);
  });
  return originals.map((clip) => ({
    clip,
    versions: ordered
      .filter((item) => parentOf(item) === clip.id)
      .sort((a, b) => (a.workflow_meta?.shortened_to ?? 0) - (b.workflow_meta?.shortened_to ?? 0)),
  }));
}

/** "15 s", "30 s", "1 min", "2 min". */
export function shortenLabel(seconds: number) {
  return seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

export function SubjectsView<C extends WallClip>({
  clips, plan, taskId, editable, busyId, shorteningId, toolbar, selectedIds, onToggleSelect, onOpen, onDownload, onShorten, renderActions,
}: {
  clips: C[];
  plan?: WorkflowPlan | null;
  taskId: string;
  editable: boolean;
  /** The clip whose download or export is running. */
  busyId: string | null;
  /** The clip being shortened right now. */
  shorteningId: string | null;
  toolbar?: React.ReactNode;
  /** Clips picked for "download selected". */
  selectedIds?: ReadonlySet<string>;
  onToggleSelect?: (clip: C) => void;
  onOpen: (clip: C) => void;
  onDownload: (clip: C) => void;
  onShorten?: (clip: C, seconds: number) => void;
  renderActions?: (clip: C) => React.ReactNode;
}) {
  const t = useTranslations("task");
  const groups = groupSubjects(clips);
  const choices = plan?.shorten_choices?.length ? plan.shorten_choices : DEFAULT_SHORTEN_CHOICES;

  return (
    <section aria-label={t("subjectsHeader", { count: groups.length })}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{t("subjectsHeader", { count: groups.length })}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("subjectsHint")}</p>
        </div>
        {toolbar}
      </div>

      <ul className="space-y-3">
        {groups.map(({ clip, versions }) => (
          <li key={clip.id} className="animate-rise rounded-2xl border bg-background p-3 sm:p-4">
            <SubjectRow
              clip={clip}
              taskId={taskId}
              editable={editable}
              busy={busyId === clip.id}
              shortening={shorteningId === clip.id}
              choices={choices}
              selected={selectedIds?.has(clip.id)}
              selecting={!!selectedIds?.size}
              onToggleSelect={onToggleSelect ? () => onToggleSelect(clip) : undefined}
              onOpen={() => onOpen(clip)}
              onDownload={() => onDownload(clip)}
              onShorten={onShorten ? (seconds) => onShorten(clip, seconds) : undefined}
              actions={renderActions?.(clip)}
            />
            {versions.length > 0 && (
              <ul className="mt-3 space-y-2 border-t pt-3" aria-label={t("subjectVersions")}>
                {versions.map((version) => (
                  <li key={version.id} className="flex flex-wrap items-center gap-3">
                    <div className="group/select relative w-12 shrink-0">
                    {onToggleSelect && (
                      <SelectDot
                        selected={!!selectedIds?.has(version.id)}
                        always={!!selectedIds?.size}
                        onToggle={() => onToggleSelect(version)}
                        label={t("selectClip", { title: `${subjectName(version, t)} · ${shortenLabel(version.workflow_meta?.shortened_to ?? 0)}` })}
                        className="left-0.5 top-0.5 size-5"
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => onOpen(version)}
                      aria-label={t("preview", { title: `${subjectName(version, t)} · ${shortenLabel(version.workflow_meta?.shortened_to ?? 0)}` })}
                      className="group relative block w-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <ClipCover src={getClipUrl(version.video_url, version.filename)} className="aspect-[9/16] rounded-lg ring-1 ring-black/5">
                        <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/25">
                          <Play className="size-3.5 fill-white text-white opacity-0 transition-opacity group-hover:opacity-100" />
                        </span>
                      </ClipCover>
                    </button>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-medium tabular-nums text-muted-foreground">
                        {t("subjectUpTo", { length: shortenLabel(version.workflow_meta?.shortened_to ?? 0) })} · {formatClipDuration(version.duration)}
                      </p>
                      <p className="text-sm font-medium leading-snug">{subjectName(version, t)}</p>
                      {version.reasoning?.trim() && <p className="line-clamp-2 text-xs text-muted-foreground">{version.reasoning.trim()}</p>}
                    </div>
                    <Button size="sm" variant="outline" onClick={() => onDownload(version)} disabled={busyId === version.id} aria-label={t("downloadNamed", { title: `${subjectName(version, t)} · ${shortenLabel(version.workflow_meta?.shortened_to ?? 0)}` })}>
                      {busyId === version.id ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}{t("download")}
                    </Button>
                    {editable && (
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/tasks/${taskId}/edit?clip=${version.id}`}><Scissors className="size-4" />{t("edit")}</Link>
                      </Button>
                    )}
                    {renderActions?.(version)}
                    {editable && version.text && <div className="w-full"><PostCopyPanel taskId={taskId} clipId={version.id} /></div>}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function subjectName(clip: Pick<WallClip, "workflow_meta" | "hook_title" | "clip_order">, t: ReturnType<typeof useTranslations<"task">>) {
  return clip.workflow_meta?.subject?.trim() || clip.hook_title?.trim() || t("clipNumber", { order: clip.clip_order });
}

function SubjectRow<C extends WallClip>({ clip, taskId, editable, busy, shortening, choices, selected, selecting, onToggleSelect, onOpen, onDownload, onShorten, actions }: {
  clip: C;
  taskId: string;
  editable: boolean;
  busy: boolean;
  shortening: boolean;
  choices: readonly number[];
  selected?: boolean;
  selecting?: boolean;
  onToggleSelect?: () => void;
  onOpen: () => void;
  onDownload: () => void;
  onShorten?: (seconds: number) => void;
  actions?: React.ReactNode;
}) {
  const t = useTranslations("task");
  const title = subjectName(clip, t);
  const moments = clip.workflow_meta?.moment_count ?? clip.workflow_meta?.moments?.length ?? 0;
  const description = clip.reasoning?.trim();
  const shortenable = choices.filter((seconds) => clip.duration > seconds + 0.5);

  return (
    <div className="flex gap-4 sm:gap-5">
      <div className="group/select relative w-24 shrink-0 self-start sm:w-32">
      {onToggleSelect && <SelectDot selected={!!selected} always={selecting} onToggle={onToggleSelect} label={t("selectClip", { title })} />}
      <button
        type="button"
        onClick={onOpen}
        aria-label={t("preview", { title })}
        className="group relative block w-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <ClipCover src={getClipUrl(clip.video_url, clip.filename)} className="aspect-[9/16] rounded-xl ring-1 ring-black/5">
          <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/25">
            <span className="flex size-10 items-center justify-center rounded-full bg-white/90 text-black opacity-0 shadow-lg transition-opacity group-hover:opacity-100"><Play className="ml-0.5 size-4 fill-current" /></span>
          </span>
          <span className="absolute bottom-1.5 right-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white">{formatClipDuration(clip.duration)}</span>
        </ClipCover>
      </button>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <p className="text-xs font-medium tabular-nums text-muted-foreground">
          {t("subjectMoments", { count: moments })} · {formatClipDuration(clip.duration)}
        </p>
        <h3 className="mt-0.5 text-base font-semibold leading-snug">{title}</h3>
        {description && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{description}</p>}

        <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
          <Button size="sm" variant="outline" onClick={onDownload} disabled={busy} aria-label={t("downloadNamed", { title })}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}{t("subjectDownloadOriginal")}
          </Button>
          {onShorten && editable && shortenable.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" disabled={shortening} aria-label={t("shortenNamed", { title })}>
                  {shortening ? <Loader2 className="size-4 animate-spin" /> : <Timer className="size-4" />}
                  {t("shorten")}<ChevronDown className="size-3.5 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-48">
                {shortenable.map((seconds) => (
                  <DropdownMenuItem key={seconds} onSelect={() => onShorten(seconds)}>
                    {t("subjectUpTo", { length: shortenLabel(seconds) })}
                    {seconds === clip.workflow_meta?.recommended_shorten && (
                      <span className="ml-auto rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">{t("subjectRecommended")}</span>
                    )}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {editable && (
            <Button size="sm" variant="outline" asChild>
              <Link href={`/tasks/${taskId}/edit?clip=${clip.id}`}><Scissors className="size-4" />{t("edit")}</Link>
            </Button>
          )}
          {actions}
        </div>
      </div>
    </div>
  );
}
