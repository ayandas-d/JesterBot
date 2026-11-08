from tools.summarize_backtest import interval

def test_interval_uses_match_blocks_and_student_t():
    center, low, high = interval([1,2,3,4,5])
    assert center == 3
    assert abs((high-center) - 2.776 * (2.5/5)**.5) < 1e-10
    assert abs(center-low-(high-center)) < 1e-10

def test_single_match_cannot_estimate_between_match_uncertainty():
    assert interval([4]) == [4,None,None]
