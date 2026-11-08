"""Unfair information is confined to the separate agent2 oracle harness."""

import hashlib
from pathlib import Path

import pytest

from game import Game, make_deal
from tools.oracle_judge.privileges import information
from tools.oracle_judge.engine import HttpAgentHandle, OracleAgentHandle
from game import AgentConfig

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_JUDGE_SHA256 = "fa7a7e3fb49c09588cfcf0930a8e3f6c189e419dbc54263ae7d53b953223d422"


def test_real_judge_is_byte_identical_to_original():
    assert hashlib.sha256((ROOT / "judge_engine.py").read_bytes()).hexdigest() == ORIGINAL_JUDGE_SHA256


@pytest.mark.parametrize("seat", [0, 1])
def test_oracle_information_is_exactly_scoped_and_never_changes_the_game(seat, tmp_path):
    game = Game(make_deal("oracle-scope", 0), 0)
    before = game.observation(seat).to_dict()
    full = information(game, seat, "oracle_full", None)
    partial = information(game, seat, "oracle_partial", None)
    board = information(game, seat, "board_oracle", None)
    assert set(full) == {"kind", "opponent_hole"}
    assert full["opponent_hole"] == list(game.deal.hole_cards[1-seat])
    assert partial["opponent_hole"] == list(game.deal.hole_cards[1-seat][:2])
    assert set(board) == {"kind", "next_board_card"}
    assert board["next_board_card"] == game.deal.board[0]
    assert information(game, seat, "unlimited_compute", None) == {"kind": "unlimited_compute"}
    assert game.observation(seat).to_dict() == before


def test_oracle_counter_reads_only_explicit_harness_file_and_validates_hand(tmp_path):
    game = Game(make_deal("counter-scope", 0), 0, hand_index=7)
    state = tmp_path / "target.json"
    state.write_text('{"hand_index":7,"gear":"VALUE","events":{"raises":20}}')
    assert information(game, 1, "oracle_counter", state)["target_state"]["gear"] == "VALUE"
    # Before Jester's first decision in a new hand, its latest actual model
    # can still belong to the previous hand (results are normally batched).
    state.write_text('{"hand_index":6,"gear":"TRAP"}')
    assert information(game,1,"oracle_counter",state)["target_state"]["gear"]=="TRAP"
    state.write_text('{"hand_index":8,"gear":"MANIAC"}')
    assert information(game, 1, "oracle_counter", state)["target_state"] is None
    with pytest.raises(ValueError):
        information(game, 1, "unknown", state)


def test_only_oracle_handle_adds_privilege_and_only_compute_handle_changes_bank(monkeypatch):
    sent = []
    monkeypatch.setattr(HttpAgentHandle, "_post", lambda self, label, path, body: sent.append(body))
    ordinary = HttpAgentHandle("http://localhost:5008", AgentConfig())
    oracle = OracleAgentHandle("http://localhost:5009", AgentConfig(), kind="oracle_full")
    compute = OracleAgentHandle("http://localhost:5010", AgentConfig(), kind="unlimited_compute")
    original = {"observation": {"hand_index": 0}, "hand_results": []}
    oracle.extra = {"opponent_hole": [1, 2, 3, 4, 5]}
    ordinary._post("choose_action", "/act", original)
    # Call the override explicitly because the base method is mocked.
    OracleAgentHandle._post(oracle, "choose_action", "/act", original)
    assert sent[0] == original and "oracle" not in sent[0]
    assert sent[1]["oracle"] == oracle.extra and "oracle" not in original
    assert ordinary.config.time_bank_seconds == oracle.config.time_bank_seconds == 8
    assert compute.config.time_bank_seconds >= 1000000


def test_copied_judge_preserves_duplicate_deals_and_scoring_for_same_actions():
    import judge_engine as real
    from tools.oracle_judge import engine as oracle
    class Fixed:
        def __init__(self):
            self.stats=real.AgentStats()
            self.config=AgentConfig(num_hands=20)
        def start_half(self):self.stats=real.AgentStats()
        def act(self,obs):
            assert "oracle" not in obs.to_dict()
            from game import Action
            return Action.CHECK_CALL
        def hand_end(self,result):pass
        def flush_hand_results(self):pass
        def describe(self):return "fixed"
    class FixedOracle(oracle.OracleAgentHandle):
        def start_half(self):self.stats=oracle.AgentStats()
        def act(self,obs):
            assert len(self.extra["opponent_hole"])==5
            from game import Action
            return Action.CHECK_CALL
        def hand_end(self,result):pass
        def flush_hand_results(self):pass
    privileged=FixedOracle("http://localhost:1",AgentConfig(num_hands=20),kind="oracle_full")
    expected=real.play_match(Fixed(),Fixed(),"judge-integrity",20).to_dict()
    actual=oracle.play_match(Fixed(),privileged,"judge-integrity",20).to_dict()
    for key in ("paired_bb","half_totals_chips","ci","verdict","points"):
        assert actual[key]==expected[key]


def test_oracle_observer_keeps_snapshot_imports_and_never_exports_private_cards():
    import os,subprocess,sys,tempfile,json
    source=ROOT/"league/champions/v2"
    with tempfile.TemporaryDirectory(prefix="oracle-contract-",dir="/tmp") as directory:
        channel=Path(directory)/"state.json"
        code='''
import json
from pathlib import Path
from tools import serve_oracle_target as observer
from game import AgentConfig,Game,make_deal
import bot.fallback
memory={}
observer.agent.new_half(AgentConfig(),memory)
game=Game(make_deal("oracle-observer",0),0)
observer.agent.choose_action(game.observation(game.to_act),memory)
print(json.dumps({"agent":observer.agent.__file__,"fallback":bot.fallback.__file__}))
'''
        result=subprocess.check_output([sys.executable,"-B","-c",code],cwd=ROOT,text=True,
            env=dict(os.environ,BOT_SOURCE_ROOT=str(source),ORACLE_STATE_PATH=str(channel),PORT="5020"))
        paths=json.loads(result.strip().splitlines()[-1])
        assert all(Path(value).is_relative_to(source) for value in paths.values())
        data=json.loads(channel.read_text())
        assert data["whole"] is not None and data["current_hand"] is not None
        assert not any(word in channel.read_text() for word in ('"hole_cards"','"hole"','"board"','"rng"'))
