import pytest

from src.workflows import subjects
from src.workflows.errors import WorkflowError
from src.workflows.schemas import SubjectDef, SubjectDiscovery, SubjectExtraction, SubjectMoment

from workflow_planner_fakes import ScriptedModel, chapter, make_outline, plan_context, plan_input, story_data


def _moment(subject, first, last, strength=80):
    return SubjectMoment(
        subject=subject, first_unit=first, last_unit=last, strength=strength, title=f"Beat {first}", why="why"
    )


def _discovery(*labels, virality=80):
    scores = list(virality) if isinstance(virality, (list, tuple)) else [virality] * len(labels)
    return SubjectDiscovery(
        notes="",
        subjects=[
            SubjectDef(label=label, description=f"{label} moments", keywords=[], virality=score)
            for label, score in zip(labels, scores)
        ],
    )


def _setup(monkeypatch, discovery, moments_by_window):
    data = story_data(120, words_per_sentence=8)
    ctx = plan_context("subjects", data)
    pi = plan_input(ctx, make_outline(chapters=[chapter(120)]))
    calls = iter(moments_by_window)
    model = ScriptedModel(
        {
            "SubjectDiscovery": [discovery],
            "SubjectExtraction": lambda prompt: SubjectExtraction(window_notes="", moments=next(calls)),
        }
    ).install(monkeypatch)
    return pi, model


@pytest.mark.asyncio
async def test_one_compilation_per_subject_with_beats_in_source_order(monkeypatch):
    pi, model = _setup(
        monkeypatch,
        _discovery("Rage quits", "Nicknames"),
        [[_moment(1, 40, 46), _moment(1, 10, 16), _moment(2, 70, 78, 90)]],
    )

    segments, plan = await subjects.plan_subjects(pi)

    assert [s["workflow_role"] for s in segments] == ["subject", "subject"]
    assert {s["workflow_meta"]["subject"] for s in segments} == {"Rage quits", "Nicknames"}
    rage = next(s for s in segments if s["workflow_meta"]["subject"] == "Rage quits")
    starts = [m["first_unit"] for m in rage["workflow_meta"]["moments"]]
    assert starts == sorted(starts) == [10, 40]
    assert rage["max_seconds"] > sum(m["seconds"] for m in rage["workflow_meta"]["moments"])
    assert plan["workflow"] == "subjects" and plan["shorten_choices"] == [15, 30, 60, 120]
    assert model.schemas().count("SubjectDiscovery") == 1


@pytest.mark.asyncio
async def test_a_line_never_plays_in_two_subjects(monkeypatch):
    pi, _ = _setup(
        monkeypatch,
        _discovery("A", "B"),
        [[_moment(1, 10, 20, 60), _moment(2, 14, 24, 90), _moment(2, 60, 70, 70), _moment(1, 80, 90, 70)]],
    )

    segments, _ = await subjects.plan_subjects(pi)

    used = [(m["first_unit"], m["last_unit"]) for s in segments for m in s["workflow_meta"]["moments"]]
    for i, a in enumerate(used):
        for b in used[i + 1 :]:
            assert a[1] < b[0] or b[1] < a[0]
    assert (10, 20) not in used  # the weaker overlap lost


@pytest.mark.asyncio
async def test_a_subject_with_too_little_material_is_dropped(monkeypatch):
    pi, _ = _setup(monkeypatch, _discovery("Big", "Tiny"), [[_moment(1, 10, 40), _moment(2, 60, 61)]])

    segments, _ = await subjects.plan_subjects(pi)

    assert [s["workflow_meta"]["subject"] for s in segments] == ["Big"]


@pytest.mark.asyncio
async def test_nothing_usable_is_subjects_not_found(monkeypatch):
    pi, _ = _setup(monkeypatch, _discovery("A"), [[_moment(1, 10, 20, 30)]])

    with pytest.raises(WorkflowError) as error:
        await subjects.plan_subjects(pi)

    assert error.value.code == "subjects_not_found"


