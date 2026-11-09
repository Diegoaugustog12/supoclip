"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowDownUp, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { frameFromFile } from "@/lib/video-frame";
import {
  type CaptionStyle,
  type Crop,
  type Fit,
  type LayoutSpec,
  type PanelCount,
  type TitleStyle,
  OUT_H,
  OUT_W,
  buildSpec,
  fitCrop,
  fromSpec,
  moveCrop,
  panelHeights,
  panelRatio,
  resizeCrop,
  resizeFree,
} from "@/lib/layout-spec";

type Saved = { id: string; name: string; spec: LayoutSpec };
type Frame = { src: string; aspect: number; image: HTMLImageElement };
type Drag = { index: number; mode: "move" | "resize"; startX: number; startY: number; crop: Crop };

const PANEL_COLORS = ["#22c55e", "#3b82f6"];
const PREVIEW_W = 300;
const CAPTION_ANIMATIONS = ["none", "karaoke", "pop", "fade", "bounce", "flicker", "glitch", "typewriter"] as const;
const TITLE_ANIMATIONS = ["fade", "pop", "none"] as const;
const SAMPLE_WORDS = ["this", "is", "how", "your", "captions", "will", "look", "here"];

type FontInfo = { name: string; display_name: string; format?: string };
type TemplateInfo = { id: string; name: string; font_family: string; font_size: number };

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
  const [source, setSource] = useState<"link" | "file">("link");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [time, setTime] = useState("30");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [loadingFrame, setLoadingFrame] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [count, setCount] = useState<PanelCount>(2);
  const [firstShare, setFirstShare] = useState(0.35);
  const [crops, setCrops] = useState<Crop[]>([]);
  const [fits, setFits] = useState<Fit[]>(["cover", "cover"]);
  const [captionY, setCaptionY] = useState<number | null>(null);
  const [caption, setCaption] = useState<CaptionStyle>({});
  const [title, setTitle] = useState<TitleStyle>({});
  const [fonts, setFonts] = useState<FontInfo[]>([]);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
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

  // Fonts and caption templates for the style controls; fonts are also loaded so the preview text uses them.
  useEffect(() => {
    fetch("/api/fonts", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : { fonts: [] }))
      .then((body) => {
        const list: FontInfo[] = Array.isArray(body.fonts) ? body.fonts : [];
        setFonts(list);
        const style = document.createElement("style");
        style.id = "layout-editor-fonts";
        style.textContent = list.map((font) => `@font-face { font-family: '${font.name}'; src: url('/api/fonts/${font.name}') format('${font.format === "otf" ? "opentype" : "truetype"}'); }`).join("\n");
        document.getElementById("layout-editor-fonts")?.remove();
        document.head.appendChild(style);
      })
      .catch(() => setFonts([]));
    fetch("/api/caption-templates", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : { templates: [] }))
      .then((body) => setTemplates(Array.isArray(body.templates) ? body.templates : []))
      .catch(() => setTemplates([]));
  }, []);
  const [fontsReady, setFontsReady] = useState(0);
  const familyFor = useCallback((choice?: string) => choice || templates.find((item) => item.id === (caption.template ?? "default"))?.font_family || "sans-serif", [caption.template, templates]);
  useEffect(() => {
    const families = [familyFor(caption.font), title.font ? familyFor(title.font) : familyFor(caption.font)];
    void Promise.all(families.map((family) => document.fonts.load(`40px "${family}"`).catch(() => [])))
      .then(() => setFontsReady((n) => n + 1));
  }, [caption.font, caption.template, title.font, familyFor]);

  // Re-fit every crop to its panel's shape when the split, count or frame changes.
  useEffect(() => {
    if (!frame) return;
    setCrops((current) => {
      const starts = current.length ? current : [
        { x: 0.68, y: 0.58, w: 0.3, h: 0 },
        { x: 0, y: 0, w: 1, h: 0 },
      ];
      return [0, 1].map((i) => fitCrop(starts[i] ?? starts[0], panelRatio(heights[i] ?? heights[0]), aspect, fits[i]));
    });
  }, [frame, heights, aspect, fits]);

  // The 9:16 result, drawn from the same crops the render will use.
  const live = useRef<HTMLVideoElement | null>(null);
  const paint = useCallback(() => {
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
      const video = live.current;
      const image: CanvasImageSource = video ?? frame.image;
      const nw = video ? video.videoWidth : frame.image.naturalWidth;
      const nh = video ? video.videoHeight : frame.image.naturalHeight;
      const source = [crop.x * nw, crop.y * nh, crop.w * nw, crop.h * nh] as const;
      if (fits[i] === "contain") {
        // Blurred copy filling the panel, then the whole crop scaled to fit.
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, y, PREVIEW_W, h);
        ctx.clip();
        const cover = Math.max(PREVIEW_W / source[2], h / source[3]);
        ctx.filter = "blur(6px)";
        ctx.drawImage(image, ...source, (PREVIEW_W - source[2] * cover) / 2, y + (h - source[3] * cover) / 2, source[2] * cover, source[3] * cover);
        ctx.filter = "none";
        const contain = Math.min(PREVIEW_W / source[2], h / source[3]);
        ctx.drawImage(image, ...source, (PREVIEW_W - source[2] * contain) / 2, y + (h - source[3] * contain) / 2, source[2] * contain, source[3] * contain);
        ctx.restore();
      } else {
        ctx.drawImage(image, ...source, 0, y, PREVIEW_W, h);
      }
      y += h;
    });
    const lineY = (captionY ?? (count === 2 ? heights[0] / OUT_H : 0.8)) * canvas.height;
    const drawText = (text: string, family: string, px: number, centreY: number, maxWidth: number) => {
      ctx.font = `${px}px "${family}", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const fit = Math.min(1, maxWidth / Math.max(1, ctx.measureText(text).width));
      ctx.font = `${Math.max(6, px * fit)}px "${family}", sans-serif`;
      ctx.lineJoin = "round";
      ctx.lineWidth = Math.max(2, px / 5);
      ctx.strokeStyle = "#000";
      ctx.strokeText(text, PREVIEW_W / 2, centreY);
      ctx.fillStyle = "#fff";
      ctx.fillText(text, PREVIEW_W / 2, centreY);
    };
    const template = templates.find((item) => item.id === (caption.template ?? "default"));
    const margin = caption.margin ?? 0.06;
    const sample = SAMPLE_WORDS.slice(0, caption.max_words ?? 4).join(" ");
    const capPx = ((caption.size ?? template?.font_size ?? 30) * PREVIEW_W) / 560;
    drawText(caption.uppercase ? sample.toUpperCase() : sample, familyFor(caption.font), capPx, lineY, PREVIEW_W * (1 - 2 * margin));
    ctx.strokeStyle = "rgba(250, 204, 21, 0.7)";
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    [margin, 1 - margin].forEach((fraction) => {
      ctx.beginPath();
      ctx.moveTo(fraction * PREVIEW_W, lineY - capPx);
      ctx.lineTo(fraction * PREVIEW_W, lineY + capPx);
      ctx.stroke();
    });
    ctx.setLineDash([]);
    if (title.enabled !== false) {
      const titlePx = ((title.size ?? 70) * PREVIEW_W) / OUT_W;
      drawText("Example headline", familyFor(title.font ?? caption.font), titlePx, (title.y ?? 0.09) * canvas.height, PREVIEW_W * 0.88);
    }
  }, [frame, crops, heights, count, captionY, caption, title, templates, familyFor, fontsReady, fits]);
  useEffect(() => { paint(); }, [paint]);

  // Plays 5 seconds of the chosen file through the same crops, so motion can be judged.
  const [playing, setPlaying] = useState(false);
  async function playClip() {
    if (playing || (source === "file" ? !file : !url.trim())) return;
    setPlaying(true);
    const video = document.createElement("video");
    let objectUrl = "";
    try {
      if (source === "file" && file) {
        objectUrl = URL.createObjectURL(file);
      } else {
        const response = await fetch("/api/layouts/preview-clip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url.trim(), time: Number(time) || 0 }),
        });
        if (!response.ok) throw new Error(await errorText(response, t("previewError")));
        objectUrl = URL.createObjectURL(await response.blob());
      }
    } catch (error) {
      setFrameError(error instanceof Error ? error.message : t("previewError"));
      setPlaying(false);
      return;
    }
    const fromFile = source === "file";
    video.src = objectUrl;
    video.muted = true;
    video.playsInline = true;
    try {
      await new Promise<void>((resolve, reject) => {
        video.onloadedmetadata = () => resolve();
        video.onerror = () => reject(new Error(t("fileError")));
      });
      if (fromFile) {
        video.currentTime = Number(time) || 0;
        await new Promise<void>((resolve) => { video.onseeked = () => resolve(); });
      }
      live.current = video;
      await video.play();
      const end = video.currentTime + 5;
      await new Promise<void>((resolve) => {
        const tick = () => {
          paint();
          if (video.ended || video.currentTime >= end) resolve();
          else requestAnimationFrame(tick);
        };
        tick();
      });
    } catch (error) {
      setFrameError(error instanceof Error ? error.message : t("fileError"));
    } finally {
      video.pause();
      live.current = null;
      URL.revokeObjectURL(objectUrl);
      setPlaying(false);
      paint();
    }
  }

  async function loadFrame() {
    setLoadingFrame(true);
    setFrameError(null);
    try {
      let blob: Blob;
      if (source === "file") {
        // Read in the browser: the file never leaves this computer.
        if (!file) return;
        try {
          blob = await frameFromFile(file, Number(time) || 0);
        } catch {
          throw new Error(t("fileError"));
        }
      } else {
        const response = await fetch("/api/layouts/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url.trim(), time: Number(time) || 0 }),
        });
        if (!response.ok) throw new Error(await errorText(response, t("previewError")));
        blob = await response.blob();
      }
      const src = URL.createObjectURL(blob);
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
      if (active.mode === "move") return moveCrop(active.crop, dx, dy);
      return fits[i] === "contain"
        ? resizeFree(active.crop, active.crop.w + dx, active.crop.h + dy)
        : resizeCrop(active.crop, active.crop.w + dx, panelRatio(heights[i]), aspect);
    }));
  }

  const stopDrag = () => { drag.current = null; };

  function swapPanels() {
    const swappedFits: Fit[] = [fits[1], fits[0]];
    setFits(swappedFits);
    setCrops((current) => [current[1], current[0]].map((crop, i) => fitCrop(crop, panelRatio(heights[i]), aspect, swappedFits[i])));
  }

  function loadLayout(item: Saved) {
    const state = fromSpec(item.spec);
    setCount(state.count);
    setFirstShare(state.firstShare);
    setCrops(state.crops);
    setFits([state.fits[0] ?? "cover", state.fits[1] ?? "cover"]);
    setCaptionY(state.captionY);
    setCaption(state.caption);
    setTitle(state.title);
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
        body: JSON.stringify({ name: name.trim(), spec: buildSpec(count, firstShare, crops, captionY, caption, title, fits) }),
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
        <div className="flex gap-2" role="radiogroup" aria-label={t("sourceLabel")}>
          {(["link", "file"] as const).map((kind) => (
            <Button key={kind} type="button" role="radio" aria-checked={source === kind} variant={source === kind ? "default" : "outline"} size="sm" onClick={() => setSource(kind)}>
              {kind === "link" ? t("sourceLink") : t("sourceFile")}
            </Button>
          ))}
        </div>
        <Label htmlFor={source === "link" ? "layout-url" : "layout-file"}>{source === "link" ? t("urlLabel") : t("fileLabel")}</Label>
        <div className="flex flex-wrap gap-2">
          {source === "link" ? (
            <Input id="layout-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("urlPlaceholder")} className="min-w-64 flex-1" />
          ) : (
            <Input id="layout-file" type="file" accept="video/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="min-w-64 flex-1" />
          )}
          <Input type="number" min={0} aria-label={t("timeLabel")} value={time} onChange={(e) => setTime(e.target.value)} className="w-24" />
          <Button onClick={() => void loadFrame()} disabled={(source === "link" ? !url.trim() : !file) || loadingFrame}>
            {loadingFrame ? t("loading") : t("loadPreview")}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">{source === "link" ? t("timeHint") : t("fileHint")}</p>
        {frameError && <p role="alert" className="text-sm text-destructive">{frameError}</p>}
      </section>

      {frame || editingId ? (
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
              {frame ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={frame.src} alt={t("frameAlt")} className="pointer-events-none size-full object-fill" draggable={false} />
              ) : (
                <p className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-muted-foreground">{t("noFrame")}</p>
              )}
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
                {[0, 1].slice(0, count).map((i) => (
                  <label key={i} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={fits[i] === "contain"}
                      onChange={(e) => {
                        const next: Fit = e.target.checked ? "contain" : "cover";
                        setFits((current) => current.map((value, index) => (index === i ? next : value)));
                        // Showing everything starts from the whole frame, which the user then trims.
                        if (next === "contain") setCrops((current) => current.map((crop, index) => (index === i ? { x: 0, y: 0, w: 1, h: 1 } : crop)));
                      }}
                    />
                    <span>{t("showWhole", { panel: labels[i] })}</span>
                  </label>
                ))}
                <p className="text-xs text-muted-foreground">{t("showWholeHint")}</p>
              </div>
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

            <fieldset className="space-y-4 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <legend className="text-sm font-semibold">{t("captionSection")}</legend>
                <Button type="button" variant="ghost" size="sm" onClick={() => setCaption({})}>{t("resetStyle")}</Button>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1 text-sm">
                  <span>{t("template")}</span>
                  <select className="h-9 w-full rounded-md border bg-background px-2" value={caption.template ?? ""} onChange={(e) => setCaption({ ...caption, template: e.target.value || undefined })}>
                    <option value="">{t("defaultOption")}</option>
                    {templates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span>{t("font")}</span>
                  <select className="h-9 w-full rounded-md border bg-background px-2" value={caption.font ?? ""} onChange={(e) => setCaption({ ...caption, font: e.target.value || undefined })}>
                    <option value="">{t("defaultOption")}</option>
                    {fonts.map((font) => <option key={font.name} value={font.name}>{font.display_name || font.name}</option>)}
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span>{t("animation")}</span>
                  <select className="h-9 w-full rounded-md border bg-background px-2" value={caption.animation ?? ""} onChange={(e) => setCaption({ ...caption, animation: e.target.value || undefined })}>
                    <option value="">{t("defaultOption")}</option>
                    {CAPTION_ANIMATIONS.map((id) => <option key={id} value={id}>{t(`animationNames.${id}`)}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={caption.uppercase === true} onChange={(e) => setCaption({ ...caption, uppercase: e.target.checked ? true : undefined })} />
                  <span>{t("uppercase")}</span>
                </label>
                <div className="space-y-2">
                  <Label>{t("sizeLabel", { value: caption.size ?? templates.find((i) => i.id === (caption.template ?? "default"))?.font_size ?? 30 })}</Label>
                  <Slider value={[caption.size ?? templates.find((i) => i.id === (caption.template ?? "default"))?.font_size ?? 30]} min={12} max={72} step={1} onValueChange={(v) => setCaption({ ...caption, size: v[0] })} aria-label={t("sizeLabel", { value: caption.size ?? 30 })} />
                </div>
                <div className="space-y-2">
                  <Label>{t("maxWordsLabel", { value: caption.max_words ?? 4 })}</Label>
                  <Slider value={[caption.max_words ?? 4]} min={1} max={8} step={1} onValueChange={(v) => setCaption({ ...caption, max_words: v[0] })} aria-label={t("maxWordsLabel", { value: caption.max_words ?? 4 })} />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>{t("marginLabel", { percent: Math.round((caption.margin ?? 0.06) * 100) })}</Label>
                  <Slider value={[(caption.margin ?? 0.06) * 100]} min={2} max={20} step={1} onValueChange={(v) => setCaption({ ...caption, margin: v[0] / 100 })} aria-label={t("marginLabel", { percent: Math.round((caption.margin ?? 0.06) * 100) })} />
                </div>
              </div>
            </fieldset>

            <fieldset className="space-y-4 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <legend className="text-sm font-semibold">{t("titleSection")}</legend>
                <Button type="button" variant="ghost" size="sm" onClick={() => setTitle({})}>{t("resetStyle")}</Button>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={title.enabled !== false} onChange={(e) => setTitle({ ...title, enabled: e.target.checked ? undefined : false })} />
                <span>{t("titleEnabled")}</span>
              </label>
              {title.enabled !== false && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="space-y-1 text-sm">
                    <span>{t("font")}</span>
                    <select className="h-9 w-full rounded-md border bg-background px-2" value={title.font ?? ""} onChange={(e) => setTitle({ ...title, font: e.target.value || undefined })}>
                      <option value="">{t("defaultOption")}</option>
                      {fonts.map((font) => <option key={font.name} value={font.name}>{font.display_name || font.name}</option>)}
                    </select>
                  </label>
                  <label className="space-y-1 text-sm">
                    <span>{t("animation")}</span>
                    <select className="h-9 w-full rounded-md border bg-background px-2" value={title.animation ?? ""} onChange={(e) => setTitle({ ...title, animation: (e.target.value || undefined) as TitleStyle["animation"] })}>
                      <option value="">{t("defaultOption")}</option>
                      {TITLE_ANIMATIONS.map((id) => <option key={id} value={id}>{t(`animationNames.${id}`)}</option>)}
                    </select>
                  </label>
                  <div className="space-y-2">
                    <Label>{t("titleYLabel", { percent: Math.round((title.y ?? 0.09) * 100) })}</Label>
                    <Slider value={[(title.y ?? 0.09) * 100]} min={5} max={90} step={1} onValueChange={(v) => setTitle({ ...title, y: v[0] / 100 })} aria-label={t("titleYLabel", { percent: Math.round((title.y ?? 0.09) * 100) })} />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("titleSizeLabel", { value: title.size ?? 70 })}</Label>
                    <Slider value={[title.size ?? 70]} min={24} max={120} step={1} onValueChange={(v) => setTitle({ ...title, size: v[0] })} aria-label={t("titleSizeLabel", { value: title.size ?? 70 })} />
                  </div>
                </div>
              )}
              <p className="text-xs text-muted-foreground">{t("titleHint")}</p>
            </fieldset>
          </section>

          <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
            <p className="text-sm font-medium">{t("outputPreview")}</p>
            <Button size="sm" variant="outline" disabled={playing || (source === "file" ? !file : !url.trim())} onClick={() => void playClip()}>{playing ? t("playing") : t("playClip")}</Button>
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
