import { describe, expect, it } from "vitest";

import { groupSubjects, shortenLabel } from "./subjects-view";

const clip = (id: string, order: number, meta: Record<string, unknown> = {}) => ({
  id, clip_order: order, workflow_meta: meta as never,
});

describe("subjects view", () => {
  it("lists each compilation followed by its shorter versions, shortest first", () => {
    const groups = groupSubjects([
      clip("b", 3),
      clip("a60", 2, { parent_clip_id: "a", shortened_to: 60 }),
      clip("a", 1),
      clip("a30", 4, { parent_clip_id: "a", shortened_to: 30 }),
    ]);

    expect(groups.map((group) => group.clip.id)).toEqual(["a", "b"]);
    expect(groups[0].versions.map((version) => version.id)).toEqual(["a30", "a60"]);
    expect(groups[1].versions).toEqual([]);
  });

  it("shows a version whose original is gone as a compilation of its own", () => {
    const groups = groupSubjects([clip("x", 1, { parent_clip_id: "deleted", shortened_to: 30 })]);

    expect(groups.map((group) => group.clip.id)).toEqual(["x"]);
  });

  it("labels lengths in seconds and minutes", () => {
    expect([15, 30, 60, 120].map(shortenLabel)).toEqual(["15 s", "30 s", "1 min", "2 min"]);
  });
});
