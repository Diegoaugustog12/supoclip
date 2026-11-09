"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowDownUp, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import {
  type Crop,
  type LayoutSpec,
  type PanelCount,
  OUT_H,
  OUT_W,
  buildSpec,
  fitCrop,
  fromSpec,
  moveCrop,
  panelHeights,
  panelRatio,
  resizeCrop,
} from "@/lib/layout-spec";

type Saved = { id: string; name: string; spec: LayoutSpec };
type Frame = { src: string; aspect: number; image: HTMLImageElement };
type Drag = { index: number; mode: "move" | "resize"; startX: number; startY: number; crop: Crop };

const PANEL_COLORS = ["#22c55e", "#3b82f6"];
const PREVIEW_W = 180;

async function errorText(response: Response, fallback: string) {
  try {
    const body = await response.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

export function LayoutEditor() {
  const t = useTranslations("layouts");
  const [url, setUrl] = useState("");
  const [time, setTime] = useState("30");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [loadingFrame, setLoadingFrame] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [count, setCount] = useState<PanelCount>(2);
  const [firstShare, setFirstShare] = useState(0.35);
  const [crops, setCrops] = useState<Crop[]>([]);
  const [captionY, setCaptionY] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [saving, setSaving] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const preview = useRef<HTMLCanvasElement>(null);
  const drag = useRef<Drag | null>(null);

  const heights = useMemo(() => panelHeights(count, firstShare), [count, firstShare]);
  const aspect = frame?.aspect ?? 16 / 9;

  const loadSaved = useCallback(async () => {
    try {
      const response = await fetch("/api/layouts", { cache: "no-store" });
      if (response.ok) setSaved((await response.json()).layouts ?? []);
    } catch {
      /* the list is a convenience */
    }
  }, []);
  useEffect(() => { void loadSaved(); }, [loadSaved]);

  // Re-fit every crop to its panel's shape when the split, count or frame changes.
  useEffect(() => {
    if (!frame) return;
    setCrops((current) => {
      const starts = current.length ? current : [
        { x: 0.68, y: 0.58, w: 0.3, h: 0 },
        { x: 0, y: 0, w: 1, h: 0 },
      ];
      return [0, 1].map((i) => fitCrop(starts[i] ?? starts[0], panelRatio(heights[i] ?? heights[0]), aspect));
    });
  }, [frame, heights, aspect]);

  // The 9:16 result, drawn from the same crops the render will use.
  useEffect(() => {
    const canvas = preview.current;
    if (!canvas || !frame || crops.length < count) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const scale = PREVIEW_W / OUT_W;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    let y = 0;
    heights.forEach((ph, i) => {
      const crop = crops[i];
      const h = ph * scale;
      const { naturalWidth: nw, naturalHeight: nh } = frame.image;
      ctx.drawImage(frame.image, crop.x * nw, crop.y * nh, crop.w * nw, crop.h * nh, 0, y, PREVIEW_W, h);
      y += h;
    });
    const lineY = (captionY ?? (count === 2 ? heights[0] / OUT_H : 0.8)) * canvas.height;
    ctx.fillStyle = "rgba(250, 204, 21, 0.9)";
    ctx.fillRect(PREVIEW_W * 0.1, lineY - 3, PREVIEW_W * 0.8, 6);
  }, [frame, crops, heights, count, captionY]);

  async function loadFrame() {
    setLoadingFrame(true);
    setFrameError(null);
    try {
      const response = await fetch("/api/layouts/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), time: Number(time) || 0 }),
      });
      if (!response.ok) throw new Error(await errorText(response, t("previewError")));
      const src = URL.createObjectURL(await response.blob());
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error(t("previewError")));
        image.src = src;
      });
      setFrame((previous) => {
        if (previous) URL.revokeObjectURL(previous.src);
        return { src, image, aspect: image.naturalWidth / image.naturalHeight };
      });
    } catch (error) {
      setFrameError(error instanceof Error ? error.message : t("previewError"));
    } finally {
      setLoadingFrame(false);
    }
  }

  function onPointerDown(event: React.PointerEvent, index: number, mode: Drag["mode"]) {
    event.preventDefault();
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { index, mode, startX: event.clientX, startY: event.clientY, crop: crops[index] };
  }

  function onPointerMove(event: React.PointerEvent) {
    const active = drag.current;
    const box = stage.current?.getBoundingClientRect();
    if (!active || !box) return;
    const dx = (event.clientX - active.startX) / box.width;
    const dy = (event.clientY - active.startY) / box.height;
    setCrops((current) => current.map((crop, i) => {
      if (i !== active.index) return crop;
      return active.mode === "move"
        ? moveCrop(active.crop, dx, dy)
        : resizeCrop(active.crop, active.crop.w + dx, panelRatio(heights[i]), aspect);
    }));
  }

  const stopDrag = () => { drag.current = null; };

  function swapPanels() {
    setCrops((current) => [current[1], current[0]].map((crop, i) => fitCrop(crop, panelRatio(heights[i]), aspect)));
  }

  function loadLayout(item: Saved) {
    const state = fromSpec(item.spec);
    setCount(state.count);
    setFirstShare(state.firstShare);
    setCrops(state.crops);
    setCaptionY(state.captionY);
    setName(item.name);
    setEditingId(item.id);
  }

  async function save(asNew: boolean) {
    if (!name.trim() || crops.length < count) return;
    setSaving(true);
    try {
      const updating = !asNew && editingId;
      const response = await fetch(updating ? `/api/layouts/${editingId}` : "/api/layouts", {
        method: updating ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), spec: buildSpec(count, firstShare, crops, captionY) }),
      });
      if (!response.ok) throw new Error(await errorText(response, t("saveError")));
      const body = await response.json();
      setEditingId(body.layout?.id ?? null);
      toast.success(t("saved"));
      await loadSaved();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    const response = await fetch(`/api/layouts/${id}`, { method: "DELETE" });
    if (!response.ok) {
      toast.error(await errorText(response, t("saveError")));
      return;
    }
    if (editingId === id) setEditingId(null);
    toast.success(t("deleted"));
    await loadSaved();
  }

  const labels = [t("topPanel"), t("bottomPanel")];

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <Label htmlFor="layout-url">{t("urlLabel")}</Label>
        <div className="flex flex-wrap gap-2">
          <Input id="layout-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("urlPlaceholder")} className="min-w-64 flex-1" />
          <Input type="number" min={0} aria-label={t("timeLabel")} value={time} onChange={(e) => setTime(e.target.value)} className="w-24" />
          <Button onClick={() => void loadFrame()} disabled={!url.trim() || loadingFrame}>
            {loadingFrame ? t("loading") : t("loadPreview")}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{t("timeHint")}</p>
        {frameError && <p role="alert" className="text-sm text-destructive">{frameError}</p>}
      </section>

      {frame ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto]">
          <section className="space-y-4">
            <div
              ref={stage}
              className="relative w-full select-none overflow-hidden rounded-lg border bg-black"
              style={{ aspectRatio: `${aspect}` }}
              onPointerMove={onPointerMove}
              onPointerUp={stopDrag}
              onPointerCancel={stopDrag}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={frame.src} alt={t("frameAlt")} className="pointer-events-none size-full object-fill" draggable={false} />
              {crops.slice(0, count).map((crop, i) => (
                <div
                  key={i}
                  role="group"
                  aria-label={labels[i]}
                  onPointerDown={(event) => onPointerDown(event, i, "move")}
                  className="absolute cursor-move touch-none border-2"
                  style={{
                    left: `${crop.x * 100}%`, top: `${crop.y * 100}%`,
                    width: `${crop.w * 100}%`, height: `${crop.h * 100}%`,
                    borderColor: PANEL_COLORS[i], background: `${PANEL_COLORS[i]}22`,
                  }}
                >
                  <span className="absolute left-1 top-1 rounded px-1 text-xs font-medium text-white" style={{ background: PANEL_COLORS[i] }}>{labels[i]}</span>
                  <div
                    role="presentation"
                    onPointerDown={(event) => onPointerDown(event, i, "resize")}
                    className="absolute -bottom-1.5 -right-1.5 size-4 cursor-nwse-resize touch-none rounded-sm border-2 border-white"
                    style={{ background: PANEL_COLORS[i] }}
                  />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{t("dragHint")}</p>

            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>{t("camerasLabel")}</Label>
                <div className="flex gap-2" role="radiogroup" aria-label={t("camerasLabel")}>
                  {([1, 2] as const).map((n) => (
                    <Button key={n} type="button" role="radio" aria-checked={count === n} variant={count === n ? "default" : "outline"} size="sm" onClick={() => setCount(n)}>
                      {n === 1 ? t("oneCamera") : t("twoCameras")}
                    </Button>
                  ))}
                </div>
              </div>
              {count === 2 && (
                <div className="space-y-2">
                  <Label>{t("splitLabel", { percent: Math.round(firstShare * 100) })}</Label>
                  <Slider value={[firstShare * 100]} min={15} max={85} step={1} onValueChange={(v) => setFirstShare(v[0] / 100)} aria-label={t("splitLabel", { percent: Math.round(firstShare * 100) })} />
                  <Button type="button" variant="outline" size="sm" onClick={swapPanels}><ArrowDownUp className="size-4" />{t("swap")}</Button>
                </div>
              )}
              <div className="space-y-2 sm:col-span-2">
                <div className="flex items-center justify-between">
                  <Label>{captionY === null ? t("captionAuto") : t("captionAt", { percent: Math.round(captionY * 100) })}</Label>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setCaptionY(captionY === null ? 0.5 : null)}>
                    {captionY === null ? t("captionCustom") : t("captionReset")}
                  </Button>
                </div>
                {captionY !== null && (
                  <Slider value={[captionY * 100]} min={10} max={90} step={1} onValueChange={(v) => setCaptionY(v[0] / 100)} aria-label={t("captionLabel")} />
                )}
              </div>
            </div>
          </section>

          <aside className="space-y-3">
            <p className="text-sm font-medium">{t("outputPreview")}</p>
            <canvas ref={preview} width={PREVIEW_W} height={Math.round((PREVIEW_W * OUT_H) / OUT_W)} className="rounded-lg border bg-black" aria-label={t("outputPreview")} />
            <div className="space-y-2">
              <Label htmlFor="layout-name">{t("nameLabel")}</Label>
              <Input id="layout-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={t("namePlaceholder")} />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={!name.trim() || saving} onClick={() => void save(false)}>{editingId ? t("update") : t("save")}</Button>
                {editingId && <Button size="sm" variant="outline" disabled={!name.trim() || saving} onClick={() => void save(true)}>{t("saveAsNew")}</Button>}
              </div>
            </div>
          </aside>
        </div>
      ) : (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t("noFrame")}</p>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">{t("mySaved")}</h2>
        {saved.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noSaved")}</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {saved.map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <button type="button" className="truncate text-left text-sm hover:underline" onClick={() => loadLayout(item)}>
                  {item.name}
                </button>
                <span className="shrink-0 text-xs text-muted-foreground">{t("panelsCount", { count: item.spec.panels.length })}</span>
                <Button size="icon" variant="ghost" aria-label={t("delete", { name: item.name })} onClick={() => void remove(item.id)}><Trash2 className="size-4" /></Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