def test_weak_and_out_of_window_moments_do_not_pass_the_gate():
    data = story_data(60, words_per_sentence=8)
    ctx = plan_context("subjects", data)
    index = plan_input(ctx, make_outline(chapters=[chapter(60)])).index
    window = list(range(1, 31))

    beats = subjects.gate_beats(
        index, [_moment(1, 5, 12, 30), _moment(1, 5, 12, 80), _moment(1, 40, 50, 80), _moment(3, 5, 12, 80)], window, 2, {}
    )

    assert [(b.first, b.last) for b in beats] == [(5, 12)]


def test_shorten_keeps_the_strongest_beats_in_source_order():
    moments = [
        {"range": [10, 30], "strength": 50, "seconds": 20},
        {"range": [100, 115], "strength": 90, "seconds": 15},
        {"range": [200, 215], "strength": 70, "seconds": 15},
    ]

    assert subjects.shorten_ranges(moments, 30) == [[100.0, 115.0], [200.0, 215.0]]
    assert subjects.shorten_ranges(moments, 15) == [[100.0, 115.0]]
    assert subjects.shorten_ranges([], 30) == []


def test_shorten_cuts_a_single_long_beat_to_its_opening():
    result = subjects.shorten_ranges([{"range": [0, 100], "strength": 80, "seconds": 100}], 30)

    assert result == [[0.0, 30.0]]


def test_output_windows_map_source_beats_onto_the_clip_timeline():
    ranges = [(10.0, 20.0), (50.0, 60.0), (100.0, 110.0)]
    offsets = [0.0, 10.0, 20.0]

    assert subjects.output_windows(ranges, offsets, [[52.0, 58.0]]) == [(12.0, 18.0)]
    # A beat across two source ranges plays as one joined window when they touch on the clip.
    assert subjects.output_windows(ranges, offsets, [[15.0, 55.0]]) == [(5.0, 15.0)]
    assert subjects.output_windows(ranges, offsets, [[105.0, 110.0], [10.0, 12.0]]) == [(0.0, 2.0), (25.0, 30.0)]
    assert subjects.output_windows(ranges, offsets, [[200.0, 210.0]]) == []


@pytest.mark.asyncio
async def test_subjects_come_out_most_viral_first_and_weak_ones_are_dropped(monkeypatch):
    pi, _ = _setup(
        monkeypatch,
        _discovery("Calm", "Wild", "Dull", virality=(60, 95, 20)),
        [[_moment(1, 10, 40, 70), _moment(2, 50, 80, 70), _moment(3, 90, 115, 70)]],
    )

    segments, plan = await subjects.plan_subjects(pi)

    assert [s["workflow_meta"]["subject"] for s in segments] == ["Wild", "Calm"]
    assert [item["virality"] for item in plan["subjects"]] == [95, 60]


def test_the_editing_style_steers_the_prompts_and_auto_adds_nothing():
    data = story_data(30)
    outline = make_outline(chapters=[chapter(30)])

    humor = plan_input(plan_context("subjects", data, advanced={"style": "humor"}), outline)
    plain = plan_input(plan_context("subjects", data), outline)

    assert "comedy" in humor.instructions.lower()
    assert plain.instructions == ""


def _windowed(monkeypatch, fail):
    """A plan input over six windows whose model fails for the windows ``fail`` picks."""
    data = story_data(300, words_per_sentence=8)
    pi = plan_input(plan_context("subjects", data), make_outline(chapters=[chapter(300)]))
    windows = subjects.pack_windows(pi.index, [(1, len(pi.index))], 150.0)
    ScriptedModel({}).install(monkeypatch)

    async def fake_run(agent, prompt, **kwargs):
        first = int(prompt.split("#")[1].split()[0])
        if fail(first, windows):
            raise RuntimeError("provider down")
        from types import SimpleNamespace

        return SimpleNamespace(output=SubjectExtraction(window_notes="", moments=[]))

    monkeypatch.setattr(subjects, "run", fake_run)
    return pi, windows


