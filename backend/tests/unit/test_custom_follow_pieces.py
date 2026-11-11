from src.media.custom_follow import _pieces


def _no_overlap(pieces):
    for (a0, b0, _, _), (a1, _, _, _) in zip(pieces, pieces[1:]):
        assert b0 <= a1 + 1e-9, pieces


def test_closing_key_without_ramp_does_not_overlap():
    keys = [(0.0, 100.0, 0.0, False), (5.0, 140.0, 0.6, False), (30.5, 140.0, 0.0, False)]
    pieces = _pieces(keys)
    _no_overlap(pieces)
    assert pieces[-1][:2] == (5.0, 30.5) and pieces[-1][2] == pieces[-1][3] == 140.0


def test_cut_and_drift_pieces_keep_order():
    keys = [(0.0, 10.0, 0.0, False), (4.0, 50.0, 0.25, True), (9.0, 60.0, 0.6, False), (12.0, 60.0, 0.0, False)]
    _no_overlap(_pieces(keys))
