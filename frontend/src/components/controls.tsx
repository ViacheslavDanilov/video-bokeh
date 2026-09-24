"use client";

import type { SceneParams } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

const SIZES = [256, 512, 1024];
const OBJECT_COUNTS = [1, 2, 3, 4, 5, 6, 7, 8];

function CountSelect({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))}>
      <SelectTrigger id={id} aria-label={label} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {OBJECT_COUNTS.map((n) => (
          <SelectItem key={n} value={String(n)}>
            {n}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function Controls({
  params,
  onChange,
  onGenerate,
  busy,
  disabled,
}: {
  params: SceneParams;
  onChange: (next: SceneParams) => void;
  onGenerate: () => void;
  busy: boolean;
  disabled: boolean;
}) {
  const set = <K extends keyof SceneParams>(key: K, value: SceneParams[K]) =>
    onChange({ ...params, [key]: value });

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(e) => {
        e.preventDefault();
        onGenerate();
      }}
    >
      <div className="space-y-2">
        <Label htmlFor="seed">Seed</Label>
        <Input
          id="seed"
          type="number"
          className="font-mono"
          min={0}
          // Past this the field emits exponent notation and the server answers with
          // its own integer-parser error, which means nothing to a reader.
          max={999_999_999}
          value={params.seed}
          onChange={(e) => set("seed", Number(e.target.value))}
        />
      </div>

      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <Label htmlFor="frames">Frames</Label>
          <span className="text-muted-foreground font-mono text-xs">
            {params.frames}
          </span>
        </div>
        <Slider
          id="frames"
          aria-label="Frames"
          min={8}
          max={240}
          step={8}
          value={[params.frames]}
          onValueChange={([v]) => set("frames", v)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="size">Size</Label>
        <Select
          value={String(params.size)}
          onValueChange={(v) => set("size", Number(v))}
        >
          <SelectTrigger id="size" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SIZES.map((s) => (
              <SelectItem key={s} value={String(s)}>
                {s} &times; {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="objects-min">Objects</Label>
        <div className="flex items-center gap-2">
          <CountSelect
            id="objects-min"
            label="Fewest objects"
            value={params.n_objects_min}
            onChange={(min) =>
              onChange({
                ...params,
                n_objects_min: min,
                n_objects_max: Math.max(min, params.n_objects_max),
              })
            }
          />
          <span className="text-muted-foreground text-sm">to</span>
          <CountSelect
            id="objects-max"
            label="Most objects"
            value={params.n_objects_max}
            onChange={(max) =>
              onChange({
                ...params,
                n_objects_max: max,
                n_objects_min: Math.min(max, params.n_objects_min),
              })
            }
          />
        </div>
        <p className="text-muted-foreground text-xs leading-relaxed">
          The seed picks a count in this range. Past five, scenes get harder to
          place without overlap and some seeds are refused.
        </p>
      </div>

      <Button type="submit" disabled={busy || disabled}>
        {busy ? "Generating" : "Generate scene"}
      </Button>
    </form>
  );
}
