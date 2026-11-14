"""Running a key press: the fast lane, the slow lane for actions that wait, and double taps."""
import contextlib
import json
import threading
import time

import ha_keys

BLOCKING_ACTIONS = ('shell', 'http', 'delay')  # run on the slow lane so key input stays responsive
DOUBLE_PRESS_SECONDS = 0.35  # a key with double_actions waits this long for a second tap


def action_list_name(hold, double=False):
    return 'hold_actions' if hold else 'double_actions' if double else 'actions'


class PressMixin:
    """Methods of the Daemon; they use its state."""

    def give_feedback(self, button_id, ok):
        """Tell the panel how a press went. A dimmed panel stays dim: it only gets the flash, not a wake."""
        panel = self.panel  # the main loop sets it to None on a reconnect without the state lock
        if panel is not None:
            if self.dimmed:
                panel.feedback(button_id, ok, wake=False)
            else:
                panel.feedback(button_id, ok)

    @contextlib.contextmanager
    def input_turn(self):
        """Hold input_lock. When slow typing holds it, wait with state_lock released.

        Otherwise the worker would hold the state lock for minutes, and the main loop, reconnects,
        slow keys and every queued press would wait behind it.
        """
        if not self.input_lock.acquire(blocking=False):
            with self.state_lock.suspended():
                self.input_lock.acquire()
        try:
            yield
        finally:
            self.input_lock.release()

    def is_slow(self, button_id, hold, double=False):
        button = next((b for b in self.effective_buttons() if b['id'] == button_id), None)
        if button is None:
            return False
        return self.waits(self.resolved_button(button).get(action_list_name(hold, double), []))

    def waits(self, actions, depth=0):
        """Whether the list waits (shell, HTTP, delay, slow typing), following presses of other keys."""
        for action in actions:
            if action.get('type') in BLOCKING_ACTIONS or (action.get('type') == 'text' and action.get('delay_ms')):
                return True
            if action.get('type') == 'press' and depth < 8:  # depth: a loop of presses is refused when it runs
                target = next((b for b in self.effective_buttons() if b['id'] == action.get('id')), None)
                if target and self.waits(self.resolved_button(target).get('actions', []), depth + 1):
                    return True
        return False

    def start_press(self, button_id, hold=False, double=False):
        """Run a press now, or on the slow lane when it waits (shell, HTTP, delay) so other keys keep working.

        A button that is still running ignores further presses instead of running twice.
        """
        if not self.is_slow(button_id, hold, double):
            return self.dispatch_press(button_id, hold=hold, double=double)
        identity = (self.profile, self.page, button_id)
        with self.slow_lock:
            running = identity in self.slow_running
            claimed = not running and self.slow_slots.acquire(blocking=False)
            if claimed:
                self.slow_running.add(identity)
        if not claimed:
            self.log(f'Button {button_id} is still running or the slow lane is full; press ignored')
            self.give_feedback(button_id, False)
            return False
        threading.Thread(target=self.run_slow_press, args=(button_id, hold, identity, double),
                         name=f'slow-button-{button_id}', daemon=True).start()
        return True

    def run_slow_press(self, button_id, hold, identity, double=False):
        try:
            with self.state_lock:
                # The worker may have changed page before this thread got the lock: the id now names another key
                if (self.profile, self.page) != identity[:2]:
                    self.log(f'Button {button_id} did not run: the page changed before it started')
                    self.give_feedback(button_id, False)
                    return
                self.dispatch_press(button_id, hold=hold, double=double)
        except Exception as exc:
            self.log(f'Action failed: {exc}')
        finally:
            with self.slow_lock:
                self.slow_running.discard(identity)
            self.slow_slots.release()

    def start_actions(self, actions):
        """Trigger and timer actions: a list that waits (shell, HTTP, delay) runs on the slow lane, like a slow key.

        Otherwise one slow trigger would hold up every key press behind it. A list that is still running is skipped.
        """
        if not self.waits(actions):
            for action in actions:
                self.run_action(action)
            return
        identity = ('actions', json.dumps(actions, sort_keys=True))
        with self.slow_lock:
            claimed = identity not in self.slow_running and self.slow_slots.acquire(blocking=False)
            if claimed:
                self.slow_running.add(identity)
        if not claimed:
            self.log('A trigger is still running or the slow lane is full; this run was skipped')
            return
        threading.Thread(target=self.run_slow_actions, args=(actions, identity), name='slow-actions', daemon=True).start()

    def run_slow_actions(self, actions, identity):
        try:
            with self.state_lock:
                for action in actions:
                    if self.stop.is_set():
                        break
                    self.run_action(action)
        except Exception as exc:
            self.log(f'Action failed: {exc}')
        finally:
            with self.slow_lock:
                self.slow_running.discard(identity)
            self.slow_slots.release()

    def dispatch_press(self, button_id, hold=False, double=False):
        identity = (self.profile, self.page, button_id)
        if identity in self.active_press or len(self.active_press) >= 16:
            raise ValueError('Circular button action')
        buttons = self.effective_buttons()
        button = next((b for b in buttons if b['id'] == button_id), None)
        if button is None:
            self.last_action = {'id': button_id, 'label': 'Unknown button', 'ok': False,
                                'error': 'The button does not exist on the active page', 'at': time.time()}
            self.give_feedback(button_id, False)
            self.publish_runtime(True, force=True)
            return False
        if not self.active_press:
            self.state_set_by_action.clear()
        state_key = self.state_key(button)
        resolved = self.resolved_button(button)
        actions = resolved.get(action_list_name(hold, double), [])
        # Home Assistant steps run on the panel. When the list holds nothing else, the panel flashes the result.
        panel_ready = self.panel_supports_ha()
        panel_feedback = panel_ready and not self.active_press and ha_keys.only_panel_steps(actions)
        self.active_press.append(identity)
        ok, error = False, ''
        try:
            self.log(f'Button {button_id}: {button["label"]}' + (' (hold)' if hold else ' (double)' if double else ''))
            for action in actions:
                if self.stop.is_set():
                    raise RuntimeError('Stopping')
                self.run_action(action)
            if ha_keys.steps_of(actions) and not panel_ready:
                raise RuntimeError(ha_keys.UNSUPPORTED)
            if (button.get('states') and not hold and not double and not button.get('bind')
                    and state_key not in self.state_set_by_action):
                self.button_states[state_key] = (self.button_states.get(state_key, 0) + 1) % len(button['states'])
                self.push_page()
            ok = True
        except Exception as exc:
            error = str(exc)[:180]
            self.log(f'Action failed: {exc}')
        finally:
            self.active_press.pop()
            self.last_action = {'id': button_id, 'label': button['label'], 'ok': ok,
                                'error': error or None, 'at': time.time()}
            self.events.add('press', button=button_id, label=button['label'], profile=self.profile, page=self.page,
                            ok=ok, hold=hold, double=double)
            try:
                if not panel_feedback:
                    self.give_feedback(button_id, ok)
            finally:
                self.publish_runtime(True, force=True)
        return ok

    def tap_with_double(self, button_id, at=None):
        """A tap on a key with double_actions: a second tap in time runs them, otherwise the single actions run late.

        at is when the panel sent the tap. A busy worker can handle two taps made seconds apart back to back,
        so the gap is measured between the taps, not between handling them.
        """
        at = time.monotonic() if at is None else at
        identity = (self.profile, self.page, button_id)
        pending = self.pending_single.pop(identity, None)
        if pending is not None:
            if at - pending[1] <= DOUBLE_PRESS_SECONDS:
                self.start_press(button_id, double=True)
                return
            self.start_press(button_id)  # too far apart: the first tap was a single tap, and this one starts over
        token = next(self.single_tokens)
        self.pending_single[identity] = (token, at)
        self.schedule_job(('single-due', identity, token), DOUBLE_PRESS_SECONDS)