@pytest.mark.asyncio
async def test_a_single_failing_window_is_skipped_with_a_note(monkeypatch):
    pi, windows = _windowed(monkeypatch, lambda first, windows: first == windows[0][0])
    assert len(windows) >= 5

    read = await subjects._extract(pi, _discovery("A").subjects, windows)

    assert len(read) == len(windows) - 1
    assert any(note["code"] == "SUBJECTS_WINDOWS_SKIPPED" for note in pi.notes)


@pytest.mark.asyncio
async def test_most_windows_failing_means_the_video_was_not_read(monkeypatch):
    pi, windows = _windowed(monkeypatch, lambda first, windows: True)

    with pytest.raises(WorkflowError) as error:
        await subjects._extract(pi, _discovery("A").subjects, windows)

    assert error.value.code == "analysis_incomplete"


@pytest.mark.asyncio
async def test_discovery_falls_back_to_the_outline_when_the_full_transcript_keeps_failing(monkeypatch):
    from types import SimpleNamespace

    pi, _ = _setup(monkeypatch, _discovery("A"), [[]])
    monkeypatch.setattr(subjects, "DISCOVER_BACKOFF_SECONDS", 0.0)
    prompts = []

    async def fake_run(agent, prompt, **kwargs):
        prompts.append(prompt)
        if "<transcript>" in prompt:
            raise RuntimeError("503")
        return SimpleNamespace(output=_discovery("A"))

    monkeypatch.setattr(subjects, "run", fake_run)

    discovery = await subjects._discover(pi)

    assert [s.label for s in discovery.subjects] == ["A"]
    assert "<transcript>" not in prompts[-1] and len(prompts) == subjects.DISCOVER_ATTEMPTS + 1
    assert "SUBJECTS_DISCOVERED_FROM_OUTLINE" in pi.stats.fallbacks


@pytest.mark.asyncio
async def test_discovery_that_always_fails_is_plan_failed(monkeypatch):
    pi, _ = _setup(monkeypatch, _discovery("A"), [[]])
    monkeypatch.setattr(subjects, "DISCOVER_BACKOFF_SECONDS", 0.0)

    async def fake_run(agent, prompt, **kwargs):
        raise RuntimeError("503")

    monkeypatch.setattr(subjects, "run", fake_run)

    with pytest.raises(WorkflowError) as error:
        await subjects._discover(pi)

    assert error.value.code == "plan_failed"


def test_recommend_shorten_follows_the_style():
    moments = [
        {"range": [0.0, 20.0], "strength": 95, "seconds": 20.0},
        {"range": [100.0, 120.0], "strength": 20, "seconds": 20.0},
        {"range": [200.0, 220.0], "strength": 20, "seconds": 20.0},
        {"range": [300.0, 320.0], "strength": 20, "seconds": 20.0},
    ]

    # One peak holds most of the weight: comedy is fine with a 30 s copy, drama wants the build-up.
    assert subjects.recommend_shorten(moments, "humor") == 30
    assert subjects.recommend_shorten(moments, "drama") == 60
    assert subjects.recommend_shorten([{"range": [0.0, 10.0], "strength": 80, "seconds": 10.0}], "humor") is None


def test_stored_subject_clips_get_a_suggestion_on_read():
    from src.repositories.clip_repository import _workflow_meta

    moments = [
        {"range": [0.0, 20.0], "strength": 95, "seconds": 20.0},
        {"range": [100.0, 120.0], "strength": 20, "seconds": 20.0},
        {"range": [200.0, 220.0], "strength": 20, "seconds": 20.0},
    ]
    meta = _workflow_meta({"subject": "Raiva", "moments": moments, "style": "humor"})
    assert meta["recommended_shorten"] == 15
    assert "recommended_shorten" not in _workflow_meta({"subject": "Raiva", "moments": moments, "shortened_to": 30})
    assert _workflow_meta(None) == {}
