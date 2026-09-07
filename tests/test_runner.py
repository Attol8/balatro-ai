import json
from copy import deepcopy

import pytest

from balatro_ai.runner import Limits, public_state, run_game, validate_response
from tests.game.state_factory import state


class Game:
    def __init__(self, *, fail=False, victory=True, profile='all_unlocked', active=False):
        self.raw = state()
        self.raw.update(deck='RED', stake='WHITE')
        self.started = False
        self.fail, self.victory, self.profile, self.active = fail, victory, profile, active
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append(method)
        if method == 'health':
            return {'profile_mode': self.profile}
        if method == 'gamestate':
            return deepcopy(self.raw) if self.started or self.active else {'state': 'MENU'}
        if method == 'start':
            self.started = True
            return deepcopy(self.raw)
        if self.fail:
            raise RuntimeError('uncertain action')
        self.raw['ante_num'] = 9 if self.victory else 8
        self.raw['won'] = True
        self.raw['state'] = 'ROUND_EVAL' if self.victory else 'GAME_OVER'
        return deepcopy(self.raw)


class Coach:
    def __init__(self, *, stale=False, timeout=False):
        self.packets=[]
        self.stale, self.timeout = stale, timeout

    def choose(self, packet, timeout):
        self.packets.append(packet)
        if self.timeout:
            raise TimeoutError('fake coach timeout')
        return {'request_id': 'stale' if self.stale else packet['request_id'],
                'action_json': '{"type":"select_blind"}', 'plan': 'Grow safely.'}


@pytest.fixture(autouse=True)
def no_poll_delay(monkeypatch):
    monkeypatch.setattr('balatro_ai.runner.time.sleep', lambda _: None)
    # Fake games must not contend with a real player in another process.
    monkeypatch.setattr('balatro_ai.runner.fcntl.flock', lambda *_: None)


def test_complete_loop_and_public_boundary(tmp_path):
    game, coach = Game(), Coach()
    result = run_game(game, coach, tmp_path/'run')
    assert result['status'] == 'won' and result['ante_reached'] == 9
    assert result['decisions'] == result['coach_requests'] == 1
    packet = json.dumps(coach.packets)
    assert 'TEST-SEED' not in packet
    assert 'seed' not in coach.packets[0]['observation']
    assert json.loads((tmp_path/'run/result.json').read_text()) == result
    trace = [json.loads(line) for line in (tmp_path/'run/trajectory.jsonl').read_text().splitlines()]
    assert [t['event'] for t in trace] == ['rpc_attempt','coach_request','coach_response','rpc_attempt','transition']


@pytest.mark.parametrize('stale,timeout', [(True,False),(False,True)])
def test_bad_coach_never_mutates(tmp_path, stale, timeout):
    game=Game()
    result=run_game(game, Coach(stale=stale,timeout=timeout),tmp_path/'run')
    assert result['status'] in {'error','stopped'}
    assert 'select' not in game.calls
    assert result['decisions'] == 0


def test_uncertain_mutation_not_retried(tmp_path):
    game=Game(fail=True)
    result=run_game(game,Coach(),tmp_path/'run')
    assert result['status']=='error'
    assert game.calls.count('select') == 1


def test_premature_won_flag_is_loss(tmp_path):
    result=run_game(Game(victory=False),Coach(),tmp_path/'run')
    assert result['status']=='lost' and not result['won']


@pytest.mark.parametrize('kwargs', [{'profile':'normal'},{'active':True}])
def test_preflight_does_not_start_existing_or_wrong_game(tmp_path,kwargs):
    game=Game(**kwargs)
    result=run_game(game,Coach(),tmp_path/'run')
    assert result['status']=='error' and 'start' not in game.calls


def test_limits_and_no_automatic_strategy(tmp_path):
    game=Game()
    def unchanged(method,params=None):
        if method == 'select':
            game.calls.append(method)
            return deepcopy(game.raw)
        return Game.rpc(game,method,params)
    game.rpc=unchanged
    result=run_game(game,Coach(),tmp_path/'run', limits=Limits(max_calls=1))
    assert result['reason']=='coach_call_limit'
    assert game.calls.count('select')==1


def test_validation_rejects_extra_action_fields_and_illegal_action():
    obs=public_state(state())
    for action in ({'type':'select_blind','extra':1}, {'type':'play_cards','cards':[0]}):
        with pytest.raises(ValueError):
            validate_response({'request_id':'a','action_json':json.dumps(action),'plan':''},'a',obs)


def test_output_not_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        run_game(Game(),Coach(),tmp_path)


def test_invalid_limits():
    for kwargs in ({'seconds':float('nan')},{'call_seconds':0},{'max_calls':False}):
        with pytest.raises(ValueError):
            Limits(**kwargs)


def test_auth_failure_precedes_game_start(tmp_path):
    class Unauthenticated(Coach):
        def preflight(self, timeout):
            assert 0 < timeout <= 10
            raise RuntimeError('ChatGPT login required')
    game=Game()
    result=run_game(game,Unauthenticated(),tmp_path/'run')
    assert result['status']=='error'
    assert 'start' not in game.calls


def test_cashout_is_only_automatic_move(tmp_path):
    game=Game()
    game.raw['state']='ROUND_EVAL'
    coach=Coach()
    result=run_game(game,coach,tmp_path/'run')
    assert result['status']=='won'
    assert not coach.packets and result['coach_requests']==0
    assert game.calls.count('cash_out')==1


def test_expired_budget_never_starts_game(tmp_path,monkeypatch):
    ticks=iter([0,2,3,4,5,6,7])
    monkeypatch.setattr('balatro_ai.runner.time.monotonic',lambda:next(ticks))
    game=Game()
    result=run_game(game,Coach(),tmp_path/'run',limits=Limits(seconds=1))
    assert result['status']=='stopped' and 'start' not in game.calls


def test_rpc_timeout_uses_remaining_game_budget(monkeypatch):
    from balatro_ai.client import BalatroBotClient
    from balatro_ai.runner import game_rpc
    seen=[]
    def post(self,payload):
        seen.append(self.timeout)
        return {'result':{}}
    monkeypatch.setattr(BalatroBotClient,'_http_post',post)
    monkeypatch.setattr('balatro_ai.runner.time.monotonic',lambda:10)
    assert game_rpc(BalatroBotClient(), 'gamestate', None, 10.25) == {}
    assert seen==[.25]


def test_explicit_continuation_never_restarts_or_replays(tmp_path):
    from balatro_ai.runner import Continuation
    game=Game(active=True)
    current=public_state(game.raw)
    saved=Continuation(current,'Retained plan',(),3,4,10,20,'previous-run')
    result=run_game(game,Coach(),tmp_path/'continued',seed=game.raw['seed'],continuation=saved)
    assert result['status']=='won'
    assert 'start' not in game.calls
    assert game.calls.count('select')==1
    assert result['decisions']==5 and result['coach_requests']==4
    assert result['seconds']>=10


def test_continuation_rejects_changed_game_before_mutation(tmp_path):
    from balatro_ai.runner import Continuation
    game=Game(active=True)
    saved=Continuation(public_state(game.raw),'',(),0,0,0,0,'previous-run')
    game.raw['money']+=1
    result=run_game(game,Coach(),tmp_path/'continued',seed=game.raw['seed'],continuation=saved)
    assert result['status']=='error'
    assert 'start' not in game.calls and 'select' not in game.calls


def test_invalid_action_is_corrected_before_any_game_mutation(tmp_path):
    class Correcting(Coach):
        def choose(self, packet, timeout):
            response=super().choose(packet,timeout)
            if len(self.packets)==1:
                response['action_json']='{"type":"play_cards","cards":[0]}'
            else:
                assert packet['validation_feedback']['error']=='coach selected an illegal action'
            return response
    game=Game()
    result=run_game(game,Correcting(),tmp_path/'run')
    assert result['status']=='won' and result['coach_requests']==2
    assert game.calls.count('select')==1 and 'play' not in game.calls


def test_unchanged_plan_preserves_full_strategy_and_recovery_log(tmp_path):
    class SamePlan(Coach):
        def choose(self,packet,timeout):
            response=super().choose(packet,timeout)
            if len(self.packets)==1:
                response['plan']='Keep the whole strategy.'
            else:
                assert packet['plan']=='Keep the whole strategy.'
                response['plan']='='
            return response
    game=Game()
    def rpc(method,params=None):
        if method=='select' and game.calls.count('select')==0:
            game.calls.append(method)
            return deepcopy(game.raw)
        return Game.rpc(game,method,params)
    game.rpc=rpc
    result=run_game(game,SamePlan(),tmp_path/'run')
    assert result['status']=='won'
    rows=[json.loads(l) for l in (tmp_path/'run/trajectory.jsonl').read_text().splitlines()]
    replies=[r for r in rows if r['event']=='coach_response']
    assert replies[-1]['plan_unchanged'] is True
    assert replies[-1]['response']['plan']=='Keep the whole strategy.'


def test_endless_continues_past_ante_eight_and_records_later_loss(tmp_path):
    game=Game(active=True)
    game.raw.update(ante_num=9,won=True,state='ROUND_EVAL')
    from balatro_ai.runner import Continuation
    saved=Continuation(public_state(game.raw),'Keep scaling.',(),0,0,0,0,'win')
    def rpc(method,params=None):
        if method=='cash_out':
            game.calls.append(method)
            game.raw['state']='GAME_OVER'
            return deepcopy(game.raw)
        return Game.rpc(game,method,params)
    game.rpc=rpc
    result=run_game(game,Coach(),tmp_path/'endless',seed=game.raw['seed'],continuation=saved,endless=True)
    assert game.calls.count('cash_out')==1
    assert result['status']=='lost' and result['reason']=='endless_game_over'
    assert result['ante_8_cleared'] is True and result['won'] is True
